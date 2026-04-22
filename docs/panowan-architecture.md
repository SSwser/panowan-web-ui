# PanoWan 架构解析

## 核心结论

PanoWan **不是扩图（Outpainting）**，而是在 Wan2.1 T2V 扩散模型基础上，通过三个代码层面的机制改造成能生成 360° 全景视频的系统。全景连续性来自**算法约束**，内容质量来自 **LoRA 微调**。

---

## 模型文件与职责

| 文件 | 大小 | 职责 |
|---|---|---|
| `diffusion_pytorch_model.safetensors` | ~4 GB | DiT 主干（1.3B 参数，30 层 Transformer） |
| `models_t5_umt5-xxl-enc-bf16.pth` | ~6 GB | T5 UMT5-XXL 文本编码器 |
| `Wan2.1_VAE.pth` | ~0.2 GB | 视频 VAE（编码/解码潜空间） |
| `latest-lora.ckpt` | ~0.1 GB | 全景内容 LoRA 适配层 |

---

## 生成流水线

```
用户 Prompt
    │
    ▼
WanPrompter (T5 UMT5-XXL 文本编码, 最长 512 token)
    │
    ▼
初始噪声生成 (shape: [1, 16, 21, 56, 112] in latent space)
    │
    ▼  ← 1. ERP Warp：球面坐标几何变形
    │
    ▼
Flow Matching Denoiser 循环 (默认 50 步)
    │   ├── WanModel DiT (3D RoPE 位置编码)
    │   ├── Classifier-Free Guidance (cfg_scale=5.0)
    │   └── 2. 每步随机横向 roll → 强迫左右边缘等价
    │
    ▼  ← 3. Circular Padding：解码前循环填充防接缝
    │
    ▼
Wan-VAE 解码 (Tiled 分块解码，防 OOM)
    │
    ▼
mp4 (默认 896×448, fps=15, 81帧 ≈ 5.4s)
```

---

## 三个核心全景机制

### 1. ERP 球面噪声扭曲（`pipeline/wan_video.py: _erp_warp`）

```python
def _erp_warp(self, latents):
    x = x * torch.sin((y * 0.5 + 0.5) * math.pi)
    warped = F.grid_sample(latents, grid, mode="bilinear", ...)
    # 保留方差统计，噪声仍服从 N(0,1)
    warped = torch.sign(warped) * (warped_x2 ** 0.5)
```

在第一步扩散之前，对初始高斯噪声做**等距柱状投影几何变形**：
- 越靠近顶部/底部（高纬区域），像素越向水平中心压缩
- 模拟真实 ERP 图像中极点像素被拉伸的几何特性
- `sign(warped) * sqrt(E[x²])` 保留方差，不影响扩散收敛

### 2. 去噪过程中随机横向循环滚动

```python
# 每个去噪步骤随机在宽度（经度）方向循环位移
random_shift = torch.randint(0, latents.size(-1), (1,)).item()
latents = torch.roll(latents, shifts=random_shift, dims=-1)

# 全部步骤完成后回滚还原
latents = torch.roll(latents, shifts=-sum_shift % latents.size(-1), dims=-1)
```

迫使模型学会"左边界 == 右边界"的等价关系，这是实现**水平方向无缝循环**的核心。

### 3. 解码前循环填充（防 VAE 边缘效应）

```python
if latent_padding_size > 0:
    left_pad = latents[..., -latent_padding_size:]
    right_pad = latents[..., :latent_padding_size]
    latents = torch.cat([left_pad, latents, right_pad], dim=-1)
    # VAE 解码后裁掉 padding
```

VAE 卷积在图像边界会产生块状伪影，用对侧内容填充后解码，消除 360° 视频接缝处的边缘噪声。

---

## DiT 模型架构细节

```
config.json:
  _class_name: WanModel
  model_type: t2v
  dim: 1536          ← 隐层维度
  num_layers: 30     ← Transformer 层数
  num_heads: 12      ← 注意力头数
  head_dim: 128      ← (1536/12)
  ffn_dim: 8960
  in_dim: 16         ← VAE 潜空间通道数
  out_dim: 16
  text_len: 512
```

位置编码使用 **3D RoPE**（Rotary Position Embedding），分三个维度独立计算：
- `freqs[0]`：时间帧维度
- `freqs[1]`：高度维度
- `freqs[2]`：宽度维度（经度方向，与 roll 配合）

---

## LoRA 的作用

LoRA 本身不包含几何机制，它的作用是让 DiT 在全景训练数据上学会适合全景的**内容分布**：
- 一致的地平线和天地关系
- 宽视角下自然的透视感
- 全景场景下合理的物体分布

几何连续性 = 代码层面（roll + padding + ERP warp）  
内容质量 = LoRA 训练层面

---

## 与扩图的本质区别

| 维度 | 扩图（Outpainting） | PanoWan |
|---|---|---|
| 输入 | 已有图像 + 扩展遮罩 | 只有文本 |
| 生成方式 | 条件扩散，锚定已有像素 | 无条件从噪声生成 |
| 全景连续性 | 靠遮罩边界拼接 | 靠每步 roll + 循环 padding |
| 几何约束 | 无 | ERP warped noise |

---

## 可调 CLI 参数（无需修改上游代码）

`panowan-test` 支持的所有参数：

| 参数 | 类型 | 默认值 | 影响 |
|---|---|---|---|
| `--num-inference-steps` | int | 50 | 步数越少越快，质量略降 |
| `--width` | int | 896 | 必须是 height 的 2 倍 |
| `--height` | int | 448 | 分辨率越低越快 |
| `--seed` | int | 0 | 固定随机种子，可复现 |
| `--negative-prompt` | str | 内置默认 | 负向提示词 |
| `--tiled` | bool | True | 分块推理，节省 VRAM |

---

## RTX 3060 12GB 运行参考

| 配置 | 预计时间 | 适用场景 |
|---|---|---|
| 896×448, 50 steps (默认) | ~60–90 分钟 | 最终输出 |
| 896×448, 20 steps | ~25–40 分钟 | 快速预览 |
| 448×224, 20 steps | ~5–10 分钟 | 草稿确认 |

时间主要瓶颈：每次生成都要冷启动（重新加载 ~10 GB 模型权重），约占总时间的 2–5 分钟。
