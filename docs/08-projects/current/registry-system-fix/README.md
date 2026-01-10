# Registry System Fix Project

**Date Started:** 2026-01-10
**Last Updated:** 2026-01-10
**Status:** In Progress (Phase 2)
**Priority:** Critical

## Problem Statement

The player name registry system had multiple issues preventing proper player identification:

1. **2,099 names stuck in "pending"** since October 2025 - AI resolver never called
2. **Reprocessing completely broken** - `process_single_game()` method didn't exist
3. **Inconsistent name normalization** - 10+ scrapers with different implementations
4. **No automatic recovery** - Manual intervention required at every step

## Project Phases

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1: AI Resolution | ✅ Complete | Batch resolve pending names, add cache lookup |
| Phase 2: Reprocessing | ✅ Complete | Implement `process_single_game()` method |
| Phase 3: Automation | 🔄 In Progress | Auto-trigger reprocessing after resolution |
| Phase 4: Standardization | 📋 Planned | Standardize all scraper normalization |

## Changes Made (This Session)

### 1. Implemented `process_single_game()` (CRITICAL FIX)

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

The reprocessing tool was calling a method that **didn't exist**, causing all reprocessing attempts to fail silently with `AttributeError`.

**Added:**
- `process_single_game(game_id, game_date, season)` - Main entry point
- `_extract_single_game_data()` - Parameterized query for single game
- `_save_single_game_records()` - Atomic MERGE upsert

**Commit:** `56cf1a7` - feat(registry): Implement process_single_game() for reprocessing

### 2. Fixed Date Conversion in Reprocessing Tool

**File:** `tools/player_registry/reprocess_resolved.py`

Fixed `reprocess_game()` to convert date object to string before passing to processor.

### 3. Enhanced Cache Handling (Previous Session)

**File:** `shared/utils/player_name_resolver.py`

- Added `DATA_ERROR` cache hit handling (skip re-queuing known bad names)
- Added alias creation failure handling with warning log
- Added comprehensive unit tests (11 tests)

**Commit:** `e5225b2` - fix(registry): Improve cache handling and add comprehensive tests

## Current Architecture

```
Phase 2 Raw Data (scrapers)
    ↓ player names with varying formats
Phase 3 Analytics (processors)
    ↓ names resolved via registry/alias/cache
    ↓ failures → registry_failures table
    ↓
[4:30 AM] AI Batch Resolution
    ↓ creates aliases, caches decisions
    ↓ marks registry_failures.resolved_at
    ↓
[MANUAL] Reprocessing ← NOW WORKS!
    ↓ process_single_game() re-runs failed games
    ↓ marks registry_failures.reprocessed_at
    ↓
Data Complete in player_game_summary
```

## Known Gaps (Prioritized)

| Priority | Gap | Impact | Status |
|----------|-----|--------|--------|
| HIGH | No auto-reprocessing after alias creation | Data stays incomplete until manual run | Planned |
| HIGH | Manual alias creation doesn't update registry_failures | Orphaned records | Planned |
| MEDIUM | Inconsistent normalization in scrapers | Name mismatches possible | Documented |
| LOW | No AI cache TTL | Bad decisions persist | Monitoring needed |
| LOW | No automatic health alerts | Silent failures | Planned |

## Files Modified (All Sessions)

| File | Change | Commit |
|------|--------|--------|
| `player_game_summary_processor.py` | Added `process_single_game()` method | `56cf1a7` |
| `reprocess_resolved.py` | Fixed date conversion, table reference | `56cf1a7` |
| `player_name_resolver.py` | Added cache lookup + DATA_ERROR handling | `e5225b2` |
| `test_player_name_resolver.py` | 11 comprehensive unit tests | `e5225b2` |
| `main_reference_service.py` | Added /resolve-pending, /health-check | `174c33d` |
| `add_registry_scheduler_jobs.sh` | Cloud Scheduler setup script | `174c33d` |

## Documentation

| Document | Purpose |
|----------|---------|
| [01-investigation-findings.md](./01-investigation-findings.md) | Complete analysis of all scrapers and failure scenarios |
| [02-implementation-plan.md](./02-implementation-plan.md) | Prioritized implementation plan |
| [03-data-flow.md](./03-data-flow.md) | How names flow through the system |
| [04-gaps-and-risks.md](./04-gaps-and-risks.md) | Known issues and mitigation strategies |

## Testing the Fix

```bash
# Verify process_single_game exists
python -c "
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
p = PlayerGameSummaryProcessor()
print('Method exists:', hasattr(p, 'process_single_game'))
"

# Dry run reprocessing
python tools/player_registry/reprocess_resolved.py --resolved-since 2025-01-01 --dry-run

# Actually reprocess
python tools/player_registry/reprocess_resolved.py --resolved-since 2025-01-01
```

## Remaining Work

1. **Deploy reference service** with new endpoints
2. **Run scheduler setup**: `./bin/orchestration/add_registry_scheduler_jobs.sh`
3. **Implement auto-reprocessing** trigger after AI resolution
4. **Process older seasons** (911 failures from 2021-2024)
5. **Standardize scraper normalization** (10+ files need updates)

## Related Documentation

- [Player Registry Reference](/docs/06-reference/player-registry.md)
- [Registry Failures Runbook](/docs/02-operations/runbooks/observability/registry-failures.md)
- [Name Resolution Backfill Guide](/docs/02-operations/backfill/runbooks/name-resolution.md)
