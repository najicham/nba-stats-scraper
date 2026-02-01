# ML Experimentation Roadmap

**Created:** 2026-02-01 (Session 67)
**Status:** ACTIVE
**Goal:** Continuously improve model performance through systematic experimentation

---

## Overview

This document outlines our strategy for:
1. Cleaning historical feature data
2. Running experiments to understand model behavior
3. Monthly retraining and model promotion
4. Learning from last season to predict this season's trajectory

---

## Part 1: Feature Store Cleanup

### Current State

| Season | Records | team_win_pct | Rolling Avgs | Vegas Coverage |
|--------|---------|--------------|--------------|----------------|
| 2025-26 | 23K | ✅ Real values | ✅ Clean | 26-46% |
| 2024-25 | 26K | ❌ 100% = 0.5 | ✅ Clean | ~25% |
| 2023-24 | 26K | ❌ 100% = 0.5 | ✅ Clean | ~25% |
| 2022-23 | ~25K | ❌ 100% = 0.5 | ⚠️ Unknown | ~20% |
| 2021-22 | ~25K | ❌ 100% = 0.5 | ⚠️ Unknown | ~15% |

### Cleanup Tasks

#### Task 1: Fix team_win_pct for 2024-25

```sql
-- Step 1: Create corrected team win percentages
CREATE OR REPLACE TABLE nba_analytics.team_win_pct_corrected AS
WITH game_results AS (
  SELECT
    team_abbr,
    game_date,
    CASE WHEN points > opponent_points THEN 1 ELSE 0 END as win,
    EXTRACT(YEAR FROM game_date) as season_year
  FROM nba_analytics.team_game_summary
  WHERE game_date >= '2021-10-01'
),
running_record AS (
  SELECT
    team_abbr,
    game_date,
    SUM(win) OVER (
      PARTITION BY team_abbr, season_year
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as wins_before,
    COUNT(*) OVER (
      PARTITION BY team_abbr, season_year
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as games_before
  FROM game_results
)
SELECT
  team_abbr,
  game_date,
  CASE
    WHEN games_before >= 5 THEN ROUND(wins_before / games_before, 4)
    ELSE 0.5
  END as team_win_pct
FROM running_record;

-- Step 2: Update feature store (via backfill job)
```

#### Task 2: Fix other zero-constant features

Features that need investigation/fixing:
- `pace_score` (100% = 0 in 2024-25)
- `usage_spike_score` (100% = 0 in 2024-25)
- `back_to_back` (100% = 0 in 2024-25)
- `injury_risk` (100% = 0 in 2024-25)

#### Task 3: Backfill Script

```bash
# Create backfill script
PYTHONPATH=. python bin/backfill_feature_store_historical.py \
    --season 2024-25 \
    --fix-team-win-pct \
    --fix-pace-score \
    --dry-run
```

### Cleanup Timeline

| Week | Task | Status |
|------|------|--------|
| Week 1 | Audit all seasons with `bin/audit_feature_store.py` | |
| Week 1 | Create team_win_pct correction table | |
| Week 2 | Create backfill script for 2024-25 | |
| Week 2 | Run 2024-25 backfill | |
| Week 3 | Verify 2024-25 data quality | |
| Week 3 | Backfill 2023-24 if needed | |

---

## Part 2: Last Season Analysis

### Goal

Train on 2024-25 data (similar dates to current season) to:
1. See how model performance evolved over the season
2. Identify when retraining was needed
3. Predict what to expect for 2025-26 second half

### Experiment: Simulate Last Season

```python
# Train on Nov 2024 - Jan 2025 (equivalent to current V9 training window)
# Evaluate on Feb - June 2025 to see performance trajectory

TRAINING_PERIODS = [
    # Equivalent to our current position
    ("2024-11-02", "2025-01-08", "initial"),  # ~9K samples

    # Monthly additions
    ("2024-11-02", "2025-01-31", "jan_retrain"),
    ("2024-11-02", "2025-02-28", "feb_retrain"),
    ("2024-11-02", "2025-03-31", "mar_retrain"),
    ("2024-11-02", "2025-04-15", "apr_retrain"),
]

EVAL_PERIODS = [
    ("2025-01-09", "2025-01-31", "jan_holdout"),
    ("2025-02-01", "2025-02-28", "february"),
    ("2025-03-01", "2025-03-31", "march"),
    ("2025-04-01", "2025-04-15", "april_regular"),
    ("2025-04-16", "2025-06-15", "playoffs"),
]
```

### Questions to Answer

1. **How does hit rate evolve?**
   - Does it stay stable? Decay? Improve?
   - Is there a predictable pattern?

2. **When is retraining most beneficial?**
   - Monthly? Every 2 weeks?
   - After trade deadline?
   - Before playoffs?

3. **What's the optimal training window?**
   - Full season? Last 60 days? Rolling window?
   - Does recency weighting help?

4. **How do different filters perform?**
   - Premium (92+ conf, 3+ edge)
   - High edge (5+)
   - All predictions

---

## Part 3: Monthly Retraining Strategy

### Current Strategy

Train on current season only, retrain monthly.

```
Month    Training Window       Expected Samples
-------- -------------------- -----------------
Feb      Nov 2 - Jan 31       ~12,000
Mar      Nov 2 - Feb 28       ~15,000
Apr      Nov 2 - Mar 31       ~18,000
Playoffs Nov 2 - Apr 15       ~20,000
```

