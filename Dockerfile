# PanoWan local Docker service
# Generates 360 panoramic videos from text prompts over HTTP

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    vmtouch \
    && rm -rf /var/lib/apt/lists/*

# Clone PanoWan
RUN git clone https://github.com/VariantConst/PanoWan.git

# Install uv and PanoWan dependencies
WORKDIR /app/PanoWan
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/uv \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install uv fastapi "uvicorn[standard]" sse-starlette && \
    bash ./scripts/install-uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv sync

ENV PATH="/root/.local/bin:${PATH}"

# Copy application code
WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts

# Create upscale model directory
RUN mkdir -p /app/data/models/upscale

EXPOSE 8000

# Start the local HTTP service
CMD ["bash", "/app/scripts/start-local.sh"]
