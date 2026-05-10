from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.unit
def test_cost_calculation_uses_per_1m_prices():
    from nexagent.costs import ModelPrice, cost_for_tokens

    price = ModelPrice(
        provider_id="p1",
        provider_name="Provider",
        model_id="m1",
        display_name="Model",
        input_price_per_1m="0.2",
        output_price_per_1m="0.8",
        currency="USD",
    )

    result = cost_for_tokens(1_000_000, 500_000, price)

    assert result["input_cost"] == 0.2
    assert result["output_cost"] == 0.4
    assert result["total_cost"] == 0.6
    assert result["priced"] is True


@pytest.mark.unit
def test_price_index_supports_scoped_model_names():
    from nexagent.costs import build_price_index, price_for_model

    provider = SimpleNamespace(
        id="aliyun",
        name="阿里云",
        model_configs=[
            {
                "id": "glm-5",
                "display_name": "GLM 5",
                "input_price_per_1m": 1,
                "output_price_per_1m": 2,
                "currency": "CNY",
            }
        ],
    )

    index = build_price_index([provider])
    price = price_for_model("aliyun::glm-5", index)

    assert price is not None
    assert price.provider_id == "aliyun"
    assert price.model_id == "glm-5"
    assert price.currency == "CNY"


@pytest.mark.unit
def test_price_index_does_not_use_ambiguous_unscoped_model_names():
    from nexagent.costs import build_price_index, price_for_model

    providers = [
        SimpleNamespace(
            id="aliyun",
            name="阿里云",
            model_configs=[{"id": "glm-5", "input_price_per_1m": 1, "output_price_per_1m": 2}],
        ),
        SimpleNamespace(
            id="zhipu",
            name="智谱",
            model_configs=[{"id": "glm-5", "input_price_per_1m": 3, "output_price_per_1m": 4}],
        ),
    ]

    index = build_price_index(providers)

    assert price_for_model("glm-5", index) is None
    assert price_for_model("aliyun::glm-5", index).provider_id == "aliyun"  # type: ignore[union-attr]
