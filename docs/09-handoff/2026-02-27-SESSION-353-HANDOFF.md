# Session 353 Handoff — All Models BLOCKED, Recovery Strategy

**Date:** 2026-02-27
**Previous:** Session 352 — LightGBM fix, CI/CD bug, edge floor adjustment
**Full Session 352 details:** `docs/09-handoff/2026-02-27-SESSION-352-HANDOFF.md`

## Situation: Every Model is BLOCKED

As of Feb 26, **every tracked model** in `model_performance_daily` is BLOCKED (HR 7d < 52.4%). This has been the case for 3-5+ days depending on the model. Despite this, the best bets filter pipeline is still extracting profitable picks (62.5% HR over 30d, 72.7% last 7d) — but at very low volume (1-4 picks/day).

### Production Models
| Model | HR 7d | HR 14d | N 7d | Staleness | Days BLOCKED |
|-------|-------|--------|------|-----------|--------------|
| `catboost_v12` | 44.7% | 47.9% | 85 | 27 days | 4 |
| `catboost_v9` | 35.0% | 43.5% | 20 | 21 days | 5 |

### Best Shadow Models
| Model | HR 7d | HR 14d | N 7d | Staleness | Notes |
|-------|-------|--------|------|-----------|-------|
| `v9_low_vegas_train0106_0205` | 51.9% | 54.2% | 52 | 17 days | Closest to breakeven |
| `v12_q43_train1225_0205_feb22` | 50.0% | 50.0% | 20 | 11 days | |
| `v9_q45_train1102_0125` | 50.0% | 48.5% | 30 | 32 days | Very stale |

### Edge 5+ Performance (where best bets come from)
| Model | Edge 5+ HR 14d | N | Premium vs Overall |
|-------|---------------|---|-------------------|
| `v9_low_vegas_train0106_0205` | **66.7%** | 18 | +16.7pp |
| `v12_noveg_q45_train1102_0125` | 62.5% | 8 | +21.9pp |
| `catboost_v12` | 42.1% | 19 | -2.6pp |
| `catboost_v9` | 37.5% | 8 | +2.5pp |

### Best Bets Performance (despite BLOCKED models)
| Period | W-L | HR |
|--------|-----|-----|
| Last 7d | 8-3 | 72.7% |
| Last 14d | 10-6 | 62.5% |
| Last 30d | 30-18 | 62.5% |

## Key Questions to Investigate

### 1. Is "all BLOCKED" normal for late February?
- Check the historical `model_performance_daily` table for prior periods where all models were BLOCKED simultaneously
- Was there a similar pattern last year or earlier this season?
- Is this correlated with the All-Star break / trade deadline period (trades disrupt player roles, minutes, etc.)?

```sql
-- How often has every model been BLOCKED simultaneously?
WITH daily_states AS (
  SELECT game_date,
    COUNTIF(state = 'BLOCKED') AS blocked_count,
    COUNTIF(state != 'BLOCKED') AS non_blocked_count,
    COUNT(DISTINCT model_id) AS total_models
  FROM `nba-props-platform.nba_predictions.model_performance_daily`
  WHERE game_date >= '2025-11-01'
  GROUP BY game_date
)
SELECT game_date, blocked_count, non_blocked_count, total_models,
  ROUND(100.0 * blocked_count / total_models, 1) AS pct_blocked
FROM daily_states
WHERE non_blocked_count = 0  -- All models BLOCKED
ORDER BY game_date DESC
```

### 2. What's driving the degradation?
- Is it OVER or UNDER predictions failing?
- Is it specific player tiers (stars, starters, bench)?
- Is it specific teams or matchup types?
- Did something change in the NBA around Feb 20-22 (trade deadline was Feb 6)?

```sql
-- Direction breakdown for V12 last 14 days
SELECT
  CASE WHEN predicted_margin > 0 THEN 'OVER' ELSE 'UNDER' END AS direction,
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND system_id = 'catboost_v12'
  AND ABS(predicted_margin) >= 3
  AND prediction_correct IS NOT NULL
GROUP BY 1
```

```sql
-- Weekly HR trend for V12 (when did degradation start?)
SELECT
  DATE_TRUNC(game_date, WEEK) AS week,
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-01'
  AND system_id = 'catboost_v12'
  AND ABS(predicted_margin) >= 3
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1
```

### 3. Are the new shadow models accumulating enough data?
11 shadow models were registered Feb 26-27 but most have 0-1 graded edge 3+ bets. Check:

