#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv 가 설치되어 있지 않습니다. https://docs.astral.sh/uv/ 를 참고하세요." >&2
  exit 1
fi

echo "Generating lock file with uv..."
uv lock
echo "Done. Commit the generated 'uv.lock' file."

