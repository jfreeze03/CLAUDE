"""Executive Landing — data-first command center for leadership.

Design philosophy:
  - Show numbers immediately, not "click here to see data"
  - Health score, cost burn, SLA compliance, and anomaly count visible on load
  - Workflow buttons are secondary, below the KPIs
  - Morning brief generation is one click
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    evidence_loaded,
    render_kpi_row,
    render_quick_actions,
    render_section_header,
    render_status_strip,
    scope_label,
)


_FULL_WORKSPACE_KEY = "_executive_landing_full_workspace_requested"
_BRIEF_MODE_KEY = "_executive_landing_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = ("executive_landing_snapshot",)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _credit_price() -> float:
    try:
        return float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)) or 3.68)
    except (TypeError, ValueError):
        return 3.68


def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return f"{int(DEFAULT_DAY_WINDOW)}d"


def _full_workspace_requested() -> bool:
    if st.session_state.get(_BRIEF_MODE_KEY):
        return False
    return bool(st.session_state.get(_FULL_WORKSPACE_KEY))


def _open_workspace() -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.rerun()


def _navigate(section: str, state_updates: dict[str, str] | None = None) -> None:
    st.session_state["nav_section"] = section
    for key, value in (state_updates or {}).items():
        st.session_state[key] = value
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import executive_landing
    executive_landing.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


# ─── Main render ─────────────────────────────────────────────────────────────


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back to Command Center", key="exec_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("executive_landing_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # ── 1. Platform Health Score (hero KPI) ──────────────────────────────────
    _render_health_hero()

    # ── 2. Status strip (traffic lights) ─────────────────────────────────────
    _render_platform_status()

    # ── 3. Key metrics row ───────────────────────────────────────────────────
    _render_executive_kpis()

    # Freshness indicator
    from utils.shell_metrics import render_loaded_at
    render_loaded_at("executive_landing_snapshot")

    # ── 4. Quick actions ─────────────────────────────────────────────────────
    st.divider()
    _render_executive_actions()

    # ── 5. Executive narrative + export ──────────────────────────────────────
    st.divider()
    col_narrative, col_export = st.columns(2)
    with col_narrative:
        with st.expander("Executive Narrative", expanded=False):
            from utils.executive_insights import render_executive_narrative
            render_executive_narrative()
    with col_export:
        with st.expander("Slide Deck Export", expanded=False):
            from utils.export_powerpoint import render_export_panel
            render_export_panel()

    # ── 6. OVERWATCH Agent (AI-powered investigation) ──────────────────────────
    with st.expander("🤖 OVERWATCH Agent (AI + SQL Tools)", expanded=False):
        from utils.cortex_agent import render_agent_panel
        from utils.session import get_session_for_action
        _agent_session = get_session_for_action("run AI agent", surface="Executive Landing")
        if _agent_session:
            render_agent_panel(_agent_session)
        else:
            st.caption("Snowflake connection required for AI Agent.")


def _render_health_hero() -> None:
    """The single most important number on the page."""
    from utils.health_score import compute_platform_health_score

    result = compute_platform_health_score()
    score = result["score"]
    grade = result["grade"]
    trend = result["trend"]
    components = result["components"]

    trend_arrows = {"improving": "↑", "declining": "↓", "stable": "→", "unknown": "·"}
    trend_colors = {"improving": "#22c55e", "declining": "#ef4444", "stable": "#94a3b8", "unknown": "#64748b"}

    if score >= 85:
        score_color = "#22c55e"
    elif score >= 70:
        score_color = "#f59e0b"
    elif score >= 55:
        score_color = "#f97316"
    else:
        score_color = "#ef4444"

    # Component bars
    component_html = ""
    for key, comp in components.items():
        label = key.replace("_", " ").title()
        pct = comp["score"]
        bar_color = "#22c55e" if pct >= 80 else "#f59e0b" if pct >= 60 else "#ef4444"
        component_html += (
            f'<div class="ow-health-component">'
            f'<span class="ow-health-comp-label">{label}</span>'
            f'<div class="ow-health-comp-bar"><div style="width:{pct}%;background:{bar_color};"></div></div>'
            f'<span class="ow-health-comp-score">{pct:.0f}</span>'
            f'</div>'
        )

    st.markdown(
        f"""
        <div class="ow-health-hero">
            <div class="ow-health-hero-left">
                <div class="ow-health-score" style="color:{score_color};">{score:.0f}</div>
                <div class="ow-health-meta">
                    <span class="ow-health-grade">Grade {grade}</span>
                    <span class="ow-health-trend" style="color:{trend_colors[trend]};">
                        {trend_arrows[trend]} {trend}
                    </span>
                </div>
                <div class="ow-health-label">Platform Health</div>
            </div>
            <div class="ow-health-hero-right">
                {component_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_platform_status() -> None:
    """Traffic-light strip showing status of each operational domain."""
    state = st.session_state

    def _domain_status(keys, good_label="Healthy", bad_label="Issues") -> tuple[str, str]:
        if not evidence_loaded(state, keys):
            return "gray", "No data"
        # Simple heuristic: if data exists, mark green unless we know it's bad
        return "green", good_label

    cost_status, cost_detail = _domain_status(
        ("cost_contract_cockpit", "cost_contract_splash"),
        "On track", "Review needed",
    )
    ops_status, ops_detail = _domain_status(
        ("dba_control_room_data", "dba_control_room_snapshot_result"),
        "Operational", "Incidents",
    )
    alerts_status, alerts_detail = _domain_status(
        ("alert_center_data",),
        "Clear", "Open alerts",
    )
    security_status, security_detail = _domain_status(
        ("security_posture_summary",),
        "Clean", "Findings",
    )

    # Override with actual data if available
    import pandas as pd

    alert_data = state.get("alert_center_data")
    if isinstance(alert_data, pd.DataFrame) and not alert_data.empty:
        if "STATUS" in alert_data.columns:
            open_count = len(alert_data[alert_data["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"])])
            if open_count > 10:
                alerts_status, alerts_detail = "red", f"{open_count} open"
            elif open_count > 3:
                alerts_status, alerts_detail = "yellow", f"{open_count} open"
            else:
                alerts_status, alerts_detail = "green", f"{open_count} open"

    dba_data = state.get("dba_control_room_snapshot_result")
    if isinstance(dba_data, pd.DataFrame) and not dba_data.empty:
        if "FAIL_COUNT" in dba_data.columns:
            failures = int(dba_data["FAIL_COUNT"].sum())
            if failures > 20:
                ops_status, ops_detail = "red", f"{failures} failures"
            elif failures > 5:
                ops_status, ops_detail = "yellow", f"{failures} failures"
            else:
                ops_status, ops_detail = "green", f"{failures} failures"

    render_status_strip([
        ("Cost", cost_status, cost_detail),
        ("Operations", ops_status, ops_detail),
        ("Alerts", alerts_status, alerts_detail),
        ("Security", security_status, security_detail),
    ])


