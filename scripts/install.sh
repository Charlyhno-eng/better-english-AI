#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo 'Install uv before running setup.' >&2; exit 1; }
command -v npm >/dev/null || { echo 'Install Node.js 22.12 or newer before running setup.' >&2; exit 1; }

# Native speech dependencies belong to initial installation, not model downloads.
if ! command -v ffmpeg >/dev/null || ! command -v espeak-ng >/dev/null; then
  if command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y ffmpeg espeak-ng
  else
    echo 'This system needs ffmpeg and espeak-ng installed with its package manager.' >&2
    exit 1
  fi
fi

uv sync --directory backend --extra dev --extra stt --extra tts --extra pronunciation --locked
npm ci --prefix frontend
echo 'Installation complete. Start both servers, then open Setup in the web app.'
