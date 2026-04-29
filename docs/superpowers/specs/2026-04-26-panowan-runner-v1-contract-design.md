# PanoWan Runner v1 Contract Design

> Final implementation target: define the first stable, project-owned invocation contract for `third_party/PanoWan/runner.py`.

This document defines the v1 invocation contract that worker/runtime code will use when invoking the PanoWan backend through the backend-root entrypoint. It is intentionally narrower than the broader backend-runtime architecture document. Its purpose is to freeze the platform-owned boundary before implementation.

This contract follows the already accepted architectural direction:

- `runner.py` is the only canonical platform entrypoint for PanoWan runtime execution.
- worker code expresses product/runtime intent through one structured project-owned payload.
- upstream CLI shape, backend layout details, and runtime bridging mechanics remain internal to `runner.py`.
- text-to-video and image-to-video extend one shared contract rather than exposing separate worker-owned command families.

## 1. Goal and Non-Goals

### Goal

Define the first stable project-owned invocation contract for `third_party/PanoWan/runner.py` such that:

- worker code depends only on project vocabulary,
- `runner.py` owns task dispatch and runtime translation,
- no worker path depends on upstream CLI flags or backend layout details,
- and text-to-video plus image-to-video share one canonical backend-root boundary.

### Non-Goals

This document does not:

- define PanoWan internal inference implementation,
- preserve compatibility with legacy upstream CLI invocation,
- define a multi-backend generic manifest abstraction,
- or expose all possible future tuning controls in version 1.

## 2. Design Constraints

The following constraints are part of the design, not optional migration aids:

1. No patch-upon-patch handling.
2. No backward-compatibility shim for legacy PanoWan CLI flags.
3. `runner.py --job <path>` is the only public invocation shape for version 1.
4. Runtime details such as `input_video`, `cwd`, backend-relative model paths, and backend temp layout remain internal.
5. `negative_prompt` is part of the public generation contract and must not be hidden behind backend defaults.

## 3. Canonical Invocation Shape

Version 1 uses a file-backed JSON payload.

```text
python third_party/PanoWan/runner.py --job <job.json>
```

This is the only supported platform invocation form.

Why this shape is required:

- it keeps the public contract structured and versionable,
- it avoids regrowing a backend-specific passthrough flag surface,
- it is easy to validate, store, replay, and test,
- and it keeps the process boundary simple without leaking upstream semantics.

## 4. Contract Model

The contract represents generation intent, not backend implementation details.

The worker side is responsible for deciding:

- what task is being requested,
- what prompts are being used,
- where the output should be written,
- what the output shape should be,
- and any stable generation controls intentionally exposed by version 1.

`runner.py` is responsible for:

- validating the payload,
- dispatching between `t2v` and `i2v`,
- translating project fields into current runtime behavior,
- constructing any internal bridge artifacts such as single-frame video input,
- and surfacing structured success or failure output.

## 5. v1 Payload Schema

### 5.1 Required fields for all tasks

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | `string` | yes | Must be `"v1"`. Identifies the platform contract version. |
| `task` | `string` | yes | Generation mode. Allowed values: `"t2v"`, `"i2v"`. |
| `prompt` | `string` | yes | Positive prompt text. |
| `negative_prompt` | `string` | yes | Negative prompt text. Must be present even when empty. |
| `output_path` | `string` | yes | Absolute output path for the generated video artifact. |
| `resolution` | `object` | yes | Output resolution object. See below. |
| `num_frames` | `integer` | yes | Final output video frame count. |

`resolution` is required to have:

| Field | Type | Required | Description |
|---|---|---|---|
| `width` | `integer` | yes | Output width in pixels. |
| `height` | `integer` | yes | Output height in pixels. |

### 5.2 Conditionally required fields

The following fields are required when `task == "i2v"`:

| Field | Type | Required when `task=i2v` | Description |
|---|---|---|---|
| `input_image_path` | `string` | yes | Absolute path to the input image. |
| `denoising_strength` | `number` | yes | Image-to-video conditioning strength. Must be less than `1.0`. |

These fields must not be present for `task == "t2v"` unless the implementation later explicitly extends the contract.

### 5.3 Optional fields intentionally exposed in v1

| Field | Type | Required | Description |
|---|---|---|---|
| `seed` | `integer \| null` | no | Explicit seed for deterministic generation. |
| `num_inference_steps` | `integer \| null` | no | Requested inference step count. |
| `guidance_scale` | `number \| null` | no | Requested guidance or CFG scale. |
| `result_path` | `string \| null` | no | Absolute path where `runner.py` should write a structured result JSON file. |

These fields are exposed because they are stable generation controls rather than backend layout details.

## 6. Required Semantics

### 6.1 `negative_prompt`

`negative_prompt` is required for all tasks.

Rules:

- The field must always be present.
- Empty string is allowed.
- `runner.py` must not silently substitute an internal default negative prompt when the field is omitted, because omission itself is invalid.

This rule keeps prompt intent explicit at the platform boundary.

### 6.2 `num_frames`

`num_frames` has one meaning for all tasks: the final output video frame count.

