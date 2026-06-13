# utils/warehouse_controls.py - Dynamic warehouse settings management
"""
Provides live warehouse setting inspection and modification:
  - View current settings (size, auto_suspend, auto_resume, clusters)
  - Resize warehouse dynamically
  - Alter auto-suspend timeout
  - Suspend/resume warehouse
  - All actions logged to OVERWATCH_ADMIN_ACTION_AUDIT

Safety: All write operations require admin_actions_enabled() gate.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def build_warehouse_settings_sql(warehouse_name: str = None) -> str:
    """SQL to get current warehouse settings."""
    if warehouse_name:
        safe_name = str(warehouse_name).replace("'", "''")
        return f"""
        SHOW WAREHOUSES LIKE '{safe_name}'
        """
    return "SHOW WAREHOUSES"


def load_warehouse_settings(session, warehouse_name: str = None) -> list[dict[str, Any]]:
    """Load current warehouse settings from Snowflake."""
    try:
        if warehouse_name:
            safe_name = str(warehouse_name).replace("'", "''")
            rows = session.sql(f"SHOW WAREHOUSES LIKE '{safe_name}'").collect()
        else:
            rows = session.sql("SHOW WAREHOUSES").collect()

        settings = []
        for row in rows:
            row_dict = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            settings.append({
                "name": str(row_dict.get("name", "")),
                "state": str(row_dict.get("state", "")),
                "size": str(row_dict.get("size", "")),
                "type": str(row_dict.get("type", "")),
                "auto_suspend": int(row_dict.get("auto_suspend", 0) or 0),
                "auto_resume": str(row_dict.get("auto_resume", "")),
                "min_cluster_count": int(row_dict.get("min_cluster_count", 1) or 1),
                "max_cluster_count": int(row_dict.get("max_cluster_count", 1) or 1),
                "scaling_policy": str(row_dict.get("scaling_policy", "")),
                "resource_monitor": str(row_dict.get("resource_monitor", "")),
                "owner": str(row_dict.get("owner", "")),
            })
        return settings
    except Exception as e:
        st.warning(f"Could not load warehouse settings: {e}")
        return []


def alter_warehouse_size(session, warehouse_name: str, new_size: str) -> dict[str, Any]:
    """Resize a warehouse with audit logging."""
    valid_sizes = ("X-Small", "Small", "Medium", "Large", "X-Large", "2X-Large", "3X-Large", "4X-Large")
    if new_size not in valid_sizes:
        return {"success": False, "message": f"Invalid size: {new_size}. Valid: {', '.join(valid_sizes)}"}

    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled in Settings to modify warehouses."}

    safe_name = str(warehouse_name).replace('"', '').replace("'", "")
    sql = f'ALTER WAREHOUSE "{safe_name}" SET WAREHOUSE_SIZE = \'{new_size}\''

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="ALTER_WAREHOUSE_SIZE",
            target_object=warehouse_name,
            sql_text=sql,
            result_status="SUCCESS",
            result_message=f"Resized to {new_size}",
        )
        return {"success": True, "message": f"Warehouse {warehouse_name} resized to {new_size}"}
    except Exception as e:
        return {"success": False, "message": f"Failed: {str(e)[:200]}"}


def alter_warehouse_suspend(session, warehouse_name: str, timeout_seconds: int) -> dict[str, Any]:
    """Change warehouse auto-suspend timeout with audit logging."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled."}

    timeout = max(0, int(timeout_seconds))
    safe_name = str(warehouse_name).replace('"', '').replace("'", "")
    sql = f'ALTER WAREHOUSE "{safe_name}" SET AUTO_SUSPEND = {timeout}'

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="ALTER_WAREHOUSE_SUSPEND",
            target_object=warehouse_name,
            sql_text=sql,
            result_status="SUCCESS",
            result_message=f"Auto-suspend set to {timeout}s",
        )
        return {"success": True, "message": f"Auto-suspend for {warehouse_name} set to {timeout}s"}
    except Exception as e:
        return {"success": False, "message": f"Failed: {str(e)[:200]}"}


