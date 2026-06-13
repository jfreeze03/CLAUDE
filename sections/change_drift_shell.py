"""Change & Drift — data-first shell with change counts and drift status.

Shows:
  - DDL change count, grant/revoke events
  - Object drift exceptions
  - AI-assisted change detection (Cortex Code, AISQL)
  - Change impact scoring when available
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


_FULL_WORKSPACE_KEY = "_change_drift_full_workspace_requested"
_BRIEF_MODE_KEY = "_change_drift_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "change_drift_summary",
    "change_drift_exceptions",
    "change_drift_meta",
    "change_drift_proof_sql",
)

_WORKFLOWS = (
    ("Object Changes", "DDL, schema, table, view change history."),
    ("Access Changes", "Grant, revoke, role, privilege mutations."),
    ("Drift Detection", "Config drift, unapproved changes, exceptions."),
    ("DBA Tools", "Controlled admin actions with audit trail."),
    ("AI Change Gov", "Cortex Code, AISQL, AI-assisted change audit."),
    ("Change Impact", "Blast radius scoring for detected changes."),
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

def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if workflow:
        st.session_state["change_drift_workflow"] = workflow
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import change_drift
    change_drift.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="cd_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("change_drift_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Change & Drift KPIs ───────────────────────────────────────────────
    _render_change_kpis()

    # ── 2. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_change_kpis() -> None:
    """Show change detection metrics from loaded evidence."""
    import pandas as pd

    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")

    has_data = (
        (isinstance(summary, pd.DataFrame) and not summary.empty)
        or (isinstance(exceptions, pd.DataFrame) and not exceptions.empty)
    )

    if has_data:
        # Extract change counts
        ddl_changes = 0
        grant_events = 0
        drift_exceptions = 0

        if isinstance(summary, pd.DataFrame) and not summary.empty:
            if "CHANGE_COUNT" in summary.columns:
                ddl_changes = int(pd.to_numeric(summary["CHANGE_COUNT"], errors="coerce").sum())
            elif "DDL_COUNT" in summary.columns:
                ddl_changes = int(pd.to_numeric(summary["DDL_COUNT"], errors="coerce").sum())
            else:
                ddl_changes = len(summary)

            if "GRANT_COUNT" in summary.columns:
                grant_events = int(pd.to_numeric(summary["GRANT_COUNT"], errors="coerce").sum())

        if isinstance(exceptions, pd.DataFrame) and not exceptions.empty:
            drift_exceptions = len(exceptions)

        # Status
        if drift_exceptions > 10:
            status, detail = "red", f"{drift_exceptions} unapproved drift(s)"
        elif drift_exceptions > 0:
            status, detail = "yellow", f"{drift_exceptions} exception(s)"
        else:
            status, detail = "green", "No drift detected"

        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Drift", status, detail),
            ("Window", "green", _window_label()),
        ])

        kpis = [
            ("DDL Changes", str(ddl_changes), "Schema/object mutations"),
            ("Grant Events", str(grant_events), "Access mutations" if grant_events > 0 else None),
            ("Drift Exceptions", str(drift_exceptions), "Unapproved" if drift_exceptions > 0 else None),
        ]

        # AI-assisted change indicator
        ai_change_count = 0
        if isinstance(summary, pd.DataFrame) and "AI_CHANGE_COUNT" in summary.columns:
            ai_change_count = int(pd.to_numeric(summary["AI_CHANGE_COUNT"], errors="coerce").sum())
        if ai_change_count > 0:
            kpis.append(("AI Changes", str(ai_change_count), "Cortex Code/AISQL"))

        render_kpi_row(kpis)

        # DDL sparkline (changes per day)
        if isinstance(summary, pd.DataFrame) and "CHANGE_DATE" in summary.columns:
            daily_changes = summary.groupby("CHANGE_DATE").size().tail(14)
            if len(daily_changes) >= 3:
                from utils.sparklines import svg_sparkline
                spark = svg_sparkline(daily_changes.tolist(), width=120, height=20)
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;margin:2px 0;">'
                    f'<span style="font-size:0.68rem;color:var(--text-muted);">Change volume (14d)</span>'
                    f'{spark}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Freshness + confidence
        from utils.shell_metrics import render_loaded_at, render_confidence_note
        render_loaded_at("change_drift_summary")
        render_confidence_note([("DDL", "exact"), ("Drift", "live")])

    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Drift", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load change and drift evidence.")
        if st.button("Load Changes", key="cd_load", type="primary"):
            _open_workspace()


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"cd_wf_{label}", width="stretch"):
                    _open_workspace(label)
