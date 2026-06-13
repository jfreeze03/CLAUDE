# utils/multi_account.py - Multi-account and organization-level support
"""
Enterprise Snowflake deployments run multiple accounts.
This module provides:
  - Organization-level cost aggregation SQL
  - Cross-account credit comparison
  - Account inventory and health summary
  - Organization billing view integration

Requires ORGANIZATION_USAGE views (available to ORGADMIN role).
"""
from __future__ import annotations

from typing import Any


def build_org_credit_summary_sql(days_back: int = 30) -> str:
    """SQL to aggregate credit consumption across all accounts in the organization."""
    days_back = max(1, int(days_back or 30))
    return f"""
    SELECT
        account_name,
        account_locator,
        region,
        DATE(usage_date) AS usage_date,
        service_type,
        ROUND(SUM(credits_used), 4) AS credits_used,
        ROUND(SUM(credits_used_compute), 4) AS credits_used_compute,
        ROUND(SUM(credits_used_cloud_services), 4) AS credits_used_cloud_services
    FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
    WHERE usage_date >= DATEADD('day', -{days_back}, CURRENT_DATE())
    GROUP BY account_name, account_locator, region, DATE(usage_date), service_type
    ORDER BY credits_used DESC
    """


def build_org_contract_status_sql() -> str:
    """SQL to pull organization-level contract remaining balance."""
    return """
    SELECT
        DATE AS balance_date,
        ORGANIZATION_NAME,
        CURRENCY,
        FREE_USAGE_BALANCE,
        CAPACITY_BALANCE,
        ON_DEMAND_CONSUMPTION_BALANCE,
        ROLLOVER_BALANCE,
        (COALESCE(FREE_USAGE_BALANCE, 0) + COALESCE(CAPACITY_BALANCE, 0)
         + COALESCE(ROLLOVER_BALANCE, 0)) AS total_remaining
    FROM SNOWFLAKE.ORGANIZATION_USAGE.REMAINING_BALANCE_DAILY
    ORDER BY DATE DESC
    LIMIT 30
    """


def build_org_account_inventory_sql() -> str:
    """SQL to list all accounts in the organization."""
    return """
    SELECT
        account_name,
        account_locator,
        region,
        snowflake_region,
        created_on,
        account_url,
        edition,
        comment
    FROM SNOWFLAKE.ORGANIZATION_USAGE.ACCOUNTS
    ORDER BY account_name
    """


def build_org_rate_sheet_sql() -> str:
    """SQL to pull the organization's effective rate sheet."""
    return """
    SELECT
        DATE AS effective_date,
        SERVICE_TYPE,
        EFFECTIVE_RATE,
        CURRENCY,
        USAGE_TYPE
    FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
    WHERE DATE >= DATEADD('day', -7, CURRENT_DATE())
    ORDER BY DATE DESC, SERVICE_TYPE
    """


def build_cross_account_comparison_sql(days_back: int = 30) -> str:
    """SQL to compare credit consumption across accounts."""
    days_back = max(1, int(days_back or 30))
    return f"""
    WITH account_totals AS (
        SELECT
            account_name,
            region,
            SUM(credits_used) AS total_credits,
            SUM(credits_used_compute) AS compute_credits,
            SUM(credits_used_cloud_services) AS cloud_credits,
            COUNT(DISTINCT DATE(usage_date)) AS active_days,
            AVG(credits_used) AS avg_daily_credits,
            MAX(credits_used) AS peak_daily_credits
        FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
        WHERE usage_date >= DATEADD('day', -{days_back}, CURRENT_DATE())
        GROUP BY account_name, region
    )
    SELECT
        account_name,
        region,
        ROUND(total_credits, 2) AS total_credits,
        ROUND(compute_credits, 2) AS compute_credits,
        ROUND(cloud_credits, 2) AS cloud_credits,
        active_days,
        ROUND(avg_daily_credits, 2) AS avg_daily_credits,
        ROUND(peak_daily_credits, 2) AS peak_daily_credits,
        ROUND(total_credits * 100.0 / NULLIF(SUM(total_credits) OVER (), 0), 1) AS pct_of_org
    FROM account_totals
    ORDER BY total_credits DESC
    """


def build_org_storage_summary_sql() -> str:
    """SQL to aggregate storage across accounts."""
    return """
    SELECT
        account_name,
        DATE(usage_date) AS usage_date,
        ROUND(average_stage_bytes / (1024*1024*1024*1024.0), 4) AS stage_tb,
        ROUND(average_storage_bytes / (1024*1024*1024*1024.0), 4) AS storage_tb,
        ROUND(average_failsafe_bytes / (1024*1024*1024*1024.0), 4) AS failsafe_tb,
        ROUND(
            (average_stage_bytes + average_storage_bytes + average_failsafe_bytes)
            / (1024*1024*1024*1024.0), 4
        ) AS total_tb
    FROM SNOWFLAKE.ORGANIZATION_USAGE.STORAGE_DAILY_HISTORY
    WHERE usage_date >= DATEADD('day', -30, CURRENT_DATE())
    ORDER BY usage_date DESC, total_tb DESC
    """


def check_org_access(session) -> dict[str, Any]:
    """
    Check whether the current session has ORGANIZATION_USAGE access.

    Returns:
        {"available": bool, "account_count": int, "org_name": str, "error": str}
    """
    result = {"available": False, "account_count": 0, "org_name": "", "error": ""}
    try:
        rows = session.sql(
            "SELECT COUNT(*) AS cnt FROM SNOWFLAKE.ORGANIZATION_USAGE.ACCOUNTS"
        ).collect()
        count = int(rows[0]["CNT"]) if rows else 0
        result["available"] = count > 0
        result["account_count"] = count

        org_rows = session.sql(
            "SELECT CURRENT_ORGANIZATION_NAME() AS org"
        ).collect()
        result["org_name"] = str(org_rows[0]["ORG"]) if org_rows else ""
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def summarize_org_costs(org_df) -> dict[str, Any]:
    """Summarize organization-level costs into a structured report."""
    import pandas as pd

    if not isinstance(org_df, pd.DataFrame) or org_df.empty:
        return {"total_credits": 0, "accounts": [], "top_service": ""}

    total = float(org_df["CREDITS_USED"].sum()) if "CREDITS_USED" in org_df.columns else 0

    accounts = []
    if "ACCOUNT_NAME" in org_df.columns:
        account_totals = org_df.groupby("ACCOUNT_NAME")["CREDITS_USED"].sum().sort_values(ascending=False)
        for acct, credits in account_totals.head(10).items():
            accounts.append({
                "account": str(acct),
                "credits": round(float(credits), 2),
                "pct": round(float(credits) / total * 100, 1) if total > 0 else 0,
            })

    top_service = ""
    if "SERVICE_TYPE" in org_df.columns:
        top_service = str(org_df.groupby("SERVICE_TYPE")["CREDITS_USED"].sum().idxmax())

    return {
        "total_credits": round(total, 2),
        "accounts": accounts,
        "account_count": len(accounts),
        "top_service": top_service,
    }
