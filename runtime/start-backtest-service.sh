#!/usr/bin/env bash
set -euo pipefail

# Keep historical research separate from the ATP trading runtime: a slow
# ClickHouse query must never block market, risk, or order processes.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_dir="${repo_root}/runtime"
config_dir="${runtime_dir}/config"
log_dir="${runtime_dir}/log"
pid_dir="${runtime_dir}/pids"
history_env="${config_dir}/HistoryData.env"
auth_env="${config_dir}/AuthAdmin.env"
pid_file="${pid_dir}/Backtest.pid"

if [[ ! -x "${repo_root}/.auth-venv/bin/python" ]]; then
    printf 'Python environment is missing; install AuthAdminService/requirements.txt first\n' >&2
    exit 1
fi
if [[ ! -f "${history_env}" || ! -f "${auth_env}" ]]; then
    printf 'Missing historical or authorization configuration; run runtime/prepare.sh first\n' >&2
    exit 1
fi

set -a
source "${auth_env}"
source "${history_env}"
set +a

mkdir -p "${log_dir}" "${pid_dir}"
if [[ -f "${pid_file}" ]] && kill -0 "$(<"${pid_file}")" 2>/dev/null; then
    printf 'BacktestService is already running (PID %s)\n' "$(<"${pid_file}")"
    exit 0
fi
rm -f "${pid_file}"
env "PYTHONPATH=${repo_root}" "${repo_root}/.auth-venv/bin/python" -m uvicorn \
    BacktestService.app:app --host 127.0.0.1 --port 18082 \
    >"${log_dir}/BacktestService.stdout.log" 2>&1 &
printf '%s\n' "$!" >"${pid_file}"

for _ in {1..100}; do
    if curl --fail --silent http://127.0.0.1:18082/readyz >/dev/null 2>&1; then
        printf 'BacktestService is ready: http://127.0.0.1:18082/\n'
        exit 0
    fi
    if ! kill -0 "$(<"${pid_file}")" 2>/dev/null; then
        printf 'BacktestService exited; see %s\n' "${log_dir}/BacktestService.stdout.log" >&2
        exit 1
    fi
    sleep 0.1
done
printf 'BacktestService did not become ready; see %s\n' "${log_dir}/BacktestService.stdout.log" >&2
exit 1
