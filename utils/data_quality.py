# utils/data_quality.py - Data quality monitoring for upstream pipelines
"""
Monitors:
  - Row count drift (tables that stopped growing or shrunk)
  - Load freshness SLA (tables that haven't been loaded recently)
  - Schema change detection
  - Pipeline volume anomalies

Answers: "Is our upstream data flowing and healthy?"
"""
from __future__ import annotations

from typing import Any


def build_load_freshness_sql(days_back: int = 7, stale_hours: int = 24) -> str:
    """SQL to detect tables that haven't received fresh data within the SLA window."""
    days_back = max(1, int(days_back or 7))
    stale_hours = max(1, int(stale_hours or 24))
    return f"""
    WITH recent_loads AS (
        SELECT
            table_catalog AS database_name,
            table_schema AS schema_name,
            table_name,
            MAX(last_load_time) AS last_load_time,
            COUNT(*) AS load_count,
            SUM(row_count) AS total_rows_loaded
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOAD_HISTORY
        WHERE last_load_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
        GROUP BY table_catalog, table_schema, table_name
    ),
    table_metadata AS (
        SELECT
            table_catalog AS database_name,
            table_schema AS schema_name,
            table_name,
            row_count,
            bytes,
            last_altered
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
        WHERE deleted IS NULL
          AND table_type = 'BASE TABLE'
          AND row_count > 0
    )
    SELECT
        COALESCE(rl.database_name, tm.database_name) AS database_name,
        COALESCE(rl.schema_name, tm.schema_name) AS schema_name,
        COALESCE(rl.table_name, tm.table_name) AS table_name,
        tm.row_count AS current_rows,
        ROUND(tm.bytes / (1024*1024*1024.0), 2) AS size_gb,
        rl.last_load_time,
        rl.load_count AS loads_in_window,
        rl.total_rows_loaded,
        tm.last_altered,
        DATEDIFF('hour', COALESCE(rl.last_load_time, tm.last_altered), CURRENT_TIMESTAMP()) AS hours_since_load,
        CASE
            WHEN rl.last_load_time IS NULL AND tm.row_count > 1000 THEN 'No Recent Load'
            WHEN DATEDIFF('hour', rl.last_load_time, CURRENT_TIMESTAMP()) > {stale_hours * 3} THEN 'Critical'
            WHEN DATEDIFF('hour', rl.last_load_time, CURRENT_TIMESTAMP()) > {stale_hours} THEN 'Stale'
            ELSE 'Fresh'
        END AS freshness_status
    FROM table_metadata tm
    LEFT JOIN recent_loads rl
      ON tm.database_name = rl.database_name
     AND tm.schema_name = rl.schema_name
     AND tm.table_name = rl.table_name
    WHERE tm.row_count > 100
      AND (
          rl.last_load_time IS NULL
          OR DATEDIFF('hour', rl.last_load_time, CURRENT_TIMESTAMP()) > {stale_hours}
      )
    ORDER BY
        CASE freshness_status
            WHEN 'Critical' THEN 1
            WHEN 'No Recent Load' THEN 2
            WHEN 'Stale' THEN 3
            ELSE 4
        END,
        tm.row_count DESC
    LIMIT 50
    """


