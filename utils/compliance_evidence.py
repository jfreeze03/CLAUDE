# utils/compliance_evidence.py - Compliance and audit evidence collection
"""
Collects evidence needed for SOC 2, HIPAA, and general audit compliance:
  - Access review evidence (who has access to what)
  - Privilege escalation detection
  - Data access patterns for sensitive tables
  - Login anomaly detection
  - Password policy compliance

Answers: "Can we prove our access controls are working?"
"""
from __future__ import annotations

from typing import Any


def build_privilege_escalation_sql(days_back: int = 30) -> str:
    """SQL to detect privilege escalation events (GRANT to privileged roles)."""
    days_back = max(1, int(days_back or 30))
    return f"""
    SELECT
        query_type,
        user_name AS granted_by,
        role_name AS granting_role,
        start_time,
        SUBSTR(query_text, 1, 500) AS grant_statement,
        execution_status
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND query_type IN ('GRANT', 'REVOKE')
      AND execution_status = 'SUCCESS'
      AND (
          query_text ILIKE '%ACCOUNTADMIN%'
          OR query_text ILIKE '%SECURITYADMIN%'
          OR query_text ILIKE '%SYSADMIN%'
          OR query_text ILIKE '%ALL PRIVILEGES%'
          OR query_text ILIKE '%OWNERSHIP%'
      )
    ORDER BY start_time DESC
    LIMIT 100
    """


def build_failed_login_sql(days_back: int = 7) -> str:
    """SQL to detect suspicious login patterns."""
    days_back = max(1, int(days_back or 7))
    return f"""
    SELECT
        user_name,
        client_ip,
        reported_client_type,
        error_code,
        error_message,
        event_timestamp,
        COUNT(*) OVER (PARTITION BY user_name, DATE(event_timestamp)) AS daily_failures
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
    WHERE event_timestamp >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND is_success = 'NO'
    ORDER BY event_timestamp DESC
    LIMIT 200
    """


def build_dormant_users_sql(days_back: int = 90) -> str:
    """SQL to find users who haven't logged in within the dormancy threshold."""
    days_back = max(30, int(days_back or 90))
    return f"""
    WITH user_activity AS (
        SELECT
            u.name AS user_name,
            u.login_name,
            u.created_on,
            u.disabled,
            u.default_role,
            MAX(lh.event_timestamp) AS last_login
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
          ON u.name = lh.user_name
          AND lh.is_success = 'YES'
          AND lh.event_timestamp >= DATEADD('day', -{days_back * 2}, CURRENT_TIMESTAMP())
        WHERE u.deleted_on IS NULL
        GROUP BY u.name, u.login_name, u.created_on, u.disabled, u.default_role
    )
    SELECT
        user_name,
        login_name,
        created_on,
        disabled,
        default_role,
        last_login,
        DATEDIFF('day', COALESCE(last_login, created_on), CURRENT_TIMESTAMP()) AS days_inactive,
        CASE
            WHEN last_login IS NULL AND DATEDIFF('day', created_on, CURRENT_TIMESTAMP()) > {days_back}
                THEN 'Never Logged In'
            WHEN DATEDIFF('day', last_login, CURRENT_TIMESTAMP()) > {days_back}
                THEN 'Dormant'
            WHEN disabled = 'true' THEN 'Disabled'
            ELSE 'Active'
        END AS account_status
    FROM user_activity
    WHERE (
        last_login IS NULL
        OR DATEDIFF('day', last_login, CURRENT_TIMESTAMP()) > {days_back}
    )
      AND disabled != 'true'
    ORDER BY days_inactive DESC
    """


