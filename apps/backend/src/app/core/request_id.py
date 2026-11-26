import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[\x21-\x7e]{1,128}")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def resolve_request_id(incoming: str | None) -> str:
    """Use the caller's request id as given when it is printable ASCII of sane length."""
    if incoming is not None and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex
