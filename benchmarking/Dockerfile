FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app:/opt
COPY workers/pyproject.toml /tmp/workers-pyproject.toml
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://security.debian.org|https://security.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' \
      > /etc/apt/apt.conf.d/80-retries; \
    i=0; \
    until apt-get update; do \
      i=$((i + 1)); \
      [ "$i" -ge 5 ] && exit 1; \
      sleep $((i * 5)); \
    done; \
    apt-get install -y --no-install-recommends fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -c "import tomllib, subprocess; spec=tomllib.load(open('/tmp/workers-pyproject.toml','rb'))['project']; subprocess.check_call(['pip','install','--no-cache-dir',*spec['dependencies']])" \
    && pip install --no-cache-dir "fonttools>=4.50.0"
COPY benchmarking /app/benchmarking
CMD ["celery", "-A", "benchmarking.celery_app", "worker", "-Q", "benchmark", "-n", "benchmark@%h", "-l", "info"]
