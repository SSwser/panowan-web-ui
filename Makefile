DEV ?= 0
COMPOSE_FILE ?= docker-compose.yml
ifeq ($(DEV),1)
COMPOSE_FILE := docker-compose-dev.yml
endif

UP_FLAGS ?=

DOCKER ?= bash scripts/docker-proxy.sh

COMPOSE ?= $(DOCKER) compose -f $(COMPOSE_FILE)
SERVICE_URL ?= http://localhost:8000
TAG ?= latest
UV_CACHE_VOLUME_NAME ?= panowan-uv-cache
export TAG

# Build-time mirror overrides (leave empty for official sources).
# Examples:
#   make build APT_MIRROR=mirrors.tuna.tsinghua.edu.cn PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
#   make build APT_MIRROR=mirrors.aliyun.com PYPI_INDEX=https://mirrors.aliyun.com/pypi/simple
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

$(eval $(call normalize_bind_var,PANOWAN_HOST_DIR))
$(eval $(call normalize_bind_var,MODEL_ROOT))

.PHONY: init submodule env test build up down logs health doctor download-models docker-env

init: env submodule

submodule:
	git submodule update --init --recursive

env:
	@if [ ! -f .env ]; then cp .env.example .env; fi

test:
	python3 -m unittest discover -s tests

build:
	$(COMPOSE) build $(BUILD_ARGS)

up:
	@if [ "$(DEV)" = "1" ]; then $(DOCKER) volume create $(UV_CACHE_VOLUME_NAME) >/dev/null; fi
	$(COMPOSE) up -d $(UP_FLAGS)

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

health:
	SERVICE_URL="$(SERVICE_URL)" bash scripts/health.sh

doctor:
	bash scripts/doctor.sh

download-models:
	bash scripts/download-models.sh

docker-env:
	@echo "DOCKER=$(DOCKER)"
	@echo "COMPOSE_FILE=$(COMPOSE_FILE)"
	@echo "TAG=$(TAG)"
	@$(DOCKER) version --format '{{.Server.Version}}' 2>/dev/null || echo "docker daemon unavailable"