### Retraining Triggers

1. **Calendar**: First week of each month
2. **Performance**: Hit rate drops below 52% for 7+ consecutive days
3. **Events**: Trade deadline, All-Star break, playoff start

### Model Promotion Process

```
1. Train new model
   └── PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V9_FEB"

2. Evaluate on holdout
   └── Compare to current production model

3. If better:
   └── Rename to catboost_v9_33features_YYYYMMDD_HHMMSS.cbm
   └── Upload to GCS
   └── Deploy: ./bin/deploy-service.sh prediction-worker

4. Monitor 48 hours
   └── Check hit rate, error rate, prediction volume

5. Document in experiment registry
```

---

## Part 4: Experiment Ideas

### Batch 1: Training Window Experiments (Priority)

| ID | Hypothesis | Training | Eval |
|----|------------|----------|------|
| EXP_WINDOW_30D | 30-day rolling window captures recent trends | Last 30 days | Next 7 days |
| EXP_WINDOW_60D | 60-day window balances recency and stability | Last 60 days | Next 7 days |
| EXP_WINDOW_90D | 90-day window has enough samples | Last 90 days | Next 7 days |
| EXP_FULL_SEASON | Full season maximizes samples | Full season | Next 7 days |

### Batch 2: Recency Weighting Experiments

| ID | Hypothesis | Approach |
|----|------------|----------|
| EXP_RECENCY_90D | 90-day half-life emphasizes recent | Exponential decay |
| EXP_RECENCY_180D | 180-day half-life is balanced | Exponential decay |
| EXP_RECENCY_MONTHLY | Month-by-month weights | 1.0, 0.9, 0.8... |

### Batch 3: Data Source Experiments

| ID | Hypothesis | Data Source |
|----|------------|-------------|
| EXP_DK_ONLY | DraftKings-only training matches DK betting | Odds API DK |
| EXP_FD_ONLY | FanDuel-only for FD bettors | Odds API FD |
| EXP_MULTI_BOOK | Multi-book with indicator captures book biases | All books + indicator |

### Batch 4: Seasonal Patterns

| ID | Hypothesis | Approach |
|----|------------|----------|
| EXP_LATE_SEASON | Late season (Mar-Apr) has different patterns | Train on late-season only |
| EXP_B2B_SPECIALIST | Back-to-back games need special handling | Separate B2B model |
| EXP_HOME_AWAY_SPLIT | Home/away have different patterns | Separate models |

### Batch 5: Feature Engineering

| ID | Hypothesis | New Features |
|----|------------|--------------|
| EXP_MOMENTUM | Add 3-game and 5-game momentum | win_streak, pts_trend |
| EXP_MATCHUP | Add historical matchup features | h2h_avg, h2h_edge |
| EXP_REST | More granular rest features | days_rest, games_in_14d |

---

## Part 5: Experiment Execution Plan

### Week 1 (Current)
- [x] Deploy V9 to production
- [x] Add features_snapshot to all predictions
- [ ] Upload V9 model to GCS
- [ ] Run audit on 2024-25 data

### Week 2
- [ ] Fix 2024-25 team_win_pct
- [ ] Run EXP_WINDOW experiments on 2024-25
- [ ] Analyze last season performance trajectory

### Week 3
- [ ] Backfill 2024-25 feature store
- [ ] Run EXP_RECENCY experiments
- [ ] Document optimal retraining frequency

### Week 4
- [ ] Run EXP_DATA_SOURCE experiments
- [ ] Create automated monthly retraining script
- [ ] Set up experiment tracking dashboard

### Monthly (Ongoing)
- [ ] First week: Retrain V9 with expanded window
- [ ] Second week: Evaluate and promote if better
- [ ] Continuous: Monitor hit rate, investigate drops

---

## Part 6: Success Metrics

### Primary Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Premium Hit Rate | 56.5% | >58% |
| High-Edge Hit Rate | 72.2% | >70% (maintain) |
| MAE | 4.82 | <4.5 |

### Secondary Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Model Staleness | Days since last retrain | <30 days |
| Feature Coverage | % predictions with full features | >95% |
| Vegas Coverage | % with real Vegas lines | >50% |

---

## Part 7: Experiment Registry

Track all experiments in BigQuery:

```sql
-- Schema: nba_predictions.ml_experiments
experiment_id STRING
experiment_name STRING
experiment_type STRING  -- 'window', 'recency', 'data_source', etc.
hypothesis STRING
config_json STRING
train_period STRUCT<start_date, end_date, samples>
eval_period STRUCT<start_date, end_date, samples>
results_json STRING  -- MAE, hit rates, etc.
model_path STRING
status STRING  -- 'running', 'completed', 'promoted', 'archived'
tags ARRAY<STRING>
created_at TIMESTAMP
completed_at TIMESTAMP
```

---

## Scripts to Create

1. `bin/backfill_feature_store_historical.py` - Fix historical data
2. `ml/experiments/last_season_analysis.py` - Analyze 2024-25 trajectory
3. `ml/experiments/automated_monthly_retrain.py` - Monthly retraining
4. `bin/promote_model.py` - Model promotion workflow

---

*Last Updated: Session 67, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
