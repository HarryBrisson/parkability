#!/usr/bin/env bash
# Refresh parkability artifacts: fetch parking + permit-zone data, roll up by geography.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest -q
python3 -m parkability "$@"
echo
echo "Artifacts written to data/processed/ :"
ls -1 data/processed/
