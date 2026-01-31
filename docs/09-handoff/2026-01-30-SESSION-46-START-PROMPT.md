# Session 46 Start Prompt

Copy and paste the text below to start a new Claude Code session:

---

Continue work on NBA stats scraper pipeline. Session 45 completed a deep investigation using 6 parallel agents and discovered the **root cause** of the model performance collapse.

Read the handoff document first:
```
cat docs/09-handoff/2026-01-30-SESSION-45-DEEP-INVESTIGATION-HANDOFF.md
```

## Critical Finding: Data Corruption

**DNP (Did Not Play) players are being recorded with `points = 0` instead of `NULL`**

Evidence:
- Jan 2026: 32.7% zero-point games (vs 10-12% historical)
- Jan 27: 105 zero-point records, 0 DNP marked
- Star players like Kyrie Irving showing `points_avg_last_5 = 0.0`

Impact:
- `points_avg_last_5` mean dropped from 10.53 → 8.49 (-19.4%)
- Model under-predicts stars because their features are artificially lowered
- Training MAE: 4.02 vs Production MAE: 5.5+ explained by data quality difference

## Secondary Findings

1. **Model NEVER had edge over Vegas** - 4+ years, 277K+ predictions, always negative edge
2. **CatBoost V8 OVER predictions overshoot by +3.23 pts**
3. **Code bugs**: 30-day window approximation, DNP filtering in PPM, missing points = 0

## Priority Tasks for This Session

### Priority 1: Fix DNP Data Corruption (CRITICAL)

1. **Investigate where DNP handling broke**:
   ```bash
   # Check player_game_summary for DNP marking patterns
   bq query --use_legacy_sql=false "
   SELECT game_date,
          COUNT(*) as total,
          COUNTIF(is_dnp = TRUE) as dnp_marked,
          COUNTIF(points = 0) as zero_points,
          COUNTIF(points IS NULL) as null_points
   FROM nba_analytics.player_game_summary
   WHERE game_date >= '2026-01-20'
   GROUP BY 1 ORDER BY 1"
   ```

2. **Find the code that sets is_dnp**:
   - Look in `data_processors/analytics/player_game_summary/`
   - Find where `is_dnp` flag is set
   - Understand why it stopped working

3. **Fix the DNP handling** - Ensure DNP players get `points = NULL`

4. **Backfill corrupted data** - Reprocess Jan 2026 data

### Priority 2: Fix Feature Extraction

Location: `data_processors/precompute/ml_feature_store/feature_extractor.py`

```python
# Current (buggy):
points_list = [(g.get('points') or 0) for g in last_10_games]

# Should be:
points_list = [g.get('points') for g in last_10_games if g.get('points') is not None]
```

### Priority 3: Fix 30-Day Window Bug

Location: `data_processors/precompute/ml_feature_store/feature_extractor.py` lines 700-748

```python
# Current: Uses 30-day window approximation
WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 30 DAY)

# Should: Use actual last 10 games
```

## Files to Focus On

| File | Issue |
|------|-------|
| `data_processors/analytics/player_game_summary/*.py` | DNP handling |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Feature bugs |
| `predictions/worker/prediction_systems/catboost_v8.py` | OVER threshold |

## Quick Validation Commands

```bash
# Check current prediction accuracy
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions,
       ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as accuracy
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1 DESC"

# Check DNP data quality
bq query --use_legacy_sql=false "
SELECT game_date,
       COUNTIF(points = 0) as zero_pts,
       COUNTIF(is_dnp = TRUE) as dnp_marked
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1"
```

## Latest Commit

```
fe2e3871 docs: Add Sessions 43-45 investigation findings and V11 experiment results
```

## Key Learnings from Session 45

1. Data quality issues can masquerade as model issues
2. DNP handling is critical for rolling average features
3. The model never had edge over Vegas - this is fundamental
4. Time-based features (recency, seasonality) don't help

---

**Focus on fixing the DNP data corruption first - everything else depends on clean data.**
