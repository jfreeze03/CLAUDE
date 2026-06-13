# utils/contract_forecast.py - Predictive contract burn and capacity forecasting
"""
Computes:
  - Days remaining at current burn rate
  - Projected exhaustion date
  - Burn rate trend (accelerating/decelerating/stable)
  - Contract utilization percentage

This answers the CIO question: "When do we run out of credits?"
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_contract_burn_sql(days_back: int = 90) -> str:
    """SQL to pull daily credit consumption for burn rate calculation.

    Uses METERING_HISTORY as the source of truth for total account consumption.
    Returns daily totals for the specified lookback window.
    """
    days_back = max(7, int(days_back or 90))
    return f"""
    SELECT
        DATE(start_time) AS usage_date,
        ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits,
        COUNT(DISTINCT service_type) AS service_count
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND start_time < CURRENT_DATE()
    GROUP BY DATE(start_time)
    ORDER BY usage_date
    """


def build_contract_capacity_sql() -> str:
    """SQL to pull contract capacity from REMAINING_BALANCE_DAILY (if available).

    Falls back gracefully — many accounts don't have this view populated.
    """
    return """
    SELECT
        DATE AS balance_date,
        COALESCE(FREE_USAGE_BALANCE, 0) + COALESCE(CAPACITY_BALANCE, 0)
            + COALESCE(ROLLOVER_BALANCE, 0) AS total_remaining_credits,
        COALESCE(CAPACITY_BALANCE, 0) AS capacity_balance,
        COALESCE(ON_DEMAND_CONSUMPTION_BALANCE, 0) AS on_demand_balance,
        COALESCE(ROLLOVER_BALANCE, 0) AS rollover_balance
    FROM SNOWFLAKE.ORGANIZATION_USAGE.REMAINING_BALANCE_DAILY
    WHERE DATE >= DATEADD('day', -7, CURRENT_DATE())
    ORDER BY DATE DESC
    LIMIT 7
    """


def compute_burn_forecast(
    daily_credits_df,
    contract_remaining: float | None = None,
    contract_total: float | None = None,
) -> dict[str, Any]:
    """
    Compute burn rate forecast from daily credit consumption data.

    Args:
        daily_credits_df: DataFrame with columns [usage_date, daily_credits]
        contract_remaining: Remaining credits in the contract (if known)
        contract_total: Total contract capacity (if known)

    Returns:
        {
            "daily_burn_rate": float,
            "weekly_burn_rate": float,
            "monthly_burn_rate": float,
            "burn_trend": str ("accelerating", "decelerating", "stable"),
            "burn_trend_pct": float (week-over-week change),
            "days_remaining": int | None (None if contract capacity unknown),
            "projected_exhaustion_date": date | None,
            "utilization_pct": float | None,
            "confidence": str ("high", "medium", "low"),
            "observed_days": int,
            "recent_7d_avg": float,
            "prior_7d_avg": float,
        }
    """
    import pandas as pd

    result = {
        "daily_burn_rate": 0.0,
        "weekly_burn_rate": 0.0,
        "monthly_burn_rate": 0.0,
        "burn_trend": "unknown",
        "burn_trend_pct": 0.0,
        "days_remaining": None,
        "projected_exhaustion_date": None,
        "utilization_pct": None,
        "confidence": "low",
        "observed_days": 0,
        "recent_7d_avg": 0.0,
        "prior_7d_avg": 0.0,
    }

    if daily_credits_df is None or not isinstance(daily_credits_df, pd.DataFrame):
        return result
    if daily_credits_df.empty:
        return result

    df = daily_credits_df.copy()

    # Normalize column names
    df.columns = [c.upper() for c in df.columns]
    if "DAILY_CREDITS" not in df.columns:
        return result

    df["DAILY_CREDITS"] = pd.to_numeric(df["DAILY_CREDITS"], errors="coerce").fillna(0)

    if "USAGE_DATE" in df.columns:
        df["USAGE_DATE"] = pd.to_datetime(df["USAGE_DATE"], errors="coerce")
        df = df.dropna(subset=["USAGE_DATE"]).sort_values("USAGE_DATE")

    observed_days = len(df)
    result["observed_days"] = observed_days

    if observed_days < 3:
        return result

    # Calculate burn rates
    total_credits = df["DAILY_CREDITS"].sum()
    daily_avg = total_credits / observed_days
    result["daily_burn_rate"] = round(daily_avg, 2)
    result["weekly_burn_rate"] = round(daily_avg * 7, 2)
    result["monthly_burn_rate"] = round(daily_avg * 30, 2)

    # Trend detection: compare recent 7 days vs prior 7 days
    if observed_days >= 14:
        recent_7 = df.tail(7)["DAILY_CREDITS"].mean()
        prior_7 = df.iloc[-14:-7]["DAILY_CREDITS"].mean()
        result["recent_7d_avg"] = round(recent_7, 2)
        result["prior_7d_avg"] = round(prior_7, 2)

        if prior_7 > 0:
            trend_pct = ((recent_7 - prior_7) / prior_7) * 100
            result["burn_trend_pct"] = round(trend_pct, 1)
            if trend_pct > 10:
                result["burn_trend"] = "accelerating"
            elif trend_pct < -10:
                result["burn_trend"] = "decelerating"
            else:
                result["burn_trend"] = "stable"
        else:
            result["burn_trend"] = "stable"

        result["confidence"] = "high" if observed_days >= 30 else "medium"
    elif observed_days >= 7:
        recent = df.tail(7)["DAILY_CREDITS"].mean()
        result["recent_7d_avg"] = round(recent, 2)
        result["burn_trend"] = "stable"
        result["confidence"] = "medium"
    else:
        result["confidence"] = "low"
        result["burn_trend"] = "unknown"

    # Forecast exhaustion if contract info available
    burn_rate_for_forecast = result["recent_7d_avg"] if result["recent_7d_avg"] > 0 else daily_avg

    if contract_remaining and contract_remaining > 0 and burn_rate_for_forecast > 0:
        days_left = int(contract_remaining / burn_rate_for_forecast)
        result["days_remaining"] = days_left
        result["projected_exhaustion_date"] = date.today() + timedelta(days=days_left)

    if contract_total and contract_total > 0:
        if contract_remaining is not None:
            used = contract_total - contract_remaining
            result["utilization_pct"] = round((used / contract_total) * 100, 1)
        elif total_credits > 0:
            # Approximate from observed consumption
            result["utilization_pct"] = round((total_credits / contract_total) * 100, 1)

    return result


def render_contract_burn_widget(
    forecast: dict[str, Any],
    *,
    container=None,
    compact: bool = False,
) -> None:
    """Render the contract burn forecast as a Streamlit widget."""
    import html as html_mod

    target = container or st

    days_remaining = forecast.get("days_remaining")
    daily_rate = forecast.get("daily_burn_rate", 0)
    trend = forecast.get("burn_trend", "unknown")
    trend_pct = forecast.get("burn_trend_pct", 0)
    confidence = forecast.get("confidence", "low")
    utilization = forecast.get("utilization_pct")
    exhaustion_date = forecast.get("projected_exhaustion_date")

    # Color coding
    if days_remaining is not None:
        if days_remaining < 30:
            status_color = "#ef4444"
            status_label = "CRITICAL"
        elif days_remaining < 90:
            status_color = "#f97316"
            status_label = "WARNING"
        elif days_remaining < 180:
            status_color = "#f59e0b"
            status_label = "WATCH"
        else:
            status_color = "#22c55e"
            status_label = "HEALTHY"
    else:
        status_color = "#64748b"
        status_label = "NO CONTRACT DATA"

    trend_icons = {"accelerating": "↑ Accelerating", "decelerating": "↓ Decelerating", "stable": "→ Stable", "unknown": "· Unknown"}
    trend_colors = {"accelerating": "#ef4444", "decelerating": "#22c55e", "stable": "#94a3b8", "unknown": "#64748b"}

    if compact:
        days_text = f"{days_remaining}d remaining" if days_remaining else "N/A"
        rate_text = f"{daily_rate:,.0f} cr/day"
        target.markdown(
            f'<div style="font-size:0.75rem;color:var(--text-secondary,#cbd5e1);">'
            f'<span style="color:{status_color};font-weight:700;">{status_label}</span> · '
            f'{days_text} · {rate_text} · '
            f'<span style="color:{trend_colors[trend]};">{trend_icons[trend]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # Full widget
    cols = target.columns(4)
    with cols[0]:
        if days_remaining is not None:
            target_label = f"{days_remaining}"
            if exhaustion_date:
                target.metric(
                    "Days Remaining",
                    target_label,
                    delta=f"Exhaust {exhaustion_date.strftime('%b %d, %Y')}",
                    delta_color="inverse",
                )
            else:
                target.metric("Days Remaining", target_label)
        else:
            target.metric("Days Remaining", "—", help="Configure contract capacity to enable forecasting")

    with cols[1]:
        from .cost import get_credit_price
        monthly_cost = forecast.get("monthly_burn_rate", 0) * get_credit_price()
        target.metric(
            "Monthly Burn",
            f"${monthly_cost:,.0f}",
            delta=f"{daily_rate:,.0f} cr/day",
        )

    with cols[2]:
        if utilization is not None:
            target.metric("Contract Used", f"{utilization:.1f}%")
        else:
            target.metric("Contract Used", "—")

    with cols[3]:
        trend_label = trend_icons.get(trend, "Unknown")
        delta_str = f"{trend_pct:+.1f}% WoW" if trend_pct != 0 else "Flat"
        target.metric("Burn Trend", trend_label.split(" ")[1] if " " in trend_label else trend_label, delta=delta_str)

    # Confidence note
    target.caption(
        f"Confidence: {confidence} · "
        f"Based on {forecast.get('observed_days', 0)} observed days · "
        f"Recent 7d avg: {forecast.get('recent_7d_avg', 0):,.1f} cr/day"
    )
