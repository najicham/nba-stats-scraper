# ML Monthly Retraining - Execution Tasks

**Created:** 2026-02-01 (Session 69)
**Purpose:** Discrete tasks for Sonnet sessions to execute
**Parent Doc:** `STRATEGY.md`

---

## Task Overview

These tasks are designed to be executed independently. Each can be completed in a single Sonnet session.

| Task | Priority | Complexity | Dependencies |
|------|----------|------------|--------------|
| Task 1: Activate Scheduler | P1 | Low | None |
| Task 2: Run February Retrain | P1 | Low | None |
| Task 3: Pre-Retrain Validation | P2 | Medium | None |
| Task 4: Enhance quick_retrain.py | P2 | Medium | None |
| Task 5: Run Window Experiments | P3 | Low | Task 2 complete |

---

## Task 1: Activate Cloud Scheduler

**Goal:** Enable automatic monthly retraining trigger

**Complexity:** Low (run existing scripts)

**Steps:**

1. Review the deploy script:
   ```bash
   cat orchestration/cloud_functions/monthly_retrain/deploy.sh
   ```

2. Deploy the Cloud Function:
   ```bash
   cd orchestration/cloud_functions/monthly_retrain
   ./deploy.sh
   ```

3. Verify the scheduler job was created:
   ```bash
   gcloud scheduler jobs list --location=us-west2 | grep monthly-retrain
   ```

4. Test with dry run:
   ```bash
   curl -X POST "https://FUNCTION_URL" \
       -H "Content-Type: application/json" \
       -d '{"dry_run": true}'
   ```

**Success Criteria:**
- [ ] Cloud Function deployed
- [ ] Cloud Scheduler job exists (1st of month, 6 AM ET)
- [ ] Dry run returns expected output

**Notes:**
- If deploy.sh needs updates, modify it
- Ensure service account has BigQuery and GCS permissions

---

## Task 2: Run February Retrain

**Goal:** Execute first manual monthly retrain and validate the process

**Complexity:** Low (run existing script)

**Steps:**

1. Dry run first:
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_FEB_RETRAIN" \
       --train-start 2025-11-02 --train-end 2026-01-31 \
       --eval-start 2026-01-25 --eval-end 2026-01-31 \
       --line-source draftkings \
       --dry-run
   ```

2. Execute the retrain:
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_FEB_RETRAIN" \
       --train-start 2025-11-02 --train-end 2026-01-31 \
       --eval-start 2026-01-25 --eval-end 2026-01-31 \
       --line-source draftkings \
       --hypothesis "February monthly retrain with expanded window"
   ```

3. Review output against success criteria:
   - MAE ≤ 5.0?
   - High-edge hit rate ≥ 65%?
   - Sample size ≥ 50 high-edge bets?

4. Verify experiment registered:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT experiment_name,
          JSON_VALUE(results_json, '$.mae') as mae,
          JSON_VALUE(results_json, '$.hit_rate_high_edge') as high_edge_hr,
          JSON_VALUE(results_json, '$.bets_high_edge') as bets
   FROM nba_predictions.ml_experiments
   WHERE experiment_name = 'V9_FEB_RETRAIN'"
   ```

5. Document results in session handoff

**Success Criteria:**
- [ ] Retrain completes without errors
- [ ] Results meet minimum thresholds
- [ ] Experiment recorded in ml_experiments table
- [ ] Model file saved to models/ directory

**Decision Point:**
- If results are good: Proceed to promotion (optional - may wait for human review)
- If results are poor: Document issues, do not promote

---

## Task 3: Add Pre-Retrain Validation

**Goal:** Create validation script that checks data quality before training

**Complexity:** Medium (new code)

**Create:** `ml/experiments/pre_retrain_validation.py`

**Checks to Implement:**

1. **Feature Store Completeness**
   ```sql
   SELECT
       COUNT(*) as total_records,
       COUNT(DISTINCT game_date) as unique_dates,
       MIN(game_date) as earliest,
       MAX(game_date) as latest
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date BETWEEN @train_start AND @train_end
   ```
   - Fail if < 8,000 records
   - Fail if dates don't span full window

2. **Vegas Line Coverage**
   ```sql
   SELECT
       COUNTIF(has_vegas_line = 1) * 100.0 / COUNT(*) as vegas_coverage
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date BETWEEN @train_start AND @train_end
   ```
   - Warn if < 80% coverage
   - Fail if < 50% coverage

3. **Data Quality Checks**
   - No NULL values in critical features
   - Points averages in reasonable range (0-50)
   - No duplicate player-game combinations

**Output Format:**
```
PRE-RETRAIN VALIDATION
======================
Training Window: 2025-11-02 to 2026-01-31

Feature Store:
  ✅ Records: 12,456 (min: 8,000)
  ✅ Date coverage: 91 days (expected: 91)
  ✅ Vegas coverage: 87.3% (min: 50%)

Data Quality:
  ✅ No NULL critical features
  ✅ Points averages in range
  ✅ No duplicates

RESULT: PASS - Ready for training
```

**Integration:**
- Add `--validate-only` flag to `quick_retrain.py`
- Or create standalone script called before training

---

## Task 4: Enhance quick_retrain.py

**Goal:** Add parameters needed for future experiments

**Complexity:** Medium (code changes)

**Enhancements:**

### 4a. Add Recency Weighting

```python
# New argument
parser.add_argument('--half-life', type=int, default=None,
                    help='Half-life in days for recency weighting (default: none)')

