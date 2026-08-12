#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
config_dir="${repo_root}/runtime/config"

mkdir -p "${repo_root}/runtime/data" "${repo_root}/runtime/log" "${repo_root}/runtime/pids"
cp "${repo_root}/XServer/XServer.db" "${config_dir}/XServer.db"
cp "${repo_root}/XRiskJudge/XRiskJudge.db" "${config_dir}/XRiskJudge.db"

sqlite3 "${config_dir}/XServer.db" <<'SQL'
UPDATE UserPermissionTable
SET Plugins='Market|OrderManager|EventLog|Monitor|RiskJudge|FutureAnalysis|StockAnalysis|Permission',
    Messages='FutureMarket|StockMarket|SpotMarket|OrderStatus|AccountFund|AccountPosition|EventLog|ColoStatus|AppStatus|RiskReport'
WHERE UserName='admin';
SQL

auth_env="${config_dir}/AuthAdmin.env"
if [[ ! -f "${auth_env}" ]]; then
    # This file is local runtime state and is ignored by Git. XServer and the
    # authorization service must share this key; it is never stored in source.
    auth_key=$(od -An -N 32 -tx1 /dev/urandom | tr -d ' \n')
    umask 077
    cat >"${auth_env}" <<EOF
QF_AUTH_DATABASE_URL=sqlite:///${repo_root}/runtime/data/auth_admin.db
QF_AUTH_INTERNAL_KEY=${auth_key}
QF_AUTH_MODE=development
QF_AUTH_DEFAULT_DOMAIN=desk:cn_equity
QF_AUTH_SESSION_TTL_SECONDS=900
QF_AUTH_DEV_ADMIN_USERNAME=admin
QF_AUTH_DEV_ADMIN_PASSWORD=123456
QF_AUTH_DEV_ACCOUNT=610000071840
EOF
fi
chmod 600 "${auth_env}"

business_env="${config_dir}/BusinessAdmin.env"
if [[ ! -f "${business_env}" ]]; then
    # This remains independent of the trading runtime. Teams may replace this
    # local SQLite URL with the dedicated PostgreSQL control-plane database.
    umask 077
    cat >"${business_env}" <<EOF
QF_BUSINESS_DATABASE_URL=sqlite:///${repo_root}/runtime/data/business_admin.db
QF_BUSINESS_AUTH_URL=http://127.0.0.1:18080
QF_BUSINESS_DOMAIN=desk:cn_equity
EOF
fi
chmod 600 "${business_env}"

# runtime/config is local state. Keep the checked-in XServer sample as the
# source of truth, then make its paths and control-plane switch explicit for
# the local process. The policy is off by default so an empty development
# database cannot change the existing simulated trading chain.
cat >"${config_dir}/XServer.yml" <<EOF
XServerConfig:
  ServerIP: 127.0.0.1
  Port: 8000
  OpenTime: 00:00:00.000
  CloseTime: 23:59:59.999
  SnapShot: false
  BinPath: ${repo_root}/runtime/data
  UserDBPath: ${config_dir}/XServer.db
  AppCheckTime: 23:58:00.000
  AppStatusStoreTime: 23:59:00.000
  Authorization:
    Enabled: true
    ServiceURL: http://127.0.0.1:18080
    TimeoutMs: 1000
    Domain: desk:cn_equity
  BusinessPolicy:
    Enabled: ${QF_BUSINESS_POLICY_ENABLED:-false}
    ServiceURL: ${QF_BUSINESS_POLICY_URL:-http://127.0.0.1:19080}
    TimeoutMs: ${QF_BUSINESS_POLICY_TIMEOUT_MS:-1000}
    RefreshSeconds: ${QF_BUSINESS_POLICY_REFRESH_SECONDS:-60}
EOF

printf 'runtime configuration prepared in %s\n' "${config_dir}"
