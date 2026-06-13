# utils/task_controls.py - Live task graph monitoring and execution controls
"""
Provides:
  - Live task graph visualization (running, succeeded, failed, scheduled)
  - Execute task on demand
  - Kill/cancel running task
  - Resume suspended task
  - Suspend running task
  - View task run history with duration and error details

All write operations require admin_actions_enabled() and are audit-logged.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def build_live_task_runs_sql() -> str:
    """SQL to get currently active and recent task runs from INFORMATION_SCHEMA."""
    return """
    SELECT
        database_name,
        schema_name,
        name AS task_name,
        state,
        scheduled_time,
        query_start_time,
        completed_time,
        DATEDIFF('second', query_start_time, COALESCE(completed_time, CURRENT_TIMESTAMP())) AS running_sec,
        error_code,
        error_message,
        run_id,
        root_task_id,
        graph_run_group_id,
        attempt_number
    FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
        SCHEDULED_TIME_RANGE_START => DATEADD('hour', -2, CURRENT_TIMESTAMP()),
        RESULT_LIMIT => 200
    ))
    ORDER BY scheduled_time DESC
    """


def build_task_graph_sql(root_task: str, database: str, schema: str) -> str:
    """SQL to get the task dependency tree for a root task."""
    safe_db = str(database).replace("'", "''")
    safe_schema = str(schema).replace("'", "''")
    safe_task = str(root_task).replace("'", "''")
    return f"""
    SELECT
        name AS task_name,
        database_name,
        schema_name,
        state,
        schedule,
        predecessors,
        warehouse,
        condition,
        definition
    FROM TABLE(INFORMATION_SCHEMA.TASK_DEPENDENTS(
        TASK_NAME => '{safe_db}.{safe_schema}.{safe_task}',
        RECURSIVE => TRUE
    ))
    ORDER BY name
    """


def load_live_task_status(session) -> list[dict[str, Any]]:
    """Load current task execution status."""
    try:
        rows = session.sql(build_live_task_runs_sql()).collect()
        tasks = []
        for row in rows:
            row_dict = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            tasks.append({
                "database": str(row_dict.get("DATABASE_NAME", "")),
                "schema": str(row_dict.get("SCHEMA_NAME", "")),
                "task_name": str(row_dict.get("TASK_NAME", "")),
                "state": str(row_dict.get("STATE", "")),
                "scheduled_time": row_dict.get("SCHEDULED_TIME"),
                "running_sec": int(row_dict.get("RUNNING_SEC", 0) or 0),
                "error_code": str(row_dict.get("ERROR_CODE", "") or ""),
                "error_message": str(row_dict.get("ERROR_MESSAGE", "") or ""),
                "graph_run_group": str(row_dict.get("GRAPH_RUN_GROUP_ID", "") or ""),
                "attempt": int(row_dict.get("ATTEMPT_NUMBER", 1) or 1),
            })
        return tasks
    except Exception as e:
        st.warning(f"Could not load live task status: {e}")
        return []


def execute_task(session, database: str, schema: str, task_name: str) -> dict[str, Any]:
    """Execute a task immediately (on-demand run)."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled to execute tasks."}

    safe_db = str(database).replace('"', '')
    safe_schema = str(schema).replace('"', '')
    safe_task = str(task_name).replace('"', '')
    fqn = f'"{safe_db}"."{safe_schema}"."{safe_task}"'
    sql = f"EXECUTE TASK {fqn}"

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="EXECUTE_TASK",
            target_object=fqn,
            sql_text=sql,
            result_status="SUCCESS",
            result_message="Task execution initiated",
        )
        return {"success": True, "message": f"Task {fqn} execution initiated."}
    except Exception as e:
        return {"success": False, "message": f"Failed to execute task: {str(e)[:200]}"}


def cancel_task(session, database: str, schema: str, task_name: str) -> dict[str, Any]:
    """Cancel/kill a running task by suspending it."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled to cancel tasks."}

    safe_db = str(database).replace('"', '')
    safe_schema = str(schema).replace('"', '')
    safe_task = str(task_name).replace('"', '')
    fqn = f'"{safe_db}"."{safe_schema}"."{safe_task}"'
    sql = f"ALTER TASK {fqn} SUSPEND"

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="CANCEL_TASK",
            target_object=fqn,
            sql_text=sql,
            result_status="SUCCESS",
            result_message="Task suspended (cancelled running execution)",
        )
        return {"success": True, "message": f"Task {fqn} suspended. Running queries will complete but no new runs will start."}
    except Exception as e:
        return {"success": False, "message": f"Failed to cancel task: {str(e)[:200]}"}


def resume_task(session, database: str, schema: str, task_name: str) -> dict[str, Any]:
    """Resume a suspended task."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled to resume tasks."}

    safe_db = str(database).replace('"', '')
    safe_schema = str(schema).replace('"', '')
    safe_task = str(task_name).replace('"', '')
    fqn = f'"{safe_db}"."{safe_schema}"."{safe_task}"'
    sql = f"ALTER TASK {fqn} RESUME"

    try:
        session.sql(sql).collect()
        log_admin_action(
            session,
            action_type="RESUME_TASK",
            target_object=fqn,
            sql_text=sql,
            result_status="SUCCESS",
            result_message="Task resumed",
        )
        return {"success": True, "message": f"Task {fqn} resumed."}
    except Exception as e:
        return {"success": False, "message": f"Failed to resume task: {str(e)[:200]}"}


