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

printf 'runtime configuration prepared in %s\n' "${config_dir}"
