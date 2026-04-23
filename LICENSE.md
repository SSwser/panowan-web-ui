# 许可证

## 项目许可

本项目（**panowan-web-ui**）代码部分采用 **MIT 许可证**。

您可以自由地：
- 使用本项目代码用于学习和研究
- 修改和改进代码
- 在遵守 MIT 许可证条款的前提下将其用于其他项目

### MIT 许可证文本

```
MIT License

Copyright (c) 2026 panowan-web-ui contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 依赖和模型权重许可

本项目使用的模型权重和库遵循各自的开源许可证：

### PanoWan 项目

| 组件 | 许可证 | 说明 | 来源 |
|---|---|---|---|
| **PanoWan LoRA 权重** | Apache License 2.0 | 全景视频生成的 LoRA 微调权重 | [PanoWan GitHub](https://github.com/VariantConst/PanoWan) |
| **PanoWan 论文** | arXiv | 学术论文："PanoWan: Lifting Diffusion Video Generation Models to 360° with Latitude/Longitude-aware Mechanisms" | [arXiv:2505.22016](https://arxiv.org/abs/2505.22016) |

### Wan 系列模型

| 模型 | 许可证 | 说明 | 来源 |
|---|---|---|---|
| **Wan2.1-T2V-1.3B** | Apache License 2.0 | 视频生成基础模型 | [Wan-AI/Wan2.1](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B) |
| **UMT5-XXL 文本编码器** | Apache License 2.0 | T5 文本编码模型 | [HuggingFace Model Hub](https://huggingface.co/google/umt5-xxl-enc-bf16) |
| **Wan VAE** | Apache License 2.0 | 视频潜空间编解码器 | [Wan-AI/Wan2.1](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B) |

### 核心依赖库

| 库 | 许可证 |
|---|---|
| PyTorch | BSD |
| Diffusers | Apache License 2.0 |
| FastAPI | MIT |
| Uvicorn | BSD |
| PIL (Pillow) | HPND |
| NumPy | BSD |
| CUDA Toolkit | NVIDIA Software License |

所有依赖库的具体许可证条款，请参考 `pip show <package-name>` 或对应项目的 LICENSE 文件。

---

## 原始项目许可

本项目基于 [@anthonyharley32/panowan-worker](https://github.com/anthonyharley32/panowan-worker) 改造。

**原始项目许可证**：请参考原项目仓库的 LICENSE 文件。

本项目对原项目的主要改进包括：
- 重新组织项目结构和命名
- 扩充和改进部署文档
- 优化配置和脚本
- 增强 Web UI 功能

感谢原作者的优秀工程实现。

---

## 使用限制和声明

### ⚠️ 重要声明

本项目仅用于 **学习、研究和技术交流** 目的。

### 禁止用途

❌ 禁止用于以下目的：
1. **商业用途**：不得用于商业产品或服务的生产
2. **大规模生产**：不得用于工业级视频生产
3. **违反法律的用途**：不得用于生成违反当地法律的内容
4. **生成有害内容**：
   - 虚假信息与诈骗
   - 非法内容
   - 侵犯隐私或肖像权的内容
   - 暴力、仇恨或歧视性内容
5. **侵犯知识产权**：不得用于生成侵犯他人著作权、商标权或专利权的内容

### 许可的用途 ✅

✅ 本项目可用于：
1. 个人学习和研究
2. 学术论文研究（需标注来源）
3. 非商业开源项目
4. 技术交流和分享
5. 改进和优化算法研究

### 免责声明

本项目按"现状"提供，**不提供任何保证**（明示或暗示），包括但不限于对适销性、特定用途适用性、非侵权性的保证。

在任何情况下，作者或贡献者均**不对**以下内容承担责任：
- 任何数据丢失或损坏
- 任何直接、间接、特殊、偶然、后果性或惩罚性损害赔偿
- 任何由本项目使用或无法使用而产生的损害

---

## 模型权重的获取和使用

### 自动下载

运行以下命令自动下载模型权重：

```bash
make download-models
```

权重将下载到 `data/models/` 目录。

### HuggingFace 模型卡片

更多关于模型的详细信息和使用条款，请访问：

- [Wan2.1-T2V-1.3B Model Card](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B)
- [PanoWan LoRA](https://huggingface.co/yousiki/PanoWan)

### 学术引用

如果您在学术研究中使用了本项目或 PanoWan 模型，请引用原始论文：

```bibtex
@article{panowan2025,
  title={PanoWan: Lifting Diffusion Video Generation Models to 360° with Latitude/Longitude-aware Mechanisms},
  author={...},
  journal={arXiv preprint arXiv:2505.22016},
  year={2025}
}
```

---

## 第三方许可汇总

| 组件 | 类型 | 许可证 | 备注 |
|---|---|---|---|
| PyTorch | 库 | BSD | 深度学习框架 |
| Diffusers | 库 | Apache 2.0 | 扩散模型管道 |
| FastAPI | 库 | MIT | Web 框架 |
| NVIDIA CUDA | 工具链 | NVIDIA Software License | GPU 计算 |
| Wan2.1-T2V | 模型 | Apache 2.0 | 基础视频生成模型 |
| PanoWan LoRA | 模型 | Apache 2.0 | 全景生成权重 |

所有 Apache 2.0 许可证的完整文本可在其官方网站查看：[apache.org/licenses/LICENSE-2.0](https://apache.org/licenses/LICENSE-2.0)

---

## 更改和修改

如果您对本项目进行了重大改进或修改，建议：

1. **保留原始许可证通知**：在修改后的代码中保留原始 MIT 许可证通知
2. **标注更改**：清楚地标注您所做的更改
3. **遵守下游许可证**：如果使用了 Apache 2.0 的模型或库，您的衍生项目可能需要遵守 Apache 2.0 许可证
4. **贡献回馈**（可选）：考虑将有益的改进贡献回开源项目

---

## 许可证问题

如您对许可证有任何疑问或发现许可证相关的问题，请：

1. 查看原始项目：[panowan-worker GitHub](https://github.com/anthonyharley32/panowan-worker)
2. 查看 PanoWan 官方项目：[PanoWan GitHub](https://github.com/VariantConst/PanoWan)
3. 提交 Issue 或联系项目维护者

---

## 总结

| 方面 | 说明 |
|---|---|
| **项目代码** | MIT 许可证 ✅ 自由使用 |
| **模型权重** | Apache 2.0 许可证 ✅ 学习/研究用途 |
| **预期用途** | 学习、研究、技术交流 |
| **禁止用途** | 商业、违法、有害内容生成 |
| **免责** | 不提供任何保证 |

---

最后更新：2026 年 4 月 23 日

