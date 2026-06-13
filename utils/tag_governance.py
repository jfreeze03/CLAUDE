# utils/tag_governance.py - Tag-based governance and cost attribution
"""
Snowflake tags are the foundation of enterprise governance:
  - COST_OWNER for chargeback
  - SENSITIVITY for classification
  - SERVICE_TIER for RPO/RTO
  - APP_OWNER for responsibility routing

This module tracks tag coverage, identifies untagged assets,
and scores governance maturity.
"""
from __future__ import annotations

from typing import Any


def build_tag_coverage_sql() -> str:
    """SQL to assess tag coverage across databases and warehouses."""
    return """
    WITH all_objects AS (
        SELECT
            'DATABASE' AS object_type,
            database_name AS object_name,
            NULL AS schema_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES
        WHERE deleted IS NULL

        UNION ALL

        SELECT
            'WAREHOUSE' AS object_type,
            name AS object_name,
            NULL AS schema_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
        WHERE deleted_on IS NULL
    ),
    tagged_objects AS (
        SELECT DISTINCT
            UPPER(domain) AS object_type,
            object_name,
            tag_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE tag_name IN ('COST_OWNER', 'DATA_OWNER', 'APP_OWNER', 'SERVICE_TIER', 'SENSITIVITY')
    ),
    coverage AS (
        SELECT
            ao.object_type,
            ao.object_name,
            COUNT(DISTINCT t.tag_name) AS tag_count,
            LISTAGG(DISTINCT t.tag_name, ', ') WITHIN GROUP (ORDER BY t.tag_name) AS applied_tags
        FROM all_objects ao
        LEFT JOIN tagged_objects t
          ON UPPER(ao.object_type) = t.object_type
         AND UPPER(ao.object_name) = UPPER(t.object_name)
        GROUP BY ao.object_type, ao.object_name
    )
    SELECT
        object_type,
        object_name,
        tag_count,
        applied_tags,
        CASE
            WHEN tag_count >= 3 THEN 'Well Tagged'
            WHEN tag_count >= 1 THEN 'Partially Tagged'
            ELSE 'Untagged'
        END AS coverage_status
    FROM coverage
    ORDER BY tag_count ASC, object_type, object_name
    """


def build_untagged_assets_sql() -> str:
    """SQL to find assets missing critical governance tags."""
    return """
    WITH warehouses AS (
        SELECT name AS object_name, 'WAREHOUSE' AS object_type
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
        WHERE deleted_on IS NULL
    ),
    tagged AS (
        SELECT DISTINCT object_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE tag_name = 'COST_OWNER'
          AND UPPER(domain) = 'WAREHOUSE'
    )
    SELECT
        w.object_name,
        w.object_type,
        'Missing COST_OWNER tag' AS gap_description,
        'Unattributed cost — cannot route spend to an owner' AS risk
    FROM warehouses w
    LEFT JOIN tagged t ON UPPER(w.object_name) = UPPER(t.object_name)
    WHERE t.object_name IS NULL
    ORDER BY w.object_name
    """


def summarize_tag_governance(coverage_df) -> dict[str, Any]:
    """Summarize tag governance maturity."""
    import pandas as pd

    result = {
        "total_objects": 0,
        "well_tagged": 0,
        "partially_tagged": 0,
        "untagged": 0,
        "coverage_pct": 0.0,
        "maturity": "Not Assessed",
    }

    if not isinstance(coverage_df, pd.DataFrame) or coverage_df.empty:
        return result

    result["total_objects"] = len(coverage_df)
    if "COVERAGE_STATUS" in coverage_df.columns:
        counts = coverage_df["COVERAGE_STATUS"].value_counts()
        result["well_tagged"] = int(counts.get("Well Tagged", 0))
        result["partially_tagged"] = int(counts.get("Partially Tagged", 0))
        result["untagged"] = int(counts.get("Untagged", 0))

    tagged = result["well_tagged"] + result["partially_tagged"]
    result["coverage_pct"] = round(tagged / result["total_objects"] * 100, 1) if result["total_objects"] > 0 else 0

    if result["coverage_pct"] >= 90:
        result["maturity"] = "Mature"
    elif result["coverage_pct"] >= 60:
        result["maturity"] = "Developing"
    elif result["coverage_pct"] >= 30:
        result["maturity"] = "Early"
    else:
        result["maturity"] = "Ad Hoc"

    return result
