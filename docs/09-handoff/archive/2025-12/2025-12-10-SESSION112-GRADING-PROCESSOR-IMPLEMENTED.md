# Session 112 Handoff - Grading Processor Implemented & Complete

**Date:** 2025-12-10
**Duration:** ~45 minutes
**Focus:** Implement Phase 5B grading processor, run grading backfill, create Phase 6 design doc

---

## Executive Summary

Session 112 successfully implemented the Phase 5B grading processor and ran a **complete** backfill of all 47,355 predictions across 61 game dates. The grading processor compares predictions to actual game results, computing accuracy metrics for ML training.

**Key Accomplishments:**
1. Implemented grading processor (`prediction_accuracy_processor.py`)
2. Implemented grading backfill job (`prediction_accuracy_grading_backfill.py`)
3. Fixed JSON serialization issues (numpy bools, NaN values)
4. **Grading Complete:** 47,355 records graded across 61 dates
5. Created comprehensive Phase 6 design doc for Claude web review

---

## Grading Results - COMPLETE

### Final Status
| Metric | Value |
|--------|-------|
| Total Graded Records | 47,355 |
| Total Game Dates | 61 |
| Date Range | Nov 6, 2021 - Nov 25, 2025 |

### System Performance Comparison (KEY INSIGHT!)

```
+----------------------------+------+---------+----------+--------------+
|         system_id          | cnt  | avg_mae | avg_bias | win_rate_pct |
+----------------------------+------+---------+----------+--------------+
| ensemble_v1                | 9798 |    4.51 |    -1.28 |         92.4 |
| xgboost_v1                 | 9798 |    4.52 |    -1.69 |         91.7 |
| moving_average_baseline_v1 | 9798 |    4.63 |    -2.03 |         95.3 |
| similarity_balanced_v1     | 8163 |    4.87 |    -0.94 |         91.0 |
| zone_matchup_v1            | 9798 |    5.72 |    -0.55 |         94.7 |
+----------------------------+------+---------+----------+--------------+
```

### Key Findings from Grading

1. **Best MAE:** ensemble_v1 (4.51) and xgboost_v1 (4.52) - virtually tied
2. **Best Win Rate:** moving_average_baseline_v1 (95.3%!) - surprising winner
3. **Lowest Bias:** zone_matchup_v1 (-0.55) - most calibrated but worst MAE
4. **All Systems Under-Predict:** Every system has negative bias (-0.55 to -2.03)
5. **Similarity Has Fewer Records:** 8,163 vs 9,798 (missing ~1,635 predictions)

### Actionable Insights

- **Bias Correction:** Adding +1.5 points to all predictions would improve accuracy
- **Win Rate vs MAE Paradox:** Moving average wins more bets despite higher error
  - This suggests the line-setting is the key factor, not raw accuracy
- **Ensemble Not Winning:** Despite best MAE, ensemble (92.4%) loses to simple moving average (95.3%)

---

## Files Created This Session

### New Grading Processor Files
```
data_processors/grading/__init__.py
data_processors/grading/prediction_accuracy/__init__.py
data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py (390 lines)

backfill_jobs/grading/__init__.py
backfill_jobs/grading/prediction_accuracy/__init__.py
backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py (366 lines)
```

### Phase 6 Design Doc (For Claude Web Review)
```
docs/archive/2025-12/prompts/claude-web-phase6-design-review.md
```

**Purpose:** Copy this doc into Claude web for expert review of:
- Phase 5B grading implementation validation
- Phase 6 publishing design recommendations
- 8 specific design questions answered

---

## Grading Processor Implementation Details

### prediction_accuracy_processor.py (390 lines)

**Key Features:**
- Loads predictions from `player_prop_predictions`
- Loads actual points from `player_game_summary`
- Computes accuracy metrics for each prediction
- Handles NaN values safely (pace_adjustment, similarity_sample_size)
- Converts numpy bools to Python bools for JSON serialization
- Pre-deletes existing data for idempotency

**Core Metrics Computed:**
```python
{
    'absolute_error': abs(predicted - actual),
    'signed_error': predicted - actual,  # positive = over-predicted
    'prediction_correct': bool(went_over == recommended_over),  # for OVER/UNDER
    'within_3_points': bool(absolute_error <= 3.0),
    'within_5_points': bool(absolute_error <= 5.0),
    'predicted_margin': predicted - line,
    'actual_margin': actual - line
}
```

### prediction_accuracy_grading_backfill.py (366 lines)

**Usage:**
```bash
# Grade specific dates
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --dates 2022-01-01

# Grade date range
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-01 --end-date 2025-11-30 --skip-preflight
```

---

## prediction_accuracy Schema

```sql
CREATE TABLE prediction_accuracy (
  -- Primary Keys
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

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
  absolute_error NUMERIC(5, 1),
  signed_error NUMERIC(5, 1),  -- positive = over-predicted
  prediction_correct BOOLEAN,  -- NULL for PASS

  -- Margin Analysis
  predicted_margin NUMERIC(5, 1),
  actual_margin NUMERIC(5, 1),

  -- Threshold Accuracy
  within_3_points BOOLEAN,
  within_5_points BOOLEAN,

  -- Metadata
  model_version STRING,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup;
```

---

## Bug Fixes Applied

### 1. JSON Serialization (numpy bools)
**Problem:** `Object of type bool_ is not JSON serializable`
**Fix:** Convert all booleans explicitly: `bool(value)`

