"""FastAPI service providing OIDC sessions and Casbin authorization."""

from __future__ import annotations

import secrets
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import casbin
import jwt
from casbin_sqlalchemy_adapter import Adapter
from fastapi import FastAPI, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError
from passlib.context import CryptContext
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .database import AuditEvent, AuthSession, Base, Identity
from .schemas import (
    AuthorizationRequest,
    AuthorizationResponse,
    DevelopmentLoginRequest,
    InternalSessionResponse,
    OidcLoginRequest,
    PolicyRule,
    RoleBinding,
    SessionResponse,
)


PASSWORDS = CryptContext(schemes=["argon2"], deprecated="auto")
MODEL_PATH = Path(__file__).with_name("model.conf")


@dataclass(frozen=True)
class ResolvedSession:
    identity: Identity
    oidc_roles: tuple[str, ...]


class AuthorizationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.validate()
        self.engine = create_engine(settings.database_url, future=True)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.enforcer = casbin.Enforcer(str(MODEL_PATH), Adapter(self.engine))
        self._bootstrap_development_data()

    def _bootstrap_development_data(self) -> None:
        if self.settings.auth_mode != "development":
            return
        if not self.settings.dev_admin_password:
            raise RuntimeError("QF_AUTH_DEV_ADMIN_PASSWORD must be set in development mode")
        with self.session_factory.begin() as db:
            identity = db.scalar(select(Identity).where(Identity.username == self.settings.dev_admin_username))
            if not identity:
                identity = Identity(
                    subject=f"local:{self.settings.dev_admin_username}",
                    username=self.settings.dev_admin_username,
                    display_name="Local Administrator",
                    password_hash=PASSWORDS.hash(self.settings.dev_admin_password),
                )
                db.add(identity)
        actor = f"user:{self.settings.dev_admin_username}"
        domain = self.settings.default_domain
        changed = False
        changed |= self.enforcer.add_grouping_policy(actor, "role:admin", domain)
        changed |= self.enforcer.add_policy("role:admin", domain, "*", "*")
        if changed:
            self.enforcer.save_policy()

    def audit(self, db: Session, actor: str, action: str, resource: str, domain: str,
              result: str, trace_id: str = "", detail: dict | None = None) -> None:
        db.add(AuditEvent(actor=actor, action=action, resource=resource, domain=domain,
                          result=result, trace_id=trace_id or None, detail=detail or {}))

    def create_development_session(self, request: DevelopmentLoginRequest) -> SessionResponse:
        if self.settings.auth_mode != "development":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="development login is disabled")
        with self.session_factory.begin() as db:
            identity = db.scalar(select(Identity).where(Identity.username == request.username))
            if not identity or not identity.active or not identity.password_hash or not PASSWORDS.verify(request.password, identity.password_hash):
                self.audit(db, f"user:{request.username}", "session:create", "session", self.settings.default_domain, "DENY")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
            return self._create_session(db, identity, "development")

    def create_oidc_session(self, request: OidcLoginRequest) -> SessionResponse:
        if not self.settings.oidc_issuer:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OIDC is not configured")
        try:
            jwks = PyJWKClient(f"{self.settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs")
            signing_key = jwks.get_signing_key_from_jwt(request.access_token)
            claims = jwt.decode(request.access_token, signing_key.key, algorithms=["RS256"],
                                audience=self.settings.oidc_audience, issuer=self.settings.oidc_issuer)
        except (jwt.PyJWTError, PyJWKClientError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid OIDC token") from exc
        subject = str(claims["sub"])
        username = str(claims.get("preferred_username", subject))
        with self.session_factory.begin() as db:
            identity = db.scalar(select(Identity).where(Identity.subject == subject))
            if not identity:
                identity = Identity(subject=subject, username=username, display_name=str(claims.get("name", username)))
                db.add(identity)
                db.flush()
            if not identity.active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="identity is disabled")
            return self._create_session(db, identity, "oidc", self._oidc_roles(claims))

    @staticmethod
    def _oidc_roles(claims: dict) -> tuple[str, ...]:
        realm_access = claims.get("realm_access", {})
        raw_roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
        if not isinstance(raw_roles, list):
            return ()
        return tuple(sorted({f"role:{role}" for role in raw_roles
                             if isinstance(role, str) and re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", role)}))

    def _create_session(self, db: Session, identity: Identity, auth_method: str,
                        oidc_roles: tuple[str, ...] = ()) -> SessionResponse:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds)
        # UUID is a char[32] field in the fixed-layout C++ packet. 30 hex
        # characters leave room for its terminating NUL byte at every hop.
        session = AuthSession(id=secrets.token_hex(15), identity_id=identity.id,
                              auth_method=auth_method, roles=list(oidc_roles), expires_at=expires_at)
        db.add(session)
        actor = f"user:{identity.username}"
        self.audit(db, actor, "session:create", "session", self.settings.default_domain, "ALLOW")
        return SessionResponse(session_id=session.id, actor=actor, expires_at=expires_at)

    def resolve_session(self, session_id: str) -> tuple[ResolvedSession | None, str]:
        with self.session_factory() as db:
            session = db.get(AuthSession, session_id)
            expires_at = session.expires_at if session else None
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if not session or session.revoked_at or expires_at <= datetime.now(UTC):
                return None, "session is invalid, revoked, or expired"
            identity = db.get(Identity, session.identity_id)
            if not identity or not identity.active:
                return None, "identity is disabled"
            db.expunge(identity)
            roles = tuple(role for role in (session.roles or []) if isinstance(role, str))
            return ResolvedSession(identity=identity, oidc_roles=roles), ""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        resolved, reason = self.resolve_session(request.session_id)
        actor = f"user:{resolved.identity.username}" if resolved else "anonymous"
        subjects = (actor, *(resolved.oidc_roles if resolved else ()))
        allowed = bool(resolved and any(
            self.enforcer.enforce(subject, request.domain, request.resource, request.action)
            for subject in subjects
        ))
        with self.session_factory.begin() as db:
            self.audit(db, actor, request.action, request.resource, request.domain,
                       "ALLOW" if allowed else "DENY", request.trace_id,
                       {"reason": reason if not allowed else "", "subjects": list(subjects)})
        return AuthorizationResponse(allowed=allowed, actor=actor,
                                     reason="" if allowed else (reason or "policy denied"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    service = AuthorizationService(settings)
    app = FastAPI(title="QuantFabric AuthAdminService", version="0.1.0")

    def require_internal_key(value: str | None) -> None:
        if not settings.internal_key or not value or not secrets.compare_digest(value, settings.internal_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal service key")

    @app.get("/healthz")
    def health() -> dict:
        return {"status": "ok", "mode": settings.auth_mode}

    @app.post("/v1/sessions/development", response_model=SessionResponse)
    def development_login(request: DevelopmentLoginRequest) -> SessionResponse:
        return service.create_development_session(request)

    @app.post("/v1/sessions/oidc", response_model=SessionResponse)
    def oidc_login(request: OidcLoginRequest) -> SessionResponse:
        return service.create_oidc_session(request)

    @app.get("/v1/internal/sessions/{session_id}", response_model=InternalSessionResponse)
    def internal_session(session_id: str, x_qf_internal_key: str | None = Header(default=None)) -> InternalSessionResponse:
        require_internal_key(x_qf_internal_key)
        resolved, reason = service.resolve_session(session_id)
        if not resolved:
            return InternalSessionResponse(active=False, reason=reason)
        return InternalSessionResponse(active=True, actor=f"user:{resolved.identity.username}",
                                       username=resolved.identity.username, domain=settings.default_domain)

    @app.post("/v1/internal/authorize", response_model=AuthorizationResponse)
    def internal_authorize(request: AuthorizationRequest,
                           x_qf_internal_key: str | None = Header(default=None)) -> AuthorizationResponse:
        require_internal_key(x_qf_internal_key)
        return service.authorize(request)

    @app.post("/v1/admin/policies")
    def add_policy(request: PolicyRule, session_id: str = Header(alias="X-QF-Session-ID")) -> dict:
        decision = service.authorize(AuthorizationRequest(session_id=session_id, domain=settings.default_domain,
                                                           resource="auth/policy", action="policy:write"))
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
        changed = service.enforcer.add_policy(request.subject, request.domain, request.resource, request.action)
        if changed:
            service.enforcer.save_policy()
        return {"changed": changed}

    @app.delete("/v1/admin/policies")
    def remove_policy(request: PolicyRule, session_id: str = Header(alias="X-QF-Session-ID")) -> dict:
        decision = service.authorize(AuthorizationRequest(session_id=session_id, domain=settings.default_domain,
                                                           resource="auth/policy", action="policy:write"))
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
        changed = service.enforcer.remove_policy(request.subject, request.domain, request.resource, request.action)
        if changed:
            service.enforcer.save_policy()
        return {"changed": changed}

    @app.get("/v1/admin/policies")
    def list_policies(session_id: str = Header(alias="X-QF-Session-ID")) -> dict:
        decision = service.authorize(AuthorizationRequest(session_id=session_id, domain=settings.default_domain,
                                                           resource="auth/policy", action="policy:read"))
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
        return {"items": service.enforcer.get_policy()}

    @app.post("/v1/admin/role-bindings")
    def add_role_binding(request: RoleBinding, session_id: str = Header(alias="X-QF-Session-ID")) -> dict:
        decision = service.authorize(AuthorizationRequest(session_id=session_id, domain=settings.default_domain,
                                                           resource="auth/policy", action="policy:write"))
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
        changed = service.enforcer.add_grouping_policy(request.subject, request.role, request.domain)
        if changed:
            service.enforcer.save_policy()
        return {"changed": changed}

    @app.delete("/v1/admin/role-bindings")
    def remove_role_binding(request: RoleBinding, session_id: str = Header(alias="X-QF-Session-ID")) -> dict:
        decision = service.authorize(AuthorizationRequest(session_id=session_id, domain=settings.default_domain,
                                                           resource="auth/policy", action="policy:write"))
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
        changed = service.enforcer.remove_grouping_policy(request.subject, request.role, request.domain)
        if changed:
            service.enforcer.save_policy()
        return {"changed": changed}

    @app.get("/v1/admin/role-bindings")
    def list_role_bindings(session_id: str = Header(alias="X-QF-Session-ID")) -> dict:
        decision = service.authorize(AuthorizationRequest(session_id=session_id, domain=settings.default_domain,
                                                           resource="auth/policy", action="policy:read"))
        if not decision.allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
        return {"items": service.enforcer.get_grouping_policy()}

    return app
