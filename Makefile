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

ifneq (,$(wildcard .env))
include .env
endif

define normalize_bind_path
ifneq ($(strip $($(1))),)
ifneq ($(filter /% ./% ../%,$($(1))),)
export $(1) := $($(1))
else ifneq ($(findstring :,$($(1))),)
export $(1) := $($(1))
else
export $(1) := ./$(strip $($(1)))
endif
endif
endef

$(eval $(call normalize_bind_path,PANOWAN_SRC_DIR))
$(eval $(call normalize_bind_path,MODEL_ROOT))

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
	@$(DOCKER) version --format '{{.Server.Version}}' 2>/dev/null || echo "docker daemon unavailable"
