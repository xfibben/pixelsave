from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Header, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DownloadJob
from app.storage import delete_object


def require_client_id(x_client_id: str | None = Header(default=None)) -> str:
    if not x_client_id or not x_client_id.strip():
        raise HTTPException(status_code=400, detail="Falta el identificador del dispositivo")
    return x_client_id.strip()


def ensure_schema_compat(db: Session) -> None:
    db.execute(
        text(
            """
            ALTER TABLE download_jobs
            ADD COLUMN IF NOT EXISTS client_id VARCHAR(128) NOT NULL DEFAULT 'legacy'
            """
        )
    )
    db.commit()


def purge_expired_jobs(db: Session) -> None:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(hours=settings.max_job_age_hours)
    expired_jobs = db.scalars(select(DownloadJob).where(DownloadJob.created_at < cutoff)).all()
    if not expired_jobs:
        return

    for job in expired_jobs:
        if job.storage_bucket and job.storage_object_key:
            delete_object(job.storage_bucket, job.storage_object_key)
        db.delete(job)
    db.commit()


def get_visible_job_or_404(db: Session, job_id: UUID, client_id: str) -> DownloadJob:
    job = db.get(DownloadJob, job_id)
    if job is None or job.client_id != client_id:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job
