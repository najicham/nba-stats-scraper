# Failure Tracking Design Document

**Date:** 2025-12-06
**Status:** In Progress
**Priority:** HIGH - Critical for operational visibility
**Version:** 3.0

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Design Decision: Purpose-Specific Tables](#design-decision-purpose-specific-tables)
4. [Registry Failures Table (Phase 3)](#registry-failures-table-phase-3)
5. [Precompute Failures Table (Phase 4)](#precompute-failures-table-phase-4)
6. [Workflow Lifecycle](#workflow-lifecycle)
7. [Validation Integration](#validation-integration)
8. [Implementation Plan](#implementation-plan)
9. [Quick Reference](#quick-reference)

---

## Problem Statement

When a player is missing from a processor's output, we cannot determine if:
- **Registry issue:** Player name not yet resolved (can fix via alias)
- **Data quality:** Not enough games yet (expected skip)
- **Actual error:** Processing failed unexpectedly (needs investigation)

### Key Use Case: Name Resolution Reprocessing

```
1. Backfill runs for 2021-2022 season
2. Player "marcusmorris" not in registry → skipped
3. Later: AI creates alias marcusmorris → marcusmorrissr
4. Need to find: Which dates need reprocessing?
5. Reprocess only those dates → downstream cascades
```

**Without tracking:** No way to efficiently find these gaps.

---

## Goals

### Primary Goal
Track registry failures with full lifecycle:
- **Created:** When failure occurs
- **Resolved:** When alias is created
- **Reprocessed:** When dates are reprocessed

### Secondary Goals
- Enable validation to show actionable breakdown
- Support automated reprocessing workflows
- Distinguish registry issues from data quality issues

---

## Design Decision: Purpose-Specific Tables

We use **two separate tables** for different purposes:

| Table | Purpose | Phase | Action Required |
|-------|---------|-------|-----------------|
| `registry_failures` | Track name resolution issues | Phase 3 | Create alias, reprocess |
| `precompute_failures` | Track data quality skips | Phase 4 | Wait for more data |

### Why Separate Tables?

1. **Different workflows** - Registry failures need alias creation; data quality skips just need time
2. **Different lifecycle** - Registry failures have resolved/reprocessed states
3. **Cleaner validation** - No filtering by category needed
4. **Better automation** - Can trigger alerts on "resolved but not reprocessed"

---

## Registry Failures Table (Phase 3)

### Schema

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.registry_failures` (
  -- Identity
  player_lookup STRING NOT NULL,        -- Raw name that failed lookup
  game_date DATE NOT NULL,              -- When the player played
  processor_name STRING NOT NULL,       -- Which processor encountered it

  -- Context
  team_abbr STRING,                     -- Team context for debugging
  season STRING,                        -- Season (e.g., "2021-22")
  game_id STRING,                       -- Specific game

  -- Lifecycle timestamps
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  resolved_at TIMESTAMP,                -- When alias was created
  reprocessed_at TIMESTAMP,             -- When date was reprocessed

  -- Metadata
  occurrence_count INT64 DEFAULT 1,     -- How many times seen
  run_id STRING                         -- Processing run that created this
)
PARTITION BY game_date
CLUSTER BY player_lookup, processor_name
OPTIONS (
  description = "Track player name resolution failures for reprocessing workflow"
);
```

### Failure Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        REGISTRY FAILURE LIFECYCLE                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐                   │
│  │   PENDING    │ ──── │   RESOLVED   │ ──── │ REPROCESSED  │                   │
│  └──────────────┘      └──────────────┘      └──────────────┘                   │
│                                                                                  │
│  created_at: SET       resolved_at: SET      reprocessed_at: SET               │
│  resolved_at: NULL     reprocessed_at: NULL  ✅ Complete                        │
│                                                                                  │
│  Action: Create alias  Action: Reprocess     No action needed                   │
│                                                                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  Status Query:                                                                   │
│  CASE                                                                           │
│    WHEN reprocessed_at IS NOT NULL THEN 'complete'                              │
│    WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'                       │
│    ELSE 'pending_resolution'                                                    │
│  END                                                                            │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Which Processors Write Here

| Processor | When |
|-----------|------|
| `PlayerGameSummaryProcessor` | Registry lookup returns None |
| `UpcomingPlayerGameContextProcessor` | Registry lookup returns None |

---

## Precompute Failures Table (Phase 4)

### Schema (Existing)

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.precompute_failures` (
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  analysis_date DATE NOT NULL,
  entity_id STRING NOT NULL,
  failure_category STRING NOT NULL,
  failure_reason STRING NOT NULL,
  can_retry BOOLEAN NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY processor_name, failure_category, can_retry
```

### Failure Categories

| Category | Meaning | Action |
|----------|---------|--------|
| `INSUFFICIENT_DATA` | < 5 games played | Wait for more games |
| `INCOMPLETE_DATA` | Upstream windows incomplete | Wait or check Phase 3 |
| `MISSING_DEPENDENCY` | No shot zone, etc. | Check dependency processor |
| `CIRCUIT_BREAKER_ACTIVE` | Too many retries | Manual investigation |
| `PROCESSING_ERROR` | Exception | Debug code |

### Which Processors Write Here

| Processor | Categories |
|-----------|------------|
| `PlayerDailyCacheProcessor` | INSUFFICIENT_DATA, INCOMPLETE_DATA, MISSING_DEPENDENCY |
| `PlayerShotZoneAnalysisProcessor` | INSUFFICIENT_DATA, PROCESSING_ERROR |
| `PlayerCompositeFactorsProcessor` | INSUFFICIENT_DATA, INCOMPLETE_DATA |
| `MLFeatureStoreProcessor` | INSUFFICIENT_DATA, INCOMPLETE_DATA |
| `TeamDefenseZoneAnalysisProcessor` | PROCESSING_ERROR |

---

## Workflow Lifecycle

### 1. During Backfill

```
PlayerGameSummaryProcessor runs for 2021-11-05:
├── Player "lebronJames" → found in registry ✅ → record created
├── Player "marcusmorris" → NOT found ❌ → registry_failures record created
└── Player "stephcurry" → found in registry ✅ → record created
```

### 2. After AI Resolution

```bash
# AI resolution creates alias
python tools/player_registry/resolve_unresolved_batch.py

# This should update registry_failures:
UPDATE registry_failures
SET resolved_at = CURRENT_TIMESTAMP()
WHERE player_lookup = 'marcusmorris'
  AND resolved_at IS NULL
```

### 3. Reprocessing

```bash
# Find dates ready to reprocess
python tools/player_registry/reprocess_resolved.py --dry-run

# Output:
# Ready to reprocess:
#   marcusmorris: 45 dates (2021-11-05 to 2022-04-10)
#
# Run without --dry-run to reprocess

# After reprocessing:
UPDATE registry_failures
SET reprocessed_at = CURRENT_TIMESTAMP()
WHERE player_lookup = 'marcusmorris'
  AND resolved_at IS NOT NULL
  AND reprocessed_at IS NULL
```

---

## Validation Integration

### Validation Output (Goal)

```
Registry Failures Summary for 2021-11-05:
┌─────────────────────────────────────────────────────────────────┐
│ Total failures:           25                                    │
│ ├─ Pending resolution:     5  ⚠️  (need alias)                  │
│ ├─ Ready to reprocess:     8  🔄 (alias exists, run reprocess)  │
│ └─ Reprocessed:           12  ✅ (complete)                     │
└─────────────────────────────────────────────────────────────────┘

Pending resolution (top 5 by occurrence):
  marcusmorris      - 45 games, first seen 2021-11-05
  johndoe           - 12 games, first seen 2021-12-01
  ...

Ready to reprocess:
  robertwilliams    - 30 dates ready
  kevinknox         - 22 dates ready
```

### Validation Queries

```sql
-- Status breakdown for a date
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'reprocessed'
    WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
    ELSE 'pending_resolution'
  END as status,
  COUNT(DISTINCT player_lookup) as player_count,
  COUNT(*) as total_records
FROM `nba_processing.registry_failures`
WHERE game_date = @target_date
GROUP BY status

-- Players needing attention (pending > 7 days)
SELECT
  player_lookup,
  COUNT(*) as affected_dates,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  MIN(created_at) as first_seen
FROM `nba_processing.registry_failures`
WHERE resolved_at IS NULL
  AND created_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY player_lookup
ORDER BY affected_dates DESC
```

---

## Implementation Plan

### Phase 1: Schema & Infrastructure ✅ COMPLETE

| Task | Status |
|------|--------|
| Create `registry_failures` table schema | ✅ Done |
| Create BigQuery table | ✅ Done |
| Add `save_registry_failures()` to AnalyticsProcessorBase | ✅ Done |
| Update PlayerGameSummaryProcessor | ✅ Done |
| Update UpcomingPlayerGameContextProcessor | ✅ Done |

### Phase 2: Workflow Integration ✅ COMPLETE

| Task | Status |
|------|--------|
| Update `resolve_unresolved_batch.py` to set `resolved_at` | ✅ Done |
| Update `reprocess_resolved.py` to query registry_failures | ✅ Done |
| Update `reprocess_resolved.py` to set `reprocessed_at` | ✅ Done |

### Phase 3: Validation Enhancement (Future)

| Task | Status |
|------|--------|
| Add registry failure status to validation output | ⏳ Future |
| Add "ready to reprocess" alerts | ⏳ Future |

---

## Quick Reference

### Check Registry Failure Status

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'reprocessed'
    WHEN resolved_at IS NOT NULL THEN 'ready'
    ELSE 'pending'
  END as status,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as records
FROM \`nba-props-platform.nba_processing.registry_failures\`
GROUP BY status"
```

### Find Players Ready to Reprocess

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as dates_to_reprocess
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NOT NULL
  AND reprocessed_at IS NULL
GROUP BY player_lookup
ORDER BY dates_to_reprocess DESC"
```

### Find Stale Pending Failures

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as affected_dates,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MIN(created_at), DAY) as days_pending
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NULL
GROUP BY player_lookup
HAVING days_pending > 7
ORDER BY affected_dates DESC"
```

---

## Related Documentation

- **Name Resolution Runbook:** `docs/02-operations/runbooks/backfill/name-resolution.md`
- **AI Name Resolution Design:** `docs/08-projects/current/ai-name-resolution/DESIGN-DOC-AI-NAME-RESOLUTION.md`

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-06 | 3.0 | **REDESIGN**: Separate registry_failures table with lifecycle tracking |
| 2025-12-06 | 2.1 | Implemented Phase 3 tracking (superseded) |
| 2025-12-06 | 2.0 | Added Phase 3 tracking design |
| 2025-12-06 | 1.0 | Initial draft |
