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

.PHONY: init submodule env test build setup-models up down logs health doctor docker-env prune

init: env submodule

submodule:
	git submodule update --init --recursive

env:
	@if [ ! -f .env ]; then cp .env.example .env; fi

test:
	python -m unittest discover -s tests

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

setup-models:
	$(DOCKER) compose $(COMPOSE_FILES) --profile setup run --rm model-setup

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
