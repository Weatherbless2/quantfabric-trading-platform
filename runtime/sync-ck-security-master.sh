#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"
exec env "PYTHONPATH=${repo_root}${PYTHONPATH:+:${PYTHONPATH}}" \
    "${repo_root}/.auth-venv/bin/python" "${repo_root}/runtime/sync-ck-security-master.py"
