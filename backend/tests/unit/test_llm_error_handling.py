from __future__ import annotations

import pytest


class StreamChunkTimeoutError(Exception):
    pass


@pytest.mark.unit
def test_stream_chunk_timeout_is_not_retried():
    from nexagent.agents.middlewares.llm_error_handling import LLMErrorHandlingMiddleware

    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        raise StreamChunkTimeoutError("No streaming chunk received for 120.0s")

    middleware = LLMErrorHandlingMiddleware(max_retries=1)

    with pytest.raises(StreamChunkTimeoutError):
        middleware.wrap_model_call(object(), handler)  # type: ignore[arg-type]

    assert calls == 1
