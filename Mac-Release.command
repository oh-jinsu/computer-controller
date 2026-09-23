#!/bin/bash
# Developer release only. End users run Mac Bridge.app; no compiler/keys needed.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/opt/node@22/bin:/usr/local/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export LANG=en_US.UTF-8
# Reuse the developer environment, including in an ordinary Git worktree.
common="$(git rev-parse --path-format=absolute --git-common-dir)"
python=".venv/bin/python"
if [ ! -x "$python" ]; then python="$(dirname "$common")/.venv/bin/python"; fi
if [ ! -x "$python" ]; then
  echo "개발용 Python 환경이 없습니다. 개발 환경을 먼저 준비하세요. 배포 앱 사용자에게는 필요하지 않습니다."
  exit 1
fi
exec "$python" packaging/scripts/release_pipeline.py "$@"
