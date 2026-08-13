#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pid_file="${repo_root}/runtime/pids/HistoryData.pid"

[[ -f "${pid_file}" ]] || exit 0
history_pid=$(<"${pid_file}")
if kill -0 "${history_pid}" 2>/dev/null; then
    kill "${history_pid}"
    for _ in {1..50}; do
        kill -0 "${history_pid}" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "${history_pid}" 2>/dev/null; then
        kill -KILL "${history_pid}"
    fi
    printf 'stopped HistoryData    PID %s\n' "${history_pid}"
fi
rm -f "${pid_file}"
