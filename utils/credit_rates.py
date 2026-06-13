# utils/credit_rates.py - Multi-rate credit pricing for accurate dollarization
"""
Enterprise Snowflake contracts have different rates per service type:
  - Standard compute: $3.00-$4.00/credit
  - Serverless tasks/pipes: different rate
  - AI/Cortex: $2.20/credit (token-based)
  - Storage: $/TB/month
  - Data transfer: varies

This module applies the correct rate per service type instead of
assuming a flat $/credit across all consumption.
"""
from __future__ import annotations

from typing import Any

import streamlit as st
from config import DEFAULTS


# Default rate structure (override from Settings or OVERWATCH_SETTINGS table)
DEFAULT_RATE_TABLE: dict[str, float] = {
    "WAREHOUSE_METERING": DEFAULTS["credit_price"],
    "COMPUTE": DEFAULTS["credit_price"],
    "AUTOMATIC_CLUSTERING": DEFAULTS["credit_price"],
    "MATERIALIZED_VIEW": DEFAULTS["credit_price"],
    "SEARCH_OPTIMIZATION": DEFAULTS["credit_price"],
    "QUERY_ACCELERATION": DEFAULTS["credit_price"],
    "SERVERLESS_TASK": DEFAULTS["credit_price"],
    "SNOWPIPE": DEFAULTS["credit_price"],
    "SNOWPIPE_STREAMING": DEFAULTS["credit_price"],
    "REPLICATION": DEFAULTS["credit_price"],
    "SNOWPARK_CONTAINER_SERVICES": DEFAULTS["credit_price"],
    "CORTEX": DEFAULTS["ai_credit_price"],
    "AI": DEFAULTS["ai_credit_price"],
    "INTELLIGENCE": DEFAULTS["ai_credit_price"],
    "DATA_TRANSFER": 0.0,  # Billed separately, not credit-based
    "STORAGE": 0.0,  # Billed per TB, not credit-based
}

# Service type categories for grouping
SERVICE_CATEGORIES: dict[str, str] = {
    "WAREHOUSE_METERING": "Compute",
    "AUTOMATIC_CLUSTERING": "Serverless",
    "MATERIALIZED_VIEW": "Serverless",
    "SEARCH_OPTIMIZATION": "Serverless",
    "QUERY_ACCELERATION": "Serverless",
    "SERVERLESS_TASK": "Serverless",
    "SNOWPIPE": "Serverless",
    "SNOWPIPE_STREAMING": "Serverless",
    "SNOWPARK_CONTAINER_SERVICES": "Containers",
    "REPLICATION": "Replication",
    "CORTEX": "AI / Cortex",
    "AI": "AI / Cortex",
    "INTELLIGENCE": "AI / Cortex",
}


def get_rate_table() -> dict[str, float]:
    """Return the current multi-rate pricing table from session state or defaults."""
    custom_rates = st.session_state.get("_credit_rate_table")
    if isinstance(custom_rates, dict) and custom_rates:
        merged = dict(DEFAULT_RATE_TABLE)
        merged.update(custom_rates)
        return merged

    # Apply current session settings over defaults
    compute_rate = float(st.session_state.get("credit_price", DEFAULTS["credit_price"]))
    ai_rate = float(st.session_state.get("ai_credit_price", DEFAULTS["ai_credit_price"]))

    rates = dict(DEFAULT_RATE_TABLE)
    for key in rates:
        if key in ("CORTEX", "AI", "INTELLIGENCE"):
            rates[key] = ai_rate
        elif rates[key] == DEFAULTS["credit_price"]:
            rates[key] = compute_rate

    return rates


def get_rate_for_service(service_type: str) -> float:
    """Return the credit rate for a specific Snowflake service type."""
    rates = get_rate_table()
    service_upper = str(service_type or "").upper().strip()

    # Direct match
    if service_upper in rates:
        return rates[service_upper]

    # Partial match
    for key, rate in rates.items():
        if key in service_upper or service_upper in key:
            return rate

    # AI/Cortex keyword match
    if any(kw in service_upper for kw in ("CORTEX", "AI", "INTELLIGENCE", "TOKEN")):
        return float(st.session_state.get("ai_credit_price", DEFAULTS["ai_credit_price"]))

    # Default to compute rate
    return float(st.session_state.get("credit_price", DEFAULTS["credit_price"]))


def get_service_category(service_type: str) -> str:
    """Return the display category for a service type."""
    service_upper = str(service_type or "").upper().strip()

    if service_upper in SERVICE_CATEGORIES:
        return SERVICE_CATEGORIES[service_upper]

    if any(kw in service_upper for kw in ("CORTEX", "AI", "INTELLIGENCE")):
        return "AI / Cortex"
    if any(kw in service_upper for kw in ("STORAGE",)):
        return "Storage"
    if any(kw in service_upper for kw in ("TRANSFER", "PRIVATELINK")):
        return "Network"
    if any(kw in service_upper for kw in ("WAREHOUSE",)):
        return "Compute"

    return "Other"


def credits_to_dollars_multi_rate(
    credits: float,
    service_type: str = "COMPUTE",
) -> float:
    """Convert credits to dollars using the service-specific rate."""
    rate = get_rate_for_service(service_type)
    return round(float(credits or 0) * rate, 2)


def dollarize_dataframe(df, credit_column: str, service_type_column: str = None):
    """Add a _COST_USD column using multi-rate pricing.

    If service_type_column is provided, uses per-row rates.
    Otherwise uses the default compute rate.
    """
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if credit_column not in df.columns:
        return df

    frame = df.copy()
    cost_col = f"{credit_column}_COST_USD"

    if service_type_column and service_type_column in frame.columns:
        # Per-row rate lookup
        frame[cost_col] = frame.apply(
            lambda row: credits_to_dollars_multi_rate(
                float(row.get(credit_column, 0) or 0),
                str(row.get(service_type_column, "COMPUTE") or "COMPUTE"),
            ),
            axis=1,
        )
    else:
        # Uniform rate
        rate = float(st.session_state.get("credit_price", DEFAULTS["credit_price"]))
        credits = pd.to_numeric(frame[credit_column], errors="coerce").fillna(0)
        frame[cost_col] = (credits * rate).round(2)

    # Insert after the credit column
    cols = list(frame.columns)
    if cost_col in cols:
        cols.remove(cost_col)
        insert_at = cols.index(credit_column) + 1
        cols.insert(insert_at, cost_col)
        frame = frame[cols]

    return frame


def build_rate_summary() -> dict[str, Any]:
    """Return the current rate configuration for display."""
    rates = get_rate_table()
    compute_rate = rates.get("WAREHOUSE_METERING", DEFAULTS["credit_price"])
    ai_rate = rates.get("CORTEX", DEFAULTS["ai_credit_price"])

    unique_rates = sorted(set(v for v in rates.values() if v > 0))

    return {
        "compute_rate": compute_rate,
        "ai_rate": ai_rate,
        "storage_rate_per_tb": float(st.session_state.get("storage_cost_per_tb", DEFAULTS["storage_cost_per_tb"])),
        "unique_rates": unique_rates,
        "is_multi_rate": len(unique_rates) > 1,
        "rate_table": {k: v for k, v in rates.items() if v > 0},
    }
