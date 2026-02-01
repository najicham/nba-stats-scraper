# Multi-Model Monthly Retraining Strategy

**Created:** Session 69 (2026-02-01)
**Status:** Planning
**Goal:** Run multiple model versions in production, retrain monthly, compare performance

---

## Strategy Overview

Each month we train a new model and deploy it **alongside** existing models. All models make predictions, we track performance by `system_id`, and we can see which performs best over time.

```
January:   [V9] ──────────────────────────────────────►
February:        [V9_FEB] ────────────────────────────►
March:                     [V9_MAR] ──────────────────►
April:                               [V9_APR] ────────►
```

All models run in parallel. We retire models that underperform after 2-3 months of comparison.

---

## Naming Convention

| Component | Format | Example |
|-----------|--------|---------|
| **System ID** | `catboost_v9_{month}` | `catboost_v9_feb` |
| **Model File** | `catboost_v9_{month}_{date}.cbm` | `catboost_v9_feb_20260201.cbm` |
| **Experiment Name** | `V9_{MONTH}_MONTHLY` | `V9_FEB_MONTHLY` |

**Baseline model:** `catboost_v9` (original, trained Nov 2 - Jan 8)

---

## Monthly Workflow

### 1st of Each Month (Automated)

```
Cloud Scheduler triggers → Cloud Function runs → New model trained
```

The Cloud Function:
1. Trains on expanding window (Nov 2 → end of previous month)
2. Evaluates on last 7 days
3. Saves model to GCS
4. Registers in `ml_experiments` table
5. Notifies via Slack

### Manual Steps (Within 48 Hours)

1. **Review results** in `ml_experiments`
2. **Create prediction system** for new model
3. **Deploy** prediction-worker with new system enabled
4. **Monitor** for 48-72 hours

---

## Implementation Plan

### Phase 1: Deploy February Model (This Week)

**Goal:** Get `catboost_v9_feb` running alongside `catboost_v9`

**Steps:**

1. **Create prediction system file**
   ```
   predictions/worker/prediction_systems/catboost_v9_feb.py
   ```
   - Copy from catboost_v9.py
   - Change SYSTEM_ID to `catboost_v9_feb`
   - Point to Feb model file

2. **Register in worker**
   - Add to prediction systems list
   - Enable alongside V9

3. **Deploy**
   ```bash
   ./bin/deploy-service.sh prediction-worker
   ```

4. **Verify**
   - Check predictions have both system_ids
   - Monitor for errors

### Phase 2: Automate Monthly Model Creation (This Month)

**Goal:** Cloud Function creates prediction system code automatically

**Enhancement to Cloud Function:**
1. Train model (already done)
2. Generate prediction system Python file
3. Commit to repo (or store in GCS for manual pickup)
4. Notify: "New model ready for deployment"

### Phase 3: Performance Dashboard (Future)

**Goal:** Easy comparison of all running models

```sql
-- Monthly model comparison
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) /
    NULLIF(COUNTIF(actual_points != line_value), 0), 1) as hit_rate,
  COUNTIF(ABS(predicted_points - line_value) >= 5) as high_edge_bets
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND system_id LIKE 'catboost_v9%'
GROUP BY system_id
ORDER BY hit_rate DESC
```

---

## Model Lifecycle

```
Month 1: Train → Deploy → Monitor
Month 2: Continue monitoring, train new model
Month 3: Compare 3 months of data
         → Retire worst performer if clear loser
         → Keep top 2-3 models running
```

**Retirement Criteria:**
- Model has 100+ high-edge predictions graded
- Hit rate is >5% worse than best performer
- Consistent underperformance for 4+ weeks

**Keep Running If:**
- Different models excel in different conditions
- No clear winner after 2 months
- Sample sizes still too small

---

## Prediction Worker Architecture

### Current (Single CatBoost)

```python
# worker.py
CATBOOST_VERSION = os.environ.get('CATBOOST_VERSION', 'v9')
# Only runs one CatBoost system
```

### Target (Multiple CatBoost)

```python
# worker.py
CATBOOST_MODELS = [
    'catboost_v9',      # Original baseline
    'catboost_v9_feb',  # February retrain
    # 'catboost_v9_mar',  # Added in March
]

# Each model runs and produces predictions with its own system_id
```

**Key Change:** Instead of picking ONE CatBoost version, run ALL active versions.

---

## Storage & Cleanup

### Model Files

```
models/
├── catboost_v9_33features_20260108.cbm      # Original V9
├── catboost_v9_feb_20260201.cbm             # February
├── catboost_v9_mar_20260301.cbm             # March (future)
└── ...
```

**Cleanup Policy:**
- Keep last 6 months of models
- Archive older models to GCS
- Never delete - just move to cold storage

### BigQuery Tables

All predictions go to same tables with different `system_id`:
- `player_prop_predictions` - All predictions
- `prediction_accuracy` - All graded results

No schema changes needed.

---

## Immediate Next Steps

### Task A: Create catboost_v9_feb.py (Sonnet)

```
Create predictions/worker/prediction_systems/catboost_v9_feb.py

Copy from catboost_v9.py with these changes:
1. SYSTEM_ID = "catboost_v9_feb"
2. MODEL_PATH points to the Feb retrain model
3. Update docstring with training dates (Nov 2 - Jan 31)

The Feb model file is: models/catboost_retrain_V9_FEB_RETRAIN_20260201_093024.cbm
Rename it to: models/catboost_v9_feb_20260201.cbm
```

### Task B: Update worker.py to run multiple CatBoost (Sonnet)

```
Modify predictions/worker/worker.py to:
1. Run both catboost_v9 and catboost_v9_feb
2. Each produces predictions with its own system_id
3. Both are included in the ensemble (or run separately)
```

### Task C: Deploy and Verify (Sonnet)

```
1. Deploy: ./bin/deploy-service.sh prediction-worker
2. Trigger a prediction run
3. Verify both system_ids appear in player_prop_predictions
```

---

## Questions to Decide

1. **Ensemble handling:** Should monthly models be part of the ensemble, or run independently?
   - Option A: Each CatBoost contributes to ensemble
   - Option B: Each CatBoost produces separate predictions (more data for comparison)
   - **Recommendation:** Option B initially (separate predictions) for clearer comparison

2. **How many models to run simultaneously?**
   - Recommendation: 3-4 max (current + last 2-3 months)
   - More models = more Cloud Run resources

3. **Auto-retirement:** Should we auto-retire underperformers?
   - Recommendation: Manual for now, automate later when we understand patterns

---

## Success Metrics

After 3 months of this strategy:

| Metric | Target |
|--------|--------|
| Models running | 3-4 |
| Predictions per model per day | ~50-100 |
| Clear performance comparison | Yes |
| Best model identified | Ideally |

---

## Change Log

| Date | Change |
|------|--------|
| 2026-02-01 | Created multi-model strategy document |

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
