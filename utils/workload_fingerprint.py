# utils/workload_fingerprint.py - Statistical workload DNA fingerprinting
"""
Builds a "normal" fingerprint per warehouse per hour-of-day/day-of-week,
then detects drift from normal without explicit thresholds.

This answers: "Is today's workload pattern unusual compared to what we
normally see at this time on this day?"

Approach:
  - Build a baseline profile (mean, stddev) per warehouse per time slot
  - Score current period against baseline using Mahalanobis-like distance
  - Surface warehouses where current behavior diverges from historical norm
"""
from __future__ import annotations

from typing import Any


def build_fingerprint_baseline_sql(weeks_back: int = 4) -> str:
    """SQL to build per-warehouse per-time-slot statistical baselines."""
    weeks_back = max(2, int(weeks_back or 4))
    return f"""
    WITH hourly_profile AS (
        SELECT
            warehouse_name,
            EXTRACT(DOW FROM DATE(start_time)) AS day_of_week,
            EXTRACT(HOUR FROM start_time) AS hour_of_day,
            DATE(start_time) AS usage_date,
            COUNT(*) AS query_count,
            ROUND(SUM(total_elapsed_time) / 1000.0, 1) AS total_elapsed_sec,
            ROUND(SUM(bytes_scanned) / (1024*1024*1024.0), 2) AS gb_scanned,
            ROUND(AVG(total_elapsed_time) / 1000.0, 2) AS avg_elapsed_sec,
            COUNT(DISTINCT user_name) AS unique_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('week', -{weeks_back}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('day', -1, CURRENT_DATE())
          AND warehouse_name IS NOT NULL
          AND execution_status = 'SUCCESS'
        GROUP BY warehouse_name, day_of_week, hour_of_day, usage_date
    )
    SELECT
        warehouse_name,
        day_of_week,
        hour_of_day,
        COUNT(*) AS sample_days,
        ROUND(AVG(query_count), 1) AS baseline_query_count,
        ROUND(STDDEV(query_count), 1) AS stddev_query_count,
        ROUND(AVG(total_elapsed_sec), 1) AS baseline_elapsed_sec,
        ROUND(STDDEV(total_elapsed_sec), 1) AS stddev_elapsed_sec,
        ROUND(AVG(gb_scanned), 2) AS baseline_gb_scanned,
        ROUND(STDDEV(gb_scanned), 2) AS stddev_gb_scanned,
        ROUND(AVG(unique_users), 1) AS baseline_users,
        ROUND(AVG(avg_elapsed_sec), 2) AS baseline_avg_query_sec
    FROM hourly_profile
    GROUP BY warehouse_name, day_of_week, hour_of_day
    HAVING COUNT(*) >= 2
    ORDER BY warehouse_name, day_of_week, hour_of_day
    """


def build_current_period_sql(hours_back: int = 4) -> str:
    """SQL to get the current period's workload profile for comparison."""
    hours_back = max(1, int(hours_back or 4))
    return f"""
    SELECT
        warehouse_name,
        EXTRACT(DOW FROM CURRENT_DATE()) AS day_of_week,
        EXTRACT(HOUR FROM start_time) AS hour_of_day,
        COUNT(*) AS query_count,
        ROUND(SUM(total_elapsed_time) / 1000.0, 1) AS total_elapsed_sec,
        ROUND(SUM(bytes_scanned) / (1024*1024*1024.0), 2) AS gb_scanned,
        ROUND(AVG(total_elapsed_time) / 1000.0, 2) AS avg_elapsed_sec,
        COUNT(DISTINCT user_name) AS unique_users
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('hour', -{hours_back}, CURRENT_TIMESTAMP())
      AND warehouse_name IS NOT NULL
      AND execution_status = 'SUCCESS'
    GROUP BY warehouse_name, hour_of_day
    ORDER BY warehouse_name, hour_of_day
    """


