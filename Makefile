COMPOSE ?= docker compose
SERVICE_URL ?= http://localhost:8000

ifneq (,$(wildcard .env))
include .env
endif

.PHONY: env test build up down logs health download-models doctor

env:
	@if [ ! -f .env ]; then cp .env.example .env; fi

test:
	python3 -m unittest discover -s tests

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

health:
	SERVICE_URL="$(SERVICE_URL)" bash scripts/health.sh

download-models:
	bash scripts/download-models.sh

doctor:
	bash scripts/doctor.sh