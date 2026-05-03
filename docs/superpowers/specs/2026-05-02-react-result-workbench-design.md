# PanoWan React TypeScript 结果工作台重构 Spec

## 1. 背景

当前 PanoWan Web UI 是 `app/static/index.html` 单页 HTML，内联 CSS 和 JavaScript 同时承担：

- 生成任务提交
- 质量预设与自定义参数
- 任务历史渲染
- `/jobs` 轮询
- `/jobs/events` SSE 增量更新
- Worker summary
- 视频预览 dialog
- 原始/超分对比
- 超分任务提交
- 取消、强制取消、失败清理等任务治理

这个实现已经承载完整功能，但随着结果预览、超分版本、360° 全景交互增加，旧单页结构不再适合作为主 UI 架构。

本次重构目标是直接建立最优 React TypeScript 结果工作台，不做旧前端语义兼容层，不在新 React 代码里复刻旧 DOM 和旧状态拼装逻辑。

## 2. 目标

### 2.1 产品目标

重构后的 UI 以“结果工作台”为中心，而不是以“任务列表”为中心。

首版必须实现：

1. 独立 `frontend/` Vite React TypeScript 工程。
2. FastAPI 服务 React build 产物作为主 UI。
3. 顶部运行状态栏：
   - 容量
   - Worker 状态
   - 队列
   - Runtime warm 状态
   - 自动刷新/SSE 状态
   - 设置入口
4. 左侧新建任务面板：
   - Prompt
   - 质量预设
   - 自定义参数
   - 负向提示词
   - seed
   - 预计耗时
   - 提交任务
5. 中间结果预览工作台：
   - 360° 球形拖拽预览作为生成和超分结果的核心预览方式。
   - 支持播放、暂停、时间轴、音量、重置视角、全屏。
   - 支持左右对比、单看、滑块对比、A/B 对比。
6. 右侧版本与超分面板：
   - 原始生成版本
   - 2x 超分版本
   - 4x 超分版本
   - 再次超分版本
   - 排队、运行、失败中的派生版本
   - 新建超分任务
7. 底部最近任务表：
   - 缩略图
   - 状态
   - Prompt
   - 版本标签
   - 参数
   - 提交时间
   - 耗时
   - 查看、下载、更多操作
   - 取消、强制取消、重试取消、失败清理等任务治理能力
8. API 可重构，不考虑旧前端兼容。
9. 视觉风格对齐 `DESIGN.md`：
   - 白底
   - 灰阶
   - Cal.com 风格
   - 克制用色
   - 阴影优先于重边框
   - 无渐变、无装饰图形

### 2.2 技术目标

1. 前端从单文件 HTML/JS/CSS 迁移为 React TypeScript。
2. 前端主要状态基于 result/version 工作台模型。
3. 后端保留 job 作为执行单元，但 API 输出前端友好的 result/version 视图。
4. SSE 更新结果工作台模型，而不是要求前端从原始 job 列表猜版本链。
5. 360° viewer 使用 `three` + `@react-three/fiber` 的项目内组件实现，参考 `omni-flow` 的 `PanoVideoViewer` 思路。
6. 不引入大型 panorama viewer 库作为第一选择。
7. 桌面优先，手机只保证不破版和基本可用。

## 3. 非目标

本次不做：

1. 旧 `app/static/index.html` 前端语义兼容。
2. 为旧 JS 事件、旧 DOM ID、旧表格字段保留 shim。
3. 同时维护旧 UI 和新 UI 两套主入口。
4. 移动端完整工作台体验。
5. 多用户权限系统。
6. 云端项目/资产管理。
7. 高级视频编辑功能。
8. 陀螺仪、VR 眼镜、惯性滚动等高级全景交互。
9. 复杂媒体资产库。
10. 为所有历史 job 做复杂迁移脚本；如果需要历史记录兼容，只保留后端能自然映射的最小 result/version 视图。

## 4. 核心架构

### 4.1 新架构分层

```text
frontend/
  React TypeScript Result Workbench
    ↓
FastAPI API
  result/version view API
  job lifecycle API
  worker/runtime summary API
  SSE result events
    ↓
LocalJobBackend
  canonical job execution state
    ↓
Worker / Engines
  generate / upscale execution
```

### 4.2 关键原则

- **job 是执行模型**  
  后端内部仍用 job 表达排队、运行、取消、失败、完成。

- **result/version 是前端产品模型**  
  前端看到的是一个生成结果，以及它下面的多个版本。

