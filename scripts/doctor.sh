#!/usr/bin/env bash
# scripts/doctor.sh — PanoWan 环境诊断脚本
# 用法: bash scripts/doctor.sh [--autofix]  或  make doctor
set -euo pipefail

AUTOFIX="${1:-}"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_host
panowan_env_tool_defaults

LORA_CHECKPOINT_FILE="${LORA_CHECKPOINT_PATH}"

PASS="✓"
FAIL="✗"
WARN="!"
SECTION="──────────────────────────────────────"

NVIDIA_GPU_FAILED=false

ok()   { echo "  $PASS $*"; }
fail() { echo "  $FAIL $*"; ISSUES=$((ISSUES + 1)); }
warn() { echo "  $WARN $*"; WARNINGS=$((WARNINGS + 1)); }

docker_gpu_access_ok() {
  docker run --rm --gpus all --entrypoint nvidia-smi \
    nvidia/cuda:12.2.0-base-ubuntu22.04 \
    --query-gpu=name --format=csv,noheader &>/dev/null 2>&1
}

maybe_fix_nvidia_runtime() {
  if [[ "$AUTOFIX" == "--autofix" ]]; then
    autofix_nvidia || return 1
  elif [[ -t 0 ]]; then
    echo ""
    read -p "  是否立即尝试自动修复 NVIDIA Container Toolkit？(需要 sudo) [y/N] " -r
    echo ""
    [[ $REPLY =~ ^[Yy]$ ]] || return 1
    autofix_nvidia || return 1
  else
    echo ""
    echo "  提示: 非交互模式下可运行 'bash scripts/doctor.sh --autofix' 自动修复。"
    return 1
  fi

  echo ""
  echo "  重新测试 GPU 访问…"
  if docker_gpu_access_ok; then
    ISSUES=$((ISSUES - 1))
    NVIDIA_GPU_FAILED=false
    ok "GPU 访问已修复！"
    return 0
  fi

  echo "  $FAIL GPU 仍无法访问，可能需要手动处理"
  return 1
}

autofix_nvidia() {
  echo ""
  echo "修复 NVIDIA Container Toolkit…"
  echo ""
  
  if ! command -v sudo &>/dev/null; then
    echo "  $FAIL sudo 未找到，无法自动修复"
    return 1
  fi
  
  set +e
  # 移除旧的 nvidia-docker 源
  echo "  清除旧的 nvidia-docker 源…"
  sudo rm -f /etc/apt/sources.list.d/nvidia-docker.list
  
  # 安装必要工具
  echo "  安装依赖工具…"
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2 2>&1 | grep -v "^Reading\|^Building\|^Selecting"
  
  # 添加密钥
  echo "  添加 NVIDIA 密钥…"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey 2>/dev/null | \
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  
  # 添加源
  echo "  添加 NVIDIA Container Toolkit 源…"
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list 2>/dev/null | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  
  # 更新并安装
  echo "  安装 NVIDIA Container Toolkit…"
  sudo apt-get update -qq
  export NVIDIA_CONTAINER_TOOLKIT_VERSION=1.19.0-1
  sudo apt-get install -y \
    nvidia-container-toolkit=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
    nvidia-container-toolkit-base=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
    libnvidia-container-tools=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
    libnvidia-container1=${NVIDIA_CONTAINER_TOOLKIT_VERSION} 2>&1 | grep -v "^Reading\|^Building\|^Selecting"
  
  # 配置 Docker 运行时
  echo "  配置 Docker…"
  sudo nvidia-ctk runtime configure --runtime=docker
  
  # 重启 Docker
  echo "  重启 Docker daemon…"
  sudo systemctl restart docker
  
  set -e
  echo "  $PASS 修复完成！"
  return 0
}

ISSUES=0
WARNINGS=0

echo ""
echo "PanoWan Doctor"
echo "$SECTION"

# ── 1. Docker ──────────────────────────────────────────────────────────────
echo ""
echo "[1/5] Docker"

if command -v docker &>/dev/null; then
  ok "docker CLI 已安装: $(docker --version)"
else
  fail "docker 未找到 — 请安装 Docker Desktop 或 Docker Engine"
fi

if docker info &>/dev/null 2>&1; then
  ok "Docker daemon 正在运行"
else
  fail "Docker daemon 未响应 — 请确保 Docker 已启动"
fi

if docker compose version &>/dev/null 2>&1; then
  ok "docker compose: $(docker compose version --short 2>/dev/null || docker compose version)"
else
  fail "docker compose 插件未安装"
fi

# ── 2. NVIDIA / CUDA ────────────────────────────────────────────────────────
echo ""
echo "[2/5] NVIDIA GPU"

if command -v nvidia-smi &>/dev/null; then
  if nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | grep -q .; then
    GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    ok "宿主机 GPU: $GPU"
  else
    fail "nvidia-smi 存在但无法查询 GPU"
  fi
