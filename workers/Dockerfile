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
COPY workers/pyproject.toml ./
COPY ptm_shared /opt/ptm_shared
RUN python3 -c "\
import tomllib, subprocess, sys; \
deps = tomllib.loads(open('pyproject.toml','rb').read())['project']['dependencies']; \
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + deps)"

# ── Layer: Source code ───────────────────────────────────────────────────────
# Changes here do NOT invalidate the pip layer above.
COPY workers .
RUN pip install --no-cache-dir --no-deps .

CMD ["celery", "-A", "celery_app", "worker", "-l", "info"]
