# utils/network_egress.py - Data transfer and network cost monitoring
"""
Tracks the often-overlooked network costs:
  - Cross-region data transfer
  - PrivateLink usage
  - External function egress
  - Replication transfer

These can be 10-20% of total spend but are invisible in
warehouse-only cost views.
"""
from __future__ import annotations


def build_data_transfer_sql(days_back: int = 30) -> str:
    """SQL to pull data transfer credits from metering history."""
    days_back = max(1, int(days_back or 30))
    return f"""
    SELECT
        DATE(start_time) AS usage_date,
        service_type,
        ROUND(SUM(credits_used), 4) AS transfer_credits,
        COUNT(*) AS metering_rows
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND (
          service_type ILIKE '%DATA_TRANSFER%'
          OR service_type ILIKE '%PRIVATELINK%'
          OR service_type ILIKE '%REPLICATION%'
          OR service_type ILIKE '%EXTERNAL_FUNCTION%'
      )
    GROUP BY usage_date, service_type
    HAVING SUM(credits_used) > 0
    ORDER BY usage_date DESC, transfer_credits DESC
    """


def build_replication_cost_sql(days_back: int = 30) -> str:
    """SQL to pull replication-specific transfer costs."""
    days_back = max(1, int(days_back or 30))
    return f"""
    SELECT
        DATE(start_time) AS usage_date,
        database_name,
        ROUND(SUM(credits_used), 4) AS replication_credits,
        ROUND(SUM(bytes_transferred) / (1024*1024*1024.0), 2) AS gb_transferred
    FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_USAGE_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
    GROUP BY usage_date, database_name
    ORDER BY replication_credits DESC
    """


def build_network_summary_sql(days_back: int = 30) -> str:
    """SQL for a consolidated network cost summary."""
    days_back = max(1, int(days_back or 30))
    return f"""
    WITH transfer_costs AS (
        SELECT
            CASE
                WHEN service_type ILIKE '%REPLICATION%' THEN 'Replication'
                WHEN service_type ILIKE '%PRIVATELINK%' THEN 'PrivateLink'
                WHEN service_type ILIKE '%DATA_TRANSFER%' THEN 'Data Transfer'
                WHEN service_type ILIKE '%EXTERNAL_FUNCTION%' THEN 'External Functions'
                ELSE 'Other Network'
            END AS network_category,
            ROUND(SUM(credits_used), 4) AS credits,
            COUNT(DISTINCT DATE(start_time)) AS active_days
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND (
              service_type ILIKE '%DATA_TRANSFER%'
              OR service_type ILIKE '%PRIVATELINK%'
              OR service_type ILIKE '%REPLICATION%'
              OR service_type ILIKE '%EXTERNAL_FUNCTION%'
          )
        GROUP BY network_category
    )
    SELECT
        network_category,
        credits,
        active_days,
        ROUND(credits / NULLIF(active_days, 0), 2) AS avg_daily_credits
    FROM transfer_costs
    WHERE credits > 0
    ORDER BY credits DESC
    """
