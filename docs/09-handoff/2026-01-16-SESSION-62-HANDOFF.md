# Session 62 Handoff - NBA Daily Orchestration Validation

**Date**: 2026-01-16 (started evening of Jan 15)
**Focus**: NBA daily orchestration validation, coordinator stall fix
**Status**: Code fix ready, deployment pending

---

## Executive Summary

This session focused on validating the NBA daily orchestration pipeline from multiple angles. We discovered and addressed:

1. **Name normalization gaps** - 2 players had props but different `player_lookup` values than canonical
2. **Timing issues** - Context data created after coordinator ran
3. **Coordinator stall issue** - Batches getting stuck at 102-103/104 (workers fail silently)

We implemented a code fix for the stall issue but deployment failed due to missing shared module. The fix is ready for proper deployment.

---

## Current Pipeline State

| Phase | Latest Data | Status |
|-------|-------------|--------|
| Phase 2 (boxscores) | Jan 15 | ✅ Current |
| Phase 3 (analytics) | Jan 15 | ✅ Current |
| Phase 4 (precompute) | Jan 15 | ✅ Current |
| Phase 5 (predictions) | Jan 16 | ⚠️ Stalled at 103/104 |

### Prediction Batch Status

- **Batch ID**: `batch_2026-01-15_1768526607`
- **Progress**: 103/104 workers completed
- **Issue**: 1 worker never responded (same pattern as previous batch)
- **Main predictions table**: Shows 77 players (stale - from earlier batch)
- **Staging tables**: ~150+ tables exist with predictions not yet merged

---

## Issues Identified & Fixed

### 1. Name Normalization Gap (FIXED)

**Problem**: OddsAPI uses different player name formats than our canonical names.

| Props Name | Canonical Name | Status |
|------------|----------------|--------|
| `isaiahstewartii` | `isaiahstewart` | ✅ Alias added |
| `vincentwilliamsjr` | `vincewilliamsjr` | ✅ Alias existed |

**Fix Applied**: Added alias to `nba_reference.player_aliases`:
```sql
INSERT INTO nba_reference.player_aliases (
  alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display,
  alias_type, alias_source, is_active, notes, created_by, created_at, processed_at
)
VALUES (
  'isaiahstewartii', 'isaiahstewart', 'Isaiah Stewart II', 'Isaiah Stewart',
  'name_variation', 'odds_api', TRUE, 'Odds API uses suffix II for Isaiah Stewart',
  'session_62_validation', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
)
```

### 2. Timing Issue (DOCUMENTED)

**Problem**: 6 players had context data created at 23:51, but last coordinator ran at 16:31.

**Affected Players**: cadecunningham, franzwagner, jalenduren, tobiasharris, tristandasilva, wendellcarterjr

**Root Cause**: Injury-return players get added to context later in the day when cleared to play.

**Resolution**: The new batch (started at 01:26) picked up these players.

### 3. Coordinator Stall Issue (CODE FIX READY, NOT DEPLOYED)

**Problem**: Coordinator waits indefinitely for 100% worker completion. If 1-2 workers fail silently, batch never completes and staging tables never merge.

**Pattern Observed**:
- First batch: 102/104 completed, stuck for 79 minutes
- Second batch: 103/104 completed, stuck again

**Code Fix Implemented** (in local files, not deployed):

#### File: `predictions/coordinator/batch_state_manager.py`

Added `check_and_complete_stalled_batch()` method:
```python
def check_and_complete_stalled_batch(
    self,
    batch_id: str,
    stall_threshold_minutes: int = 10,
    min_completion_pct: float = 95.0
) -> bool:
    """
    Check if a batch is stalled and complete it with partial results.

    A batch is considered stalled if:
    1. It has reached the minimum completion percentage (default 95%)
    2. No new completions for stall_threshold_minutes (default 10 min)
    """
    # ... implementation details in file
```

Modified `record_completion()` to auto-check for stall at 95%+.

#### File: `predictions/coordinator/coordinator.py`

Added `/check-stalled` endpoint:
```python
@app.route('/check-stalled', methods=['POST'])
@require_api_key
def check_stalled_batches():
    """
    Check for stalled batches and complete them with partial results.
    Can be called manually or by scheduled job.
    """
    # ... implementation details in file
```

**Deployment Issue**: Attempted deployment failed with `ModuleNotFoundError: No module named 'shared'`. The coordinator imports from `shared.config.orchestration_config` which requires proper build context.

**Rollback**: Rolled back to revision `prediction-coordinator-00041-sbn` (working).

---

## Validation System Enhancements

Updated `/docs/08-projects/current/orchestration-optimization/VALIDATION-PLAN.md` with new validation angles:

### New Validation Queries Added

1. **Enhanced Coverage with Alias Resolution** (§2c)
   - JOINs through `player_aliases` for accurate prop→prediction coverage

2. **Name Normalization Gap Check** (§2d)
   - Finds players in props but not in context due to name mismatch

3. **Timing Validation** (§2e)
   - Compares context creation time vs coordinator run time

4. **Coordinator Duration Check** (§3)
   - Detects coordinators running >30 minutes

