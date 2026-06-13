# utils/self_healing.py - Self-healing playbooks for known issue patterns
"""
When a known issue pattern is detected, automatically:
  1. Generate the fix SQL
  2. Validate it's safe (no destructive ops without approval)
  3. Present for one-click execution or auto-execute if pre-approved

Supported playbooks:
  - Idle warehouse suspension
  - Task resume after transient failure
  - Resource monitor credit quota adjustment
  - Warehouse auto-suspend timeout fix
  - Stale clustering key maintenance
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


PLAYBOOK_VERSION = "2026-06-10-v1"


# ─── Playbook definitions ────────────────────────────────────────────────────

PLAYBOOKS: dict[str, dict[str, Any]] = {
    "suspend_idle_warehouse": {
        "name": "Suspend Idle Warehouse",
        "trigger": "Warehouse consuming credits with zero query activity",
        "risk": "Low",
        "reversible": True,
        "requires_approval": False,
        "description": "Suspends a warehouse that has been idle for longer than the configured threshold.",
    },
    "resume_failed_task": {
        "name": "Resume Failed Task",
        "trigger": "Task in SUSPENDED_DUE_TO_FAILURE state with transient error",
        "risk": "Low",
        "reversible": True,
        "requires_approval": False,
        "description": "Resumes a task that was suspended due to a transient failure (timeout, throttle).",
    },
    "fix_auto_suspend": {
        "name": "Fix Auto-Suspend Timeout",
        "trigger": "Warehouse auto_suspend set to 0 or extremely high value",
        "risk": "Medium",
        "reversible": True,
        "requires_approval": True,
        "description": "Sets warehouse auto_suspend to 60 seconds (OVERWATCH standard).",
    },
    "adjust_resource_monitor": {
        "name": "Adjust Resource Monitor",
        "trigger": "Resource monitor approaching quota with no notify trigger",
        "risk": "Medium",
        "reversible": True,
        "requires_approval": True,
        "description": "Adds a notify trigger at 80% before the suspend trigger fires.",
    },
    "resize_oversized_warehouse": {
        "name": "Resize Oversized Warehouse",
        "trigger": "Warehouse consistently using <20% of capacity with zero spill",
        "risk": "High",
        "reversible": True,
        "requires_approval": True,
        "description": "Reduces warehouse size by one step after verifying no spill or queue pressure.",
    },
}


# ─── SQL generators ──────────────────────────────────────────────────────────

def generate_suspend_warehouse_sql(warehouse_name: str) -> str:
    """Generate SQL to suspend an idle warehouse."""
    safe_name = str(warehouse_name).replace("'", "''").replace(";", "")
    return f'ALTER WAREHOUSE IF EXISTS "{safe_name}" SUSPEND;'


def generate_resume_task_sql(database: str, schema: str, task_name: str) -> str:
    """Generate SQL to resume a suspended task."""
    safe_db = str(database).replace('"', '')
    safe_schema = str(schema).replace('"', '')
    safe_task = str(task_name).replace('"', '')
    return f'ALTER TASK IF EXISTS "{safe_db}"."{safe_schema}"."{safe_task}" RESUME;'


def generate_fix_auto_suspend_sql(warehouse_name: str, timeout_seconds: int = 60) -> str:
    """Generate SQL to fix warehouse auto-suspend timeout."""
    safe_name = str(warehouse_name).replace("'", "''").replace(";", "")
    timeout = max(30, int(timeout_seconds))
    return f'ALTER WAREHOUSE IF EXISTS "{safe_name}" SET AUTO_SUSPEND = {timeout};'


def generate_add_notify_trigger_sql(monitor_name: str, notify_pct: int = 80) -> str:
    """Generate SQL to add a notify trigger to a resource monitor."""
    safe_name = str(monitor_name).replace("'", "''").replace(";", "")
    pct = max(50, min(99, int(notify_pct)))
    return f'ALTER RESOURCE MONITOR IF EXISTS "{safe_name}" SET TRIGGERS ON {pct} PERCENT DO NOTIFY;'


def generate_resize_warehouse_sql(warehouse_name: str, new_size: str) -> str:
    """Generate SQL to resize a warehouse."""
    safe_name = str(warehouse_name).replace("'", "''").replace(";", "")
    valid_sizes = {"X-Small", "Small", "Medium", "Large", "X-Large", "2X-Large", "3X-Large", "4X-Large"}
    if new_size not in valid_sizes:
        return f"-- Invalid size: {new_size}. Valid: {', '.join(sorted(valid_sizes))}"
    return f"ALTER WAREHOUSE IF EXISTS \"{safe_name}\" SET WAREHOUSE_SIZE = '{new_size}';"


# ─── Playbook execution engine ───────────────────────────────────────────────

def evaluate_playbook(
    playbook_id: str,
    entity_name: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Evaluate whether a playbook should be triggered and generate the fix.

    Returns:
        {
            "playbook": str,
            "entity": str,
            "should_execute": bool,
            "requires_approval": bool,
            "sql": str,
            "risk": str,
            "reason": str,
            "validation_checks": [str],
        }
    """
    playbook = PLAYBOOKS.get(playbook_id)
    if not playbook:
        return {
            "playbook": playbook_id,
            "entity": entity_name,
            "should_execute": False,
            "requires_approval": True,
            "sql": "",
            "risk": "Unknown",
            "reason": f"Unknown playbook: {playbook_id}",
            "validation_checks": [],
        }

    result = {
        "playbook": playbook["name"],
        "entity": entity_name,
        "should_execute": True,
        "requires_approval": playbook["requires_approval"],
        "risk": playbook["risk"],
        "reason": playbook["trigger"],
        "validation_checks": [],
    }

    # Generate SQL based on playbook
    if playbook_id == "suspend_idle_warehouse":
        result["sql"] = generate_suspend_warehouse_sql(entity_name)
        result["validation_checks"] = [
            "Warehouse has zero queries in the last hour",
            "No scheduled tasks depend on this warehouse",
            "Warehouse is not OVERWATCH_WH",
        ]
        # Safety check: never suspend the OVERWATCH warehouse
        if "OVERWATCH" in entity_name.upper():
            result["should_execute"] = False
            result["reason"] = "Cannot suspend OVERWATCH warehouse"

    elif playbook_id == "resume_failed_task":
        evidence = evidence or {}
        db = evidence.get("database", "")
        schema = evidence.get("schema", "PUBLIC")
        result["sql"] = generate_resume_task_sql(db, schema, entity_name)
        result["validation_checks"] = [
            "Error was transient (timeout, throttle, temporary unavailability)",
            "Task has succeeded in the past 7 days",
            "No configuration change caused the failure",
        ]

    elif playbook_id == "fix_auto_suspend":
        result["sql"] = generate_fix_auto_suspend_sql(entity_name)
        result["validation_checks"] = [
            "Current auto_suspend is 0 or > 600 seconds",
            "Warehouse is not a dedicated always-on service",
            "Owner has been notified",
        ]

    elif playbook_id == "adjust_resource_monitor":
        result["sql"] = generate_add_notify_trigger_sql(entity_name)
        result["validation_checks"] = [
            "Monitor has a suspend trigger but no notify trigger",
            "Monitor is approaching quota (>70% used)",
        ]

    elif playbook_id == "resize_oversized_warehouse":
        new_size = (evidence or {}).get("recommended_size", "Small")
        result["sql"] = generate_resize_warehouse_sql(entity_name, new_size)
        result["validation_checks"] = [
            "Warehouse p95 query time is stable at current load",
            "Zero remote spill in the observation window",
            "Queue pressure is below threshold",
            "Owner approval obtained",
        ]

    return result