- **不让 React 推断业务关系**  
  前端不应靠扫描 `/jobs` 和 `source_job_id` 临时拼版本树。后端应输出 result/version 视图。

- **viewer 与业务解耦**  
  `PanoVideoViewer` 只负责全景视频渲染和视角控制，不知道 job、result、upscale。

## 5. 前端工程结构

新增：

```text
frontend/
  package.json
  package-lock.json 或 pnpm-lock.yaml
  tsconfig.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    api/
      client.ts
      resultClient.ts
      taskClient.ts
      runtimeClient.ts
      eventClient.ts
    components/
      AppShell.tsx
      RuntimeStatusBar.tsx
      StatusPill.tsx
      IconButton.tsx
    features/
      create/
        CreateTaskPanel.tsx
        QualityPresetControl.tsx
        CustomQualityDialog.tsx
      results/
        ResultPreviewWorkspace.tsx
        VersionStrip.tsx
        ResultMetadataBar.tsx
        EmptyResultState.tsx
      viewer/
        PanoVideoViewer.tsx
        ViewerControls.tsx
        SyncedPanoramaCompare.tsx
        ABPanoramaCompare.tsx
        SliderPanoramaCompare.tsx
      versions/
        VersionUpscalePanel.tsx
        VersionTimeline.tsx
        UpscaleForm.tsx
      tasks/
        RecentTasksTable.tsx
        TaskActionsMenu.tsx
        CancelTaskDialog.tsx
    stores/
      runtimeStore.ts
      resultStore.ts
      workspaceStore.ts
    types/
      api.ts
      result.ts
      task.ts
      runtime.ts
    styles/
      tokens.css
      app.css
```

是否使用 Zustand 可在 implementation plan 决定。若引入状态库，优先轻量方案；如果 React state + reducer 已足够，则不强行引入。

## 6. 页面布局

### 6.1 桌面布局

目标接近用户提供的工作台图：

```text
┌──────────────────────────────────────────────────────────────┐
│ PanoWan 视频生成     容量  Worker  队列  Runtime  自动刷新  设置 │
├──────────────┬────────────────────────────┬──────────────────┤
│ 新建任务      │ 结果预览                    │ 版本与超分        │
│ Prompt       │ 状态 / 耗时 / 来源           │ 原始生成          │
│ 质量预设      │ [360° viewer / compare]     │ 2x 超分           │
│ 负向提示词    │ 播放条 / 重置 / 全屏          │ 4x 超分           │
│ seed         │ 版本 strip                   │ 再次超分          │
│ 提交任务      │ 元数据栏                     │ 新建超分任务       │
├──────────────┴────────────────────────────┴──────────────────┤
│ 最近任务表                                                     │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 响应式

首版桌面优先：

- 1280px+：完整三栏 + 底部表格。
- 1024px–1279px：缩窄左右栏，预览区保持优先宽度。
- <1024px：允许左右栏上下堆叠，结果预览优先。
- 手机：保证可滚动、可提交、可查看结果，不追求完整工作台效率。

## 7. 视觉设计

### 7.1 设计系统

遵循 `DESIGN.md`：

- 背景：`#ffffff` 或非常浅灰。
- 主文本：`#242424`。
- 次级文本：`#898989`。
- 色彩只用于：
  - 成功状态
  - 失败状态
  - 链接
  - 视频/缩略图内容本身
- 不使用暖色品牌背景、径向渐变或玻璃拟态。
- 卡片使用 ring shadow + soft shadow，而不是厚边框。
- 交互控件圆角以 8px、12px、9999px 为主。
- heading 使用 Cal Sans 倾向，body 使用 Inter 倾向；实际字体加载方案在 implementation plan 中确认。

### 7.2 关键组件风格

- 顶部状态 pill：
  - 白底
  - 细 ring shadow
  - 小绿点表示 active/healthy
- 主要按钮：
  - charcoal 背景
  - 白色文本
  - hover 降低 opacity 或轻微 shadow 变化
- 次级按钮：
  - 白底
  - shadow ring
  - charcoal 文本
- 表格：
  - 低对比表头
  - 行 hover 使用浅灰
  - 操作按钮保持 compact

## 8. 后端数据模型

### 8.1 内部执行模型

后端继续保留 job：

```ts
type JobType = "generate" | "upscale"

type JobStatus =
  | "queued"
  | "claimed"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled"
```

job 仍负责：

- 任务状态
- 执行参数
- 输入输出路径
- 下载 URL
- 取消状态
- 错误信息
- worker 归属
- 创建/开始/完成时间