def score_workload_drift(
    current_df,
    baseline_df,
    *,
    sensitivity: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Score current workload against baseline fingerprint.

    Returns list of warehouses with drift, sorted by severity.
    Each entry: {warehouse, drift_score, dimensions, severity, detail}
    """
    import pandas as pd

    if not isinstance(current_df, pd.DataFrame) or current_df.empty:
        return []
    if not isinstance(baseline_df, pd.DataFrame) or baseline_df.empty:
        return []

    results = []

    for _, current_row in current_df.iterrows():
        wh = str(current_row.get("WAREHOUSE_NAME", ""))
        dow = int(current_row.get("DAY_OF_WEEK", 0))
        hour = int(current_row.get("HOUR_OF_DAY", 0))

        # Find matching baseline
        mask = (
            (baseline_df["WAREHOUSE_NAME"] == wh)
            & (baseline_df["DAY_OF_WEEK"] == dow)
            & (baseline_df["HOUR_OF_DAY"] == hour)
        )
        baseline_match = baseline_df[mask]
        if baseline_match.empty:
            continue

        baseline = baseline_match.iloc[0]
        drift_dimensions = []
        total_z = 0.0
        dimension_count = 0

        # Compare each dimension
        for current_col, baseline_col, stddev_col, label in [
            ("QUERY_COUNT", "BASELINE_QUERY_COUNT", "STDDEV_QUERY_COUNT", "Query Volume"),
            ("TOTAL_ELAPSED_SEC", "BASELINE_ELAPSED_SEC", "STDDEV_ELAPSED_SEC", "Total Runtime"),
            ("GB_SCANNED", "BASELINE_GB_SCANNED", "STDDEV_GB_SCANNED", "Data Scanned"),
        ]:
            current_val = float(current_row.get(current_col, 0) or 0)
            baseline_val = float(baseline.get(baseline_col, 0) or 0)
            stddev = float(baseline.get(stddev_col, 0) or 0)

            if stddev > 0:
                z = (current_val - baseline_val) / stddev
                total_z += abs(z)
                dimension_count += 1
                if abs(z) >= sensitivity:
                    direction = "above" if z > 0 else "below"
                    drift_dimensions.append(
                        f"{label}: {current_val:.0f} vs baseline {baseline_val:.0f} ({z:+.1f}σ {direction})"
                    )

        if dimension_count == 0:
            continue

        avg_z = total_z / dimension_count

        if avg_z >= sensitivity * 1.5:
            severity = "Critical"
        elif avg_z >= sensitivity:
            severity = "High"
        elif avg_z >= sensitivity * 0.7:
            severity = "Medium"
        else:
            continue  # Below threshold

        results.append({
            "warehouse": wh,
            "drift_score": round(avg_z, 2),
            "dimensions": drift_dimensions,
            "severity": severity,
            "hour": hour,
            "day_of_week": dow,
            "detail": f"Composite drift: {avg_z:.1f}σ from baseline at {hour}:00 on day {dow}",
        })

    results.sort(key=lambda x: x["drift_score"], reverse=True)
    return results


def render_drift_summary(drift_results: list[dict[str, Any]], *, container=None) -> None:
    """Render workload drift findings."""
    import streamlit as st

    target = container or st

    if not drift_results:
        target.caption("✓ All warehouse workloads are within normal patterns.")
        return

    critical = sum(1 for d in drift_results if d["severity"] == "Critical")
    high = sum(1 for d in drift_results if d["severity"] == "High")

    if critical > 0:
        target.warning(f"**Workload Drift Detected:** {critical} critical, {high} high severity")
    elif high > 0:
        target.info(f"**Workload Drift:** {high} warehouses diverging from normal patterns")

    for finding in drift_results[:5]:
        sev_colors = {"Critical": "🔴", "High": "🟠", "Medium": "🟡"}
        icon = sev_colors.get(finding["severity"], "⚪")
        target.markdown(f"{icon} **{finding['warehouse']}** — {finding['detail']}")
        for dim in finding["dimensions"]:
            target.caption(f"  · {dim}")
