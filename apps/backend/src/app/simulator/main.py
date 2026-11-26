"""Stand-in for Ollama's HTTP API (docs/simulator.md).

It always gives the same answer to the same call, and fails the way a real model server
does when told to through /_sim/faults.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.simulator.answers import MODELS, classify, count_tokens
from app.simulator.faults import Fault, FaultIn, FaultStore

app = FastAPI(title="Model server simulator")
faults = FaultStore()
faults.load_env()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    # Ollama answers its root path with this text.
    return "Ollama is running"


@app.get("/api/version")
async def version() -> dict[str, str]:
    return {"version": "simulator"}


@app.get("/api/tags")
async def tags() -> dict[str, Any]:
    return {"models": [{"name": m, "model": m} for m in MODELS]}


def _not_found(model: str) -> JSONResponse:
    return JSONResponse({"error": f"model '{model}' not found"}, status_code=404)


@app.post("/api/generate")
async def generate(request: Request) -> JSONResponse:
    body = await request.json()
    model = body.get("model", "")
    if model not in MODELS:
        return _not_found(model)
    # A request with no prompt only loads the model, as in Ollama.
    return JSONResponse(
        {"model": model, "created_at": _now(), "response": "", "done": True, "done_reason": "load"}
    )


async def _apply_faults(model: str, request: Request) -> JSONResponse | str | None:
    """The answer a fault decides, or None for the normal answer.

    The fault set first wins; a delay waits, then the faults current at that moment decide.
    """
    matching = faults.matching(model)
    delay = next((f for f in matching if f.type == "delay"), None)
    if delay is not None:
        await asyncio.sleep(delay.seconds or 0)
        matching = faults.matching(model)
    decisive: Fault | None = next(
        (f for f in matching if f.type not in ("delay", "harmful_proposal")), None
    )
    if decisive is None:
        return None
    match decisive.type:
        case "5xx":
            return JSONResponse({"error": "internal error"}, status_code=decisive.status or 500)
        case "429":
            headers = {}
            if decisive.retry_after is not None:
                headers["Retry-After"] = f"{decisive.retry_after:g}"
            return JSONResponse({"error": "too many requests"}, status_code=429, headers=headers)
        case "reject":
            return JSONResponse({"error": "invalid request"}, status_code=decisive.status or 400)
        case "never_answer":
            # Hold the call open until the caller gives up and closes the connection.
            # The body is read, so the next ASGI message is the disconnect.
            while (await request.receive())["type"] != "http.disconnect":
                pass
            return JSONResponse({"error": "caller went away"}, status_code=499)
        case "malformed_json":
            return "this is not json {"
        case "schema_violation":
            return json.dumps({"intent": "unknown", "urgency": "whenever"})
        case "truncated":
            return "truncated"
    return None


@app.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    model = body.get("model", "")
    if model not in MODELS:
        return _not_found(model)
    messages = body.get("messages") or []
    prompt = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    message = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")

    decided = await _apply_faults(model, request)
    if isinstance(decided, JSONResponse):
        return decided
    done_reason = "stop"
    if decided == "truncated":
        content = '{"intent": "bil'
        done_reason = "length"
    elif decided is not None:
        content = decided
    else:
        content = json.dumps(classify(message, prompt, model=model))
    return JSONResponse(
        {
            "model": model,
            "created_at": _now(),
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": count_tokens(prompt) + count_tokens(message),
            "eval_count": count_tokens(content),
        },
        headers={"X-Request-ID": uuid.uuid4().hex},
    )


@app.get("/_sim/faults")
async def list_faults() -> list[Fault]:
    return faults.all()


@app.post("/_sim/faults", status_code=201)
async def add_fault(fault: FaultIn) -> Fault:
    return faults.add(fault)


@app.delete("/_sim/faults", status_code=204)
async def clear_faults() -> None:
    faults.clear()


@app.delete("/_sim/faults/{fault_id}", status_code=204)
async def remove_fault(fault_id: int) -> None:
    if not faults.remove(fault_id):
        raise HTTPException(status_code=404, detail="No such fault")