### 8.2 前端结果模型

新增 result/version 视图：

```ts
interface ResultSummary {
  result_id: string
  root_job_id: string
  prompt: string
  negative_prompt?: string
  status: ResultStatus
  selected_version_id?: string
  created_at: string
  updated_at: string
  versions: ResultVersion[]
}

type ResultStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "mixed"

interface ResultVersion {
  version_id: string
  job_id: string
  parent_version_id?: string
  type: "original" | "upscale"
  label: string
  status: JobStatus
  model?: string
  scale?: number
  width?: number
  height?: number
  duration_seconds?: number
  fps?: number
  bitrate_mbps?: number
  file_size_bytes?: number
  thumbnail_url?: string
  preview_url?: string
  download_url?: string
  params: Record<string, unknown>
  error?: string
  created_at: string
  started_at?: string
  finished_at?: string
}
```

### 8.3 映射规则

- `generate` job 产生一个 `ResultSummary`。
- `generate` job 对应 `ResultVersion(type="original")`。
- `upscale` job 根据 `source_job_id` 或新字段 `source_version_id` 挂到对应 result 下。
- 再超分版本挂到它的 parent version。
- 如果一个 result 下有运行中、失败、完成混合版本，result status 可为 `mixed`。
- 前端显示状态时优先显示 selected version 状态，同时顶部 result 摘要显示集合状态。

## 9. API 设计

由于不考虑旧前端兼容，可以直接重构为工作台友好的 API。

### 9.1 Results

#### `GET /api/results`

返回最近 results 列表。

```json
{
  "results": [
    {
      "result_id": "res_20260502_001",
      "root_job_id": "job_generate_001",
      "prompt": "A cinematic alpine valley at sunset",
      "status": "completed",
      "selected_version_id": "ver_4x_seedvr2",
      "created_at": "2026-05-02T20:13:00Z",
      "updated_at": "2026-05-02T20:19:00Z",
      "versions": []
    }
  ]
}
```

#### `GET /api/results/{result_id}`

返回单个 result 完整版本树。

#### `POST /api/results`

创建生成任务，并返回 result。

请求：

```json
{
  "prompt": "A cinematic alpine valley at sunset",
  "negative_prompt": "overexposed, static, blurry",
  "quality": "standard",
  "params": {
    "num_inference_steps": 50,
    "width": 896,
    "height": 448,
    "seed": 0
  }
}
```

响应：

```json
{
  "result": {
    "result_id": "res_20260502_001",
    "root_job_id": "job_generate_001",
    "status": "queued",
    "versions": [
      {
        "version_id": "ver_original",
        "job_id": "job_generate_001",
        "type": "original",
        "status": "queued"
      }
    ]
  }
}
```

### 9.2 Versions / Upscale

#### `POST /api/results/{result_id}/versions/{version_id}/upscale`

从指定版本创建超分版本。

请求：

```json
{
  "model": "seedvr2",
  "scale_mode": "factor",
  "scale": 4,
  "target_width": 3584,
  "target_height": 1792,
  "replace_source": false
}
```

响应：

```json
{
  "version": {
    "version_id": "ver_4x_seedvr2",
    "job_id": "job_upscale_004",
    "parent_version_id": "ver_original",
    "type": "upscale",
    "label": "4x SeedVR2",
    "status": "queued",
    "model": "seedvr2",
    "scale": 4,
    "width": 3584,
    "height": 1792
  }
}
```

### 9.3 Runtime

#### `GET /api/runtime/summary`

返回：

```json
{
  "capacity": 1,
  "available_capacity": 1,
  "online_workers": 1,
  "loading_workers": 0,
  "busy_workers": 0,
  "queued_jobs": 0,
  "running_jobs": 0,
  "cancelling_jobs": 0,
  "runtime_warm": true
}
```

### 9.4 Task Governance

可以按新 API 命名整理：

```text
POST   /api/jobs/{job_id}/cancel
POST   /api/jobs/{job_id}/cancel/escalate
POST   /api/jobs/{job_id}/cancel/retry
DELETE /api/jobs/failed
GET    /api/jobs/{job_id}/download
```

这些仍围绕 job，因为取消/下载是执行单元行为。

### 9.5 SSE

#### `GET /api/events`

替代旧 `/jobs/events`，发送 result-aware 事件。

事件类型：

```text
result_created
result_updated
version_created
version_updated
version_deleted
runtime_updated
heartbeat
```

示例：

