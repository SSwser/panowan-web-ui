# ADR 0011: Workflow-Oriented Makefile Command Surface

Date: 2026-05-01
Status: Proposed

## Context

The repository currently exposes a mixed Makefile command surface where workflow entrypoints and low-level capability commands are presented side-by-side.

That shape has created two recurring problems:

- onboarding flows are not explicit enough for the two real developer entry contexts (main repository vs. Git worktree),
- and the public command surface has grown around implementation details rather than around the development workflow developers actually follow.

In particular:

- `init` and `init-worktree` look semantically similar while doing very different things,
- worktree setup has historically centered on `data-sync`, even though a usable worktree also requires host Python setup, backend installation, and environment diagnosis,
- and several Makefile targets duplicate existing script CLIs without adding orchestration value.

The project now has a clearer development rhythm:

1. initialize the main repository once,
2. initialize each new worktree once,
3. start development mode frequently,
4. verify local changes before handoff,
5. and use lower-level scripts directly when performing targeted diagnosis or maintenance.

The Makefile should reflect that workflow directly.

## Decision

Adopt a **workflow-oriented Makefile command surface** and remove public targets that merely mirror lower-level script capabilities.

### 1. Makefile is a workflow interface, not a generic capability catalog

The public Makefile interface exists to expose the most common developer workflows:

- main-repository onboarding,
- worktree onboarding,
- development-mode startup,
- local verification,
- and high-frequency runtime actions.

It must not try to expose every underlying maintenance or helper action as a first-class target.

### 2. Public Makefile commands are intentionally small and explicit

The public Makefile command surface is reduced to:

- `setup`
- `setup-worktree`
- `dev`
- `verify`
- `test`
- `build`
- `up`
- `down`
- `logs`

These names define the supported developer-facing entrypoints.

### 3. Main-repository onboarding and worktree onboarding are separate workflows

The project recognizes two distinct initialization contexts:

- **main repository onboarding** — first-time setup of the canonical repository checkout,
- **worktree onboarding** — first-time setup of an additional Git worktree.

Those flows must remain separate because they have different requirements.

`setup` is the public entrypoint for main-repository onboarding.

`setup-worktree` is the public entrypoint for worktree onboarding.

They must not share a vague `init` vocabulary because that naming obscures the operational difference that matters to developers.

### 4. Worktree setup means “ready to develop,” not merely “data linked”

`setup-worktree` is not defined as a thin alias for data-linking behavior.

It must orchestrate the steps required to make a worktree usable for real development:

- shared data linking,
- host Python environment setup,
- backend installation / model verification,
- and environment diagnosis.

By default it links shared model data only.

If a developer explicitly opts in, `WITH_RUNTIME=1` extends worktree setup to link runtime data as well.

This keeps the default behavior conservative while still supporting advanced shared-runtime workflows.

### 5. `dev` is the development-mode runtime entrypoint

`dev` exists to express developer intent directly.

It is the stable public command for starting the development stack and maps to the development compose mode rather than to a separate bespoke runtime path.

The public contract is:

- `dev` starts the development stack,
- `up`, `down`, and `logs` remain available for direct runtime control,
- and `DEV` remains the mechanism that selects the development compose file.

This preserves one compose-selection model instead of inventing a second one.

### 6. `verify` means test plus diagnosis

The public verification contract is:

- run the test suite,
- then run environment/runtime diagnosis.

`verify` therefore means `test + doctor`.

`doctor` already subsumes health-oriented checks, so `verify` must not duplicate a separate health step.

This keeps verification semantics small and stable: code correctness plus runtime precondition diagnosis.

### 7. Low-level capability commands belong to scripts, not to the public Makefile surface

The following capability-oriented commands are not part of the public Makefile interface:

- environment bootstrap substeps,
- backend-only maintenance commands,
- data-sync subcommands,
- direct doctor/health helpers,
- Docker environment inspection helpers,
- and similar implementation-facing operations.

When developers need those lower-level actions, they should invoke the corresponding script CLIs directly, such as:

- `bash scripts/data-sync.sh ...`
- `bash scripts/doctor.sh`
- `bash scripts/docker-proxy.sh ...`

This boundary exists because those commands are implementation capabilities, not core workflow entrypoints.

### 8. No backward-compatibility aliases are preserved

The command-surface change is intentionally explicit.

Legacy Makefile entrypoints such as `init` and `init-worktree` are removed instead of being kept as aliases.

This avoids preserving the old mental model in parallel with the new one.

## Consequences

### Positive

- The public Makefile interface now matches how developers actually use the repository.
- Main-repository onboarding and worktree onboarding become unambiguous.
- Worktree setup becomes a real “ready to develop” workflow rather than a partial data-link helper.
- The repository reduces duplicate command surfaces between Makefile and script CLIs.
- Documentation can teach one clear command set instead of mixing workflow commands and maintenance commands.

### Tradeoffs

- Some previously available Makefile subcommands disappear from the public surface.
- Advanced users must learn to call script CLIs directly for targeted maintenance and diagnosis.
- Documentation must be updated in step with the Makefile change, or the new workflow contract will be unclear.

## Implementation Notes

The decision constrains the public interface, not the internal implementation shape.

The Makefile may still call private shell logic or existing scripts internally to implement `setup`, `setup-worktree`, and `verify`.

The important architectural rule is that those internal steps are no longer presented as the public Makefile API.
