"""Warehouse Health — data-first shell with pressure metrics.

Shows:
  - Active warehouse count, idle credits, queue pressure
  - Remote spill and capacity utilization
  - Self-healing recommendations when idle waste detected
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


_FULL_WORKSPACE_KEY = "_warehouse_health_full_workspace_requested"
_BRIEF_MODE_KEY = "_warehouse_health_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "warehouse_health_data",
    "warehouse_health_snapshot",
    "warehouse_health_scaling",
    "wh_pressure_df",
    "wh_idle_df",
)

_WORKFLOWS = (
    ("Pressure & Queue", "Queue depth, concurrency, and setting review."),
    ("Idle & Waste", "Idle credits, suspend candidates, resize proof."),
    ("Scaling Events", "Auto-scale, multi-cluster, and cluster sizing."),
    ("Optimization", "Cache hits, spill, scan efficiency, resize."),
    ("Heatmap", "Time-of-day warehouse activity patterns."),
    ("Capacity Planning", "Growth forecast and right-sizing recommendations."),
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
        st.session_state["warehouse_health_pane"] = view
    st.rerun()

def _delegate_full_workspace() -> None:
    from sections import warehouse_health
    warehouse_health.render()

def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back", key="wh_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("warehouse_health_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Warehouse KPIs ────────────────────────────────────────────────────
    _render_warehouse_kpis()

    # ── 2. Optimization suggestions (when data loaded) ───────────────────────
    if _has_evidence():
        _render_optimization_hints()

    # ── 3. Warehouse Settings Control (dynamic) ──────────────────────────────
    from utils.perf import deferred_expander
    deferred_expander("⚙️ Warehouse Settings (resize, suspend, timeout)", _render_wh_settings, key="wh_settings_panel")

    # ── 4. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_warehouse_kpis() -> None:
    """Show warehouse health metrics from loaded evidence."""
    import pandas as pd

    snapshot = st.session_state.get("warehouse_health_snapshot")
    pressure = st.session_state.get("wh_pressure_df")
    idle = st.session_state.get("wh_idle_df")

    has_data = (
        (isinstance(snapshot, pd.DataFrame) and not snapshot.empty)
        or (isinstance(pressure, pd.DataFrame) and not pressure.empty)
        or (isinstance(idle, pd.DataFrame) and not idle.empty)
    )

    if has_data:
        # Extract metrics
        active_warehouses = 0
        total_credits = 0.0
        idle_credits = 0.0
        queue_pressure = 0
        remote_spill_gb = 0.0

        if isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
            active_warehouses = len(snapshot)
            if "TOTAL_CREDITS" in snapshot.columns:
                total_credits = float(pd.to_numeric(snapshot["TOTAL_CREDITS"], errors="coerce").sum())
            elif "CREDITS" in snapshot.columns:
                total_credits = float(pd.to_numeric(snapshot["CREDITS"], errors="coerce").sum())

        if isinstance(idle, pd.DataFrame) and not idle.empty:
            if "IDLE_CREDITS" in idle.columns:
                idle_credits = float(pd.to_numeric(idle["IDLE_CREDITS"], errors="coerce").sum())

        if isinstance(pressure, pd.DataFrame) and not pressure.empty:
            if "QUEUED_COUNT" in pressure.columns:
                queue_pressure = int(pd.to_numeric(pressure["QUEUED_COUNT"], errors="coerce").sum())
            if "REMOTE_SPILL_GB" in pressure.columns:
                remote_spill_gb = float(pd.to_numeric(pressure["REMOTE_SPILL_GB"], errors="coerce").sum())

        # Status determination
        if idle_credits > 50 or queue_pressure > 20:
            status, detail = "red", "Action needed"
        elif idle_credits > 10 or queue_pressure > 5:
            status, detail = "yellow", "Review recommended"
        else:
            status, detail = "green", "Healthy"

        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Warehouses", status, detail),
            ("Window", "green", _window_label()),
        ])

        credit_price = float(st.session_state.get("credit_price", 3.68))
        kpis = [
            ("Active WHs", str(active_warehouses), None),
            ("Total Credits", f"{total_credits:,.0f}", f"${total_credits * credit_price:,.0f}"),
            ("Idle Waste", f"{idle_credits:,.1f} cr", f"${idle_credits * credit_price:,.0f}" if idle_credits > 0 else None),
            ("Queue Pressure", str(queue_pressure), "Bottleneck" if queue_pressure > 10 else None),
        ]

        if remote_spill_gb > 0.1:
            kpis.append(("Remote Spill", f"{remote_spill_gb:.1f} GB", "Upsize candidate"))

        render_kpi_row(kpis)

        # Self-healing suggestion for idle waste
        if idle_credits > 10:
            st.caption(f"💡 {idle_credits:,.1f} idle credits detected. Open Idle & Waste for suspend candidates.")

    else:
        render_status_strip([
            ("Scope", "green", scope_label(_active_company(), _active_environment())),
            ("Warehouses", "gray", "No evidence loaded"),
            ("Window", "green", _window_label()),
        ])
        st.info("Open the workspace to load warehouse health evidence.")
        if st.button("Load Warehouse Health", key="wh_load", type="primary"):
            _open_workspace()


def _render_optimization_hints() -> None:
    """Show quick optimization suggestions from loaded warehouse data."""
    import pandas as pd
    from utils.capacity_planning import recommend_warehouse_size

    snapshot = st.session_state.get("warehouse_health_snapshot")
    if not isinstance(snapshot, pd.DataFrame) or snapshot.empty:
        return

    # Check for obvious optimization candidates
    hints = []

    # Look for warehouses with high queue but no spill (multi-cluster candidate)
    if all(c in snapshot.columns for c in ("WAREHOUSE_NAME", "QUEUED_COUNT")):
        high_queue = snapshot[pd.to_numeric(snapshot["QUEUED_COUNT"], errors="coerce").fillna(0) > 5]
        for _, row in high_queue.head(2).iterrows():
            wh = str(row.get("WAREHOUSE_NAME", ""))
            queue = int(row.get("QUEUED_COUNT", 0) or 0)
            hints.append(f"🔄 **{wh}** — {queue} queued queries. Consider multi-cluster or scaling.")

    # Look for idle warehouses
    idle_df = st.session_state.get("wh_idle_df")
    if isinstance(idle_df, pd.DataFrame) and not idle_df.empty and "IDLE_CREDITS" in idle_df.columns:
        top_idle = idle_df.sort_values("IDLE_CREDITS", ascending=False).head(2)
        for _, row in top_idle.iterrows():
            wh = str(row.get("WAREHOUSE_NAME", ""))
            credits = float(row.get("IDLE_CREDITS", 0) or 0)
            if credits > 5:
                hints.append(f"💤 **{wh}** — {credits:.1f} idle credits. Candidate for suspend timeout reduction.")

    if hints:
        with st.expander(f"💡 {len(hints)} Optimization Hint(s)", expanded=False):
            for hint in hints:
                st.markdown(hint)
            st.caption("Open Capacity Planning or Idle & Waste for full analysis and implementation SQL.")


def _render_wh_settings() -> None:
    """Render warehouse settings control panel (deferred)."""
    from utils.warehouse_controls import render_warehouse_settings_panel
    from utils.session import get_session_for_action

    session = get_session_for_action("manage warehouse settings", surface="Warehouse Health")
    if session:
        render_warehouse_settings_panel(session)


def _render_workflow_grid() -> None:
    for i in range(0, len(_WORKFLOWS), 3):
        batch = _WORKFLOWS[i:i + 3]
        cols = st.columns(3)
        for col, (label, _desc) in zip(cols, batch):
            with col:
                if st.button(label, key=f"wh_wf_{label}", width="stretch"):
                    _open_workspace(label)
