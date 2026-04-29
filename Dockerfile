# PanoWan Worker product runtime images
# Targets:
#   api                 CPU-only API and Web UI service
#   worker-panowan      GPU worker with PanoWan engine dependencies
#   dev-api             API development target with reload support
#   dev-worker-panowan  Worker development target with mounted engine/source support

FROM ubuntu:22.04 AS runtime-base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:${PATH}"

WORKDIR /app

ARG APT_MIRROR=
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    if [ -n "${APT_MIRROR}" ]; then \
    sed -i "s|archive.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list \
    && sed -i "s|security.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y \
    ffmpeg \
    python3 \
    python3-venv \
    vmtouch \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

FROM runtime-base AS api-deps

ARG PYPI_INDEX=
ENV UV_INDEX_URL=${PYPI_INDEX:-}

COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --link-mode=copy

FROM api-deps AS engine-panowan-deps

FROM engine-panowan-deps AS upscale-realesrgan-deps

ARG PYPI_INDEX=
ENV PIP_INDEX_URL=${PYPI_INDEX:-}

COPY third_party/Upscale/realesrgan/requirements.txt /tmp/upscale-realesrgan-requirements.txt
RUN /opt/venv/bin/python -m venv /opt/venvs/upscale-realesrgan \
    && MAIN_SITE=$(/opt/venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])") \
    && INNER_SITE=$(/opt/venvs/upscale-realesrgan/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])") \
    && printf '%s\n' "$MAIN_SITE" > "$INNER_SITE/panowan_worker_site.pth" \
    && /opt/venvs/upscale-realesrgan/bin/python -m pip install --upgrade pip \
    && /opt/venvs/upscale-realesrgan/bin/python -m pip install -r /tmp/upscale-realesrgan-requirements.txt

FROM api-deps AS api

WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts
RUN mkdir -p /app/runtime
EXPOSE 8000
CMD ["bash", "/app/scripts/start-api.sh"]

FROM engine-panowan-deps AS worker-panowan

WORKDIR /app
COPY --from=upscale-realesrgan-deps /opt/venvs/upscale-realesrgan /opt/venvs/upscale-realesrgan
COPY app /app/app
COPY scripts /app/scripts
COPY third_party/PanoWan /engines/panowan
COPY third_party/Upscale /engines/upscale
RUN mkdir -p /app/runtime /models
EXPOSE 8000
CMD ["bash", "/app/scripts/start-worker.sh"]

FROM api-deps AS dev-api

WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --link-mode=copy
EXPOSE 8000
CMD ["bash", "/app/scripts/start-api.sh"]

FROM engine-panowan-deps AS dev-worker-panowan

WORKDIR /app
COPY --from=upscale-realesrgan-deps /opt/venvs/upscale-realesrgan /opt/venvs/upscale-realesrgan
COPY app /app/app
COPY scripts /app/scripts
COPY third_party/PanoWan /engines/panowan
COPY third_party/Upscale /engines/upscale
CMD ["bash", "/app/scripts/start-worker.sh"]
