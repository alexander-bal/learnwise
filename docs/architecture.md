# AI Ticket Triage Service — Architecture

## Stack

- Python 3.15, FastAPI, pydantic v2, asyncio
- uvicorn; two processes from one codebase, the API and the review worker (`ROLE=api|worker`), each started and restarted by a supervisor (`pnpm dev` locally)
- SQLite through async SQLAlchemy 2 (aiosqlite); Alembic migrations applied at startup; every connection sets `journal_mode = WAL`, `foreign_keys = ON`, `busy_timeout = 5000`, and `synchronous = FULL`
- Ollama, output constrained to a JSON schema; a separate [simulator](simulator.md) process with Ollama's HTTP API stands in for tests and demos
- JSON logs via standard logging
- Frontend: a simple React console on port 3000, no tests
- Dev tools: uv, pytest with httpx, ruff (lint and format), ty (type checking)

## Components

| Component | Responsibility |
|---|---|
| HTTP API | Serves `/process`, `/healthz` and `/readyz`; starts reviews (writes a row) |
| Review worker | asyncio task (`worker.py`) in the worker process; runs the one open review in attempts, steps and transitions in `services/`. It polls for a due review (1 s). On a termination signal it stops before its next model call; on a schema newer than its code it exits, and its supervisor starts it again |
| LLM gateway | The only way to a model: timeouts, retries, concurrency limits, circuit breaker, call log. One Ollama adapter, used for both provider profiles |
| SQLite | Source of truth, including review job state |
| Simulator | Separate FastAPI process with Ollama's HTTP API on `SIM_PORT` (11435); faults in memory, set on its own `/_sim/faults` endpoints ([simulator.md](simulator.md)) |

## Code Layout

```
apps/
  frontend/        React console
  backend/         FastAPI service
```

The backend is the `app` package in `apps/backend/src/app`, in the usual FastAPI layout:

```
src/app/
  main.py, __main__.py, lifespan.py, worker.py   app factory, entry point, startup, review worker
  api/routes/      one file per REST resource, e.g. reviews.py
  services/        business logic, e.g. reviews.py
  models/          one file per table, e.g. review.py
  schemas/         pydantic request and response models
  core/  db/  llm/ config, database and migrations, LLM gateway
```

Dependencies point down: routes → services → models. Routes and the worker hold no logic; they call services.

Tests sit in `apps/backend/tests`, mirroring `src/app`:

```
tests/
  conftest.py      shared fixtures
  unit/            one module at a time, no database or network, e.g. services/test_scoring.py
  integration/     the app through httpx against a temporary SQLite and the simulator,
                   e.g. api/test_reviews.py
```

`pytest tests/unit` runs in seconds and needs nothing running; `pytest tests/integration` starts the simulator.
