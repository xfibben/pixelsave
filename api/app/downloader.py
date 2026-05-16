import mimetypes
import subprocess
from base64 import b64decode
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


def _resolve_cookies_file(settings, temp_path: Path) -> str | None:
    if settings.yt_dlp_cookies_file:
        return settings.yt_dlp_cookies_file
    if settings.yt_dlp_cookies_text:
        cookies_path = temp_path / "cookies.txt"
        cookies_path.write_text(settings.yt_dlp_cookies_text, encoding="utf-8")
        return str(cookies_path)
    if settings.yt_dlp_cookies_base64:
        cookies_path = temp_path / "cookies.txt"
        decoded = b64decode(settings.yt_dlp_cookies_base64).decode("utf-8")
        cookies_path.write_text(decoded, encoding="utf-8")
        return str(cookies_path)
    return None


def _common_command(output_template: Path, source_url: str, settings, cookies_file: str | None) -> list[str]:
    command = [
        "yt-dlp",
        "--no-playlist",
        "--restrict-filenames",
        "--newline",
        "--print",
        "after_move:filepath",
        "--merge-output-format",
        "mp4",
        "--retries",
        str(settings.yt_dlp_retries),
        "--fragment-retries",
        str(settings.yt_dlp_retries),
        "--extractor-retries",
        str(settings.yt_dlp_retries),
        "--socket-timeout",
        "30",
        "-o",
        str(output_template),
    ]
    if settings.yt_dlp_impersonate:
        command.extend(["--impersonate", settings.yt_dlp_impersonate])
    if cookies_file:
        command.extend(["--cookies", cookies_file])
    if settings.yt_dlp_proxy:
        command.extend(["--proxy", settings.yt_dlp_proxy])
    if settings.yt_dlp_source_address:
        command.extend(["--source-address", settings.yt_dlp_source_address])
    command.append(source_url)
    return command


def _platform_attempts(
    output_template: Path, source_url: str, settings, platform: str, cookies_file: str | None
) -> list[tuple[str, list[str]]]:
    attempts: list[tuple[str, list[str]]] = []

    generic = _common_command(output_template, source_url, settings, cookies_file)
    attempts.append(("generic", generic))

    if platform == "instagram":
        instagram = _common_command(output_template, source_url, settings, cookies_file)
        instagram[-1:-1] = [
            "--add-header",
            "Referer:https://www.instagram.com/",
            "--add-header",
            "Origin:https://www.instagram.com",
            "--add-header",
            f"X-IG-App-ID:{settings.instagram_app_id}",
            "--add-header",
            "Accept-Language:en-US,en;q=0.9",
        ]
        instagram[-1:-1] = [
            "--extractor-args",
            f"instagram:app_id={settings.instagram_app_id}",
        ]
        attempts.insert(0, ("instagram-web", instagram))

    return attempts


def _normalize_failure(platform: str, details: str) -> str:
    normalized = details.lower()
    if platform == "instagram":
        if "login required" in normalized or "requested content is not available" in normalized:
            return (
                "Instagram bloqueo esta descarga para acceso anonimo. "
                "Necesitas configurar cookies validas en YT_DLP_COOKIES_FILE o salir por otra IP/proxy en "
                "YT_DLP_PROXY. Detalle tecnico:\n\n"
                f"{details}"
            )
        if "rate-limit" in normalized or "too many requests" in normalized or "http error 429" in normalized:
            return (
                "Instagram limito temporalmente la IP del servidor. "
                "Prueba con un proxy/IP distinta en YT_DLP_PROXY o espera a que el bloqueo caduque. Detalle tecnico:\n\n"
                f"{details}"
            )
    return details


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
            cookies_file = _resolve_cookies_file(settings, temp_path)
            output_template = temp_path / "%(title).120B-%(id)s.%(ext)s"
            attempts = _platform_attempts(
                output_template, job.source_url, settings, detect_platform(job.source_url), cookies_file
            )
            errors: list[str] = []
            downloaded_file: Path | None = None

            for label, command in attempts:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=settings.yt_dlp_timeout_seconds,
                )
                combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
                if result.returncode == 0:
                    downloaded_file = _extract_downloaded_file(combined_output)
                    break

                errors.append(f"[{label}] {combined_output or 'yt-dlp fallo sin devolver error legible'}")

            if downloaded_file is None:
                details = "\n\n".join(errors) or "yt-dlp fallo sin devolver error legible"
                raise RuntimeError(_normalize_failure(job.platform, details))

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
