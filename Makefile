DOCKER ?= bash scripts/docker-proxy.sh
DEV ?=
COMPOSE_FILES := -f docker-compose.yml $(if $(DEV),-f docker-compose-dev.yml)
COMPOSE ?= $(DOCKER) compose $(COMPOSE_FILES)
SERVICE_URL ?= http://localhost:8000
TAG ?= latest
export TAG

APT_MIRROR ?=
PYPI_INDEX ?=
BUILD_ARGS := $(if $(APT_MIRROR),--build-arg APT_MIRROR=$(APT_MIRROR)) $(if $(PYPI_INDEX),--build-arg PYPI_INDEX=$(PYPI_INDEX))

# uv run expects a command name, not a Python flag. Use uv run python so
# `-m ...` is passed to Python instead of uv.
PYTHON_RUN := $(shell if command -v uv >/dev/null 2>&1; then printf 'uv run python'; else printf 'python'; fi)

ifneq (,$(wildcard .env))
include .env
endif

NORMALIZE_BIND_PATH ?= bash scripts/lib/path.sh

define normalize_bind_var
ifneq ($(strip $($(1))),)
export $(1) := $(shell $(NORMALIZE_BIND_PATH) "$($(1))")
endif
endef

$(eval $(call normalize_bind_var,MODEL_ROOT))

.PHONY: init setup-python setup-submodules env test build setup-backends up down logs health doctor docker-env prune

# setup-backends needs host-side Python deps like huggingface_hub before it can
# download weights, so init bootstraps the environment first instead of assuming
# the caller already ran uv sync manually.
init: env setup-python setup-submodules setup-backends doctor

env:
	@if [ ! -f .env ]; then cp .env.example .env; fi

setup-python:
	@if command -v uv >/dev/null 2>&1; then \
		uv sync --group dev; \
	else \
		python -m pip install -e .; \
	fi

setup-submodules:
	git submodule update --init --recursive

setup-backends: setup-python
	$(PYTHON_RUN) -m app.backends install

test:
	$(PYTHON_RUN) -m unittest discover -s tests

build:
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
	$(COMPOSE) build $(BUILD_ARGS)

up:
	$(COMPOSE) up -d $(UP_FLAGS)

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

health:
	SERVICE_URL="$(SERVICE_URL)" bash scripts/health.sh

doctor:
	bash scripts/doctor.sh

docker-env:
	@echo "DOCKER=$(DOCKER)"
	@echo "COMPOSE=$(COMPOSE)"
	@echo "DEV=$(DEV)"
	@echo "TAG=$(TAG)"
	@$(DOCKER) version --format '{{.Server.Version}}' 2>/dev/null || echo "docker daemon unavailable"

prune:
	$(DOCKER) image prune -f
