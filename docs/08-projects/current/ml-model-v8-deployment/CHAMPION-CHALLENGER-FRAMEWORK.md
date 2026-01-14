# Champion/Challenger Model Framework

**Created:** 2026-01-10
**Updated:** 2026-01-14
**Current Champion:** `catboost_v8`

---

## Quick Links

- [Training Data Strategy](./TRAINING-DATA-STRATEGY.md) - When and how to train new models
- [Performance Analysis Guide](./PERFORMANCE-ANALYSIS-GUIDE.md) - Monitoring and grading
- [Improvement Journey](./IMPROVEMENT-JOURNEY.md) - Model evolution history

---

## Key Insight: More Data ≠ Better Performance

**Experiment (Jan 2026):** Trained challenger V10 with 48% more data (through Jan 2026).
**Result:** V8 (older data) still wins 52.3% head-to-head on production picks.

**Recommended training window:** 2.5-3 seasons (not all available data)
**See:** [TRAINING-DATA-STRATEGY.md](./TRAINING-DATA-STRATEGY.md) for full analysis.

---

## Overview

This document describes how to test, compare, and promote new prediction models in the NBA Props platform.

### The Framework

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MODEL LIFECYCLE                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   1. DEVELOPMENT          2. SHADOW MODE         3. CHAMPION        │
│   ──────────────          ──────────────         ──────────         │
│   • Train new model       • Run alongside        • Production       │
│   • Local validation        champion              picks             │
│   • Feature engineering   • Backfill 4 seasons   • Daily grading    │
│                           • Compare performance  • Monitoring       │
│                           • Statistical tests    • Alerts           │
│                                                                      │
│        ──────►                  ──────►                              │
│                                                                      │
│   Promotion Criteria:                                                │
│   • 3%+ better win rate for 7+ days                                 │
│   • MAE at least 0.2 points lower                                   │
│   • Minimum 100 predictions in test period                          │
│   • Statistical significance (p < 0.05)                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step 1: Adding a New Model (e.g., catboost_v9)

### 1.1 Create the Model Class

Create a new prediction system in `predictions/worker/prediction_systems/`:

```python
# predictions/worker/prediction_systems/catboost_v9.py
class CatBoostV9:
    def __init__(self):
        self.system_id = 'catboost_v9'
        self.system_name = 'CatBoost V9'
        self.version = '9.0'
        # Load your trained model
        self.model = self._load_model()

    def predict(self, features, player_lookup, game_date, prop_line=None):
        # Return: (predicted_points, confidence, recommendation, metadata)
        ...
```

### 1.2 Register in Worker

Add the new system to `predictions/worker/worker.py`:

```python
# Import new system
from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9

# Initialize (in shadow mode - doesn't affect production)
_catboost_v9 = CatBoostV9()
```

### 1.3 Add to Shadow Mode Runner

Update `predictions/shadow_mode_runner.py` to include the new model:

```python
# Add V9 to comparison
v9_model = CatBoostV9()
v9_pred, v9_conf, v9_rec, v9_meta = v9_model.predict(...)
```

---

## Step 2: Backfill Historical Predictions

### 2.1 Create Backfill Script

Use the existing template from `ml/backfill_v8_predictions.py`:

```bash
# Copy and modify for your new model
cp ml/backfill_v8_predictions.py ml/backfill_v9_predictions.py
```

Key modifications:
- Update `system_id` to `'catboost_v9'`
- Import your new model class
- Adjust feature requirements if needed

### 2.2 Run Backfill

```bash
# Backfill all historical dates (4 seasons)
PYTHONPATH=. python ml/backfill_v9_predictions.py

# Or resume from a specific date
PYTHONPATH=. python ml/backfill_v9_predictions.py --start-date 2024-01-01

# Dry run first
PYTHONPATH=. python ml/backfill_v9_predictions.py --dry-run
```

### 2.3 Verify Prediction Backfill

```sql
-- Check backfill completeness
SELECT
    system_id,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date,
    COUNT(*) as total_predictions,
    COUNTIF(current_points_line IS NOT NULL AND current_points_line != 20) as real_lines
FROM nba_predictions.player_prop_predictions
WHERE system_id IN ('catboost_v8', 'catboost_v9')
GROUP BY system_id
```

### 2.4 Run Grading Backfill (Phase 5B) - CRITICAL

**This step is required for fair comparisons.** Without grading, predictions exist but aren't evaluated against actual results.

```bash
# Grade all predictions against actual game results
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-02 --end-date 2026-01-08
```

This will:
- Read predictions from `player_prop_predictions`
- Match against actual points from `player_game_summary`
- Write graded results to `prediction_accuracy`
- Takes ~20-30 minutes for 4 seasons

