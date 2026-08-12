#!/usr/bin/env bash
set -euo pipefail

# Start the Python control plane without starting the C++ trading services.
# It can safely share the existing local AuthAdminService with the trading
# runtime, but it has its own database, PID and log file.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_dir="${repo_root}/runtime"
config_dir="${runtime_dir}/config"
log_dir="${runtime_dir}/log"
pid_dir="${runtime_dir}/pids"
auth_env="${config_dir}/AuthAdmin.env"
business_env="${config_dir}/BusinessAdmin.env"

if [[ ! -x "${repo_root}/.auth-venv/bin/python" ]]; then
    printf 'Python environment is missing; install AuthAdminService/requirements.txt first\n' >&2
    exit 1
fi

"${runtime_dir}/prepare.sh"
set -a
source "${auth_env}"
source "${business_env}"
set +a
mkdir -p "${log_dir}" "${pid_dir}"

wait_for_http() {
    local url=$1
    for _ in {1..100}; do
        curl --fail --silent "${url}" >/dev/null 2>&1 && return
        sleep 0.1
    done
    return 1
}

auth_pid_file="${pid_dir}/AuthAdmin.pid"
if ! wait_for_http "${QF_BUSINESS_AUTH_URL}/healthz"; then
    if [[ -f "${auth_pid_file}" ]] && ! kill -0 "$(<"${auth_pid_file}")" 2>/dev/null; then
        rm -f "${auth_pid_file}"
    fi
    if [[ ! -f "${auth_pid_file}" ]]; then
        env "PYTHONPATH=${repo_root}" "${repo_root}/.auth-venv/bin/python" -m uvicorn \
            AuthAdminService.app:app --host 127.0.0.1 --port 18080 \
            >"${log_dir}/AuthAdmin.stdout.log" 2>&1 &
        printf '%s\n' "$!" >"${auth_pid_file}"
    fi
    if ! wait_for_http "${QF_BUSINESS_AUTH_URL}/healthz"; then
        printf 'AuthAdminService did not become ready; see %s\n' "${log_dir}/AuthAdmin.stdout.log" >&2
        exit 1
    fi
fi

pid_file="${pid_dir}/BusinessAdmin.pid"
if wait_for_http "http://127.0.0.1:19080/healthz"; then
    printf 'BusinessAdminService is already ready: http://127.0.0.1:19080/\n'
    exit 0
fi
if [[ -f "${pid_file}" ]] && kill -0 "$(<"${pid_file}")" 2>/dev/null; then
    printf 'BusinessAdmin is already running (PID %s)\n' "$(<"${pid_file}")"
    exit 0
fi
rm -f "${pid_file}"
env "PYTHONPATH=${repo_root}" "${repo_root}/.auth-venv/bin/python" -m uvicorn \
    BusinessAdminService.app:app --host 127.0.0.1 --port 19080 \
    >"${log_dir}/BusinessAdmin.stdout.log" 2>&1 &
printf '%s\n' "$!" >"${pid_file}"

if ! wait_for_http "http://127.0.0.1:19080/healthz"; then
    printf 'BusinessAdminService did not become ready; see %s\n' "${log_dir}/BusinessAdmin.stdout.log" >&2
    exit 1
fi
printf 'BusinessAdminService is ready: http://127.0.0.1:19080/\n'
