# CatBoost V9 Promotion Plan

**Created:** 2026-02-01 (Session 67)
**Status:** READY FOR IMPLEMENTATION

---

## Model Specification

### V9 Identity

| Property | Value |
|----------|-------|
| Model ID | `catboost_v9` |
| Training Approach | **Current Season Only** |
| Training Period | Nov 2, 2025 → Jan 8, 2026 (68 days) |
| Training Samples | 9,993 |
| Features | 33 (same as V8) |
| Source File | `models/catboost_retrain_exp_20260201_current_szn_20260201_011018.cbm` |

### Performance (Evaluated on Jan 9-31, 2026)

| Metric | V9 | V8 (True) | Improvement |
|--------|-----|-----------|-------------|
| MAE | 4.82 | 5.36 | -0.54 ✅ |
| Hit Rate (all) | 52.9% | 53.1% | ≈ |
| Hit Rate (high-edge 5+) | **72.2%** | 56.9% | +15.3% ✅ |
| Hit Rate (premium) | **56.5%** | 52.5% | +4.0% ✅ |

### Key Differentiator: Current Season Training

Unlike V8 (trained on 2021-2024 historical data), V9 is trained on **current season only**:

1. **Avoids historical data quality issues** - team_win_pct bug, Vegas imputation mismatch
2. **Captures current player roles** - trades, injuries, lineup changes
3. **Reflects current league trends** - pace, three-point rates, etc.
4. **Retrainable monthly** - as season progresses, training window grows

---

## Promotion Checklist

### Phase 1: Model Setup

- [ ] **1.1 Rename model file**
  ```bash
  cp models/catboost_retrain_exp_20260201_current_szn_20260201_011018.cbm \
     models/catboost_v9_33features_20260201_011018.cbm
  ```

- [ ] **1.2 Upload to GCS**
  ```bash
  gsutil cp models/catboost_v9_33features_20260201_011018.cbm \
     gs://nba-props-platform-models/catboost/v9/
  ```

- [ ] **1.3 Register in ml_model_registry**
  ```sql
  INSERT INTO nba_predictions.ml_model_registry
  (model_id, model_version, model_path, training_start_date, training_end_date,
   training_samples, feature_count, feature_version, mae, notes, created_at, status)
  VALUES
  ('catboost_v9', 'v9_current_season',
   'gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260201_011018.cbm',
   '2025-11-02', '2026-01-08', 9993, 33, 'v2_33features', 4.82,
   'Current season only training. Session 67 experiment winner.',
   CURRENT_TIMESTAMP(), 'production');
  ```

### Phase 2: Code Changes

- [ ] **2.1 Create catboost_v9.py prediction system**
  - Copy from `catboost_v8.py`
  - Update model glob pattern: `catboost_v9_33features_*.cbm`
  - Update system_id: `catboost_v9`
  - Add training metadata to predictions

- [ ] **2.2 Update worker.py**
  - Add V9 to available systems
  - Keep V8 as fallback initially

- [ ] **2.3 Ensure features_snapshot is captured**
  - Already implemented in worker.py (v4.1)
  - Verify it includes all 9 key features

### Phase 3: Deployment

- [ ] **3.1 Deploy prediction-worker with V9**
  ```bash
  ./bin/deploy-service.sh prediction-worker
  ```

- [ ] **3.2 Verify deployment**
  ```bash
  # Check logs for V9 loading
  gcloud logging read 'resource.labels.service_name="prediction-worker"
    AND textPayload=~"catboost_v9"' --limit=10
  ```

### Phase 4: Validation

- [ ] **4.1 Generate predictions for a test date**
  - Use coordinator to trigger predictions
  - Verify predictions have `system_id = 'catboost_v9'`

- [ ] **4.2 Compare V9 vs V8 side-by-side**
  ```sql
  SELECT system_id, COUNT(*), AVG(confidence_score), AVG(predicted_points)
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
  GROUP BY system_id
  ```

- [ ] **4.3 Monitor for 48-72 hours**
  - Check prediction volume
  - Check error rates
  - Check confidence distribution

### Phase 5: Documentation

- [ ] **5.1 Update CLAUDE.md with V9 info**
- [ ] **5.2 Create V9 model card**
- [ ] **5.3 Update experiment plan with final status**

---

## Monthly Retraining Strategy

V9 uses current-season-only training. As the season progresses:

| Month | Training Window | Expected Samples |
|-------|-----------------|------------------|
| Feb | Nov 2 - Jan 31 | ~12,000 |
| Mar | Nov 2 - Feb 28 | ~15,000 |
| Apr | Nov 2 - Mar 31 | ~18,000 |
| Playoffs | Full season | ~20,000+ |

### Retraining Trigger

Retrain V9 when:
1. **Monthly cadence** - First week of each month
2. **Performance drop** - Hit rate drops below 52% for 7+ days
3. **Major roster changes** - Trade deadline, injuries to stars

### Retraining Command

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_$(date +%b)_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end $(date -d "yesterday" +%Y-%m-%d) \
    --eval-start $(date -d "7 days ago" +%Y-%m-%d) \
    --eval-end $(date -d "yesterday" +%Y-%m-%d) \
    --hypothesis "Monthly V9 retrain with expanded training window" \
    --tags "v9,monthly,production"
```

---

## Rollback Plan

If V9 underperforms in production:

1. **Immediate**: Switch back to V8 in worker.py
2. **Deploy**: `./bin/deploy-service.sh prediction-worker`
3. **Investigate**: Compare V9 vs V8 predictions for failing games

---

## Features Snapshot

The worker already captures `features_snapshot` for debugging:

```json
{
  "points_avg_last_5": 18.4,
  "points_avg_last_10": 17.8,
  "points_avg_season": 16.2,
  "vegas_points_line": 17.5,
  "has_vegas_line": 1,
  "minutes_avg_last_10": 32.5,
  "ppm_avg_last_10": 0.55,
  "fatigue_score": 85,
  "opponent_def_rating": 112.3
}
```

This allows us to:
1. Debug why a prediction was wrong
2. Verify features were computed correctly
3. Reproduce predictions for analysis

---

## Success Criteria

V9 is successful if (after 1 week in production):

| Metric | Target |
|--------|--------|
| Premium hit rate | ≥55% |
| High-edge hit rate | ≥65% |
| Prediction volume | Same as V8 |
| Error rate | <1% |

---

*Created: Session 67, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
