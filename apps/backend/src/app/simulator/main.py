"""Stand-in for Ollama's HTTP API (docs/simulator.md). Only liveness for now."""

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI(title="Model server simulator")


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    # Ollama answers its root path with this text.
    return "Ollama is running"


@app.get("/api/version")
async def version() -> dict[str, str]:
    return {"version": "simulator"}