5. **Batch Progress Check** (§3b)
   - Shows X/Y completion from logs

6. **Staging vs Main Comparison** (§3c)
   - Compares staging table count vs main predictions

### Quick Validation Commands

```bash
# Pipeline status
bq query --nouse_legacy_sql "
SELECT 'Phase2' as phase, MAX(game_date) as latest FROM nba_raw.bdl_player_boxscores WHERE game_date >= '2026-01-01'
UNION ALL SELECT 'Phase3', MAX(game_date) FROM nba_analytics.player_game_summary WHERE game_date >= '2026-01-01'
UNION ALL SELECT 'Phase4', MAX(game_date) FROM nba_precompute.player_composite_factors WHERE game_date >= '2026-01-01'
UNION ALL SELECT 'Phase5', MAX(game_date) FROM nba_predictions.player_prop_predictions WHERE is_active = TRUE
"

# Check stuck coordinator
bq query --nouse_legacy_sql "
SELECT processor_name, status, data_date, started_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running
FROM nba_reference.processor_run_history
WHERE processor_name = 'PredictionCoordinator' AND status = 'running'
"

# Coverage with alias resolution
bq query --nouse_legacy_sql "
WITH props AS (
  SELECT DISTINCT p.player_lookup as props_lookup,
    COALESCE(a.nba_canonical_lookup, p.player_lookup) as canonical_lookup
  FROM nba_raw.odds_api_player_points_props p
  LEFT JOIN nba_reference.player_aliases a ON p.player_lookup = a.alias_lookup AND a.is_active = TRUE
  WHERE p.game_date = CURRENT_DATE()
),
predictions AS (
  SELECT DISTINCT player_lookup FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE() AND is_active = TRUE
)
SELECT COUNT(DISTINCT props_lookup) as with_props,
  COUNT(DISTINCT CASE WHEN pred.player_lookup IS NOT NULL THEN props_lookup END) as matched,
  COUNT(DISTINCT CASE WHEN pred.player_lookup IS NULL THEN props_lookup END) as missing
FROM props LEFT JOIN predictions pred ON props.canonical_lookup = pred.player_lookup
"
```

---

## Immediate Actions Needed

### 1. Deploy Coordinator Fix (HIGH PRIORITY)

The stall fix code is ready but needs proper deployment with shared module access.

**Option A**: Create cloudbuild config for coordinator
```yaml
# Need to create: cloudbuild-coordinator.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/prediction-coordinator', '-f', 'predictions/coordinator/Dockerfile', '.']
  # ... include shared module in build context
```

**Option B**: Modify coordinator to not depend on shared module (remove the import if not critical)

### 2. Clean Up Current Stalled Batch

```bash
# Clean up stuck run_history entry
bq query --nouse_legacy_sql "
UPDATE nba_reference.processor_run_history
SET status = 'failed', errors = '{\"message\":\"Manual cleanup: stuck batch\"}'
WHERE processor_name = 'PredictionCoordinator' AND status = 'running'
"

# Then force new batch
curl -X POST 'https://prediction-coordinator-756957797294.us-west2.run.app/start' \
  -H 'Authorization: Bearer $(gcloud auth print-identity-token)' \
  -H 'Content-Type: application/json' \
  -d '{"game_date": "2026-01-16", "force": true}'
```

### 3. Investigate Worker Reliability

Consistently 1-2 workers per batch fail silently. Need to investigate:
- Pub/Sub message delivery issues
- Worker timeout/crash patterns
- Specific players that fail (is it consistent?)

---

## Files Modified This Session

| File | Changes |
|------|---------|
| `predictions/coordinator/batch_state_manager.py` | Added `check_and_complete_stalled_batch()`, modified `record_completion()` |
| `predictions/coordinator/coordinator.py` | Added `/check-stalled` endpoint |
| `docs/08-projects/current/orchestration-optimization/VALIDATION-PLAN.md` | Added 6 new validation queries, session log, deployment notes |
| `nba_reference.player_aliases` (BigQuery) | Added isaiahstewartii alias |

---

## Key Learnings

1. **Worker reliability is a systemic issue** - Not random, consistently 1-2 workers fail per batch
2. **100% completion requirement is fragile** - Need partial completion with threshold
3. **Name normalization needs proactive monitoring** - Should check for new mismatches regularly
4. **Timing between context refresh and coordinator** - Context can update after coordinator runs

---

## Reference Links

- **Coordinator service**: `https://prediction-coordinator-756957797294.us-west2.run.app`
- **Current revision**: `prediction-coordinator-00041-sbn`
- **Failed revision**: `prediction-coordinator-00042-n9c` (rollback complete)
- **Validation doc**: `docs/08-projects/current/orchestration-optimization/VALIDATION-PLAN.md`

---

## For Next Session

1. **Deploy the coordinator fix** with proper build context
2. **Once deployed**, call `/check-stalled` to complete the stuck batch
3. **Verify** predictions merge to main table
4. **Monitor** next batch to confirm fix works
5. **Investigate** worker reliability root cause

---

**Session Duration**: ~3 hours
**Primary Outcome**: Validation system enhanced, stall fix implemented (pending deploy)
