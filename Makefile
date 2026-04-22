PORT ?= 8000
OUTPUT_FILE ?= output.mp4
POLL_INTERVAL ?= 5
COMPOSE ?= docker compose
SERVICE_URL ?= http://localhost:$(PORT)
REQUEST_FILE ?= requests/generate-request.sample.json
PROMPT ?=

ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: env test build up down logs health generate download-models doctor

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

download-models:
	bash scripts/download-models.sh

doctor:
	bash scripts/doctor.sh

generate:
	@set -e; \
	if [ -n "$(PROMPT)" ]; then \
		response=$$(python3 -c 'import json,sys,urllib.request; req = urllib.request.Request(sys.argv[1] + "/generate", data=json.dumps({"prompt": sys.argv[2]}).encode(), headers={"Content-Type": "application/json"}, method="POST"); print(urllib.request.urlopen(req).read().decode())' "$(SERVICE_URL)" "$(PROMPT)"); \
	else \
		response=$$(python3 -c 'import pathlib,sys,urllib.request; payload = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"); req = urllib.request.Request(sys.argv[1] + "/generate", data=payload.encode(), headers={"Content-Type": "application/json"}, method="POST"); print(urllib.request.urlopen(req).read().decode())' "$(SERVICE_URL)" "$(REQUEST_FILE)"); \
	fi; \
	echo "$$response"; \
	job_id=$$(printf '%s' "$$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])'); \
	while true; do \
		status_json=$$(curl -fsS $(SERVICE_URL)/jobs/$$job_id); \
		echo "$$status_json"; \
		status=$$(printf '%s' "$$status_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'); \
		if [ "$$status" = "completed" ]; then \
			curl -fsS $(SERVICE_URL)/jobs/$$job_id/download -o $(OUTPUT_FILE); \
			echo "Saved $(OUTPUT_FILE)"; \
			break; \
		fi; \
		if [ "$$status" = "failed" ]; then \
			echo "Job $$job_id failed" >&2; \
			exit 1; \
		fi; \
		sleep $(POLL_INTERVAL); \
	done