import json
import logging

from app.core.logging import JsonFormatter
from app.core.request_id import request_id_var


def _record(**extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "app.test", "levelname": "INFO", "msg": "hi %s"})
    record.args = ("there",)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_a_line_is_one_json_object_with_the_message_and_extras() -> None:
    line = JsonFormatter().format(_record(route="/prompts", status=200))

    entry = json.loads(line)
    assert entry["msg"] == "hi there"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "app.test"
    assert entry["route"] == "/prompts"
    assert entry["status"] == 200
    assert entry["ts"].endswith("+00:00")
    assert "\n" not in line


def test_the_current_request_id_is_written_on_the_line() -> None:
    token = request_id_var.set("req-9")
    try:
        entry = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)

    assert entry["request_id"] == "req-9"


def test_no_request_id_outside_a_request_and_no_uvicorn_colour_duplicate() -> None:
    entry = json.loads(JsonFormatter().format(_record(color_message="\x1b[1mhi\x1b[0m")))

    assert "request_id" not in entry
    assert "color_message" not in entry
