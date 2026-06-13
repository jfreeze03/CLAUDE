# utils/sla_tracking.py - Task/pipeline SLA compliance tracking
"""
Provides SLA compliance metrics for scheduled workloads:
  - Task completion within expected duration
  - Pipeline freshness against target windows
  - SLA compliance percentage (the number executives want)

Answers: "What percentage of our scheduled jobs completed on time?"
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st


def build_task_sla_compliance_sql(days_back: int = 7, sla_multiplier: float = 1.5) -> str:
    """SQL to compute task SLA compliance from TASK_HISTORY.

    A task "misses SLA" when its latest duration exceeds sla_multiplier times
    its historical average duration. This is a pragmatic definition when
    explicit SLA targets aren't configured per-task.
    """
    days_back = max(1, int(days_back or 7))
    sla_multiplier = max(1.0, float(sla_multiplier or 1.5))
    return f"""
    WITH task_runs AS (
        SELECT
            database_name,
            schema_name,
            name AS task_name,
            state,
            DATEDIFF('second', scheduled_time, completed_time) AS duration_sec,
            scheduled_time,
            completed_time
        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
        WHERE scheduled_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND state IN ('SUCCEEDED', 'FAILED', 'CANCELLED')
    ),
    task_baselines AS (
        SELECT
            database_name,
            schema_name,
            task_name,
            AVG(duration_sec) AS avg_duration_sec,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_sec) AS p95_duration_sec,
            COUNT(*) AS total_runs,
            COUNT_IF(state = 'SUCCEEDED') AS success_count,
            COUNT_IF(state = 'FAILED') AS failure_count
        FROM task_runs
        GROUP BY database_name, schema_name, task_name
    ),
    sla_assessment AS (
        SELECT
            b.database_name,
            b.schema_name,
            b.task_name,
            b.total_runs,
            b.success_count,
            b.failure_count,
            ROUND(b.avg_duration_sec, 1) AS avg_duration_sec,
            ROUND(b.p95_duration_sec, 1) AS p95_duration_sec,
            ROUND(b.avg_duration_sec * {sla_multiplier}, 1) AS sla_threshold_sec,
            COUNT_IF(r.duration_sec <= b.avg_duration_sec * {sla_multiplier} AND r.state = 'SUCCEEDED') AS within_sla_count,
            COUNT_IF(r.duration_sec > b.avg_duration_sec * {sla_multiplier} OR r.state != 'SUCCEEDED') AS sla_miss_count
        FROM task_baselines b
        JOIN task_runs r
          ON b.database_name = r.database_name
         AND b.schema_name = r.schema_name
         AND b.task_name = r.task_name
        GROUP BY
            b.database_name, b.schema_name, b.task_name,
            b.total_runs, b.success_count, b.failure_count,
            b.avg_duration_sec, b.p95_duration_sec
    )
    SELECT
        database_name,
        schema_name,
        task_name,
        total_runs,
        success_count,
        failure_count,
        avg_duration_sec,
        p95_duration_sec,
        sla_threshold_sec,
        within_sla_count,
        sla_miss_count,
        ROUND(within_sla_count * 100.0 / NULLIF(total_runs, 0), 1) AS sla_compliance_pct,
        CASE
            WHEN total_runs = 0 THEN 'No Data'
            WHEN within_sla_count * 100.0 / NULLIF(total_runs, 0) >= 99 THEN 'Excellent'
            WHEN within_sla_count * 100.0 / NULLIF(total_runs, 0) >= 95 THEN 'Good'
            WHEN within_sla_count * 100.0 / NULLIF(total_runs, 0) >= 90 THEN 'Acceptable'
            WHEN within_sla_count * 100.0 / NULLIF(total_runs, 0) >= 80 THEN 'At Risk'
            ELSE 'Critical'
        END AS sla_status
    FROM sla_assessment
    WHERE total_runs >= 3
    ORDER BY sla_compliance_pct ASC, sla_miss_count DESC
    """


def build_overall_sla_sql(days_back: int = 7, sla_multiplier: float = 1.5) -> str:
    """SQL for the single overall SLA compliance percentage."""
    days_back = max(1, int(days_back or 7))
    sla_multiplier = max(1.0, float(sla_multiplier or 1.5))
    return f"""
    WITH task_runs AS (
        SELECT
            database_name,
            schema_name,
            name AS task_name,
            state,
            DATEDIFF('second', scheduled_time, completed_time) AS duration_sec,
            scheduled_time
        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
        WHERE scheduled_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND state IN ('SUCCEEDED', 'FAILED', 'CANCELLED')
    ),
    task_baselines AS (
        SELECT
            database_name, schema_name, task_name,
            AVG(duration_sec) AS avg_duration_sec,
            COUNT(*) AS total_runs
        FROM task_runs
        GROUP BY database_name, schema_name, task_name
        HAVING COUNT(*) >= 3
    ),
    compliance AS (
        SELECT
            r.database_name,
            r.schema_name,
            r.task_name,
            CASE
                WHEN r.state = 'SUCCEEDED'
                 AND r.duration_sec <= b.avg_duration_sec * {sla_multiplier}
                    THEN 1
                ELSE 0
            END AS met_sla
        FROM task_runs r
        JOIN task_baselines b
          ON r.database_name = b.database_name
         AND r.schema_name = b.schema_name
         AND r.task_name = b.task_name
    )
    SELECT
        COUNT(*) AS total_runs,
        SUM(met_sla) AS within_sla,
        COUNT(*) - SUM(met_sla) AS missed_sla,
        ROUND(SUM(met_sla) * 100.0 / NULLIF(COUNT(*), 0), 1) AS overall_sla_pct,
        COUNT(DISTINCT task_name) AS tracked_tasks,
        COUNT(DISTINCT IFF(met_sla = 0, task_name, NULL)) AS tasks_with_misses
    FROM compliance
    """


def compute_sla_summary(sla_df) -> dict[str, Any]:
    """Compute SLA summary metrics from the overall SLA query result."""
    import pandas as pd

    result = {
        "overall_sla_pct": None,
        "total_runs": 0,
        "within_sla": 0,
        "missed_sla": 0,
        "tracked_tasks": 0,
        "tasks_with_misses": 0,
        "status": "No Data",
        "status_color": "#64748b",
    }

    if not isinstance(sla_df, pd.DataFrame) or sla_df.empty:
        return result

    row = sla_df.iloc[0]
    pct = float(row.get("OVERALL_SLA_PCT", 0) or 0)
    result["overall_sla_pct"] = pct
    result["total_runs"] = int(row.get("TOTAL_RUNS", 0) or 0)
    result["within_sla"] = int(row.get("WITHIN_SLA", 0) or 0)
    result["missed_sla"] = int(row.get("MISSED_SLA", 0) or 0)
    result["tracked_tasks"] = int(row.get("TRACKED_TASKS", 0) or 0)
    result["tasks_with_misses"] = int(row.get("TASKS_WITH_MISSES", 0) or 0)

    if pct >= 99:
        result["status"] = "Excellent"
        result["status_color"] = "#22c55e"
    elif pct >= 95:
        result["status"] = "Good"
        result["status_color"] = "#22c55e"
    elif pct >= 90:
        result["status"] = "Acceptable"
        result["status_color"] = "#f59e0b"
    elif pct >= 80:
        result["status"] = "At Risk"
        result["status_color"] = "#f97316"
    else:
        result["status"] = "Critical"
        result["status_color"] = "#ef4444"

    return result


def render_sla_badge(summary: dict[str, Any], *, container=None) -> None:
    """Render a compact SLA compliance badge."""
    target = container or st

    pct = summary.get("overall_sla_pct")
    status = summary.get("status", "No Data")
    color = summary.get("status_color", "#64748b")
    tracked = summary.get("tracked_tasks", 0)
    missed_tasks = summary.get("tasks_with_misses", 0)

    if pct is None:
        target.caption("SLA tracking requires task history (load Workload Operations first)")
        return

    target.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;padding:6px 12px;
             border:1px solid var(--border-subtle, #334155);border-radius:6px;
             background:var(--bg-card, #1e293b);">
            <div style="font-size:1.5rem;font-weight:800;color:{color};line-height:1;">
                {pct:.1f}%
            </div>
            <div style="font-size:0.7rem;color:var(--text-muted, #94a3b8);">
                <div>SLA Compliance · <strong style="color:{color};">{status}</strong></div>
                <div>{tracked} tasks tracked · {missed_tasks} with misses</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
