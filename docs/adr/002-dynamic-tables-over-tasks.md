# ADR-002: Dynamic Tables Over Scheduled Tasks

## Status: Accepted

## Context
The original architecture used hourly Snowflake Tasks to refresh mart tables. This required task management, failure monitoring, and manual scheduling alignment with ACCOUNT_USAGE latency.

## Decision
Migrate core aggregations to Dynamic Tables with TARGET_LAG. The app reads from views (V_OVERWATCH_*) that point to DTs. Nightly Tasks remain only for derived analytics that require procedural logic.

## Consequences
- **Pro**: Automatic refresh without task scheduling complexity
- **Pro**: Guaranteed freshness (TARGET_LAG enforced by Snowflake)
- **Pro**: Serverless compute (no warehouse reserved for refresh)
- **Con**: Requires Enterprise Edition
- **Con**: Cannot use procedural logic (stored proc patterns) in DTs
- **Mitigation**: Views abstract the DT dependency; fallback to live queries when DTs aren't deployed
