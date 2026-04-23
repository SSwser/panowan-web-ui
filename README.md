# panowan-web-ui

一个基于 [PanoWan](https://github.com/VariantConst/PanoWan) 的本地 Docker 化视频生成服务，提供 HTTP API 与 Web UI，让你可以在自己的机器上方便地提交文本生成全景视频任务、查看任务进度并下载结果。

> **灵感来源与致谢**
>
> 本项目基于 [@anthonyharley32/panowan-worker](https://github.com/anthonyharley32/panowan-worker) 改造而来，感谢原作者的出色工程实现。
>
> 同时衷心感谢 [PanoWan](https://github.com/VariantConst/PanoWan) 项目的官方开源——正是他们提出的全景视频生成方法与 LoRA 权重，才使这一切成为可能。
>
> 本项目仅用于学习和技术交流，请勿用于商业用途。

---

## 功能特性

- **Web UI**：浏览器内一键提交任务、查看进度、下载结果
- **异步任务队列**：提交后立即返回任务 ID，后台生成，完成后下载
- **持久化存储**：生成的 MP4 和任务记录在容器重启后保留
- **全参数暴露**：可调整分辨率、推理步数、随机种子、负向提示词等
- **一键诊断**：`make doctor` 检测 GPU、Docker、模型文件等配置

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
│   ├── generator.py    # 视频生成逻辑
│   ├── main.py         # 服务入口
│   ├── settings.py     # 环境变量配置
│   └── static/
│       └── index.html  # Web UI
├── data/
│   ├── models/         # 模型权重（首次启动自动下载）
│   └── runtime/        # 任务记录与生成输出（容器重启保留）
├── scripts/
│   ├── doctor.sh       # 环境诊断脚本
│   ├── download-models.sh
│   └── health.sh
├── tests/
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── ENVIRONMENT.md      # 详细环境配置指南
```

## 快速开始

### 1. 克隆并配置环境变量

```bash
git clone https://github.com/SSwser/panowan-web-ui.git
cd panowan-web-ui
make env          # 从模板生成 .env
```

编辑 `.env`，按需配置（中国用户建议设置 HuggingFace 镜像）：

```bash
# 中国用户推荐：使用镜像加速下载
HF_ENDPOINT=https://hf-mirror.com

# 可选：HuggingFace Token（提升速率限制）
HF_TOKEN=your_token_here

# 生成超时（秒，默认 1800 = 30分钟）
GENERATION_TIMEOUT_SECONDS=1800
```

### 2. 检查环境（推荐）

```bash
make doctor
```

脚本会检查 Docker、GPU、NVIDIA Container Toolkit 及模型文件状态。如发现 GPU 访问问题，会交互式引导修复。

### 3. 下载模型权重

```bash
make download-models
```

将下载约 10 GB 模型到 `data/models/`，可与构建镜像并行进行。下载内容：

| 文件 | 大小 | 说明 |
|---|---|---|
| `diffusion_pytorch_model.safetensors` | ~4 GB | DiT 主干模型 |
| `models_t5_umt5-xxl-enc-bf16.pth` | ~6 GB | T5 文本编码器 |
| `latest-lora.ckpt` | ~0.1 GB | PanoWan 全景 LoRA |

### 4. 构建并启动服务

```bash
make build    # 构建 Docker 镜像
make up       # 后台启动
```

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
查询单个任务状态。状态值：`queued` / `running` / `completed` / `failed`

### `GET /jobs/{job_id}/download`
下载完成的 MP4 文件。

---

## 命令行使用（curl）

```bash
# 提交任务
JOB_ID=$(curl -s -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A cinematic alpine valley at sunset", "width": 896, "height": 448}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

echo "Job ID: $JOB_ID"

# 轮询状态
curl http://localhost:8000/jobs/$JOB_ID

# 下载结果
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
make env              # 初始化 .env 文件
make doctor           # 环境诊断
make download-models  # 下载模型权重
make build            # 构建 Docker 镜像
make up               # 后台启动服务
make down             # 停止服务
make logs             # 查看日志
make health           # 健康检查
make test             # 运行单元测试
```

---

## 常见问题

### Q: 服务启动后 `model_ready` 一直是 `false`？

模型加载需要时间（冷启动约 2–5 分钟）。可持续轮询 `/health` 或查看日志：

```bash
make logs
```

### Q: 生成很慢 / 超时？

- 降低分辨率（如 448×224）和推理步数（20 步）先验证效果
- 调大超时：在 `.env` 中设置 `GENERATION_TIMEOUT_SECONDS=3600`
- 确保 GPU 被 Docker 正确识别：`make doctor`

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

### Q: 生成的视频接缝处有伪影？

这是全景生成的已知局限。全景连续性由算法约束保证（循环滚动 + 循环 padding），建议：
- 使用更高推理步数（50 步）
- 在 Prompt 中描述大范围自然场景（云雾、山川、海洋）效果更好

---

## 环境配置详情

详见 [ENVIRONMENT.md](ENVIRONMENT.md)，包含：
- NVIDIA Container Toolkit 安装与修复
- 所有环境变量说明
- WSL2 特殊配置
- 生产部署建议

---

## 开发与测试

运行单元测试：

```bash
python3 -m unittest discover -s tests
```

直接运行容器（不使用 Compose）：

```bash
docker run --rm -p 8000:8000 --gpus all \
  -v $(pwd)/data/models:/app/PanoWan/models \
  -v $(pwd)/data/runtime:/app/runtime \
  panowan-local
```

---

## 许可证

本项目代码遵循 MIT 许可证。

模型权重（Wan2.1、PanoWan LoRA）遵循其各自的开源许可证（Apache 2.0），详见 `data/models/` 下各自的 README。

---

## 致谢

- **[PanoWan](https://github.com/VariantConst/PanoWan)**：感谢官方团队开源全景视频生成方法及 LoRA 权重，论文：[PanoWan: Lifting Diffusion Video Generation Models to 360° with Latitude/Longitude-aware Mechanisms](https://arxiv.org/abs/2505.22016)
- **[panowan-worker](https://github.com/anthonyharley32/panowan-worker)**：感谢 @anthonyharley32 提供的 Docker 化工程实现，本项目直接基于此改造
- **[Wan-AI/Wan2.1](https://github.com/Wan-Video/Wan2.1)**：底层视频生成模型