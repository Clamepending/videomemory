"""Usage tracking helpers for VLM calls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional
import time


@dataclass(frozen=True)
class ModelUsageEvent:
    """Normalized usage record for one model invocation."""

    provider_name: str
    model_name: str
    api_model_name: str
    source: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None
    was_success: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/DB-friendly dict."""
        return asdict(self)


_MODEL_PRICE_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    # Google
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    # OpenAI
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    # Anthropic
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4-6": (5.00, 25.00),
    # OpenRouter
    "qwen3-vl-8b": (0.08, 0.50),
    "mistral-small-3.1": (0.00, 0.00),
    "molmo-2-8b": (0.00, 0.00),
    # Local/self-hosted
    "local-vllm": (0.00, 0.00),
}

_MODEL_PRICE_ALIASES = {
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4.1-nano-2025-04-14": "gpt-4.1-nano",
    "claude-sonnet-4": "claude-sonnet-4-6",
    "claude-sonnet-4-20250514": "claude-sonnet-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5",
    "claude-opus-4": "claude-opus-4-6",
    "claude-opus-4-20250514": "claude-opus-4-6",
    "claude-opus-4-1": "claude-opus-4-6",
    "claude-opus-4-1-20250805": "claude-opus-4-6",
    "qwen/qwen3-vl-8b-instruct": "qwen3-vl-8b",
    "qwen/qwen-2-vl-7b-instruct": "qwen-2-vl-7b",
    "qwen/qwen-2.5-vl-7b-instruct": "qwen-2-vl-7b",
    "microsoft/phi-4-multimodal-instruct": "phi-4-multimodal",
    "mistralai/mistral-small-3.1-24b-instruct": "mistral-small-3.1",
    "mistralai/mistral-small-3.1-24b-instruct:free": "mistral-small-3.1",
    "molmo/molmo-2-8b-free": "molmo-2-8b",
    "local-vllm": "local-vllm",
}

_RANGE_SPECS = {
    "day": {
        "bucket_count": 24,
        "bucket_size": timedelta(hours=1),
        "display_name": "Last 24 Hours",
    },
    "week": {
        "bucket_count": 7,
        "bucket_size": timedelta(days=1),
        "display_name": "Last 7 Days",
    },
    "month": {
        "bucket_count": 30,
        "bucket_size": timedelta(days=1),
        "display_name": "Last 30 Days",
    },
}


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_usage_model_name(model_name: Optional[str]) -> Optional[str]:
    """Normalize a model name into the pricing/usage key used by the UI."""
    if model_name is None:
        return None
    normalized = str(model_name).strip().lower()
    if not normalized:
        return None
    return _MODEL_PRICE_ALIASES.get(normalized, normalized)


def estimate_model_cost_usd(
    model_name: Optional[str],
    *,
    api_model_name: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
) -> Optional[float]:
    """Estimate per-call cost in USD from token counts when pricing is known."""
    normalized = normalize_usage_model_name(model_name)
    if normalized is None and api_model_name is not None:
        normalized = normalize_usage_model_name(api_model_name)
    if normalized is None:
        return None

    pricing = _MODEL_PRICE_USD_PER_MILLION.get(normalized)
    if pricing is None:
        api_normalized = normalize_usage_model_name(api_model_name)
        if api_normalized is not None:
            pricing = _MODEL_PRICE_USD_PER_MILLION.get(api_normalized)
    if pricing is None:
        return None

    input_rate, output_rate = pricing
    input_count = max(0, input_tokens or 0)
    output_count = max(0, output_tokens or 0)
    return round((input_count * input_rate + output_count * output_rate) / 1_000_000.0, 8)