```json
{
  "event": "version_updated",
  "data": {
    "result_id": "res_20260502_001",
    "version_id": "ver_4x_seedvr2",
    "job_id": "job_upscale_004",
    "status": "completed",
    "download_url": "/api/jobs/job_upscale_004/download"
  }
}
```

## 10. 前端状态流

### 10.1 初始化

1. App 加载。
2. 请求 `/api/runtime/summary`。
3. 请求 `/api/results`。
4. 默认选中最近完成或最近活跃 result。
5. 建立 `/api/events` SSE。
6. SSE 事件增量更新 runtime/result/version store。

### 10.2 创建生成

1. 用户在 `CreateTaskPanel` 输入 prompt。
2. 点击提交。
3. 前端调用 `POST /api/results`。
4. 后端创建 generate job 和 result/version 视图。
5. 前端立即选中新 result。
6. SSE 后续更新 version 状态。
7. 完成后中间 viewer 自动显示原始版本。

### 10.3 创建超分

1. 用户在右侧选择源版本。
2. 选择模型和缩放方式。
3. 点击开始超分。
4. 前端调用 `POST /api/results/{result_id}/versions/{version_id}/upscale`。
5. 新 version 立即进入版本链。
6. 中间工作台可保持当前版本，也可自动切到新运行中版本；推荐自动选中新版本并显示排队/运行状态。
7. 完成后 viewer 加载新版本视频。

### 10.4 版本对比

- 左右对比：
  - source version 和 target version 各一个 `PanoVideoViewer`。
  - 共享：
    - `currentTime`
    - `paused`
    - `viewState`
  - 任一 viewer 拖拽后同步另一边视角。

- 单看：
  - 一个 viewer。
  - 显示 selected version。

- A/B：
  - 一个 viewer。
  - 切换 source URL，保持 currentTime 和 viewState。

- 滑块对比：
  - 优先实现同一视角下的双 viewer 叠层裁切。
  - 拖动 slider 改变上层 viewer 可见宽度。
  - 两个 viewer 共享时间和视角。

## 11. 全景 Viewer 设计

### 11.1 依赖

新增前端依赖：

```json
{
  "three": "implementation-plan-selects-current-compatible-version",
  "@react-three/fiber": "implementation-plan-selects-current-compatible-version"
}
```

是否引入 `@react-three/drei` 暂不作为首版必要依赖。  
如果只需要 `Canvas` 和基础相机控制，可以不引入 `drei`。

### 11.2 实现方式

`PanoVideoViewer` 内部：

1. 创建 `HTMLVideoElement`。
2. 设置：
   - `loop`
   - `playsInline`
   - `crossOrigin = "anonymous"`，如果同源下载不需要 CORS 也保持安全默认。
3. 使用 `new THREE.VideoTexture(video)`。
4. 设置 `texture.colorSpace = THREE.SRGBColorSpace`。
5. 使用 sphere geometry。
6. material 使用 `side={THREE.BackSide}`，从球体内部观看。
7. camera 放在球心。
8. pointer drag 修改 yaw/pitch。
9. pitch clamp 防止翻转。
10. unmount 或 src change 时清理 video 和 texture。

### 11.3 控制接口

```ts
interface PanoViewState {
  yaw: number
  pitch: number
  fov: number
}

interface PanoVideoViewerProps {
  src: string
  paused: boolean
  currentTime: number
  muted: boolean
  viewState: PanoViewState
  onTimeChange(time: number): void
  onDurationChange(duration: number): void
  onViewChange(view: PanoViewState): void
  onError(error: ViewerError): void
}
```

### 11.4 降级策略

不是旧 UI 兼容，而是 runtime failure fallback：

- 如果 WebGL 不可用：
  - 中间 viewer 显示错误状态。
  - 提供下载按钮。
  - 可提供“平面预览”作为错误 fallback，但不作为主交互。
- 如果视频加载失败：
  - 显示版本错误状态。
  - 保留下载和重试/刷新入口。
- 如果某个对比模式不适合当前版本：
  - 禁用该模式并解释原因。

## 12. 错误处理

### 12.1 创建任务失败

- 左侧 `CreateTaskPanel` 显示 inline error。
- 不清空用户输入。
- 不创建空 result。

### 12.2 超分失败

- 右侧版本链显示失败版本。
- 中间工作台如果选中失败版本，显示失败详情和可操作项。
- 最近任务表显示失败状态。
- 支持清理失败任务。

### 12.3 取消中

- 版本链和任务表都显示 cancelling。
- 长取消说明不塞进表格行。
- 复杂操作放在 `TaskActionsMenu` 或 `CancelTaskDialog`。

