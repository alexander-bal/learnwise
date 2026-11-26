# AI Ticket Triage Service

Specs are in [docs/](docs/); the stack and layout are in [docs/architecture.md](docs/architecture.md).

## Setup

Needs [uv](https://docs.astral.sh/uv/) and pnpm. uv installs Python 3.15 itself.

```bash
pnpm bootstrap
```

## Run

```bash
pnpm dev
```

Starts, each restarted when it exits: the simulator (`:11435`), the API (`:4000`), the worker, and the console (http://localhost:3000). The API and the worker migrate the SQLite database at `apps/backend/var/app.db` on startup.

## Check

```bash
pnpm test
```

```bash
pnpm lint
```

## Agent skills

`apps/backend/.claude/skills/fastapi` links to the skill bundled with the installed FastAPI, through [Library Skills](https://library-skills.io). It resolves after `pnpm bootstrap`; refresh it after upgrading FastAPI with `uvx library-skills --claude` in `apps/backend`.
