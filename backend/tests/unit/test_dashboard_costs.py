from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest


@pytest.mark.unit
def test_dashboard_log_payload_includes_cost_and_raw_tokens():
    from nexagent.costs import build_price_index
    from nexagent.db.models import InvocationLog

    from app.gateway.routers.dashboard import _log_payload

    provider = SimpleNamespace(
        id="aliyun",
        name="阿里云",
        model_configs=[
            {
                "id": "glm-5",
                "input_price_per_1m": 1,
                "output_price_per_1m": 2,
                "currency": "CNY",
            }
        ],
    )
    row = InvocationLog(
        id="log-1",
        model_name="aliyun::glm-5",
        input_tokens=1000,
        output_tokens=2000,
        raw_input_tokens=15_200_000,
        raw_output_tokens=2000,
        token_source="anomaly_corrected",
        token_estimated=True,
        created_at=datetime.utcnow(),
    )

    payload = _log_payload(row, price_index=build_price_index([provider]))

    assert payload["raw_total_tokens"] == 15_202_000
    assert payload["total_tokens"] == 3000
    assert payload["currency"] == "CNY"
    assert payload["priced"] is True
    assert payload["price_missing_reason"] == ""


@pytest.mark.unit
def test_dashboard_log_payload_marks_unpriced_model():
    from nexagent.db.models import InvocationLog

    from app.gateway.routers.dashboard import _log_payload

    row = InvocationLog(
        id="log-1",
        model_name="unknown::model",
        input_tokens=1000,
        output_tokens=1000,
        created_at=datetime.utcnow(),
    )

    payload = _log_payload(row, price_index={})

    assert payload["priced"] is False
    assert payload["price_missing_reason"] == "model_price_not_configured"


@pytest.mark.unit
def test_dashboard_currency_accumulator_keeps_currencies_separate():
    from app.gateway.routers.dashboard import _add_currency_amount

    values: dict[str, float] = {}

    _add_currency_amount(values, "USD", 0.01)
    _add_currency_amount(values, "CNY", 0.2)
    _add_currency_amount(values, "USD", 0.02)

    assert values == {"USD": 0.03, "CNY": 0.2}