def execute_playbook(
    session,
    playbook_result: dict[str, Any],
    *,
    dry_run: bool = True,
    executed_by: str = "",
) -> dict[str, Any]:
    """
    Execute a playbook's SQL if approved.

    Args:
        session: Snowflake session
        playbook_result: Output from evaluate_playbook()
        dry_run: If True, validate but don't execute
        executed_by: Username for audit trail

    Returns:
        {"success": bool, "message": str, "executed": bool, "audit_logged": bool}
    """
    sql = playbook_result.get("sql", "")
    if not sql or sql.startswith("--"):
        return {"success": False, "message": "No executable SQL generated", "executed": False, "audit_logged": False}

    if not playbook_result.get("should_execute"):
        return {"success": False, "message": playbook_result.get("reason", "Blocked"), "executed": False, "audit_logged": False}

    if playbook_result.get("requires_approval") and not st.session_state.get("_playbook_approval_granted"):
        return {"success": False, "message": "Requires approval. Set approval in session state.", "executed": False, "audit_logged": False}

    if dry_run:
        return {"success": True, "message": f"DRY RUN: Would execute: {sql}", "executed": False, "audit_logged": False}

    # Execute
    try:
        session.sql(sql).collect()
        # Audit log
        try:
            audit_sql = (
                f"INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_ADMIN_ACTION_AUDIT "
                f"(ACTION_TYPE, TARGET_OBJECT, SQL_TEXT, RESULT_STATUS, RESULT_MESSAGE) "
                f"VALUES ('PLAYBOOK_EXECUTION', '{playbook_result['entity']}', "
                f"'{sql.replace(chr(39), chr(39)+chr(39))}', 'SUCCESS', '{playbook_result['playbook']}')"
            )
            session.sql(audit_sql).collect()
            audit_logged = True
        except Exception:
            audit_logged = False

        return {"success": True, "message": f"Executed: {sql}", "executed": True, "audit_logged": audit_logged}
    except Exception as e:
        return {"success": False, "message": f"Execution failed: {str(e)[:200]}", "executed": False, "audit_logged": False}


def render_playbook_card(
    playbook_result: dict[str, Any],
    *,
    container=None,
    key_prefix: str = "pb",
) -> bool:
    """Render a playbook recommendation card. Returns True if user clicked Execute."""
    target = container or st

    risk_colors = {"Low": "#22c55e", "Medium": "#f59e0b", "High": "#ef4444"}
    risk = playbook_result.get("risk", "Medium")
    color = risk_colors.get(risk, "#64748b")

    with target.container(border=True):
        col_info, col_action = target.columns([3.5, 1.5])
        with col_info:
            target.markdown(
                f"**{playbook_result.get('playbook', '?')}** — "
                f"`{playbook_result.get('entity', '?')}`"
            )
            target.caption(
                f"Risk: **{risk}** · {playbook_result.get('reason', '')}"
            )
            if playbook_result.get("sql"):
                target.code(playbook_result["sql"], language="sql")

        with col_action:
            if playbook_result.get("requires_approval"):
                target.caption("⚠️ Requires approval")
            if playbook_result.get("should_execute"):
                return target.button(
                    "Execute" if not playbook_result.get("requires_approval") else "Approve & Execute",
                    key=f"{key_prefix}_{playbook_result.get('entity', 'x')[:20]}",
                    type="primary" if risk == "Low" else "secondary",
                )
    return False
