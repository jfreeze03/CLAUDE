# ADR-003: Multi-Rate Credit Pricing

## Status: Accepted

## Context
Enterprise Snowflake contracts have different rates per service type (compute: $3.68, AI/Cortex: $2.20, serverless varies). Using a flat $/credit produces inaccurate cost displays for accounts with significant AI or serverless consumption.

## Decision
Implement a rate table (utils/credit_rates.py) that applies the correct rate per service type. The existing `credits_to_dollars()` accepts an optional `service_type` parameter and routes to multi-rate when available.

## Consequences
- **Pro**: Accurate cost display across all service types
- **Pro**: Backward compatible (flat rate still works when service_type is omitted)
- **Con**: Requires users to configure AI credit price in Settings
- **Con**: Chargeback reports must specify which rate was applied
- **Mitigation**: Default rates match common contract structures