### 12.4 SSE 断开

- 顶部状态栏显示自动刷新异常或重连中。
- 前端 fallback 到周期性刷新 `/api/results` 和 `/api/runtime/summary`。
- 重连成功后恢复实时状态。

### 12.5 API 状态不一致

不做旧语义兼容，但要防御真实运行时状态漂移：

- result 缺少版本：显示空状态并提示刷新。
- version 指向不存在 job：显示数据错误状态。
- download URL 缺失：禁用预览/下载并显示原因。
- metadata 缺失：用 `—`，不伪造值。

## 13. 测试策略

### 13.1 后端测试

新增或更新测试覆盖：

1. `POST /api/results` 创建 result + original version。
2. `GET /api/results` 返回 result/version 聚合视图。
3. `GET /api/results/{id}` 返回完整版本链。
4. `POST /api/results/{id}/versions/{version_id}/upscale` 创建派生 version。
5. generate job 状态变化映射到 result/version。
6. upscale job 状态变化映射到 result/version。
7. failed/cancelling/cancelled 状态映射。
8. SSE 输出 result-aware events。
9. worker/runtime summary 输出新顶部状态需要的字段。
10. 失败任务清理后 result/version 视图一致。

### 13.2 前端单元测试

覆盖：

1. API client 请求/响应解析。
2. result store 处理 `result_created`、`version_created`、`version_updated`。
3. 版本链排序与 selected version 逻辑。
4. 质量预设映射。
5. 超分表单目标分辨率计算。
6. 任务治理 action 的状态反馈。

### 13.3 Viewer 测试

JSDOM 对 WebGL 支持有限，所以 viewer 测试分两层：

1. 单元层：
   - props/state 同步。
   - 错误 fallback。
   - viewer controls 状态。
2. E2E 层：
   - 页面能加载 viewer 容器。
   - 播放控制可点击。
   - 拖拽区域不报错。
   - 对比模式切换不崩溃。

### 13.4 E2E 测试

Playwright 覆盖桌面 golden path：

1. 打开 React UI。
2. 提交生成任务。
3. result 出现在中间工作台。
4. version 链出现原始版本。
5. 模拟完成后 viewer 可见。
6. 创建 2x/4x 超分。
7. 右侧版本链出现新版本。
8. 切换左右对比、单看、滑块对比、A/B。
9. 下载按钮存在。
10. 取消/失败清理入口可操作。

### 13.5 手动验证

因为这是 UI 重构，完成前必须启动 dev server 并用浏览器验证：

- 1280px+ 桌面布局。
- 生成任务提交。
- SSE 或 fallback 刷新。
- 360° viewer 拖拽。
- 超分版本创建。
- 左右对比同步视角。
- A/B 保持时间和视角。
- 滑块对比。
- 失败/取消任务操作。
- 浏览器 console 无错误。

## 14. 构建与服务

### 14.1 前端开发

```bash
rtk npm --prefix frontend install
rtk npm --prefix frontend run dev
rtk npm --prefix frontend run build
rtk npm --prefix frontend run test
```

具体包管理器可在 implementation plan 中确认；如果项目偏好 npm，则使用 npm lock；如果希望更快可选择 pnpm，但不要在 spec 中强制。

### 14.2 FastAPI 集成

生产/默认服务：

- React build 输出到 `frontend/dist`。
- FastAPI root route 返回 `frontend/dist/index.html`。
- 静态资产由 FastAPI 挂载。
- API 全部在 `/api/...` 下，避免与前端路由冲突。

开发模式：

- Vite dev server 单独运行。
- API 请求通过 Vite proxy 转发到 FastAPI。
- FastAPI 保留 API 服务，不在 dev 模式强行服务前端 build。

### 14.3 删除旧入口

旧 `app/static/index.html` 不再作为主 UI。  
实施时可以：

- 删除它；或
- 暂时保留为非主入口，但不继续维护，不在新 API 上兼容它。

由于用户明确要求不做补丁叠补丁，推荐实施完成后删除旧主入口。

## 15. 成功标准

本次重构完成时，应满足：

1. `frontend/` React TypeScript 工程存在并可构建。
2. FastAPI 默认页面加载新 React UI。
3. UI 结构对齐目标图：
   - 顶部状态栏
   - 左侧创建
   - 中间结果预览
   - 右侧版本与超分
   - 底部最近任务
4. 生成任务可从新 UI 创建。
5. 生成结果可进入 result/version 工作台。
6. 生成和超分结果均支持 360° 拖拽预览。
7. 原始/超分支持：
   - 左右对比
   - 单看
   - 滑块对比
   - A/B 对比
