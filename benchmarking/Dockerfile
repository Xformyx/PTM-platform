FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app:/opt
COPY workers/pyproject.toml /tmp/workers-pyproject.toml
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -c "import tomllib, subprocess; spec=tomllib.load(open('/tmp/workers-pyproject.toml','rb'))['project']; subprocess.check_call(['pip','install','--no-cache-dir',*spec['dependencies']])" \
    && pip install --no-cache-dir "fonttools>=4.50.0"
COPY benchmarking /app/benchmarking
CMD ["celery", "-A", "benchmarking.celery_app", "worker", "-Q", "benchmark", "-n", "benchmark@%h", "-l", "info"]
