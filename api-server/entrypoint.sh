#!/bin/sh
set -e
# Reload is noisy on Docker (watchfiles + parent/child stdout); disable in production via UVICORN_RELOAD=false
if [ "${UVICORN_RELOAD:-true}" = "true" ] || [ "${UVICORN_RELOAD:-true}" = "1" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
else
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