def build_sensitive_access_sql(days_back: int = 7) -> str:
    """SQL to track access to tables tagged as sensitive or PII."""
    days_back = max(1, int(days_back or 7))
    return f"""
    SELECT
        ah.query_id,
        ah.user_name,
        ah.role_name,
        ah.query_start_time,
        doa.object_name AS accessed_object,
        doa.object_domain AS object_type,
        doa.columns_accessed,
        ah.query_type
    FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah,
    LATERAL FLATTEN(input => ah.direct_objects_accessed) doa
    WHERE ah.query_start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND (
          doa.object_name ILIKE '%PII%'
          OR doa.object_name ILIKE '%SENSITIVE%'
          OR doa.object_name ILIKE '%PHI%'
          OR doa.object_name ILIKE '%CUSTOMER%'
          OR doa.object_name ILIKE '%SSN%'
          OR doa.object_name ILIKE '%CREDIT_CARD%'
      )
    ORDER BY ah.query_start_time DESC
    LIMIT 100
    """


def build_role_grant_summary_sql() -> str:
    """SQL to summarize current role grants for access review."""
    return """
    WITH role_grants AS (
        SELECT
            grantee_name,
            role,
            granted_by,
            created_on
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
        WHERE deleted_on IS NULL
    ),
    privileged_roles AS (
        SELECT DISTINCT grantee_name, role
        FROM role_grants
        WHERE role IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
    )
    SELECT
        pr.grantee_name AS user_name,
        pr.role AS privileged_role,
        rg.granted_by,
        rg.created_on,
        DATEDIFF('day', rg.created_on, CURRENT_TIMESTAMP()) AS days_since_granted
    FROM privileged_roles pr
    JOIN role_grants rg
      ON pr.grantee_name = rg.grantee_name
     AND pr.role = rg.role
    ORDER BY pr.role, rg.created_on DESC
    """


def build_compliance_scorecard(
    escalations_df=None,
    failed_logins_df=None,
    dormant_users_df=None,
) -> dict[str, Any]:
    """Build a compliance readiness scorecard from collected evidence."""
    import pandas as pd

    scorecard = {
        "overall_score": 80,
        "categories": {},
        "findings": [],
        "recommendations": [],
    }

    # Privilege escalation
    escalation_count = 0
    if isinstance(escalations_df, pd.DataFrame) and not escalations_df.empty:
        escalation_count = len(escalations_df)
        if escalation_count > 10:
            scorecard["overall_score"] -= 20
            scorecard["findings"].append(f"{escalation_count} privilege escalation events detected")
            scorecard["recommendations"].append("Review all GRANT statements to privileged roles")
        elif escalation_count > 0:
            scorecard["overall_score"] -= 5
    scorecard["categories"]["privilege_management"] = {
        "score": max(0, 100 - escalation_count * 5),
        "events": escalation_count,
    }

    # Failed logins
    failed_count = 0
    if isinstance(failed_logins_df, pd.DataFrame) and not failed_logins_df.empty:
        failed_count = len(failed_logins_df)
        # Check for brute force patterns
        if "DAILY_FAILURES" in failed_logins_df.columns:
            max_daily = int(failed_logins_df["DAILY_FAILURES"].max())
            if max_daily > 20:
                scorecard["overall_score"] -= 15
                scorecard["findings"].append(f"Possible brute force: {max_daily} failures from one user in one day")
                scorecard["recommendations"].append("Investigate high-failure accounts and consider MFA enforcement")
    scorecard["categories"]["login_security"] = {
        "score": max(0, 100 - min(30, failed_count)),
        "events": failed_count,
    }

    # Dormant users
    dormant_count = 0
    if isinstance(dormant_users_df, pd.DataFrame) and not dormant_users_df.empty:
        dormant_count = len(dormant_users_df)
        if dormant_count > 20:
            scorecard["overall_score"] -= 10
            scorecard["findings"].append(f"{dormant_count} dormant user accounts should be reviewed")
            scorecard["recommendations"].append("Disable or remove dormant accounts per access review policy")
        elif dormant_count > 5:
            scorecard["overall_score"] -= 5
    scorecard["categories"]["access_hygiene"] = {
        "score": max(0, 100 - dormant_count * 2),
        "events": dormant_count,
    }

    scorecard["overall_score"] = max(0, min(100, scorecard["overall_score"]))
    return scorecard