def coerce_usage_event(data: Mapping[str, Any]) -> ModelUsageEvent:
    """Convert a DB/API row into a typed usage event."""
    input_tokens = _coerce_optional_int(data.get("input_tokens"))
    output_tokens = _coerce_optional_int(data.get("output_tokens"))
    total_tokens = _coerce_optional_int(data.get("total_tokens"))
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = max(0, input_tokens or 0) + max(0, output_tokens or 0)

    estimated_cost_usd = _coerce_optional_float(data.get("estimated_cost_usd"))
    latency_ms = _coerce_optional_float(data.get("latency_ms"))

    return ModelUsageEvent(
        provider_name=str(data.get("provider_name") or ""),
        model_name=str(data.get("model_name") or ""),
        api_model_name=str(data.get("api_model_name") or data.get("model_name") or ""),
        source=str(data.get("source") or "unknown"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        latency_ms=latency_ms,
        was_success=bool(data.get("was_success", True)),
        created_at=float(data.get("created_at") or time.time()),
    )


def build_usage_dashboard_payload(
    events: Iterable[Mapping[str, Any]],
    *,
    range_key: str,
    recent_events: Optional[Iterable[Mapping[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Aggregate raw events for the Usage page/API."""
    normalized_range = range_key if range_key in _RANGE_SPECS else "month"
    spec = _RANGE_SPECS[normalized_range]
    now_dt = (now or datetime.now().astimezone()).replace(microsecond=0)
    bucket_size: timedelta = spec["bucket_size"]

    if bucket_size >= timedelta(days=1):
        bucket_end = now_dt.replace(hour=0, minute=0, second=0)
    else:
        bucket_end = now_dt.replace(minute=0, second=0)

    bucket_starts = [
        bucket_end - bucket_size * (spec["bucket_count"] - idx - 1)
        for idx in range(spec["bucket_count"])
    ]
    if bucket_size >= timedelta(days=1):
        bucket_starts = [value.replace(hour=0, minute=0, second=0) for value in bucket_starts]

    buckets: list[dict[str, Any]] = []
    bucket_index_by_key: dict[int, int] = {}
    for idx, bucket_start in enumerate(bucket_starts):
        if bucket_size >= timedelta(days=1):
            label = bucket_start.strftime("%b %d").replace(" 0", " ")
        else:
            label = bucket_start.strftime("%-I %p")
        bucket = {
            "bucket_start": bucket_start.isoformat(),
            "bucket_start_ts": bucket_start.timestamp(),
            "label": label,
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "cost_covered_calls": 0,
            "token_covered_calls": 0,
            "success_calls": 0,
            "models": {},
        }
        buckets.append(bucket)
        bucket_index_by_key[int(bucket_start.timestamp())] = idx

    summary = {
        "calls": 0,
        "success_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "token_covered_calls": 0,
        "cost_covered_calls": 0,
        "range_name": spec["display_name"],
        "coverage_notes": [],
    }
    model_totals: dict[str, dict[str, Any]] = {}

    for raw_event in events:
        event = coerce_usage_event(raw_event)
        created_at_dt = datetime.fromtimestamp(event.created_at, tz=now_dt.tzinfo)
        if created_at_dt < bucket_starts[0]:
            continue

        if bucket_size >= timedelta(days=1):
            bucket_key = int(created_at_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        else:
            bucket_key = int(created_at_dt.replace(minute=0, second=0, microsecond=0).timestamp())
        bucket_idx = bucket_index_by_key.get(bucket_key)
        if bucket_idx is None:
            continue
        bucket = buckets[bucket_idx]

        model_key = normalize_usage_model_name(event.model_name) or event.model_name or "unknown"
        model_entry = bucket["models"].setdefault(
            model_key,
            {
                "calls": 0,
                "success_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "token_covered_calls": 0,
                "cost_covered_calls": 0,
            },
        )
        total_entry = model_totals.setdefault(
            model_key,
            {
                "model_name": model_key,
                "api_model_name": event.api_model_name or event.model_name or model_key,
                "provider_name": event.provider_name,
                "calls": 0,
                "success_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "token_covered_calls": 0,
                "cost_covered_calls": 0,
            },
        )

        summary["calls"] += 1
        bucket["calls"] += 1
        model_entry["calls"] += 1
        total_entry["calls"] += 1

        if event.was_success:
            summary["success_calls"] += 1
            bucket["success_calls"] += 1
            model_entry["success_calls"] += 1
            total_entry["success_calls"] += 1

        token_known = any(value is not None for value in (event.input_tokens, event.output_tokens, event.total_tokens))
        if token_known:
            summary["token_covered_calls"] += 1
            bucket["token_covered_calls"] += 1
            model_entry["token_covered_calls"] += 1
            total_entry["token_covered_calls"] += 1

        input_tokens = max(0, event.input_tokens or 0)
        output_tokens = max(0, event.output_tokens or 0)
        total_tokens = max(0, event.total_tokens or (input_tokens + output_tokens))

        summary["input_tokens"] += input_tokens
        summary["output_tokens"] += output_tokens
        summary["total_tokens"] += total_tokens
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        model_entry["input_tokens"] += input_tokens
        model_entry["output_tokens"] += output_tokens
        model_entry["total_tokens"] += total_tokens
        total_entry["input_tokens"] += input_tokens
        total_entry["output_tokens"] += output_tokens
        total_entry["total_tokens"] += total_tokens

        if event.estimated_cost_usd is not None:
            cost = float(event.estimated_cost_usd)
            summary["estimated_cost_usd"] += cost
            summary["cost_covered_calls"] += 1
            bucket["estimated_cost_usd"] += cost
            bucket["cost_covered_calls"] += 1
            model_entry["estimated_cost_usd"] += cost
            model_entry["cost_covered_calls"] += 1
            total_entry["estimated_cost_usd"] += cost
            total_entry["cost_covered_calls"] += 1

    if summary["token_covered_calls"] < summary["calls"]:
        summary["coverage_notes"].append(
            f"Token counts were available for {summary['token_covered_calls']} of {summary['calls']} calls."
        )
    if summary["cost_covered_calls"] < summary["calls"]:
        summary["coverage_notes"].append(
            f"Estimated spend was available for {summary['cost_covered_calls']} of {summary['calls']} calls."
        )

    recent = [coerce_usage_event(item).to_dict() for item in (recent_events if recent_events is not None else events)]
    recent.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)

    return {
        "range": normalized_range,
        "summary": {
            **summary,
            "estimated_cost_usd": round(summary["estimated_cost_usd"], 8),
        },
        "buckets": [
            {
                **bucket,
                "estimated_cost_usd": round(bucket["estimated_cost_usd"], 8),
                "models": {
                    model_name: {
                        **model_values,
                        "estimated_cost_usd": round(model_values["estimated_cost_usd"], 8),
                    }
                    for model_name, model_values in bucket["models"].items()
                },
            }
            for bucket in buckets
        ],
        "models": sorted(
            [
                {
                    **values,
                    "estimated_cost_usd": round(values["estimated_cost_usd"], 8),
                }
                for values in model_totals.values()
            ],
            key=lambda item: (
                -float(item.get("estimated_cost_usd") or 0.0),
                -int(item.get("calls") or 0),
                str(item.get("model_name") or ""),
            ),
        ),
        "recent_events": recent,
    }
