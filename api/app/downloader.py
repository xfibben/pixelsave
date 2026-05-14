import mimetypes
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import DownloadJob
from app.storage import ensure_bucket, upload_file


def detect_platform(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    hostname = hostname.lower()
    if "instagram.com" in hostname:
        return "instagram"
    if "facebook.com" in hostname or "fb.watch" in hostname:
        return "facebook"
    if "x.com" in hostname or "twitter.com" in hostname:
        return "x"
    if "tiktok.com" in hostname:
        return "tiktok"
    if "youtube.com" in hostname or "youtu.be" in hostname:
        return "youtube"
    return "generic"


def _extract_downloaded_file(output: str) -> Path:
    for line in reversed(output.splitlines()):
        candidate = Path(line.strip())
        if candidate.exists():
            return candidate
    raise RuntimeError("yt-dlp no reporto el archivo final")


def _guess_content_type(file_path: Path) -> str:
    content_type, _ = mimetypes.guess_type(file_path.name)
    return content_type or "application/octet-stream"


def _set_job_status(db: Session, job: DownloadJob, status: str, error_message: str | None = None) -> None:
    job.status = status
    job.error_message = error_message
    if status == "processing" and job.started_at is None:
        job.started_at = datetime.now(UTC)
    if status in {"completed", "failed"}:
        job.completed_at = datetime.now(UTC)
    db.add(job)
    db.commit()
    db.refresh(job)


def process_job(job_id: str) -> None:
    settings = get_settings()
    ensure_bucket()

    db = SessionLocal()
    job_uuid = UUID(job_id)
    try:
        job = db.get(DownloadJob, job_uuid)
        if job is None:
            raise RuntimeError(f"Job {job_id} no existe")

        _set_job_status(db, job, "processing")

        with TemporaryDirectory(prefix=f"pixelsave-{job_id}-") as temp_dir:
            temp_path = Path(temp_dir)
            output_template = temp_path / "%(title).120B-%(id)s.%(ext)s"
            command = [
                "yt-dlp",
                "--no-playlist",
                "--restrict-filenames",
                "--newline",
                "--print",
                "after_move:filepath",
                "--merge-output-format",
                "mp4",
                "-o",
                str(output_template),
                job.source_url,
            ]

            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=settings.yt_dlp_timeout_seconds,
            )

            combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part)
            if result.returncode != 0:
                raise RuntimeError(combined_output.strip() or "yt-dlp fallo sin devolver error legible")

            downloaded_file = _extract_downloaded_file(combined_output)
            if not downloaded_file.exists():
                raise RuntimeError("El archivo descargado no existe despues de yt-dlp")

            object_key = f"{job.id}/{downloaded_file.name}"
            content_type = _guess_content_type(downloaded_file)
            file_size = upload_file(str(downloaded_file), object_key, content_type=content_type)

            job.title = downloaded_file.stem
            job.filename = downloaded_file.name
            job.content_type = content_type
            job.file_size_bytes = file_size
            job.storage_bucket = settings.storage_bucket
            job.storage_object_key = object_key
            _set_job_status(db, job, "completed")
    except Exception as exc:
        db.rollback()
        job = db.get(DownloadJob, job_uuid)
        if job is not None:
            _set_job_status(db, job, "failed", str(exc))
        raise
    finally:
        db.close()