def suspend_warehouse(session, warehouse_name: str) -> dict[str, Any]:
    """Suspend a warehouse immediately."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled."}

    safe_name = str(warehouse_name).replace('"', '').replace("'", "")
    sql = f'ALTER WAREHOUSE "{safe_name}" SUSPEND'

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="SUSPEND_WAREHOUSE",
            target_object=warehouse_name,
            sql_text=sql,
            result_status="SUCCESS",
        )
        return {"success": True, "message": f"Warehouse {warehouse_name} suspended"}
    except Exception as e:
        return {"success": False, "message": f"Failed: {str(e)[:200]}"}


def resume_warehouse(session, warehouse_name: str) -> dict[str, Any]:
    """Resume a suspended warehouse."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled."}

    safe_name = str(warehouse_name).replace('"', '').replace("'", "")
    sql = f'ALTER WAREHOUSE "{safe_name}" RESUME'

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="RESUME_WAREHOUSE",
            target_object=warehouse_name,
            sql_text=sql,
            result_status="SUCCESS",
        )
        return {"success": True, "message": f"Warehouse {warehouse_name} resumed"}
    except Exception as e:
        return {"success": False, "message": f"Failed: {str(e)[:200]}"}


def render_warehouse_settings_panel(session, *, container=None) -> None:
    """Render the interactive warehouse settings control panel."""
    target = container or st

    target.markdown("**Warehouse Settings Control**")

    # Load settings
    settings = load_warehouse_settings(session)
    if not settings:
        target.warning("No warehouses found or insufficient privileges.")
        return

    # Warehouse selector
    wh_names = [s["name"] for s in settings]
    selected_wh = target.selectbox("Warehouse", wh_names, key="wh_settings_select")

    current = next((s for s in settings if s["name"] == selected_wh), None)
    if not current:
        return

    # Display current settings
    col1, col2, col3, col4 = target.columns(4)
    with col1:
        target.metric("State", current["state"])
    with col2:
        target.metric("Size", current["size"])
    with col3:
        target.metric("Auto-Suspend", f"{current['auto_suspend']}s")
    with col4:
        target.metric("Clusters", f"{current['min_cluster_count']}-{current['max_cluster_count']}")

    target.caption(f"Owner: {current['owner']} | Resource Monitor: {current['resource_monitor'] or 'None'}")

    # Action controls
    target.divider()
    from .admin import admin_actions_enabled
    admin_enabled = admin_actions_enabled()

    if not admin_enabled:
        target.info("Enable Admin Actions in Settings to modify warehouse configuration.")
        return

    col_size, col_suspend, col_action = target.columns(3)

    with col_size:
        valid_sizes = ("X-Small", "Small", "Medium", "Large", "X-Large", "2X-Large", "3X-Large", "4X-Large")
        current_idx = valid_sizes.index(current["size"]) if current["size"] in valid_sizes else 0
        new_size = target.selectbox("New Size", valid_sizes, index=current_idx, key="wh_new_size")
        if target.button("Resize", key="wh_resize_btn", disabled=new_size == current["size"]):
            result = alter_warehouse_size(session, selected_wh, new_size)
            if result["success"]:
                target.success(result["message"])
            else:
                target.error(result["message"])

    with col_suspend:
        new_timeout = target.number_input("Auto-Suspend (sec)", value=current["auto_suspend"],
                                          min_value=0, max_value=3600, step=30, key="wh_new_suspend")
        if target.button("Set Timeout", key="wh_suspend_btn", disabled=new_timeout == current["auto_suspend"]):
            result = alter_warehouse_suspend(session, selected_wh, int(new_timeout))
            if result["success"]:
                target.success(result["message"])
            else:
                target.error(result["message"])

    with col_action:
        target.write("")
        if current["state"].upper() == "STARTED":
            if target.button("⏸ Suspend", key="wh_suspend_action", type="secondary"):
                result = suspend_warehouse(session, selected_wh)
                if result["success"]:
                    target.success(result["message"])
                else:
                    target.error(result["message"])
        else:
            if target.button("▶ Resume", key="wh_resume_action", type="primary"):
                result = resume_warehouse(session, selected_wh)
                if result["success"]:
                    target.success(result["message"])
                else:
                    target.error(result["message"])
