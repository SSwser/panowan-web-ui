PORT ?= 8000
OUTPUT_FILE ?= output.mp4
COMPOSE ?= docker compose
SERVICE_URL ?= http://localhost:$(PORT)
REQUEST_FILE ?= requests/generate-request.sample.json
PROMPT ?=

ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: env test build up down logs health generate request-template prefetch-models

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
	curl -fsS $(SERVICE_URL)/health

request-template:
	@if [ -z "$(PROMPT)" ]; then \
		echo "PROMPT is required, e.g. make request-template PROMPT='A cinematic alpine valley at sunset'"; \
		exit 1; \
	fi
	@mkdir -p $(dir $(REQUEST_FILE))
	@python3 -c 'import json, pathlib, sys; path = pathlib.Path(sys.argv[1]); path.write_text(json.dumps({"prompt": sys.argv[2]}, indent=2) + "\n", encoding="utf-8")' "$(REQUEST_FILE)" "$(PROMPT)"
	@echo "Wrote $(REQUEST_FILE)"

prefetch-models:
	bash scripts/prefetch-models.sh

generate:
	@if [ -n "$(PROMPT)" ]; then \
		python3 -c 'import json,sys; print(json.dumps({"prompt": sys.argv[1]}))' "$(PROMPT)" | \
		curl -fsS -X POST $(SERVICE_URL)/generate \
			-H "Content-Type: application/json" \
			-o $(OUTPUT_FILE) \
			--data @-; \
	else \
		curl -fsS -X POST $(SERVICE_URL)/generate \
			-H "Content-Type: application/json" \
			-o $(OUTPUT_FILE) \
			--data @$(REQUEST_FILE); \
	fi