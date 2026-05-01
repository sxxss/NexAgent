"""Cost estimation helpers for model invocation logs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    provider_id: str
    provider_name: str
    model_id: str
    display_name: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal
    currency: str = "USD"


def decimal_money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def cost_for_tokens(input_tokens: int, output_tokens: int, price: ModelPrice | None) -> dict[str, Any]:
    if price is None:
        return {
            "input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
            "currency": "",
            "priced": False,
        }
    input_cost = Decimal(max(0, input_tokens)) * decimal_money(price.input_price_per_1m) / Decimal(1_000_000)
    output_cost = Decimal(max(0, output_tokens)) * decimal_money(price.output_price_per_1m) / Decimal(1_000_000)
    total = input_cost + output_cost
    return {
        "input_cost": _money_float(input_cost),
        "output_cost": _money_float(output_cost),
        "total_cost": _money_float(total),
        "currency": price.currency,
        "priced": bool(decimal_money(price.input_price_per_1m) or decimal_money(price.output_price_per_1m)),
    }


def build_price_index(providers: list[Any]) -> dict[str, ModelPrice]:
    index: dict[str, ModelPrice] = {}
    unscoped_counts: dict[str, int] = {}
    unscoped_prices: dict[str, ModelPrice] = {}
    for provider in providers:
        provider_id = str(getattr(provider, "id", "") or "")
        provider_name = str(getattr(provider, "name", "") or provider_id)
        configs = getattr(provider, "model_configs", None) or []
        if not isinstance(configs, list):
            continue
        for config in configs:
            if not isinstance(config, dict):
                continue
            model_id = str(config.get("id") or "")
            if not provider_id or not model_id:
                continue
            price = ModelPrice(
                provider_id=provider_id,
                provider_name=provider_name,
                model_id=model_id,
                display_name=str(config.get("display_name") or model_id),
                input_price_per_1m=decimal_money(config.get("input_price_per_1m")),
                output_price_per_1m=decimal_money(config.get("output_price_per_1m")),
                currency=str(config.get("currency") or "USD").upper(),
            )
            index[f"{provider_id}::{model_id}"] = price
            unscoped_counts[model_id] = unscoped_counts.get(model_id, 0) + 1
            unscoped_prices.setdefault(model_id, price)
    for model_id, count in unscoped_counts.items():
        if count == 1:
            index[model_id] = unscoped_prices[model_id]
    return index


def price_for_model(model_name: str | None, index: dict[str, ModelPrice]) -> ModelPrice | None:
    if not model_name:
        return None
    if model_name in index:
        return index[model_name]
    if "::" in model_name:
        return None
    return None


def _money_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