# Implementation
def compute_sample_weights(game_dates, half_life_days):
    """Exponential decay weighting for recency."""
    if half_life_days is None:
        return None
    max_date = game_dates.max()
    days_ago = (max_date - game_dates).dt.days
    weights = np.exp(-np.log(2) * days_ago / half_life_days)
    return weights

# In training
if args.half_life:
    weights = compute_sample_weights(df_train['game_date'], args.half_life)
    model.fit(X_train, y_train, sample_weight=weights, ...)
else:
    model.fit(X_train, y_train, ...)
```

### 4b. Add Hyperparameter Arguments

```python
parser.add_argument('--depth', type=int, default=6,
                    help='Tree depth (default: 6)')
parser.add_argument('--learning-rate', type=float, default=0.05,
                    help='Learning rate (default: 0.05)')
parser.add_argument('--l2-reg', type=float, default=3.0,
                    help='L2 regularization (default: 3.0)')

# In training
model = cb.CatBoostRegressor(
    iterations=1000,
    learning_rate=args.learning_rate,
    depth=args.depth,
    l2_leaf_reg=args.l2_reg,
    random_seed=42,
    verbose=100,
    early_stopping_rounds=50
)
```

### 4c. Add Feature Set Selection

```python
FEATURE_SETS = {
    'all': FEATURES,  # Current 33
    'no_vegas': [f for f in FEATURES if not f.startswith('vegas') and f != 'has_vegas_line'],
    'core': [
        "points_avg_last_5", "points_avg_last_10", "points_avg_season",
        "points_std_last_10", "minutes_avg_last_10",
        "vegas_points_line", "has_vegas_line",
        "opponent_def_rating", "team_off_rating",
        "fatigue_score", "rest_advantage",
        "home_away", "back_to_back",
        "recent_trend", "games_in_last_7_days",
    ],
    'stats_only': [
        "points_avg_last_5", "points_avg_last_10", "points_avg_season",
        "points_std_last_10", "games_in_last_7_days",
        "minutes_avg_last_10", "ppm_avg_last_10",
        "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
        "avg_points_vs_opponent", "games_vs_opponent",
    ],
}

parser.add_argument('--feature-set', choices=list(FEATURE_SETS.keys()),
                    default='all', help='Feature subset to use')
```

**Testing:**
```bash
# Test recency weighting
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "TEST_RECENCY" --half-life 60 --dry-run

# Test hyperparameters
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "TEST_HYPERPARAMS" --depth 8 --learning-rate 0.03 --dry-run

# Test feature sets
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "TEST_FEATURES" --feature-set core --dry-run
```

---

## Task 5: Run Window Experiments

**Goal:** Determine optimal training window size

**Complexity:** Low (run existing script multiple times)

**Prerequisite:** Task 2 complete (establish baseline)

**Experiments:**

```bash
# W1: 30-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W1_30DAY" \
    --train-start 2025-12-25 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "30-day rolling window"

# W2: 45-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W2_45DAY" \
    --train-start 2025-12-10 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "45-day rolling window"

# W3: 60-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W3_60DAY" \
    --train-start 2025-11-25 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "60-day rolling window"

# W4: 90-day window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W4_90DAY" \
    --train-start 2025-10-26 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "90-day rolling window"

# W5: Full season (same as current V9 approach)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "EXP_W5_FULL_SEASON" \
    --train-start 2025-11-02 --train-end 2026-01-24 \
    --eval-start 2026-01-25 --eval-end 2026-01-31 \
    --line-source draftkings \
    --hypothesis "Full season training"
```

**Analysis Query:**
```sql
SELECT
    experiment_name,
    JSON_VALUE(config_json, '$.train_days') as train_days,
    JSON_VALUE(results_json, '$.mae') as mae,
    JSON_VALUE(results_json, '$.hit_rate_all') as hr_all,
    JSON_VALUE(results_json, '$.hit_rate_high_edge') as hr_high_edge,
    JSON_VALUE(results_json, '$.bets_high_edge') as n_high_edge
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE 'EXP_W%'
ORDER BY CAST(JSON_VALUE(config_json, '$.train_days') AS INT64)
```

**Document Results:**
- Which window size has best high-edge hit rate?
- Is there a clear winner or are results similar?
- Sample sizes sufficient for conclusions?

---

## Task Handoff Template

When completing a task, document:

```markdown
## Task X Complete - [Date]

**Session:** [Session Number]
**Task:** [Task Name]
**Status:** ✅ Complete / ⚠️ Partial / ❌ Blocked

### What Was Done
- [Bullet points of actions taken]

### Results
- [Key metrics or outputs]

### Issues Encountered
- [Any problems and how they were resolved]

### Next Steps
- [What should happen next]

### Files Changed
- [List of files created/modified]
```

---

## Dependency Graph

```
Task 1 (Scheduler)
    │
    └──► Monthly automation enabled

Task 2 (Feb Retrain) ◄─── Can run independently
    │
    └──► Baseline established
         │
         └──► Task 5 (Window Experiments)

Task 3 (Validation) ◄─── Can run independently
    │
    └──► Better data quality checks

Task 4 (Enhancements) ◄─── Can run independently
    │
    └──► Enables future experiments
         (recency, hyperparams, features)
```

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
