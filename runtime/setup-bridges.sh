#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
venv_dir="${repo_root}/.venv"

python3 -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --disable-pip-version-check \
    -r "${repo_root}/bridges/requirements.txt"

printf 'bridge Python environment prepared in %s\n' "${venv_dir}"
