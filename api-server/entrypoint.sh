#!/bin/sh
set -e
# Keep BLAS/OpenMP from expanding a single TMM request across every core.
# One-core 100% is still possible; this only prevents accidental all-core
# saturation inside the API process.  Override via env if needed.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
# Reload is noisy on Docker (watchfiles + parent/child stdout); disable in production via UVICORN_RELOAD=false
if [ "${UVICORN_RELOAD:-true}" = "true" ] || [ "${UVICORN_RELOAD:-true}" = "1" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
else
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
