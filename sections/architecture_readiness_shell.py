"""Architecture Readiness — data-first shell with design evidence.

Shows:
  - Architecture objective compliance count
  - DR readiness status
  - Forward platform control coverage (AI, Adaptive Compute)
  - Clustering and cache optimization opportunities
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


_FULL_WORKSPACE_KEY = "_architecture_readiness_full_workspace_requested"
_BRIEF_MODE_KEY = "_architecture_readiness_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "arch_objectives_df",
    "arch_iso_df",
    "arch_cluster_df",
    "arch_cache_df",
    "arch_dr_data",
    "arch_source_health",
    "arch_futures_board",
    "arch_agentic_cockpit",
    "arch_adaptive_compute",
    "arch_ai_inventory",
    "arch_ai_usage",
    "arch_ai_security_guardrails",
    "arch_openflow_operations",
    "arch_horizon_readiness",
    "arch_forward_controls",
)

_WORKFLOWS = (
    ("Workload Isolation", "Databases/warehouses that need isolation."),
    ("Clustering", "Large tables where pruning needs attention."),
    ("Cache Optimization", "Cache misses, scan pressure, resize proof."),
    ("DR Readiness", "Replication, failover, RPO/RTO ownership."),
    ("AI & Futures", "Cortex, agents, MCP, adaptive compute guardrails."),
    ("Objectives", "Owner, policy, RPO/RTO, architecture context."),
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

def _open_workspace(pane: str = "Architecture Brief") -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["architecture_readiness_pane"] = pane
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import architecture_readiness
    architecture_readiness.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="arch_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("architecture_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Architecture KPIs ─────────────────────────────────────────────────
    _render_architecture_kpis()

    # ── 2. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_architecture_kpis() -> None:
    """Show architecture readiness metrics from loaded evidence."""
    import pandas as pd

    objectives = st.session_state.get("arch_objectives_df")
    dr_data = st.session_state.get("arch_dr_data")
    futures = st.session_state.get("arch_futures_board")
    adaptive = st.session_state.get("arch_adaptive_compute")
    ai_guardrails = st.session_state.get("arch_ai_security_guardrails")

    has_data = any(
        isinstance(st.session_state.get(k), pd.DataFrame) and not st.session_state.get(k).empty
        for k in ("arch_objectives_df", "arch_futures_board", "arch_adaptive_compute")
    ) or isinstance(dr_data, (pd.DataFrame, dict))

    if has_data:
        # Objectives compliance
        objectives_total = objectives_met = 0
        if isinstance(objectives, pd.DataFrame) and not objectives.empty:
            objectives_total = len(objectives)
            if "STATUS" in objectives.columns:
                objectives_met = int(objectives["STATUS"].str.upper().isin(["MET", "COMPLIANT", "APPROVED"]).sum())

        # DR readiness
        dr_status = "gray"
        dr_detail = "Not assessed"
        if isinstance(dr_data, pd.DataFrame) and not dr_data.empty:
            dr_status = "green"
            dr_detail = f"{len(dr_data)} protected objects"
        elif isinstance(dr_data, dict):
            dr_status = "green" if dr_data.get("ready") else "yellow"
            dr_detail = str(dr_data.get("status", "Loaded"))

        # Forward platform controls
        futures_coverage = 0
        if isinstance(futures, pd.DataFrame) and not futures.empty:
            if "COVERAGE_STATE" in futures.columns:
                futures_coverage = int(futures["COVERAGE_STATE"].str.upper().eq("EVIDENCE CAPTURED").sum())

        # Adaptive compute candidates
        adaptive_count = 0
        if isinstance(adaptive, pd.DataFrame) and not adaptive.empty:
            adaptive_count = len(adaptive)

        # AI security guardrails
        ai_guardrail_count = 0
        if isinstance(ai_guardrails, pd.DataFrame) and not ai_guardrails.empty:
            ai_guardrail_count = len(ai_guardrails)

        # Status
        if objectives_total > 0 and objectives_met / objectives_total < 0.7:
            status, detail = "yellow", f"{objectives_met}/{objectives_total} objectives met"
        else:
            status, detail = "green", "Architecture aligned"

        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Architecture", status, detail),
            ("DR", dr_status, dr_detail),
        ])

        kpis = [
            ("Objectives", f"{objectives_met}/{objectives_total}" if objectives_total else "—", None),
            ("Futures Coverage", str(futures_coverage), "Controls with evidence"),
            ("Adaptive Compute", str(adaptive_count), "Candidates" if adaptive_count > 0 else None),
            ("AI Guardrails", str(ai_guardrail_count), "Controls active"),
        ]

        render_kpi_row(kpis)

        # Secondary row: DR drill freshness, Horizon readiness
        secondary = []

        # DR drill last date
        if isinstance(dr_data, pd.DataFrame) and not dr_data.empty:
            if "LAST_DRILL_DATE" in dr_data.columns:
                last_drill = pd.to_datetime(dr_data["LAST_DRILL_DATE"], errors="coerce").max()
                if pd.notna(last_drill):
                    days_since = (pd.Timestamp.now() - last_drill).days
                    secondary.append(("Last DR Drill", f"{days_since}d ago", "Overdue" if days_since > 90 else None))

        # Horizon governance readiness
        horizon = st.session_state.get("arch_horizon_readiness")
        if isinstance(horizon, pd.DataFrame) and not horizon.empty:
            secondary.append(("Horizon Ready", str(len(horizon)), "Governance views"))

        if secondary:
            render_kpi_row(secondary)

        # Freshness + confidence
        from utils.shell_metrics import render_loaded_at, render_confidence_note
        render_loaded_at("arch_objectives_df")
        render_confidence_note([("Objectives", "exact"), ("Futures", "live"), ("DR", "exact")])

    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Architecture", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load architecture readiness evidence.")
        if st.button("Load Architecture", key="arch_load", type="primary"):
            _open_workspace()


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"arch_wf_{label}", width="stretch"):
                    _open_workspace(label)
