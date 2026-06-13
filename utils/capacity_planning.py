# utils/capacity_planning.py - Capacity forecasting and warehouse sizing
"""
Provides:
  - Warehouse capacity forecasting based on growth trends
  - Right-sizing recommendations from utilization data
  - Peak hour prediction for scaling policies
  - Capacity runway estimation

Answers: "When will we need a bigger warehouse?" and "Is this warehouse too large?"
"""
from __future__ import annotations

from typing import Any


def build_warehouse_utilization_sql(days_back: int = 30) -> str:
    """SQL to compute warehouse utilization metrics for right-sizing."""
    days_back = max(7, int(days_back or 30))
    return f"""
    WITH hourly_usage AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time) AS hour_bucket,
            SUM(credits_used_compute) AS hourly_credits,
            COUNT(*) AS metering_rows
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_TIMESTAMP()
        GROUP BY warehouse_name, hour_bucket
    ),
    query_pressure AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time) AS hour_bucket,
            COUNT(*) AS query_count,
            AVG(queued_overload_time) / 1000.0 AS avg_queue_sec,
            MAX(queued_overload_time) / 1000.0 AS max_queue_sec,
            SUM(bytes_spilled_to_remote_storage) / (1024*1024*1024.0) AS remote_spill_gb,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_elapsed_time / 1000.0) AS p95_elapsed_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          AND execution_status = 'SUCCESS'
        GROUP BY warehouse_name, hour_bucket
    )
    SELECT
        u.warehouse_name,
        COUNT(DISTINCT u.hour_bucket) AS active_hours,
        ROUND(AVG(u.hourly_credits), 4) AS avg_hourly_credits,
        ROUND(MAX(u.hourly_credits), 4) AS peak_hourly_credits,
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY u.hourly_credits), 4) AS p95_hourly_credits,
        ROUND(AVG(qp.query_count), 0) AS avg_hourly_queries,
        ROUND(MAX(qp.query_count), 0) AS peak_hourly_queries,
        ROUND(AVG(qp.avg_queue_sec), 2) AS avg_queue_sec,
        ROUND(MAX(qp.max_queue_sec), 2) AS peak_queue_sec,
        ROUND(SUM(qp.remote_spill_gb), 2) AS total_remote_spill_gb,
        ROUND(AVG(qp.p95_elapsed_sec), 2) AS avg_p95_elapsed_sec
    FROM hourly_usage u
    LEFT JOIN query_pressure qp
      ON u.warehouse_name = qp.warehouse_name
     AND u.hour_bucket = qp.hour_bucket
    GROUP BY u.warehouse_name
    ORDER BY avg_hourly_credits DESC
    """


def build_peak_hour_analysis_sql(warehouse_name: str = None, days_back: int = 14) -> str:
    """SQL to identify peak usage hours for scaling policy decisions."""
    days_back = max(7, int(days_back or 14))
    wh_filter = f"AND warehouse_name = '{warehouse_name}'" if warehouse_name else ""
    return f"""
    SELECT
        warehouse_name,
        EXTRACT(HOUR FROM DATE_TRUNC('hour', start_time)) AS hour_of_day,
        EXTRACT(DOW FROM DATE_TRUNC('hour', start_time)) AS day_of_week,
        COUNT(*) AS query_count,
        ROUND(AVG(total_elapsed_time / 1000.0), 2) AS avg_elapsed_sec,
        ROUND(AVG(queued_overload_time / 1000.0), 2) AS avg_queue_sec,
        ROUND(SUM(bytes_spilled_to_remote_storage) / (1024*1024*1024.0), 2) AS remote_spill_gb
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND warehouse_name IS NOT NULL
      AND execution_status = 'SUCCESS'
      {wh_filter}
    GROUP BY warehouse_name, hour_of_day, day_of_week
    ORDER BY warehouse_name, day_of_week, hour_of_day
    """


def build_growth_trend_sql(warehouse_name: str = None, days_back: int = 60) -> str:
    """SQL to compute week-over-week credit growth for capacity forecasting."""
    days_back = max(14, int(days_back or 60))
    wh_filter = f"AND warehouse_name = '{warehouse_name}'" if warehouse_name else ""
    return f"""
    WITH weekly_credits AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('week', DATE(start_time)) AS week_start,
            ROUND(SUM(credits_used), 4) AS weekly_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          {wh_filter}
        GROUP BY warehouse_name, week_start
    )
    SELECT
        warehouse_name,
        week_start,
        weekly_credits,
        LAG(weekly_credits) OVER (PARTITION BY warehouse_name ORDER BY week_start) AS prev_week_credits,
        ROUND(
            (weekly_credits - LAG(weekly_credits) OVER (PARTITION BY warehouse_name ORDER BY week_start))
            / NULLIF(LAG(weekly_credits) OVER (PARTITION BY warehouse_name ORDER BY week_start), 0) * 100,
            1
        ) AS wow_growth_pct
    FROM weekly_credits
    ORDER BY warehouse_name, week_start
    """


