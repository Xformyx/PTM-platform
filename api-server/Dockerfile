FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    xz-utils \
    fontconfig \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    && rm -rf /var/lib/apt/lists/*

# Install Libertinus Serif font for Typst PDF reports
RUN mkdir -p /usr/share/fonts/opentype/libertinus \
    && curl -fsSL -o /tmp/libertinus.tar.xz https://github.com/alerque/libertinus/releases/download/v7.040/Libertinus-7.040.tar.xz \
    && tar -xf /tmp/libertinus.tar.xz -C /tmp \
    && cp /tmp/Libertinus-7.040/static/OTF/*.otf /usr/share/fonts/opentype/libertinus/ \
    && fc-cache -f \
    && rm -rf /tmp/libertinus* /tmp/Libertinus*

# Install Typst for PDF report generation
RUN curl -fsSL -o /tmp/typst.tar.xz https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz \
    && tar -xf /tmp/typst.tar.xz -C /tmp \
    && mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst \
    && chmod +x /usr/local/bin/typst \
    && rm -rf /tmp/typst*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
