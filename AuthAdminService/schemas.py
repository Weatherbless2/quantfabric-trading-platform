"""HTTP request and response contracts for AuthAdminService."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

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


class IdentityCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=256)


class IdentityUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    active: bool | None = None


class IdentityResponse(BaseModel):
    subject: str
    username: str
    display_name: str
    active: bool


class MenuRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = Field(default=None, max_length=64)
    resource: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=64)
    sort_order: int = Field(default=0, ge=0, le=1_000_000)
    enabled: bool = True


class MenuResponse(MenuRequest):
    pass


class AccountGrant(BaseModel):
    subject: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=128)
    account: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)


class AccountGrantResponse(AccountGrant):
    id: int
    active: bool


class AuditQuery(BaseModel):
    actor: str | None = Field(default=None, max_length=128)
    action: str | None = Field(default=None, max_length=64)
    result: str | None = Field(default=None, max_length=16)
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    offset: Annotated[int, Field(ge=0, le=1_000_000)] = 0
