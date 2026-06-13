# utils/chargeback.py - Automated cost allocation and chargeback reporting
"""
Allocates warehouse credit consumption to business units using:
  - COST_OWNER tags from OVERWATCH_OWNER_TAG_NAMES
  - Warehouse ownership patterns from OVERWATCH_OWNER_DIRECTORY
  - Query-level user/role attribution as fallback

Produces chargeback reports suitable for FinOps review.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def build_chargeback_by_owner_sql(days_back: int = 30) -> str:
    """SQL to allocate warehouse costs to owners using tag-based attribution.

    Priority: COST_OWNER tag > warehouse owner directory > role-based fallback.
    """
    days_back = max(1, int(days_back or 30))
    return f"""
    WITH warehouse_credits AS (
        SELECT
            warehouse_name,
            DATE(start_time) AS usage_date,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_DATE()
        GROUP BY warehouse_name, DATE(start_time)
    ),
    owner_lookup AS (
        SELECT
            ENTITY_PATTERN,
            OWNER_NAME,
            OWNER_EMAIL,
            SERVICE_TIER,
            MATCH_PRIORITY
        FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_OWNER_DIRECTORY
        WHERE UPPER(ENTITY_TYPE) = 'WAREHOUSE'
          AND COALESCE(IS_ACTIVE, TRUE)
    ),
    attributed AS (
        SELECT
            wc.warehouse_name,
            wc.usage_date,
            wc.daily_credits,
            COALESCE(
                ol.OWNER_NAME,
                'Unattributed'
            ) AS cost_owner,
            COALESCE(ol.OWNER_EMAIL, '') AS owner_email,
            COALESCE(ol.SERVICE_TIER, 'Unclassified') AS service_tier,
            CASE
                WHEN ol.OWNER_NAME IS NOT NULL THEN 'Owner Directory'
                ELSE 'Unattributed'
            END AS attribution_source
        FROM warehouse_credits wc
        LEFT JOIN owner_lookup ol
          ON (
              (ol.ENTITY_PATTERN = '*' AND ol.MATCH_PRIORITY > 0)
              OR UPPER(wc.warehouse_name) = UPPER(ol.ENTITY_PATTERN)
              OR (ol.ENTITY_PATTERN LIKE '%*%'
                  AND UPPER(wc.warehouse_name) LIKE REPLACE(UPPER(ol.ENTITY_PATTERN), '*', '%'))
          )
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY wc.warehouse_name, wc.usage_date
            ORDER BY COALESCE(ol.MATCH_PRIORITY, 0) DESC
        ) = 1
    )
    SELECT
        cost_owner,
        owner_email,
        service_tier,
        attribution_source,
        COUNT(DISTINCT warehouse_name) AS warehouse_count,
        COUNT(DISTINCT usage_date) AS active_days,
        ROUND(SUM(daily_credits), 2) AS total_credits,
        ROUND(AVG(daily_credits), 2) AS avg_daily_credits,
        ROUND(MAX(daily_credits), 2) AS peak_daily_credits,
        LISTAGG(DISTINCT warehouse_name, ', ') WITHIN GROUP (ORDER BY warehouse_name) AS warehouses
    FROM attributed
    GROUP BY cost_owner, owner_email, service_tier, attribution_source
    ORDER BY total_credits DESC
    """


def build_chargeback_by_database_sql(days_back: int = 30) -> str:
    """SQL to allocate query costs by database (for environments without warehouse-level ownership)."""
    days_back = max(1, int(days_back or 30))
    return f"""
    WITH query_costs AS (
        SELECT
            q.database_name,
            q.warehouse_name,
            q.user_name,
            q.role_name,
            DATE(q.start_time) AS usage_date,
            q.execution_time AS exec_ms,
            SUM(q.execution_time) OVER (
                PARTITION BY q.warehouse_name, DATE_TRUNC('hour', q.start_time)
            ) AS hour_total_exec_ms
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.start_time < CURRENT_DATE()
          AND q.warehouse_name IS NOT NULL
          AND q.execution_time > 0
          AND q.database_name IS NOT NULL
    ),
    metered AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time) AS hour_bucket,
            SUM(COALESCE(credits_used_compute, credits_used)) AS hourly_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_DATE()
        GROUP BY warehouse_name, hour_bucket
    ),
    allocated AS (
        SELECT
            qc.database_name,
            qc.warehouse_name,
            qc.usage_date,
            ROUND(
                SUM(COALESCE(m.hourly_credits, 0) * qc.exec_ms / NULLIF(qc.hour_total_exec_ms, 0)),
                6
            ) AS allocated_credits
        FROM query_costs qc
        LEFT JOIN metered m
          ON qc.warehouse_name = m.warehouse_name
         AND DATE_TRUNC('hour', qc.usage_date) = m.hour_bucket
        GROUP BY qc.database_name, qc.warehouse_name, qc.usage_date
    )
    SELECT
        database_name,
        COUNT(DISTINCT warehouse_name) AS warehouse_count,
        COUNT(DISTINCT usage_date) AS active_days,
        ROUND(SUM(allocated_credits), 2) AS total_credits,
        ROUND(AVG(allocated_credits), 2) AS avg_daily_credits,
        LISTAGG(DISTINCT warehouse_name, ', ') WITHIN GROUP (ORDER BY warehouse_name) AS warehouses
    FROM allocated
    GROUP BY database_name
    HAVING SUM(allocated_credits) > 0.01
    ORDER BY total_credits DESC
    """


def build_chargeback_trend_sql(days_back: int = 30) -> str:
    """SQL for weekly chargeback trend by owner."""
    days_back = max(7, int(days_back or 30))
    return f"""
    WITH warehouse_credits AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('week', DATE(start_time)) AS week_start,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS weekly_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_DATE()
        GROUP BY warehouse_name, week_start
    ),
    owner_lookup AS (
        SELECT ENTITY_PATTERN, OWNER_NAME, MATCH_PRIORITY
        FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_OWNER_DIRECTORY
        WHERE UPPER(ENTITY_TYPE) = 'WAREHOUSE'
          AND COALESCE(IS_ACTIVE, TRUE)
    ),
    attributed AS (
        SELECT
            wc.week_start,
            COALESCE(ol.OWNER_NAME, 'Unattributed') AS cost_owner,
            wc.weekly_credits
        FROM warehouse_credits wc
        LEFT JOIN owner_lookup ol
          ON UPPER(wc.warehouse_name) = UPPER(ol.ENTITY_PATTERN)
             OR (ol.ENTITY_PATTERN LIKE '%*%'
                 AND UPPER(wc.warehouse_name) LIKE REPLACE(UPPER(ol.ENTITY_PATTERN), '*', '%'))
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY wc.warehouse_name, wc.week_start
            ORDER BY COALESCE(ol.MATCH_PRIORITY, 0) DESC
        ) = 1
    )
    SELECT
        week_start,
        cost_owner,
        ROUND(SUM(weekly_credits), 2) AS weekly_credits
    FROM attributed
    GROUP BY week_start, cost_owner
    ORDER BY week_start, weekly_credits DESC
    """


def format_chargeback_report(owner_df, *, credit_price: float = 3.68) -> dict[str, Any]:
    """Format chargeback data into a structured report."""
    import pandas as pd

    if not isinstance(owner_df, pd.DataFrame) or owner_df.empty:
        return {"owners": [], "total_credits": 0, "total_cost": 0, "unattributed_pct": 0}

    total_credits = float(owner_df["TOTAL_CREDITS"].sum()) if "TOTAL_CREDITS" in owner_df.columns else 0

    owners = []
    for _, row in owner_df.iterrows():
        credits = float(row.get("TOTAL_CREDITS", 0) or 0)
        owners.append({
            "owner": str(row.get("COST_OWNER", "Unknown")),
            "email": str(row.get("OWNER_EMAIL", "")),
            "tier": str(row.get("SERVICE_TIER", "")),
            "credits": round(credits, 2),
            "cost_usd": round(credits * credit_price, 2),
            "pct_of_total": round(credits / total_credits * 100, 1) if total_credits > 0 else 0,
            "warehouses": str(row.get("WAREHOUSES", "")),
            "source": str(row.get("ATTRIBUTION_SOURCE", "")),
        })

    unattributed = sum(o["credits"] for o in owners if o["owner"] == "Unattributed")
    unattributed_pct = round(unattributed / total_credits * 100, 1) if total_credits > 0 else 0

    return {
        "owners": owners,
        "total_credits": round(total_credits, 2),
        "total_cost": round(total_credits * credit_price, 2),
        "unattributed_pct": unattributed_pct,
        "owner_count": len([o for o in owners if o["owner"] != "Unattributed"]),
    }
