#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/opt/node@22/bin:/usr/local/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if [ "$(uname -s)" != "Darwin" ]; then
  echo "이 시작 파일은 macOS용입니다. 테스트 방법은 README.md를 확인하세요."
  exit 1
fi
packages=()
command -v uv >/dev/null 2>&1 || packages+=(uv)
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then packages+=(ffmpeg); fi
command -v deno >/dev/null 2>&1 || packages+=(deno)
command -v tunnel-client >/dev/null 2>&1 || packages+=(openai/tools/tunnel-client)
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  packages+=(node@22)
elif [ "$(node -p 'Number(process.versions.node.split(".")[0]) >= 20')" != 'true' ]; then
  packages+=(node@22)
fi
if [ "${#packages[@]}" -gt 0 ]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "없는 도구: ${packages[*]}. Homebrew 공식 페이지를 엽니다. 설치 후 다시 실행하세요."
    open https://brew.sh
    exit 1
  fi
  echo "없는 도구만 설치합니다: ${packages[*]}"
  brew install "${packages[@]}"
fi
# Recreate a Python environment HERE; never copy or depend on the old .venv.
uv sync --python 3.12
exec .venv/bin/python -m mac_bridge.local start "$@"
