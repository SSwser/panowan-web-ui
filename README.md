# PanoWan Local Docker Service

This project now runs as a local HTTP service inside Docker and no longer depends on RunPod.

## What changed

- The service code is split into `app/api.py`, `app/generator.py`, `app/settings.py`, and `app/main.py`.
- The old `handler.py` entrypoint has been removed to avoid RunPod-era naming confusion.
- `Dockerfile` now uses a standard CUDA base image and starts the HTTP service on port `8000`.
- Model weights are downloaded on first container start into `data/models/`, so rebuilds do not require downloading them again.
- The sample request payload lives at `requests/generate-request.sample.json`.

## Structure

```text
.
├── app/
│   ├── api.py
│   ├── generator.py
│   ├── main.py
│   └── settings.py
├── data/
│   └── models/
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── requests/
│   └── generate-request.sample.json
├── scripts/
│   └── start-local.sh
├── tests/
│   └── ...
```

## API

- `GET /`: web UI (index.html) — job management dashboard
- `GET /api`: API info
- `GET /health`: health check
- `POST /generate`: submit a generation job and return a job id immediately
- `GET /jobs`: list all jobs
- `GET /jobs/{job_id}`: inspect job status
- `GET /jobs/{job_id}/download`: download the finished MP4

`GET /health` returns both service and model readiness, for example:

```json
{
  "status": "starting",
  "service_started": true,
  "model_ready": false,
  "panowan_dir_exists": true,
  "wan_model_exists": false,
  "lora_exists": false
}
```

The `POST /generate` endpoint accepts either of these payloads:

```json
{
  "prompt": "A cinematic alpine valley at sunset"
}
```

```json
{
  "input": {
    "prompt": "A cinematic alpine valley at sunset"
  }
}
```

## Build

```bash
docker build -t panowan-local .
```

Or with Compose:

```bash
cp .env.example .env
docker compose up --build
```

The image build now installs code and dependencies only. Model weights are fetched on first container start and then reused from `data/models/`.
Compose also mounts `data/runtime/` into the container so generated MP4 files and `jobs.json` survive container restarts.

## Local Dev Flow

1. Prepare environment:

```bash
cp .env.example .env
```

2. Run unit tests:

```bash
python3 -m unittest discover -s tests
```

If you want to overlap model downloads with the Docker image pull, start them in a second terminal right away:

```bash
make download-models
```

That writes the weights into `data/models/` and can run while `docker build` or `docker pull` is still in progress.

3. Build the image:

```bash
docker compose build
```

4. Start the service:

```bash
docker compose up -d
```

The first startup may take a while because it downloads model weights into `data/models/`.

5. Verify health:

```bash
curl http://localhost:8000/health
```

6. Trigger generation:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  --data @requests/generate-request.sample.json
```

Then poll the job and download the result when it is ready:

```bash
curl http://localhost:8000/jobs/<job_id>
curl -o output.mp4 http://localhost:8000/jobs/<job_id>/download
```

Or open the web UI in a browser to manage jobs interactively:

```bash
xdg-open http://localhost:8000
```

7. Inspect logs if needed:

```bash
docker compose logs -f
```

8. Stop the service:

```bash
docker compose down
```

You can also run the same flow with `make`:

```bash
make env
make test
make download-models
make build
make up
make health
make generate PROMPT="A cinematic alpine valley at sunset" OUTPUT_FILE=custom.mp4
make logs
make down
```

## Run

```bash
docker run --rm -p 8000:8000 --gpus all panowan-local
```

If you need a different timeout, set `GENERATION_TIMEOUT_SECONDS`:

```bash
docker run --rm -p 8000:8000 --gpus all \
  -e GENERATION_TIMEOUT_SECONDS=3600 \
  panowan-local
```

## Test

Unit tests:

```bash
python3 -m unittest discover -s tests
```

Health check:

```bash
curl http://localhost:8000/health
```

Submit a generation job:

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  --data @requests/generate-request.sample.json
```

The default output directory for generated files is `/app/runtime/outputs`, and job state is persisted to `/app/runtime/jobs.json`. You can override them with `OUTPUT_DIR` and `JOB_STORE_PATH`.