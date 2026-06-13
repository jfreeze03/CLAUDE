"""Security Posture — data-first shell with key metrics.

Shows:
  - Finding counts by severity immediately when loaded
  - Privileged role count, dormant users, MFA gaps
  - Compliance score from loaded evidence
  - Data sharing exposure count
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


_FULL_WORKSPACE_KEY = "_security_posture_full_workspace_requested"
_BRIEF_MODE_KEY = "_security_posture_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "security_posture_summary",
    "security_posture_exceptions",
    "security_operability_fact",
    "security_privileged_grants",
    "security_access_review_trend",
    "security_action_closure",
    "security_posture_proof_sql",
)

_WORKFLOWS = (
    ("Access Posture", "MFA gaps, failed logins, user-level access evidence."),
    ("Privilege Sprawl", "Admin roles, ownership, grant-option, approval blockers."),
    ("Data Sharing", "Shared databases, imported data, consumers, owners."),
    ("Compliance Evidence", "SOC 2, HIPAA audit evidence and dormant users."),
    ("Adoption Analytics", "User activity patterns and role utilization."),
    ("Horizon Governance", "Classification, policies, lineage, access history."),
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
        st.session_state["security_posture_requested_view"] = "Access Workflows"
        st.session_state["security_posture_requested_workflow"] = workflow
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import security_posture
    security_posture.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="sec_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("security_posture_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Security KPIs ─────────────────────────────────────────────────────
    _render_security_kpis()

    # ── 2. Compliance readiness indicator ────────────────────────────────────
    if _has_evidence():
        _render_compliance_indicator()

    # ── 3. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_security_kpis() -> None:
    """Show security findings, privileged roles, and posture status."""
    import pandas as pd

    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")

    if isinstance(summary, pd.DataFrame) and not summary.empty:
        # Extract finding counts
        critical = high = medium = total_findings = 0
        if "SEVERITY" in summary.columns:
            severity_upper = summary["SEVERITY"].str.upper()
            critical = int(severity_upper.eq("CRITICAL").sum())
            high = int(severity_upper.eq("HIGH").sum())
            medium = int(severity_upper.eq("MEDIUM").sum())
            total_findings = len(summary)
        elif "FINDING_COUNT" in summary.columns:
            total_findings = int(summary["FINDING_COUNT"].sum())

        # Determine status
        if critical > 0:
            status, detail = "red", f"{critical} critical findings"
        elif high > 3:
            status, detail = "yellow", f"{high} high findings"
        elif total_findings > 0:
            status, detail = "green", f"{total_findings} findings (no critical)"
        else:
            status, detail = "green", "Clean posture"

        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Security", status, detail),
            ("Window", "green", _window_label()),
        ])

        # Primary KPIs
        kpis = [
            ("Critical", str(critical), "Immediate action" if critical > 0 else None),
            ("High", str(high), "Review needed" if high > 0 else None),
            ("Medium", str(medium), None),
            ("Total Findings", str(total_findings), None),
        ]

        # Exception count
        exception_count = 0
        if isinstance(exceptions, pd.DataFrame) and not exceptions.empty:
            exception_count = len(exceptions)
            kpis.append(("Exceptions", str(exception_count), "Unresolved"))

        render_kpi_row(kpis)

        # Secondary row: privileged roles, dormant users, governance score
        secondary = []
        priv_grants = st.session_state.get("security_privileged_grants")
        if isinstance(priv_grants, pd.DataFrame) and not priv_grants.empty:
            secondary.append(("Privileged Grants", str(len(priv_grants)), "Review access"))

        # Dormant user count (from access review if loaded)
        access_review = st.session_state.get("security_access_review_trend")
        if isinstance(access_review, pd.DataFrame) and not access_review.empty:
            if "ACCOUNT_STATUS" in access_review.columns:
                dormant = int(access_review["ACCOUNT_STATUS"].str.upper().isin(["DORMANT", "NEVER LOGGED IN"]).sum())
                if dormant > 0:
                    secondary.append(("Dormant Users", str(dormant), "Disable candidates"))

        if secondary:
            render_kpi_row(secondary)

        # Loaded-at + confidence
        from utils.shell_metrics import render_loaded_at, render_confidence_note
        render_loaded_at("security_posture_summary")
        render_confidence_note([("Findings", "exact"), ("Access", "live")])

    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Security", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load security posture evidence.")
        if st.button("Load Security Posture", key="sec_load", type="primary"):
            _open_workspace()


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"sec_wf_{label}", width="stretch"):
                    _open_workspace(label)


def _render_compliance_indicator() -> None:
    """Show a compact compliance readiness indicator from loaded security data."""
    import pandas as pd
    from utils.compliance_evidence import build_compliance_scorecard

    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")

    # Build a lightweight scorecard from available data
    scorecard = build_compliance_scorecard(
        escalations_df=summary if isinstance(summary, pd.DataFrame) else None,
        dormant_users_df=None,  # Would need separate load
        failed_logins_df=None,
    )

    score = scorecard["overall_score"]
    level = scorecard["readiness_level"]

    if score >= 80:
        color = "#22c55e"
    elif score >= 60:
        color = "#f59e0b"
    else:
        color = "#ef4444"

    st.markdown(
        f'<div style="padding:6px 12px;border-left:3px solid {color};'
        f'background:var(--bg-card,#1e293b);border-radius:0 6px 6px 0;margin:6px 0;'
        f'font-size:0.75rem;color:var(--text-secondary,#cbd5e1);">'
        f'Compliance Readiness: <strong style="color:{color};">{level}</strong> '
        f'({score}/100) · Open Compliance Evidence for full audit trail'
        f'</div>',
        unsafe_allow_html=True,
    )
