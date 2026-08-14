#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="${repo_root}/runtime/config/HistoryData.env"
if [[ ! -f "${config}" ]]; then
    printf 'missing %s; run ./runtime/prepare.sh and configure ClickHouse credentials\n' "${config}" >&2
    exit 1
fi
set -a
source "${config}"
set +a
cd "${repo_root}"
exec "${repo_root}/.auth-venv/bin/python" -m BacktestService.cli "$@"
