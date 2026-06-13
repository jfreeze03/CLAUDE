# sections/base.py - Shared section infrastructure
"""
Eliminates duplicated boilerplate across all workspace sections:
  - _lazy_util() pattern (single definition)
  - get_active_company() / get_active_environment() / get_credit_price()
  - Common imports and patterns

Usage in any section:
    from sections.base import lazy_util, get_active_company, get_credit_price
    run_query = lazy_util("run_query")
"""
from __future__ import annotations

from importlib import import_module

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, ENVIRONMENT_CONFIG
from utils.primitives import safe_float, safe_int, safe_str


def lazy_util(name: str):
    """Create a lazy-loaded reference to a utils function.

    Avoids importing the entire utils package on module load.
    The actual import happens on first call.
    """
    def _call(*args, **kwargs):
        import utils as _utils
        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


def get_active_company() -> str:
    """Return the currently selected company from session state."""
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    """Return the currently selected environment from session state."""
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def get_credit_price() -> float:
    """Return the configured credit price."""
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def get_ai_credit_price() -> float:
    """Return the configured AI/Cortex credit price."""
    return safe_float(st.session_state.get("ai_credit_price", DEFAULTS.get("ai_credit_price", 2.20)), 2.20)


def get_storage_cost() -> float:
    """Return the configured storage cost per TB."""
    return safe_float(st.session_state.get("storage_cost_per_tb", DEFAULTS.get("storage_cost_per_tb", 23.0)), 23.0)


def get_window_days() -> int:
    """Return the number of days in the current global date window."""
    from datetime import date
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return max(1, (end - start).days + 1)
    return 7


# ─── Common lazy util references (pre-built for convenience) ─────────────────

run_query = lazy_util("run_query")
run_query_or_raise = lazy_util("run_query_or_raise")
format_snowflake_error = lazy_util("format_snowflake_error")
get_session_for_action = lazy_util("get_session_for_action")
get_wh_filter_clause = lazy_util("get_wh_filter_clause")
get_db_filter_clause = lazy_util("get_db_filter_clause")
get_user_filter_clause = lazy_util("get_user_filter_clause")
download_csv = lazy_util("download_csv")
mark_loaded = lazy_util("mark_loaded")
render_priority_dataframe = lazy_util("render_priority_dataframe")
add_cost_companion_columns = lazy_util("add_cost_companion_columns")
