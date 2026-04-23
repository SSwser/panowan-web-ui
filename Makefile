DEV ?= 0
COMPOSE_FILE ?= docker-compose.yml
ifeq ($(DEV),1)
COMPOSE_FILE := docker-compose-dev.yml
endif

UP_FLAGS ?=
ifeq ($(DEV),1)
UP_FLAGS += --no-build
endif

DOCKER ?= bash scripts/docker-proxy.sh

COMPOSE ?= $(DOCKER) compose -f $(COMPOSE_FILE)
SERVICE_URL ?= http://localhost:8000
TAG ?= latest
export TAG

ifneq (,$(wildcard .env))
include .env
endif

NORMALIZE_BIND_PATH ?= bash scripts/lib/path.sh

define normalize_bind_var
ifneq ($(strip $($(1))),)
export $(1) := $(shell $(NORMALIZE_BIND_PATH) "$($(1))")
endif
endef

$(eval $(call normalize_bind_var,PANOWAN_SRC_DIR))
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
	$(COMPOSE) build

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

download-models:
	bash scripts/download-models.sh

docker-env:
	@echo "DOCKER=$(DOCKER)"
	@echo "COMPOSE_FILE=$(COMPOSE_FILE)"
	@echo "TAG=$(TAG)"
	@$(DOCKER) version --format '{{.Server.Version}}' 2>/dev/null || echo "docker daemon unavailable"
