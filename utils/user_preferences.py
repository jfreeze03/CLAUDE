# utils/user_preferences.py - Persistent user preferences via Snowflake
"""
Stores and retrieves user-specific settings from OVERWATCH_SETTINGS:
  - Theme selection
  - Credit price overrides
  - Contract capacity
  - Experience view preference

Settings persist across sessions so users don't have to re-configure
every time they open the app.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


_PREFS_LOADED_KEY = "_overwatch_user_prefs_loaded"
_PREFS_TABLE = "DBA_MAINT_DB.OVERWATCH.OVERWATCH_SETTINGS"

# Settings we persist per-user
_PERSISTABLE_SETTINGS = {
    "active_theme": "THEME",
    "credit_price": "CREDIT_PRICE_USD",
    "ai_credit_price": "AI_CREDIT_PRICE_USD",
    "storage_cost_per_tb": "STORAGE_COST_PER_TB",
    "_contract_total_credits": "CONTRACT_TOTAL_CREDITS",
    "_contract_remaining_credits": "CONTRACT_REMAINING_CREDITS",
    "overwatch_experience_view": "EXPERIENCE_VIEW",
    "exceptions_only_mode": "EXCEPTIONS_ONLY_MODE",
}


def load_user_preferences(session) -> dict[str, Any]:
    """Load user preferences from OVERWATCH_SETTINGS table."""
    if st.session_state.get(_PREFS_LOADED_KEY):
        return {}

    try:
        rows = session.sql(f"""
            SELECT SETTING_NAME, SETTING_VALUE, SETTING_TYPE
            FROM {_PREFS_TABLE}
            WHERE SETTING_NAME IN ({', '.join(f"'{v}'" for v in _PERSISTABLE_SETTINGS.values())})
        """).collect()

        prefs = {}
        for row in rows:
            row_dict = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            name = str(row_dict.get("SETTING_NAME", ""))
            value = str(row_dict.get("SETTING_VALUE", ""))
            stype = str(row_dict.get("SETTING_TYPE", "STRING"))

            # Find the session state key for this setting
            state_key = next((k for k, v in _PERSISTABLE_SETTINGS.items() if v == name), None)
            if state_key:
                if stype == "NUMBER":
                    try:
                        prefs[state_key] = float(value)
                    except ValueError:
                        pass
                elif stype == "BOOLEAN":
                    prefs[state_key] = value.lower() in ("true", "1", "yes")
                else:
                    prefs[state_key] = value

        st.session_state[_PREFS_LOADED_KEY] = True
        return prefs
    except Exception:
        st.session_state[_PREFS_LOADED_KEY] = True
        return {}


def apply_preferences(prefs: dict[str, Any]) -> None:
    """Apply loaded preferences to session state (only if not already set by user)."""
    for key, value in prefs.items():
        if key not in st.session_state or st.session_state.get(key) is None:
            st.session_state[key] = value


def save_user_preferences(session) -> bool:
    """Save current settings to OVERWATCH_SETTINGS for persistence."""
    try:
        for state_key, setting_name in _PERSISTABLE_SETTINGS.items():
            value = st.session_state.get(state_key)
            if value is None:
                continue

            # Determine type
            if isinstance(value, bool):
                stype = "BOOLEAN"
                svalue = "true" if value else "false"
            elif isinstance(value, (int, float)):
                stype = "NUMBER"
                svalue = str(value)
            else:
                stype = "STRING"
                svalue = str(value)

            safe_value = svalue.replace("'", "''")
            session.sql(f"""
                MERGE INTO {_PREFS_TABLE} tgt
                USING (SELECT '{setting_name}' AS SETTING_NAME) src
                ON tgt.SETTING_NAME = src.SETTING_NAME
                WHEN MATCHED THEN UPDATE SET
                    SETTING_VALUE = '{safe_value}',
                    SETTING_TYPE = '{stype}',
                    UPDATED_AT = CURRENT_TIMESTAMP(),
                    UPDATED_BY = CURRENT_USER()
                WHEN NOT MATCHED THEN INSERT (SETTING_NAME, SETTING_VALUE, SETTING_TYPE, DESCRIPTION)
                VALUES ('{setting_name}', '{safe_value}', '{stype}', 'User preference')
            """).collect()

        return True
    except Exception:
        return False


def render_save_preferences_button(session, *, container=None) -> None:
    """Render a button to persist current settings."""
    target = container or st
    if target.button("💾 Save Settings", key="save_prefs_btn", help="Persist current settings across sessions"):
        if save_user_preferences(session):
            target.success("Settings saved.")
        else:
            target.warning("Could not save settings (check permissions on OVERWATCH_SETTINGS).")
