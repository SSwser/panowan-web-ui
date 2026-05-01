# PanoWan Worker

PanoWan Worker 是一个正在产品化的视频生成运行时与调度平台。当前默认推理引擎是 [PanoWan](https://github.com/VariantConst/PanoWan)，但项目边界不是 PanoWan wrapper；长期目标是支持多 inference engine，并演进为可在 GPU 集群中分布式运行的生成平台。

当前阶段提供本地 Docker 化运行、HTTP API、Web UI、异步任务、持久化输出，并正在扩展 T2V、I2V、upscale、job orchestration 等产品能力。

> **定位说明**
>
> - **主项目**：产品化视频生成 runtime、API、任务管理、调度与未来集群能力。
> - **PanoWan**：当前默认 engine，作为 vendor/engine 边界保留，未来可替换或与其他 engine 并存。
>
- **Docker/Compose 拓扑**：默认 Compose 拓扑已拆分为 `api` / `worker-panowan` 两类运行角色；宿主机侧初始化通过 `make setup-backends` 完成。

> **灵感来源与致谢**
>
> 本项目基于 [@anthonyharley32/panowan-worker](https://github.com/anthonyharley32/panowan-worker) 改造而来，感谢原作者的出色工程实现。
>
> 同时衷心感谢 [PanoWan](https://github.com/VariantConst/PanoWan) 项目的官方开源——正是他们提出的全景视频生成方法与 LoRA 权重，才使这一切成为可能。
>
> 本项目仅用于学习和技术交流，请勿用于商业用途。

---

## 产品愿景

PanoWan Worker 的发展目标是成为一个 engine-oriented video generation platform：

- **产品化 API runtime**：对外提供稳定的任务提交、查询、取消、事件推送和结果下载接口。
- **多能力视频生成**：以 T2V 为起点，继续集成 I2V、upscale 和后处理能力。
- **可替换推理引擎**：PanoWan 是当前默认 engine，但不是应用边界；未来可接入其他视频生成或增强 engine。
- **GPU worker 执行模型**：API 负责调度与交互，worker 负责 GPU 推理和模型加载。
- **分布式调度路径**：从本地文件 job backend 起步，未来演进到 scheduler、queue、数据库和 GPU 集群 worker。

详细架构说明见：

- [Runtime Architecture](docs/runtime-architecture.md)
- [ADR 0001: Engine-oriented Product Runtime](docs/adr/0001-engine-oriented-product-runtime.md)
- [ADR 0002: Model Download Manager](docs/adr/0002-model-download-manager.md)
- [ADR 0003: Backend Runtime Contracts](docs/adr/0003-backend-runtime-contract.md)

---

## 运行架构

默认 Docker/Compose 拓扑以三个运行角色为核心：

| 角色 | 职责 | GPU | Engine 依赖 |
|---|---|---:|---:|
| API service | HTTP API、Web UI、job 创建/查询/取消、SSE 事件、调度入口 | 否 | 否 |
| GPU Worker | job claim、engine adapter、模型加载、T2V/I2V/upscale 执行、状态回写 | 是 | 是 |
| Host setup (`make setup-backends`) | 下载/校验模型权重并准备 backend vendor tree | 否 | 是 |

生产拓扑由 `docker-compose.yml` 定义；`docker-compose-dev.yml` 作为开发 override 提供源码挂载与 dev 镜像。设计细节见 `docs/architecture/`。

---

## 当前功能特性

- **Web UI**：浏览器内提交任务、查看进度、下载结果。
- **HTTP API**：提交生成任务、查询任务状态、下载输出文件。
- **异步任务队列**：提交后立即返回任务 ID，后台生成，完成后下载。
- **持久化存储**：生成的 MP4 和任务记录在容器重启后保留。
- **全参数暴露**：可调整分辨率、推理步数、随机种子、负向提示词等。
- **环境诊断**：`make doctor` 检测 GPU、Docker、模型文件等配置。
- **扩展方向**：I2V、upscale、多 engine worker、分布式调度。

## 系统要求

| 组件 | 最低要求 |
|---|---|
| GPU | NVIDIA，显存 ≥ 12 GB（推荐 RTX 3060 12GB 及以上）|
| 驱动 | NVIDIA Driver + CUDA 12.x |
| 软件 | Docker Engine + docker compose 插件 |
| 磁盘 | ≥ 15 GB（模型权重约 10 GB + 输出空间）|

> **WSL2 用户**：请确保已安装 NVIDIA Container Toolkit。若有问题，运行 `make doctor` 自动检测并引导修复。

## 项目结构

```text
.
├── app/
│   ├── api.py          # HTTP API 路由
│   ├── api_service.py  # API 服务入口
│   ├── worker_service.py # Worker 服务入口
│   ├── generator.py    # 视频生成逻辑
│   ├── upscaler.py     # 视频超分辨率
│   ├── process_runner.py # 子进程管理
│   ├── sse.py          # Server-Sent Events
│   ├── paths.py        # 路径常量
│   ├── settings.py     # 环境变量配置
│   ├── backends/       # backend setup CLI、模型注册与下载
│   └── static/
│       └── index.html  # Web UI
├── data/
│   ├── models/         # 模型权重
│   └── runtime/        # 任务记录与生成输出（容器重启保留）
├── docs/
│   ├── architecture/   # 产品 runtime 架构与 ADR
│   └── panowan-architecture.md
├── scripts/
│   ├── doctor.sh       # 环境诊断脚本
│   ├── health.sh      # 服务健康检查
│   ├── check-runtime.sh # Worker 启动前运行时检查
│   ├── start-api.sh    # API 容器入口
│   ├── start-worker.sh # Worker 容器入口
│   └── docker-proxy.sh # Docker CLI 代理（WSL 兼容）
├── third_party/
│   └── PanoWan/        # 当前默认 vendor engine
├── tests/
├── docker-compose.yml
├── docker-compose-dev.yml
├── Dockerfile
├── Makefile
└── ENVIRONMENT.md      # 详细环境配置指南
```

## 快速开始

标准启动流程：

```bash
make init
make build
make up
make health
```

各步骤说明如下。

### 1. 克隆并配置环境变量

```bash
git clone https://github.com/SSwser/panowan-web-ui.git
cd panowan-web-ui
make init         # 生成 .env、安装 Python 依赖、初始化 submodule、下载/校验 backends
```

编辑 `.env`，按需配置：

```bash
# 中国用户推荐：使用镜像加速下载
HF_ENDPOINT=https://hf-mirror.com

# 可选：HuggingFace Token（提升速率限制）
HF_TOKEN=your_token_here

# 生成超时（秒，默认 1800 = 30分钟）
GENERATION_TIMEOUT_SECONDS=1800
```

### 2. 检查环境

```bash
make doctor
```

脚本会检查 Docker、GPU、NVIDIA Container Toolkit 及模型文件状态。如发现 GPU 访问问题，会交互式引导修复。

### 3. 准备模型权重

模型准备由宿主机侧的 backend setup CLI 完成：

```bash
make setup-backends
```

`make init` 已经会自动执行这一步；单独运行 `make setup-backends` 适用于后续补装或重新校验模型资产。

下载内容：

| 文件 | 大小 | 说明 |
|---|---|---|
| `diffusion_pytorch_model.safetensors` | ~4 GB | DiT 主干模型 |
| `models_t5_umt5-xxl-enc-bf16.pth` | ~6 GB | T5 文本编码器 |
| `latest-lora.ckpt` | ~0.1 GB | PanoWan 全景 LoRA |

### 4. 构建并启动服务

生产拓扑（拆分的 API + GPU Worker）：

```bash
make build
make up
```

开发模式（源码挂载 + dev 镜像）：

```bash
make setup-backends
make build DEV=1
make up DEV=1
make logs DEV=1
```

开发 override 通过 `docker-compose-dev.yml` 注入，仅作为开发便利层，不改变默认产品拓扑。DEV 启动不再编排一次性 `model-setup` 容器；后端源码树、模型权重与运行时校验统一由宿主机侧 `make setup-backends` 负责准备。

### 5. 验证健康状态

```bash
make health
# 或
curl http://localhost:8000/health
```

响应示例：

```json
{
  "status": "ready",
  "service_started": true,
  "model_ready": true,
  "panowan_dir_exists": true,
  "wan_model_exists": true,
  "lora_exists": true
}
```

`model_ready` 为 `false` 时说明模型仍在加载（首次启动冷启动约需 2–5 分钟）。

### 6. 打开 Web UI

浏览器访问：[http://localhost:8000](http://localhost:8000)

在页面中填写 Prompt、设置参数后点击生成，即可在列表中查看任务进度并下载结果。

---

## API 参考

### `GET /health`

服务与模型就绪状态。

### `POST /generate`

提交生成任务，立即返回任务 ID。

**请求体（简洁格式）：**

```json
{
  "prompt": "A cinematic alpine valley at sunset with drifting clouds",
  "negative_prompt": "low quality, blurry, jittery motion",
  "width": 896,
  "height": 448,
  "num_inference_steps": 50,
  "seed": 42
}
```

**请求体（兼容格式，`input` 包装）：**

```json
{
  "input": {
    "prompt": "A cinematic alpine valley at sunset"
  }
}
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `prompt` | string | 必填 | 视频描述文本 |
| `negative_prompt` | string | `""` | 负向提示词，用于排除不想要的内容 |
| `width` | int | 896 | 输出宽度（必须是 height 的 2 倍，全景比例）|
| `height` | int | 448 | 输出高度 |
| `num_inference_steps` | int | 50 | 推理步数，越少越快但质量略降 |
| `seed` | int | 0 | 随机种子，相同种子可复现结果 |

**响应：**

```json
{
  "job_id": "7ddf135f-5a10-40a7-843b-5c48728be172",
  "status": "queued"
}
```

### `GET /jobs`

列出所有任务。

### `GET /jobs/{job_id}`

查询单个任务状态。状态值：`queued` / `running` / `completed` / `failed`。

### `GET /jobs/{job_id}/download`

下载完成的 MP4 文件。

---

## 命令行使用（curl）

```bash
JOB_ID=$(curl -s -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A cinematic alpine valley at sunset", "width": 896, "height": 448}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

echo "Job ID: $JOB_ID"

curl http://localhost:8000/jobs/$JOB_ID
curl -o output.mp4 http://localhost:8000/jobs/$JOB_ID/download
```

---

## 性能参考（RTX 3060 12GB）

| 分辨率 | 推理步数 | 预计时间 | 适用场景 |
|---|---|---|---|
| 448×224 | 20 步 | ~5–10 分钟 | 快速草稿验证 |
| 896×448 | 20 步 | ~25–40 分钟 | 快速预览 |
| 896×448 | 50 步 | ~60–90 分钟 | 最终质量输出 |
| 1280×640 | 50 步 | ~80–120 分钟 | 高分辨率输出 |

> 注：每次生成冷启动加载约 10 GB 模型权重，约需 2–5 分钟，已计入上述时间。

---

## Makefile 速查

```bash
make env           # initialize .env
make init          # bootstrap Python deps + submodules + backend assets
make doctor        # diagnose host Docker/GPU/model state
make setup-backends  # prepare backend vendor tree and model assets on host
make build         # build production api + worker images
make build DEV=1   # build development api + worker images
make up            # start split production topology
make up DEV=1      # start split topology with dev overrides
make down          # stop production topology
make down DEV=1    # stop development topology
make logs          # follow production logs
make logs DEV=1    # follow development logs
make health        # check API health endpoint
make test          # run unit tests
```

---

## 常见问题

### Q: 服务启动后 `model_ready` 一直是 `false`？

模型加载需要时间（冷启动约 2–5 分钟）。可持续轮询 `/health` 或查看日志：

```bash
make logs
```

### Q: 生成很慢 / 超时？

- 降低分辨率（如 448×224）和推理步数（20 步）先验证效果。
- 调大超时：在 `.env` 中设置 `GENERATION_TIMEOUT_SECONDS=3600`。
- 确保 GPU 被 Docker 正确识别：`make doctor`。

### Q: Docker 容器内无法访问 GPU？

```bash
make doctor
```

脚本会交互式引导安装 NVIDIA Container Toolkit。详细步骤见 [ENVIRONMENT.md](ENVIRONMENT.md)。

### Q: 模型下载很慢？

在 `.env` 中设置：

```bash
HF_ENDPOINT=https://hf-mirror.com
HF_HUB_ENABLE_HF_TRANSFER=1
```

### Q: 为什么要拆 API 和 GPU Worker？

API 是产品交互和调度入口，未来应能运行在 CPU 节点并水平扩展；Worker 才负责 GPU、模型、engine adapter 和长时间推理。这个边界是未来多 engine 与 GPU 集群调度的基础。

### Q: PanoWan 会被移入主项目吗？

短期不会。PanoWan 保持 vendor engine 身份，主项目通过 engine boundary 使用它。未来可以接入其他 engine，而不是把产品架构绑定到单一上游项目。

---

## 环境配置详情

详见 [ENVIRONMENT.md](ENVIRONMENT.md)，包含：

- NVIDIA Container Toolkit 安装与修复。
- 所有环境变量说明。
- WSL2 特殊配置。
- 生产部署建议。

---

## 开发与测试

运行单元测试：

```bash
python3 -m unittest discover -s tests
```

开发运行使用 dev override：

```bash
make build DEV=1
make up DEV=1
make logs DEV=1
```

该流程会启用源码 bind mount 和 dev 目标镜像，保持与生产拓扑一致的 API / worker-panowan 拆分。

---

## 许可证

本项目代码遵循 **MIT 许可证**，仅用于学习、研究和技术交流目的。

模型权重（Wan2.1、PanoWan LoRA）遵循其各自的开源许可证（**Apache 2.0**）。

**详见 [LICENSE.md](LICENSE.md)**，其中包含：

- 完整的许可证条款和免责声明。
- 所有依赖库和模型的许可证汇总。
- 使用限制和禁止用途。
- 学术引用指南。

---

## 致谢

- **[PanoWan](https://github.com/VariantConst/PanoWan)**：感谢官方团队开源全景视频生成方法及 LoRA 权重，论文：[PanoWan: Lifting Diffusion Video Generation Models to 360° with Latitude/Longitude-aware Mechanisms](https://arxiv.org/abs/2505.22016)
- **[panowan-worker](https://github.com/anthonyharley32/panowan-worker)**：感谢 @anthonyharley32 提供的 Docker 化工程实现，本项目直接基于此改造
- **[Wan-AI/Wan2.1](https://github.com/Wan-Video/Wan2.1)**：底层视频生成模型
