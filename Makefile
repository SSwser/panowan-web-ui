DOCKER ?= bash scripts/docker-proxy.sh
COMPOSE_PROD ?= $(DOCKER) compose -f docker-compose.yml
COMPOSE_DEV ?= $(DOCKER) compose -f docker-compose.yml -f docker-compose-dev.yml
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

.PHONY: init submodule env test build build-dev setup-models up up-dev down down-dev logs logs-dev health doctor download-models docker-env

init: env submodule

submodule:
	git submodule update --init --recursive

env:
	@if [ ! -f .env ]; then cp .env.example .env; fi

test:
	python -m unittest discover -s tests

build:
	$(COMPOSE_PROD) build $(BUILD_ARGS)

build-dev:
	$(COMPOSE_DEV) build $(BUILD_ARGS)

setup-models:
	$(COMPOSE_PROD) run --rm --profile setup model-setup

up:
	$(COMPOSE_PROD) up -d $(UP_FLAGS)

up-dev:
	$(COMPOSE_DEV) up -d $(UP_FLAGS)

down:
	$(COMPOSE_PROD) down

down-dev:
	$(COMPOSE_DEV) down

logs:
	$(COMPOSE_PROD) logs -f

logs-dev:
	$(COMPOSE_DEV) logs -f

health:
	SERVICE_URL="$(SERVICE_URL)" bash scripts/health.sh

doctor:
	bash scripts/doctor.sh

download-models:
	bash scripts/download-models.sh

docker-env:
	@echo "DOCKER=$(DOCKER)"
	@echo "COMPOSE_PROD=$(COMPOSE_PROD)"
	@echo "COMPOSE_DEV=$(COMPOSE_DEV)"
	@echo "TAG=$(TAG)"
	@$(DOCKER) version --format '{{.Server.Version}}' 2>/dev/null || echo "docker daemon unavailable"
