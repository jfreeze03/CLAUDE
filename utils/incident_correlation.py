# utils/incident_correlation.py - Automated root cause correlation
"""
When an anomaly (cost spike, failure burst, regression) is detected,
correlate it with events from the same time window:
  - DDL changes (CREATE/ALTER/DROP)
  - New user workloads
  - Schema changes
  - Warehouse setting changes
  - Deploy/task changes

Transforms "something is wrong" into "here's probably why."
"""
from __future__ import annotations

import re
from typing import Any


def _safe_date_expr(target_date: str) -> str:
    """Validate and sanitize a date string into a safe SQL expression."""
    safe_date = str(target_date).strip()[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", safe_date):
        return f"TO_DATE('{safe_date}', 'YYYY-MM-DD')"
    return "CURRENT_DATE()"


def build_ddl_changes_sql(target_date: str, days_window: int = 1) -> str:
    """SQL to find DDL changes around a target date."""
    date_expr = _safe_date_expr(target_date)
    days = max(1, min(30, int(days_window)))
    return f"""
    SELECT
        query_type,
        user_name,
        role_name,
        database_name,
        schema_name,
        warehouse_name,
        start_time,
        SUBSTR(query_text, 1, 200) AS query_preview,
        total_elapsed_time / 1000.0 AS elapsed_sec
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, {date_expr})
      AND start_time < DATEADD('day', {days}, {date_expr})
      AND query_type IN (
          'CREATE_TABLE', 'ALTER_TABLE', 'DROP_TABLE',
          'CREATE_VIEW', 'ALTER_VIEW', 'DROP_VIEW',
          'CREATE_SCHEMA', 'ALTER_SCHEMA', 'DROP_SCHEMA',
          'CREATE_DATABASE', 'ALTER_DATABASE', 'DROP_DATABASE',
          'CREATE_WAREHOUSE', 'ALTER_WAREHOUSE', 'DROP_WAREHOUSE',
          'CREATE_TASK', 'ALTER_TASK', 'DROP_TASK',
          'CREATE_PROCEDURE', 'ALTER_PROCEDURE', 'DROP_PROCEDURE',
          'GRANT', 'REVOKE'
      )
    ORDER BY start_time DESC
    LIMIT 50
    """


def build_new_workload_sql(target_date: str, days_window: int = 1) -> str:
    """SQL to find new users or roles that appeared around a target date."""
    date_expr = _safe_date_expr(target_date)
    days = max(1, min(30, int(days_window)))
    return f"""
    WITH baseline_users AS (
        SELECT DISTINCT user_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days + 7}, {date_expr})
          AND start_time < DATEADD('day', -{days}, {date_expr})
    ),
    incident_users AS (
        SELECT
            user_name,
            warehouse_name,
            COUNT(*) AS query_count,
            ROUND(SUM(total_elapsed_time) / 1000.0, 1) AS total_sec,
            MIN(start_time) AS first_seen
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days}, {date_expr})
          AND start_time < DATEADD('day', {days}, {date_expr})
          AND warehouse_name IS NOT NULL
        GROUP BY user_name, warehouse_name
    )
    SELECT
        i.user_name,
        i.warehouse_name,
        i.query_count,
        i.total_sec,
        i.first_seen,
        CASE WHEN b.user_name IS NULL THEN 'New' ELSE 'Existing' END AS user_status
    FROM incident_users i
    LEFT JOIN baseline_users b ON i.user_name = b.user_name
    WHERE b.user_name IS NULL
       OR i.query_count > 100
    ORDER BY i.total_sec DESC
    LIMIT 25
    """


def build_warehouse_change_sql(target_date: str, warehouse_name: str = None) -> str:
    """SQL to find warehouse setting changes around a target date."""
    date_expr = _safe_date_expr(target_date)
    wh_filter = f"AND warehouse_name = '{str(warehouse_name).replace(chr(39), '')}'" if warehouse_name else ""
    return f"""
    SELECT
        user_name,
        role_name,
        warehouse_name,
        start_time,
        query_type,
        SUBSTR(query_text, 1, 300) AS query_preview
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -3, {date_expr})
      AND start_time < DATEADD('day', 1, {date_expr})
      AND query_type IN ('ALTER_WAREHOUSE', 'CREATE_WAREHOUSE')
      {wh_filter}
    ORDER BY start_time DESC
    LIMIT 20
    """


def build_volume_change_sql(target_date: str, warehouse_name: str = None) -> str:
    """SQL to detect query volume changes around a target date."""
    date_expr = _safe_date_expr(target_date)
    wh_filter = f"AND warehouse_name = '{str(warehouse_name).replace(chr(39), '')}'" if warehouse_name else ""
    return f"""
    WITH hourly AS (
        SELECT
            DATE_TRUNC('hour', start_time) AS hour_bucket,
            warehouse_name,
            COUNT(*) AS query_count,
            SUM(total_elapsed_time) / 1000.0 AS total_exec_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -3, {date_expr})
          AND start_time < DATEADD('day', 1, {date_expr})
          AND warehouse_name IS NOT NULL
          {wh_filter}
        GROUP BY hour_bucket, warehouse_name
    )
    SELECT
        hour_bucket,
        warehouse_name,
        query_count,
        ROUND(total_exec_sec, 1) AS total_exec_sec,
        LAG(query_count) OVER (PARTITION BY warehouse_name ORDER BY hour_bucket) AS prev_hour_count,
        ROUND(
            (query_count - LAG(query_count) OVER (PARTITION BY warehouse_name ORDER BY hour_bucket))
            * 100.0 / NULLIF(LAG(query_count) OVER (PARTITION BY warehouse_name ORDER BY hour_bucket), 0),
            1
        ) AS pct_change
    FROM hourly
    ORDER BY ABS(pct_change) DESC NULLS LAST
    LIMIT 30
    """


def correlate_incident(
    anomaly_type: str,
    anomaly_date: str,
    entity: str = "",
    *,
    ddl_changes_df=None,
    new_workloads_df=None,
    warehouse_changes_df=None,
    volume_changes_df=None,
) -> dict[str, Any]:
    """
    Build a correlation report for an anomaly.

    Returns:
        {
            "anomaly": {"type": str, "date": str, "entity": str},
            "probable_causes": [{"cause": str, "confidence": str, "evidence": str}],
            "contributing_factors": [str],
            "timeline": [{"time": str, "event": str}],
            "recommendation": str,
        }
    """
    import pandas as pd

    result = {
        "anomaly": {"type": anomaly_type, "date": anomaly_date, "entity": entity},
        "probable_causes": [],
        "contributing_factors": [],
        "timeline": [],
        "recommendation": "Investigate the correlated events below.",
    }

    # DDL changes correlation
    if isinstance(ddl_changes_df, pd.DataFrame) and not ddl_changes_df.empty:
        for _, row in ddl_changes_df.head(5).iterrows():
            event = f"{row.get('QUERY_TYPE', '?')} by {row.get('USER_NAME', '?')} on {row.get('DATABASE_NAME', '?')}.{row.get('SCHEMA_NAME', '?')}"
            result["timeline"].append({
                "time": str(row.get("START_TIME", "")),
                "event": event,
            })

        # High-impact DDL
        high_impact = ddl_changes_df[
            ddl_changes_df["QUERY_TYPE"].str.upper().isin([
                "ALTER_WAREHOUSE", "DROP_TABLE", "ALTER_TABLE",
                "CREATE_WAREHOUSE", "DROP_SCHEMA"
            ])
        ] if "QUERY_TYPE" in ddl_changes_df.columns else pd.DataFrame()

        if not high_impact.empty:
            result["probable_causes"].append({
                "cause": f"Schema/warehouse change: {high_impact.iloc[0].get('QUERY_TYPE', '?')} by {high_impact.iloc[0].get('USER_NAME', '?')}",
                "confidence": "High",
                "evidence": str(high_impact.iloc[0].get("QUERY_PREVIEW", ""))[:150],
            })

    # New workload correlation
    if isinstance(new_workloads_df, pd.DataFrame) and not new_workloads_df.empty:
        new_users = new_workloads_df[new_workloads_df.get("USER_STATUS", pd.Series()) == "New"]
        if not new_users.empty:
            top_new = new_users.iloc[0]
            result["probable_causes"].append({
                "cause": f"New workload: {top_new.get('USER_NAME', '?')} ran {top_new.get('QUERY_COUNT', 0)} queries on {top_new.get('WAREHOUSE_NAME', '?')}",
                "confidence": "Medium",
                "evidence": f"First seen: {top_new.get('FIRST_SEEN', '?')}, total runtime: {top_new.get('TOTAL_SEC', 0):.0f}s",
            })

        # Heavy existing users
        heavy = new_workloads_df[
            (new_workloads_df.get("USER_STATUS", pd.Series()) == "Existing")
            & (new_workloads_df.get("QUERY_COUNT", pd.Series(dtype=int)) > 200)
        ]
        if not heavy.empty:
            result["contributing_factors"].append(
                f"Heavy user {heavy.iloc[0].get('USER_NAME', '?')}: {heavy.iloc[0].get('QUERY_COUNT', 0)} queries"
            )

    # Warehouse setting changes
    if isinstance(warehouse_changes_df, pd.DataFrame) and not warehouse_changes_df.empty:
        for _, row in warehouse_changes_df.head(3).iterrows():
            result["probable_causes"].append({
                "cause": f"Warehouse config change by {row.get('USER_NAME', '?')}",
                "confidence": "High",
                "evidence": str(row.get("QUERY_PREVIEW", ""))[:150],
            })

    # Volume spikes
    if isinstance(volume_changes_df, pd.DataFrame) and not volume_changes_df.empty:
        if "PCT_CHANGE" in volume_changes_df.columns:
            spikes = volume_changes_df[volume_changes_df["PCT_CHANGE"].abs() > 100]
            if not spikes.empty:
                top_spike = spikes.iloc[0]
                result["contributing_factors"].append(
                    f"Volume spike: {top_spike.get('PCT_CHANGE', 0):.0f}% change at {top_spike.get('HOUR_BUCKET', '?')} on {top_spike.get('WAREHOUSE_NAME', '?')}"
                )

    # Generate recommendation
    if result["probable_causes"]:
        top_cause = result["probable_causes"][0]
        if "warehouse" in top_cause["cause"].lower():
            result["recommendation"] = "Review the warehouse configuration change and verify it was intentional. Consider rollback if unauthorized."
        elif "new workload" in top_cause["cause"].lower():
            result["recommendation"] = "Review the new workload for proper warehouse sizing and scheduling. Consider isolating to a dedicated warehouse."
        elif "schema" in top_cause["cause"].lower() or "table" in top_cause["cause"].lower():
            result["recommendation"] = "Check if the DDL change affected query plans or clustering. Review execution plans for affected queries."
        else:
            result["recommendation"] = "Investigate the top correlated event and verify it was expected. Route to the entity owner for confirmation."
    elif result["contributing_factors"]:
        result["recommendation"] = "No single root cause identified. Volume/workload growth may be organic. Monitor for recurrence."
    else:
        result["recommendation"] = "No correlated events found. This may be a Snowflake-side issue (maintenance, throttling) or an infrequent batch job."

    return result