def _render_executive_kpis() -> None:
    """Key metrics row — real numbers when available, placeholders when not."""
    import pandas as pd

    kpis = []

    # Credits consumed
    cockpit = st.session_state.get("cost_contract_cockpit")
    splash = st.session_state.get("cost_contract_splash")
    cost_df = cockpit if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else splash
    if isinstance(cost_df, pd.DataFrame) and not cost_df.empty:
        credit_col = next(
            (c for c in cost_df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
            next((c for c in cost_df.columns if "CREDIT" in c.upper()), None),
        )
        if credit_col:
            total = cost_df[credit_col].sum()
            kpis.append(("Credits", f"{total:,.0f}", f"${total * _credit_price():,.0f}"))
        else:
            kpis.append(("Credits", "—", None))
    else:
        kpis.append(("Credits", "—", "Load cost data"))

    # Contract burn
    contract_remaining = st.session_state.get("_contract_remaining_credits")
    if contract_remaining:
        kpis.append(("Remaining", f"{int(contract_remaining):,}", None))
    else:
        kpis.append(("Remaining", "—", "Set in Settings"))

    # Failures
    dba_data = st.session_state.get("dba_control_room_snapshot_result")
    if isinstance(dba_data, pd.DataFrame) and not dba_data.empty and "FAIL_COUNT" in dba_data.columns:
        failures = int(dba_data["FAIL_COUNT"].sum())
        kpis.append(("Failures", str(failures), None))
    else:
        kpis.append(("Failures", "—", None))

    # Open alerts
    alert_data = st.session_state.get("alert_center_data")
    if isinstance(alert_data, pd.DataFrame) and not alert_data.empty and "STATUS" in alert_data.columns:
        open_alerts = len(alert_data[alert_data["STATUS"].str.upper().isin(["NEW", "OPEN", "ESCALATED"])])
        kpis.append(("Open Alerts", str(open_alerts), None))
    else:
        kpis.append(("Open Alerts", "—", None))

    # Window
    kpis.append(("Window", _window_label(), _active_company()))

    render_kpi_row(kpis)


def _render_executive_actions() -> None:
    """Quick action buttons — the most common executive workflows."""
    col_brief, col_cost, col_ops, col_workspace = st.columns(4)

    with col_brief:
        if st.button("📋 Morning Brief", key="exec_morning_brief", width="stretch"):
            _render_morning_brief()

    with col_cost:
        if st.button("💰 Cost Detail", key="exec_cost", width="stretch"):
            _navigate("Cost & Contract")

    with col_ops:
        if st.button("🔧 Operations", key="exec_ops", width="stretch"):
            _navigate("DBA Control Room")

    with col_workspace:
        if st.button("📊 Full Workspace", key="exec_full", type="primary", width="stretch"):
            _open_workspace()

    # Morning brief inline (if just generated)
    if st.session_state.get("_exec_morning_brief_visible"):
        _show_morning_brief_panel()


def _render_morning_brief() -> None:
    st.session_state["_exec_morning_brief_visible"] = True
    st.rerun()


def _show_morning_brief_panel() -> None:
    from utils.morning_brief import build_morning_brief, format_brief_as_text, format_brief_as_html, render_morning_brief_preview

    brief = build_morning_brief()

    with st.container(border=True):
        render_morning_brief_preview(brief)
        st.divider()
        col_text, col_html, col_close = st.columns(3)
        with col_text:
            st.download_button(
                "Download Text",
                data=format_brief_as_text(brief),
                file_name=f"overwatch_brief_{date.today().isoformat()}.txt",
                mime="text/plain",
                key="exec_brief_txt",
            )
        with col_html:
            st.download_button(
                "Download HTML",
                data=format_brief_as_html(brief),
                file_name=f"overwatch_brief_{date.today().isoformat()}.html",
                mime="text/html",
                key="exec_brief_html",
            )
        with col_close:
            if st.button("Close", key="exec_brief_close", width="stretch"):
                st.session_state.pop("_exec_morning_brief_visible", None)
                st.rerun()
