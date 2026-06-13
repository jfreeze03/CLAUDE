"""Alert Center — 95-level shell with alert age, SLA, and trend.

KPIs:
  - Open/Critical/Resolved counts with trend deltas
  - Oldest open alert age (hours)
  - Resolution SLA (% resolved within 24h)
  - Alert trend sparkline (daily new alerts)
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import evidence_loaded, render_kpi_row, render_status_strip, scope_label
from utils.perf import get_cached_metrics, deferred_expander
from utils.shell_metrics import compute_alert_age, render_loaded_at, render_confidence_note


_FULL_WORKSPACE_KEY = "_alert_center_full_workspace_requested"
_BRIEF_MODE_KEY = "_alert_center_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = ("alert_center_data", "alert_center_annotations")

_WORKFLOWS = (
    ("Issue Inbox", "Combined alert + action queue for morning triage."),
    ("Triage Digest", "Critical, high, overdue, and escalated rows first."),
    ("Email Delivery", "Delivery proof: sent, logged, or waiting."),
    ("Queue Routing", "Route alerts into owner work and closure proof."),
    ("Control Health", "Source readiness, rules, and control gaps."),
    ("Automation", "No-touch alerts, Control-M, Jira, Terraform feeds."),
)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)

def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT

def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return "Selected"

def _full_workspace_requested() -> bool:
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    return bool(st.session_state.get(_FULL_WORKSPACE_KEY))

def _has_evidence() -> bool:
    return evidence_loaded(st.session_state, _FULL_WORKSPACE_STATE_KEYS)

def _open_workspace(view: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if view:
        st.session_state["alert_center_requested_view"] = view
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import alert_center
    alert_center.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="ac_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    metrics = get_cached_metrics("alert_center_data")
    has_data = bool(metrics.get("total_count"))

    if has_data:
        _render_alert_kpis(metrics)
        _render_alert_sparkline()
        render_loaded_at("alert_center_data")
        render_confidence_note([("Alert counts", "exact"), ("Age/SLA", "live")])
    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Alerts", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load alert evidence.")
        if st.button("Open Issue Inbox", key="ac_load", type="primary"):
            _open_workspace("Issue Inbox")
        return

    st.divider()
    _render_workflow_grid()


def _render_alert_kpis(metrics: dict) -> None:
    """Render alert KPIs with age tracking and SLA."""
    import pandas as pd

    open_count = metrics.get("open_count", 0)
    critical_count = metrics.get("critical_count", 0)
    total = metrics.get("total_count", 0)
    resolved = total - open_count

    # Status
    if open_count > 10 or critical_count > 3:
        status, detail = "red", f"{open_count} open, {critical_count} critical"
    elif open_count > 3:
        status, detail = "yellow", f"{open_count} open"
    else:
        status, detail = "green", f"{open_count} open"

    render_status_strip([
        ("Scope", "green", scope_label(_active_company(), _active_environment())),
        ("Alerts", status, detail),
        ("Window", "green", _window_label()),
    ])

    # Primary KPIs
    render_kpi_row([
        ("Open", str(open_count), "Triage needed" if open_count > 5 else None),
        ("Critical/High", str(critical_count), "Escalate" if critical_count > 0 else None),
        ("Resolved", str(resolved), None),
        ("Total", str(total), None),
    ])

    # Alert age and SLA metrics
    alert_df = st.session_state.get("alert_center_data")
    if isinstance(alert_df, pd.DataFrame) and not alert_df.empty:
        age_metrics = compute_alert_age(alert_df)

        secondary = []
        if age_metrics["oldest_hours"] > 0:
            oldest_label = f"{age_metrics['oldest_hours']:.0f}h"
            secondary.append(("Oldest Open", oldest_label, "Overdue" if age_metrics["oldest_hours"] > 48 else None))
        if age_metrics["avg_hours"] > 0:
            secondary.append(("Avg Age", f"{age_metrics['avg_hours']:.0f}h", None))
        if age_metrics["pct_resolved_24h"] > 0:
            sla_color = None
            if age_metrics["pct_resolved_24h"] < 80:
                sla_color = "↓ Below target"
            secondary.append(("24h SLA", f"{age_metrics['pct_resolved_24h']:.0f}%", sla_color))

        if secondary:
            render_kpi_row(secondary)


def _render_alert_sparkline() -> None:
    """Show daily new alert trend sparkline."""
    import pandas as pd

    alert_df = st.session_state.get("alert_center_data")
    if not isinstance(alert_df, pd.DataFrame) or alert_df.empty:
        return
    if "CREATED_AT" not in alert_df.columns:
        return

    created = pd.to_datetime(alert_df["CREATED_AT"], errors="coerce")
    daily_counts = created.dt.date.value_counts().sort_index().tail(14)
    if len(daily_counts) < 3:
        return

    from utils.sparklines import svg_sparkline
    spark = svg_sparkline(daily_counts.tolist(), width=120, height=20)
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin:2px 0;">'
        f'<span style="font-size:0.68rem;color:var(--text-muted);">Alert trend (14d)</span>'
        f'{spark}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _) in zip(cols, batch):
            with col:
                if st.button(label, key=f"ac_wf_{label}", width="stretch"):
                    _open_workspace(label)
