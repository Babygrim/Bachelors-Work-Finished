from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(RegisterRequest):
    pass


class UserResponse(BaseModel):
    id: str
    email: str
    subscription: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    renews_at: datetime | None = None
    payments_enabled: bool = False


class JobResponse(BaseModel):
    job_id: str
    kind: Literal["image", "video"]
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int
    result_url: str | None = None
    error: dict[str, str] | None = None
