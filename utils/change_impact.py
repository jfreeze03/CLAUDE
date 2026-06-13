# utils/change_impact.py - Change impact scoring and blast radius analysis
"""
When a DDL change is detected (from Change & Drift), score its
potential blast radius by checking:
  - How many queries reference the changed object?
  - How many users/roles access it?
  - How many downstream views/procedures depend on it?
  - Is it in a production tier database?

This turns "a table was altered" into "this change affects 47 queries,
12 users, and 3 downstream views in a Tier 0 database."
"""
from __future__ import annotations

from typing import Any


def build_object_usage_sql(object_name: str, database: str = None, days_back: int = 7) -> str:
    """SQL to count queries that referenced a specific object."""
    days_back = max(1, int(days_back or 7))
    safe_obj = str(object_name).replace("'", "''")
    db_filter = f"AND database_name = '{database}'" if database else ""
    return f"""
    SELECT
        COUNT(*) AS query_count,
        COUNT(DISTINCT user_name) AS unique_users,
        COUNT(DISTINCT role_name) AS unique_roles,
        COUNT(DISTINCT warehouse_name) AS unique_warehouses,
        MIN(start_time) AS first_access,
        MAX(start_time) AS last_access
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND (
          query_text ILIKE '%{safe_obj}%'
      )
      AND execution_status = 'SUCCESS'
      {db_filter}
    """


def build_access_history_sql(object_name: str, database: str = None, days_back: int = 7) -> str:
    """SQL using ACCESS_HISTORY for precise object reference counting."""
    days_back = max(1, int(days_back or 7))
    safe_obj = str(object_name).replace("'", "''").upper()
    db_filter = f"AND UPPER(doa.value:objectDomain::STRING) = UPPER('{database}')" if database else ""
    return f"""
    SELECT
        ah.user_name,
        ah.role_name,
        COUNT(DISTINCT ah.query_id) AS query_count,
        MIN(ah.query_start_time) AS first_access,
        MAX(ah.query_start_time) AS last_access
    FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah,
    LATERAL FLATTEN(input => ah.direct_objects_accessed) doa
    WHERE ah.query_start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND UPPER(doa.value:objectName::STRING) = '{safe_obj}'
      {db_filter}
    GROUP BY ah.user_name, ah.role_name
    ORDER BY query_count DESC
    LIMIT 50
    """


def build_dependent_objects_sql(object_name: str, database: str = None) -> str:
    """SQL to find objects that depend on the changed object."""
    safe_obj = str(object_name).replace("'", "''").upper()
    db_filter = f"AND UPPER(referenced_database_name) = UPPER('{database}')" if database else ""
    return f"""
    SELECT
        referencing_database_name AS dependent_database,
        referencing_schema_name AS dependent_schema,
        referencing_object_name AS dependent_object,
        referencing_object_type AS dependent_type,
        dependency_type
    FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
    WHERE UPPER(referenced_object_name) = '{safe_obj}'
      {db_filter}
    ORDER BY referencing_object_type, referencing_object_name
    """


def score_change_impact(
    object_name: str,
    object_type: str = "TABLE",
    *,
    query_count: int = 0,
    unique_users: int = 0,
    unique_roles: int = 0,
    dependent_objects: int = 0,
    database_tier: str = "Tier 2",
    is_production: bool = False,
) -> dict[str, Any]:
    """
    Score the blast radius of a change.

    Returns:
        {
            "impact_score": int (0-100),
            "severity": "Critical" | "High" | "Medium" | "Low",
            "blast_radius": str,
            "risk_factors": [str],
            "recommendation": str,
        }
    """
    score = 0
    risk_factors = []

    # Query volume impact
    if query_count > 1000:
        score += 35
        risk_factors.append(f"High query volume: {query_count:,} queries reference this object")
    elif query_count > 100:
        score += 20
        risk_factors.append(f"Moderate query volume: {query_count:,} references")
    elif query_count > 10:
        score += 10

    # User impact
    if unique_users > 20:
        score += 20
        risk_factors.append(f"Wide user impact: {unique_users} users affected")
    elif unique_users > 5:
        score += 10
        risk_factors.append(f"{unique_users} users access this object")

    # Downstream dependencies
    if dependent_objects > 10:
        score += 25
        risk_factors.append(f"Deep dependency chain: {dependent_objects} downstream objects")
    elif dependent_objects > 3:
        score += 15
        risk_factors.append(f"{dependent_objects} dependent objects")
    elif dependent_objects > 0:
        score += 5

    # Production tier multiplier
    if is_production or "Tier 0" in database_tier:
        score = min(100, int(score * 1.5))
        risk_factors.append("Production Tier 0 database — changes require approval")
    elif "Tier 1" in database_tier:
        score = min(100, int(score * 1.2))
        risk_factors.append("Tier 1 database — changes should be reviewed")

    # Severity classification
    if score >= 75:
        severity = "Critical"
        blast_radius = "Wide — likely to affect multiple teams and workflows"
        recommendation = "Rollback or verify with all affected owners before proceeding. Notify downstream teams."
    elif score >= 50:
        severity = "High"
        blast_radius = "Significant — affects active users and dependent objects"
        recommendation = "Review with object owner and validate downstream queries still function."
    elif score >= 25:
        severity = "Medium"
        blast_radius = "Moderate — limited user and dependency impact"
        recommendation = "Monitor for query failures in the next 24 hours."
    else:
        severity = "Low"
        blast_radius = "Minimal — few references and no critical dependencies"
        recommendation = "No immediate action required. Standard change tracking."

    return {
        "object": object_name,
        "object_type": object_type,
        "impact_score": min(100, score),
        "severity": severity,
        "blast_radius": blast_radius,
        "risk_factors": risk_factors,
        "recommendation": recommendation,
        "metrics": {
            "query_count": query_count,
            "unique_users": unique_users,
            "unique_roles": unique_roles,
            "dependent_objects": dependent_objects,
            "database_tier": database_tier,
        },
    }
