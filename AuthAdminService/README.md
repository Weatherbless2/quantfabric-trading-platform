# AuthAdminService

`AuthAdminService` is QuantFabric's authorization control plane. It uses OIDC
for identity, PyCasbin for resource authorization, PostgreSQL for policy and
audit data, and returns short-lived opaque sessions to the native Qt client.

The C++ trading data path remains `vn.py -> XServer -> XWatcher -> XRiskJudge
-> XTrader`. The service does not forward market data or orders.

## Authorization model

The Casbin model is RBAC with domains. Each decision is evaluated as
`subject + domain + resource + action`.

Resource names retain the ownership hierarchy from the supplied business
tables without adding unsafe foreign keys into an independently deployed
control plane:

- `account/<fundacct>` identifies a `fundacct` account, linked to
  `projectacct` and `fundinfo` through `fundacctlink`.
- `market/<exchange>/instrument/<ticker>` identifies one explicit subscription.
- `colo/<colo_id>`, `risk-limit/<colo_id>`, and `auth/policy` identify colo,
  risk, and permission-management operations.

The principal actions are `account:read`, `order:read`, `order:create`,
`order:cancel`, `market:subscribe`, `risk:update`, `fund:transfer`,
`app:manage`, and `policy:write`. Administrators create the resulting account,
project, or fund scope through Casbin policy rows; the transactional business
tables remain their source of ownership data.

Keycloak realm roles are evaluated as temporary `role:<name>` subjects for the
short session. They are not persisted as user-role bindings, so a removed IdP
role cannot survive a later login. Explicit platform role bindings remain
standard Casbin `g` rules.

## Local development

`runtime/prepare.sh` creates `runtime/config/AuthAdmin.env` with a local-only
administrator password and service key (permissions `0600`). Then start
QuantFabric normally. The gateway exchanges its local credentials for a
30-character opaque session before connecting XServer; that session, not the
password, is placed in the C++ login packet.

```bash
.vnpy-venv/bin/python -m pip install -r AuthAdminService/requirements.txt
./runtime/prepare.sh
./runtime/start.sh test
```

The local administrator is `admin` / `123456`; it exists only in generated
development configuration and must not be exposed beyond the local host.

## Production

Copy `.env.example` to a protected `.env`, set all values, then start the
control-plane services with:

```bash
docker compose -f docker-compose.auth.yml up --build
```

The Compose deployment runs `python -m AuthAdminService.migrate` before the
API container starts. It records applied filenames in `qf_schema_migration`,
so a restart does not re-run an already applied migration. Production must set
`QF_AUTH_MODE=oidc`; development-password login is disabled in that mode.

XServer calls internal endpoints with `QF_AUTH_INTERNAL_KEY`. Before exposing
the service beyond one host, production must protect this service identity and
transport with deployment TLS/mTLS.
