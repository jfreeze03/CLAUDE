"""Account Health — data-first shell with morning triage metrics.

Shows:
  - Resource monitor status, YTD credits, storage costs
  - Failed queries and long-running query counts
  - Checklist completion status
  - Morning exception count for triage
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    evidence_loaded,
    render_kpi_row,
    render_status_strip,
    scope_label,
)


_FULL_WORKSPACE_KEY = "_account_health_full_workspace_requested"
_BRIEF_MODE_KEY = "_account_health_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "health_data",
    "account_health_morning_exceptions",
    "account_health_operator_gates",
    "account_health_control_board",
    "account_health_intervention_matrix",
    "account_health_checklist",
)

_WORKFLOWS = (
    ("Overview", "KPIs, resource monitors, account posture."),
    ("Morning Report", "Overnight exceptions and triage."),
    ("DBA Checklist", "Daily checklist with closure tracking."),
    ("Access Hygiene", "Dormant users, orphan roles, access review."),
    ("Executive Briefing", "Leadership-ready account status."),
    ("Source Health", "Evidence freshness and availability."),
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

def _open_workspace(pane: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if pane:
        st.session_state["account_health_pane"] = pane
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import account_health
    account_health.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="ah_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("account_health_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Account Health KPIs ───────────────────────────────────────────────
    _render_health_kpis()

    # ── 2. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_health_kpis() -> None:
    """Show account health metrics from loaded evidence."""
    import pandas as pd

    health_data = st.session_state.get("health_data")
    morning_exceptions = st.session_state.get("account_health_morning_exceptions")

    has_data = (
        (isinstance(health_data, dict) and bool(health_data))
        or (isinstance(morning_exceptions, pd.DataFrame) and not morning_exceptions.empty)
    )

    if has_data:
        # Extract from health_data dict
        failures = 0
        long_queries = 0
        queued = 0
        credits_24h = 0.0

        if isinstance(health_data, dict):
            failures = int(health_data.get("failures", health_data.get("fail_count", 0)) or 0)
            long_queries = int(health_data.get("long_queries", 0) or 0)
            queued = int(health_data.get("queued", health_data.get("queued_count", 0)) or 0)
            credits_24h = float(health_data.get("credits_24h", health_data.get("daily_credits", 0)) or 0)

        # Morning exceptions
        exception_count = 0
        if isinstance(morning_exceptions, pd.DataFrame) and not morning_exceptions.empty:
            exception_count = len(morning_exceptions)

        # Status
        if failures > 20 or exception_count > 10:
            status, detail = "red", f"{failures} failures, {exception_count} exceptions"
        elif failures > 5 or exception_count > 3:
            status, detail = "yellow", f"{failures} failures"
        else:
            status, detail = "green", "Healthy"

        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Account", status, detail),
            ("Window", "green", _window_label()),
        ])

        credit_price = float(st.session_state.get("credit_price", 3.68))
        kpis = [
            ("Failures", str(failures), "Investigate" if failures > 10 else None),
            ("Long Queries", str(long_queries), "> 5min runtime" if long_queries > 0 else None),
            ("24h Credits", f"{credits_24h:,.0f}", f"${credits_24h * credit_price:,.0f}"),
            ("Exceptions", str(exception_count), "Morning triage" if exception_count > 0 else None),
        ]

        render_kpi_row(kpis)

        # Checklist status
        checklist = st.session_state.get("account_health_checklist")
        if isinstance(checklist, pd.DataFrame) and not checklist.empty:
            if "STATUS" in checklist.columns:
                completed = int(checklist["STATUS"].str.upper().eq("COMPLETED").sum())
                total_items = len(checklist)
                st.caption(f"📋 DBA Checklist: {completed}/{total_items} items completed")

        # Secondary row: resource monitor, dormant users, login failures
        secondary = []

        # Resource monitor % (from health_data if available)
        if isinstance(health_data, dict):
            rm_pct = health_data.get("resource_monitor_pct", health_data.get("rm_used_pct"))
            if rm_pct is not None:
                rm_pct = float(rm_pct)
                secondary.append(("Resource Monitor", f"{rm_pct:.0f}%", "Quota used" if rm_pct > 80 else None))

            # YTD credits if available
            ytd = health_data.get("ytd_credits", health_data.get("credits_ytd"))
            if ytd is not None and float(ytd) > 0:
                ytd = float(ytd)
                secondary.append(("YTD Credits", f"{ytd:,.0f}", f"${ytd * credit_price:,.0f}"))

            # Login failure rate
            login_failures = health_data.get("login_failures", health_data.get("failed_logins", 0))
            if login_failures and int(login_failures) > 0:
                secondary.append(("Login Failures", str(int(login_failures)), "Review access"))

        if secondary:
            render_kpi_row(secondary)

        # Freshness + confidence
        from utils.shell_metrics import render_loaded_at, render_confidence_note
        render_loaded_at("health_data")
        render_confidence_note([("Health", "live"), ("Credits", "allocated")])

    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Account", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load account health evidence.")
        if st.button("Load Account Health", key="ah_load", type="primary"):
            _open_workspace()


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"ah_wf_{label}", width="stretch"):
                    _open_workspace(label)
