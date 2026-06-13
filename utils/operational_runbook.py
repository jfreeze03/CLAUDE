# utils/operational_runbook.py - Automated operational runbook generation
"""
Generates structured runbook entries from detected issues:
  - Incident response steps for common failure patterns
  - Escalation paths with owner/oncall information
  - Resolution verification queries
  - Post-incident review templates

Transforms "task failed" into a complete operator workflow.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


# Common failure pattern runbooks
RUNBOOK_TEMPLATES: dict[str, dict[str, Any]] = {
    "task_failure_transient": {
        "title": "Task Failure — Transient Error",
        "severity": "Medium",
        "steps": [
            "Check error code in TASK_HISTORY for transient indicators (timeout, throttle, temporary unavailability)",
            "Verify upstream data source is available",
            "Check warehouse auto-suspend/resume status",
            "Resume task if error was transient: ALTER TASK ... RESUME",
            "Monitor next scheduled run for success",
            "Close action queue item with resolution evidence",
        ],
        "escalation": "DBA On-Call → Pipeline Owner → DBA Lead",
        "verification_sql": """
SELECT name, state, scheduled_time, completed_time, error_code, error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE name = '{entity_name}'
  AND scheduled_time >= DATEADD('hour', -4, CURRENT_TIMESTAMP())
ORDER BY scheduled_time DESC
LIMIT 5
""",
    },
    "task_failure_persistent": {
        "title": "Task Failure — Persistent/Repeated",
        "severity": "High",
        "steps": [
            "Review error message pattern across last 5 failures",
            "Check for schema changes in referenced objects",
            "Verify role permissions haven't been revoked",
            "Check warehouse capacity — is it hitting resource monitor?",
            "Test task SQL manually in a worksheet",
            "Engage pipeline owner for fix",
            "Document root cause and resolution",
        ],
        "escalation": "DBA On-Call → Pipeline Owner → DBA Lead → Change Advisory",
        "verification_sql": """
SELECT name, state, error_code, error_message, scheduled_time
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE name = '{entity_name}'
  AND state = 'FAILED'
  AND scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
ORDER BY scheduled_time DESC
""",
    },
    "warehouse_queue_pressure": {
        "title": "Warehouse Queue Pressure",
        "severity": "Medium",
        "steps": [
            "Check current warehouse size and cluster configuration",
            "Review top queries by execution time in the last hour",
            "Identify if the pressure is from one large query or many concurrent small queries",
            "If concurrency: consider multi-cluster warehouse or query routing",
            "If single large query: check for missing clustering or full table scans",
            "If temporary spike: monitor for resolution within 30 minutes",
        ],
        "escalation": "DBA On-Call → Platform DBA → Warehouse Owner",
        "verification_sql": """
SELECT warehouse_name, COUNT(*) AS queued,
       MAX(queued_overload_time)/1000 AS max_queue_sec
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
    DATEADD('hour', -1, CURRENT_TIMESTAMP()), CURRENT_TIMESTAMP()))
WHERE warehouse_name = '{entity_name}'
  AND queued_overload_time > 0
GROUP BY warehouse_name
""",
    },
    "cost_spike": {
        "title": "Cost Spike — Warehouse Credit Anomaly",
        "severity": "High",
        "steps": [
            "Identify the time window of the spike",
            "Check for new workloads (new users, new queries, new tasks)",
            "Check for warehouse configuration changes (size increase, auto-suspend disabled)",
            "Check for schema changes that could cause full table scans",
            "Compare to baseline: is this a one-time event or recurring?",
            "Route to warehouse owner for confirmation",
            "If unauthorized: rollback configuration change",
        ],
        "escalation": "DBA On-Call → FinOps → Warehouse Owner → DBA Lead",
        "verification_sql": """
SELECT DATE(start_time) AS usage_date, warehouse_name,
       ROUND(SUM(credits_used), 2) AS daily_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = '{entity_name}'
  AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
GROUP BY usage_date, warehouse_name
ORDER BY usage_date DESC
""",
    },
    "security_privilege_escalation": {
        "title": "Privilege Escalation Detected",
        "severity": "Critical",
        "steps": [
            "Identify who performed the GRANT and when",
            "Verify the grant was authorized (check change ticket/approval)",
            "If unauthorized: REVOKE immediately and notify security team",
            "Review what access the escalated role provides",
            "Check if the role was used after escalation",
            "Document in security incident log",
            "Schedule access review for affected users",
        ],
        "escalation": "Security On-Call → DBA Lead → Security Approver → CISO",
        "verification_sql": """
SELECT user_name, role_name, query_type, start_time,
       SUBSTR(query_text, 1, 300) AS statement
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_type IN ('GRANT', 'REVOKE')
  AND start_time >= DATEADD('day', -1, CURRENT_TIMESTAMP())
  AND query_text ILIKE '%{entity_name}%'
ORDER BY start_time DESC
""",
    },
}


def get_runbook(pattern: str, entity_name: str = "") -> dict[str, Any]:
    """
    Get a runbook for a specific failure pattern.

    Args:
        pattern: Key from RUNBOOK_TEMPLATES
        entity_name: The affected entity (task name, warehouse name, etc.)

    Returns:
        Runbook dict with steps, escalation, and verification SQL.
    """
    template = RUNBOOK_TEMPLATES.get(pattern, {})
    if not template:
        return {
            "title": f"Unknown Pattern: {pattern}",
            "severity": "Medium",
            "steps": ["Investigate the issue manually", "Document findings", "Route to owner"],
            "escalation": "DBA On-Call → DBA Lead",
            "verification_sql": "",
        }

    runbook = dict(template)
    # Substitute entity name in SQL
    if entity_name and runbook.get("verification_sql"):
        safe_name = str(entity_name).replace("'", "''")
        runbook["verification_sql"] = runbook["verification_sql"].format(entity_name=safe_name)

    return runbook


def detect_pattern(
    entity_type: str,
    failure_count: int = 0,
    *,
    is_transient: bool = False,
    is_cost_spike: bool = False,
    is_security: bool = False,
    queue_pressure: bool = False,
) -> str:
    """Detect which runbook pattern matches the current situation."""
    if is_security:
        return "security_privilege_escalation"
    if is_cost_spike:
        return "cost_spike"
    if queue_pressure:
        return "warehouse_queue_pressure"
    if entity_type.upper() in ("TASK", "PROCEDURE"):
        if failure_count > 3 or not is_transient:
            return "task_failure_persistent"
        return "task_failure_transient"
    return "task_failure_transient"


def render_runbook(runbook: dict[str, Any], *, container=None) -> None:
    """Render a runbook as a structured operator guide."""
    target = container or st

    severity_colors = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}
    icon = severity_colors.get(runbook.get("severity", "Medium"), "⚪")

    target.markdown(f"{icon} **{runbook.get('title', 'Runbook')}**")
    target.caption(f"Severity: {runbook.get('severity', 'Medium')} · Escalation: {runbook.get('escalation', '')}")

    target.markdown("**Resolution Steps:**")
    for i, step in enumerate(runbook.get("steps", []), 1):
        target.markdown(f"{i}. {step}")

    if runbook.get("verification_sql"):
        with target.expander("Verification SQL"):
            target.code(runbook["verification_sql"].strip(), language="sql")
