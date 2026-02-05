# Model Training Plan - New Named Models

**Session 124**

---

## Naming Convention

Format: `catboost_v9_{training_start}_{training_end}`

Example: `catboost_v9_20251102_20260131`

---

## Models to Train

### Model 1: catboost_v9_20251102_20260131

**Purpose:** Extended training with all available current-season data

| Property | Value |
|----------|-------|
| system_id | `catboost_v9_20251102_20260131` |
| Training Start | 2025-11-02 |
| Training End | 2026-01-31 |
| Eval Start | 2026-02-01 |
| Eval End | 2026-02-03 (extend as more data available) |
| Features | 33 (V9 contract) |

**Training Command:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_20251102_20260131_PROD" \
    --train-start 2025-11-02 \
    --train-end 2026-01-31 \
    --eval-start 2026-02-01 \
    --eval-end 2026-02-03 \
    --hypothesis "Extended training window for production naming" \
    --tags "production,naming-refresh,session-124"
```

### Model 2: catboost_v9_20251102_20260203

**Purpose:** Maximum training data (train through yesterday)

| Property | Value |
|----------|-------|
| system_id | `catboost_v9_20251102_20260203` |
| Training Start | 2025-11-02 |
| Training End | 2026-02-03 |
| Eval Start | N/A (no held-out eval) |
| Features | 33 (V9 contract) |

**Note:** This model has no held-out eval period. Use for production once Model 1 is validated.

**Training Command:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_20251102_20260203_PROD" \
    --train-start 2025-11-02 \
    --train-end 2026-02-03 \
    --eval-days 0 \
    --hypothesis "Maximum training data for production" \
    --tags "production,naming-refresh,session-124"
```

---

## Deployment Strategy

### Phase 1: Shadow Mode (1 week)
- Deploy both new models alongside existing `catboost_v9`
- Compare predictions daily
- Monitor for drift

### Phase 2: A/B Test (1 week)
- Route 20% of traffic to new model
- Compare hit rates

### Phase 3: Full Rollout
- If new model performs same or better, promote to production
- Keep old model as fallback

---

## Database Changes

### Option A: Add model_artifact_id (Recommended)

```sql
-- Add column to track specific model instance
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS model_artifact_id STRING;

-- Example values:
-- 'catboost_v9_20251102_20260131'
-- 'catboost_v9_20251102_20260203'
```

### Option B: Use model_file_name (Already Exists)

The `model_file_name` field already tracks specific model files:
- `catboost_v9_33features_20260201_011018.cbm`

Could standardize this to match our naming convention.

---

## Success Criteria

| Metric | Threshold |
|--------|-----------|
| MAE | ≤ current V9 (5.14) |
| Hit Rate (All) | ≥ 54% |
| Hit Rate (Edge 3+) | ≥ 63% |
| Hit Rate (Edge 5+) | ≥ 75% |
| Tier Bias (all tiers) | ≤ ±2 pts |

---

## Timeline

| Day | Action |
|-----|--------|
| Day 1 | Train Model 1, validate metrics |
| Day 2 | Deploy to shadow mode |
| Days 3-7 | Monitor shadow performance |
| Day 8 | Decision: promote or iterate |

---

*Session 124 - Model Training Plan*