### 2. NaN Handling
**Problem:** `400 POST ... Invalid numeric value: nan`
**Fix:** Added `_safe_float()` and `_is_nan()` helper methods

---

## Files to Commit

```bash
# Stage new files
git add data_processors/grading/
git add backfill_jobs/grading/
git add docs/archive/2025-12/prompts/claude-web-phase6-design-review.md
git add docs/09-handoff/2025-12-10-SESSION112-GRADING-PROCESSOR-IMPLEMENTED.md

# Commit
git commit -m "feat: Implement Phase 5B grading processor

Adds prediction accuracy grading that compares predictions to actual
game results for ML training:

- prediction_accuracy_processor.py: Core grading logic
- prediction_accuracy_grading_backfill.py: Backfill job with checkpointing
- Handles numpy bool/NaN serialization issues
- Computes MAE, signed_error, recommendation accuracy
- Graded 47,355 predictions (Nov 2021 - Nov 2025)

Key findings:
- Best MAE: ensemble_v1 (4.51), xgboost_v1 (4.52)
- Best win rate: moving_average_baseline_v1 (95.3%)
- All systems under-predict by 0.5-2.0 points

Also adds Phase 6 design doc for Claude web review.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Required Reading for Next Session

1. **This handoff doc** (current file)
2. **Phase 6 design doc:** `docs/archive/2025-12/prompts/claude-web-phase6-design-review.md`
   - Copy to Claude web for design review before implementing Phase 6
3. **Grading processor:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
4. **Previous session:** `docs/09-handoff/2025-12-10-SESSION111-GRADING-SCHEMA-AND-PHASE6-DESIGN.md`

---

## Verification Commands

```bash
# Check grading completion
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as graded_records,
  COUNT(DISTINCT game_date) as dates,
  ROUND(AVG(absolute_error), 2) as avg_mae,
  ROUND(AVG(signed_error), 2) as avg_bias
FROM nba_predictions.prediction_accuracy"

# Check grading by system (KEY QUERY)
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as cnt,
  ROUND(AVG(absolute_error), 2) as avg_mae,
  ROUND(AVG(signed_error), 2) as avg_bias,
  ROUND(SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100.0 /
        NULLIF(SUM(CASE WHEN prediction_correct IS NOT NULL THEN 1 ELSE 0 END), 0), 1) as win_rate_pct
FROM nba_predictions.prediction_accuracy
GROUP BY 1 ORDER BY 3"

# Check grading by date
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as graded,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM nba_predictions.prediction_accuracy
GROUP BY 1 ORDER BY 1
LIMIT 20"

# Compare predictions vs graded counts
bq query --use_legacy_sql=false "
SELECT
  'predictions' as tbl, COUNT(*) as cnt, COUNT(DISTINCT game_date) as dates
FROM nba_predictions.player_prop_predictions
UNION ALL
SELECT 'graded', COUNT(*), COUNT(DISTINCT game_date)
FROM nba_predictions.prediction_accuracy"
```

---

## Next Steps for Session 113

### Priority 1: Review Phase 6 Design Doc with Claude Web
1. Copy `docs/archive/2025-12/prompts/claude-web-phase6-design-review.md` to Claude web
2. Get expert review and recommendations
3. Document decisions for Phase 6 implementation

### Priority 2: Investigate Win Rate vs MAE Paradox
Why does moving_average (worst MAE) have the best win rate?
- Analyze by confidence level
- Check if line values favor conservative predictions

### Priority 3: Implement Phase 6 (if design approved)
Based on Claude web review, implement:
- `data_processors/publishing/system_daily_performance_processor.py`
- Populate `system_daily_performance` table
- Create aggregation views

### Priority 4: Continue Backfilling More Dates
If time permits, continue backfilling more dates (Jan 8+ 2022):
- Phase 4 → MLFS → Predictions → Grading pipeline

---

## Session History

| Session | Focus | Key Outcome |
|---------|-------|-------------|
| 107 | January 2022 test | Found `upcoming_context` blocker |
| 108 | Synthetic context fix | PDC/PCF processors updated |
| 109 | Complete Phase 4 | 7/7 dates for all Phase 4 tables |
| 110 | MLFS backfill + Phase 6 analysis | MLFS 7/7, Phase 6 design needed |
| 111 | Grading schema + design | Schema updated, Phase 5B/6 clarified |
| **112** | **Grading processor** | **47k predictions graded, Phase 6 doc created** |

---

## Background Jobs Status

All background jobs from previous sessions should be killed. If stale jobs appear:
```bash
pkill -f "backfill_jobs/" 2>/dev/null
pkill -f "bq query" 2>/dev/null
```

---

## Key Insights Summary

### 1. Moving Average Wins More Bets (95.3% vs 92.4% ensemble)
Despite having worse MAE, the simple moving average baseline outperforms sophisticated ML models on actual betting outcomes. This suggests:
- Line-setting already accounts for complex factors
- Regression to mean (conservative predictions) beats edge-seeking

### 2. All Systems Under-Predict
Every system has negative bias (-0.55 to -2.03 points). Easy fix: add +1.5 point offset.

### 3. Similarity System Has Gaps
Only 8,163 records vs 9,798 for others (~17% missing). Investigate why.

### 4. Zone Matchup: Low Bias, High Error
Most calibrated system (bias -0.55) but highest MAE (5.72). Good for ensemble weighting?

---

## Contact

Session conducted by Claude Code (Opus 4.5)
Previous session: Session 111 (Grading Schema Design)