else
  warn "nvidia-smi 未找到 — 如需 GPU 加速，请安装 NVIDIA 驱动"
fi

echo "  测试 Docker 容器内 GPU 访问（可能需要几秒）…"
if docker_gpu_access_ok; then
  ok "Docker --gpus all 可访问 GPU"
else
  fail "Docker 容器内无法访问 GPU — 请检查:"
  echo "       • nvidia-container-toolkit 是否安装 (apt install nvidia-container-toolkit)"
  echo "       • /etc/docker/daemon.json 是否配置了 nvidia runtime"
  echo "       • WSL2 用户: 参见 https://docs.nvidia.com/cuda/wsl-user-guide/"
  NVIDIA_GPU_FAILED=true
  maybe_fix_nvidia_runtime || true
fi

# ── 3. 模型文件 ──────────────────────────────────────────────────────────────
echo ""
echo "[3/5] 模型文件"

if [[ -f "$WAN_DIFFUSION_FILE" ]]; then
  SIZE=$(du -sh "$WAN_DIFFUSION_FILE" 2>/dev/null | cut -f1)
  ok "diffusion_pytorch_model.safetensors ($SIZE)"
else
  fail "缺少: $WAN_DIFFUSION_FILE"
  echo "       运行 make download-models 下载"
fi

if [[ -f "$WAN_T5_FILE" ]]; then
  SIZE=$(du -sh "$WAN_T5_FILE" 2>/dev/null | cut -f1)
  ok "models_t5_umt5-xxl-enc-bf16.pth ($SIZE)"
else
  fail "缺少: $WAN_T5_FILE"
  echo "       运行 make download-models 下载"
fi

if [[ -f "$LORA_CHECKPOINT_FILE" ]]; then
  SIZE=$(du -sh "$LORA_CHECKPOINT_FILE" 2>/dev/null | cut -f1)
  ok "latest-lora.ckpt ($SIZE)"
else
  fail "缺少: $LORA_CHECKPOINT_FILE"
  echo "       运行 make download-models 下载"
fi

# ── 4. 环境变量 ──────────────────────────────────────────────────────────────
echo ""
echo "[4/5] 环境变量"

if [[ -f "$REPO_ROOT/.env" ]]; then
  ok ".env 文件存在"
  # shellcheck disable=SC1090
  set -a; source "$REPO_ROOT/.env" 2>/dev/null || true; set +a
else
  warn ".env 文件不存在 — 运行 make env 从模板创建"
fi

if [[ -n "${HF_TOKEN:-}" ]]; then
  ok "HF_TOKEN 已设置"
else
  warn "HF_TOKEN 未设置 — 下载私有/受限模型时需要"
fi

if [[ -n "${HF_ENDPOINT:-}" ]]; then
  ok "HF_ENDPOINT=$HF_ENDPOINT"
else
  warn "HF_ENDPOINT 未设置 — 中国大陆用户建议设置为镜像站 (如 https://hf-mirror.com)"
fi

if [[ -n "${HF_HUB_ENABLE_HF_TRANSFER:-}" ]]; then
  ok "HF_HUB_ENABLE_HF_TRANSFER=$HF_HUB_ENABLE_HF_TRANSFER"
else
  warn "HF_HUB_ENABLE_HF_TRANSFER 未设置 — 设为 1 可提升下载速度"
fi

# ── 5. 服务健康 ──────────────────────────────────────────────────────────────
echo ""
echo "[5/5] 服务健康 ($SERVICE_URL)"

HEALTH_JSON=$(curl -fsSm 5 "$SERVICE_URL/health" 2>/dev/null || true)
if [[ -n "$HEALTH_JSON" ]]; then
  STATUS=$(echo "$HEALTH_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo "?")
  MODEL_READY=$(echo "$HEALTH_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("model_ready","?"))' 2>/dev/null || echo "?")
  if [[ "$STATUS" == "ready" ]]; then
    ok "服务状态: $STATUS (model_ready=$MODEL_READY)"
  else
    warn "服务状态: $STATUS (model_ready=$MODEL_READY) — 模型可能未加载完成"
  fi
else
  warn "无法连接到 $SERVICE_URL — 服务未启动？运行 make up"
fi

# ── 总结 ─────────────────────────────────────────────────────────────────────
echo ""
echo "$SECTION"
if [[ $ISSUES -eq 0 && $WARNINGS -eq 0 ]]; then
  echo "  $PASS 一切正常，环境就绪！"
elif [[ $ISSUES -eq 0 ]]; then
  echo "  $WARN $WARNINGS 个警告，无严重问题。"
else
  echo "  $FAIL $ISSUES 个错误，$WARNINGS 个警告。"
fi
echo ""
