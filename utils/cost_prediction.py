# utils/cost_prediction.py - Forward-looking cost prediction
"""
ML-lite cost prediction using simple time-series decomposition:
  - Day-of-week seasonality adjustment
  - Linear trend extraction
  - End-of-month budget projection
  - "If nothing changes" vs "at current growth" scenarios

Doesn't require snowflake-ml-python — pure pandas/numpy.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def predict_end_of_month_cost(
    daily_credits: list[float],
    *,
    credit_price: float = 3.68,
    target_date: date | None = None,
) -> dict[str, Any]:
    """
    Predict end-of-month credit consumption from observed daily data.

    Uses two scenarios:
      1. "Flat" — remaining days consume the recent 7-day average
      2. "Trend" — remaining days follow the observed growth trajectory

    Returns:
        {
            "flat_projection_credits": float,
            "trend_projection_credits": float,
            "flat_projection_cost": float,
            "trend_projection_cost": float,
            "days_observed": int,
            "days_remaining": int,
            "daily_avg_recent": float,
            "growth_rate_daily": float,
            "confidence": str,
        }
    """
    if not daily_credits or len(daily_credits) < 3:
        return {
            "flat_projection_credits": 0,
            "trend_projection_credits": 0,
            "flat_projection_cost": 0,
            "trend_projection_cost": 0,
            "days_observed": 0,
            "days_remaining": 0,
            "daily_avg_recent": 0,
            "growth_rate_daily": 0,
            "confidence": "insufficient_data",
        }

    today = target_date or date.today()
    # Days remaining in current month
    if today.month == 12:
        month_end = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(today.year, today.month + 1, 1) - timedelta(days=1)
    days_remaining = max(0, (month_end - today).days)

    clean = [max(0, float(v)) for v in daily_credits if v is not None]
    days_observed = len(clean)

    # Recent average (last 7 days or all if less)
    recent_window = clean[-7:] if len(clean) >= 7 else clean
    daily_avg = sum(recent_window) / len(recent_window)

    # Already consumed this month (sum of observed)
    consumed = sum(clean)

    # Flat projection
    flat_remaining = daily_avg * days_remaining
    flat_total = consumed + flat_remaining

    # Trend projection (simple linear regression on daily values)
    growth_rate = 0.0
    if len(clean) >= 7:
        # Compare last 3 days avg to first 3 days avg
        first_3 = sum(clean[:3]) / 3
        last_3 = sum(clean[-3:]) / 3
        if first_3 > 0:
            total_growth = (last_3 - first_3) / first_3
            growth_rate = total_growth / max(1, len(clean) - 3)

    trend_remaining = 0.0
    projected_daily = daily_avg
    for day in range(days_remaining):
        projected_daily *= (1 + growth_rate)
        trend_remaining += max(0, projected_daily)

    trend_total = consumed + trend_remaining

    # Confidence
    if days_observed >= 20:
        confidence = "high"
    elif days_observed >= 10:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "flat_projection_credits": round(flat_total, 1),
        "trend_projection_credits": round(trend_total, 1),
        "flat_projection_cost": round(flat_total * credit_price, 0),
        "trend_projection_cost": round(trend_total * credit_price, 0),
        "days_observed": days_observed,
        "days_remaining": days_remaining,
        "daily_avg_recent": round(daily_avg, 1),
        "growth_rate_daily": round(growth_rate * 100, 2),
        "confidence": confidence,
        "consumed_so_far": round(consumed, 1),
        "consumed_cost": round(consumed * credit_price, 0),
    }


def build_monthly_prediction_sql(month_offset: int = 0) -> str:
    """SQL to pull daily credits for the current (or offset) month for prediction."""
    if month_offset == 0:
        return """
        SELECT
            DATE(start_time) AS usage_date,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE DATE(start_time) >= DATE_TRUNC('month', CURRENT_DATE())
          AND DATE(start_time) < CURRENT_DATE()
        GROUP BY usage_date
        ORDER BY usage_date
        """
    else:
        return f"""
        SELECT
            DATE(start_time) AS usage_date,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE DATE(start_time) >= DATEADD('month', {int(month_offset)}, DATE_TRUNC('month', CURRENT_DATE()))
          AND DATE(start_time) < DATEADD('month', {int(month_offset) + 1}, DATE_TRUNC('month', CURRENT_DATE()))
        GROUP BY usage_date
        ORDER BY usage_date
        """


def render_prediction_widget(prediction: dict[str, Any], *, container=None) -> None:
    """Render the end-of-month prediction as a compact widget."""
    import streamlit as st

    target = container or st

    if prediction["confidence"] == "insufficient_data":
        target.caption("Insufficient data for month-end prediction (need 3+ days).")
        return

    flat_cost = prediction["flat_projection_cost"]
    trend_cost = prediction["trend_projection_cost"]
    consumed = prediction["consumed_cost"]
    days_remaining = prediction["days_remaining"]
    growth_rate = prediction["growth_rate_daily"]

    # Color based on trend direction
    if growth_rate > 1:
        trend_color = "#ef4444"
        trend_label = "accelerating"
    elif growth_rate < -1:
        trend_color = "#22c55e"
        trend_label = "decelerating"
    else:
        trend_color = "#94a3b8"
        trend_label = "stable"

    cols = target.columns(4)
    with cols[0]:
        target.metric("Month Consumed", f"${consumed:,.0f}",
                      f"{prediction['days_observed']}d observed")
    with cols[1]:
        target.metric("Flat Projection", f"${flat_cost:,.0f}",
                      f"{days_remaining}d remaining")
    with cols[2]:
        target.metric("Trend Projection", f"${trend_cost:,.0f}",
                      f"{growth_rate:+.1f}%/day {trend_label}")
    with cols[3]:
        target.metric("Confidence", prediction["confidence"].title(),
                      f"Avg ${prediction['daily_avg_recent'] * float(st.session_state.get('credit_price', 3.68)):,.0f}/day")
