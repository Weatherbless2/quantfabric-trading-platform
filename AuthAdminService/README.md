# AuthAdminService

`AuthAdminService` is the small authorization control plane for the C++ Qt
desktop applications. It provides four capabilities only:

1. Verify a local username and password.
2. Create a short-lived session.
3. Return the menus and accounts available to the signed-in user.
4. Check whether a user may perform an action on an account.

It uses PyCasbin for authorization. Redis, Keycloak, OIDC login, approval
workflows, and a web frontend are outside the current project scope.

The trading path is:

```text
QtTrader -> XServer -> XWatcher -> XRiskJudge -> XTrader
```

`AuthAdminService` does not forward market data or orders. QtTrader obtains a
short session from this service, then connects directly to XServer with the
C++ PackMessage protocol. XServer asks this service to validate the session and
account action before it forwards a sensitive request.

## Authorization Model

Casbin evaluates:

```text
subject + domain + resource + action
```

The initial resources are deliberately small:

- `menu/<menu-id>`: whether a desktop menu is visible.
- `account/<fundacct>`: whether an account can be read or traded.
- `auth/policy`: whether an administrator may change user, menu, or account
  authorization.

The initial actions are `menu:read`, `account:read`, `market:subscribe`,
`order:create`, `order:cancel`, and `policy:write`.

## Local Development

`runtime/prepare.sh` creates `runtime/config/AuthAdmin.env` with a local-only
administrator password and service key. The file has permission `0600` and is
ignored by Git.

```bash
python3 -m venv .auth-venv
.auth-venv/bin/python -m pip install -r AuthAdminService/requirements.txt
./runtime/prepare.sh
./runtime/start.sh test
```

The local administrator is `admin` / `123456`. It is for local development
only and must not be exposed beyond the local host.

## Data Store

The development runtime uses a local SQLite database. When the team deploys
the platform, move the same users, Casbin rules, account grants, and audit logs
to one PostgreSQL instance. This migration is a later deployment task, not a
new permission feature.
