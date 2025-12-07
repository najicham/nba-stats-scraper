# Session 56: Registry Failures Implementation

**Date:** 2025-12-06
**Duration:** ~2 hours
**Status:** Complete

---

## Summary

Implemented a dedicated `registry_failures` table and full lifecycle tracking for player name resolution failures. This enables targeted reprocessing after aliases are created.

---

## What Was Built

### New Table: `nba_processing.registry_failures`

```sql
CREATE TABLE registry_failures (
  player_lookup STRING,      -- Raw name that failed
  game_date DATE,            -- When player played
  processor_name STRING,     -- Which processor
  team_abbr STRING,          -- Context
  season STRING,             -- Context
  game_id STRING,            -- Context
  created_at TIMESTAMP,      -- When failure recorded
  resolved_at TIMESTAMP,     -- When alias created
  reprocessed_at TIMESTAMP,  -- When dates reprocessed
  occurrence_count INT64,
  run_id STRING
)
```

### Lifecycle

```
PENDING → RESOLVED → REPROCESSED
   ↓          ↓           ↓
created_at  resolved_at  reprocessed_at
```

### Files Created/Modified

| File | Change |
|------|--------|
| `schemas/bigquery/processing/registry_failures_table.sql` | NEW - Table schema |
| `data_processors/analytics/analytics_base.py` | Added `registry_failures` list and `save_registry_failures()` |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Tracks registry failures |
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Tracks registry failures |
| `tools/player_registry/resolve_unresolved_batch.py` | Sets `resolved_at` when alias created |
| `tools/player_registry/reprocess_resolved.py` | Queries registry_failures, sets `reprocessed_at` |
| `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md` | Updated to v3.0 |
| `docs/02-operations/runbooks/observability/registry-failures.md` | NEW - Operational runbook |
| `docs/02-operations/runbooks/backfill/name-resolution.md` | Updated cross-references |
| `shared/utils/player_registry/tests/test_registry_failures.py` | NEW - 18 unit tests |

---

## Design Decisions

### Why Separate Tables?

We chose to create a dedicated `registry_failures` table instead of using the existing `precompute_failures` table because:

1. **Different workflows** - Registry failures need alias creation then reprocessing; precompute failures just need time for more data
2. **Lifecycle tracking** - Registry failures have `resolved_at` and `reprocessed_at` timestamps
3. **Cleaner queries** - No filtering by category needed
4. **Better automation** - Can easily find "ready to reprocess" players

### Entity ID Convention

Registry failures use `player_lookup` (the raw name that failed), not the canonical name. This ensures:
- Query works before AND after alias is created
- Matches what's in `unresolved_player_names` table

---

## How It Works

### During Backfill

```python
# PlayerGameSummaryProcessor
if universal_player_id is None:
    self.registry_failures.append({
        'player_lookup': player_lookup,
        'game_date': row['game_date'],
        'team_abbr': row['team_abbr'],
        'season': '2021-22',
        'game_id': row['game_id']
    })
```

### After AI Resolution

```python
# resolve_unresolved_batch.py
def mark_registry_failures_resolved(self, player_lookup):
    UPDATE registry_failures
    SET resolved_at = CURRENT_TIMESTAMP()
    WHERE player_lookup = @player_lookup
      AND resolved_at IS NULL
```

### During Reprocessing

```python
# reprocess_resolved.py
def get_players_ready_to_reprocess(self):
    SELECT player_lookup, game_dates
    FROM registry_failures
    WHERE resolved_at IS NOT NULL
      AND reprocessed_at IS NULL
```

---

## Testing

- **Unit Tests:** 18 tests in `test_registry_failures.py`, all passing
- **Integration:** Table created in BigQuery, verified with `bq show`

---

## Known Limitations

1. **Old failures not migrated** - Any PLAYER_NOT_IN_REGISTRY failures in `precompute_failures` from before this implementation are not migrated to the new table

2. **No duplicate handling on re-runs** - If a processor re-runs for the same date, new failures are inserted (deduplicated within the run, but not across runs)

3. **Validation not yet integrated** - Phase 3 validators don't yet query registry_failures for reconciliation

---

## Future Work

1. **Validation Integration** - Update `phase3_validator.py` to show registry failure breakdown
2. **Alerting** - Set up Slack/email alerts for stale pending failures
3. **Dashboard** - BigQuery dashboard for failure trends

---

## Quick Reference

```bash
# Check status
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready'
    ELSE 'pending'
  END as status,
  COUNT(DISTINCT player_lookup) as players
FROM nba_processing.registry_failures
GROUP BY status"

# Run AI resolution
python tools/player_registry/resolve_unresolved_batch.py

# Reprocess resolved players
python tools/player_registry/reprocess_resolved.py --dry-run
python tools/player_registry/reprocess_resolved.py
```

---

## Related Documentation

- **Design Doc:** `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md`
- **Runbook:** `docs/02-operations/runbooks/observability/registry-failures.md`
- **Name Resolution:** `docs/02-operations/runbooks/backfill/name-resolution.md`
