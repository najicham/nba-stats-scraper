# Registry System Fix Project

**Date Started:** 2026-01-10
**Last Updated:** 2026-01-10
**Status:** Phase 3 Complete - Monitoring Integrated
**Priority:** Critical

## Problem Statement

The player name registry system had multiple issues preventing proper player identification:

1. **2,099 names stuck in "pending"** since October 2025 - AI resolver never called
2. **Reprocessing completely broken** - `process_single_game()` method didn't exist
3. **Inconsistent name normalization** - 10+ scrapers with different implementations
4. **No automatic recovery** - Manual intervention required at every step
5. **No visibility into prediction gaps** - Couldn't detect when lines exist but no prediction made

## Project Phases

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1: AI Resolution | ✅ Complete | Batch resolve pending names, add cache lookup |
| Phase 2: Reprocessing | ✅ Complete | Implement `process_single_game()` method |
| Phase 3: Automation | ✅ Complete | Auto-trigger reprocessing after resolution |
| Phase 4: Monitoring | ✅ Complete | Prediction coverage monitoring and validation |
| Phase 5: Standardization | 📋 Planned | Standardize all scraper normalization |

## All Changes Made (This Session)

### 1. Implemented `process_single_game()` (CRITICAL FIX)

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

The reprocessing tool was calling a method that **didn't exist**, causing all reprocessing attempts to fail silently with `AttributeError`.

**Commit:** `56cf1a7`

### 2. Auto-Reprocessing After AI Resolution

**File:** `tools/player_registry/resolve_unresolved_batch.py`

- Integrated reprocessing directly into resolution script
- Circuit breaker (stops after 5 consecutive failures)
- Observability logging to `nba_processing.reprocessing_runs`
- Alerts on failure rate > 20%

**Commit:** `89d91f5`

### 3. Backfill Recovery Tool

**File:** `tools/player_registry/recover_backfill_failures.py`

Recovers historical failures where player now exists in registry:
```bash
python tools/player_registry/recover_backfill_failures.py --dry-run
python tools/player_registry/recover_backfill_failures.py
```

**Commit:** `4dfba5d`

### 4. Prediction Coverage Monitoring

**File:** `tools/monitoring/check_prediction_coverage.py`

Identifies players with betting lines but no predictions:
```bash
python tools/monitoring/check_prediction_coverage.py --date 2026-01-09 --detailed
```

**Commit:** `9371bbe`

### 5. Validation Framework Integration

**Files:**
- `validation/validators/predictions/prediction_coverage_validator.py`
- `docs/02-operations/daily-validation-checklist.md` (Step 9 added)
- `docs/02-operations/runbooks/observability/registry-failures.md` (updated)

**Commit:** `c4fc3ad`

### 6. Cache Handling Improvements

**File:** `shared/utils/player_name_resolver.py`

- Added `DATA_ERROR` cache hit handling (skip re-queuing known bad names)
- Added alias creation failure handling with warning log
- Added comprehensive unit tests (11 tests)

**Commit:** `e5225b2`

## Current Architecture

```
Phase 2 Raw Data (scrapers)
    ↓ player names with varying formats
Phase 3 Analytics (processors)
    ↓ names resolved via registry/alias/cache
    ↓ failures → registry_failures table
    ↓
[4:30 AM] AI Batch Resolution + Auto-Reprocessing
    ↓ creates aliases, caches decisions
    ↓ auto-reprocesses affected games
    ↓ marks registry_failures.resolved_at + reprocessed_at
    ↓
Data Complete in player_game_summary
    ↓
[Morning] Prediction Coverage Check
    ↓ identifies any remaining gaps
    ↓ flags name resolution issues
```

## Recovery Tools Summary

| Tool | Purpose | Command |
|------|---------|---------|
| AI Resolution + Reprocess | Full flow | `python tools/player_registry/resolve_unresolved_batch.py` |
| Reprocess Only | Already resolved | `python tools/player_registry/resolve_unresolved_batch.py --reprocess-only` |
| Backfill Recovery | Historical fixes | `python tools/player_registry/recover_backfill_failures.py` |
| Coverage Check | Find gaps | `python tools/monitoring/check_prediction_coverage.py --detailed` |

## Historical Data Analysis

From backfill investigation:

| Category | Failures | Players | Action |
|----------|----------|---------|--------|
| Resolved, ready to reprocess | 2,138 | 38 | Run `--reprocess-only` |
| In registry but unresolved | 1,064 | 569 | Run `recover_backfill_failures.py` |
| Truly missing | 1,074 | 19 | AI resolution needed |
| **Total** | 4,276 | 626 | |

## Known Gaps (Prioritized)

| Priority | Gap | Impact | Status |
|----------|-----|--------|--------|
| ~~HIGH~~ | ~~No auto-reprocessing after alias creation~~ | ~~Data stays incomplete~~ | ✅ Fixed |
| MEDIUM | Manual alias creation doesn't update registry_failures | Orphaned records | Documented |
| MEDIUM | Inconsistent normalization in scrapers | Name mismatches possible | Documented |
| LOW | No AI cache TTL | Bad decisions persist | Monitoring in place |

## All Commits (This Session)

| Commit | Description |
|--------|-------------|
| `e5225b2` | fix(registry): Improve cache handling and add comprehensive tests |
| `56cf1a7` | feat(registry): Implement process_single_game() for reprocessing |
| `e7524da` | docs(registry): Add comprehensive system documentation |
| `89d91f5` | feat(registry): Add auto-reprocessing after AI resolution |
| `4dfba5d` | feat(registry): Add backfill recovery tool for historical failures |
| `9371bbe` | feat(monitoring): Add prediction coverage gap tracking |
| `c4fc3ad` | fix(processors): Add monitoring, sanitization, and roster query fixes |

## Documentation

| Document | Purpose |
|----------|---------|
| [01-investigation-findings.md](./01-investigation-findings.md) | Complete analysis of all scrapers and failure scenarios |
| [02-implementation-plan.md](./02-implementation-plan.md) | Prioritized implementation plan |
| [03-data-flow.md](./03-data-flow.md) | How names flow through the system |
| [04-gaps-and-risks.md](./04-gaps-and-risks.md) | Known issues and mitigation strategies |

## Daily Monitoring

Add to your morning routine (now in `docs/02-operations/daily-validation-checklist.md`):

```bash
# Step 9.1: Registry failures status
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
    ELSE 'pending_resolution'
  END as status,
  COUNT(DISTINCT player_lookup) as players
FROM \`nba_processing.registry_failures\`
GROUP BY status"

# Step 9.2: Prediction coverage check
python tools/monitoring/check_prediction_coverage.py --date $(date -d 'yesterday' +%Y-%m-%d)
```

## Remaining Work

1. **Deploy reference service** with new endpoints
2. **Run scheduler setup**: `./bin/orchestration/add_registry_scheduler_jobs.sh`
3. **Process historical failures**: Run `recover_backfill_failures.py`
4. **Standardize scraper normalization** (10+ files need updates - future project)

## Related Documentation

- [Player Registry Reference](/docs/06-reference/player-registry.md)
- [Registry Failures Runbook](/docs/02-operations/runbooks/observability/registry-failures.md)
- [Name Resolution Backfill Guide](/docs/02-operations/backfill/runbooks/name-resolution.md)
- [Daily Validation Checklist](/docs/02-operations/daily-validation-checklist.md)
