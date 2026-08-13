from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    result: dict[str, Any] | None = None
    error: str | None = None
    current_stage: str | None = None
    regenerated_from: str | None = None


# In-memory job store
JOBS: dict[str, Job] = {}
