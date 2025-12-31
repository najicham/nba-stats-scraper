# Session 111 Handoff - Grading Schema Updated, Phase 5B & Phase 6 Design Ready

**Date:** 2025-12-10
**Duration:** ~30 minutes
**Focus:** Validate Jan 1-7 backfills, update grading schema, design Phase 5B (Grading) and Phase 6 (Publishing)

---

## Executive Summary

Session 111 validated the Jan 1-7, 2022 backfills (100% coverage), redesigned the `prediction_accuracy` schema with ML training features, and clarified the Phase 5/6 architecture:

- **Phase 5A (existing):** Predictions - generates predictions for upcoming games
- **Phase 5B (to build):** Grading - compares predictions to actual results for ML training
- **Phase 6 (future):** Publishing - prepares data for website consumption

**Key Accomplishments:**
1. Validated Jan 1-7, 2022: 100% coverage, all 5 systems, MAE 4.75-6.2
2. Updated `prediction_accuracy` schema with `system_id`, `signed_error`, margin fields
3. Applied new schema to BigQuery (table recreated)
4. Documented Phase 5B and Phase 6 design decisions

---

## Files to Commit

```bash
# Stage the schema change
git add schemas/bigquery/nba_predictions/prediction_accuracy.sql

# Commit
git commit -m "feat: Update prediction_accuracy schema for ML training

- Add system_id to grade each prediction system separately
- Add signed_error for bias direction detection
- Add margin analysis fields (predicted_margin, actual_margin)
- Add threshold accuracy (within_3_points, within_5_points)
- Change partition to game_date, cluster by system_id, player_lookup

Enables comprehensive grading for ML model improvement.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Required Reading for Next Session

1. **This handoff doc** (current file)
2. **Backfill validation checklist:** `docs/02-operations/backfill/backfill-validation-checklist.md`
   - Section 7: Phase 5 Predictions Validation
3. **Previous session handoff:** `docs/09-handoff/2025-12-10-SESSION110-MLFS-BACKFILL-AND-PHASE6-DESIGN.md`
4. **Updated schema:** `schemas/bigquery/nba_predictions/prediction_accuracy.sql`

---

## Current Backfill Status

### Validated Periods
| Period | Phase 4 | MLFS | Predictions | Coverage |
|--------|---------|------|-------------|----------|
| Nov 6-30, 2021 | ✅ | ✅ | ✅ | ~99% |
| Dec 1-31, 2021 | ✅ | ✅ | ✅ | 100% |
| Jan 1-7, 2022 | ✅ | ✅ | ✅ | 100% |

### Jan 1-7, 2022 Validation Results
```
Coverage: 100% all 7 dates
Duplicates: 0
Systems: 5 (all active)
Total predictions: 5,377

MAE by system:
- xgboost_v1: 4.75 (best)
- ensemble_v1: 4.79
- moving_average_baseline_v1: 4.94
- similarity_balanced_v1: 4.99
- zone_matchup_v1: 6.2

