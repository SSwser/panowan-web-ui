---
name: maintaining-react-workbench
description: Use when maintaining a Docker-served React workbench, debugging blank pages or stale Vite assets, validating browser behavior with Playwright, or diagnosing result/version preview media issues.
---

# Maintaining React Workbench

## Overview

A React workbench needs deployed-system evidence, not just unit tests. Verify the failed layer: container lifecycle, static serving, API contract, React state, browser console, or media.

## When to Use

Use when:
- A Docker-served React page is blank, stale, or unlike the latest `dist` build.
- Playwright shows console errors, old Vite hashes, favicon failures, or media 409/404s.
- Editing result/version UI, event streams, task actions, or preview behavior.
- Setting up worktrees, shared data links, resource paths, Docker Compose, or local cache env.

Do not use for backend-only logic with no UI/deploy/runtime surface.

## Quick Reference

| Symptom | First check | Trap |
|---|---|---|
| Blank page | GET `/`, then GET current `/assets/...` | `HEAD` can return 405; use GET |
| Old hash 404 | Fresh Playwright tab/context | Prior-tab console can be stale |
| Favicon 404 | GET `/favicon.ico` should be 204/200 | Browser noise counts |
| Media endpoint 409 | Inspect item `status` + media URLs | URLs do not prove playability |
| Worktree resource issue | Run setup/data-link command | Do not hardcode local roots |
| Frontend not hot-reloading | Use `make dev` and open `:5173` | `make up` serves baked `dist` on `:8000` |
| `make dev` → `make up` orphan warning | `make up` should include `--remove-orphans` | Dev frontend must not linger in prod topology |
| Host tests miss FastAPI or import stale code | Run `make test` from checkout root | Wrong cwd can import another checkout first |
| Docker command fails | Use project compose wrapper | Host Docker may be absent |
| Playwright storage ENOENT | Fresh/no-storage browser context | Config failure is not page failure |

## Workflow

1. Use the project’s command wrapper.
2. Run host tests through `make test` from the checkout/worktree root so the checkout-local `.venv` and `PYTHONPATH=$(CURDIR)` are used.
3. Rebuild and restart the deployed stack, not just the frontend bundle.
4. Verify backend before browser claims:
   - GET runtime/status summary if available
   - GET list/detail API backing the workbench
   - GET `/`, then GET exact JS/CSS assets from HTML
5. Playwright proof:
   - open a fresh query/tab/context after rebuilds
   - if storage state is missing (`storage.json` ENOENT), retry with a fresh/no-storage context before judging the page
   - read only new console messages (`all:false` if available)
   - use accessibility snapshots for rendered UI state
   - inspect network for unexpected media/download fetches
6. When switching from dev back to prod-like topology, confirm the dev frontend orphan is removed rather than merely ignored.
7. Claim success only after fresh tests/build/browser evidence.

## Project Entrypoints

Prefer Makefile targets over ad hoc commands:
- `make setup`: bootstrap canonical checkout, install host/runtime assets, run diagnostics.
- `make setup-worktree`: link shared data, verify worktree prerequisites, run diagnostics. Use `WITH_RUNTIME=1` only when runtime sharing is intended.
- `make test` / `make verify`: run unit tests; `verify` also runs diagnostics.
- `make build`: validate lockfile, prune optional dangling images, build compose images.
- `make up`: start the prod-like static UI/API/worker topology; open UI at `http://localhost:8000`.
- `make dev`: start the development API/worker/Vite topology; open UI at `http://localhost:5173` and API at `http://localhost:8000`.
- `make down` / `make logs`: stop services or follow compose logs.

## Result Preview Rule

Gate every media `src` by successful item/version status:

```tsx
const isPlayable = item.status === 'succeeded' || item.status === 'completed'
const videoUrl = isPlayable ? item.preview_url || item.download_url || null : null
```

Never render `<video src>` for queued/running/cancelling/failed/cancelled states, even if URLs exist. Failed or unfinished items may carry URLs that return 409/404.

## Tests to Add

- Component callback tests across shell, list/table rows, task actions, and transform forms.
- Preview tests for completed, running-with-URLs, and failed-with-URLs items.
- Client tests for list/detail/create/derive endpoints and payloads.
- Static UI tests for `/`, `/assets/{path}`, missing assets, and favicon.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Treating `curl -I` 405 as static failure | Use GET |
| Trusting old Playwright console | Fresh tab/query + new console only |
| Treating Playwright storage ENOENT as page failure | Retry with fresh/no-storage context |
| Treating `preview_url` as playable | Gate by success status |
| Stopping after Docker build | Restart stack, API GETs, browser proof |
| Running tests from another checkout | Use `make test` at the worktree root |
| Ignoring compose orphan warnings | Fix `make up`/compose flags; do not normalize the warning |
| Manual worktree resource config | Use setup/data-link flow |
