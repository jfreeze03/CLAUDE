# utils/pipeline_freshness.py - Pipeline freshness SLA monitoring
"""
Tracks pipeline freshness as a first-class operational metric:
  - Expected refresh intervals per table/pipeline
  - Actual last-load timestamps vs SLA targets
  - Freshness breach alerting
  - Snowpipe and task-based pipeline status

Answers: "Is our data arriving on time?"
"""
from __future__ import annotations

from typing import Any


def build_pipeline_status_sql(days_back: int = 3) -> str:
    """SQL to get current pipeline/load status from multiple sources."""
    days_back = max(1, int(days_back or 3))
    return f"""
    WITH task_pipelines AS (
        SELECT
            database_name,
            schema_name,
            name AS pipeline_name,
            'TASK' AS pipeline_type,
            state,
            scheduled_time,
            completed_time,
            DATEDIFF('minute', scheduled_time, COALESCE(completed_time, CURRENT_TIMESTAMP())) AS duration_min,
            ROW_NUMBER() OVER (PARTITION BY database_name, schema_name, name ORDER BY scheduled_time DESC) AS rn
        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
        WHERE scheduled_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
    ),
    snowpipe_pipelines AS (
        SELECT
            pipe_catalog AS database_name,
            pipe_schema AS schema_name,
            pipe_name AS pipeline_name,
            'SNOWPIPE' AS pipeline_type,
            'LOADED' AS state,
            last_load_time AS scheduled_time,
            last_load_time AS completed_time,
            0 AS duration_min,
            ROW_NUMBER() OVER (PARTITION BY pipe_catalog, pipe_schema, pipe_name ORDER BY last_load_time DESC) AS rn
        FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
        WHERE last_load_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
    ),
    combined AS (
        SELECT * FROM task_pipelines WHERE rn = 1
        UNION ALL
        SELECT * FROM snowpipe_pipelines WHERE rn = 1
    )
    SELECT
        database_name,
        schema_name,
        pipeline_name,
        pipeline_type,
        state,
        scheduled_time AS last_run_time,
        completed_time,
        duration_min,
        DATEDIFF('minute', COALESCE(completed_time, scheduled_time), CURRENT_TIMESTAMP()) AS minutes_since_last,
        CASE
            WHEN state = 'FAILED' THEN 'Failed'
            WHEN DATEDIFF('hour', COALESCE(completed_time, scheduled_time), CURRENT_TIMESTAMP()) > 24 THEN 'Critical'
            WHEN DATEDIFF('hour', COALESCE(completed_time, scheduled_time), CURRENT_TIMESTAMP()) > 6 THEN 'Stale'
            WHEN state = 'SUCCEEDED' OR state = 'LOADED' THEN 'Fresh'
            ELSE 'Unknown'
        END AS freshness_status
    FROM combined
    ORDER BY
        CASE freshness_status
            WHEN 'Failed' THEN 1
            WHEN 'Critical' THEN 2
            WHEN 'Stale' THEN 3
            ELSE 4
        END,
        minutes_since_last DESC
    """


def build_snowpipe_health_sql(days_back: int = 7) -> str:
    """SQL to check Snowpipe-specific health."""
    days_back = max(1, int(days_back or 7))
    return f"""
    SELECT
        pipe_catalog AS database_name,
        pipe_schema AS schema_name,
        pipe_name,
        DATE(last_load_time) AS load_date,
        SUM(files_inserted) AS files_loaded,
        SUM(bytes_inserted) / (1024*1024*1024.0) AS gb_loaded,
        SUM(credits_used) AS pipe_credits,
        COUNT(*) AS load_events
    FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
    WHERE last_load_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
    GROUP BY database_name, schema_name, pipe_name, load_date
    ORDER BY load_date DESC, pipe_credits DESC
    """


def summarize_pipeline_health(pipeline_df) -> dict[str, Any]:
    """Summarize pipeline health into executive metrics."""
    import pandas as pd

    result = {
        "total_pipelines": 0,
        "fresh": 0,
        "stale": 0,
        "failed": 0,
        "critical": 0,
        "freshness_pct": 0.0,
        "status": "unknown",
        "top_issues": [],
    }

    if not isinstance(pipeline_df, pd.DataFrame) or pipeline_df.empty:
        return result

    result["total_pipelines"] = len(pipeline_df)

    if "FRESHNESS_STATUS" in pipeline_df.columns:
        status_counts = pipeline_df["FRESHNESS_STATUS"].str.upper().value_counts()
        result["fresh"] = int(status_counts.get("FRESH", 0))
        result["stale"] = int(status_counts.get("STALE", 0))
        result["failed"] = int(status_counts.get("FAILED", 0))
        result["critical"] = int(status_counts.get("CRITICAL", 0))

        total = result["total_pipelines"]
        result["freshness_pct"] = round(result["fresh"] / total * 100, 1) if total > 0 else 0

        if result["failed"] > 0 or result["critical"] > 0:
            result["status"] = "critical"
        elif result["stale"] > 3:
            result["status"] = "warning"
        elif result["stale"] > 0:
            result["status"] = "watch"
        else:
            result["status"] = "healthy"

        # Top issues
        problem_pipes = pipeline_df[
            pipeline_df["FRESHNESS_STATUS"].str.upper().isin(["FAILED", "CRITICAL", "STALE"])
        ]
        for _, row in problem_pipes.head(5).iterrows():
            result["top_issues"].append(
                f"{row.get('PIPELINE_NAME', '?')} ({row.get('PIPELINE_TYPE', '?')}): "
                f"{row.get('FRESHNESS_STATUS', '?')} — {row.get('MINUTES_SINCE_LAST', 0):.0f}min ago"
            )

    return result