Bias: All systems under-predict (-1.1 to -2.3 points)
```

### Predictions Table Summary
- **Date range:** Nov 6, 2021 - Jan 7, 2022
- **Total dates:** 61
- **Total predictions:** ~47,355
- **Grading status:** 0 records (not yet implemented)

---

## Phase 5B: Grading Process Design

### Purpose
Compare predictions to actual game results to:
1. Enable ML model training on accuracy data
2. Track system performance over time
3. Support confidence calibration analysis

### Updated Schema (Applied to BQ)
```sql
CREATE TABLE prediction_accuracy (
  -- Keys
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,  -- Grade each system separately

  -- Prediction Snapshot
  predicted_points NUMERIC(5, 1),
  confidence_score NUMERIC(4, 3),
  recommendation STRING,  -- OVER/UNDER/PASS
  line_value NUMERIC(5, 1),

  -- Feature Inputs (for ML analysis)
  referee_adjustment NUMERIC(5, 1),
  pace_adjustment NUMERIC(5, 1),
  similarity_sample_size INTEGER,

  -- Actual Result
  actual_points INTEGER,

  -- Core Accuracy Metrics
  absolute_error NUMERIC(5, 1),  -- |predicted - actual|
  signed_error NUMERIC(5, 1),    -- predicted - actual (bias direction)
  prediction_correct BOOLEAN,     -- Was OVER/UNDER correct?

  -- Margin Analysis
  predicted_margin NUMERIC(5, 1),  -- predicted - line
  actual_margin NUMERIC(5, 1),     -- actual - line

  -- Thresholds
  within_3_points BOOLEAN,
  within_5_points BOOLEAN,

  -- Metadata
  model_version STRING,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup;
```

### Key Design Decisions
1. **Grade ALL systems separately** (5 systems + ensemble = 6 records per player/game)
   - Enables system comparison and weight optimization
   - Storage is trivial (~250k records/season)

2. **Include signed_error** for bias detection
   - Positive = over-predicted, negative = under-predicted
   - Current systems show -1.1 to -2.3 bias (under-predicting)

3. **Margin analysis** for betting evaluation
   - `predicted_margin = predicted_points - line_value`
   - `actual_margin = actual_points - line_value`

4. **Threshold accuracy** for "close enough" analysis
   - `within_3_points` and `within_5_points` booleans

### Implementation Plan
```
Files to create:
1. data_processors/grading/prediction_accuracy_processor.py
2. backfill_jobs/grading/prediction_accuracy_backfill.py

Core logic:
1. Query predictions for game_date
2. Query actual points from player_game_summary
3. Join and compute all accuracy metrics
4. Write to prediction_accuracy table (with pre-delete for idempotency)
```

### Grading Trigger
- **Daily:** Run after games finish (~midnight ET), triggered by gamebook processor
- **Backfill:** Run for historical dates with existing predictions

---

## Phase 6: Publishing Design

### Purpose
Prepare data for website consumption. This is NOT grading - grading is Phase 5B.

### What Phase 6 Does
1. Aggregate accuracy metrics for website dashboards
2. Prepare prediction data in website-friendly format
3. Generate system performance leaderboards
4. Create daily recommendation summaries

### Existing Schema Infrastructure (Empty)
| Table | Purpose | Status |
|-------|---------|--------|
| `prediction_results` | Detailed predicted vs actual | Schema exists, empty |
| `system_daily_performance` | Daily aggregated accuracy | Schema exists, empty |
| `prediction_quality_log` | Data quality tracking | Schema exists, empty |

### Existing Views (Will Work Once Data Exists)
- `v_system_accuracy_leaderboard.sql` - Ranks systems by 30-day accuracy
- `v_system_performance_comparison.sql` - Compares systems with trends

### Phase 6 Can Wait
Phase 6 is lower priority than:
1. Completing Phase 5B (grading)
2. Backfilling historical data through full 2021-22 season
3. Validating system accuracy

---

## Design Review Documents

### For Web Chat Review: Phase 5B Grading Design

**Copy this to Claude web chat for design review:**

```markdown
# Phase 5B Grading Process Design Review

## Context
We have an NBA prediction system that generates player points predictions before games. After games complete, we need to grade these predictions against actual results.

## Current State
- 5 prediction systems running: moving_average, zone_matchup, similarity, xgboost, ensemble
- ~47,000 predictions exist (Nov 6, 2021 - Jan 7, 2022)
- No grading has been implemented yet
- Schema table exists but is empty

## Proposed Design

### Schema (Already Applied)
```sql
prediction_accuracy (
  player_lookup, game_id, game_date, system_id,
  predicted_points, confidence_score, recommendation, line_value,
  referee_adjustment, pace_adjustment, similarity_sample_size,
  actual_points,
  absolute_error, signed_error, prediction_correct,
  predicted_margin, actual_margin,
  within_3_points, within_5_points,
  model_version, graded_at
)
```

### Key Decisions Made
1. Grade each of 5 systems separately (not just ensemble)
2. Include signed_error for bias detection (positive=over-predicted)
3. Include margin analysis for betting evaluation
4. Include threshold booleans for "close enough" analysis

### Questions for Review
1. Is grading all 5 systems separately the right approach, or should we only grade ensemble?
2. Are the accuracy metrics sufficient for ML training?
3. Should we add any additional fields for confidence calibration analysis?
4. For daily operations, should grading run immediately after games or next morning?

### Expected Output
- ~250k graded records per season (5 systems × 50k predictions)
- Enable queries like "Which system performs best on high-usage players?"
- Support confidence calibration: "When we say 80% confident, are we right 80% of the time?"
```

---

### For Web Chat Review: Phase 6 Publishing Design

**Copy this to Claude web chat for design review:**

```markdown
# Phase 6 Publishing Process Design Review

## Context
We have an NBA prediction and grading pipeline:
- Phase 5A: Generate predictions before games
- Phase 5B: Grade predictions after games (for ML training)
- Phase 6: Publish data for website consumption

## Current State
- Schema tables exist but are empty: prediction_results, system_daily_performance
- Views exist that will work once data exists
- Phase 5B (grading) not yet implemented

## Questions for Design
1. **What data does the website need?**
   - Daily predictions summary?
   - System accuracy leaderboard?
   - Player-specific accuracy history?
   - Confidence calibration charts?

2. **Aggregation levels**
   - Per-prediction detail vs daily summary vs rolling 30-day?
   - By system, by player, by team?

3. **Update frequency**
   - Real-time as predictions are made?
   - Batch after all games complete?
   - Rolling window recalculation?

4. **Relationship to grading**
   - Should Phase 6 depend on Phase 5B completing?
   - Or can predictions be published before grading?

## Existing Schema to Review

### system_daily_performance
- overall_accuracy, avg_prediction_error, rmse
- over_accuracy, under_accuracy
- high_conf_predictions, high_conf_accuracy
- confidence_calibration_score

### prediction_results
- prediction_id, predicted_recommendation, actual_result
- within_3_points, within_5_points
- line_margin, actual_margin
- key_factors (JSON)

## What Should Phase 6 Processor Do?
Please suggest the core responsibilities of a Phase 6 Publishing Processor.
```

---

## Next Steps for Session 112

### Immediate Tasks
1. **Commit schema changes** (see commands above)
2. **Implement grading processor:**
   - `data_processors/grading/prediction_accuracy_processor.py`
   - `backfill_jobs/grading/prediction_accuracy_backfill.py`
3. **Test grading on Jan 1-7, 2022** (small date range)
4. **Backfill grading for Nov 6, 2021 - Jan 7, 2022** (~47k predictions)

### After Grading Works
5. Continue backfilling Jan 8+ dates (Phase 4 → MLFS → Predictions → Grading)
6. Target: Complete 2021-22 season backfill
7. Then: Design and implement Phase 6

### Quick Commands
```bash
# Verify schema was applied
bq show --schema nba_predictions.prediction_accuracy

# Check predictions to grade
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions_to_grade
FROM nba_predictions.player_prop_predictions
WHERE game_date <= '2022-01-07'"

# After implementing grading, test on one date
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy_backfill.py \
  --dates 2022-01-01
```

---

## Technical Notes

### Grading Logic Pseudocode
```python
def grade_predictions_for_date(game_date):
    # 1. Get predictions
    predictions = bq.query("""
        SELECT player_lookup, game_id, system_id,
               predicted_points, confidence_score, recommendation,
               line_value, referee_adjustment, pace_adjustment,
               similarity_sample_size, model_version
        FROM player_prop_predictions
        WHERE game_date = @date
    """)

    # 2. Get actuals
    actuals = bq.query("""
        SELECT player_lookup, points as actual_points
        FROM player_game_summary
        WHERE game_date = @date
    """)

    # 3. Join and compute
    for pred in predictions:
        actual = actuals.get(pred.player_lookup)
        if actual:
            graded = {
                **pred,
                'actual_points': actual.points,
                'absolute_error': abs(pred.predicted_points - actual.points),
                'signed_error': pred.predicted_points - actual.points,
                'prediction_correct': compute_correct(pred, actual),
                'predicted_margin': pred.predicted_points - pred.line_value,
                'actual_margin': actual.points - pred.line_value,
                'within_3_points': abs(pred.predicted_points - actual.points) <= 3,
                'within_5_points': abs(pred.predicted_points - actual.points) <= 5,
                'graded_at': datetime.now()
            }
            results.append(graded)

    # 4. Pre-delete for idempotency
    bq.query("DELETE FROM prediction_accuracy WHERE game_date = @date")

    # 5. Insert
    bq.insert_rows_json('prediction_accuracy', results)
```

### prediction_correct Logic
```python
def compute_correct(pred, actual):
    if pred.recommendation == 'PASS':
        return None  # Can't grade PASS recommendations

    if pred.line_value is None:
        return None

    went_over = actual.points > pred.line_value
    recommended_over = pred.recommendation == 'OVER'

    return went_over == recommended_over
```

---

## Session History

| Session | Focus | Key Outcome |
|---------|-------|-------------|
| 107 | January 2022 test | Found `upcoming_context` blocker |
| 108 | Synthetic context fix | PDC/PCF processors updated |
| 109 | Complete Phase 4 | 7/7 dates for all Phase 4 tables |
| 110 | MLFS backfill + Phase 6 analysis | MLFS 7/7, Phase 6 design needed |
| 111 | Grading schema + design | Schema updated, Phase 5B/6 clarified |

---

## Contact

Session conducted by Claude Code (Opus 4.5)
Previous session: Session 110 (MLFS Backfill)