def recommend_warehouse_size(
    utilization: dict[str, Any],
    *,
    queue_threshold_sec: float = 5.0,
    spill_threshold_gb: float = 1.0,
) -> dict[str, Any]:
    """
    Recommend warehouse sizing based on utilization metrics.

    Args:
        utilization: Dict with keys from warehouse_utilization_sql results
        queue_threshold_sec: Queue time above this suggests upsize
        spill_threshold_gb: Remote spill above this suggests upsize

    Returns:
        {
            "recommendation": "upsize" | "downsize" | "maintain" | "consider_multi_cluster",
            "reason": str,
            "confidence": "high" | "medium" | "low",
            "evidence": [str],
        }
    """
    avg_queue = float(utilization.get("avg_queue_sec", 0) or 0)
    peak_queue = float(utilization.get("peak_queue_sec", 0) or 0)
    remote_spill = float(utilization.get("total_remote_spill_gb", 0) or 0)
    peak_credits = float(utilization.get("peak_hourly_credits", 0) or 0)
    avg_credits = float(utilization.get("avg_hourly_credits", 0) or 0)

    evidence = []
    recommendation = "maintain"
    reason = "Warehouse utilization is within normal parameters."
    confidence = "medium"

    # Check for upsize signals
    upsize_signals = 0
    if avg_queue > queue_threshold_sec:
        upsize_signals += 1
        evidence.append(f"Average queue time {avg_queue:.1f}s exceeds {queue_threshold_sec}s threshold")
    if peak_queue > queue_threshold_sec * 3:
        upsize_signals += 1
        evidence.append(f"Peak queue time {peak_queue:.1f}s indicates frequent bottlenecks")
    if remote_spill > spill_threshold_gb:
        upsize_signals += 1
        evidence.append(f"Remote spill {remote_spill:.1f}GB suggests insufficient memory")

    # Check for downsize signals
    downsize_signals = 0
    if avg_queue < 0.5 and remote_spill < 0.1 and avg_credits > 0:
        if peak_credits < avg_credits * 1.5:
            downsize_signals += 1
            evidence.append("Consistently low queue and zero spill with stable load")

    # Check for multi-cluster signals
    if peak_queue > queue_threshold_sec * 5 and remote_spill < spill_threshold_gb:
        recommendation = "consider_multi_cluster"
        reason = "High queue pressure without spill suggests concurrency bottleneck, not query size."
        confidence = "high"
    elif upsize_signals >= 2:
        recommendation = "upsize"
        reason = "Multiple signals indicate the warehouse is undersized for current workload."
        confidence = "high" if upsize_signals >= 3 else "medium"
    elif downsize_signals > 0 and upsize_signals == 0:
        recommendation = "downsize"
        reason = "Warehouse is consistently underutilized with no pressure signals."
        confidence = "medium"
    else:
        confidence = "high" if not evidence else "medium"

    return {
        "recommendation": recommendation,
        "reason": reason,
        "confidence": confidence,
        "evidence": evidence,
    }


def forecast_capacity_exhaustion(
    weekly_growth_pct: float,
    current_weekly_credits: float,
    warehouse_capacity_credits: float,
) -> dict[str, Any]:
    """
    Forecast when current warehouse capacity will be exhausted.

    Args:
        weekly_growth_pct: Week-over-week growth rate
        current_weekly_credits: Current weekly consumption
        warehouse_capacity_credits: Max weekly capacity of current size

    Returns:
        {"weeks_until_full": int | None, "action_needed": bool, "urgency": str}
    """
    if weekly_growth_pct <= 0 or current_weekly_credits <= 0:
        return {"weeks_until_full": None, "action_needed": False, "urgency": "none"}

    if current_weekly_credits >= warehouse_capacity_credits:
        return {"weeks_until_full": 0, "action_needed": True, "urgency": "immediate"}

    # Compound growth projection
    growth_rate = 1 + (weekly_growth_pct / 100)
    projected = current_weekly_credits
    weeks = 0
    max_weeks = 52

    while projected < warehouse_capacity_credits and weeks < max_weeks:
        projected *= growth_rate
        weeks += 1

    if weeks >= max_weeks:
        return {"weeks_until_full": None, "action_needed": False, "urgency": "none"}

    if weeks <= 4:
        urgency = "critical"
    elif weeks <= 12:
        urgency = "plan"
    else:
        urgency = "monitor"

    return {
        "weeks_until_full": weeks,
        "action_needed": weeks <= 12,
        "urgency": urgency,
    }
