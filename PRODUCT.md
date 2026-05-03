# Product

## Register

product

## Users

PanoWan is used by a local creator or operator who submits panorama video generation jobs, waits for GPU-backed processing, previews results, and iteratively improves them through one or more upscale passes. The user is judging output quality and choosing the next operation inside a focused creative workflow, not browsing a generic task dashboard.

## Product Purpose

PanoWan Worker is an engine-oriented video generation runtime and web workspace. It provides a local API, worker process, job lifecycle, output storage, and browser UI for text-to-video, image-to-video, and video upscaling workflows.

The product should make long-running generation understandable and controllable while keeping the generated result as the main working object. Success means the operator can submit a prompt, see whether the runtime is ready, monitor progress, inspect the latest video, compare versions, run additional upscale passes, and recover from failures without leaving the main page.

## Brand Personality

Precise, restrained, and work-focused. The interface should feel like a compact creative operations console: quiet enough for repeated use, dense enough for technical work, and confident enough that users trust long-running generation and upscale state.

The product should feel calm under load. It should communicate technical state clearly without turning infrastructure details into the main visual story.

## Anti-references

Do not make this feel like a marketing landing page, a decorative AI showcase, or a colorful prompt toy. Avoid warm brand palettes, decorative gradients, glass panels, card-heavy SaaS composition, large hero sections, and workflow diagrams that compete with the video result.

Avoid task-list-first layouts where job IDs dominate the screen. Tasks are provenance and control surface; the generated video, preview, comparison, and version chain are the primary workflow.

## Design Principles

1. Lead with results, not jobs. The latest generated video and its versions should be the center of the page.
2. Treat tasks as provenance. The job system explains where results came from, but it should not dominate the workflow.
3. Keep preview and comparison central. Panorama dragging, playback, A/B, side-by-side, and slider comparison belong in the main stage.
4. Support iterative enhancement. Upscale outputs should form a navigable version chain that can be upscaled again.
5. Preserve monochrome restraint. Layout, typography, spacing, and elevation should carry the interface; color should remain rare and meaningful.

## Accessibility & Inclusion

Target WCAG 2.1 AA for the product UI. Preserve keyboard access for form inputs, task actions, preview controls, comparison controls, and version selection. Keep focus states visible even in the grayscale visual system.

Do not rely on color alone for job state, runtime health, selection, comparison mode, or failure conditions. Pair semantic color with labels, icons, shape, or placement. Respect reduced-motion preferences for progress, loading, and preview transitions, especially because generation tasks can remain active for a long time.
