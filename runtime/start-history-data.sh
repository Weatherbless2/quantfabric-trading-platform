#!/usr/bin/env bash
set -euo pipefail

# Historical K lines are optional for the trading runtime. Keeping this
# process separate means a ClickHouse outage cannot stop market, risk or order
# services from starting.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_dir="${repo_root}/runtime"
config_dir="${runtime_dir}/config"
log_dir="${runtime_dir}/log"
pid_dir="${runtime_dir}/pids"
history_env="${config_dir}/HistoryData.env"
auth_env="${config_dir}/AuthAdmin.env"
pid_file="${pid_dir}/HistoryData.pid"

if [[ ! -x "${repo_root}/.auth-venv/bin/python" ]]; then
    printf 'Python environment is missing; install HistoryDataService/requirements.txt first\n' >&2
    exit 1
fi
if [[ ! -f "${history_env}" ]]; then
    printf 'Missing %s; copy runtime/config/HistoryData.env.example and set local read-only ClickHouse credentials\n' \
        "${history_env}" >&2
    exit 1
fi
if [[ ! -f "${auth_env}" ]]; then
    printf 'Missing %s; run runtime/prepare.sh first\n' "${auth_env}" >&2
    exit 1
fi

set -a
source "${auth_env}"
source "${history_env}"
set +a
if [[ "${QF_HISTORY_BACKEND:-clickhouse}" == "clickhouse" ]] && \
        [[ -z "${QF_HISTORY_CLICKHOUSE_USERNAME:-}" || -z "${QF_HISTORY_CLICKHOUSE_PASSWORD:-}" ]]; then
    printf 'QF_HISTORY_CLICKHOUSE_USERNAME and QF_HISTORY_CLICKHOUSE_PASSWORD must be set in %s\n' \
        "${history_env}" >&2
    exit 1
fi

mkdir -p "${log_dir}" "${pid_dir}"
if [[ -f "${pid_file}" ]] && kill -0 "$(<"${pid_file}")" 2>/dev/null; then
    printf 'HistoryDataService is already running (PID %s)\n' "$(<"${pid_file}")"
    exit 0
fi
rm -f "${pid_file}"
env "PYTHONPATH=${repo_root}" "${repo_root}/.auth-venv/bin/python" -m uvicorn \
    HistoryDataService.app:app --host 127.0.0.1 --port 18081 \
    >"${log_dir}/HistoryData.stdout.log" 2>&1 &
printf '%s\n' "$!" >"${pid_file}"

for _ in {1..100}; do
    if curl --fail --silent http://127.0.0.1:18081/readyz >/dev/null 2>&1; then
        printf 'HistoryDataService is ready: http://127.0.0.1:18081/\n'
        exit 0
    fi
    if ! kill -0 "$(<"${pid_file}")" 2>/dev/null; then
        printf 'HistoryDataService exited; see %s\n' "${log_dir}/HistoryData.stdout.log" >&2
        exit 1
    fi
    sleep 0.1
done
printf 'HistoryDataService did not become ready; see %s\n' "${log_dir}/HistoryData.stdout.log" >&2
exit 1
