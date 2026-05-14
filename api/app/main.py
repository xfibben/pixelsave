from contextlib import asynccontextmanager
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.downloader import detect_platform
from app.jobs import ensure_schema_compat, get_visible_job_or_404, purge_expired_jobs, require_client_id
from app.models import DownloadJob
from app.queue import get_queue
from app.schemas import CreateJobRequest, HealthResponse, JobListResponse, JobResponse
from app.storage import ensure_bucket, get_object, object_exists


def serialize_job(job: DownloadJob) -> JobResponse:
    download_url = None
    if job.status == "completed":
        download_url = f"/api/v1/jobs/{job.id}/download"

    return JobResponse(
        id=job.id,
        source_url=job.source_url,
        platform=job.platform,
        status=job.status,
        error_message=job.error_message,
        title=job.title,
        filename=job.filename,
        content_type=job.content_type,
        file_size_bytes=job.file_size_bytes,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        download_url=download_url,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with next(get_db()) as db:
        ensure_schema_compat(db)
        purge_expired_jobs(db)
    ensure_bucket()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/v1/jobs", response_model=JobResponse, status_code=201)
def create_job(
    payload: CreateJobRequest,
    client_id: str = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> JobResponse:
    purge_expired_jobs(db)
    job = DownloadJob(
        client_id=client_id,
        source_url=str(payload.url),
        platform=detect_platform(str(payload.url)),
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    queue = get_queue()
    queue.enqueue("app.downloader.process_job", str(job.id), job_id=str(job.id))

    return serialize_job(job)


@app.get("/api/v1/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    client_id: str = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> JobListResponse:
    purge_expired_jobs(db)
    stmt = (
        select(DownloadJob)
        .where(DownloadJob.client_id == client_id)
        .order_by(DownloadJob.created_at.desc())
        .limit(limit)
    )
    jobs = db.scalars(stmt).all()
    return JobListResponse(items=[serialize_job(job) for job in jobs])


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, client_id: str = Depends(require_client_id), db: Session = Depends(get_db)) -> JobResponse:
    purge_expired_jobs(db)
    job = get_visible_job_or_404(db, job_id, client_id)
    return serialize_job(job)


@app.get("/api/v1/jobs/{job_id}/download")
def download_job_file(job_id: UUID, client_id: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    purge_expired_jobs(db)
    job = get_visible_job_or_404(db, job_id, client_id)
    if job.status != "completed" or not job.storage_bucket or not job.storage_object_key or not job.filename:
        raise HTTPException(status_code=409, detail="El archivo aun no esta disponible")
    if not object_exists(job.storage_bucket, job.storage_object_key):
        raise HTTPException(status_code=404, detail="El archivo no existe en storage")

    minio_response = get_object(job.storage_bucket, job.storage_object_key)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(job.filename)}",
    }

    return StreamingResponse(
        minio_response.stream(32 * 1024),
        media_type=job.content_type or "application/octet-stream",
        headers=headers,
    )