This meaning does not change between `t2v` and `i2v`.

If image-to-video requires internal bridging such as constructing a single-frame input video, that remains a `runner.py` implementation detail and must not change the worker-side meaning of `num_frames`.

### 6.3 `output_path`

`output_path` identifies the final expected output artifact path.

`runner.py` may produce temporary or intermediate files internally, but it must treat `output_path` as the public output target owned by the caller.

### 6.4 `result_path`

When `result_path` is provided, `runner.py` must write a structured JSON result there.

When `result_path` is omitted, structured result output is optional, but exit code behavior remains mandatory.

## 7. Explicitly Forbidden Fields and Dependencies

The following are intentionally outside the v1 platform contract and must not be surfaced through worker-facing payload fields:

- upstream PanoWan CLI flags,
- `input_video`,
- `cwd`,
- backend-relative import path controls,
- `config_file`,
- `lora_path`,
- `model_dir`,
- `vendor_path`,
- `sources_path`,
- temp/build/runtime scratch paths,
- or any field that exposes current backend layout as public API.

Why these fields are forbidden:

- they encode backend implementation details rather than product intent,
- they would reintroduce worker dependence on current runtime wiring,
- and they would make backend-root refactors unnecessarily break the platform boundary.

If future model selection is needed, version 1 should still avoid path-shaped fields. A future field such as `model_id` would be the correct direction, not filesystem location exposure.

## 8. Validation Rules

`runner.py` must reject invalid payloads before dispatch.

Minimum validation rules for v1:

1. `version` must equal `"v1"`.
2. `task` must be exactly `"t2v"` or `"i2v"`.
3. `prompt` must be present.
4. `negative_prompt` must be present.
5. `output_path` must be present and absolute.
6. `resolution.width` and `resolution.height` must both be present positive integers.
7. `num_frames` must be a positive integer.
8. For `task == "i2v"`, `input_image_path` must be present and absolute.
9. For `task == "i2v"`, `denoising_strength` must be present and less than `1.0`.
10. For `task == "t2v"`, `input_image_path` and `denoising_strength` must be rejected.
11. Unknown top-level fields should be rejected in version 1 to keep the contract strict and explicit.

This strict validation is intentional. Version 1 is defining a clean boundary, not a permissive migration surface.

## 9. Result and Error Contract

### 9.1 Process-level contract

`runner.py` must use process exit status as the mandatory success/failure signal:

- exit code `0` means success,
- non-zero exit code means failure.

### 9.2 Structured result contract

When `result_path` is provided, `runner.py` must write a machine-readable JSON result.

Minimum success shape:

```json
{
  "status": "ok",
  "output_path": "/abs/path/out.mp4"
}
```

Minimum failure shape:

```json
{
  "status": "error",
  "code": "INVALID_INPUT",
  "message": "input_image_path is required for task=i2v"
}
```

stderr remains useful for human debugging, but worker code must not depend on parsing stderr text as a stable API.

## 10. Example Payloads

### 10.1 Text-to-video

```json
{
  "version": "v1",
  "task": "t2v",
  "prompt": "a cinematic drone shot over a futuristic city",
  "negative_prompt": "blurry, low quality, distorted",
  "output_path": "/abs/path/out.mp4",
  "resolution": {
    "width": 832,
    "height": 480
  },
  "num_frames": 81,
  "seed": 1234,
  "num_inference_steps": 30,
  "guidance_scale": 6.0,
  "result_path": "/abs/path/out.result.json"
}
```

### 10.2 Image-to-video

```json
{
  "version": "v1",
  "task": "i2v",
  "prompt": "the camera slowly pushes in",
  "negative_prompt": "blurry, low quality, warped anatomy",
  "output_path": "/abs/path/out.mp4",
  "resolution": {
    "width": 832,
    "height": 480
  },
  "num_frames": 81,
  "input_image_path": "/abs/path/input.png",
  "denoising_strength": 0.85,
  "seed": 1234,
  "num_inference_steps": 30,
  "guidance_scale": 6.0,
  "result_path": "/abs/path/out.result.json"
}
```

## 11. Relationship to the Architecture Spec

This document is the child contract spec for:

- `docs/superpowers/specs/2026-04-26-panowan-backend-runtime-vendor-entry-design.md`

The architecture spec explains why the project must standardize on a backend-root entrypoint and a platform-owned contract. This document freezes the first concrete contract that satisfies that direction.

## 12. Future Extension Rules

Future contract evolution should follow these rules:

1. Extend the structured payload rather than adding worker-visible CLI flag families.
2. Keep task branching inside `runner.py`.
3. Prefer semantic identifiers over filesystem paths.
4. Add fields only when they represent durable platform intent.
5. If a new field would expose current backend wiring, keep it internal instead.

## 13. Success Condition

This spec succeeds when:

- worker/runtime code invokes only `runner.py --job <json>`,
- worker/runtime code no longer knows about upstream PanoWan CLI shape,
- t2v and i2v share one backend-root contract,
- `negative_prompt` is explicit and stable at the platform boundary,
- and backend internals can evolve without changing the worker-facing invocation vocabulary.
