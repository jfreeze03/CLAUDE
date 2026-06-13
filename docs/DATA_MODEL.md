# OVERWATCH Data Model

## Entity Relationship Diagram

```mermaid
erDiagram
    OVERWATCH_SETTINGS ||--o{ OVERWATCH_SCHEMA_MIGRATION : configures
    OVERWATCH_COMPANY_SCOPE ||--o{ OVERWATCH_OWNER_DIRECTORY : scopes
    OVERWATCH_OWNER_DIRECTORY ||--o{ OVERWATCH_ACTION_QUEUE : routes
    OVERWATCH_ACTION_QUEUE ||--o{ OVERWATCH_COST_SAVINGS_VERIFICATION_RUN : verifies
    OVERWATCH_ACTION_QUEUE ||--o{ OVERWATCH_WORKLOAD_RECOVERY_AUDIT : tracks
    OVERWATCH_ALERTS ||--o{ OVERWATCH_ADMIN_ACTION_AUDIT : audits
    OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER ||--o{ OVERWATCH_PLATFORM_FUTURES_EVIDENCE : governs

    OVERWATCH_SETTINGS {
        varchar SETTING_NAME PK
        varchar SETTING_VALUE
        varchar SETTING_TYPE
        timestamp UPDATED_AT
    }

    OVERWATCH_COMPANY_SCOPE {
        varchar COMPANY
        varchar SCOPE_TYPE
        varchar SCOPE_PATTERN
        varchar MATCH_MODE
        boolean IS_ACTIVE
    }

    OVERWATCH_OWNER_DIRECTORY {
        varchar OWNER_KEY PK
        varchar ENTITY_TYPE
        varchar ENTITY_PATTERN
        varchar OWNER_NAME
        varchar SERVICE_TIER
        number MATCH_PRIORITY
    }

    OVERWATCH_ACTION_QUEUE {
        varchar ACTION_ID PK
        varchar SOURCE
        varchar CATEGORY
        varchar SEVERITY
        varchar ENTITY_NAME
        varchar OWNER
        varchar STATUS
        float EST_MONTHLY_SAVINGS
        varchar VERIFICATION_STATUS
    }

    OVERWATCH_ALERTS {
        number ALERT_ID PK
        varchar SEVERITY
        varchar STATUS
        varchar ENTITY_NAME
        timestamp CREATED_AT
        timestamp RESOLVED_AT
    }

    OVERWATCH_ADMIN_ACTION_AUDIT {
        number ACTION_ID PK
        varchar ACTION_TYPE
        varchar TARGET_OBJECT
        varchar SQL_TEXT
        varchar RESULT_STATUS
        timestamp ACTION_TS
    }

    OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER {
        varchar CONTROL_ID PK
        varchar CONTROL_AREA
        varchar OWNER
        varchar DBA_DECISION
        varchar AUTOMATION_BOUNDARY
    }

    OVERWATCH_PLATFORM_FUTURES_EVIDENCE {
        number EVIDENCE_ID PK
        varchar CONTROL_ID
        varchar ENTITY_NAME
        varchar SEVERITY
        varchar APPROVAL_STATUS
    }

    OVERWATCH_COST_SAVINGS_VERIFICATION_RUN {
        number RUN_ID PK
        varchar ACTION_ID
        float BASELINE_VALUE
        float POST_PERIOD_VALUE
        varchar VERIFICATION_OUTCOME
    }

    OVERWATCH_WORKLOAD_RECOVERY_AUDIT {
        number RECOVERY_AUDIT_ID PK
        varchar ACTION_ID
        varchar ENTITY_NAME
        varchar RECOVERY_SLA_STATE
        varchar ACTION_TAKEN
    }
```

## Dynamic Tables (Pre-computation Layer)

| Dynamic Table | Source | Lag | Purpose |
|--------------|--------|-----|---------|
| DT_DAILY_CREDITS | WAREHOUSE_METERING_HISTORY | 1h | Daily cost per warehouse |
| DT_HOURLY_PRESSURE | WAREHOUSE_METERING_HISTORY | 30min | Hourly warehouse utilization |
| DT_TASK_SUMMARY | TASK_HISTORY | 1h | Task success/failure rollup |
| DT_SERVICE_COSTS | METERING_HISTORY | 2h | All service type costs |
| DT_QUERY_BOTTLENECKS | QUERY_HISTORY | 1h | p95 latency, spill, queue |
| DT_STORAGE_TREND | STORAGE_USAGE | 6h | Storage growth over 90 days |

## App-Facing Views

All app queries should read from `V_OVERWATCH_*` views, which abstract
whether the underlying data comes from Dynamic Tables (when deployed)
or live ACCOUNT_USAGE queries (fallback).

## Data Flow

```
SNOWFLAKE.ACCOUNT_USAGE (raw) 
    → Dynamic Tables (pre-aggregated, 30min-6h lag)
        → V_OVERWATCH_* views (stable interface)
            → utils/query.py run_query() (tiered caching)
                → Shell pre-computed metrics (scalars in session state)
                    → UI rendering (instant, no DB access)
```
