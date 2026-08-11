# QuantFabric Runtime

## Current Scope

This runtime starts the QuantFabric C++ trading core and the lightweight
authorization service. The production desktop applications are C++ Qt clients:

- `QtTrader` will connect directly to `XServer` with the existing HPSocket and
  PackMessage protocol.
- `QtAdmin` will call `AuthAdminService` over HTTP to manage users, menus, and
  account grants.
- `AuthAdminService` provides login, short sessions, and Casbin checks only.
  Redis, Keycloak, and a web frontend are not part of the current scope.
- `pytdx` and ATP remain external market/broker adapters. They are provider
  integrations, not an application-level Python/C++ client layer.

The existing `XMonitor` C++ GUI is the reference client for the future
`QtTrader` implementation.

## First-time Setup

Run the following commands from the repository root:

```bash
git submodule update --init --recursive

sudo apt-get update
sudo apt-get install -y build-essential cmake curl sqlite3 python3-venv \
    qtbase5-dev qt5-qmake

python3 -m venv .auth-venv
.auth-venv/bin/python -m pip install -r AuthAdminService/requirements.txt

./runtime/setup-bridges.sh
./runtime/prepare.sh
```

`prepare.sh` creates `runtime/config/AuthAdmin.env` with mode `0600`. It
contains the local development authorization secret and is deliberately ignored
by Git.

## Build

```bash
cmake -S . -B build
cmake --build build --target \
    XServer_0.9.0 XWatcher_0.4.0 XRiskJudge_0.9.3 XTrader_0.9.3 \
    XMarketCenter_0.9.3 XQuant_0.1.0 QtAdmin_0.1.0 \
    -j"$(nproc)"
```

## Start and Stop

Start the safe local test chain first:

```bash
./runtime/start.sh test
```

The script starts `AuthAdmin`, `XServer`, `XWatcher`, `XRiskJudge`, `XTrader`,
`XMarketCenter`, and `XQuant`. `AuthAdmin` listens on `127.0.0.1:18080`.

Stop all runtime processes with:

```bash
./runtime/stop.sh
```

## Desktop Client Contract

`QtTrader` obtains a short login session from `AuthAdminService`, then sends
that session through the C++ client protocol to `XServer`. `XServer` validates
the session and account permission with `AuthAdminService` before it forwards
market subscriptions, order requests, or cancellation requests to the C++
core.

The planned implementation order is documented in
`doc/architecture/TargetArchitecture.md`.

## Safety Boundary

Do not use `real-trade` until the broker configuration, account grant, and
order-risk tests have been reviewed. Local vendor SDK files, runtime databases,
logs, generated secrets, and real account data must not be committed.
