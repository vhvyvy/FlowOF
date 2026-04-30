#!/usr/bin/env sh
set -eu

cd backend
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
