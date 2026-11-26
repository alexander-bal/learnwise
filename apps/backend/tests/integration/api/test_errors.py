import logging

import httpx
import pytest


async def test_an_unknown_route_is_a_json_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope", headers={"X-Request-ID": "trace-404"})

    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Not Found", "retryable": False}
    assert response.headers["X-Request-ID"] == "trace-404"


async def test_a_finished_request_logs_its_route_status_and_duration(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        await client.get("/prompts", headers={"X-Request-ID": "trace-log"})

    [record] = [r for r in caplog.records if r.name == "app.request"]
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["route"] == "/prompts"
    assert record.__dict__["status"] == 200
    assert record.__dict__["duration_ms"] >= 0


async def test_a_wrong_method_is_a_json_405_that_keeps_its_allow_header(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/prompts")

    assert response.status_code == 405
    assert response.json()["code"] == "http_error"
    assert response.headers["Allow"] == "GET"