8. 可创建超分版本。
9. 版本链能显示完成、排队、运行、失败等状态。
10. 任务治理能力保留：
    - 取消
    - 强制取消
    - 重试取消
    - 清理失败
    - 下载
11. SSE 或 fallback 刷新能保持状态更新。
12. 页面视觉符合 `DESIGN.md` 的灰阶白底方向。
13. 后端和前端测试通过。
14. 浏览器手动验证通过。

## 16. 风险与处理

### 风险 1：360° viewer 和视频同步复杂度高

处理：

- `PanoVideoViewer` 独立封装。
- 对比模式共享统一 `viewState` 和 playback state。
- 优先实现左右对比和 A/B，再实现滑块。
- 滑块使用双 viewer 叠层裁切，避免手写复杂 WebGL shader。

### 风险 2：result/version API 重构影响任务生命周期

处理：

- job 生命周期内部不推倒重来。
- 新 API 是 job 的产品视图。
- 状态转换仍复用现有 lifecycle 规则。
- 测试覆盖 job → version 映射。

### 风险 3：旧单页功能遗漏

处理：

- 不保留旧实现形状，但列出必须保留的用户能力。
- 用成功标准逐项检查：
  - 生成
  - 超分
  - 预览
  - 对比
  - 下载
  - 取消
  - 失败治理
  - worker summary
  - SSE

### 风险 4：前端一次性过大

处理：

- implementation plan 可分阶段执行，但目标架构不缩水。
- 每阶段都以最终架构落子，不写临时兼容层。
- 先建立 API contract 和 store，再构建工作台 UI。

## 17. 推荐实施阶段

这不是详细执行计划，只是 spec 层的阶段边界：

### Phase 1：前端工程与 API contract

- 建立 `frontend/`。
- 建立 React shell。
- 定义 TypeScript API types。
- 后端新增 `/api/results`、`/api/runtime/summary`、`/api/events`。
- FastAPI 支持 React build。

### Phase 2：Result/version 后端视图

- job → result/version 聚合。
- generate 创建 result。
- upscale 创建派生 version。
- SSE 输出 result-aware events。
- 后端测试。

### Phase 3：工作台 UI

- 顶部状态栏。
- 左侧创建任务。
- 中间结果工作台静态结构。
- 右侧版本与超分。
- 底部最近任务。
- 前端 store 和 API client。

### Phase 4：360° viewer 与对比

- `PanoVideoViewer`。
- 单看。
- A/B。
- 左右对比。
- 滑块对比。
- 播放控制、视角同步、全屏、重置视角。

### Phase 5：任务治理与完善

- 取消。
- 强制取消。
- 重试取消。
- 清理失败。
- 下载。
- 错误状态。
- SSE 断线 fallback。
- E2E 和浏览器验证。

### Phase 6：删除旧主 UI

- 移除旧 `app/static/index.html` 主入口。
- 清理不再使用的旧静态逻辑。
- 确认 FastAPI root route 指向 React build。

## 18. Open Decisions

目前还剩少量可以留到 implementation plan 的决策：

1. 前端包管理器：npm / pnpm。
2. 是否使用 Zustand。
3. 是否引入 `@react-three/drei`。
4. Cal Sans 字体加载方式。
5. 缩略图来源：
   - 后端生成缩略图；
   - 前端用视频首帧；
   - 暂时使用视频内容占位。
6. 滑块对比首版实现细节：
   - 双 viewer 叠层裁切；
   - 或单 Canvas/WebGL shader。

这些不影响主架构，可以在写实施计划时定。

## 19. 结论

推荐方案是：

> 直接以结果工作台为目标重构。新增独立 `frontend/` React TypeScript 工程，后端 API 重构为 result/version 视图，保留 job 作为执行单元但不暴露为前端主心智。360° 全景预览使用项目内 `three` + `@react-three/fiber` 组件实现。旧 HTML 单页不做兼容，不继续作为主 UI。

## 20. Research Sources

- [egjs-view360 / PanoViewer](https://naver.github.io/egjs-view360/)
- [ProGamerGov/html-360-viewer](https://github.com/ProGamerGov/html-360-viewer)
- [mpetroff/pannellum](https://github.com/mpetroff/pannellum)
- [yanwsh/videojs-panorama](https://github.com/yanwsh/videojs-panorama)
- [SSwser/omni-flow](https://github.com/SSwser/omni-flow)
