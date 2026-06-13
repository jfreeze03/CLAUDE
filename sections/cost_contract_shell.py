"""Cost & Contract — performance-optimized FinOps command center.

Perf optimizations:
  - Pre-computed metrics from cached scalars (no DataFrame re-scan)
  - Single batched HTML for status strip + KPIs
  - Lazy imports only when evidence exists
  - Deferred expanders for prediction/anomaly/chargeback
  - Cortex metrics from cached splash summary
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    evidence_loaded,
    render_kpi_row,
    render_status_strip,
    scope_label,
)
from utils.perf import get_cached_metrics, deferred_expander


_FULL_WORKSPACE_KEY = "_cost_contract_full_workspace_requested"
_BRIEF_MODE_KEY = "_cost_contract_brief_mode"
_DETAIL_WORKFLOW_KEY = "_cost_contract_detail_workflow"
_COST_SPLASH_KEY = "cost_contract_splash"
_FULL_WORKSPACE_STATE_KEYS = (
    _COST_SPLASH_KEY,
    "cost_contract_cockpit",
    "cost_contract_run_rate",
    "cost_contract_queue",
    "cost_contract_verification_health",
    "cost_contract_attribution_reconciliation",
    "cost_contract_service_lens",
    "cost_contract_budget_command_center",
    "cost_contract_spike_root_cause",
    "cost_contract_change_cost_correlation",
)

# Map shell button labels to actual workspace workflow names
_WORKFLOW_MAP = {
    "Bill & Attribution": "Explain bill / attribution / contract",
    "FinOps Controls": "FinOps Control Center",
    "Cortex Spend": "AI and Cortex spend",
    "Budget Gov": "Budget governance",
    "Anomaly Detection": "Cost anomaly detection",
    "Chargeback": "Chargeback allocation",
    "Recommendations": "Recommendations and action queue",
    "Network Costs": "Network and transfer costs",
    "Value Log": "Snowflake value log",
}


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
    selected_days = st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW)
    try:
        days = int(selected_days)
    except (TypeError, ValueError):
        days = int(DEFAULT_DAY_WINDOW)
    if days in DAY_WINDOW_OPTIONS:
        return f"{days}d"
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return f"{int(DEFAULT_DAY_WINDOW)}d"


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
        # Resolve shell label to workspace workflow name
        resolved = _WORKFLOW_MAP.get(workflow, workflow)
        st.session_state["cost_contract_workflow"] = resolved
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import cost_contract
    cost_contract.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _get_cost_df():
    """Get the best available cost DataFrame."""
    import pandas as pd
    cockpit = st.session_state.get("cost_contract_cockpit")
    splash = st.session_state.get(_COST_SPLASH_KEY)
    cost_df = cockpit if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else splash
    if isinstance(cost_df, pd.DataFrame) and not cost_df.empty:
        return cost_df
    return None


# ─── Main render ─────────────────────────────────────────────────────────────


def render() -> None:
    if _full_workspace_requested():
        col_back, _ = st.columns([1.0, 4.0])
        with col_back:
            if st.button("← Back to Cost Summary", key="cc_back", width="stretch"):
                _return_to_brief()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("cost_contract_shell_seen_at", datetime.now().isoformat(timespec="seconds"))

    # Use pre-computed metrics (fast path — no DataFrame scanning)
    metrics = get_cached_metrics("cost_contract_cockpit")
    if not metrics:
        metrics = get_cached_metrics("cost_contract_splash")
    has_data = bool(metrics.get("total_credits"))

    # ── 1. Cost KPIs + status ────────────────────────────────────────────────
    _render_cost_kpis_fast(metrics) if has_data else _render_cost_empty()

    if not has_data:
        return  # Skip rest when no evidence loaded

    # ── 2. Spend trend (lightweight sparkline only) ──────────────────────────
    _render_spend_sparkline()

    # ── 3. Deferred: Prediction + Anomalies + Chargeback (computed on open) ──
    deferred_expander("📈 Month-End Prediction", _render_month_end_prediction, key="cc_pred")
    deferred_expander("⚠️ Cost Anomalies", _render_cost_anomaly_summary, key="cc_anom")
    deferred_expander("📊 Service & Chargeback", _render_service_and_chargeback, key="cc_chargeback")
    deferred_expander("🤖 Cortex Code Settings & Security", _render_cortex_settings, key="cc_cortex")

    # ── 4. Workflow grid ─────────────────────────────────────────────────────
    st.divider()
    _render_workflow_grid()


def _render_cost_kpis_fast(metrics: dict) -> None:
    """Render KPIs from pre-computed metrics (no DataFrame access)."""
    total_credits = metrics.get("total_credits", 0)
    max_variance = metrics.get("max_variance", 0)
    unique_dates = metrics.get("unique_dates", 1)
    credit_price = _credit_price()
    total_cost = total_credits * credit_price

    # Status
    if max_variance > 30:
        status, status_detail = "red", f"Spike: {max_variance:.0f}%"
    elif max_variance > 15:
        status, status_detail = "yellow", f"Elevated: {max_variance:.0f}%"
    else:
        status, status_detail = "green", "On track"

    # Cortex status from splash summary
    cortex_spend, _, _, _ = _get_cortex_metrics()
    cortex_status = "yellow" if cortex_spend > 100 else "green" if cortex_spend > 0 else "gray"
    cortex_detail = f"${cortex_spend:,.0f}" if cortex_spend > 0 else "Not loaded"

    render_status_strip([
        ("Scope", "green", scope_label(_active_company(), _active_environment())),
        ("Window", "green", _window_label()),
        ("Compute", status, status_detail),
        ("AI/Cortex", cortex_status, cortex_detail),
        ("Rate", "green", f"${credit_price:.2f}/cr"),
    ])

    # KPIs from scalars
    days = max(1, unique_dates)
    daily_avg = total_credits / days

    kpis = [
        ("Total Spend", f"${total_cost:,.0f}", f"{total_credits:,.0f} credits"),
        ("Daily Avg", f"${daily_avg * credit_price:,.0f}", f"{daily_avg:,.0f} cr/day"),
        ("Monthly Run", f"${daily_avg * 30 * credit_price:,.0f}", f"{daily_avg * 30:,.0f} cr/mo"),
    ]

    remaining = st.session_state.get("_contract_remaining_credits")
    if remaining:
        days_left = int(remaining / daily_avg) if daily_avg > 0 else 999
        kpis.append(("Days Left", str(days_left), f"{int(remaining):,} cr"))
    else:
        kpis.append(("Window", _window_label(), _active_company()))

    render_kpi_row(kpis)

    # Cortex KPI row (only if AI costs exist)
    if cortex_spend > 0:
        _, cortex_credits, cortex_requests, top_user = _get_cortex_metrics()
        ai_price = float(st.session_state.get("ai_credit_price", 2.20))
        render_kpi_row([
            ("Cortex Cost", f"${cortex_spend:,.0f}", f"{cortex_credits:,.2f} AI cr"),
            ("AI Requests", f"{cortex_requests:,}", f"${cortex_spend / max(cortex_requests, 1):,.3f}/req" if cortex_requests > 0 else None),
            ("Top AI User", top_user[:18], None),
            ("AI Rate", f"${ai_price:.2f}/cr", None),
        ])


def _render_cost_empty() -> None:
    """No data state — single action button."""
    render_status_strip([
        ("Scope", "green", scope_label(_active_company(), _active_environment())),
        ("Window", "green", _window_label()),
        ("Cost", "gray", "No evidence loaded"),
    ])
    st.info("Open the workspace to load cost evidence.")
    if st.button("Load Cost Overview", key="cc_load", type="primary"):
        _open_workspace("Bill & Attribution")


def _render_spend_sparkline() -> None:
    """Lightweight sparkline — no heavy computation."""
    cost_df = _get_cost_df()
    if cost_df is None:
        return

    pd = __import__("pandas")
    credit_col = next(
        (c for c in cost_df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
        next((c for c in cost_df.columns if "CREDIT" in c.upper()), None),
    )
    if not credit_col:
        return

    values = pd.to_numeric(cost_df[credit_col], errors="coerce").fillna(0).tolist()
    if len(values) < 3:
        return

    from utils.sparklines import svg_sparkline
    spark = svg_sparkline(values[-14:], width=140, height=24, color="var(--accent, #29B5E8)")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin:2px 0 6px;">'
        f'<span style="font-size:0.7rem;color:var(--text-muted);">Spend trend</span>'
        f'{spark}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _get_cortex_metrics() -> tuple[float, float, int, str]:
    """Extract Cortex cost metrics from the splash summary or session state."""
    # First try the splash dict
    splash = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(splash, dict) and splash.get("loaded"):
        summary = splash.get("_summary")
        if isinstance(summary, dict):
            return (
                float(summary.get("cortex_spend", 0) or 0),
                float(summary.get("cortex_credits", 0) or 0),
                int(summary.get("cortex_requests", 0) or 0),
                str(summary.get("top_cortex_user", "No Cortex user")),
            )
        # Try the cortex sub-frame in the splash
        cortex_df = splash.get("cortex")
        if _is_valid_frame(cortex_df):
            row = cortex_df.iloc[0]
            return (
                float(row.get("CORTEX_SPEND_USD", 0) or 0),
                float(row.get("CORTEX_CREDITS", 0) or 0),
                int(row.get("CORTEX_REQUESTS", 0) or 0),
                str(row.get("TOP_CORTEX_USER", "No Cortex user")),
            )

    # Try the Cortex control summary from the dedicated cortex workflow
    cortex_summary = st.session_state.get("cortex_control_summary")
    if _is_valid_frame(cortex_summary):
        row = cortex_summary.iloc[0]
        spend = float(row.get("PROJECTED_30D_COST", 0) or 0)
        credits = float(row.get("TOTAL_CREDITS", row.get("CORTEX_CREDITS", 0)) or 0)
        requests = int(row.get("TOTAL_REQUESTS", row.get("CORTEX_REQUESTS", 0)) or 0)
        return spend, credits, requests, str(row.get("TOP_USER", "No user"))

    return 0.0, 0.0, 0, "No Cortex user"


def _get_top_cortex_user_spend() -> float:
    """Get the top Cortex user's spend from available evidence."""
    splash = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(splash, dict):
        summary = splash.get("_summary")
        if isinstance(summary, dict):
            return float(summary.get("top_cortex_user_spend", 0) or 0)
        cortex_df = splash.get("cortex")
        if _is_valid_frame(cortex_df):
            return float(cortex_df.iloc[0].get("TOP_CORTEX_USER_SPEND_USD", 0) or 0)
    return 0.0


