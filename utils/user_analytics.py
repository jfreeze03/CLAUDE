# utils/user_analytics.py - User behavior and adoption analytics
"""
Tracks user-level patterns for governance and optimization:
  - Active vs dormant user ratio
  - Top consumers by credit attribution
  - Login patterns and session analysis
  - Role utilization (which roles are actually used)
  - New user onboarding velocity

Answers: "Who is using Snowflake and how?"
"""
from __future__ import annotations

from typing import Any


def build_user_activity_summary_sql(days_back: int = 30) -> str:
    """SQL to build a user activity summary."""
    days_back = max(7, int(days_back or 30))
    return f"""
    WITH query_activity AS (
        SELECT
            user_name,
            role_name,
            COUNT(*) AS query_count,
            COUNT(DISTINCT DATE(start_time)) AS active_days,
            ROUND(SUM(total_elapsed_time) / 1000.0 / 3600, 2) AS total_hours,
            COUNT(DISTINCT warehouse_name) AS warehouses_used,
            COUNT(DISTINCT database_name) AS databases_accessed,
            MIN(start_time) AS first_query,
            MAX(start_time) AS last_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND user_name IS NOT NULL
        GROUP BY user_name, role_name
    ),
    login_activity AS (
        SELECT
            user_name,
            COUNT(*) AS login_count,
            COUNT_IF(is_success = 'YES') AS successful_logins,
            COUNT_IF(is_success = 'NO') AS failed_logins,
            MAX(event_timestamp) AS last_login
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
        WHERE event_timestamp >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
        GROUP BY user_name
    )
    SELECT
        qa.user_name,
        qa.role_name,
        qa.query_count,
        qa.active_days,
        qa.total_hours,
        qa.warehouses_used,
        qa.databases_accessed,
        qa.first_query,
        qa.last_query,
        COALESCE(la.login_count, 0) AS login_count,
        COALESCE(la.failed_logins, 0) AS failed_logins,
        CASE
            WHEN qa.active_days >= {days_back * 0.7} THEN 'Power User'
            WHEN qa.active_days >= {days_back * 0.3} THEN 'Regular'
            WHEN qa.active_days >= 3 THEN 'Occasional'
            ELSE 'Rare'
        END AS user_segment
    FROM query_activity qa
    LEFT JOIN login_activity la ON qa.user_name = la.user_name
    ORDER BY qa.query_count DESC
    """


def build_role_utilization_sql(days_back: int = 30) -> str:
    """SQL to show which roles are actively used vs dormant."""
    days_back = max(7, int(days_back or 30))
    return f"""
    WITH active_roles AS (
        SELECT DISTINCT role_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND role_name IS NOT NULL
    ),
    all_roles AS (
        SELECT
            name AS role_name,
            created_on,
            granted_roles,
            granted_to_roles
        FROM SNOWFLAKE.ACCOUNT_USAGE.ROLES
        WHERE deleted_on IS NULL
    )
    SELECT
        ar.role_name,
        ar.created_on,
        CASE WHEN act.role_name IS NOT NULL THEN 'Active' ELSE 'Dormant' END AS utilization_status,
        DATEDIFF('day', ar.created_on, CURRENT_TIMESTAMP()) AS age_days
    FROM all_roles ar
    LEFT JOIN active_roles act ON ar.role_name = act.role_name
    ORDER BY utilization_status DESC, age_days DESC
    """


def build_top_consumers_sql(days_back: int = 7) -> str:
    """SQL to identify top credit consumers by user."""
    days_back = max(1, int(days_back or 7))
    return f"""
    WITH user_credits AS (
        SELECT
            q.user_name,
            q.warehouse_name,
            SUM(q.execution_time) AS total_exec_ms,
            SUM(q.execution_time) * 1.0 / NULLIF(
                SUM(SUM(q.execution_time)) OVER (PARTITION BY q.warehouse_name),
                0
            ) AS exec_share
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND q.execution_time > 0
        GROUP BY q.user_name, q.warehouse_name
    ),
    warehouse_credits AS (
        SELECT
            warehouse_name,
            SUM(credits_used) AS total_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
        GROUP BY warehouse_name
    )
    SELECT
        uc.user_name,
        ROUND(SUM(uc.exec_share * wc.total_credits), 4) AS attributed_credits,
        COUNT(DISTINCT uc.warehouse_name) AS warehouses_used,
        ROUND(SUM(uc.total_exec_ms) / 1000.0 / 3600, 2) AS total_exec_hours
    FROM user_credits uc
    JOIN warehouse_credits wc ON uc.warehouse_name = wc.warehouse_name
    GROUP BY uc.user_name
    HAVING attributed_credits > 0.1
    ORDER BY attributed_credits DESC
    LIMIT 25
    """


def summarize_user_analytics(user_df) -> dict[str, Any]:
    """Summarize user analytics into executive metrics."""
    import pandas as pd

    result = {
        "total_users": 0,
        "power_users": 0,
        "regular_users": 0,
        "occasional_users": 0,
        "rare_users": 0,
        "adoption_pct": 0.0,
        "avg_queries_per_user": 0.0,
    }

    if not isinstance(user_df, pd.DataFrame) or user_df.empty:
        return result

    result["total_users"] = len(user_df)

    if "USER_SEGMENT" in user_df.columns:
        segments = user_df["USER_SEGMENT"].value_counts()
        result["power_users"] = int(segments.get("Power User", 0))
        result["regular_users"] = int(segments.get("Regular", 0))
        result["occasional_users"] = int(segments.get("Occasional", 0))
        result["rare_users"] = int(segments.get("Rare", 0))

    active = result["power_users"] + result["regular_users"]
    result["adoption_pct"] = round(active / result["total_users"] * 100, 1) if result["total_users"] > 0 else 0

    if "QUERY_COUNT" in user_df.columns:
        result["avg_queries_per_user"] = round(float(user_df["QUERY_COUNT"].mean()), 0)

    return result
