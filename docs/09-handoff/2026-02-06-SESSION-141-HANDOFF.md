# Session 141 Handoff: Zero Tolerance for Default Features

**Date:** 2026-02-06
**Focus:** Eliminate predictions made with defaulted feature values

## What Was Done

Implemented zero tolerance policy: **refuse to predict for any player whose feature vector contains defaulted values** (`default_feature_count > 0`).

### Files Changed

1. **`data_processors/precompute/ml_feature_store/quality_scorer.py`**
   - `is_quality_ready` now requires `default_count == 0`
   - Alert level yellow threshold changed from `default_count > 10` to `> 0`

2. **`predictions/coordinator/quality_gate.py`**
   - Added `HARD_FLOOR_MAX_DEFAULTS = 0` constant
   - Added `default_feature_count` to feature quality query + details dict
   - Added Rule 2b: hard floor blocks any player with `default_feature_count > 0`
   - Applies to ALL modes (FIRST, RETRY, FINAL_RETRY, LAST_CALL, BACKFILL)

3. **`predictions/worker/worker.py`**
   - Defense-in-depth: `is_actionable = False` when `default_feature_count > 0`
   - Writes `default_feature_count` to prediction record for audit trail

4. **`schemas/bigquery/predictions/01_player_prop_predictions.sql`**
   - Added `default_feature_count INT64` column

5. **`tests/unit/prediction_tests/coordinator/test_quality_gate.py`**
   - Added `TestZeroTolerance` class (6 tests): 0 defaults passes, 3 defaults blocked, BACKFILL blocked, LAST_CALL blocked, mixed batch

6. **`docs/08-projects/current/zero-tolerance-defaults/00-PROJECT-OVERVIEW.md`**

### Tests

All 38 quality gate tests pass. All 22 quality system tests pass.

## What Needs to Happen Next

### Immediate (Before Next Prediction Run)

1. **Run schema migration:**
   ```sql
   ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
   ADD COLUMN IF NOT EXISTS default_feature_count INT64
   OPTIONS(description="Session 141: Number of features using default/fallback values (0 = all real data)");
   ```

2. **Deploy in order:**
   ```bash
   ./bin/deploy-service.sh nba-phase4-precompute-processors  # quality_scorer changes
   ./bin/deploy-service.sh prediction-coordinator             # quality_gate enforcement
   ./bin/deploy-service.sh prediction-worker                  # defense-in-depth
   ```

3. **Verify next prediction run:**
   - Expect ~75 predictions (down from ~180)
   - Check `PREDICTIONS_SKIPPED` Slack alerts show `zero_tolerance_defaults_N` reasons
   - Verify no predictions have `default_feature_count > 0`

### Future Work

- **Increase coverage by fixing data gaps** (NOT by relaxing tolerance)
- Vegas line coverage is the biggest gap (80 players blocked by 3 vegas defaults)
- Consider whether to convert defaults to NULLs in the feature store itself