### 2.5 Regenerate Daily Performance (Phase 5C)

After grading, regenerate the aggregated daily performance table:

```bash
PYTHONPATH=. .venv/bin/python data_processors/grading/system_daily_performance/system_daily_performance_processor.py \
  --start-date 2021-11-02 --end-date 2026-01-08
```

### 2.6 Verify Grading Complete

```sql
-- Check grading coverage matches predictions
SELECT
    system_id,
    COUNT(*) as graded_predictions,
    MIN(game_date) as first_graded,
    MAX(game_date) as last_graded,
    ROUND(COUNTIF(prediction_correct) / COUNTIF(recommendation IN ('OVER', 'UNDER')) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v8', 'catboost_v9')
GROUP BY system_id
```

---

## Step 3: Compare Performance

### 3.1 Run Historical Comparison

```sql
-- Compare systems over historical data
WITH graded AS (
    SELECT
        pa.system_id,
        pa.game_date,
        pa.recommendation,
        pa.prediction_correct,
        pa.absolute_error,
        pa.line_value
    FROM nba_predictions.prediction_accuracy pa
    WHERE pa.line_value IS NOT NULL
      AND pa.line_value != 20  -- Exclude fake lines
      AND pa.recommendation IN ('OVER', 'UNDER')
      AND pa.system_id IN ('catboost_v8', 'catboost_v9')
)
SELECT
    system_id,
    COUNT(*) as picks,
    COUNTIF(prediction_correct) as wins,
    ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 2) as win_rate_pct,
    ROUND(AVG(absolute_error), 2) as mae
FROM graded
GROUP BY system_id
ORDER BY win_rate_pct DESC
```

### 3.2 Compare by Season

```sql
SELECT
    system_id,
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as picks,
    ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 2) as win_rate_pct,
    ROUND(AVG(absolute_error), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE line_value IS NOT NULL
  AND line_value != 20
  AND recommendation IN ('OVER', 'UNDER')
  AND system_id IN ('catboost_v8', 'catboost_v9')
GROUP BY system_id, year
ORDER BY year DESC, system_id
```

### 3.3 Compare by Confidence Tier

```sql
SELECT
    system_id,
    CASE
        WHEN confidence_score >= 0.90 THEN 'high_90+'
        WHEN confidence_score >= 0.80 THEN 'medium_80-89'
        WHEN confidence_score >= 0.70 THEN 'low_70-79'
        ELSE 'pass_<70'
    END as confidence_tier,
    COUNT(*) as picks,
    ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 2) as win_rate_pct
FROM nba_predictions.prediction_accuracy
WHERE line_value IS NOT NULL
  AND line_value != 20
  AND recommendation IN ('OVER', 'UNDER')
  AND system_id IN ('catboost_v8', 'catboost_v9')
GROUP BY system_id, confidence_tier
ORDER BY system_id, confidence_tier
```

---

## Step 4: Daily Monitoring

### 4.1 System Performance Alert

The `system_performance_alert` Cloud Function runs daily and:
- Compares champion's 7-day vs 30-day performance
- Alerts if any challenger outperforms champion by 3%+
- Sends daily summary to Slack

```bash
# Deploy the alert
gcloud functions deploy system-performance-alert \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source orchestration/cloud_functions/system_performance_alert \
    --entry-point check_system_performance \
    --trigger-http \
    --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=xxx
```

### 4.2 Add New System to Monitoring

Update `data_processors/publishing/system_performance_exporter.py`:

```python
SYSTEM_METADATA = {
    'catboost_v8': {..., 'is_primary': True},
    'catboost_v9': {  # Add new challenger
        'display_name': 'CatBoost V9',
        'description': 'Improved CatBoost with new features',
        'is_primary': False,
        'ranking': 2
    },
    ...
}
```

---

## Step 5: Promotion Decision

### 5.1 Promotion Criteria

A challenger is ready for promotion when ALL of these are met:

| Criterion | Threshold | Verification Query |
|-----------|-----------|-------------------|
| Win Rate Advantage | ≥3% better for 7+ days | `check_7d_win_rate` |
| MAE Improvement | ≥0.2 points lower | `check_mae_improvement` |
| Sample Size | ≥100 picks in test period | `check_sample_size` |
| Statistical Significance | p < 0.05 | `run_significance_test` |
| High-Confidence Performance | Maintains 90%+ tier accuracy | `check_high_conf_tier` |

### 5.2 Promotion SQL Check

