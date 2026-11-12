#!/usr/bin/env bash
# 本地直接跑（不用 Docker）
set -e
cd "$(dirname "$0")/app"
exec python3 -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
