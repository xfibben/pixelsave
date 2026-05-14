from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class CreateJobRequest(BaseModel):
    url: HttpUrl


class JobResponse(BaseModel):
    id: UUID
    source_url: str
    platform: str
    status: str
    error_message: str | None
    title: str | None
    filename: str | None
    content_type: str | None
    file_size_bytes: int | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    download_url: str | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]


class HealthResponse(BaseModel):
    status: str

