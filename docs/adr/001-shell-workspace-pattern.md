# ADR-001: Shell/Workspace Progressive Disclosure Pattern

## Status: Accepted

## Context
Streamlit reruns the entire script on every interaction. Loading all section data on navigation would cause expensive queries and slow page transitions.

## Decision
Separate each section into a lightweight shell (zero-query, pre-computed KPIs) and a full workspace (query-on-demand). The shell shows cached metrics immediately; the workspace loads only when the user explicitly clicks "Open."

## Consequences
- **Pro**: Instant page navigation, zero unnecessary queries
- **Pro**: Shell KPIs update from cached metrics without DB access
- **Con**: Users must click to see detailed data (one extra interaction)
- **Con**: Two files per section (shell + workspace) doubles file count
- **Mitigation**: Pre-computed metrics reduce the "blank shell" problem
