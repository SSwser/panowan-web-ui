# Product Runtime Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the product vision, engine-oriented runtime architecture, and key rearchitecture decisions in README and docs before implementing Docker/compose changes.

**Architecture:** This is a documentation anchor pass. README gets the concise project-facing positioning; `docs/architecture/product-runtime.md` gets the durable architecture explanation; `docs/architecture/adr/0001-engine-oriented-product-runtime.md` records the accepted decision and consequences.

**Tech Stack:** Markdown, existing repository docs, Docker/compose architecture spec.

---

## File Structure

- Modify: `README.md` — update project positioning, architecture summary, quick-start direction, and documentation links.
- Create: `docs/architecture/product-runtime.md` — durable architecture guide for product runtime roles and future direction.
- Create: `docs/architecture/adr/0001-engine-oriented-product-runtime.md` — accepted architecture decision record.

## Task 1: Update README Product Positioning

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace old project introduction**

Replace the current README title and intro with a product-platform positioning that states PanoWan is the current default engine, not the project boundary.

- [ ] **Step 2: Add architecture summary**

Add a concise section explaining API, Worker, Model Setup, and Engine Adapter roles.

- [ ] **Step 3: Update quick-start direction**

Adjust wording so model preparation is explicit and service startup is separate from asset setup.

- [ ] **Step 4: Add architecture documentation links**

Link to `docs/architecture/product-runtime.md` and `docs/architecture/adr/0001-engine-oriented-product-runtime.md`.

- [ ] **Step 5: Review README for old wrapper framing**

Search for phrases that imply the project is only a Dockerized wrapper and replace them with product-runtime language.

## Task 2: Add Product Runtime Architecture Doc

**Files:**
- Create: `docs/architecture/product-runtime.md`

- [ ] **Step 1: Create architecture directory**

Create `docs/architecture/` if missing.

- [ ] **Step 2: Write product positioning**

State that the project is evolving into a productized video generation runtime and future distributed GPU scheduling platform.

- [ ] **Step 3: Document runtime roles**

Document API, GPU Worker, Model Setup, and Engine Adapter responsibilities.

- [ ] **Step 4: Document dependency boundaries**

Explain root product dependencies vs engine dependencies.

- [ ] **Step 5: Document evolution path**

Describe current local filesystem backend, future scheduler/queue/backend, and multi-engine worker direction.

## Task 3: Add Architecture Decision Record

**Files:**
- Create: `docs/architecture/adr/0001-engine-oriented-product-runtime.md`

- [ ] **Step 1: Create ADR directory**

Create `docs/architecture/adr/` if missing.

- [ ] **Step 2: Write accepted decision**

Record the decision to split product runtime into API, GPU Worker, and Model Setup roles.

- [ ] **Step 3: Record context**

Explain why the project should not be framed as a thin wrapper and why PanoWan remains a replaceable engine.

- [ ] **Step 4: Record consequences**

State that old all-in-one compose behavior is not preserved, API stays CPU-only, Worker owns GPU/engine dependencies, and model downloads leave production startup.

## Task 4: Validate Documentation Pass

**Files:**
- Inspect: `README.md`
- Inspect: `docs/architecture/product-runtime.md`
- Inspect: `docs/architecture/adr/0001-engine-oriented-product-runtime.md`

- [ ] **Step 1: Search for placeholders**

Run a search for `TBD`, `TODO`, `placeholder`, and `thin wrapper` in the new/modified docs.

- [ ] **Step 2: Confirm docs exist**

Verify all three target docs exist.

- [ ] **Step 3: Do not commit automatically**

Leave changes uncommitted unless the user explicitly requests a git commit.
