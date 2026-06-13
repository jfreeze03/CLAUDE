# ADR-004: Least Privilege Role Defaults

## Status: Accepted

## Context
The original app defaulted unknown roles to "DBA" (full access). This meant any misconfigured role or new connection got maximum navigation access and admin capabilities.

## Decision
Unknown roles default to ANALYST (read-only navigation). Admin actions require explicit enable via `admin_actions_enabled()`. Only SNOW_ACCOUNTADMINS, SNOW_SYSADMINS, and ACCOUNTADMIN get admin mode by default.

## Consequences
- **Pro**: Security incident from misconfigured roles is prevented
- **Pro**: New users see a safe subset until explicitly promoted
- **Con**: DBAs with non-standard role names must be added to ROLE_PROFILE_OVERRIDES
- **Mitigation**: Pattern matching (role names ending in _DSA, _DTI, etc.) catches most cases
