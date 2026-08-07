#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin="${repo_root}/.venv/bin/python"

if [[ ! -x "${python_bin}" ]]; then
    printf 'bridge environment is missing; run runtime/setup-bridges.sh first\n' >&2
    exit 1
fi

exec "${python_bin}" "${repo_root}/bridges/market/pytdx_bridge.py" \
    --config "${repo_root}/runtime/config/PyTdxBridge.json" "$@"
