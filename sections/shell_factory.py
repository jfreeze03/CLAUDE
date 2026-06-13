# sections/shell_factory.py - Shell generator to eliminate shell boilerplate
"""
Every shell follows the same pattern:
  1. Check if full workspace is requested → delegate
  2. Render status strip + KPIs from pre-computed metrics
  3. Render optional enrichments (sparklines, expanders)
  4. Render compact workflow grid

This factory generates the common infrastructure so each shell
only needs to define:
  - state_keys: Which session state keys hold evidence
  - workflows: List of (label, description) tuples
  - render_kpis(metrics): Custom KPI rendering function
  - workspace_module: The module to delegate to for full workspace
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import evidence_loaded, render_kpi_row, render_status_strip, scope_label
from utils.perf import get_cached_metrics


class ShellConfig:
    """Configuration for a data-first shell."""

    def __init__(
        self,
        *,
        section_name: str,
        workspace_module: str,
        state_keys: tuple[str, ...],
        workflows: tuple[tuple[str, str], ...],
        workspace_key_prefix: str,
    ):
        self.section_name = section_name
        self.workspace_module = workspace_module
        self.state_keys = state_keys
        self.workflows = workflows
        self.prefix = workspace_key_prefix
        self.full_workspace_key = f"_{workspace_key_prefix}_full_workspace_requested"
        self.brief_mode_key = f"_{workspace_key_prefix}_brief_mode"


def active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return "Selected"


def create_shell_render(
    config: ShellConfig,
    render_kpis_fn: Callable[[dict], None],
    *,
    render_enrichments_fn: Callable[[], None] | None = None,
    empty_action_label: str = "Load Evidence",
    metrics_key: str = "",
) -> Callable[[], None]:
    """
    Create a complete shell render() function from configuration.

    Args:
        config: Shell configuration
        render_kpis_fn: Function that takes pre-computed metrics dict and renders KPIs
        render_enrichments_fn: Optional function for sparklines/expanders after KPIs
        empty_action_label: Button label when no evidence is loaded
        metrics_key: Session state key for pre-computed metrics (default: first state_key)

    Returns:
        A render() function ready to be used as the shell's entry point.
    """
    _metrics_key = metrics_key or config.state_keys[0]

    def _full_workspace_requested() -> bool:
        if st.session_state.get(config.brief_mode_key):
            return False
        return bool(st.session_state.get(config.full_workspace_key))

    def _open_workspace(view: str | None = None) -> None:
        st.session_state[config.brief_mode_key] = False
        st.session_state[config.full_workspace_key] = True
        if view:
            st.session_state[f"{config.prefix}_active_view"] = view
        st.rerun()

    def _return_to_brief() -> None:
        st.session_state[config.brief_mode_key] = True
        st.session_state[config.full_workspace_key] = False
        st.rerun()

    def _delegate_workspace() -> None:
        from importlib import import_module
        mod = import_module(config.workspace_module)
        mod.render()

    def _render_workflow_grid() -> None:
        for i in range(0, len(config.workflows), 3):
            batch = config.workflows[i:i + 3]
            cols = st.columns(3)
            for col, (label, _) in zip(cols, batch):
                with col:
                    if st.button(label, key=f"{config.prefix}_wf_{label}", width="stretch"):
                        _open_workspace(label)

    def render() -> None:
        if _full_workspace_requested():
            col_back, _ = st.columns([1.0, 4.0])
            with col_back:
                if st.button("← Back", key=f"{config.prefix}_back", width="stretch"):
                    _return_to_brief()
            _delegate_workspace()
            return

        # Pre-computed metrics (fast path)
        metrics = get_cached_metrics(_metrics_key)
        has_data = bool(metrics) and any(
            v for k, v in metrics.items() if not k.startswith("_")
        )

        if has_data:
            render_kpis_fn(metrics)
            if render_enrichments_fn:
                render_enrichments_fn()
        else:
            render_status_strip([
                ("Scope", "green", scope_label(active_company(), active_environment())),
                (config.section_name, "gray", "No evidence loaded"),
                ("Window", "green", window_label()),
            ])
            st.info(f"Open the workspace to load {config.section_name.lower()} evidence.")
            if st.button(empty_action_label, key=f"{config.prefix}_load", type="primary"):
                _open_workspace()
            return

        st.divider()
        _render_workflow_grid()

    return render