def _is_valid_frame(value) -> bool:
    """Check if a value is a non-empty DataFrame."""
    import pandas as pd
    return isinstance(value, pd.DataFrame) and not value.empty


def _render_spend_trend_and_forecast() -> None:
    """Sparkline spend trend + contract burn forecast."""
    import pandas as pd
    from utils.sparklines import svg_sparkline
    from utils.contract_forecast import compute_burn_forecast, render_contract_burn_widget

    cost_df = _get_cost_df()
    if cost_df is None:
        return

    date_col = next((c for c in cost_df.columns if "DATE" in c.upper()), None)
    credit_col = next(
        (c for c in cost_df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
        next((c for c in cost_df.columns if "CREDIT" in c.upper()), None),
    )
    if not date_col or not credit_col:
        return

    # Sparkline
    daily_values = pd.to_numeric(cost_df[credit_col], errors="coerce").fillna(0).tolist()
    if len(daily_values) >= 3:
        spark = svg_sparkline(daily_values[-14:], width=120, height=24, color="var(--accent, #29B5E8)")
        total = sum(daily_values)
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:12px;margin:4px 0 8px;">'
            f'<span style="font-size:0.72rem;color:var(--text-muted);">Spend trend ({len(daily_values)}d)</span>'
            f'{spark}'
            f'<span style="font-size:0.72rem;color:var(--text-secondary);">{total:,.0f} cr total</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Burn forecast
    daily_df = cost_df[[date_col, credit_col]].rename(
        columns={date_col: "USAGE_DATE", credit_col: "DAILY_CREDITS"}
    )
    forecast = compute_burn_forecast(
        daily_df,
        contract_remaining=st.session_state.get("_contract_remaining_credits"),
        contract_total=st.session_state.get("_contract_total_credits"),
    )
    if forecast.get("observed_days", 0) >= 3:
        render_contract_burn_widget(forecast, compact=True)


def _render_month_end_prediction() -> None:
    """Show end-of-month cost prediction from loaded daily data."""
    import pandas as pd
    from utils.cost_prediction import predict_end_of_month_cost, render_prediction_widget

    cost_df = _get_cost_df()
    if cost_df is None:
        return

    credit_col = next(
        (c for c in cost_df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
        next((c for c in cost_df.columns if "CREDIT" in c.upper()), None),
    )
    if not credit_col:
        return

    daily_values = pd.to_numeric(cost_df[credit_col], errors="coerce").fillna(0).tolist()
    if len(daily_values) < 3:
        return

    prediction = predict_end_of_month_cost(
        daily_values,
        credit_price=_credit_price(),
    )

    if prediction["confidence"] != "insufficient_data":
        with st.expander("📈 Month-End Cost Prediction", expanded=False):
            render_prediction_widget(prediction)


def _render_cost_anomaly_summary() -> None:
    """Show cost anomaly detection summary when spikes exist."""
    import pandas as pd

    cost_df = _get_cost_df()
    if cost_df is None:
        return

    # Quick anomaly check from loaded variance data
    if "VARIANCE_PCT" not in cost_df.columns:
        return

    variance = pd.to_numeric(cost_df["VARIANCE_PCT"], errors="coerce")
    spikes = cost_df[variance > 20]
    if spikes.empty:
        return

    spike_count = len(spikes)
    max_spike = float(variance.max())

    # Determine severity
    if max_spike > 50:
        severity_color = "#ef4444"
        severity_label = "CRITICAL"
    elif max_spike > 30:
        severity_color = "#f97316"
        severity_label = "HIGH"
    else:
        severity_color = "#f59e0b"
        severity_label = "WATCH"

    # Find top warehouse if available
    wh_col = next((c for c in cost_df.columns if "WAREHOUSE" in c.upper()), None)
    top_driver = ""
    if wh_col and wh_col in spikes.columns:
        top_driver = f" · Top driver: {spikes.iloc[0].get(wh_col, '?')}"

    st.markdown(
        f'<div style="padding:8px 12px;border-left:3px solid {severity_color};'
        f'background:var(--bg-card,#1e293b);border-radius:0 6px 6px 0;margin:6px 0;'
        f'font-size:0.75rem;color:var(--text-secondary,#cbd5e1);">'
        f'<span style="color:{severity_color};font-weight:700;">{severity_label}</span> · '
        f'{spike_count} cost anomaly(s) detected · Peak: {max_spike:.0f}% above baseline{top_driver}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_service_and_chargeback() -> None:
    """Service cost breakdown and chargeback preview."""
    import pandas as pd

    # Service lens from loaded data
    service_lens = st.session_state.get("cost_contract_service_lens")
    if isinstance(service_lens, pd.DataFrame) and not service_lens.empty:
        with st.expander("Service Cost Breakdown", expanded=False):
            # Show top services by credit consumption
            credit_col = next(
                (c for c in service_lens.columns if "CREDIT" in c.upper() and "BILLED" in c.upper()),
                next((c for c in service_lens.columns if "CREDIT" in c.upper()), None),
            )
            category_col = next(
                (c for c in service_lens.columns if "CATEGORY" in c.upper()),
                next((c for c in service_lens.columns if "SERVICE" in c.upper()), None),
            )

            if credit_col and category_col:
                summary = (
                    service_lens.groupby(category_col)[credit_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(6)
                )
                for category, credits in summary.items():
                    cost_usd = float(credits) * _credit_price()
                    st.markdown(
                        f"**{category}** — {float(credits):,.0f} credits (${cost_usd:,.0f})"
                    )
            else:
                st.dataframe(service_lens.head(10), use_container_width=True)

    # Chargeback preview
    cost_df = _get_cost_df()
    if cost_df is not None:
        wh_col = next((c for c in cost_df.columns if "WAREHOUSE" in c.upper() and "NAME" in c.upper()), None)
        credit_col = next(
            (c for c in cost_df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
            next((c for c in cost_df.columns if "CREDIT" in c.upper()), None),
        )
        if wh_col and credit_col:
            with st.expander("Chargeback by Warehouse (preview)", expanded=False):
                chargeback = (
                    cost_df.groupby(wh_col)[credit_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(8)
                )
                for wh, credits in chargeback.items():
                    cost_usd = float(credits) * _credit_price()
                    pct = float(credits) / cost_df[credit_col].sum() * 100 if cost_df[credit_col].sum() > 0 else 0
                    st.markdown(f"**{wh}** — {float(credits):,.0f} cr (${cost_usd:,.0f}) · {pct:.1f}%")


def _render_cortex_settings() -> None:
    """Render Cortex Code settings and security panel (deferred)."""
    from utils.cortex_settings import render_cortex_settings_panel
    from utils.session import get_session_for_action

    session = get_session_for_action("view Cortex settings", surface="Cost & Contract")
    if session:
        render_cortex_settings_panel(session)


def _render_workflow_grid() -> None:
    """Compact workflow grid with mapped labels."""
    workflow_labels = list(_WORKFLOW_MAP.keys())
    for i in range(0, len(workflow_labels), 3):
        batch = workflow_labels[i:i + 3]
        cols = st.columns(3)
        for col, label in zip(cols, batch):
            with col:
                if st.button(label, key=f"cc_wf_{label}", width="stretch"):
                    _open_workspace(label)
