# utils/trend_analysis.py - Time-series trend helpers for all sections
"""
Shared trend computation used across shells and workspaces:
  - Week-over-week delta calculation
  - Month-over-month comparison
  - Trend direction classification
  - Percentage change with directional arrows
  - Moving average computation

These feed the KPI delta indicators so every metric shows "↑12%" or "↓3%"
instead of raw numbers with no context.
"""
from __future__ import annotations

from typing import Any, Sequence


def compute_wow_delta(values: Sequence[float]) -> dict[str, Any]:
    """
    Compute week-over-week delta from a daily time series.

    Expects at least 8 values (7 recent + 1 prior day minimum).
    Returns: {delta_pct, direction, arrow, recent_avg, prior_avg}
    """
    clean = [float(v) for v in values if v is not None and v == v]
    if len(clean) < 8:
        return {"delta_pct": 0.0, "direction": "flat", "arrow": "→", "recent_avg": 0.0, "prior_avg": 0.0}

    recent_7 = clean[-7:]
    prior_7 = clean[-14:-7] if len(clean) >= 14 else clean[:len(clean) - 7]

    recent_avg = sum(recent_7) / len(recent_7)
    prior_avg = sum(prior_7) / len(prior_7) if prior_7 else recent_avg

    if prior_avg == 0:
        return {"delta_pct": 0.0, "direction": "flat", "arrow": "→", "recent_avg": recent_avg, "prior_avg": prior_avg}

    delta_pct = ((recent_avg - prior_avg) / prior_avg) * 100

    if delta_pct > 5:
        direction, arrow = "up", "↑"
    elif delta_pct < -5:
        direction, arrow = "down", "↓"
    else:
        direction, arrow = "flat", "→"

    return {
        "delta_pct": round(delta_pct, 1),
        "direction": direction,
        "arrow": arrow,
        "recent_avg": round(recent_avg, 2),
        "prior_avg": round(prior_avg, 2),
    }


def format_delta(delta_pct: float, *, invert: bool = False) -> str:
    """
    Format a percentage delta with arrow and sign for display.

    Args:
        delta_pct: The percentage change
        invert: If True, positive = good (e.g., for SLA compliance)
    """
    if abs(delta_pct) < 0.5:
        return "→ flat"
    arrow = "↑" if delta_pct > 0 else "↓"
    return f"{arrow}{abs(delta_pct):.1f}%"


def classify_trend(values: Sequence[float], *, periods: int = 3) -> str:
    """
    Classify overall trend direction from a sequence.

    Returns: "accelerating", "decelerating", "stable", "volatile", "insufficient"
    """
    clean = [float(v) for v in values if v is not None and v == v]
    if len(clean) < periods + 1:
        return "insufficient"

    # Compute period-over-period deltas
    chunk_size = max(1, len(clean) // periods)
    chunks = [clean[i:i + chunk_size] for i in range(0, len(clean), chunk_size)]
    if len(chunks) < 2:
        return "insufficient"

    avgs = [sum(c) / len(c) for c in chunks if c]
    if len(avgs) < 2:
        return "insufficient"

    # Check direction consistency
    deltas = [avgs[i] - avgs[i - 1] for i in range(1, len(avgs))]
    positive = sum(1 for d in deltas if d > 0)
    negative = sum(1 for d in deltas if d < 0)

    if positive == len(deltas):
        return "accelerating"
    if negative == len(deltas):
        return "decelerating"
    if abs(sum(deltas)) / max(1, sum(abs(d) for d in deltas)) < 0.3:
        return "volatile"
    return "stable"


def moving_average(values: Sequence[float], window: int = 7) -> list[float]:
    """Compute simple moving average."""
    clean = [float(v) if v is not None and v == v else 0.0 for v in values]
    if len(clean) < window:
        return clean

    result = []
    for i in range(len(clean)):
        start = max(0, i - window + 1)
        window_vals = clean[start:i + 1]
        result.append(round(sum(window_vals) / len(window_vals), 2))
    return result


def compute_metric_with_delta(
    current_value: float,
    historical_values: Sequence[float],
) -> tuple[str, str | None]:
    """
    Format a metric value with its WoW delta for KPI display.

    Returns: (formatted_value, delta_string_or_none)
    """
    wow = compute_wow_delta(list(historical_values) + [current_value])
    delta_str = None
    if abs(wow["delta_pct"]) >= 1.0:
        delta_str = format_delta(wow["delta_pct"])
    return f"{current_value:,.0f}", delta_str
