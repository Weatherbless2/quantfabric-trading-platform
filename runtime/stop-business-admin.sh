#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pid_file="${repo_root}/runtime/pids/BusinessAdmin.pid"

[[ -f "${pid_file}" ]] || exit 0
business_pid=$(<"${pid_file}")
if kill -0 "${business_pid}" 2>/dev/null; then
    kill "${business_pid}"
    for _ in {1..50}; do
        kill -0 "${business_pid}" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "${business_pid}" 2>/dev/null; then
        kill -KILL "${business_pid}"
    fi
    printf 'stopped BusinessAdmin  PID %s\n' "${business_pid}"
fi
rm -f "${pid_file}"