```sql
-- Full promotion decision query
WITH system_perf AS (
    SELECT
        system_id,
        COUNT(*) as picks,
        COUNTIF(prediction_correct) as wins,
        ROUND(COUNTIF(prediction_correct) / COUNT(*), 4) as win_rate,
        ROUND(AVG(absolute_error), 3) as mae
    FROM nba_predictions.prediction_accuracy
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND line_value IS NOT NULL
      AND line_value != 20
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY system_id
)
SELECT
    challenger.system_id as challenger,
    champion.system_id as champion,
    challenger.win_rate as challenger_wr,
    champion.win_rate as champion_wr,
    ROUND(challenger.win_rate - champion.win_rate, 4) as wr_advantage,
    ROUND(champion.mae - challenger.mae, 3) as mae_improvement,
    challenger.picks as challenger_picks,
    CASE
        WHEN challenger.win_rate - champion.win_rate >= 0.03
         AND champion.mae - challenger.mae >= 0.2
         AND challenger.picks >= 100
        THEN 'READY_FOR_PROMOTION'
        ELSE 'NEEDS_MORE_DATA'
    END as decision
FROM system_perf challenger
CROSS JOIN system_perf champion
WHERE champion.system_id = 'catboost_v8'
  AND challenger.system_id = 'catboost_v9'
```

### 5.3 Execute Promotion

When ready to promote:

1. **Update exporters** to use new system:
   ```bash
   # Replace 'catboost_v8' with 'catboost_v9' in all exporters
   grep -r "catboost_v8" data_processors/publishing/ --include="*.py"
   ```

2. **Update system metadata**:
   ```python
   # In system_performance_exporter.py
   SYSTEM_METADATA = {
       'catboost_v9': {..., 'is_primary': True},  # New champion
       'catboost_v8': {..., 'is_primary': False}, # Demoted
       ...
   }
   ```

3. **Update monitoring**:
   ```python
   # In system_performance_alert/main.py
   CHAMPION_SYSTEM = 'catboost_v9'
   ```

4. **Deploy changes** and monitor for 24-48 hours.

---

## Quick Reference: Adding catboost_v9

```bash
# 1. Create model class
vim predictions/worker/prediction_systems/catboost_v9.py

# 2. Create backfill script
cp ml/backfill_v8_predictions.py ml/backfill_v9_predictions.py
# Edit to use catboost_v9

# 3. Run prediction backfill (Phase 5A, ~20 min)
PYTHONPATH=. python ml/backfill_v9_predictions.py

# 4. Verify prediction backfill
bq query "SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
          WHERE system_id = 'catboost_v9' GROUP BY 1"

# 5. Run grading backfill (Phase 5B, ~20 min) - CRITICAL!
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-02 --end-date 2026-01-08

# 6. Regenerate daily performance (Phase 5C, ~5 min)
PYTHONPATH=. .venv/bin/python data_processors/grading/system_daily_performance/system_daily_performance_processor.py \
  --start-date 2021-11-02 --end-date 2026-01-08

# 7. Verify grading complete
bq query "SELECT system_id, COUNT(*) as graded,
          ROUND(COUNTIF(prediction_correct)/COUNTIF(recommendation IN ('OVER','UNDER'))*100,1) as win_rate
          FROM nba_predictions.prediction_accuracy WHERE system_id = 'catboost_v9' GROUP BY 1"

# 8. Run comparison report
PYTHONPATH=. python predictions/shadow_mode_report.py --systems catboost_v8,catboost_v9

# 9. Monitor daily via system_performance_alert

# 10. Promote when criteria met (update exporters + monitoring)
```

### Common Pitfall: Forgetting Grading Backfill

If you only run the prediction backfill (Step 3) without the grading backfill (Step 5), your new model will have:
- Predictions in `player_prop_predictions` ✓
- NO graded results in `prediction_accuracy` ✗
- Unfair comparisons (new model appears to have fewer picks)

---

## Files Reference

| Purpose | File |
|---------|------|
| Model Class Template | `predictions/worker/prediction_systems/catboost_v8.py` |
| Backfill Script Template | `ml/backfill_v8_predictions.py` |
| Shadow Mode Runner | `predictions/shadow_mode_runner.py` |
| Shadow Mode Report | `predictions/shadow_mode_report.py` |
| Daily Alert | `orchestration/cloud_functions/system_performance_alert/main.py` |
| System Metadata | `data_processors/publishing/system_performance_exporter.py` |
| Production Exporters | `data_processors/publishing/*_exporter.py` |

---

## Document History

| Date | Change |
|------|--------|
| 2026-01-10 | Initial creation - champion/challenger framework |
| 2026-01-10 | Added Phase 5B/5C grading backfill steps (critical for fair comparisons) |
