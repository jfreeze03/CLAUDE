# OVERWATCH — Snowflake DBA Command Center

A production-grade Streamlit-in-Snowflake (SiS) application for Snowflake platform operations, FinOps, governance, and executive visibility.

## What It Does

OVERWATCH provides a unified operations surface for Snowflake DBAs, FinOps teams, and executives:

- **Platform Health Score** — Single 0-100 composite KPI combining cost, reliability, security, and operational readiness
- **Cost & Contract** — Bill attribution, contract burn forecast, anomaly detection, chargeback allocation, Cortex Code spend tracking
- **DBA Control Room** — Live task graphs, failure triage, self-healing playbooks, operational runbooks
- **Workload Operations** — Task SLA compliance, pipeline freshness, query diagnosis, execute/kill controls
- **Warehouse Health** — Dynamic settings management (resize/suspend), optimization advisor, capacity planning
- **Security Posture** — Compliance evidence, privilege escalation detection, dormant user tracking
- **Change & Drift** — DDL change tracking, impact scoring, AI-assisted change governance
- **Architecture Readiness** — DR drill tracking, forward platform governance (Cortex Agents, MCP, Adaptive Compute)
- **Alert Center** — Alert age tracking, resolution SLA, scheduled delivery via email/Teams
- **Ask OVERWATCH** — Natural language Q&A powered by Snowflake Cortex COMPLETE

## Quick Start

### Deploy to Snowflake

```bash
# 1. Run the consolidated DDL (as ACCOUNTADMIN)
snowsql -f snowflake/DEPLOY.sql

# 2. Deploy the Streamlit app
snow streamlit deploy --replace
```

### Run Locally (development)

```bash
# Install dependencies
pip install streamlit pandas altair snowflake-snowpark-python

# Configure connection in .streamlit/secrets.toml
# [connections.snowflake]
# account = "your_account"
# user = "your_user"
# password = "your_password"
# role = "OVERWATCH_APP_ROLE"
# warehouse = "OVERWATCH_WH"
# database = "DBA_MAINT_DB"
# schema = "OVERWATCH"

streamlit run app.py
```

### Run Tests

```bash
pip install pytest
pytest tests/ -v
```

### Pre-deployment Validation

```bash
python scripts/validate_deployment.py
```

## Architecture

```
OVERWATCH_CODEX/
├── app.py                    # Main entry point and navigation
├── config.py                 # Centralized configuration
├── theme.py                  # CSS theme system (3 themes)
├── snowflake/DEPLOY.sql      # Consolidated Snowflake DDL
├── sections/                 # UI section shells and workspaces
│   ├── *_shell.py            # Data-first landing pages (10 shells)
│   └── *.py                  # Full workspace implementations
├── utils/                    # 61 utility modules
│   ├── perf.py               # Performance optimizations
│   ├── health_score.py       # Platform Health Score
│   ├── contract_forecast.py  # Predictive burn forecasting
│   ├── anomaly_detection.py  # Statistical anomaly detection
│   ├── self_healing.py       # Automated playbook engine
│   ├── task_controls.py      # Live task execute/kill
│   ├── warehouse_controls.py # Dynamic warehouse management
│   └── ...
├── tests/                    # 24 test files, 115+ tests
├── scripts/                  # Deployment validation
└── .github/workflows/        # CI/CD pipeline
```

## Key Design Decisions

- **Data-first shells** — Every section shows real metrics immediately when evidence is loaded. No "click here to see data" blank pages.
- **Zero-query on navigation** — Switching sections never triggers a Snowflake query. Data loads only on explicit user action.
- **Pre-computed metrics** — Shell KPIs read cached scalars, not re-scan DataFrames on every Streamlit rerun.
- **Tiered caching** — live (30s), recent (5min), historical (30min), metadata (4h) TTLs match Snowflake data latency.
- **Least privilege** — Unknown roles default to ANALYST (read-only). Admin actions require explicit gate.
- **Multi-rate pricing** — Compute, serverless, and AI/Cortex credits use different $/credit rates.

## Roles

| Role | Access |
|------|--------|
| OVERWATCH_APP_ROLE | Runtime: read monitoring, write action queue |
| OVERWATCH_ADMIN_ROLE | Full mart management, task ownership |
| OVERWATCH_READER_ROLE | Read-only dashboard access |

## Configuration

Key settings are in the sidebar Settings panel:
- Credit price ($/credit for compute)
- AI credit price ($/credit for Cortex)
- Storage cost ($/TB/month)
- Contract capacity (total + remaining credits)
- Alert email recipients
- Theme selection (Snowflake Dark, Snowflake White, Henson)

## License

Internal use — ALFA Insurance.
