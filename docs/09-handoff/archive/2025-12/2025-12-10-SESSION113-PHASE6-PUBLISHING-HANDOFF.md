# Session 113 Handoff - Phase 6 Publishing Design & Implementation

**Date:** 2025-12-10
**Focus:** Design and implement Phase 6 Publishing layer

---

## Executive Summary

This handoff provides all context needed to design and implement Phase 6 (Publishing), which prepares graded prediction data for website consumption. You will receive Claude Web responses to help guide design decisions.

---

## Current System State

### Data Pipeline Phases
```
Phase 1-2: Raw Data (NBA API) → BigQuery tables
Phase 3: Analytics (player_game_summary, team summaries)
Phase 4: Precompute (TDZA, PSZA, PCF, PDC, ML Feature Store)
Phase 5A: Predictions (5 systems generate points predictions)
Phase 5B: Grading (compare predictions to actual results) ✅ COMPLETE
Phase 6: Publishing (prepare data for website) ← YOU ARE HERE
```

### Current Data Status
| Table | Records | Dates | Status |
|-------|---------|-------|--------|
| player_prop_predictions | 47,395 | 62 | Complete |
| prediction_accuracy | 47,355 | 61 | Complete |
| system_daily_performance | 0 | 0 | **TO IMPLEMENT** |

### Grading Results (from Phase 5B)
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

**Key Insight:** Moving average baseline (95.3% win rate) beats ML models despite worse MAE. This is the "Win Rate vs MAE Paradox" - investigate as part of Phase 6.

---

## Files to Study

### CRITICAL - Read These First

1. **Phase 6 Design Questions Doc (sent to Claude Web):**
   ```
   docs/archive/2025-12/prompts/claude-web-phase6-design-review.md
   ```
   Contains 8 design questions for Claude Web review.

2. **Grading Processor (Pattern to Follow):**
   ```
   data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py
   ```
   ~390 lines. This is the pattern Phase 6 processor should follow.

3. **Grading Backfill Job (Pattern to Follow):**
   ```
   backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py
   ```
   ~366 lines. Includes checkpointing and progress tracking.

### Schema Files

4. **Prediction Accuracy Schema:**
   ```
   schemas/bigquery/nba_predictions/prediction_accuracy.sql
   ```

5. **Existing (Empty) Tables to Study:**
   ```sql
   -- Check what exists
   bq show nba_predictions.system_daily_performance
   bq show nba_predictions.prediction_results
   ```

### Reference Processors (Similar Patterns)

6. **ML Feature Store Processor:**
   ```
   data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
   ```
   Complex aggregation pattern - may be useful for rolling windows.

7. **Player Daily Cache Processor:**
   ```
   data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
   ```
   Daily aggregation pattern.

### Session History (Optional)

8. **Session 111 - Grading Schema Design:**
   ```
   docs/09-handoff/2025-12-10-SESSION111-GRADING-SCHEMA-AND-PHASE6-DESIGN.md
   ```

9. **Session 112 - Grading Implementation:**
   ```
   docs/09-handoff/2025-12-10-SESSION112-GRADING-PROCESSOR-IMPLEMENTED.md
   ```

---

## Phase 6 Design Questions

These questions were sent to Claude Web. Paste the responses into this session for guidance.

### Q1: Is grading all 5 systems separately correct?
Currently grading each system independently (5 records per player-game).

### Q2: What additional fields would improve ML training?
Current fields: absolute_error, signed_error, prediction_correct, within_3/5_points, margins

### Q3: Should we add confidence buckets for calibration?
Analyzing "when system says 80% confident, is it right 80% of the time?"

### Q4: How should PASS recommendations be handled?
Currently: prediction_correct = NULL for PASS

### Q5: What should Phase 6 actually do?
Options: Materialize views, Transform to JSON, Filter/curate, All of the above

### Q6: What update frequency is appropriate?
Options: Real-time, Batch daily, Incremental hourly

### Q7: How should Phase 6 relate to Phase 5B?
Run sequentially after grading? In parallel? Independently?

### Q8: What aggregations are needed for the website?
Rolling accuracy (7/30/season), by-system, by-player, by-confidence, etc.

---

## Proposed Phase 6 Structure

Based on Session 111-112 discussions:

### system_daily_performance Table
```sql
CREATE TABLE system_daily_performance (
  -- Keys
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

  -- Volume
  total_predictions INTEGER,
  graded_predictions INTEGER,

  -- Accuracy Metrics
  mean_absolute_error NUMERIC(5, 2),
  root_mean_squared_error NUMERIC(5, 2),
  signed_error_bias NUMERIC(5, 2),

  -- Win Rate
  total_recommendations INTEGER,  -- excluding PASS
  correct_recommendations INTEGER,
  win_rate NUMERIC(5, 3),

  -- Threshold Accuracy
  within_3_points_pct NUMERIC(5, 3),
  within_5_points_pct NUMERIC(5, 3),

  -- Confidence Analysis
  high_conf_predictions INTEGER,
  high_conf_win_rate NUMERIC(5, 3),

  -- Rolling Windows (7-day, 30-day)
  rolling_7d_mae NUMERIC(5, 2),
  rolling_7d_win_rate NUMERIC(5, 3),
  rolling_30d_mae NUMERIC(5, 2),
  rolling_30d_win_rate NUMERIC(5, 3),

  -- Metadata
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id;
```

