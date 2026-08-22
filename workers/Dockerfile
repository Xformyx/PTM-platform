FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app:/opt

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Layer: Python dependencies ──────────────────────────────────────────────
# Copy only the project spec first so this expensive pip install layer is
# cached and only re-runs when pyproject.toml changes, not when source changes.
#
# The dev extra (pytest) is installed by default because this image is the
# canonical numeric environment for the research regression suites: scipy is
# present here, so NNLS takes the `scipy.optimize.nnls` path that the locked
# numbers were produced with.  A host interpreter without scipy silently falls
# back to a different solver and cannot reproduce them.  Locked numbers that no
# environment can check are not locked.  Build with
# `--build-arg INSTALL_DEV_DEPS=false` for a lean production image.
ARG INSTALL_DEV_DEPS=true
COPY workers/pyproject.toml ./
COPY ptm_shared /opt/ptm_shared
RUN INSTALL_DEV_DEPS="$INSTALL_DEV_DEPS" python3 -c "\
import os, tomllib, subprocess, sys; \
spec = tomllib.load(open('pyproject.toml','rb'))['project']; \
deps = list(spec['dependencies']); \
deps += spec.get('optional-dependencies', {}).get('dev', []) \
    if os.environ['INSTALL_DEV_DEPS'].lower() in ('1', 'true', 'yes') else []; \
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + deps)"

# ── Layer: Source code ───────────────────────────────────────────────────────
# Changes here do NOT invalidate the pip layer above.
COPY workers .
RUN pip install --no-cache-dir --no-deps .

CMD ["celery", "-A", "celery_app", "worker", "-l", "info"]
