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

# Download Wan base model weights (separate layer for caching)
ENV PATH="/root/.local/bin:${PATH}"
RUN HF_HUB_ENABLE_HF_TRANSFER=0 bash ./scripts/download-wan.sh ./models/Wan-AI/Wan2.1-T2V-1.3B

# Download PanoWan LoRA weights (separate layer + retry on rate limit)
RUN for i in 1 2 3; do \
    bash ./scripts/download-panowan.sh ./models/PanoWan && break || \
    echo "Attempt $i failed, waiting 30s..." && sleep 30; \
    done

# Copy handler
WORKDIR /app
COPY handler.py /app/handler.py

# Install runpod SDK
RUN pip install runpod

# Start the serverless handler
CMD ["python3", "/app/handler.py"]
