"""Workload Operations — data-first shell with job metrics.

Shows:
  - Failed/succeeded task counts with SLA compliance
  - Active/queued/blocked query counts
  - Pipeline freshness status
  - Stored procedure runtime drift indicators
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


_FULL_WORKSPACE_KEY = "_workload_operations_full_workspace_requested"
_BRIEF_MODE_KEY = "_workload_operations_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "workload_operations_snapshot",
    "workload_operations_task_snapshot",
    "workload_operations_snapshot_error",
    "workload_operations_task_snapshot_error",
    "live_monitor_state",
    "query_analysis_df",
    "task_management_df",
    "stored_proc_tracker_df",
    "pipeline_health_df",
    "query_search_results",
)

_WORKFLOWS = (
    ("Task Graphs", "Job status, SLA risk, retries, downstream impact."),
    ("Query Diagnosis", "P95 runtime, queue pressure, spill, regressions."),
    ("Live Triage", "Running, queued, blocked, failed right now."),
    ("Procedures", "CALL history, runtime drift, attributed cost."),
    ("Pipelines", "Load health, Snowpipe, task signals, backlog."),
    ("History Search", "Find one query, user, warehouse, or incident."),
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
    st.session_state["workload_operations_view"] = "Workload Brief"
    if workflow:
        st.session_state["workload_operations_view"] = "Specialist Workflows"
        st.session_state["workload_operations_workflow"] = workflow
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import workload_operations
    workload_operations.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="wo_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("workload_operations_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Workload KPIs ─────────────────────────────────────────────────────
    _render_workload_kpis()

    # ── 2. Live Task Graph (execute/kill controls) ───────────────────────────
    from utils.perf import deferred_expander
    deferred_expander("🔴 Live Task Graph (run/kill/resume)", _render_live_tasks, key="wo_live_tasks")

    # ── 3. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_workload_kpis() -> None:
    """Show task and query health metrics."""
    import pandas as pd

    task_snap = st.session_state.get("workload_operations_task_snapshot")
    query_snap = st.session_state.get("workload_operations_snapshot")
    pipeline_df = st.session_state.get("pipeline_health_df")
    proc_df = st.session_state.get("stored_proc_tracker_df")

    has_task_data = isinstance(task_snap, pd.DataFrame) and not task_snap.empty
    has_query_data = isinstance(query_snap, pd.DataFrame) and not query_snap.empty
    has_pipeline_data = isinstance(pipeline_df, pd.DataFrame) and not pipeline_df.empty
    has_proc_data = isinstance(proc_df, pd.DataFrame) and not proc_df.empty

    if has_task_data or has_query_data:
        # Task metrics
        failed_tasks = succeeded_tasks = total_tasks = 0
        if has_task_data and "STATE" in task_snap.columns:
            states = task_snap["STATE"].str.upper()
            failed_tasks = int(states.eq("FAILED").sum())
            succeeded_tasks = int(states.eq("SUCCEEDED").sum())
            total_tasks = len(task_snap)

        # Query metrics
        active_queries = queued_queries = blocked_queries = 0
        if has_query_data:
            if "ACTIVE_COUNT" in query_snap.columns:
                active_queries = int(pd.to_numeric(query_snap["ACTIVE_COUNT"], errors="coerce").sum())
            if "QUEUED_COUNT" in query_snap.columns:
                queued_queries = int(pd.to_numeric(query_snap["QUEUED_COUNT"], errors="coerce").sum())
            if "BLOCKED_COUNT" in query_snap.columns:
                blocked_queries = int(pd.to_numeric(query_snap["BLOCKED_COUNT"], errors="coerce").sum())

        # Pipeline health
        pipeline_status = ""
        if has_pipeline_data and "STATUS" in pipeline_df.columns:
            stale_pipes = int(pipeline_df["STATUS"].str.upper().isin(["STALE", "FAILED", "LATE"]).sum())
            if stale_pipes > 0:
                pipeline_status = f"{stale_pipes} stale"

        # Status determination
        if failed_tasks > 10 or blocked_queries > 5:
            status, detail = "red", f"{failed_tasks} failed, {blocked_queries} blocked"
        elif failed_tasks > 3 or queued_queries > 10:
            status, detail = "yellow", f"{failed_tasks} failed, {queued_queries} queued"
        else:
            status, detail = "green", f"{failed_tasks} failures"

        status_items = [
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Jobs", status, detail),
            ("Window", "green", _window_label()),
        ]
        if pipeline_status:
            status_items.append(("Pipelines", "yellow", pipeline_status))

        render_status_strip(status_items)

        # Primary KPIs
        sla_pct = round(succeeded_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0
        kpis = [
            ("Failed Tasks", str(failed_tasks), "Investigate" if failed_tasks > 5 else None),
            ("Success Rate", f"{sla_pct:.1f}%", f"{succeeded_tasks}/{total_tasks}"),
            ("Active Queries", str(active_queries), None),
            ("Queued", str(queued_queries), "Pressure" if queued_queries > 10 else None),
        ]

        render_kpi_row(kpis)

        # Secondary row: pipelines, procedures, longest running, SLA target
        secondary = []
        if has_pipeline_data:
            # Pipeline freshness percentage
            if "FRESHNESS_STATUS" in pipeline_df.columns or "STATUS" in pipeline_df.columns:
                status_col = "FRESHNESS_STATUS" if "FRESHNESS_STATUS" in pipeline_df.columns else "STATUS"
                fresh_count = int(pipeline_df[status_col].str.upper().isin(["FRESH", "SUCCEEDED"]).sum())
                freshness_pct = round(fresh_count / len(pipeline_df) * 100, 0) if len(pipeline_df) > 0 else 0
                secondary.append(("Pipeline Fresh", f"{freshness_pct:.0f}%", pipeline_status or "On time"))
            else:
                secondary.append(("Pipelines", str(len(pipeline_df)), pipeline_status or "Healthy"))

        if has_proc_data:
            # Procedure regression count
            if "REGRESSION_FACTOR" in proc_df.columns:
                regressed = int((pd.to_numeric(proc_df["REGRESSION_FACTOR"], errors="coerce").fillna(0) > 2).sum())
                secondary.append(("Proc Regressions", str(regressed), "↑ 2x+ slower" if regressed > 0 else None))
            else:
                secondary.append(("Procedures", str(len(proc_df)), "Tracked"))

        # Longest running task/query
        live_tasks = st.session_state.get("task_live_data")
        if isinstance(live_tasks, list):
            running = [t for t in live_tasks if t.get("state", "").upper() in ("EXECUTING", "RUNNING")]
            if running:
                longest = max(running, key=lambda t: t.get("running_sec", 0))
                longest_sec = longest.get("running_sec", 0)
                if longest_sec > 60:
                    secondary.append(("Longest Running", f"{longest_sec // 60}m{longest_sec % 60}s", longest.get("task_name", "")[:18]))

        if blocked_queries > 0:
            secondary.append(("Blocked", str(blocked_queries), "Concurrency issue"))

        if secondary:
            render_kpi_row(secondary)

        # Freshness + confidence
        from utils.shell_metrics import render_loaded_at, render_confidence_note
        render_loaded_at("workload_operations_snapshot")
        render_confidence_note([("Tasks", "live"), ("Pipelines", "allocated"), ("SLA", "exact")])

    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Jobs", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load workload evidence.")
        if st.button("Load Task Graphs", key="wo_load", type="primary"):
            _open_workspace("Task Graphs")


def _render_live_tasks() -> None:
    """Render live task graph with execute/kill controls (deferred)."""
    from utils.task_controls import render_live_task_panel
    from utils.session import get_session_for_action

    session = get_session_for_action("monitor live tasks", surface="Workload Operations")
    if session:
        render_live_task_panel(session)


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"wo_wf_{label}", width="stretch"):
                    _open_workspace(label)
