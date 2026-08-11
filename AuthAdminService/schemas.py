"""HTTP request and response contracts for AuthAdminService."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

SESSION_ID_LENGTH = 30


class DevelopmentLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class OidcLoginRequest(BaseModel):
    access_token: str = Field(min_length=16)


class SessionResponse(BaseModel):
    session_id: str
    actor: str
    expires_at: datetime


class InternalSessionResponse(BaseModel):
    active: bool
    actor: str = ""
    username: str = ""
    domain: str = ""
    reason: str = ""


class AuthorizationRequest(BaseModel):
    # TLoginRequest.UUID reserves one byte for '\\0', leaving at most 31
    # bytes. The service fixes the opaque token at 30 ASCII hex characters.
    session_id: str = Field(min_length=SESSION_ID_LENGTH, max_length=SESSION_ID_LENGTH)
    domain: str = Field(min_length=1, max_length=128)
    resource: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=64)
    trace_id: str = Field(default="", max_length=128)


class AuthorizationResponse(BaseModel):
    allowed: bool
    actor: str
    reason: str = ""


class PolicyRule(BaseModel):
    subject: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=128)
    resource: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=64)


class RoleBinding(BaseModel):
    subject: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=128)
