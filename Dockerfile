# PanoWan Serverless Worker for RunPod
# Generates 360° panoramic videos from text prompts

FROM runpod/base:0.6.2-cuda12.2.0

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Clone PanoWan
RUN git clone https://github.com/VariantConst/PanoWan.git

# Install uv and PanoWan dependencies
WORKDIR /app/PanoWan
RUN pip install uv && \
    bash ./scripts/install-uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv sync

# Download model weights at build time (baked into the image = no cold start download)
RUN export PATH="$HOME/.local/bin:$PATH" && \
    HF_HUB_ENABLE_HF_TRANSFER=0 bash ./scripts/download-wan.sh ./models/Wan-AI/Wan2.1-T2V-1.3B && \
    bash ./scripts/download-panowan.sh ./models/PanoWan

# Copy handler
WORKDIR /app
COPY handler.py /app/handler.py

# Install runpod SDK
RUN pip install runpod

# Make sure uv is on PATH
ENV PATH="/root/.local/bin:${PATH}"

# Start the serverless handler
CMD ["python", "/app/handler.py"]
