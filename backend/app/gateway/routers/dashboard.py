"""Dashboard router — aggregated invocation statistics."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

router = APIRouter()


class AnomalyRepairRequest(BaseModel):
    ids: list[str] | None = None
    mode: str = "repair"  # repair | ignore


def _safe_tokens(input_tokens: int | None, output_tokens: int | None) -> tuple[int, int, bool]:
    from nexagent.token_usage import normalize_usage

    normalized = normalize_usage(input_tokens, output_tokens, source="dashboard")
    return (
        int(normalized["input_tokens"]),
        int(normalized["output_tokens"]),
        bool(normalized["token_usage_anomalous"]),
    )


def _add_currency_amount(target: dict[str, float], currency: str, amount: float) -> None:
    if not currency or not amount:
        return
    target[currency] = round(target.get(currency, 0.0) + float(amount), 6)


def _price_missing_reason(model_name: str | None, price_index: dict) -> str:
    if not model_name:
        return "missing_model_name"
    if "::" in model_name:
        return "model_price_not_configured"
    return "ambiguous_or_unmanaged_model"


def _token_source_bucket(source: str) -> str:
    if source in {"estimated", "missing_estimated", "anomaly_corrected"}:
        return "estimated"
    if source == "ignored":
        return "ignored"
    return "provider_reported"


def _row_token_payload(row) -> tuple[int, int, bool, str, int]:
    safe_input, safe_output, anomalous = _safe_tokens(row.input_tokens, row.output_tokens)
    source = getattr(row, "token_source", None) or ("ignored" if anomalous else "provider_reported")
    return safe_input, safe_output, anomalous, source, safe_input + safe_output


def _cost_payload(input_tokens: int, output_tokens: int, model_name: str | None, price_index: dict) -> dict[str, Any]:
    from nexagent.costs import cost_for_tokens, price_for_model

    price = price_for_model(model_name, price_index)
    payload = cost_for_tokens(input_tokens, output_tokens, price)
    payload["price_missing_reason"] = "" if payload["priced"] else _price_missing_reason(model_name, price_index)
    return payload


@router.get("/summary")
async def get_summary(days: int = Query(7, ge=1, le=90)):
    """Return top-level metrics for the past N days."""
    from nexagent.costs import build_price_index
    from nexagent.db.models import AgentConfig, InvocationLog, ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    since = datetime.utcnow() - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        # Total calls
        total_calls = (await session.execute(
            select(func.count()).select_from(InvocationLog)
            .where(InvocationLog.created_at >= since)
        )).scalar_one()

        # Avg latency
        avg_latency = (await session.execute(
            select(func.avg(InvocationLog.latency_ms))
            .where(InvocationLog.created_at >= since)
        )).scalar_one() or 0
        latency_rows = (await session.execute(
            select(InvocationLog.latency_ms)
            .where(InvocationLog.created_at >= since)
            .where(InvocationLog.latency_ms > 0)
        )).scalars().all()

        # Error count
        error_count = (await session.execute(
            select(func.count()).select_from(InvocationLog)
            .where(InvocationLog.created_at >= since)
            .where(InvocationLog.status == "error")
        )).scalar_one()

        # Per-agent breakdown
        agent_rows = (await session.execute(
            select(
                InvocationLog.agent_id,
                InvocationLog.agent_name,
                func.count().label("calls"),
                func.sum(InvocationLog.input_tokens + InvocationLog.output_tokens).label("tokens"),
                func.avg(InvocationLog.latency_ms).label("avg_latency"),
            )
            .where(InvocationLog.created_at >= since)
            .group_by(InvocationLog.agent_id, InvocationLog.agent_name)
            .order_by(func.count().desc())
            .limit(10)
        )).all()

        # Per-model breakdown
        model_rows = (await session.execute(
            select(
                InvocationLog.model_name,
                func.count().label("calls"),
                func.sum(InvocationLog.input_tokens + InvocationLog.output_tokens).label("tokens"),
                func.avg(InvocationLog.latency_ms).label("avg_latency"),
            )
            .where(InvocationLog.created_at >= since)
            .group_by(InvocationLog.model_name)
            .order_by(func.count().desc())
            .limit(10)
        )).all()

        # Status breakdown
        status_rows = (await session.execute(
            select(InvocationLog.status, func.count().label("count"))
            .where(InvocationLog.created_at >= since)
            .group_by(InvocationLog.status)
        )).all()

        # Recent rows for tool aggregation and token aggregation.
        tool_logs = (await session.execute(
            select(InvocationLog)
            .where(InvocationLog.created_at >= since)
        )).scalars().all()
        providers = (await session.execute(select(ModelProvider))).scalars().all()

        # Total agent count
        agent_count = (await session.execute(select(func.count()).select_from(AgentConfig))).scalar_one()

    price_index = build_price_index(providers)
    error_rate = round(error_count / total_calls * 100, 1) if total_calls else 0.0
    input_tokens = 0
    output_tokens = 0
    provider_reported_tokens = 0
    estimated_tokens = 0
    ignored_tokens = 0
    total_cost = 0.0
    cost_by_currency: dict[str, float] = {}
    priced_call_count = 0
    token_anomaly_count = 0
    token_source_counts: dict[str, int] = {}
    latencies = sorted(int(value) for value in latency_rows if value)
    p95_latency = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0
    tool_counts: dict[str, int] = {}
    agent_token_totals: dict[str, int] = {}
    model_token_totals: dict[str, int] = {}
    model_cost_totals: dict[str, float] = {}
    model_cost_currencies: dict[str, dict[str, float]] = {}
    agent_cost_totals: dict[str, float] = {}
    agent_cost_currencies: dict[str, dict[str, float]] = {}
    unpriced_models: dict[str, dict[str, Any]] = {}
    for row in tool_logs:
        safe_input, safe_output, anomalous, source, token_total = _row_token_payload(row)
        input_tokens += safe_input
        output_tokens += safe_output
        token_source_counts[source] = token_source_counts.get(source, 0) + 1
        bucket = _token_source_bucket(source)
        if bucket == "provider_reported":
            provider_reported_tokens += token_total
        elif bucket == "estimated":
            estimated_tokens += token_total
        elif bucket == "ignored":
            ignored_tokens += token_total
        if anomalous or source in {"ignored", "anomaly_corrected"}:
            token_anomaly_count += 1
        cost = _cost_payload(safe_input, safe_output, row.model_name, price_index)
        if cost["priced"]:
            priced_call_count += 1
            _add_currency_amount(cost_by_currency, str(cost["currency"]), float(cost["total_cost"]))
        elif token_total > 0:
            model_key = str(row.model_name or "default")
            item = unpriced_models.setdefault(
                model_key,
                {
                    "model_name": model_key,
                    "calls": 0,
                    "tokens": 0,
                    "reason": cost["price_missing_reason"],
                },
            )
            item["calls"] += 1
            item["tokens"] += token_total
        total_cost += float(cost["total_cost"])
        agent_key = str(row.agent_id or row.agent_name or "")
        model_key = str(row.model_name or "default")
        agent_token_totals[agent_key] = agent_token_totals.get(agent_key, 0) + token_total
        model_token_totals[model_key] = model_token_totals.get(model_key, 0) + token_total
        agent_cost_totals[agent_key] = agent_cost_totals.get(agent_key, 0.0) + float(cost["total_cost"])
        model_cost_totals[model_key] = model_cost_totals.get(model_key, 0.0) + float(cost["total_cost"])
        _add_currency_amount(
            agent_cost_currencies.setdefault(agent_key, {}),
            str(cost["currency"]),
            float(cost["total_cost"]),
        )
        _add_currency_amount(
            model_cost_currencies.setdefault(model_key, {}),
            str(cost["currency"]),
            float(cost["total_cost"]),
        )
        for tool in row.tools_used or []:
            tool_counts[str(tool)] = tool_counts.get(str(tool), 0) + 1
    pricing_percent = round(priced_call_count / total_calls * 100, 1) if total_calls else 0.0

    return {
        "days": days,
        "total_calls": total_calls,
        "total_tokens": int(input_tokens + output_tokens),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "token_anomaly_count": token_anomaly_count,
        "token_sources": {
            "provider_reported": provider_reported_tokens,
            "estimated": estimated_tokens,
            "ignored": ignored_tokens,
        },
        "token_source_counts": token_source_counts,
        "total_cost": round(total_cost, 6),
        "cost_by_currency": cost_by_currency,
        "currency": _dominant_currency(price_index),
        "priced_call_count": priced_call_count,
        "pricing_coverage": {
            "priced_calls": priced_call_count,
            "total_calls": total_calls,
            "percent": pricing_percent,
        },
        "unpriced_models": sorted(unpriced_models.values(), key=lambda item: item["tokens"], reverse=True)[:10],
        "avg_latency_ms": round(float(avg_latency), 1),
        "p95_latency_ms": p95_latency,
        "error_rate": error_rate,
        "error_count": error_count,
        "agent_count": agent_count,
        "status_breakdown": [
            {"status": row.status or "unknown", "count": row.count}
            for row in status_rows
        ],
        "top_agents": [
            {
                "agent_id": row.agent_id,
                "agent_name": row.agent_name,
                "calls": row.calls,
                "tokens": agent_token_totals.get(str(row.agent_id or row.agent_name or ""), 0),
                "cost": round(agent_cost_totals.get(str(row.agent_id or row.agent_name or ""), 0.0), 6),
                "cost_by_currency": agent_cost_currencies.get(str(row.agent_id or row.agent_name or ""), {}),
                "avg_latency_ms": round(float(row.avg_latency or 0), 1),
            }
            for row in agent_rows
        ],
        "top_models": [
            {
                "model_name": row.model_name or "default",
                "calls": row.calls,
                "tokens": model_token_totals.get(str(row.model_name or "default"), 0),
                "cost": round(model_cost_totals.get(str(row.model_name or "default"), 0.0), 6),
                "cost_by_currency": model_cost_currencies.get(str(row.model_name or "default"), {}),
                "avg_latency_ms": round(float(row.avg_latency or 0), 1),
            }
            for row in model_rows
        ],
        "top_tools": [
            {"name": name, "count": count}
            for name, count in sorted(tool_counts.items(), key=lambda item: item[1], reverse=True)[:10]
        ],
    }


@router.get("/timeseries")
async def get_timeseries(
    metric: str = Query("calls", pattern="^(calls|tokens|latency|errors|cost)$"),
    days: int = Query(7, ge=1, le=30),
):
    """Return hourly or daily time series for the requested metric."""
    from nexagent.costs import build_price_index
    from nexagent.db.models import InvocationLog, ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    since = datetime.utcnow() - timedelta(days=days)
    granularity = "hour" if days <= 3 else "day"

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(
                InvocationLog.created_at,
                InvocationLog.input_tokens,
                InvocationLog.output_tokens,
                InvocationLog.latency_ms,
                InvocationLog.status,
                InvocationLog.model_name,
            )
            .where(InvocationLog.created_at >= since)
            .order_by(InvocationLog.created_at)
        )).all()
        providers = (await session.execute(select(ModelProvider))).scalars().all()

    price_index = build_price_index(providers)
    # Bucket by hour or day
    buckets: dict[str, list] = {}
    for row in rows:
        dt = row.created_at
        if granularity == "hour":
            key = dt.strftime("%Y-%m-%dT%H:00")
        else:
            key = dt.strftime("%Y-%m-%d")
        buckets.setdefault(key, []).append(row)

    series = []
    for ts in sorted(buckets.keys()):
        bucket_rows = buckets[ts]
        if metric == "calls":
            value = len(bucket_rows)
        elif metric == "tokens":
            value = sum(
                safe_input + safe_output
                for safe_input, safe_output, _anomalous in (
                    _safe_tokens(r.input_tokens, r.output_tokens) for r in bucket_rows
                )
            )
        elif metric == "errors":
            value = sum(1 for r in bucket_rows if r.status == "error")
        elif metric == "cost":
            values: dict[str, float] = {}
            for row in bucket_rows:
                safe_input, safe_output, _anomalous = _safe_tokens(row.input_tokens, row.output_tokens)
                cost = _cost_payload(safe_input, safe_output, row.model_name, price_index)
                if cost["priced"]:
                    _add_currency_amount(values, str(cost["currency"]), float(cost["total_cost"]))
            value = next(iter(values.values()), 0.0)
        else:
            latencies = [r.latency_ms for r in bucket_rows if r.latency_ms]
            value = round(sum(latencies) / len(latencies), 1) if latencies else 0
        item = {"timestamp": ts, "value": value}
        if metric == "cost":
            item["values"] = values
        series.append(item)

    return {"metric": metric, "granularity": granularity, "series": series}


@router.get("/recent")
async def get_recent_logs(limit: int = Query(20, ge=1, le=100)):
    """Return the most recent invocation logs."""
    from nexagent.costs import build_price_index
    from nexagent.db.models import InvocationLog, ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(InvocationLog)
            .order_by(InvocationLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        providers = (await session.execute(select(ModelProvider))).scalars().all()

    price_index = build_price_index(providers)
    return {"logs": [_log_payload(log, price_index=price_index) for log in logs]}


@router.get("/agents/{agent_id}/stats")
async def get_agent_stats(agent_id: str, days: int = Query(7, ge=1, le=90)):
    """Return dashboard metrics for one configured Agent."""
    from nexagent.costs import build_price_index, cost_for_tokens, price_for_model
    from nexagent.db.models import InvocationLog, ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    since = datetime.utcnow() - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(InvocationLog)
            .where(InvocationLog.created_at >= since)
            .where(InvocationLog.agent_id == agent_id)
            .order_by(InvocationLog.created_at.desc())
        )).scalars().all()
        providers = (await session.execute(select(ModelProvider))).scalars().all()

    price_index = build_price_index(providers)
    calls = len(rows)
    token_total = sum(
        safe_input + safe_output
        for safe_input, safe_output, _anomalous in (
            _safe_tokens(row.input_tokens, row.output_tokens) for row in rows
        )
    )
    latencies = [row.latency_ms for row in rows if row.latency_ms]
    error_count = sum(1 for row in rows if row.status == "error")
    tools: dict[str, int] = {}
    total_cost = 0.0
    for row in rows:
        safe_input, safe_output, _anomalous = _safe_tokens(row.input_tokens, row.output_tokens)
        price = price_for_model(row.model_name, price_index)
        total_cost += float(cost_for_tokens(safe_input, safe_output, price)["total_cost"])
        for tool in row.tools_used or []:
            tools[tool] = tools.get(tool, 0) + 1

    return {
        "agent_id": agent_id,
        "days": days,
        "calls": calls,
        "tokens": token_total,
        "cost": round(total_cost, 6),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "error_rate": round(error_count / calls * 100, 1) if calls else 0.0,
        "top_tools": [
            {"name": name, "count": count}
            for name, count in sorted(tools.items(), key=lambda item: item[1], reverse=True)[:10]
        ],
        "recent": [_log_payload(row, price_index=price_index) for row in rows[:20]],
    }


@router.get("/pricing")
async def get_pricing():
    from nexagent.costs import build_price_index
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        providers = (await session.execute(select(ModelProvider).order_by(ModelProvider.created_at))).scalars().all()

    prices = build_price_index(providers)
    rows = []
    seen: set[tuple[str, str]] = set()
    for price in prices.values():
        key = (price.provider_id, price.model_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "provider_id": price.provider_id,
            "provider_name": price.provider_name,
            "model_id": price.model_id,
            "model_name": f"{price.provider_id}::{price.model_id}",
            "display_name": price.display_name,
            "input_price_per_1m": float(price.input_price_per_1m),
            "output_price_per_1m": float(price.output_price_per_1m),
            "currency": price.currency,
        })
    return {"prices": rows}


@router.get("/anomalies")
async def get_token_anomalies(limit: int = Query(50, ge=1, le=200)):
    from nexagent.db.models import InvocationLog
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(InvocationLog)
            .where(
                or_(
                    InvocationLog.token_source.in_(["ignored", "anomaly_corrected"]),
                    (InvocationLog.input_tokens + InvocationLog.output_tokens) > 2_000_000,
                    InvocationLog.input_tokens > 1_000_000,
                    InvocationLog.output_tokens > 1_000_000,
                )
            )
            .order_by(InvocationLog.created_at.desc())
            .limit(limit)
        )).scalars().all()

    return {
        "anomalies": [
            {
                **_log_payload(row),
                "repairable": bool(row.token_estimated and (row.input_tokens or row.output_tokens)),
            }
            for row in rows
        ]
    }


@router.post("/anomalies/repair")
async def repair_token_anomalies(body: AnomalyRepairRequest):
    from nexagent.db.models import InvocationLog
    from nexagent.db.session import AsyncSessionLocal

    if body.mode not in {"repair", "ignore"}:
        raise HTTPException(status_code=422, detail="mode must be repair or ignore")

    async with AsyncSessionLocal() as session:
        query = select(InvocationLog).where(
            or_(
                InvocationLog.token_source.in_(["ignored", "anomaly_corrected"]),
                (InvocationLog.input_tokens + InvocationLog.output_tokens) > 2_000_000,
                InvocationLog.input_tokens > 1_000_000,
                InvocationLog.output_tokens > 1_000_000,
            )
        )
        if body.ids:
            query = query.where(InvocationLog.id.in_(body.ids))
        rows = (await session.execute(query)).scalars().all()
        changed = 0
        for row in rows:
            if body.mode == "ignore":
                row.input_tokens = 0
                row.output_tokens = 0
                row.token_source = "ignored"
                row.token_estimated = False
                changed += 1
            elif row.token_estimated and (row.input_tokens or row.output_tokens):
                row.token_source = "anomaly_corrected"
                changed += 1
        await session.commit()
    return {"updated": changed, "mode": body.mode}


def _log_payload(row, price_index: dict | None = None) -> dict:
    payload = row.to_dict()
    safe_input, safe_output, anomalous, source, _token_total = _row_token_payload(row)
    payload["raw_input_tokens"] = int(getattr(row, "raw_input_tokens", None) or row.input_tokens or 0)
    payload["raw_output_tokens"] = int(getattr(row, "raw_output_tokens", None) or row.output_tokens or 0)
    payload["raw_total_tokens"] = payload["raw_input_tokens"] + payload["raw_output_tokens"]
    payload["input_tokens"] = safe_input
    payload["output_tokens"] = safe_output
    payload["total_tokens"] = safe_input + safe_output
    payload["token_source"] = source
    payload["token_estimated"] = bool(getattr(row, "token_estimated", False))
    payload["token_usage_anomalous"] = anomalous or payload["token_source"] in {"ignored", "anomaly_corrected"}
    payload.update(_cost_payload(safe_input, safe_output, row.model_name, price_index or {}))
    return payload


def _dominant_currency(price_index: dict) -> str:
    for price in price_index.values():
        if price.currency:
            return price.currency
    return "USD"
