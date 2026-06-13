"""DBA Control Room — performance-optimized data-first shell.

Performance optimizations:
  - Pre-computed metrics avoid re-scanning DataFrames on every rerun
  - Single batched HTML render for status + KPIs
  - Lazy imports only when evidence exists
  - Deferred expander content for runbooks/self-healing
  - No redundant st.rerun() calls
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    evidence_loaded,
    render_kpi_row,
    render_status_strip,
    scope_label,
)
from utils.perf import get_cached_metrics, HtmlBatch, deferred_expander


_FULL_WORKSPACE_KEY = "_dba_control_room_full_workspace_requested"
_BRIEF_MODE_KEY = "_dba_control_room_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "dba_control_room_data",
    "dba_control_room_snapshot_result",
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
)

_WORKFLOWS = (
    ("Fast Watch", "Failures, queue, routed exceptions."),
    ("Operations Board", "Priority, runbook, escalation, handoff."),
    ("Release Gate", "Blockers, task recovery, approvals."),
    ("Source Health", "Evidence freshness and availability."),
    ("Executive Evidence", "Report-ready notes for leaders."),
    ("Release Compare", "Compare windows for regressions."),
)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _credit_price() -> float:
    return _safe_float(st.session_state.get("credit_price", DEFAULTS["credit_price"]), DEFAULTS["credit_price"])


def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return "24h"


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
        st.session_state["dba_control_room_active_view"] = view
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import dba_control_room
    dba_control_room.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


# ─── Main render ─────────────────────────────────────────────────────────────


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back to Command Center", key="dba_cr_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("dba_control_room_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # Use pre-computed metrics (avoids re-scanning DataFrames)
    metrics = get_cached_metrics("dba_control_room_snapshot_result")
    has_data = bool(metrics)

    # ── 1. Status + KPIs ─────────────────────────────────────────────────────
    if has_data:
        failures = metrics.get("FAIL_COUNT", 0)
        queued = metrics.get("QUEUED_COUNT", 0)
        active = metrics.get("ACTIVE_COUNT", 0)
        blocked = metrics.get("BLOCKED_COUNT", 0)

        status = "red" if failures > 20 or blocked > 5 else "yellow" if failures > 5 or queued > 10 else "green"

        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Window", "green", _window_label()),
            ("Status", status, f"{failures} failures, {queued} queued"),
        ])

        render_kpi_row([
            ("Failures", str(failures), "↑ Critical" if failures > 20 else None),
            ("Queued", str(queued), "Pressure" if queued > 10 else None),
            ("Active", str(active), None),
            ("Blocked", str(blocked), "Investigate" if blocked > 0 else None),
        ])

        # Secondary row: MTTR + live task count
        from utils.shell_metrics import compute_mttr, render_loaded_at, render_confidence_note
        secondary = []
        action_queue = st.session_state.get("cost_contract_queue") or st.session_state.get("dba_control_room_incident_board")
        mttr = compute_mttr(action_queue) if action_queue is not None else None
        if mttr is not None:
            secondary.append(("MTTR", f"{mttr:.0f}h", "Avg resolution time"))

        # Live task count if loaded
        live_tasks = st.session_state.get("task_live_data")
        if isinstance(live_tasks, list) and live_tasks:
            running = sum(1 for t in live_tasks if t.get("state", "").upper() in ("EXECUTING", "RUNNING"))
            if running > 0:
                secondary.append(("Live Running", str(running), "Tasks executing now"))

        if secondary:
            render_kpi_row(secondary)

        render_loaded_at("dba_control_room_snapshot_result")
        render_confidence_note([("Operations", "live"), ("MTTR", "exact")])
    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Window", "green", _window_label()),
            ("Status", "gray", "No evidence loaded"),
        ])
        st.info("Open the workspace to load the first snapshot.")
        if st.button("Load Fast Watch", key="dba_cr_load_fast", type="primary"):
            _open_workspace("Fast Watch")
        return  # Skip rest of shell when no data

    # ── 2. Sparkline trends (lazy import only when data exists) ───────────────
    _render_sparklines_if_available()

    # ── 3. Deferred: Self-healing + Runbook (only computed when opened) ──────
    if failures > 5:
        deferred_expander(
            f"🔧 Self-Healing & Runbook ({failures} failures)",
            _render_healing_and_runbook,
            key="dba_cr_healing",
        )

    # ── 4. Compact workflow grid ─────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_sparklines_if_available() -> None:
    """Render sparklines using pre-computed or lightweight shell DataFrame."""
    from utils.perf import get_shell_df
    pd = __import__("pandas")

    snapshot = get_shell_df("dba_control_room_snapshot_result")
    if not isinstance(snapshot, pd.DataFrame) or snapshot.empty or len(snapshot) < 2:
        return

    from utils.sparklines import render_sparkline_snapshot

    sparkline_metrics = []
    for col_name, label in [("FAIL_COUNT", "Failures"), ("QUEUED_COUNT", "Queued"), ("ACTIVE_COUNT", "Active")]:
        if col_name in snapshot.columns:
            values = snapshot[col_name].fillna(0).tolist()[-7:]
            total = int(snapshot[col_name].sum())
            if len(values) >= 2:
                sparkline_metrics.append((label, str(total), values))

    if sparkline_metrics:
        html = render_sparkline_snapshot(sparkline_metrics)
        if html:
            st.markdown(html, unsafe_allow_html=True)


def _render_healing_and_runbook() -> None:
    """Combined self-healing + runbook — only computed when expander is opened."""
    from utils.self_healing import evaluate_playbook
    from utils.operational_runbook import detect_pattern, get_runbook, render_runbook

    metrics = get_cached_metrics("dba_control_room_snapshot_result")
    failures = metrics.get("FAIL_COUNT", 0)

    # Self-healing suggestion
    if failures > 5:
        playbook = evaluate_playbook("resume_failed_task", "Failed Tasks", {"database": "", "schema": ""})
        if playbook["should_execute"]:
            st.markdown(f"**{playbook['playbook']}** — `{playbook['entity']}`")
            st.caption(playbook["reason"])
            st.code(playbook["sql"], language="sql")

    # Runbook
    st.divider()
    is_persistent = failures > 10
    pattern = detect_pattern("TASK", failures, is_transient=not is_persistent)
    runbook = get_runbook(pattern, "Failed Tasks")
    render_runbook(runbook)


def _render_workflow_grid() -> None:
    """Compact workflow grid — no descriptions, just action buttons."""
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"dba_cr_wf_{label}", width="stretch"):
                    _open_workspace(label)
