# utils/governance_catalog.py - Snowflake governance and policy coverage
"""
Tracks governance readiness across:
  - Classification coverage (how many tables have sensitivity tags)
  - Policy coverage (masking, row access, tag policies)
  - Access history availability
  - Lineage readiness

Answers: "Are we ready for a compliance audit?"
"""
from __future__ import annotations

from typing import Any


def build_classification_coverage_sql() -> str:
    """SQL to assess data classification coverage."""
    return """
    WITH classified AS (
        SELECT
            table_catalog AS database_name,
            table_schema AS schema_name,
            table_name,
            column_name,
            tag_name,
            tag_value
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE domain = 'COLUMN'
          AND tag_name IN ('SEMANTIC_CATEGORY', 'PRIVACY_CATEGORY', 'PII', 'SENSITIVITY')
    ),
    all_columns AS (
        SELECT
            table_catalog AS database_name,
            table_schema AS schema_name,
            table_name,
            column_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.COLUMNS
        WHERE deleted IS NULL
          AND table_schema NOT IN ('INFORMATION_SCHEMA')
    )
    SELECT
        ac.database_name,
        COUNT(DISTINCT ac.column_name) AS total_columns,
        COUNT(DISTINCT c.column_name) AS classified_columns,
        ROUND(COUNT(DISTINCT c.column_name) * 100.0 / NULLIF(COUNT(DISTINCT ac.column_name), 0), 1)
            AS classification_pct
    FROM all_columns ac
    LEFT JOIN classified c
      ON ac.database_name = c.database_name
     AND ac.schema_name = c.schema_name
     AND ac.table_name = c.table_name
     AND ac.column_name = c.column_name
    GROUP BY ac.database_name
    HAVING COUNT(DISTINCT ac.column_name) > 10
    ORDER BY total_columns DESC
    """


def build_policy_coverage_sql() -> str:
    """SQL to assess masking and row access policy coverage."""
    return """
    SELECT
        policy_catalog AS database_name,
        policy_schema AS schema_name,
        policy_name,
        policy_kind,
        ref_database_name,
        ref_schema_name,
        ref_entity_name AS table_name,
        ref_column_name AS column_name
    FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES
    WHERE deleted IS NULL
    ORDER BY policy_kind, ref_database_name, ref_entity_name
    """


def build_access_history_availability_sql(days_back: int = 7) -> str:
    """SQL to verify access history is populating correctly."""
    days_back = max(1, int(days_back or 7))
    return f"""
    SELECT
        DATE(query_start_time) AS access_date,
        COUNT(*) AS access_records,
        COUNT(DISTINCT user_name) AS unique_users,
        COUNT(DISTINCT ARRAY_SIZE(direct_objects_accessed)) AS object_diversity
    FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
    WHERE query_start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
    GROUP BY access_date
    ORDER BY access_date DESC
    """


def build_governance_readiness_scorecard(
    classification_df=None,
    policy_df=None,
    access_history_df=None,
) -> dict[str, Any]:
    """Build a governance readiness scorecard."""
    import pandas as pd

    scorecard = {
        "overall_score": 50,
        "classification_pct": 0.0,
        "policy_count": 0,
        "access_history_days": 0,
        "readiness_level": "Not Assessed",
        "gaps": [],
        "strengths": [],
    }

    # Classification coverage
    if isinstance(classification_df, pd.DataFrame) and not classification_df.empty:
        if "CLASSIFICATION_PCT" in classification_df.columns:
            avg_pct = float(classification_df["CLASSIFICATION_PCT"].mean())
            scorecard["classification_pct"] = round(avg_pct, 1)
            if avg_pct >= 80:
                scorecard["overall_score"] += 20
                scorecard["strengths"].append(f"Strong classification coverage: {avg_pct:.0f}%")
            elif avg_pct >= 40:
                scorecard["overall_score"] += 10
                scorecard["gaps"].append(f"Classification coverage at {avg_pct:.0f}% — target 80%+")
            else:
                scorecard["gaps"].append(f"Low classification: only {avg_pct:.0f}% of columns tagged")

    # Policy coverage
    if isinstance(policy_df, pd.DataFrame) and not policy_df.empty:
        scorecard["policy_count"] = len(policy_df)
        masking = len(policy_df[policy_df["POLICY_KIND"].str.upper() == "MASKING_POLICY"]) if "POLICY_KIND" in policy_df.columns else 0
        row_access = len(policy_df[policy_df["POLICY_KIND"].str.upper() == "ROW_ACCESS_POLICY"]) if "POLICY_KIND" in policy_df.columns else 0
        if masking > 0:
            scorecard["overall_score"] += 10
            scorecard["strengths"].append(f"{masking} masking policies deployed")
        else:
            scorecard["gaps"].append("No masking policies found — sensitive columns may be exposed")
        if row_access > 0:
            scorecard["overall_score"] += 10
            scorecard["strengths"].append(f"{row_access} row access policies deployed")

    # Access history
    if isinstance(access_history_df, pd.DataFrame) and not access_history_df.empty:
        scorecard["access_history_days"] = len(access_history_df)
        if len(access_history_df) >= 5:
            scorecard["overall_score"] += 10
            scorecard["strengths"].append("Access history is populating correctly")
        else:
            scorecard["gaps"].append("Access history has gaps — verify Enterprise Edition feature is enabled")

    # Clamp and classify
    scorecard["overall_score"] = max(0, min(100, scorecard["overall_score"]))
    if scorecard["overall_score"] >= 80:
        scorecard["readiness_level"] = "Audit Ready"
    elif scorecard["overall_score"] >= 60:
        scorecard["readiness_level"] = "Progressing"
    elif scorecard["overall_score"] >= 40:
        scorecard["readiness_level"] = "Gaps Identified"
    else:
        scorecard["readiness_level"] = "Not Ready"

    return scorecard
