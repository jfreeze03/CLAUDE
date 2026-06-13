# utils/perf.py - Production performance optimizations
"""
Centralized performance utilities:
  - Lazy import helpers (avoid importing pandas/altair until needed)
  - Session state caching with column pruning
  - Batched HTML rendering
  - Shell metric pre-computation
  - Query deduplication helpers
  - Fragment-safe rerun avoidance
"""
from __future__ import annotations

from typing import Any, Callable
import streamlit as st


# ─── Lazy imports ─────────────────────────────────────────────────────────────

_LAZY_MODULES: dict[str, Any] = {}


def lazy_import(module_name: str):
    """Import a module only once, caching the result process-wide."""
    if module_name not in _LAZY_MODULES:
        from importlib import import_module
        _LAZY_MODULES[module_name] = import_module(module_name)
    return _LAZY_MODULES[module_name]


def lazy_pandas():
    """Get pandas without importing on every rerun."""
    return lazy_import("pandas")


def lazy_altair():
    """Get altair without importing on every rerun."""
    return lazy_import("altair")


# ─── Session state DataFrame pruning ─────────────────────────────────────────

_SHELL_COLUMNS: dict[str, list[str]] = {
    "dba_control_room_snapshot_result": [
        "FAIL_COUNT", "QUEUED_COUNT", "ACTIVE_COUNT", "BLOCKED_COUNT",
    ],
    "cost_contract_cockpit": [
        "USAGE_DATE", "TOTAL_CREDITS", "CURRENT_CREDITS", "PRIOR_CREDITS",
        "VARIANCE_PCT", "WAREHOUSE_NAME", "TOP_INCREASE_WAREHOUSE",
        "TOP_INCREASE_CREDITS", "ACTIVE_WAREHOUSES",
    ],
    "warehouse_health_snapshot": [
        "WAREHOUSE_NAME", "TOTAL_CREDITS", "CREDITS", "QUEUED_COUNT",
        "REMOTE_SPILL_GB", "IDLE_CREDITS",
    ],
    "alert_center_data": [
        "STATUS", "SEVERITY", "ENTITY", "CREATED_AT",
    ],
    "security_posture_summary": [
        "SEVERITY", "FINDING_COUNT", "CATEGORY",
    ],
}


def store_pruned(key: str, df, *, keep_full: bool = True) -> None:
    """
    Store a DataFrame in session state with an optional pruned shell copy.

    The full DataFrame is stored under `key` for workspace use.
    A lightweight shell copy (only columns needed for KPIs) is stored
    under `{key}__shell` to avoid serializing unnecessary columns on reruns.
    """
    st.session_state[key] = df

    shell_cols = _SHELL_COLUMNS.get(key)
    if shell_cols and hasattr(df, "columns"):
        existing = [c for c in shell_cols if c in df.columns]
        if existing:
            st.session_state[f"{key}__shell"] = df[existing].copy()


def get_shell_df(key: str):
    """Get the lightweight shell DataFrame, falling back to full if not pruned."""
    shell = st.session_state.get(f"{key}__shell")
    if shell is not None:
        return shell
    return st.session_state.get(key)


# ─── Shell metric pre-computation ────────────────────────────────────────────

def precompute_shell_metrics(key: str, df) -> dict[str, Any]:
    """
    Compute and cache lightweight scalar metrics from a DataFrame.
    Avoids re-scanning the DataFrame on every shell rerun.
    """
    pd = lazy_pandas()
    cache_key = f"{key}__metrics"

    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}

    # Check if already computed for this data fingerprint
    fingerprint = (len(df), id(df))
    cached = st.session_state.get(cache_key)
    if isinstance(cached, dict) and cached.get("_fingerprint") == fingerprint:
        return cached

    metrics: dict[str, Any] = {"_fingerprint": fingerprint}

    if key == "dba_control_room_snapshot_result":
        for col in ("FAIL_COUNT", "QUEUED_COUNT", "ACTIVE_COUNT", "BLOCKED_COUNT"):
            if col in df.columns:
                metrics[col] = int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

    elif key in ("cost_contract_cockpit", "cost_contract_splash"):
        credit_col = next(
            (c for c in df.columns if "CREDIT" in c.upper() and "TOTAL" in c.upper()),
            next((c for c in df.columns if "CREDIT" in c.upper()), None),
        )
        if credit_col:
            metrics["total_credits"] = float(pd.to_numeric(df[credit_col], errors="coerce").fillna(0).sum())
            metrics["credit_column"] = credit_col
        if "VARIANCE_PCT" in df.columns:
            var_values = pd.to_numeric(df["VARIANCE_PCT"], errors="coerce")
            metrics["max_variance"] = float(var_values.max()) if not var_values.isna().all() else 0.0
        date_col = next((c for c in df.columns if "DATE" in c.upper()), None)
        if date_col:
            metrics["unique_dates"] = int(df[date_col].nunique())

    elif key == "alert_center_data":
        if "STATUS" in df.columns:
            statuses = df["STATUS"].str.upper()
            metrics["open_count"] = int(statuses.isin(["NEW", "OPEN", "ESCALATED"]).sum())
            metrics["total_count"] = len(df)
        if "SEVERITY" in df.columns:
            metrics["critical_count"] = int(df["SEVERITY"].str.upper().isin(["CRITICAL", "HIGH"]).sum())

    st.session_state[cache_key] = metrics
    return metrics


