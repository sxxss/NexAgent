from __future__ import annotations

import pytest


@pytest.mark.unit
def test_token_usage_normalizes_reasonable_values():
    from nexagent.token_usage import normalize_usage

    usage = normalize_usage(1200, 340, source="test")

    assert usage["input_tokens"] == 1200
    assert usage["output_tokens"] == 340
    assert usage["token_usage_anomalous"] is False
    assert usage["token_source"] == "provider_reported"
    assert usage["token_estimated"] is False


@pytest.mark.unit
def test_token_usage_ignores_anomalous_provider_values():
    from nexagent.token_usage import normalize_usage

    usage = normalize_usage(15_200_000, 12, source="test")

    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["raw_input_tokens"] == 15_200_000
    assert usage["token_usage_anomalous"] is True
    assert usage["token_source"] == "ignored"


@pytest.mark.unit
def test_usage_with_estimate_replaces_anomalous_provider_values():
    from nexagent.token_usage import usage_with_estimate

    usage = usage_with_estimate(
        input_tokens=0,
        output_tokens=0,
        prompt_text="hello",
        response_text="world",
        model="",
        provider_anomalous=True,
    )

    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["estimated"] is True
    assert usage["token_estimated"] is True
    assert usage["token_source"] == "anomaly_corrected"
    assert usage["provider_anomalous"] is True


@pytest.mark.unit
def test_usage_with_estimate_marks_missing_provider_usage():
    from nexagent.token_usage import usage_with_estimate

    usage = usage_with_estimate(
        input_tokens=0,
        output_tokens=0,
        prompt_text="hello",
        response_text="world",
        model="",
        provider_anomalous=False,
    )

    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["token_source"] == "missing_estimated"
