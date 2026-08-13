FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app:/opt

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    xz-utils \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install Libertinus Serif (Latin) + Noto KR subset (Hangul) for Typst PDF reports.
# Subset OTF is much smaller than fonts-noto-cjk and has stable Typst family names.
RUN mkdir -p /usr/share/fonts/opentype/libertinus /usr/share/fonts/opentype/noto-kr \
    && curl -fsSL -o /tmp/libertinus.tar.xz https://github.com/alerque/libertinus/releases/download/v7.040/Libertinus-7.040.tar.xz \
    && tar -xf /tmp/libertinus.tar.xz -C /tmp \
    && cp /tmp/Libertinus-7.040/static/OTF/*.otf /usr/share/fonts/opentype/libertinus/ \
    && curl -fsSL -o /usr/share/fonts/opentype/noto-kr/NotoSansKR-Regular.otf \
         https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-Regular.otf \
    && curl -fsSL -o /usr/share/fonts/opentype/noto-kr/NotoSansKR-Bold.otf \
         https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-Bold.otf \
    && curl -fsSL -o /usr/share/fonts/opentype/noto-kr/NotoSerifKR-Regular.otf \
         https://github.com/notofonts/noto-cjk/raw/main/Serif/SubsetOTF/KR/NotoSerifKR-Regular.otf \
    && curl -fsSL -o /usr/share/fonts/opentype/noto-kr/NotoSerifKR-Bold.otf \
         https://github.com/notofonts/noto-cjk/raw/main/Serif/SubsetOTF/KR/NotoSerifKR-Bold.otf \
    && fc-cache -f \
    && rm -rf /tmp/libertinus* /tmp/Libertinus*

# Install Typst for PDF report generation
RUN curl -fsSL -o /tmp/typst.tar.xz https://github.com/typst/typst/releases/latest/download/typst-x86_64-unknown-linux-musl.tar.xz \
    && tar -xf /tmp/typst.tar.xz -C /tmp \
    && mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst \
    && chmod +x /usr/local/bin/typst \
    && rm -rf /tmp/typst*

COPY api-server/pyproject.toml ./pyproject.toml
COPY api-server/app ./app
RUN pip install --no-cache-dir .

COPY ptm_shared /opt/ptm_shared

COPY api-server/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
