"""Token usage normalization helpers."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_REASONABLE_TOKENS_PER_FIELD = 1_000_000
MAX_REASONABLE_TOKENS_PER_CALL = 2_000_000

TOKEN_SOURCE_PROVIDER_REPORTED = "provider_reported"
TOKEN_SOURCE_ESTIMATED = "estimated"
TOKEN_SOURCE_ANOMALY_CORRECTED = "anomaly_corrected"
TOKEN_SOURCE_MISSING_ESTIMATED = "missing_estimated"
TOKEN_SOURCE_IGNORED = "ignored"


def coerce_token_count(value: Any) -> int:
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, count)


def normalize_usage(input_tokens: Any = 0, output_tokens: Any = 0, *, source: str = "") -> dict[str, int | bool | str]:
    """Return safe token counters and mark impossible provider values.

    Some OpenAI-compatible gateways expose cumulative or provider-internal
    counters through LangChain metadata. A single NexAgent chat turn should not
    be able to report millions of prompt/completion tokens, so those values are
    treated as untrusted instead of poisoning dashboard totals.
    """
    input_count = coerce_token_count(input_tokens)
    output_count = coerce_token_count(output_tokens)
    total = input_count + output_count
    anomalous = (
        input_count > MAX_REASONABLE_TOKENS_PER_FIELD
        or output_count > MAX_REASONABLE_TOKENS_PER_FIELD
        or total > MAX_REASONABLE_TOKENS_PER_CALL
    )
    if anomalous:
        logger.warning(
            "Detected anomalous token usage source=%s input=%s output=%s total=%s",
            source,
            input_count,
            output_count,
            total,
        )
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "raw_input_tokens": input_count,
            "raw_output_tokens": output_count,
            "token_usage_anomalous": True,
            "token_source": TOKEN_SOURCE_IGNORED,
            "token_estimated": False,
        }
    return {
        "input_tokens": input_count,
        "output_tokens": output_count,
        "raw_input_tokens": input_count,
        "raw_output_tokens": output_count,
        "token_usage_anomalous": False,
        "token_source": TOKEN_SOURCE_PROVIDER_REPORTED,
        "token_estimated": False,
    }


def usage_from_mapping(usage: dict[str, Any] | None, *, source: str = "") -> dict[str, int | bool | str]:
    usage = usage or {}
    normalized = normalize_usage(
        usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
        usage.get("output_tokens") or usage.get("completion_tokens") or 0,
        source=source,
    )
    if usage.get("raw_input_tokens") is not None:
        normalized["raw_input_tokens"] = coerce_token_count(usage.get("raw_input_tokens"))
    if usage.get("raw_output_tokens") is not None:
        normalized["raw_output_tokens"] = coerce_token_count(usage.get("raw_output_tokens"))
    if usage.get("token_source"):
        normalized["token_source"] = str(usage.get("token_source"))
    if usage.get("estimated") is not None:
        normalized["token_estimated"] = bool(usage.get("estimated"))
    if usage.get("token_estimated") is not None:
        normalized["token_estimated"] = bool(usage.get("token_estimated"))
    return normalized


def estimate_text_tokens(text: Any, *, model: str | None = None) -> int:
    """Estimate token count for providers that omit or misreport usage."""
    value = _flatten_text(text)
    if not value:
        return 0
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model or "")
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(value))
    except Exception:
        return _heuristic_token_count(value)


def usage_with_estimate(
    *,
    input_tokens: int,
    output_tokens: int,
    prompt_text: Any,
    response_text: Any,
    model: str | None = None,
    provider_anomalous: bool = False,
) -> dict[str, int | bool | str]:
    """Use provider usage when sane, otherwise estimate from turn text."""
    missing = input_tokens == 0 and output_tokens == 0 and bool(_flatten_text(response_text))
    if not provider_anomalous and not missing:
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "raw_input_tokens": input_tokens,
            "raw_output_tokens": output_tokens,
            "estimated": False,
            "token_estimated": False,
            "token_source": TOKEN_SOURCE_PROVIDER_REPORTED,
        }
    raw_input = input_tokens
    raw_output = output_tokens
    return {
        "input_tokens": estimate_text_tokens(prompt_text, model=model),
        "output_tokens": estimate_text_tokens(response_text, model=model),
        "raw_input_tokens": raw_input,
        "raw_output_tokens": raw_output,
        "estimated": True,
        "token_estimated": True,
        "token_source": TOKEN_SOURCE_ANOMALY_CORRECTED if provider_anomalous else TOKEN_SOURCE_MISSING_ESTIMATED,
        "provider_anomalous": provider_anomalous,
        "provider_usage_missing": missing and not provider_anomalous,
    }


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("delta")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(value or "")


def _heuristic_token_count(text: str) -> int:
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    non_cjk = re.sub(r"[\u4e00-\u9fff]", " ", text)
    word_like = len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", non_cjk))
    return max(1, int(cjk_chars + word_like * 0.75))
