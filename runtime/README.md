# QuantFabric Runtime

## Current Scope

This runtime starts the QuantFabric C++ trading core and the lightweight
authorization service. The production desktop applications use a native C++
protocol boundary:

- `VnpyMonitor` is the vn.py Qt trading workbench. Its in-process
  `quantfabric_native` C++ extension connects directly to `XServer` with the
  existing HPSocket and PackMessage protocol; it does not start a bridge process.
- `QtAdmin` will call `AuthAdminService` over HTTP to manage users, menus, and
  account grants.
- `AuthAdminService` provides login, short sessions, and Casbin checks only.
  Redis, Keycloak, and a web frontend are not part of the current scope.
- `pytdx` and ATP remain external market/broker adapters. They are provider
  integrations, not an application-level Python/C++ client layer.

`XMonitor` remains a legacy Fabric monitoring client. The current trading
frontend is `VnpyMonitor`.

## First-time Setup

Run the following commands from the repository root:

```bash
git submodule update --init --recursive

sudo apt-get update
sudo apt-get install -y build-essential cmake curl sqlite3 python3-dev python3-venv \
    qtbase5-dev qt5-qmake

python3 -m venv .auth-venv
.auth-venv/bin/python -m pip install -r AuthAdminService/requirements.txt
python3 -m venv .vnpy-venv
.vnpy-venv/bin/python -m pip install -r VnpyMonitor/requirements.txt
.auth-venv/bin/python -m pip install -r HistoryDataService/requirements.txt

./runtime/setup-bridges.sh
./runtime/prepare.sh
```

`prepare.sh` creates `runtime/config/AuthAdmin.env` with mode `0600`. It
contains the local development authorization secret and is deliberately ignored
by Git.

It also creates the local BusinessAdmin SQLite configuration and rewrites
`runtime/config/XServer.yml`. Business policy admission is disabled by default;
set `QF_BUSINESS_POLICY_ENABLED=true` before `prepare.sh` and `start.sh` only
after a valid published version exists. Use `./runtime/start-business-admin.sh`
to run the Python control plane separately.

## Build

```bash
cmake -S . -B build -DPython3_EXECUTABLE="$PWD/.vnpy-venv/bin/python"
cmake --build build --target \
    XServer_0.9.0 XWatcher_0.6.0 XRiskJudge_0.9.3 XTrader_0.9.3 \
    XMarketCenter_0.9.3 XQuant_0.1.0 QtAdmin_0.1.0 quantfabric_native \
    -j"$(nproc)"
```

## Start and Stop

Start the safe local test chain first:

```bash
./runtime/start.sh test
```

The script starts `AuthAdmin`, `XServer`, `XWatcher`, `XRiskJudge`, `XTrader`,
`XMarketCenter`, and `XQuant`. `AuthAdmin` listens on `127.0.0.1:18080`.
The first `XMarketCenter` start may take up to two minutes while its 256 shared
memory publishing channels are initialized. In `test` mode it publishes local
A-share simulation data and `TestTrader` returns simulated fills; neither
pytdx nor ATP is contacted.

When business policy admission is enabled, XServer loads
`GET /v1/internal/config/published/runtime-policy` with the shared internal key.
The refresh thread swaps only a fully parsed version. Failed refreshes retain the
last accepted version; no published version at startup means fail-closed for
subscriptions, orders and cancellations. The order reference cache built from
`OrderStatus` reports supplies the security context needed to enforce
`cancel_allowed` without changing the existing PackMessage layout.

Start the desktop programs from separate terminals after the test chain is
ready:

```bash
./build/QtAdmin_0.1.0

DISPLAY=:0 .vnpy-venv/bin/python -m VnpyMonitor.app
```

Historical ClickHouse minute bars are intentionally not started by
`runtime/start.sh`: historical data must not make the C++ trading runtime depend
on database credentials or availability. Copy `runtime/config/HistoryData.env.example`
to the Git-ignored `runtime/config/HistoryData.env`, set the local read-only
ClickHouse account, then run `./runtime/start-history-data.sh` and export
`QF_HISTORY_URL=http://127.0.0.1:18081` before launching `VnpyMonitor`. See
[HistoryDataService/README.md](../HistoryDataService/README.md). Without this
variable the workbench remains fully usable with real-time bars only.

When `HistoryDataService` is ready, the BusinessAdmin “行情库状态” page also
shows its read-only coverage summary. `BusinessAdminService` calls the local
history service with the existing internal service key and never receives the
ClickHouse username or password.

Build the `quantfabric_native` extension with the same `.vnpy-venv` Python
interpreter before starting `VnpyMonitor`.

Stop all runtime processes with:

```bash
./runtime/stop.sh
```

Useful verification commands:

```bash
.auth-venv/bin/python -m unittest BusinessAdminService.test_service
cmake --build build --target XServerRuntimePolicyTest -j"$(nproc)"
./build/XServerRuntimePolicyTest
git diff --check
```

## Desktop Client Contract

`VnpyMonitor` obtains a short login session from `AuthAdminService`, then
passes it to its in-process C++ native client for the `XServer` protocol.
`XServer` validates
the session and account permission with `AuthAdminService` before it forwards
market subscriptions, order requests, or cancellation requests to the C++
core.

`QtAdmin` is the source of users and Casbin rules. It does not directly embed
or control the trading workbench: after changing a user's permissions, start a
new VnpyMonitor session with `--user`, `--password`, and `--account` so XServer
can validate the new short session.

The planned implementation order is documented in
`doc/architecture/TargetArchitecture.md`.

## Safety Boundary

Do not use `real-trade` until the broker configuration, account grant, and
order-risk tests have been reviewed. Local vendor SDK files, runtime databases,
logs, generated secrets, and real account data must not be committed.