def build_row_count_drift_sql(days_back: int = 7) -> str:
    """SQL to detect tables with abnormal row count changes."""
    days_back = max(2, int(days_back or 7))
    return f"""
    WITH daily_sizes AS (
        SELECT
            table_catalog AS database_name,
            table_schema AS schema_name,
            table_name,
            DATE(table_created_or_last_altered) AS snapshot_date,
            active_bytes,
            ROW_NUMBER() OVER (
                PARTITION BY table_catalog, table_schema, table_name
                ORDER BY table_created_or_last_altered DESC
            ) AS recency_rank
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
        WHERE table_created_or_last_altered >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND table_catalog IS NOT NULL
          AND active_bytes > 0
    ),
    comparisons AS (
        SELECT
            d1.database_name,
            d1.schema_name,
            d1.table_name,
            d1.active_bytes AS current_bytes,
            d2.active_bytes AS previous_bytes,
            d1.snapshot_date AS current_date,
            d2.snapshot_date AS previous_date,
            ROUND((d1.active_bytes - d2.active_bytes) * 100.0 / NULLIF(d2.active_bytes, 0), 1) AS pct_change
        FROM daily_sizes d1
        JOIN daily_sizes d2
          ON d1.database_name = d2.database_name
         AND d1.schema_name = d2.schema_name
         AND d1.table_name = d2.table_name
         AND d1.recency_rank = 1
         AND d2.recency_rank = 2
        WHERE d2.active_bytes > 1048576  -- Only tables > 1MB
    )
    SELECT
        database_name,
        schema_name,
        table_name,
        ROUND(current_bytes / (1024*1024*1024.0), 2) AS current_gb,
        ROUND(previous_bytes / (1024*1024*1024.0), 2) AS previous_gb,
        pct_change,
        current_date,
        previous_date,
        CASE
            WHEN pct_change < -50 THEN 'Critical Shrink'
            WHEN pct_change < -20 THEN 'Significant Shrink'
            WHEN pct_change > 200 THEN 'Explosive Growth'
            WHEN pct_change > 50 THEN 'Rapid Growth'
            ELSE 'Normal'
        END AS drift_status
    FROM comparisons
    WHERE ABS(pct_change) > 20
    ORDER BY ABS(pct_change) DESC
    LIMIT 30
    """


def build_schema_change_sql(days_back: int = 7) -> str:
    """SQL to detect recent schema changes (columns added/dropped/altered)."""
    days_back = max(1, int(days_back or 7))
    return f"""
    SELECT
        query_type,
        user_name,
        role_name,
        database_name,
        schema_name,
        start_time,
        SUBSTR(query_text, 1, 300) AS query_preview,
        execution_status
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND query_type IN (
          'ALTER_TABLE', 'ALTER_VIEW',
          'CREATE_TABLE', 'CREATE_VIEW',
          'DROP_TABLE', 'DROP_VIEW',
          'RENAME_TABLE', 'RENAME_COLUMN'
      )
      AND execution_status = 'SUCCESS'
    ORDER BY start_time DESC
    LIMIT 50
    """


def summarize_data_quality(
    freshness_df=None,
    drift_df=None,
    schema_changes_df=None,
) -> dict[str, Any]:
    """Summarize data quality findings into an actionable report."""
    import pandas as pd

    result = {
        "overall_status": "unknown",
        "stale_tables": 0,
        "critical_tables": 0,
        "drift_alerts": 0,
        "schema_changes": 0,
        "top_issues": [],
    }

    if isinstance(freshness_df, pd.DataFrame) and not freshness_df.empty:
        if "FRESHNESS_STATUS" in freshness_df.columns:
            result["stale_tables"] = len(freshness_df[freshness_df["FRESHNESS_STATUS"] == "Stale"])
            result["critical_tables"] = len(freshness_df[
                freshness_df["FRESHNESS_STATUS"].isin(["Critical", "No Recent Load"])
            ])
            for _, row in freshness_df.head(5).iterrows():
                result["top_issues"].append(
                    f"{row.get('DATABASE_NAME', '?')}.{row.get('TABLE_NAME', '?')}: "
                    f"{row.get('FRESHNESS_STATUS', '?')} ({row.get('HOURS_SINCE_LOAD', '?')}h since load)"
                )

    if isinstance(drift_df, pd.DataFrame) and not drift_df.empty:
        result["drift_alerts"] = len(drift_df)
        for _, row in drift_df.head(3).iterrows():
            result["top_issues"].append(
                f"{row.get('TABLE_NAME', '?')}: {row.get('DRIFT_STATUS', '?')} ({row.get('PCT_CHANGE', 0):+.0f}%)"
            )

    if isinstance(schema_changes_df, pd.DataFrame) and not schema_changes_df.empty:
        result["schema_changes"] = len(schema_changes_df)

    # Overall status
    if result["critical_tables"] > 0:
        result["overall_status"] = "critical"
    elif result["stale_tables"] > 3 or result["drift_alerts"] > 5:
        result["overall_status"] = "warning"
    elif result["stale_tables"] > 0 or result["drift_alerts"] > 0:
        result["overall_status"] = "watch"
    else:
        result["overall_status"] = "healthy"

    return result