```sql
-- Shadow model accumulation
SELECT system_id,
  COUNTIF(ABS(predicted_margin) >= 3) AS edge3_bets,
  ROUND(SAFE_DIVIDE(COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct),
    COUNTIF(ABS(predicted_margin) >= 3)) * 100, 1) AS hr_edge3,
  MIN(game_date) AS first_graded,
  MAX(game_date) AS last_graded
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id IN (
  'catboost_v12_noveg_q55_tw_train0105_0215',
  'catboost_v12_noveg_q55_tw_train1225_0209',
  'catboost_v12_noveg_q55_train1225_0209',
  'catboost_v12_noveg_q57_train1225_0209',
  'catboost_v9_low_vegas_train1225_0209',
  'lgbm_v12_noveg_train1102_0209',
  'lgbm_v12_noveg_train1201_0209'
)
AND game_date >= '2026-02-26'
GROUP BY 1
ORDER BY edge3_bets DESC
```

### 4. Should we retrain with the freshest possible data?
Current models are trained through Feb 9-15 at most. NBA is now 12-18 days past that. Options:
- Retrain the best-performing architecture (Q55 trend-weighted) through Feb 25
- Retrain LightGBM through Feb 25 (if it validates on Feb 28)
- Retrain with a shorter window (28d instead of 42d) to be more reactive

### 5. Is the `model_performance_daily` BLOCKED threshold too aggressive?
- BLOCKED = HR 7d < 52.4% (breakeven for -110 odds)
- With small N (20-50 picks in 7d), variance alone can cause BLOCKED state
- A model at true 55% HR has ~30% chance of showing <52.4% in any 7-day window with N=30
- Should we use 14d HR instead? Or require consecutive days below threshold?

```sql
-- How volatile is the 7d HR? Check std dev
SELECT model_id,
  ROUND(AVG(rolling_hr_7d), 1) AS avg_hr_7d,
  ROUND(STDDEV(rolling_hr_7d), 1) AS std_hr_7d,
  ROUND(MIN(rolling_hr_7d), 1) AS min_hr_7d,
  ROUND(MAX(rolling_hr_7d), 1) AS max_hr_7d,
  COUNT(*) AS days
FROM `nba-props-platform.nba_predictions.model_performance_daily`
WHERE game_date >= '2026-01-01'
  AND model_id IN ('catboost_v12', 'catboost_v9_low_vegas_train0106_0205')
GROUP BY 1
```

## Recovery Options (in priority order)

### Option 1: Fresh retrains of best architectures
The Session 348 retrain (`v12_noveg_q55_tw_train0105_0215`, 68% backtest) is only 3 days old in shadow. If it shows promise, retrain with even fresher data (through Feb 25).

```bash
# Q55 trend-weighted, fresh data
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_NOVEG_Q55_TW_FRESH" --feature-set v12 --no-vegas \
    --quantile 0.55 --trend-weights \
    --train-start 2026-01-15 --train-end 2026-02-25 \
    --eval-start 2026-02-20 --eval-end 2026-02-27 \
    --force --enable
```

### Option 2: Wait for LightGBM validation
LightGBM models (73.3% and 67.7% backtest) were fixed this session and should produce first predictions Feb 28. If they show 55%+ live HR after 3-5 days, retrain with fresh data.

### Option 3: Shorter training window experiment
The current 42-day window may include too much "old regime" data. Try a 28-day window to be more reactive to current conditions.

### Option 4: Lower the BLOCKED threshold
If investigation shows 7d HR is too volatile with small N, consider:
- Using 14d HR for state transitions
- Requiring 3+ consecutive days below threshold
- Using a lower threshold like 50% instead of 52.4%

## What Session 352 Already Did

1. **Fixed LightGBM deployment** — Two bugs (CI/CD stale image + missing libgomp1) prevented LightGBM from loading. Hot-deployed revision 00285. First predictions expected Feb 28.

2. **Fixed CI/CD pipeline** — `cloudbuild.yaml` was deploying stale Docker images on every auto-deploy. Added explicit push step before deploy. This was silently affecting ALL services.

3. **Lowered edge floor 5.0 → 3.0** — Best bets were producing 0 picks because the edge floor was too high for degraded models. Now producing 2 picks today. Signal quality filters remain intact.

4. **Fixed min-instances drift** — Auto-deploy was resetting prediction-worker to 0 min-instances.

## Files to Reference

- Zero-picks analysis: `docs/08-projects/current/model-diversity-session-350/BEST-BETS-ZERO-PICKS-ANALYSIS.md`
- Model registry: `SELECT * FROM nba_predictions.model_registry WHERE enabled = TRUE`
- Decay detection: `decay-detection` Cloud Function runs daily 11 AM ET
- Steering playbook: `docs/02-operations/runbooks/model-steering-playbook.md`
- Dead ends (don't revisit): See CLAUDE.md "Dead ends" section

## Critical Context

- **Best bets are still profitable** (62.5% 30d) despite all models being BLOCKED — the multi-model + signal filter pipeline is doing its job
- **v9_low_vegas is the only edge 5+ profitable model** at 66.7% (N=18) — it's carrying the system
- **Pick volume is critically low** (1-4/day) — the edge floor change helps but doesn't solve the root cause
- **Don't panic-retrain** — follow governance gates, shadow first, then promote. The pipeline is still making money.
