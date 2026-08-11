#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pid_dir="${repo_root}/runtime/pids"
components=(XQuant XMarketCenter XTrader XRiskJudge XWatcher XServer AuthAdmin PyTdxBridge ATPBridge)
rm -f "${pid_dir}/XVnpyBridge.pid"

for name in "${components[@]}"; do
    pid_file="${pid_dir}/${name}.pid"
    [[ -f "${pid_file}" ]] || continue
    component_pid=$(<"${pid_file}")
    if kill -0 "${component_pid}" 2>/dev/null; then
        kill "${component_pid}"
        for _ in {1..50}; do
            kill -0 "${component_pid}" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "${component_pid}" 2>/dev/null; then
            kill -KILL "${component_pid}"
        fi
        printf 'stopped %-14s PID %s\n' "${name}" "${component_pid}"
    fi
    rm -f "${pid_file}"
done

# These names are fixed by the local test configuration and are safe to remove
# only after all runtime processes above have stopped.
rm -f /dev/shm/MarketServer.shm \
      /dev/shm/OrderServer188795.shm \
      /dev/shm/OrderServer610000071840.shm \
      /dev/shm/RiskServer.shm
