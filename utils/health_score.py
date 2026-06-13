# utils/health_score.py - Composite Platform Health Score for executive KPI
"""
Computes a single 0-100 Platform Health Score combining:
  - Cost control (contract pacing, spike avoidance)
  - Reliability (task failures, query errors, SLA compliance)
  - Security posture (grant hygiene, access anomalies)
  - Operational readiness (alert closure, action queue age)

This gives executives a single number to track weekly without
opening individual sections.
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


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# --- Component scorers ---

def _cost_control_score(state: dict) -> tuple[float, str]:
    """Score 0-100 based on cost stability and contract pacing."""
    # Start at 85 (healthy baseline), deduct for issues
    score = 85.0
    notes = []

    # Check for loaded cost evidence
    cost_data = state.get("cost_contract_cockpit")
    if cost_data is not None:
        import pandas as pd
        if isinstance(cost_data, pd.DataFrame) and not cost_data.empty:
            # Look for spike indicators
            if "VARIANCE_PCT" in cost_data.columns:
                max_variance = _safe_float(cost_data["VARIANCE_PCT"].max())
                if max_variance > 50:
                    score -= 25
                    notes.append(f"Cost spike {max_variance:.0f}%")
                elif max_variance > 30:
                    score -= 15
                    notes.append(f"Cost variance {max_variance:.0f}%")
                elif max_variance > 15:
                    score -= 5

    # Check contract pacing
    run_rate = state.get("cost_contract_run_rate")
    if run_rate is not None:
        import pandas as pd
        if isinstance(run_rate, pd.DataFrame) and not run_rate.empty:
            score = min(score, 90.0)  # Evidence exists, cap optimistic score

    if not notes:
        notes.append("Stable" if score >= 75 else "Review needed")

    return _clamp(score), "; ".join(notes)


def _reliability_score(state: dict) -> tuple[float, str]:
    """Score 0-100 based on task/query failure rates and SLA compliance."""
    score = 90.0
    notes = []

    # DBA control room snapshot for failures
    dba_data = state.get("dba_control_room_data")
    if dba_data is not None:
        import pandas as pd
        if isinstance(dba_data, pd.DataFrame) and not dba_data.empty:
            if "FAIL_COUNT" in dba_data.columns:
                total_failures = _safe_int(dba_data["FAIL_COUNT"].sum())
                if total_failures > 50:
                    score -= 30
                    notes.append(f"{total_failures} failures")
                elif total_failures > 20:
                    score -= 15
                    notes.append(f"{total_failures} failures")
                elif total_failures > 5:
                    score -= 5

    # Check task management evidence
    task_data = state.get("workload_operations_task_snapshot")
    if task_data is not None:
        import pandas as pd
        if isinstance(task_data, pd.DataFrame) and not task_data.empty:
            if "STATE" in task_data.columns:
                failed_tasks = len(task_data[task_data["STATE"].str.upper() == "FAILED"])
                if failed_tasks > 10:
                    score -= 20
                    notes.append(f"{failed_tasks} failed tasks")
                elif failed_tasks > 3:
                    score -= 10

    if not notes:
        notes.append("Healthy" if score >= 80 else "Degraded")

    return _clamp(score), "; ".join(notes)


def _security_score(state: dict) -> tuple[float, str]:
    """Score 0-100 based on security posture evidence."""
    score = 80.0
    notes = []

    security_summary = state.get("security_posture_summary")
    if security_summary is not None:
        import pandas as pd
        if isinstance(security_summary, pd.DataFrame) and not security_summary.empty:
            if "SEVERITY" in security_summary.columns:
                critical = len(security_summary[
                    security_summary["SEVERITY"].str.upper().isin(["CRITICAL", "HIGH"])
                ])
                if critical > 5:
                    score -= 30
                    notes.append(f"{critical} critical/high findings")
                elif critical > 0:
                    score -= 10 * critical
                    notes.append(f"{critical} findings")

    security_exceptions = state.get("security_posture_exceptions")
    if security_exceptions is not None:
        import pandas as pd
        if isinstance(security_exceptions, pd.DataFrame) and not security_exceptions.empty:
            score -= min(20, len(security_exceptions) * 3)
            notes.append(f"{len(security_exceptions)} exceptions")

    if not notes:
        notes.append("Clean" if score >= 75 else "Review needed")

    return _clamp(score), "; ".join(notes)


def _operational_readiness_score(state: dict) -> tuple[float, str]:
    """Score 0-100 based on alert closure, action queue health."""
    score = 85.0
    notes = []

    # Alert center evidence
    alert_data = state.get("alert_center_data")
    if alert_data is not None:
        import pandas as pd
        if isinstance(alert_data, pd.DataFrame) and not alert_data.empty:
            if "STATUS" in alert_data.columns:
                open_alerts = len(alert_data[
                    alert_data["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"])
                ])
                if open_alerts > 20:
                    score -= 25
                    notes.append(f"{open_alerts} open alerts")
                elif open_alerts > 10:
                    score -= 15
                    notes.append(f"{open_alerts} open alerts")
                elif open_alerts > 3:
                    score -= 5

    # Account health morning exceptions
    morning_exceptions = state.get("account_health_morning_exceptions")
    if morning_exceptions is not None:
        import pandas as pd
        if isinstance(morning_exceptions, pd.DataFrame) and not morning_exceptions.empty:
            score -= min(15, len(morning_exceptions) * 2)

    if not notes:
        notes.append("Operational" if score >= 80 else "Attention needed")

    return _clamp(score), "; ".join(notes)


# --- Composite score ---

# Weights sum to 1.0
_COMPONENT_WEIGHTS = {
    "cost_control": 0.30,
    "reliability": 0.30,
    "security": 0.20,
    "operations": 0.20,
}


def compute_platform_health_score(state: dict | None = None) -> dict[str, Any]:
    """
    Compute the composite Platform Health Score from loaded session state.

    Returns:
        {
            "score": float (0-100),
            "grade": str ("A" through "F"),
            "components": {
                "cost_control": {"score": float, "note": str, "weight": float},
                "reliability": {"score": float, "note": str, "weight": float},
                "security": {"score": float, "note": str, "weight": float},
                "operations": {"score": float, "note": str, "weight": float},
            },
            "trend": str ("improving", "stable", "declining", "unknown"),
        }
    """
    if state is None:
        state = dict(st.session_state)

    cost_score, cost_note = _cost_control_score(state)
    reliability_score, reliability_note = _reliability_score(state)
    security_sc, security_note = _security_score(state)
    ops_score, ops_note = _operational_readiness_score(state)

    composite = (
        cost_score * _COMPONENT_WEIGHTS["cost_control"]
        + reliability_score * _COMPONENT_WEIGHTS["reliability"]
        + security_sc * _COMPONENT_WEIGHTS["security"]
        + ops_score * _COMPONENT_WEIGHTS["operations"]
    )
    composite = _clamp(composite)

    # Grade
    if composite >= 90:
        grade = "A"
    elif composite >= 80:
        grade = "B"
    elif composite >= 70:
        grade = "C"
    elif composite >= 60:
        grade = "D"
    else:
        grade = "F"

    # Trend detection from previous score
    prev_score = _safe_float(state.get("_platform_health_score_prev"))
    if prev_score > 0:
        delta = composite - prev_score
        if delta > 3:
            trend = "improving"
        elif delta < -3:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "unknown"

    return {
        "score": round(composite, 1),
        "grade": grade,
        "trend": trend,
        "components": {
            "cost_control": {"score": round(cost_score, 1), "note": cost_note, "weight": _COMPONENT_WEIGHTS["cost_control"]},
            "reliability": {"score": round(reliability_score, 1), "note": reliability_note, "weight": _COMPONENT_WEIGHTS["reliability"]},
            "security": {"score": round(security_sc, 1), "note": security_note, "weight": _COMPONENT_WEIGHTS["security"]},
            "operations": {"score": round(ops_score, 1), "note": ops_note, "weight": _COMPONENT_WEIGHTS["operations"]},
        },
    }


def render_health_score_badge(container=None) -> None:
    """Render the Platform Health Score as a compact executive badge."""
    import html as html_mod

    result = compute_platform_health_score()
    score = result["score"]
    grade = result["grade"]
    trend = result["trend"]

    trend_icons = {"improving": "↑", "declining": "↓", "stable": "→", "unknown": "·"}
    trend_colors = {"improving": "#22c55e", "declining": "#ef4444", "stable": "#94a3b8", "unknown": "#64748b"}

    # Color based on score
    if score >= 85:
        score_color = "#22c55e"
    elif score >= 70:
        score_color = "#f59e0b"
    elif score >= 55:
        score_color = "#f97316"
    else:
        score_color = "#ef4444"

    badge_html = f"""
    <div class="ow-health-score-badge" style="display:flex;align-items:center;gap:12px;padding:8px 16px;
         border:1px solid var(--border-subtle, #334155);border-radius:8px;background:var(--bg-card, #1e293b);">
        <div style="text-align:center;">
            <div style="font-size:2rem;font-weight:800;color:{score_color};line-height:1;">{score:.0f}</div>
            <div style="font-size:0.65rem;color:var(--text-muted, #94a3b8);text-transform:uppercase;letter-spacing:0.05em;">Health</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:2px;">
            <div style="font-size:0.75rem;color:var(--text-secondary, #cbd5e1);">
                Grade <strong>{html_mod.escape(grade)}</strong>
                <span style="color:{trend_colors[trend]};margin-left:6px;">{trend_icons[trend]} {trend}</span>
            </div>
            <div style="font-size:0.65rem;color:var(--text-muted, #94a3b8);">
                Cost {result['components']['cost_control']['score']:.0f} ·
                Reliability {result['components']['reliability']['score']:.0f} ·
                Security {result['components']['security']['score']:.0f} ·
                Ops {result['components']['operations']['score']:.0f}
            </div>
        </div>
    </div>
    """

    target = container or st
    target.markdown(badge_html, unsafe_allow_html=True)

    # Store for trend tracking
    st.session_state["_platform_health_score_prev"] = score
