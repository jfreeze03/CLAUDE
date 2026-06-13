# utils/security_hardening.py - Security hardening utilities
"""
Centralizes all security-sensitive operations:
  - Parameterized query helpers (no string interpolation)
  - CSP header injection for Streamlit
  - Input sanitization
  - SQL injection prevention patterns
  - Safe identifier validation
"""
from __future__ import annotations

import re
from typing import Any

import streamlit as st


# ─── Parameterized query helpers ─────────────────────────────────────────────

def safe_date(value: str) -> str:
    """Validate and return a safe SQL date expression. Never interpolate raw dates."""
    clean = str(value).strip()[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", clean):
        return f"TO_DATE('{clean}', 'YYYY-MM-DD')"
    return "CURRENT_DATE()"


def safe_int_param(value, *, min_val: int = 0, max_val: int = 365) -> int:
    """Validate an integer parameter within bounds."""
    try:
        v = int(value)
        return max(min_val, min(max_val, v))
    except (TypeError, ValueError):
        return min_val


def safe_identifier(name: str, *, max_length: int = 255) -> str:
    """Validate a Snowflake identifier. Strips dangerous characters."""
    clean = re.sub(r'[^A-Za-z0-9_.$]', '', str(name or ""))
    return clean[:max_length]


def safe_string_literal(value: str, *, max_length: int = 4000) -> str:
    """Escape a string for use in SQL single quotes."""
    clean = str(value or "")[:max_length]
    return clean.replace("'", "''")


def safe_warehouse_name(name: str) -> str:
    """Validate a warehouse name for ALTER statements."""
    clean = re.sub(r'[^A-Za-z0-9_]', '', str(name or ""))
    if not clean:
        raise ValueError("Invalid warehouse name")
    return clean


# ─── CSP headers ─────────────────────────────────────────────────────────────

def inject_csp_headers() -> None:
    """Inject Content Security Policy meta tags to prevent XSS in HTML content."""
    st.markdown(
        '<meta http-equiv="Content-Security-Policy" content="'
        "default-src 'self'; "
        "script-src 'none'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'"
        '">',
        unsafe_allow_html=True,
    )


# ─── HTML sanitization ───────────────────────────────────────────────────────

_ALLOWED_TAGS = {"div", "span", "strong", "em", "br", "p", "ul", "ol", "li", "a", "code", "pre"}


def sanitize_html(content: str) -> str:
    """Strip potentially dangerous HTML tags while keeping safe ones."""
    import html as html_mod

    # First escape everything
    escaped = html_mod.escape(str(content))

    # Then selectively un-escape allowed tags
    for tag in _ALLOWED_TAGS:
        escaped = escaped.replace(f"&lt;{tag}&gt;", f"<{tag}>")
        escaped = escaped.replace(f"&lt;/{tag}&gt;", f"</{tag}>")
        escaped = escaped.replace(f"&lt;{tag} ", f"<{tag} ")

    return escaped


# ─── Query safety validation ─────────────────────────────────────────────────

_DANGEROUS_PATTERNS = [
    r";\s*(DROP|DELETE|TRUNCATE|ALTER\s+ACCOUNT|CREATE\s+USER)",
    r"EXECUTE\s+AS\s+",
    r"INTO\s+OUTFILE",
    r"LOAD\s+DATA",
]


def validate_query_safety(sql: str) -> tuple[bool, str]:
    """
    Validate that a query doesn't contain dangerous patterns.

    Returns:
        (is_safe, reason)
    """
    sql_upper = str(sql).upper()

    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, sql_upper, re.IGNORECASE):
            return False, f"Blocked: query matches dangerous pattern '{pattern}'"

    # Check for multiple statements (semicolons)
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        return False, "Blocked: multiple statements detected"

    return True, "OK"


# ─── Rate limiting decorator ─────────────────────────────────────────────────

def rate_limited(key: str, cooldown_sec: int = 10):
    """Decorator/helper to rate-limit expensive operations."""
    from datetime import datetime

    last_key = f"_rate_limit_{key}"
    last_call = st.session_state.get(last_key)

    if last_call:
        elapsed = (datetime.now() - last_call).total_seconds()
        if elapsed < cooldown_sec:
            return False  # Rate limited

    st.session_state[last_key] = datetime.now()
    return True  # OK to proceed
