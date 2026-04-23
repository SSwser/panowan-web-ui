# 环境配置指南

## 快速诊断

运行 `make doctor` 检查环境配置：

```bash
make doctor
```

### Windows + WSL2 推荐方式

两种模式都支持：

1. WSL 原生 Docker（在 WSL 内安装 docker engine）：不需要设置 context。
2. Docker Desktop（WSL2 backend）：可显式使用 `desktop-linux` context。

Makefile 使用最直接模式：默认 `DOCKER=bash scripts/docker-proxy.sh`。

行为如下：

- 本机有 `docker`：直接使用本机 docker。
- 本机没有 `docker`：自动尝试 `wsl docker`。

需要切到 Docker Desktop context 时，显式覆盖 `DOCKER` 即可：

- 自动模式：`make up`
- Desktop context：`make up DOCKER='docker --context desktop-linux'`

常用命令：

```bash
docker context ls

# 查看 Makefile 当前判定
make docker-env

# 默认（prod）
make up

# 开发模式（dev）
make up DEV=1

# Docker Desktop context（prod/dev）
make up DOCKER='docker --context desktop-linux'
make up DEV=1 DOCKER='docker --context desktop-linux'

# 诊断
make doctor
```

说明：

- 不覆盖 `DOCKER` 时，Makefile 使用当前 `docker` 默认行为。
- 若使用其他 context（例如远端 Docker），替换为：
   `DOCKER='docker --context <your-context>'`

### Dev 模式依赖缓存（跨 worktree）

`docker-compose-dev.yml` 已配置共享 named volume：

- `panowan-uv-cache:/root/.cache/uv`

该 volume 使用固定名称 `panowan-uv-cache`，因此不同 worktree 跑 `make up DEV=1` 时，`uv sync --locked` 会复用同一份 uv 下载缓存，避免重复下载大体积 wheel（例如 `flash-attn`）。

说明：

- 共享的是下载缓存，不是 `.venv`。
- 每个 worktree 仍会维护自己的项目环境，但网络下载成本显著下降。

如需把模型缓存放到宿主机公共目录，并在 dev 启动时跳过模型下载，可在 `.env` 中设置：

```bash
MODEL_ROOT=./data/models
DEV_SKIP_DOWNLOAD_MODELS=1
```

说明：

- `MODEL_ROOT` 控制 compose 挂载到 `/app/PanoWan/models` 的宿主机路径，`make download-models` 也会复用它。
- `DEV_SKIP_DOWNLOAD_MODELS=1` 时，启动只做服务与依赖环境准备，不自动下载 Wan/LoRA 权重。

输出将显示：

- Docker 及 docker compose 安装状态
- NVIDIA GPU 及 Container Toolkit 配置
- 必要模型文件状态
- `.env` 及 HuggingFace 配置
- 服务健康状态

如果诊断发现 Docker 容器内 GPU 无法访问，脚本会交互式询问是否修复：

```
是否立即尝试自动修复 NVIDIA Container Toolkit？(需要 sudo) [y/N]
```

1. **清理旧配置**

   ```bash
   sudo rm -f /etc/apt/sources.list.d/nvidia-docker.list
   ```

2. **安装依赖**

   ```bash
   sudo apt-get install -y ca-certificates curl gnupg2
   ```

3. **添加 NVIDIA 密钥和源**

   ```bash
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
     sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   
   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   ```

4. **安装 NVIDIA Container Toolkit**

   ```bash
   export NVIDIA_CONTAINER_TOOLKIT_VERSION=1.19.0-1
   sudo apt-get install -y \
     nvidia-container-toolkit=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
     nvidia-container-toolkit-base=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
     libnvidia-container-tools=${NVIDIA_CONTAINER_TOOLKIT_VERSION} \
     libnvidia-container1=${NVIDIA_CONTAINER_TOOLKIT_VERSION}
   ```

5. **配置 Docker 运行时**

   ```bash
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

## 环境检查清单

### 前置要求

- [ ] Docker Engine 已安装（`docker --version`）
- [ ] Docker daemon 正在运行（`docker info`）
- [ ] docker compose 插件已安装（`docker compose version`）
- [ ] NVIDIA GPU 驱动已安装（`nvidia-smi`）
- [ ] NVIDIA Container Toolkit 已安装 （`docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`）

### 模型文件

运行 `make download-models` 下载必要模型（需要网络连接和足够磁盘空间）：

- `data/models/Wan-AI/Wan2.1-T2V-1.3B/diffusion_pytorch_model.safetensors` (~4 GB)
- `data/models/Wan-AI/Wan2.1-T2V-1.3B/models_t5_umt5-xxl-enc-bf16.pth` (~6 GB)
- `data/models/PanoWan/latest-lora.ckpt` (~0.1 GB)

### 环境变量（`.env`）

可选但推荐设置以下变量：

```bash
# HuggingFace 访问令牌（提高速率限制）
HF_TOKEN=

# HuggingFace 镜像站点（中国用户推荐）
HF_ENDPOINT=https://hf-mirror.com

# 模型下载并行度（默认: 8）
HF_MAX_WORKERS=8

# 启用快速转移（需要 pip install hf_transfer）
HF_HUB_ENABLE_HF_TRANSFER=1

# 生成超时（秒，默认: 1800）
GENERATION_TIMEOUT_SECONDS=1800

# 输出目录（默认: /app/runtime/outputs）
OUTPUT_DIR=/app/runtime/outputs

# 任务存储文件（默认: /app/runtime/jobs.json）
JOB_STORE_PATH=/app/runtime/jobs.json
```

运行 `make env` 从模板创建 `.env`：

```bash
make env
```

## 常见问题

### Q: Docker 容器内无法访问 GPU

**A:** 诊断脚本会交互式询问是否修复。直接答 'y' 即可自动完成。

### Q: CUDA 初始化失败 (named symbol not found)

**A:** 这通常是宿主机运行时问题。需要：

1. 更新 NVIDIA 驱动（`nvidia-smi` 应显示驱动版本）
2. 重新启动 WSL2 或 Docker daemon
3. 运行 `make doctor`，按提示交互式修复

### Q: 模型下载很慢

**A:**

- 设置 `HF_ENDPOINT` 为镜像站点（见上文）
- 增加 `HF_MAX_WORKERS`（但受网络和磁盘 I/O 限制）
- 启用 `HF_HUB_ENABLE_HF_TRANSFER=1`（需要 `pip install hf_transfer`）

### Q: 任务丢失 / 服务重启后任务消失

**A:** 这是预期行为。持久化存储由 `jobs.json` 维护，但 running/queued 任务在服务重启时标记为失败。

## 工作流

```bash
# 1. 克隆并配置环境
git clone <repo>
cd panowan-worker
make env

# 2. 检查环境
make doctor

# 3. 下载模型
make download-models

# 4. 启动服务
make up

# 6. 访问 UI
# http://localhost:8000
```

## 部署到生产环境

对于生产部署，建议：

1. 使用专用 `.env` 文件，设置适当的 `GENERATION_TIMEOUT_SECONDS`
2. 配置持久化卷以保存 `data/runtime/` 和 `data/models/`
3. 启用容器重启策略（`docker-compose.yml` 已配置 `restart: unless-stopped`）
4. 监控服务日志：`make logs`
5. 定期运行 `make doctor` 检查状态

## 获取帮助

```bash
# 查看服务日志
make logs

# 检查健康状态
make health

# 运行完整诊断
make doctor

# 或手动运行
bash scripts/doctor.sh
```
