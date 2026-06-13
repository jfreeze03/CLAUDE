# utils/anomaly_detection.py - Statistical anomaly detection for cost/query patterns
"""
Rule-based + statistical anomaly detection that surfaces:
  - Cost spikes (Z-score based, not static thresholds)
  - Query runtime regressions (p95 drift)
  - Warehouse utilization anomalies
  - Task failure bursts

This replaces static threshold alerting with adaptive detection
that adjusts to each customer's normal patterns.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st


def build_cost_anomaly_sql(days_back: int = 30, sensitivity: float = 2.0) -> str:
    """SQL to detect daily cost anomalies using Z-score from rolling baseline.

    A day is flagged anomalous when its credit consumption exceeds
    the rolling 14-day mean by more than `sensitivity` standard deviations.
    """
    days_back = max(14, int(days_back or 30))
    sensitivity = max(0.5, float(sensitivity or 2.0))
    return f"""
    WITH daily_credits AS (
        SELECT
            DATE(start_time) AS usage_date,
            warehouse_name,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_DATE()
        GROUP BY usage_date, warehouse_name
    ),
    rolling_stats AS (
        SELECT
            usage_date,
            warehouse_name,
            daily_credits,
            AVG(daily_credits) OVER (
                PARTITION BY warehouse_name
                ORDER BY usage_date
                ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
            ) AS rolling_mean,
            STDDEV(daily_credits) OVER (
                PARTITION BY warehouse_name
                ORDER BY usage_date
                ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
            ) AS rolling_stddev
        FROM daily_credits
    )
    SELECT
        usage_date,
        warehouse_name,
        ROUND(daily_credits, 2) AS daily_credits,
        ROUND(rolling_mean, 2) AS baseline_mean,
        ROUND(rolling_stddev, 2) AS baseline_stddev,
        ROUND(
            (daily_credits - rolling_mean) / NULLIF(rolling_stddev, 0),
            2
        ) AS z_score,
        ROUND(daily_credits - rolling_mean, 2) AS delta_from_baseline,
        ROUND(
            (daily_credits - rolling_mean) / NULLIF(rolling_mean, 0) * 100,
            1
        ) AS pct_above_baseline,
        CASE
            WHEN (daily_credits - rolling_mean) / NULLIF(rolling_stddev, 0) >= {sensitivity * 1.5}
                THEN 'Critical'
            WHEN (daily_credits - rolling_mean) / NULLIF(rolling_stddev, 0) >= {sensitivity}
                THEN 'High'
            WHEN (daily_credits - rolling_mean) / NULLIF(rolling_stddev, 0) >= {sensitivity * 0.7}
                THEN 'Medium'
            ELSE 'Normal'
        END AS anomaly_severity
    FROM rolling_stats
    WHERE rolling_mean IS NOT NULL
      AND rolling_stddev > 0
      AND (daily_credits - rolling_mean) / NULLIF(rolling_stddev, 0) >= {sensitivity * 0.7}
    ORDER BY usage_date DESC, z_score DESC
    """


def build_query_regression_sql(days_back: int = 14, regression_threshold: float = 2.0) -> str:
    """SQL to detect query runtime regressions by comparing recent vs baseline p95.

    Flags queries where recent p95 runtime exceeds the baseline by the threshold
    multiplier. Groups by query hash for stable comparison.
    """
    days_back = max(7, int(days_back or 14))
    threshold = max(1.2, float(regression_threshold or 2.0))
    midpoint = days_back // 2
    return f"""
    WITH recent_queries AS (
        SELECT
            query_parameterized_hash AS query_hash,
            warehouse_name,
            database_name,
            user_name,
            DATEDIFF('millisecond', '1970-01-01', start_time) AS start_epoch,
            total_elapsed_time / 1000.0 AS elapsed_sec,
            CASE
                WHEN start_time >= DATEADD('day', -{midpoint}, CURRENT_TIMESTAMP())
                    THEN 'RECENT'
                ELSE 'BASELINE'
            END AS period
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND execution_status = 'SUCCESS'
          AND total_elapsed_time > 1000
          AND warehouse_name IS NOT NULL
          AND query_parameterized_hash IS NOT NULL
    ),
    period_stats AS (
        SELECT
            query_hash,
            period,
            ANY_VALUE(warehouse_name) AS warehouse_name,
            ANY_VALUE(database_name) AS database_name,
            ANY_VALUE(user_name) AS user_name,
            COUNT(*) AS run_count,
            ROUND(AVG(elapsed_sec), 2) AS avg_sec,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_sec), 2) AS p95_sec,
            ROUND(MAX(elapsed_sec), 2) AS max_sec
        FROM recent_queries
        GROUP BY query_hash, period
        HAVING COUNT(*) >= 3
    ),
    comparison AS (
        SELECT
            r.query_hash,
            r.warehouse_name,
            r.database_name,
            r.user_name,
            b.run_count AS baseline_runs,
            r.run_count AS recent_runs,
            b.p95_sec AS baseline_p95_sec,
            r.p95_sec AS recent_p95_sec,
            b.avg_sec AS baseline_avg_sec,
            r.avg_sec AS recent_avg_sec,
            r.max_sec AS recent_max_sec,
            ROUND(r.p95_sec / NULLIF(b.p95_sec, 0), 2) AS regression_factor,
            ROUND(r.p95_sec - b.p95_sec, 2) AS regression_delta_sec
        FROM period_stats r
        JOIN period_stats b
          ON r.query_hash = b.query_hash
         AND r.period = 'RECENT'
         AND b.period = 'BASELINE'
        WHERE r.p95_sec > b.p95_sec * {threshold}
          AND r.p95_sec > 5
    )
    SELECT
        query_hash,
        warehouse_name,
        database_name,
        user_name,
        baseline_runs,
        recent_runs,
        baseline_p95_sec,
        recent_p95_sec,
        baseline_avg_sec,
        recent_avg_sec,
        recent_max_sec,
        regression_factor,
        regression_delta_sec,
        CASE
            WHEN regression_factor >= {threshold * 2} THEN 'Critical'
            WHEN regression_factor >= {threshold * 1.5} THEN 'High'
            WHEN regression_factor >= {threshold} THEN 'Medium'
            ELSE 'Watch'
        END AS severity
    FROM comparison
    ORDER BY regression_delta_sec DESC, regression_factor DESC
    LIMIT 50
    """


def build_task_failure_burst_sql(days_back: int = 7, burst_threshold: int = 3) -> str:
    """SQL to detect task failure bursts — tasks failing more than threshold times in a day."""
    days_back = max(1, int(days_back or 7))
    burst_threshold = max(1, int(burst_threshold or 3))
    return f"""
    SELECT
        DATE(scheduled_time) AS failure_date,
        database_name,
        schema_name,
        name AS task_name,
        COUNT(*) AS failure_count,
        MIN(scheduled_time) AS first_failure,
        MAX(scheduled_time) AS last_failure,
        LISTAGG(DISTINCT COALESCE(error_code, 'UNKNOWN'), ', ')
            WITHIN GROUP (ORDER BY scheduled_time) AS error_codes,
        CASE
            WHEN COUNT(*) >= {burst_threshold * 3} THEN 'Critical'
            WHEN COUNT(*) >= {burst_threshold * 2} THEN 'High'
            WHEN COUNT(*) >= {burst_threshold} THEN 'Medium'
            ELSE 'Watch'
        END AS severity
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE scheduled_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND state = 'FAILED'
    GROUP BY failure_date, database_name, schema_name, name
    HAVING COUNT(*) >= {burst_threshold}
    ORDER BY failure_date DESC, failure_count DESC
    """


def classify_anomalies(
    cost_anomalies_df=None,
    query_regressions_df=None,
    task_bursts_df=None,
) -> dict[str, Any]:
    """
    Classify and prioritize detected anomalies into an actionable summary.

    Returns:
        {
            "total_anomalies": int,
            "critical": int,
            "high": int,
            "medium": int,
            "top_findings": list[dict],
            "affected_warehouses": list[str],
            "affected_tasks": list[str],
            "recommendations": list[str],
        }
    """
    import pandas as pd

    findings = []

    if isinstance(cost_anomalies_df, pd.DataFrame) and not cost_anomalies_df.empty:
        for _, row in cost_anomalies_df.head(10).iterrows():
            findings.append({
                "type": "cost_spike",
                "severity": str(row.get("ANOMALY_SEVERITY", "Medium")),
                "entity": str(row.get("WAREHOUSE_NAME", "Unknown")),
                "signal": f"Cost spike: {row.get('PCT_ABOVE_BASELINE', 0):.0f}% above baseline",
                "date": str(row.get("USAGE_DATE", "")),
                "z_score": float(row.get("Z_SCORE", 0) or 0),
            })

    if isinstance(query_regressions_df, pd.DataFrame) and not query_regressions_df.empty:
        for _, row in query_regressions_df.head(10).iterrows():
            findings.append({
                "type": "query_regression",
                "severity": str(row.get("SEVERITY", "Medium")),
                "entity": str(row.get("WAREHOUSE_NAME", "Unknown")),
                "signal": f"Runtime regression: {row.get('REGRESSION_FACTOR', 0):.1f}x slower (p95: {row.get('RECENT_P95_SEC', 0):.1f}s vs {row.get('BASELINE_P95_SEC', 0):.1f}s baseline)",
                "database": str(row.get("DATABASE_NAME", "")),
                "user": str(row.get("USER_NAME", "")),
            })

    if isinstance(task_bursts_df, pd.DataFrame) and not task_bursts_df.empty:
        for _, row in task_bursts_df.head(10).iterrows():
            findings.append({
                "type": "task_burst",
                "severity": str(row.get("SEVERITY", "Medium")),
                "entity": f"{row.get('DATABASE_NAME', '')}.{row.get('SCHEMA_NAME', '')}.{row.get('TASK_NAME', '')}",
                "signal": f"Failed {row.get('FAILURE_COUNT', 0)} times on {row.get('FAILURE_DATE', '')}",
                "error_codes": str(row.get("ERROR_CODES", "")),
            })

    # Sort by severity
    severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Watch": 3}
    findings.sort(key=lambda f: severity_order.get(f.get("severity", "Watch"), 4))

    critical = sum(1 for f in findings if f["severity"] == "Critical")
    high = sum(1 for f in findings if f["severity"] == "High")
    medium = sum(1 for f in findings if f["severity"] == "Medium")

    affected_wh = list({f["entity"] for f in findings if f["type"] == "cost_spike"})
    affected_tasks = list({f["entity"] for f in findings if f["type"] == "task_burst"})

    # Auto-generate recommendations
    recommendations = []
    if critical > 0:
        recommendations.append("Investigate critical anomalies immediately — potential runaway workload or misconfigured warehouse.")
    if any(f["type"] == "cost_spike" and f.get("z_score", 0) > 3 for f in findings):
        recommendations.append("Review warehouse auto-scaling and query concurrency for spiking warehouses.")
    if any(f["type"] == "query_regression" for f in findings):
        recommendations.append("Check for schema changes, data volume growth, or stale statistics affecting regressed queries.")
    if any(f["type"] == "task_burst" for f in findings):
        recommendations.append("Review task dependencies and upstream data availability for burst-failing tasks.")

    return {
        "total_anomalies": len(findings),
        "critical": critical,
        "high": high,
        "medium": medium,
        "top_findings": findings[:15],
        "affected_warehouses": affected_wh[:10],
        "affected_tasks": affected_tasks[:10],
        "recommendations": recommendations,
    }


def render_anomaly_summary(summary: dict[str, Any], *, container=None) -> None:
    """Render a compact anomaly detection summary widget."""
    target = container or st

    total = summary.get("total_anomalies", 0)
    critical = summary.get("critical", 0)
    high = summary.get("high", 0)

    if total == 0:
        target.markdown(
            '<div style="padding:6px 12px;border:1px solid var(--border-subtle,#334155);'
            'border-radius:6px;background:var(--bg-card,#1e293b);font-size:0.75rem;'
            'color:var(--text-muted,#94a3b8);">'
            '✓ No anomalies detected in the current window</div>',
            unsafe_allow_html=True,
        )
        return

    if critical > 0:
        color = "#ef4444"
        status = "CRITICAL"
    elif high > 0:
        color = "#f97316"
        status = "ACTION NEEDED"
    else:
        color = "#f59e0b"
        status = "WATCH"

    findings_html = ""
    for finding in summary.get("top_findings", [])[:5]:
        sev = finding.get("severity", "Medium")
        sev_colors = {"Critical": "#ef4444", "High": "#f97316", "Medium": "#f59e0b", "Watch": "#64748b"}
        sev_color = sev_colors.get(sev, "#64748b")
        findings_html += (
            f'<div style="padding:3px 0;border-bottom:1px solid var(--border-subtle,#1e293b33);font-size:0.72rem;">'
            f'<span style="color:{sev_color};font-weight:700;">{sev}</span> · '
            f'{finding.get("entity", "")} · {finding.get("signal", "")}'
            f'</div>'
        )

    target.markdown(
        f"""
        <div style="padding:10px 14px;border:1px solid var(--border-subtle,#334155);
             border-radius:8px;background:var(--bg-card,#1e293b);">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                <span style="font-size:1.1rem;font-weight:800;color:{color};">{total}</span>
                <span style="font-size:0.72rem;color:{color};font-weight:700;">{status}</span>
                <span style="font-size:0.68rem;color:var(--text-muted,#94a3b8);">
                    {critical} critical · {high} high · {summary.get('medium', 0)} watch
                </span>
            </div>
            {findings_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Recommendations
    recs = summary.get("recommendations", [])
    if recs:
        for rec in recs[:3]:
            target.caption(f"→ {rec}")
