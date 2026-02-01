# Session 65 Handoff - 2026-02-01

## Session Summary

Continued V8 hit rate fix from Session 64. Deployed prediction worker, ran ML feature store backfill, regenerated Jan 9-28 predictions. **Hit rate improved but still significantly below healthy baseline.**

## Critical Finding: Hit Rate Still Degraded

### Results After Fix

| Period | All Predictions | Premium Picks (92+ conf, 3+ edge) |
|--------|-----------------|-----------------------------------|
| Jan 1-8 (healthy baseline) | 66.1% | **84.5%** |
| Jan 9-28 (after fix) | 53.1% | **52.5%** |
| **Gap** | -13 pts | **-32 pts** |

The Session 64 fix (deploying before backfill) improved hit rate from 50.4% to 53.1%, but there's still a massive gap vs the healthy period.

---

## Root Cause Hypothesis: Feature Version Mismatch

### The Problem

The CatBoost V8 model was trained with **33 features**, but the ML feature store now generates **37 features**.

```sql
-- Feature store has v37 records, not v33
SELECT game_date, feature_count, COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-09' AND game_date <= '2026-01-10'
GROUP BY 1, 2 ORDER BY 1, 2;

-- Results:
-- 2026-01-09 | 37 | 358
-- 2026-01-10 | 33 | 13   (old records)
-- 2026-01-10 | 37 | 296  (new records)
```

### Why This Matters

1. **Model Training**: CatBoost V8 was trained on 33 features with specific value distributions
2. **Feature Store Backfill**: The backfill we ran (Nov 13 - Jan 30) created 37-feature records
3. **Prediction Generation**: The backfill script uses the first 33 features from 37-feature records
4. **Potential Issues**:
   - Feature order might not match between v33 and v37
   - Additional features in v37 might have shifted column positions
   - Feature values might have different distributions

### Evidence of Mismatch

The ML challenger experiments (`docs/08-projects/current/ml-challenger-experiments/`) document that:
- New experiments use 37 features (v2_37features)
- V8 model was trained on 33 features (v2_33features)
- The extra 4 features are: `fatigue_score`, `shot_zone_mismatch_score`, `pace_score`, `usage_spike_score`

---

## Investigation Needed

### 1. Verify Feature Order Alignment

Check if the first 33 features in v37 records match the v33 feature order:

```python
# Feature names expected by CatBoost V8 (from ml/backfill_v8_predictions.py)
FEATURE_NAMES = [
    'points_avg_season', 'points_avg_last_10', 'minutes_avg_season',
    'minutes_avg_last_10', 'usage_rate_season', 'usage_rate_last_10',
    # ... (need to verify order matches feature store)
]
```

**Files to check:**
- `ml/backfill_v8_predictions.py` - FEATURE_NAMES list (line ~55)
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - feature generation
- `predictions/worker/prediction_systems/catboost_v8.py` - what the model expects

### 2. Compare Feature Distributions

```sql
-- Compare feature values between healthy and degraded periods
-- Check if specific features have anomalous values
SELECT
  game_date,
  ROUND(AVG(features[OFFSET(0)]), 2) as points_avg_season,
  ROUND(AVG(features[OFFSET(1)]), 2) as points_avg_last_10,
  -- ... check all 33 features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date IN ('2026-01-05', '2026-01-15')  -- healthy vs degraded
GROUP BY 1
```

### 3. Check Broken Features

From Session 49/62 investigations, these features are known to be broken:

| Feature | Status | Issue |
|---------|--------|-------|
| `pace_score` | 100% zeros | `opponent_pace_last_10` is NULL upstream |
| `usage_spike_score` | 100% zeros | `projected_usage_rate` is NULL (by design) |
| `team_win_pct` | Always 0.5 | Not passed to final record (fix committed) |
| `fatigue_score` | Partially broken | 95% zeros on some days |

---

## What Session 65 Completed

| Task | Status | Details |
|------|--------|---------|
| Deploy prediction worker | ✅ | Revision `prediction-worker-00054-jds`, commit `3b6772d6` |
| ML Feature Store backfill | ✅ | 77 days (Nov 13 - Jan 30), 19,946 players |
| Update CLAUDE.md | ✅ | Commit `6d1e30d5` - deploy-before-backfill rule |
| Fix backfill script | ✅ | Commit `da38ee61` - accept v37 features |
| Regenerate Jan 9-28 predictions | ✅ | 5,623 predictions |
| Mark old predictions superseded | ✅ | 6,186 records |
| Re-grade predictions | ✅ | 4,652 graded |

### Commits This Session

```
6d1e30d5 docs: Add deploy-before-backfill rule to CLAUDE.md
da38ee61 fix: Update backfill script to accept v37 feature store records
```

---

## Full TODO List

