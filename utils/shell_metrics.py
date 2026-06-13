# utils/shell_metrics.py - Cross-cutting shell metric enrichments
"""
Provides shared enrichment functions that every shell uses to reach 95:
  - Trend deltas (WoW ↑/↓ for every KPI)
  - Loaded-at timestamp display
  - Source confidence badges
  - MTTR computation
  - Alert age tracking
  - SLA from timestamps
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any, Sequence

import streamlit as st


# ─── Loaded-at timestamp ─────────────────────────────────────────────────────

def render_loaded_at(key: str = "", *, container=None) -> None:
    """Show when evidence was last loaded for data age visibility."""
    target = container or st
    ts = st.session_state.get(f"{key}_loaded_at") or st.session_state.get(f"{key}__loaded_at")
    if ts:
        target.caption(f"Evidence loaded: {ts}")
    else:
        target.caption(f"Shell rendered: {datetime.now().strftime('%H:%M:%S')}")


def mark_evidence_loaded(key: str) -> None:
    """Stamp when evidence was loaded for freshness display."""
    st.session_state[f"{key}__loaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─── Trend delta formatting ──────────────────────────────────────────────────

def kpi_with_trend(
    label: str,
    current_value: float,
    historical_values: Sequence[float] | None = None,
    *,
    format_str: str = "{:,.0f}",
    prefix: str = "",
    invert: bool = False,
) -> tuple[str, str, str | None]:
    """
    Build a KPI tuple (label, value, delta) with WoW trend.

    Args:
        label: KPI label
        current_value: Current numeric value
        historical_values: Past values for trend (7+ needed)
        format_str: Format for the value
        prefix: Prefix like "$"
        invert: If True, rising = good (SLA), falling = bad

    Returns:
        Tuple suitable for render_kpi_row: (label, formatted_value, delta_string)
    """
    formatted = f"{prefix}{format_str.format(current_value)}"

    if not historical_values or len(historical_values) < 2:
        return (label, formatted, None)

    values = [float(v) for v in historical_values if v is not None]
    if len(values) < 7:
        return (label, formatted, None)

    recent_avg = sum(values[-7:]) / 7
    prior_avg = sum(values[-14:-7]) / 7 if len(values) >= 14 else sum(values[:len(values) - 7]) / max(1, len(values) - 7)

    if prior_avg == 0:
        return (label, formatted, None)

    delta_pct = ((recent_avg - prior_avg) / prior_avg) * 100

    if abs(delta_pct) < 1.0:
        return (label, formatted, "→ flat")

    arrow = "↑" if delta_pct > 0 else "↓"
    delta_str = f"{arrow}{abs(delta_pct):.0f}% WoW"

    return (label, formatted, delta_str)


# ─── MTTR computation ─────────────────────────────────────────────────────────

def compute_mttr(action_queue_df) -> float | None:
    """
    Compute Mean Time To Resolution in hours from the action queue.
    Uses CREATED_AT and FIXED_AT timestamps.

    Returns hours or None if insufficient data.
    """
    import pandas as pd

    if not isinstance(action_queue_df, pd.DataFrame) or action_queue_df.empty:
        return None

    if "CREATED_AT" not in action_queue_df.columns or "FIXED_AT" not in action_queue_df.columns:
        return None

    resolved = action_queue_df.dropna(subset=["FIXED_AT"])
    if resolved.empty:
        return None

    created = pd.to_datetime(resolved["CREATED_AT"], errors="coerce")
    fixed = pd.to_datetime(resolved["FIXED_AT"], errors="coerce")
    valid = created.notna() & fixed.notna()

    if valid.sum() == 0:
        return None

    durations = (fixed[valid] - created[valid]).dt.total_seconds() / 3600
    positive = durations[durations > 0]

    if positive.empty:
        return None

    return round(float(positive.mean()), 1)


# ─── Alert age tracking ──────────────────────────────────────────────────────

def compute_alert_age(alert_df) -> dict[str, Any]:
    """
    Compute alert age metrics for open alerts.

    Returns:
        {
            "oldest_hours": float (age of oldest open alert in hours),
            "avg_hours": float,
            "pct_resolved_24h": float (% resolved within 24h),
            "total_open": int,
        }
    """
    import pandas as pd

    result = {"oldest_hours": 0, "avg_hours": 0, "pct_resolved_24h": 0, "total_open": 0}

    if not isinstance(alert_df, pd.DataFrame) or alert_df.empty:
        return result
    if "STATUS" not in alert_df.columns:
        return result

    # Open alerts age
    open_mask = alert_df["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"])
    open_alerts = alert_df[open_mask]
    result["total_open"] = len(open_alerts)

    if "CREATED_AT" in alert_df.columns and not open_alerts.empty:
        created = pd.to_datetime(open_alerts["CREATED_AT"], errors="coerce")
        valid_created = created.dropna()
        if not valid_created.empty:
            now = pd.Timestamp.now()
            ages_hours = (now - valid_created).dt.total_seconds() / 3600
            result["oldest_hours"] = round(float(ages_hours.max()), 1)
            result["avg_hours"] = round(float(ages_hours.mean()), 1)

    # Resolution SLA: % resolved within 24h
    resolved_mask = alert_df["STATUS"].str.upper().isin(["RESOLVED", "FIXED", "CLOSED"])
    resolved = alert_df[resolved_mask]
    if not resolved.empty and "CREATED_AT" in resolved.columns and "FIXED_AT" in alert_df.columns:
        created = pd.to_datetime(resolved["CREATED_AT"], errors="coerce")
        fixed = pd.to_datetime(resolved.get("FIXED_AT", pd.Series(dtype="datetime64[ns]")), errors="coerce")
        valid = created.notna() & fixed.notna()
        if valid.sum() > 0:
            durations = (fixed[valid] - created[valid]).dt.total_seconds() / 3600
            within_24h = (durations <= 24).sum()
            result["pct_resolved_24h"] = round(within_24h / valid.sum() * 100, 1)

    return result


# ─── Source confidence badge ─────────────────────────────────────────────────

def confidence_badge(source: str = "allocated") -> str:
    """Return a compact confidence indicator for KPI source basis."""
    badges = {
        "exact": "●",      # Exact from metering
        "allocated": "◐",  # Allocated estimate
        "estimated": "○",  # Rough estimate
        "live": "◉",       # Live INFORMATION_SCHEMA
        "forecast": "◈",   # Projected
    }
    return badges.get(source.lower(), "○")


def render_confidence_note(sources: list[tuple[str, str]], *, container=None) -> None:
    """Render a compact source confidence legend."""
    target = container or st
    parts = [f"{confidence_badge(src)} {label}" for label, src in sources]
    target.caption(" · ".join(parts))
