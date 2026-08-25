FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app:/opt
COPY workers/pyproject.toml /tmp/workers-pyproject.toml
RUN python3 -c "import tomllib, subprocess; spec=tomllib.load(open('/tmp/workers-pyproject.toml','rb'))['project']; subprocess.check_call(['pip','install','--no-cache-dir',*spec['dependencies']])"
COPY benchmarking /app/benchmarking
CMD ["celery", "-A", "benchmarking.celery_app", "worker", "-Q", "benchmark", "-n", "benchmark@%h", "-l", "info"]
