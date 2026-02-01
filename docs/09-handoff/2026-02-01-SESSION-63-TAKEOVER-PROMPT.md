# Session 63 Takeover Prompt

**Date:** 2026-02-01
**Status:** Investigation Complete - Ready to Execute Fix Plan
**Priority:** CRITICAL

---

## Quick Context

V8 model hit rate collapsed from **72.8%** (Jan 2025) to **55.5%** (Jan 2026). After extensive investigation in Session 63, we identified the **likely root cause**: daily orchestration started on Jan 9, 2026 and uses a different code path than backfill for Vegas line extraction.

**The smoking gun:**
- Jan 1-7: 62-70% hit rate (backfilled)
- Jan 9+: 40-58% hit rate (daily orchestration)

---

## Documents to Read (In Order)

### 1. Investigation Findings (Start Here)
```
docs/08-projects/current/feature-quality-monitoring/2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md
```
- All issues discovered during investigation
- Daily vs backfill code path differences
- Why team_win_pct hypothesis was DISPROVEN
- Broken features found (pace_score, usage_spike_score = 100% zeros)

### 2. Execution Plan (The Fix)
```
docs/08-projects/current/feature-quality-monitoring/V8-FIX-EXECUTION-PLAN.md
```
- Phase 1: Verify hypothesis on single date (Jan 12)
- Phase 2: Fix daily orchestration
- Phase 3: Add monitoring & timestamps
- Phase 4: Backfill & consider retrain

### 3. Vegas Line Root Cause (Session 62)
```
docs/08-projects/current/feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md
```
- Why backfill mode was introduced
- How Vegas extraction differs between daily and backfill
- The fix that was already implemented for backfill mode

### 4. Training Distribution Mismatch
```
docs/08-projects/current/ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md
```
- V8 was trained on data with team_win_pct = 0.5 for 100% of records
- Other feature distribution issues
- Why retraining on Nov 2025+ data may help

### 5. Feature Quality Monitoring README
```
docs/08-projects/current/feature-quality-monitoring/README.md
```
- Overall project status
- All issues found across sessions
- Action items and priorities

---

## Key Code Files to Understand

### Feature Extraction (Where the Bug Is)
```
data_processors/precompute/ml_feature_store/feature_extractor.py
```
- `get_players_with_games()` - Different queries for daily vs backfill (lines 85-199)
- `_batch_extract_vegas_lines()` - **THE KEY FUNCTION** - uses Phase 3 for daily, raw tables for backfill (lines 613-744)
- Session 62 already added backfill_mode support, but daily mode still uses Phase 3

### ML Feature Store Processor
```
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
```
- `process_date()` - Main processing logic
- `is_backfill_mode` - Flag that determines code path
- Line 638: Passes backfill_mode to feature extractor

---

## The Problem in One Sentence

**Daily orchestration uses Phase 3 for Vegas lines (43% coverage) while backfill uses raw betting tables (95% coverage), causing predictions to miss Vegas data for most players.**

---

## What to Do Next

### Phase 1: Verify Hypothesis (START HERE)

**Test Date:** `2026-01-12` (had 43.7% hit rate, 87 predictions)

```bash
# Step 1: Check current Vegas coverage
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(features[OFFSET(25)] > 0) as with_vegas,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as coverage_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-12'
  AND ARRAY_LENGTH(features) >= 33"

# Step 2: Save current predictions
bq query --use_legacy_sql=false --format=csv "
SELECT player_lookup, predicted_points, actual_points, prediction_correct, confidence_score
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date = '2026-01-12'
" > /tmp/predictions_jan12_before.csv

# Step 3: Create staging table for test
bq mk --table nba_predictions.ml_feature_store_v2_staging \
  --schema player_lookup:STRING,game_date:DATE,features:FLOAT64,feature_names:STRING
```

Then write a test script to:
1. Re-run feature store for Jan 12 with `backfill_mode=True`
2. Write to staging table
3. Compare Vegas coverage between production and staging
4. If coverage improves significantly (43% → 90%+), hypothesis confirmed

### Phase 2: Fix Daily Orchestration

**Recommended approach:** Modify `_batch_extract_vegas_lines()` to ALWAYS use raw betting tables.

The backfill mode query is already written (lines 651-715 in feature_extractor.py). Just need to make it the default for all modes.

---

## Key Metrics to Track

| Metric | Before Fix | Target |
|--------|------------|--------|
| Daily Vegas coverage | ~43% | >90% |
| Jan 9+ hit rate | 40-58% | >60% |
| Broken features detected | 0 | 2 |

---

## Verification Queries

### Check hit rate by date
```sql
SELECT game_date, COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND prediction_correct IS NOT NULL
  AND game_date >= '2026-01-01'
GROUP BY 1 ORDER BY 1
```

### Check Vegas coverage by month
```sql
SELECT FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_coverage
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

### Check broken features
```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(100.0 * COUNTIF(features[OFFSET(7)] = 0) / COUNT(*), 1) as pace_zero_pct,
  ROUND(100.0 * COUNTIF(features[OFFSET(8)] = 0) / COUNT(*), 1) as usage_spike_zero_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-01-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

---

## What We Ruled Out

| Hypothesis | Result | Evidence |
|------------|--------|----------|
| team_win_pct mismatch | DISPROVEN | Records with 0.5 do WORSE, not better |
| New players harder to predict | DISPROVEN | Returning players also degraded |
| Feature version change (33→37) | DISPROVEN | Same first 33 features |
| Betting line source change | DISPROVEN | All use ACTUAL_PROP |

---

## Files Changed in Sessions 62-63

```
M  .claude/skills/validate-daily/SKILL.md           # Added Vegas coverage check
M  data_processors/precompute/ml_feature_store/feature_extractor.py  # Backfill mode Vegas fix
M  data_processors/precompute/ml_feature_store/ml_feature_store_processor.py  # Pass backfill_mode
A  docs/08-projects/current/feature-quality-monitoring/2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md
A  docs/08-projects/current/feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md
A  docs/08-projects/current/feature-quality-monitoring/V8-FIX-EXECUTION-PLAN.md
M  docs/08-projects/current/feature-quality-monitoring/README.md
A  docs/08-projects/current/ml-challenger-training-strategy/V8-TRAINING-DISTRIBUTION-MISMATCH.md
```

---

## Session History

| Session | Date | Focus |
|---------|------|-------|
| 61 | 2026-02-01 | Discovered Vegas line drift |
| 62 | 2026-02-01 | Fixed backfill mode Vegas extraction |
| 63 | 2026-02-01 | Deep investigation, found daily vs backfill difference |

---

## Summary for New Session

1. **Read** the investigation findings and execution plan
2. **Verify** the hypothesis by testing Jan 12 with backfill mode
3. **Fix** daily orchestration to use raw betting tables
4. **Add** monitoring (feature_source_mode, predicted_at, broken feature detection)
5. **Backfill** Nov 2025 - Feb 2026 and consider retraining

The code fix is straightforward - the backfill mode Vegas query already exists. We just need to make it the default for daily mode too.

---

*Created: 2026-02-01 Session 63*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
