#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
atp_lib_dir="${repo_root}/AtpTraderOfGuosen(1)/pylib/linux64"

# ATP 扩展依赖同目录的厂商动态库，必须在 Python 进程启动前设置搜索路径。
export LD_LIBRARY_PATH="${atp_lib_dir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export PYTHONPATH="${atp_lib_dir}${PYTHONPATH:+:${PYTHONPATH}}"

exec python3 "${repo_root}/bridges/atp/atp_readonly.py" \
    --config "${repo_root}/runtime/config/ATPBridge.json" "$@"
