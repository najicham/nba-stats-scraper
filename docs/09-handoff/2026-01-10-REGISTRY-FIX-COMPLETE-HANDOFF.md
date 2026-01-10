# Registry System Fix - Complete Handoff

**Date:** 2026-01-10
**Session Type:** Implementation
**Status:** Complete (pending deployment)

---

## What Was Done

### Problem Solved
The player name registry system was broken since October 2025:
- 2,099 names stuck in "pending" status
- AI resolver existed but was never called automatically
- No automation for name resolution
- New names encountered during processing would miss Phase 3/4/5 data

### Changes Implemented

#### 1. Batch AI Resolution
- Ran `tools/player_registry/resolve_unresolved_batch.py` on all 2,099 pending names
- Created 32 new aliases for name variations (e.g., `t.j.mcconnell` → `tjmcconnell`)
- Total API cost: $0.014 (~1.4 cents using Claude Haiku)
- All 2,816 unresolved names now have status='resolved'

#### 2. Cache Lookup Integration
**File:** `shared/utils/player_name_resolver.py`

Added Step 3 to `handle_player_name()` method:
```python
# New flow:
# 1. Try alias resolution
# 2. Validate against registry
# 3. Check AI resolution cache  <-- NEW
# 4. If cache hit with MATCH -> auto-create alias, return resolved name
# 5. If cache miss -> add to unresolved queue, return None
```

This means: once AI resolves a name, subsequent encounters use the cached decision immediately (no waiting for nightly batch).

#### 3. Reprocessing Tool Fix
**File:** `tools/player_registry/reprocess_resolved.py`

Fixed wrong table reference:
- Before: `nba_raw.game_boxscores` (doesn't exist)
- After: `nba_raw.bdl_player_boxscores`

#### 4. Automation Endpoints
**File:** `data_processors/reference/main_reference_service.py`

Added two new endpoints:
- `POST /resolve-pending` - Runs AI batch resolution
- `POST|GET /health-check` - Runs health check with alerts

#### 5. Cloud Scheduler Script
**File:** `bin/orchestration/add_registry_scheduler_jobs.sh`

Creates scheduled jobs:
| Job | Schedule | Purpose |
|-----|----------|---------|
| `registry-ai-resolution` | 4:30 AM ET | Nightly AI resolution |
| `registry-health-check` | 5:00 AM ET | Daily health check |

#### 6. Unit Tests
**File:** `shared/utils/tests/test_player_name_resolver.py`

6 tests covering:
- Cache hit with MATCH creates alias
- Cache hit with DATA_ERROR doesn't create alias
- Cache miss adds to unresolved queue
- Cache initialization failure disables cache gracefully
- Basic alias resolution

---

## Current State

### Unresolved Names
```
resolved: 2,816
snoozed: 2
pending: 0  ← All cleared!
```

### Registry Failures by Season
| Season | Total Failures | Resolved | Reprocessed |
|--------|---------------|----------|-------------|
| 2021-22 | 121 | 0 | 0 |
| 2022-23 | 256 | 6 | 0 |
| 2023-24 | 139 | 0 | 0 |
| 2024-25 | 395 | 0 | 0 |
| 2025-26 | 3,364 | 2,132 | 0 |

Note: Older seasons have failures without aliases - need separate AI batch run.

---

## How Name Resolution Works Now

```
Player name from data source (ESPN, BDL, etc.)
        ↓
handle_player_name()
        ↓
1. Alias lookup ────────→ FOUND? → Return resolved name
        ↓
2. Registry check ──────→ VALID? → Return name
        ↓
3. AI Cache lookup ─────→ MATCH? → Create alias, return resolved name
        ↓
4. Add to unresolved queue, return None
        ↓
[Nightly at 4:30 AM]
AI batch resolver runs → Creates aliases → Caches decisions
        ↓
[Next processing cycle]
Step 1 or 3 finds the name → Success!
```

---

## Files Changed (Committed)

| File | Change |
|------|--------|
| `shared/utils/player_name_resolver.py` | +88 lines - Cache lookup integration |
| `tools/player_registry/reprocess_resolved.py` | +8/-8 lines - Table reference fix |
| `data_processors/reference/main_reference_service.py` | +120 lines - New endpoints |
| `bin/orchestration/add_registry_scheduler_jobs.sh` | New file - Scheduler setup |
| `shared/utils/tests/test_player_name_resolver.py` | New file - Unit tests |
| `docs/08-projects/current/registry-system-fix/README.md` | New file - Documentation |

**Commit:** `174c33d`

---

## Remaining Work

### 1. Deploy Reference Service
The reference service needs to be deployed to Cloud Run with the new endpoints.

### 2. Run Scheduler Setup
After deployment:
```bash
./bin/orchestration/add_registry_scheduler_jobs.sh
```

### 3. Process Older Seasons (Optional)
911 failures from 2021-2024 seasons need AI resolution:
```bash
# Check what's pending in older seasons
python -c "
from google.cloud import bigquery
client = bigquery.Client()
# Query registry_failures for unresolved older season entries
"

# May need to run batch resolver with specific filters
```

### 4. Run Reprocessing (Optional)
To update analytics for games that had unresolved names:
```bash
python tools/player_registry/reprocess_resolved.py --resolved-since 2025-10-01 --dry-run
python tools/player_registry/reprocess_resolved.py --resolved-since 2025-10-01
```

---

## Verification Commands

```bash
# Check pending names
python -c "
from google.cloud import bigquery
client = bigquery.Client()
result = client.query('SELECT status, COUNT(*) FROM nba_reference.unresolved_player_names GROUP BY status').result()
for row in result: print(f'{row[0]}: {row[1]}')
"

# Check AI cache entries
python -c "
from google.cloud import bigquery
client = bigquery.Client()
result = client.query('SELECT COUNT(*) FROM nba_reference.ai_resolution_cache').result()
print(f'Cache entries: {list(result)[0][0]}')
"

# Run unit tests
python -m pytest shared/utils/tests/test_player_name_resolver.py -v

# Run health check
python monitoring/resolution_health_check.py
```

---

## Key Design Decision

**Why not call AI inline during processing?**

The AI resolver requires context building:
- 3+ BigQuery queries per name (~200ms each)
- Claude API call (~1-2 seconds)
- Total: ~2-3 seconds per name

Processing 1000 players inline would add 40+ minutes. The batch approach:
1. Fast deterministic lookups during processing
2. Names that miss go to queue
3. Nightly batch resolves with AI
4. Cache lookup catches them on next occurrence

---

## Related Documentation

- `/docs/08-projects/current/registry-system-fix/README.md` - Project docs
- `/docs/06-reference/player-registry.md` - Registry system reference
- `/docs/02-operations/runbooks/observability/registry-failures.md` - Monitoring
- `/docs/02-operations/backfill/runbooks/name-resolution.md` - Backfill guide
