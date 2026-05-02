ifeq ($(OS),Windows_NT)
BASH ?= sh
else
BASH ?= bash
endif
DOCKER ?= $(BASH) scripts/docker-proxy.sh
DEV ?=
COMPOSE_FILES := -f docker-compose.yml $(if $(DEV),-f docker-compose-dev.yml)
COMPOSE ?= $(DOCKER) compose $(COMPOSE_FILES)
SERVICE_URL ?= http://localhost:8000
TAG ?= latest
AUTO_PRUNE ?= 1
export TAG

APT_MIRROR ?=
PYPI_INDEX ?=
BUILD_ARGS := $(if $(APT_MIRROR),--build-arg APT_MIRROR=$(APT_MIRROR)) $(if $(PYPI_INDEX),--build-arg PYPI_INDEX=$(PYPI_INDEX))
PRUNE_CMD := $(DOCKER) image prune -f

define announce
	@printf '\n==> %s\n\n' "$(1)"
endef

ifeq ($(AUTO_PRUNE),0)
BUILD_PRUNE_STEP := @:
else
BUILD_PRUNE_STEP := $(call announce,Prune dangling Docker images) && $(PRUNE_CMD)
endif

VENV_DIR ?= .venv
HOST_PYTHON ?= py -3.12
VENV_PYTHON ?= $(VENV_DIR)/Scripts/python.exe
PYTHON_RUN := $(VENV_PYTHON)

ifneq (,$(wildcard .env))
include .env
endif

NORMALIZE_BIND_PATH ?= $(BASH) scripts/lib/path.sh
DATA_SYNC ?= $(BASH) scripts/data-sync.sh

define normalize_bind_var
ifneq ($(strip $($(1))),)
export $(1) := $(shell $(NORMALIZE_BIND_PATH) "$($(1))")
endif
endef

$(eval $(call normalize_bind_var,MODEL_ROOT))

.PHONY: setup setup-worktree dev verify test build up down logs prune

# Recreate the checkout-local venv only when the interpreter drifts or the
# bootstrap tooling is incomplete, because worktree bootstrap owns host runtime
# readiness and Windows cannot reliably overwrite an in-place python.exe during
# venv recreation.
setup-bootstrap:
	$(call announce,Bootstrap checkout-local Python environment)
	@if [ ! -f .env ]; then cp .env.example .env; fi
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		$(HOST_PYTHON) -m venv $(VENV_DIR); \
	elif ! $(PYTHON_RUN) -c "import pip, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"; then \
		rm -rf $(VENV_DIR); \
		$(HOST_PYTHON) -m venv $(VENV_DIR); \
	fi
	$(PYTHON_RUN) -m ensurepip --upgrade
	$(PYTHON_RUN) -m pip install -e ".[host-runtime]"
	git submodule update --init --recursive

setup-bootstrap-main: setup-bootstrap
	$(call announce,Install backend assets for the main checkout)
	$(PYTHON_RUN) -m app.backends install
	$(call announce,Run environment diagnostics)
	$(BASH) scripts/doctor.sh

setup-bootstrap-worktree: setup-bootstrap
	$(call announce,Verify worktree backend and runtime prerequisites)
	$(PYTHON_RUN) -m app.backends verify
	$(call announce,Run environment diagnostics)
	$(BASH) scripts/doctor.sh

# setup bootstraps the canonical repository checkout.
setup: setup-bootstrap-main

# setup-worktree must leave the worktree ready for real development without
# re-downloading shared model assets; worktrees are expected to reuse data via
# data-sync, while runtime sharing stays opt-in through WITH_RUNTIME.
setup-worktree:
	$(call announce,Link shared worktree data)
	$(DATA_SYNC) link $(if $(WITH_RUNTIME),--runtime)
	@$(MAKE) setup-bootstrap-worktree

dev:
	$(call announce,Start development compose topology)
	@$(MAKE) up DEV=1

# verify stays intentionally small: test correctness first, then run the
# broader environment/runtime diagnosis that already subsumes health checks.
verify:
	$(call announce,Run unit tests)
	@$(MAKE) test
	$(call announce,Run environment diagnostics)
	$(BASH) scripts/doctor.sh

test:
	$(call announce,Discover and run unit tests)
	$(PYTHON_RUN) -m unittest discover -s tests

build:
	$(call announce,Validate uv lockfile)
	@if command -v uv >/dev/null 2>&1; then \
		if uv lock --check >/dev/null 2>&1; then \
			echo "uv.lock is up to date"; \
		else \
			echo "uv.lock is stale; regenerating lockfile..."; \
			uv lock; \
		fi; \
	else \
		echo "warning: uv not found, skipping uv.lock validation"; \
	fi
	$(BUILD_PRUNE_STEP)
	$(call announce,Build compose images)
	$(COMPOSE) build $(BUILD_ARGS)

prune:
	$(call announce,Prune dangling Docker images)
	$(PRUNE_CMD)

up:
	$(call announce,Start compose services)
	$(COMPOSE) up -d $(UP_FLAGS)

down:
	$(call announce,Stop compose services)
	$(COMPOSE) down

logs:
	$(call announce,Follow compose logs)
	$(COMPOSE) logs -f

