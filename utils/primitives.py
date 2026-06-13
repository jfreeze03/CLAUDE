# utils/primitives.py - Canonical type conversion and validation primitives
"""
SINGLE SOURCE OF TRUTH for safe type conversion.
All sections must import from here — no local copies.

Usage:
    from utils.primitives import safe_float, safe_int, safe_str, safe_bool
"""
from __future__ import annotations

import pandas as pd


def safe_float(value, default: float = 0.0) -> float:
    """Convert any value to float safely. Handles None, NaN, strings."""
    try:
        if value is None:
            return default
        if isinstance(value, float) and value != value:  # NaN
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    """Convert any value to int safely."""
    try:
        if value is None:
            return default
        if isinstance(value, float) and value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_str(value, default: str = "") -> str:
    """Convert any value to str safely, stripping whitespace."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text and text.upper() not in ("NONE", "NAN", "NULL", "<NA>") else default


def safe_bool(value, default: bool = False) -> bool:
    """Convert any value to bool safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return default


def safe_strip_tz(series: pd.Series) -> pd.Series:
    """Strip timezone from a datetime series for display."""
    try:
        if hasattr(series.dt, "tz") and series.dt.tz is not None:
            return series.dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return series


def coerce_numeric(series: pd.Series, default: float = 0.0) -> pd.Series:
    """Coerce a series to numeric, filling NaN with default."""
    return pd.to_numeric(series, errors="coerce").fillna(default)
