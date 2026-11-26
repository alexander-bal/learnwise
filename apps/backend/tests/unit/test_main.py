from app.main import create_app


def test_console_read_endpoints_are_tagged_by_their_table() -> None:
    paths = create_app().openapi()["paths"]

    tags = {path: paths[path]["get"]["tags"] for path in paths if "get" in paths[path]}

    assert tags["/samples"] == ["samples"]
    assert tags["/llm-calls"] == ["llm-calls"]
    assert tags["/requests"] == ["llm-calls"]
    assert tags["/requests/{request_id}"] == ["llm-calls"]
    assert tags["/idempotency-requests"] == ["idempotency-requests"]
    assert not any("records" in t for t in tags.values())
