# Experiments

A coursework project — a physical-experiment tracking system.

Users create **experiments**, add **runs**, record **data series** with uncertainty-aware **data points**, attach **images** to runs, and write **reports** (LaTeX source + compiled PDF + inline attachments). Binary files live in MinIO; metadata lives in a 5NF-normalized PostgreSQL schema.

## Stack

| Layer            | Tech                                                          |
| ---------------- | ------------------------------------------------------------- |
| Backend          | FastAPI + SQLAlchemy 2.x (async, `asyncpg`) + Alembic         |
| Database         | PostgreSQL 16                                                 |
| Object storage   | MinIO (S3-compatible)                                         |
| Background tasks | Redis + polling worker (`FileDeletionQueue` outbox)           |
| Frontend         | **Plain HTML + CSS + vanilla JavaScript (ES modules)**        |
| Frontend host    | nginx (serves static files, no build step)                    |
| Orchestration    | Docker Compose                                                |

## Prerequisites

You only need **Docker** and **Docker Compose** on the host. Everything else runs in containers.

## Running

```sh
cp .env.example .env           # edit if you want to change defaults
docker compose up --build
```

First start will:

1. Bring up Postgres, MinIO, Redis.
2. Create the MinIO bucket (`experiments` by default).
3. Run `alembic upgrade head` inside the backend container.
4. Start the FastAPI server, the background worker, and the nginx-hosted frontend.

After everything is healthy:

| Service             | URL                                                              |
| ------------------- | ---------------------------------------------------------------- |
| Frontend (app UI)   | http://localhost:5173                                            |
| Backend API         | http://localhost:8000 (OpenAPI docs at http://localhost:8000/docs) |
| MinIO S3 endpoint   | http://localhost:9000                                            |
| MinIO console       | http://localhost:9001 (user/pass from `.env`)                    |
| Postgres            | `localhost:5432` (user/pass/db from `.env`)                      |

Stop everything with `Ctrl+C` (or `docker compose down`). Data is preserved in named volumes; use `docker compose down -v` to wipe it.

## Repository layout

```
backend/            FastAPI app, Alembic migrations, ARQ worker
  app/
    core/           DB session, config, auth, ORM models
    features/       auth, experiments, runs, series, files, reports, users
    storage/        aiobotocore S3 wrapper
  alembic/          Migration files
  worker/           FileDeletionQueue poller (S3 cleanup)

frontend/           Static SPA — served as-is by nginx, no build step
  index.html        SPA shell
  style.css         Dark theme, hand-written
  js/
    api.js          fetch wrapper + endpoint functions
    app.js          hash router + page renderers

docker/             Dockerfiles and nginx config
  backend/
  frontend/         Dockerfile + nginx.conf
  postgres/         Init SQL (triggers, schema)

system_design/      Schema spec (Russian) + authoritative ER diagram
```

## Frontend

The frontend is a **single-page app written in plain HTML/CSS/vanilla JavaScript** — no React, no TypeScript, no bundler, no package manager. Files are served unmodified by nginx. Start here:

- [frontend/index.html](frontend/index.html) — SPA shell.
- [frontend/js/app.js](frontend/js/app.js) — hash router (`#/experiments`, `#/runs/:id`, …) and all page renderers. Uses a tiny `h(tag, attrs, ...children)` helper for DOM construction.
- [frontend/js/api.js](frontend/js/api.js) — fetch wrapper and every backend endpoint as a function. The JWT is stored in `localStorage`.
- [frontend/style.css](frontend/style.css) — dark theme.

The backend base URL defaults to `http://localhost:8000`. To override, set `window.__API_URL__` before `app.js` loads.

To work on the frontend, **just edit the files** — they are mounted read-only into the container, so a browser refresh is enough. No restarts needed.

## Backend

See [CLAUDE.md](CLAUDE.md) for the full design doc (data model, file-cleanup trigger pipeline, tech decisions).

Common commands:

```sh
# Run tests (testcontainers — real Postgres/MinIO)
docker compose run --rm backend pytest

# Create a new migration after editing ORM models
docker compose run --rm backend alembic revision --autogenerate -m "msg"

# Apply migrations
docker compose run --rm backend alembic upgrade head

# Lint / format
docker compose run --rm backend ruff check .
docker compose run --rm backend ruff format .
```

## Using the app

1. Open http://localhost:5173 → register a user.
2. Create an **experiment** → open it → create a **run**.
3. Inside the run: create **data series**, upload run **images**, create a **report**.
4. Inside a series: add **data points** (with optional x/y uncertainty) and click **Generate plot** — the backend renders a PNG via matplotlib and stores it in MinIO.
5. Inside a report: upload `.tex` source, PDF, and inline attachments.

Every file upload goes to MinIO; only metadata is kept in Postgres. When a file is no longer referenced, a trigger queues it in `FileDeletionQueue` and the background worker removes it from MinIO.
