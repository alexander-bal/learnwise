"""Classified failures of a model call (Processing FR-4)."""


class LlmFailure(Exception):
    """A model call that did not produce a validated object.

    `message` is ours and safe to return; a model server's own text never goes in it.
    """

    code: str = "llm_failure"
    http_status: int = 503
    retryable: bool = True
    # The status written on the attempt's llm_calls row.
    call_status: str = "error"
    message: str = "The model call failed"

    def __init__(self, detail: str = "", *, retry_after: float | None = None) -> None:
        super().__init__(detail or self.message)
        # Kept for the call log; never returned to a caller.
        self.detail = detail
        self.retry_after = retry_after


class ProviderUnavailable(LlmFailure):
    code = "provider_unavailable"
    http_status = 503
    message = "The model server is unavailable"


class AttemptTimedOut(ProviderUnavailable):
    """An attempt that got no answer in time. A kind of ProviderUnavailable."""

    call_status = "timeout"


class OutputInvalid(LlmFailure):
    code = "output_invalid"
    http_status = 502
    message = "The model returned an invalid output"


class ProviderRejected(LlmFailure):
    code = "provider_rejected"
    http_status = 422
    retryable = False
    message = "The model server rejected the request"


class ProviderMisconfigured(LlmFailure):
    code = "provider_misconfigured"
    http_status = 503
    message = "The configured model is not installed"


class DeadlineExceeded(LlmFailure):
    code = "deadline_exceeded"
    http_status = 504
    call_status = "timeout"
    message = "The request deadline passed"


class CircuitOpen(LlmFailure):
    code = "circuit_open"
    http_status = 503
    message = "The model is failing; calls are paused"
