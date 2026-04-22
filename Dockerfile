# PanoWan local Docker service
# Generates 360 panoramic videos from text prompts over HTTP

FROM nvidia/cuda:12.2.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Clone PanoWan
RUN git clone https://github.com/VariantConst/PanoWan.git

# Install uv and PanoWan dependencies
WORKDIR /app/PanoWan
RUN python3 -m pip install --no-cache-dir --upgrade pip && \
    python3 -m pip install --no-cache-dir uv fastapi "uvicorn[standard]" && \
    bash ./scripts/install-uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv sync

ENV PATH="/root/.local/bin:${PATH}"

# Copy application code
WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts

EXPOSE 8000

# Start the local HTTP service
CMD ["bash", "/app/scripts/start-local.sh"]
