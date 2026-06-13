# utils/company_config_loader.py - Dynamic company scope from database
"""
Loads company scoping configuration from OVERWATCH_COMPANY_SCOPE table
instead of requiring hardcoded config.py updates for each new company.

Supports:
  - Loading scope rules from Snowflake at startup
  - Graceful fallback to static config when Snowflake is unavailable
  - Caching to avoid repeated queries
  - Self-service onboarding of new companies via SQL INSERT

This is the path to supporting N companies without config.py changes.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


_COMPANY_SCOPE_CACHE_KEY = "_overwatch_dynamic_company_config"
_COMPANY_SCOPE_LOADED_KEY = "_overwatch_dynamic_company_config_loaded"


def build_load_company_scope_sql() -> str:
    """SQL to load company scope configuration."""
    return """
    SELECT
        COMPANY,
        SCOPE_TYPE,
        SCOPE_PATTERN,
        MATCH_MODE,
        ENVIRONMENT,
        IS_ACTIVE,
        NOTES
    FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_COMPANY_SCOPE
    WHERE COALESCE(IS_ACTIVE, TRUE)
    ORDER BY COMPANY, SCOPE_TYPE, SCOPE_PATTERN
    """


def load_company_config_from_db(session) -> dict[str, dict[str, Any]] | None:
    """
    Load company scope rules from OVERWATCH_COMPANY_SCOPE and convert
    to the COMPANY_CONFIG format expected by the rest of the app.

    Returns None if the table doesn't exist or query fails.
    """
    import pandas as pd

    try:
        df = session.sql(build_load_company_scope_sql()).to_pandas()
    except Exception:
        return None

    if df.empty:
        return None

    companies: dict[str, dict[str, Any]] = {}

    for company in df["COMPANY"].unique():
        company_df = df[df["COMPANY"] == company]
        config: dict[str, Any] = {
            "wh_patterns": [],
            "wh_exclude_patterns": [],
            "db_patterns": [],
            "db_exclude_patterns": [],
            "exclude_db_pattern": "",
            "user_patterns": [],
            "user_exclude_patterns": [],
            "label": str(company),
            "color": _company_color(str(company)),
        }

        for _, row in company_df.iterrows():
            scope_type = str(row.get("SCOPE_TYPE", "")).upper()
            pattern = str(row.get("SCOPE_PATTERN", ""))
            match_mode = str(row.get("MATCH_MODE", "ILIKE")).upper()

            if scope_type == "WAREHOUSE":
                if match_mode == "NOT_ILIKE":
                    config["wh_exclude_patterns"].append(pattern)
                else:
                    config["wh_patterns"].append(pattern)

            elif scope_type == "DATABASE":
                if match_mode == "NOT_ILIKE":
                    config["db_exclude_patterns"].append(pattern)
                else:
                    config["db_patterns"].append(pattern)

            elif scope_type == "USER":
                if match_mode == "NOT_ILIKE":
                    config["user_exclude_patterns"].append(pattern)
                else:
                    config["user_patterns"].append(pattern)

        companies[company] = config

    # Always add the ALL pseudo-company
    if "ALL" not in companies:
        companies["ALL"] = {
            "wh_patterns": [],
            "wh_exclude_patterns": [],
            "db_patterns": [],
            "db_exclude_patterns": [],
            "exclude_db_pattern": "",
            "user_patterns": [],
            "user_exclude_patterns": [],
            "label": "ALL",
            "color": "#38bdf8",
        }

    return companies


def _company_color(company: str) -> str:
    """Assign a consistent color to a company name."""
    colors = [
        "#34d399",  # green
        "#c084fc",  # purple
        "#38bdf8",  # blue
        "#f59e0b",  # amber
        "#f472b6",  # pink
        "#06b6d4",  # cyan
        "#a78bfa",  # violet
        "#fb923c",  # orange
    ]
    # Simple hash-based color assignment
    idx = hash(company.upper()) % len(colors)
    return colors[idx]


def get_dynamic_company_config(session=None) -> dict[str, dict[str, Any]] | None:
    """
    Get the dynamic company config, loading from DB if not cached.

    Returns None if loading fails (caller should fall back to static config).
    """
    # Check cache
    if st.session_state.get(_COMPANY_SCOPE_LOADED_KEY):
        return st.session_state.get(_COMPANY_SCOPE_CACHE_KEY)

    if session is None:
        return None

    try:
        config = load_company_config_from_db(session)
        if config:
            st.session_state[_COMPANY_SCOPE_CACHE_KEY] = config
            st.session_state[_COMPANY_SCOPE_LOADED_KEY] = True
            return config
    except Exception:
        pass

    return None


def merge_with_static_config(
    static_config: dict[str, dict[str, Any]],
    dynamic_config: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """
    Merge dynamic DB config with static fallback.
    Dynamic config wins for companies that exist in both.
    Static config provides defaults for companies not in DB.
    """
    if not dynamic_config:
        return static_config

    merged = dict(static_config)
    for company, config in dynamic_config.items():
        merged[company] = config

    return merged


def build_onboard_company_sql(
    company: str,
    warehouses: list[str],
    databases: list[str],
    *,
    exclude_warehouses: list[str] | None = None,
    user_patterns: list[str] | None = None,
) -> str:
    """Generate SQL to onboard a new company into OVERWATCH_COMPANY_SCOPE."""
    statements = []

    for wh in warehouses:
        safe_wh = str(wh).replace("'", "''")
        statements.append(
            f"INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_COMPANY_SCOPE "
            f"(COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, IS_ACTIVE, NOTES) "
            f"VALUES ('{company}', 'WAREHOUSE', '{safe_wh}', 'EQUALS', TRUE, 'Auto-onboarded');"
        )

    for db in databases:
        safe_db = str(db).replace("'", "''")
        statements.append(
            f"INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_COMPANY_SCOPE "
            f"(COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, IS_ACTIVE, NOTES) "
            f"VALUES ('{company}', 'DATABASE', '{safe_db}', 'EQUALS', TRUE, 'Auto-onboarded');"
        )

    for wh in (exclude_warehouses or []):
        safe_wh = str(wh).replace("'", "''")
        statements.append(
            f"INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_COMPANY_SCOPE "
            f"(COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, IS_ACTIVE, NOTES) "
            f"VALUES ('{company}', 'WAREHOUSE', '{safe_wh}', 'NOT_ILIKE', TRUE, 'Auto-onboarded exclusion');"
        )

    for pattern in (user_patterns or []):
        safe_pattern = str(pattern).replace("'", "''")
        statements.append(
            f"INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_COMPANY_SCOPE "
            f"(COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, IS_ACTIVE, NOTES) "
            f"VALUES ('{company}', 'USER', '{safe_pattern}', 'ILIKE', TRUE, 'Auto-onboarded');"
        )

    return "\n".join(statements)
