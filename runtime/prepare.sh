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

printf 'runtime configuration prepared in %s\n' "${config_dir}"