### Implementation Steps

1. **Create Processor:**
   ```
   data_processors/publishing/system_daily_performance/
   ├── __init__.py
   └── system_daily_performance_processor.py
   ```

2. **Create Backfill Job:**
   ```
   backfill_jobs/publishing/system_daily_performance/
   ├── __init__.py
   └── system_daily_performance_publishing_backfill.py
   ```

3. **Logic Flow:**
   ```python
   def process_date(game_date):
       # 1. Load graded predictions for the date
       graded = load_from_prediction_accuracy(game_date)

       # 2. Aggregate by system_id
       for system_id in ['ensemble_v1', 'xgboost_v1', ...]:
           system_data = graded[graded.system_id == system_id]

           # 3. Compute metrics
           metrics = {
               'mean_absolute_error': system_data.absolute_error.mean(),
               'win_rate': system_data.prediction_correct.mean(),
               ...
           }

           # 4. Compute rolling windows (requires historical data)
           rolling_7d = compute_rolling_window(system_id, game_date, days=7)
           rolling_30d = compute_rolling_window(system_id, game_date, days=30)

       # 5. Write to BigQuery
       write_to_system_daily_performance(results)
   ```

---

## Key Implementation Patterns

### 1. Safe Float Handling (from grading processor)
```python
def _safe_float(self, value) -> Optional[float]:
    """Convert to float, handling None and NaN."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return float(value)
```

### 2. Boolean JSON Serialization
```python
# Always convert numpy bools to Python bools
'prediction_correct': bool(value) if value is not None else None
```

### 3. Idempotent Processing
```python
# Pre-delete before insert
self._delete_existing_data(game_date)
self._insert_new_data(results)
```

### 4. Checkpointing (from backfill job)
```python
checkpoint = BackfillCheckpoint('system_daily_performance_publishing')
completed = checkpoint.get_completed_dates()
remaining = [d for d in dates if d not in completed]
```

---

## Verification Commands

```bash
# Check current graded data
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

# Check if system_daily_performance exists
bq show nba_predictions.system_daily_performance

# After implementation - verify
bq query --use_legacy_sql=false "
SELECT game_date, system_id, mean_absolute_error, win_rate
FROM nba_predictions.system_daily_performance
ORDER BY game_date DESC, system_id
LIMIT 20"
```

---

## Win Rate vs MAE Paradox Investigation

**Question:** Why does moving_average (worst MAE 4.63) have best win rate (95.3%)?

**Hypothesis:** Conservative predictions win more bets because:
1. Lines are already priced efficiently
2. Regression to mean beats edge-seeking
3. Under-prediction (-2.03 bias) aligns with how lines are set

**Analysis to Add in Phase 6:**
```python
# Track these metrics to understand the paradox
'predictions_over': count where recommendation == 'OVER',
'predictions_under': count where recommendation == 'UNDER',
'over_win_rate': win rate for OVER picks,
'under_win_rate': win rate for UNDER picks,
'avg_confidence_over': average confidence for OVER,
'avg_confidence_under': average confidence for UNDER,
```

---

## Expected Deliverables

1. **Schema:** `schemas/bigquery/nba_predictions/system_daily_performance.sql`
2. **Processor:** `data_processors/publishing/system_daily_performance/system_daily_performance_processor.py`
3. **Backfill Job:** `backfill_jobs/publishing/system_daily_performance/system_daily_performance_publishing_backfill.py`
4. **Populated Table:** `nba_predictions.system_daily_performance` with all 61 dates

---

## Claude Web Responses Section

**Paste Claude Web responses to the 8 design questions below:**

### Response to Q1 (Grade all 5 systems?):
[PASTE HERE]

### Response to Q2 (Additional ML fields?):
[PASTE HERE]

### Response to Q3 (Confidence buckets?):
[PASTE HERE]

### Response to Q4 (PASS handling?):
[PASTE HERE]

### Response to Q5 (What should Phase 6 do?):
[PASTE HERE]

### Response to Q6 (Update frequency?):
[PASTE HERE]

### Response to Q7 (Relationship to Phase 5B?):
[PASTE HERE]

### Response to Q8 (Aggregations needed?):
[PASTE HERE]

---

## Files to Commit (from Session 112)

These files were created in Session 112 but may not be committed yet:
```bash
git add data_processors/grading/
git add backfill_jobs/grading/
git add docs/archive/2025-12/prompts/claude-web-phase6-design-review.md
git add docs/09-handoff/2025-12-10-SESSION112-GRADING-PROCESSOR-IMPLEMENTED.md
git add docs/09-handoff/2025-12-10-SESSION113-PHASE6-PUBLISHING-HANDOFF.md

git commit -m "feat: Add Phase 5B grading processor and Phase 6 handoff

- Grading processor compares predictions to actual results
- Grading backfill job with checkpointing
- 47,355 predictions graded across 61 dates
- Phase 6 design doc for Claude web review
- Phase 6 handoff doc with implementation guidance

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Contact

Session 113 prepared by Claude Code (Opus 4.5)
Previous sessions: 111 (Schema Design), 112 (Grading Implementation)
