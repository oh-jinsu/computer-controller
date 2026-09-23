#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "먼저 bash Mac-Start.command를 실행하세요."
  exit 1
fi
exec .venv/bin/python -m mac_bridge.local permission
