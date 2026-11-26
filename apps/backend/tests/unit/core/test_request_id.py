import re

import pytest

from app.core.request_id import resolve_request_id

GENERATED = re.compile(r"[0-9a-f]{32}")


def test_a_valid_incoming_id_is_used_as_given() -> None:
    assert resolve_request_id("req-42_ABC.x") == "req-42_ABC.x"


@pytest.mark.parametrize("incoming", [None, "", "has space", "x" * 129, "line\nbreak", "é"])
def test_a_missing_or_unsafe_id_is_replaced_by_a_generated_one(incoming: str | None) -> None:
    resolved = resolve_request_id(incoming)
    assert GENERATED.fullmatch(resolved)
    assert resolved != incoming


def test_generated_ids_are_unique() -> None:
    assert resolve_request_id(None) != resolve_request_id(None)