### P1 - Critical (Blocking Hit Rate)

1. **Investigate feature version mismatch** (THIS SESSION'S MAIN TASK)
   - Verify v33 vs v37 feature alignment
   - Check if feature positions shifted
   - Compare feature distributions between healthy/degraded periods

2. **Fix daily Vegas line source**
   - Daily mode uses Phase 3 (43% coverage)
   - Backfill mode uses raw tables (95% coverage)
   - Need to modify daily orchestration to use raw betting tables
   - Files: `data_processors/precompute/ml_feature_store/`

3. **Retrain model on v37 features** (if mismatch confirmed)
   - Current model trained on v33
   - Feature store now generates v37
   - May need new model training

### P2 - High Priority

4. **Add tracking fields to prediction schema**
   - `build_commit_sha` - Track which code version
   - `predicted_at` - When predictions were made
   - `feature_source_mode` - 'daily' vs 'backfill'
   - `critical_features` - JSON snapshot of key values
   - Status: Schema added (Session 64), worker code deployed

5. **Run challenger experiment `exp_20260201_current_szn`**
   - Priority experiment: Current season only training
   - Uses v37 features properly
   - Expected to avoid distribution issues
   - Location: `docs/08-projects/current/ml-challenger-experiments/`

6. **Fix broken features**
   - `pace_score`: Fix upstream `opponent_pace_last_10` NULL issue
   - `team_win_pct`: Backfill with committed fix
   - Files: `data_processors/analytics/upcoming_player_game_context/`

### P3 - Medium Priority

7. **Create prediction_execution_log table**
   - Design complete in Session 64
   - Schema: `schemas/bigquery/predictions/prediction_execution_log.sql`
   - Needs implementation in worker

8. **Add feature source mode tracking**
   - Track 'daily' vs 'backfill' in `ml_feature_store_v2`
   - Helps distinguish data quality issues by mode

9. **Deploy scheduled query for feature_health_daily**
   - Table: `nba_monitoring_west2.feature_health_daily`
   - Table created but scheduled query not set up

10. **Run all 6 challenger experiments**
    - `exp_20260201_dk_only` - DraftKings only
    - `exp_20260201_dk_bettingpros` - DraftKings BettingPros
    - `exp_20260201_recency_90d` - 90-day half-life
    - `exp_20260201_recency_180d` - 180-day half-life
    - `exp_20260201_current_szn` - Current season only (PRIORITY)
    - `exp_20260201_multi_book` - Multi-bookmaker

---

## Key Queries for Investigation

### Check Feature Store Coverage

```sql
-- Vegas line coverage by date
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(features[OFFSET(25)] IS NOT NULL AND features[OFFSET(25)] != 0) as has_vegas,
  ROUND(COUNTIF(features[OFFSET(25)] IS NOT NULL AND features[OFFSET(25)] != 0) * 100.0 / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-28'
GROUP BY 1 ORDER BY 1;
```

### Compare Healthy vs Degraded Period Features

```sql
-- Feature distributions comparison
SELECT
  CASE WHEN game_date <= '2026-01-08' THEN 'healthy' ELSE 'degraded' END as period,
  ROUND(AVG(features[OFFSET(0)]), 2) as f0_points_avg_season,
  ROUND(AVG(features[OFFSET(1)]), 2) as f1_points_avg_last_10,
  ROUND(AVG(features[OFFSET(25)]), 2) as f25_vegas_line,
  ROUND(AVG(features[OFFSET(26)]), 2) as f26_vegas_opening,
  ROUND(AVG(feature_quality_score), 1) as quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-28'
  AND feature_count = 37
GROUP BY 1;
```

### Hit Rate by Week

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-01'
  AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

---

## Key Files

| File | Purpose |
|------|---------|
| `ml/backfill_v8_predictions.py` | Prediction backfill script - has FEATURE_NAMES |
| `predictions/worker/prediction_systems/catboost_v8.py` | V8 model prediction logic |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature store generation |
| `docs/08-projects/current/feature-quality-monitoring/` | Investigation docs |
| `docs/08-projects/current/ml-challenger-experiments/` | Experiment definitions |

---

## Next Session Start Prompt

```
Continue investigating V8 hit rate degradation from Session 65.

Read first: docs/09-handoff/2026-02-01-SESSION-65-HANDOFF.md

Key Issue: Premium picks hit rate is 52.5% vs 84.5% baseline (32 pt gap).
Hypothesis: Feature version mismatch between v33 model and v37 feature store.

Priority Tasks:
1. Verify feature order alignment between v33 and v37
2. Compare feature distributions between healthy (Jan 1-8) and degraded (Jan 9-28) periods
3. Determine if model needs retraining on v37 features
4. If mismatch confirmed, run exp_20260201_current_szn challenger experiment
```

---

*Session 65 - 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
