# PanoWan local Docker service
# Generates 360 panoramic videos from text prompts over HTTP
#
# Dev-mode architecture:
#   docker-compose-dev.yml bind-mounts ./third_party/PanoWan onto /app/PanoWan,
#   replacing the shallow clone baked into the image.  The Python venv lives at
#   /opt/venv (set via UV_PROJECT_ENVIRONMENT), so it is NOT shadowed by the
#   mount.  When start-local.sh runs `uv sync` in DEV_MODE=1, it reuses
#   /opt/venv and only adds missing dev dependencies.
#
# Mirror overrides (optional — leave empty for official sources):
#   make build APT_MIRROR=mirrors.tuna.tsinghua.edu.cn PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
#   make build APT_MIRROR=mirrors.aliyun.com PYPI_INDEX=https://mirrors.aliyun.com/pypi/simple

# ── Stage 1: Build ──────────────────────────────────────────────────────────
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /build

# APT mirror — leave empty for official Ubuntu archives.
# Set to e.g. mirrors.tuna.tsinghua.edu.cn in China.
ARG APT_MIRROR=
RUN if [ -n "${APT_MIRROR}" ]; then \
    sed -i "s|archive.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list \
    && sed -i "s|security.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi

# Install build-time system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Shallow clone — no git history needed at runtime
RUN git clone --depth 1 https://github.com/VariantConst/PanoWan.git

# Install uv and PanoWan Python dependencies.
# UV_PROJECT_ENVIRONMENT places the venv at /opt/venv, independent of the
# source tree so that a dev bind mount on /app/PanoWan won't shadow it.
ARG PYPI_INDEX=
WORKDIR /build/PanoWan
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/uv \
    pip_install_flag="${PYPI_INDEX:+-i ${PYPI_INDEX}}" && \
    python3 -m pip install --upgrade pip $pip_install_flag && \
    python3 -m pip install uv $pip_install_flag && \
    bash ./scripts/install-uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    if [ -n "${PYPI_INDEX}" ]; then export UV_INDEX_URL="${PYPI_INDEX}"; fi && \
    uv sync --no-dev --link-mode=copy

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# UV_PROJECT_ENVIRONMENT ensures `uv sync` (dev mode) also targets /opt/venv,
# so the venv survives the /app/PanoWan bind mount in dev compose.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ARG PYPI_INDEX=
# UV_INDEX_URL persists into runtime for dev-mode uv sync.
# Empty value = use default PyPI; set via --build-arg PYPI_INDEX=... to override.
ENV UV_INDEX_URL=${PYPI_INDEX:-}
ENV PATH="/opt/venv/bin:/root/.local/bin:${PATH}"

WORKDIR /app

# APT mirror — leave empty for official Ubuntu archives.
ARG APT_MIRROR=
RUN if [ -n "${APT_MIRROR}" ]; then \
    sed -i "s|archive.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list \
    && sed -i "s|security.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi

# Runtime dependencies only — no git, pip, or build tools
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
    python3 \
    vmtouch \
    && rm -rf /var/lib/apt/lists/*

# PanoWan source (shallow clone from builder — replaced by bind mount in dev)
COPY --from=builder /build/PanoWan /app/PanoWan
# Python venv with all installed packages
COPY --from=builder /opt/venv /opt/venv
# uv binary + managed Python interpreter (needed by venv and dev-mode uv sync)
COPY --from=builder /root/.local /root/.local

# Application code
COPY app /app/app
COPY scripts /app/scripts

# Create upscale model directory
RUN mkdir -p /app/data/models/upscale

EXPOSE 8000

CMD ["bash", "/app/scripts/start-local.sh"]
