"""Shared helpers for section shells — redesigned for data-first UX."""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st


def evidence_loaded(state, keys: tuple[str, ...]) -> bool:
    return any(state.get(key) is not None for key in keys)


def evidence_label(state, keys: tuple[str, ...]) -> str:
    return "Loaded" if evidence_loaded(state, keys) else "On demand"


def action_state_label(state, keys: tuple[str, ...]) -> str:
    return "Loaded" if evidence_loaded(state, keys) else "Ready"


def evidence_caption(state, keys: tuple[str, ...], unloaded_caption: str) -> str:
    if evidence_loaded(state, keys):
        return "Loaded evidence is available; open the workspace to continue from the saved proof."
    return unloaded_caption


def compact_environment_label(environment: str | None) -> str:
    labels = {
        "ALL": "All env",
        "PROD": "Prod",
        "DEV_ALL": "All dev",
    }
    env_key = str(environment or "ALL")
    return labels.get(env_key, env_key)


def scope_label(company: str | None, environment: str | None) -> str:
    company_key = str(company or "ALL")
    return f"{company_key} / {compact_environment_label(environment)}"


def render_shell_snapshot(metrics: tuple[tuple[str, object], ...]) -> None:
    """Render lightweight shell snapshot cards without the bulk of metric widgets."""
    if not metrics:
        return
    cards = []
    for label, value in metrics:
        cards.append(
            '<div class="ow-shell-snapshot-card" style="display:flex;flex-direction:column;gap:2px;'
            'padding:8px 12px;border:1px solid var(--border-subtle,#334155);border-radius:6px;'
            'background:var(--bg-card,#1e293b);">'
            f'<span style="font-size:0.66rem;color:var(--text-muted,#94a3b8);text-transform:uppercase;'
            f'letter-spacing:0.04em;font-weight:700;">{html.escape(str(label))}</span>'
            f'<strong style="font-size:0.95rem;color:var(--text-primary,#eef8fb);font-weight:800;">'
            f'{html.escape(str(value))}</strong>'
            "</div>"
        )
    column_count = max(1, min(4, len(cards)))
    st.markdown(
        (
            '<div style="display:grid;gap:0.5rem;'
            f'grid-template-columns:repeat({column_count}, minmax(0, 1fr));">'
            f'{"".join(cards)}</div>'
        ),
        unsafe_allow_html=True,
    )


# ─── New data-first shell components ─────────────────────────────────────────


def render_status_strip(
    sections: list[tuple[str, str, str]],
) -> None:
    """Render a horizontal traffic-light status strip.

    Args:
        sections: list of (label, status, detail) where status is
                  "green", "yellow", "red", or "gray"
    """
    status_colors = {
        "green": "#22c55e",
        "yellow": "#f59e0b",
        "red": "#ef4444",
        "gray": "#64748b",
    }
    items = []
    for label, status, detail in sections:
        color = status_colors.get(status, "#64748b")
        safe_label = html.escape(str(label))
        safe_detail = html.escape(str(detail))
        items.append(
            f'<div class="ow-status-item">'
            f'<span class="ow-status-dot" style="background:{color};"></span>'
            f'<span class="ow-status-label">{safe_label}</span>'
            f'<span class="ow-status-detail">{safe_detail}</span>'
            f'</div>'
        )
    st.markdown(
        f'<div class="ow-status-strip">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


def render_kpi_row(
    kpis: list[tuple[str, str, str | None]],
) -> None:
    """Render a row of large KPI values with optional delta indicators.

    Args:
        kpis: list of (label, value, delta_text_or_None)
    """
    cards = []
    for label, value, delta in kpis:
        safe_label = html.escape(str(label))
        safe_value = html.escape(str(value))
        delta_html = ""
        if delta:
            is_negative = str(delta).startswith("-") or str(delta).startswith("↓")
            delta_color = "#22c55e" if is_negative else "#ef4444" if "+" in str(delta) or "↑" in str(delta) else "var(--text-muted)"
            safe_delta = html.escape(str(delta))
            delta_html = f'<span class="ow-kpi-delta" style="color:{delta_color};">{safe_delta}</span>'
        cards.append(
            f'<div class="ow-kpi-card">'
            f'<span class="ow-kpi-label">{safe_label}</span>'
            f'<span class="ow-kpi-value">{safe_value}</span>'
            f'{delta_html}'
            f'</div>'
        )
    col_count = max(1, min(5, len(cards)))
    st.markdown(
        f'<div class="ow-kpi-row" style="grid-template-columns:repeat({col_count}, minmax(0,1fr));">'
        f'{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_quick_actions(
    actions: list[tuple[str, str]],
    *,
    key_prefix: str = "qa",
) -> str | None:
    """Render a compact row of quick-action buttons. Returns clicked action label or None."""
    if not actions:
        return None
    cols = st.columns(len(actions))
    for i, (label, btn_label) in enumerate(actions):
        with cols[i]:
            if st.button(btn_label, key=f"{key_prefix}_{i}", width="stretch"):
                return label
    return None


def render_section_header(
    title: str,
    subtitle: str = "",
    *,
    status: str = "gray",
    show_workspace_button: bool = True,
    workspace_key: str = "open_workspace",
) -> bool:
    """Render a compact section header with optional workspace toggle.

    Returns True if the workspace button was clicked.
    """
    status_colors = {
        "green": "#22c55e",
        "yellow": "#f59e0b",
        "red": "#ef4444",
        "gray": "#64748b",
    }
    color = status_colors.get(status, "#64748b")
    safe_title = html.escape(str(title))
    safe_subtitle = html.escape(str(subtitle))

    col_header, col_action = st.columns([4.5, 1.5])
    with col_header:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{color};display:inline-block;"></span>'
            f'<span style="font-size:1.1rem;font-weight:800;color:var(--text-primary,#eef8fb);">{safe_title}</span>'
            f'</div>'
            f'<div style="font-size:0.78rem;color:var(--text-muted,#94a3b8);margin-left:16px;">{safe_subtitle}</div>',
            unsafe_allow_html=True,
        )
    with col_action:
        if show_workspace_button:
            return st.button("Open Full Workspace", key=workspace_key, type="primary", width="stretch")
    return False


def render_last_updated(timestamp_key: str = "") -> None:
    """Show when the shell was last rendered / evidence was last loaded."""
    ts = st.session_state.get(timestamp_key)
    if ts:
        st.caption(f"Last loaded: {ts}")
    else:
        now = datetime.now().strftime("%H:%M:%S")
        st.caption(f"Shell rendered: {now}")
