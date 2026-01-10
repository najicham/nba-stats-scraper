# Registry System Fix Project

**Date Started:** 2026-01-10
**Status:** In Progress
**Priority:** Critical

## Problem Statement

The player name registry system was not functioning properly:
- 2,099 names stuck in "pending" status since October 2025
- AI resolver never being called automatically
- Registry not being updated
- No automation for name resolution

## Root Cause

The system design was sound, but **operational gaps** existed:
1. AI resolver existed but was never triggered automatically
2. No Cloud Scheduler jobs for registry updates
3. Cache lookup not integrated into main resolver flow

## Changes Made

### 1. Batch AI Resolution (Completed)
- Ran `tools/player_registry/resolve_unresolved_batch.py`
- Processed 142 pending names
- Created 32 new aliases
- Total cost: $0.014 (~1.4 cents)

**Result:** All 2,816 unresolved names now resolved (2 snoozed)

### 2. Cache Lookup Integration (Completed)
**File:** `shared/utils/player_name_resolver.py`

Added cache lookup to `handle_player_name()` method:
- After alias/registry lookup fails
- Checks AI resolution cache for prior MATCH decisions
- Auto-creates alias on cache hit
- Returns resolved name immediately

```python
# New flow in handle_player_name():
# 1. Try alias resolution
# 2. Validate against registry
# 3. Check AI resolution cache  <-- NEW
# 4. If cache hit with MATCH -> create alias, return resolved name
# 5. If cache miss -> add to unresolved queue, return None
```

### 3. Reprocessing Tool Bug (Needs Fix)
**File:** `tools/player_registry/reprocess_resolved.py`

The tool references a non-existent table `nba_raw.game_boxscores`. Should use:
- `nba_raw.bdl_player_boxscores` or
- `nba_raw.nbac_player_boxscores`

### 4. Automation (Pending)
Need to add Cloud Scheduler jobs for:
- Nightly AI resolution (4:30 AM ET)
- Nightly reprocessing (5:00 AM ET)

## Current State

### Registry Failures by Season
| Season | Total Failures | Resolved | Reprocessed |
|--------|---------------|----------|-------------|
| 2021-22 | 121 | 0 | 0 |
| 2022-23 | 256 | 6 | 0 |
| 2023-24 | 139 | 0 | 0 |
| 2024-25 | 395 | 0 | 0 |
| 2025-26 | 3,364 | 2,132 | 0 |

### What Happens Now (After Cache Integration)

**Scenario: Morning roster processing encounters unknown name**

1. `handle_player_name("T.J. McConnell", "espn", {...})` called
2. Alias lookup: Not found (no alias yet)
3. Registry check: Not found (name variant)
4. **NEW: Cache check**:
   - If cached MATCH exists: Create alias, return resolved name
   - If no cache: Add to unresolved queue, return None
5. Analytics processor records failure to `registry_failures` table

**Scenario: Same name encountered again (after AI batch ran)**

1. `handle_player_name("T.J. McConnell", ...)` called
2. Alias lookup: FOUND (created by cache lookup or AI batch)
3. Return resolved name immediately

## How Resolution Works End-to-End

```
Player name from data source
        |
        v
handle_player_name()
        |
        +---> Alias lookup -----> FOUND? ---> Return resolved name
        |
        +---> Registry check ---> VALID? ---> Return name
        |
        +---> Cache lookup ------> MATCH? ---> Create alias, return resolved
        |
        v
Add to unresolved_player_names (status='pending')
Add to registry_failures
Return None (processor handles failure)
        |
        v
[Nightly Batch]
resolve_unresolved_batch.py
        |
        +---> AI resolver calls Claude API
        +---> Creates aliases for MATCH decisions
        +---> Caches all decisions
        +---> Marks failures as resolved
        |
        v
[Next Processing Cycle]
        |
        +---> Alias lookup now finds the name
        +---> OR cache lookup finds MATCH decision
        |
        v
Name resolution succeeds!
```

## Automation Added

### Cloud Scheduler Jobs

Created script: `bin/orchestration/add_registry_scheduler_jobs.sh`

| Job | Schedule | Endpoint | Purpose |
|-----|----------|----------|---------|
| `registry-ai-resolution` | 4:30 AM ET | `/resolve-pending` | Nightly AI resolution of pending names |
| `registry-health-check` | 5:00 AM ET | `/health-check` | Daily health check with alerts |

### Reference Service Endpoints Added

**POST /resolve-pending**
- Runs AI batch resolution on pending unresolved names
- Optional params: `limit`, `dry_run`
- Sends error notifications on failure

**POST|GET /health-check**
- Runs full health check
- Sends CRITICAL/WARNING alerts based on status
- Returns metrics on pending names, resolution rate, etc.

## Remaining Work

1. **Process older seasons** - 911 failures from 2021-2024 seasons need aliases
2. **Deploy reference service** - Service needs to be deployed to Cloud Run
3. **Run scheduler setup** - After deployment, run `add_registry_scheduler_jobs.sh`

## Files Modified

| File | Change |
|------|--------|
| `shared/utils/player_name_resolver.py` | Added cache lookup + auto-alias creation |
| `tools/player_registry/reprocess_resolved.py` | Fixed table reference (game_boxscores → bdl_player_boxscores) |
| `data_processors/reference/main_reference_service.py` | Added /resolve-pending and /health-check endpoints |
| `bin/orchestration/add_registry_scheduler_jobs.sh` | New script for Cloud Scheduler setup |
| `shared/utils/tests/test_player_name_resolver.py` | New unit tests for cache lookup |

## Related Documentation

- `/docs/06-reference/player-registry.md` - Registry system reference
- `/docs/02-operations/runbooks/observability/registry-failures.md` - Failure monitoring
- `/docs/02-operations/backfill/runbooks/name-resolution.md` - Name resolution backfill guide