def kill_query(session, query_id: str) -> dict[str, Any]:
    """Cancel a specific running query by ID."""
    from .admin import admin_actions_enabled, log_admin_action
    if not admin_actions_enabled():
        return {"success": False, "message": "Admin actions must be enabled to kill queries."}

    safe_id = str(query_id).replace("'", "''").replace(";", "")[:200]
    sql = f"SELECT SYSTEM$CANCEL_QUERY('{safe_id}')"

    try:
        result = session.sql(sql).collect()
        msg = str(result[0][0]) if result else "Query cancellation submitted"
        log_admin_action(
            session,
            action_type="KILL_QUERY",
            target_object=query_id,
            sql_text=sql,
            result_status="SUCCESS",
            result_message=msg,
        )
        return {"success": True, "message": msg}
    except Exception as e:
        return {"success": False, "message": f"Failed to cancel query: {str(e)[:200]}"}


def render_live_task_panel(session, *, container=None) -> None:
    """Render the live task graph monitoring and control panel."""
    target = container or st

    target.markdown("**Live Task Graph Monitor**")

    col_refresh, col_filter = target.columns([1, 2])
    with col_refresh:
        refresh = target.button("🔄 Refresh", key="task_live_refresh", type="primary")

    # Load live status
    if refresh or "task_live_data" not in st.session_state:
        tasks = load_live_task_status(session)
        st.session_state["task_live_data"] = tasks
        st.session_state["task_live_loaded_at"] = datetime.now().isoformat(timespec="seconds")
    else:
        tasks = st.session_state.get("task_live_data", [])

    if not tasks:
        target.info("No task runs in the last 2 hours, or insufficient privileges.")
        return

    # Loaded timestamp
    loaded_at = st.session_state.get("task_live_loaded_at", "")
    target.caption(f"Loaded: {loaded_at} · {len(tasks)} task runs")

    # State summary
    from collections import Counter
    state_counts = Counter(t["state"].upper() for t in tasks)
    running = state_counts.get("EXECUTING", 0) + state_counts.get("RUNNING", 0)
    succeeded = state_counts.get("SUCCEEDED", 0)
    failed = state_counts.get("FAILED", 0)
    scheduled = state_counts.get("SCHEDULED", 0)

    col_r, col_s, col_f, col_sch = target.columns(4)
    with col_r:
        target.metric("Running", str(running))
    with col_s:
        target.metric("Succeeded", str(succeeded))
    with col_f:
        target.metric("Failed", str(failed))
    with col_sch:
        target.metric("Scheduled", str(scheduled))

    target.divider()

    # Task list with action buttons
    from .admin import admin_actions_enabled
    admin_enabled = admin_actions_enabled()

    # Show running tasks first (most actionable)
    running_tasks = [t for t in tasks if t["state"].upper() in ("EXECUTING", "RUNNING")]
    failed_tasks = [t for t in tasks if t["state"].upper() == "FAILED"]
    other_tasks = [t for t in tasks if t["state"].upper() not in ("EXECUTING", "RUNNING", "FAILED")]

    if running_tasks:
        target.markdown("**🟢 Running**")
        for task in running_tasks[:10]:
            fqn = f"{task['database']}.{task['schema']}.{task['task_name']}"
            col_info, col_action = target.columns([3, 1])
            with col_info:
                target.markdown(f"`{fqn}` — running {task['running_sec']}s")
            with col_action:
                if admin_enabled:
                    if target.button("⏹ Kill", key=f"kill_{fqn}_{task.get('scheduled_time', '')}"):
                        result = cancel_task(session, task["database"], task["schema"], task["task_name"])
                        if result["success"]:
                            target.success(result["message"])
                        else:
                            target.error(result["message"])

    if failed_tasks:
        target.markdown("**🔴 Failed**")
        for task in failed_tasks[:10]:
            fqn = f"{task['database']}.{task['schema']}.{task['task_name']}"
            col_info, col_action = target.columns([3, 1])
            with col_info:
                error_preview = task["error_message"][:80] if task["error_message"] else task["error_code"]
                target.markdown(f"`{fqn}` — {error_preview}")
            with col_action:
                if admin_enabled:
                    col_exec, col_resume = target.columns(2)
                    with col_exec:
                        if target.button("▶ Run", key=f"exec_{fqn}"):
                            result = execute_task(session, task["database"], task["schema"], task["task_name"])
                            if result["success"]:
                                target.success(result["message"])
                            else:
                                target.error(result["message"])
                    with col_resume:
                        if target.button("↩ Resume", key=f"resume_{fqn}"):
                            result = resume_task(session, task["database"], task["schema"], task["task_name"])
                            if result["success"]:
                                target.success(result["message"])
                            else:
                                target.error(result["message"])

    if other_tasks and target.checkbox("Show succeeded/scheduled", key="task_show_other"):
        for task in other_tasks[:20]:
            fqn = f"{task['database']}.{task['schema']}.{task['task_name']}"
            target.caption(f"  {task['state']} · `{fqn}` · {task['running_sec']}s")


# Import datetime at module level for the panel
from datetime import datetime