def get_cached_metrics(key: str) -> dict[str, Any]:
    """Retrieve pre-computed metrics without re-scanning the DataFrame."""
    cached = st.session_state.get(f"{key}__metrics")
    if isinstance(cached, dict):
        return cached

    # Compute on demand if the DataFrame exists
    df = st.session_state.get(key)
    pd = lazy_pandas()
    if isinstance(df, pd.DataFrame) and not df.empty:
        return precompute_shell_metrics(key, df)
    return {}


# ─── Batched HTML rendering ──────────────────────────────────────────────────

class HtmlBatch:
    """Accumulate HTML fragments and render in a single st.markdown call."""

    def __init__(self):
        self._parts: list[str] = []

    def add(self, html: str) -> "HtmlBatch":
        if html:
            self._parts.append(html)
        return self

    def render(self) -> None:
        if self._parts:
            st.markdown("".join(self._parts), unsafe_allow_html=True)
            self._parts.clear()

    def __bool__(self) -> bool:
        return bool(self._parts)


# ─── Deferred computation for expanders ──────────────────────────────────────

def deferred_expander(
    label: str,
    compute_fn: Callable[[], None],
    *,
    key: str,
    expanded: bool = False,
) -> None:
    """
    Render an expander that only computes content when the user has opened it.

    On first render, stores a flag. On subsequent renders, skips computation
    if the expander was never interacted with.
    """
    interaction_key = f"_expander_opened_{key}"

    # Always show the expander (Streamlit renders content regardless)
    # but skip expensive computation if user hasn't interacted
    was_opened = st.session_state.get(interaction_key, expanded)

    with st.expander(label, expanded=expanded):
        if was_opened or expanded:
            compute_fn()
            st.session_state[interaction_key] = True
        else:
            if st.button("Load content", key=f"_expander_load_{key}"):
                st.session_state[interaction_key] = True
                st.rerun()


# ─── Rerun avoidance ─────────────────────────────────────────────────────────

def navigate_without_rerun(section: str, **state_updates) -> None:
    """
    Queue a navigation change without calling st.rerun().

    The navigation will take effect on the next natural rerun (button click,
    widget interaction). Avoids double-rerun on button clicks that already
    trigger a rerun.
    """
    st.session_state["nav_section"] = section
    for key, value in state_updates.items():
        st.session_state[key] = value


def should_skip_rerun() -> bool:
    """
    Return True if the current render is already handling a pending navigation.
    Prevents the pattern: button click → st.rerun() → render → st.rerun() again.
    """
    return bool(st.session_state.get("_overwatch_pending_section"))


# ─── Per-section row limits ──────────────────────────────────────────────────

SECTION_ROW_LIMITS: dict[str, int] = {
    "shell_kpi": 50,
    "shell_sparkline": 30,
    "workspace_overview": 500,
    "workspace_detail": 2000,
    "workspace_full": 5000,
}


def get_row_limit(context: str = "workspace_overview") -> int:
    """Get the appropriate row limit for the current rendering context."""
    return SECTION_ROW_LIMITS.get(context, 5000)


# ─── Query deduplication ─────────────────────────────────────────────────────

_QUERY_DEDUP_CACHE: dict[str, str] = {}


def deduplicate_query_key(sql: str, scope: str = "") -> str:
    """
    Generate a deduplication key for a SQL query.
    If the same logical query is requested multiple times in one render,
    the cached result can be reused.
    """
    import hashlib
    key_input = f"{scope}:{sql[:500]}"
    return hashlib.sha1(key_input.encode("utf-8", errors="ignore")).hexdigest()[:16]
