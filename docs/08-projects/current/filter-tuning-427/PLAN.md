# Filter Tuning & Model-Aware Filtering Plan

**Created:** Session 427 (2026-03-06)
**Updated:** Session 428 (2026-03-06)
**Status:** Phase 1 COMPLETE — 4 filters demoted to observation

## Background

Session 427 ran three parallel research queries to evaluate filter effectiveness, model-family sensitivity, and weekly stability. The results reveal that 5-6 active filters are blocking profitable picks (counterfactual HR 59-65%), and filter sensitivity varies dramatically by model family.

## Research Findings

### Finding 1: Six Active Filters Are Blocking Winners

Counterfactual HR = "what HR would these blocked picks have achieved?"
Breakeven at -110 = 52.4%. Baseline OVER = 59.9%, UNDER = 57.3%.

**Harmful (CF HR > 55% — blocking profitable picks):**

| Filter | CF HR | Blocked Picks | Current Status |
|--------|-------|---------------|----------------|
| `neg_pm_streak` | **64.5%** | 758 | ACTIVE |
| `under_edge_7plus` | **60.2%** | 989 | ACTIVE |
| `star_under` | **59.6%** | 706 | ACTIVE |
| `line_dropped_over` | **60.0%** | 477 | ACTIVE |
| `flat_trend_under` | **59.2%** | 211 | ACTIVE |
| `mid_line_over` | ~53% directional weekly | varies | ACTIVE |

**Effective (CF HR < 52.4% — correctly blocking losers):**

| Filter | CF HR | Blocked Picks | Current Status |
|--------|-------|---------------|----------------|
| `starter_v12_under` | 42.8% | 138 | ACTIVE — keep |
| `opponent_under_block` | 46.7% | 906 | ACTIVE — keep |
| `v9_under_5plus` | 48.6% | 148 | ACTIVE — keep |

**Drifted:**
- `bench_under`: claimed 35.1% HR, now 54.6% (+19.5pp drift). N=2,314. Still below baseline but original justification gone.

**Caveat:** CF HR is computed across ALL models' edge 3+ predictions, not within the best-bets pipeline. Filter interactions matter. Must validate with `bin/post_filter_eval.py` before demoting.

### Finding 2: Filter Sensitivity Varies by Model Family

| Model Family | Edge 3+ Lift (OVER) | Edge 3+ Lift (UNDER) | Key Insight |
|---|---|---|---|
| v12_mae | **+14.3pp** | +4.9pp | Edge floor is critical |
| v9_mae | +6.2pp | **-0.1pp** | Edge floor useless for UNDER |
| XGBoost | +0.4pp | +2.7pp | Strong regardless, 65-73% HR raw |
| Quantile | N/A (UNDER only) | 0 to -1.4pp | Edge doesn't correlate with HR |

**Specific anti-patterns:**
- v9_mae UNDER on low-line (<15 pts) = **36.3% HR** (N=124) — should block
- XGBoost = 65-73% HR at all edge levels — should get fewer filters
- v12_mae OVER best bets = **83.3%** (N=24) — top contributor

### Finding 3: Weekly Retuning Is Not Worth It

- `mid_line_over`: stddev 13.6pp on mean 2.8pp lift — pure noise
- `flat_trend_under`: 68% directional consistency, static thresholds sufficient
- No filter showed predictable weekly patterns
- **Conclusion:** Monthly review via `bin/post_filter_eval.py` is sufficient

## Implementation Plan

### Phase 1: Filter Cleanup — COMPLETED (Session 428)

**Result:** 4 filters demoted to observation. 2 were already handled. 1 kept after validation.

| Filter | Action | Reason |
|--------|--------|--------|
| `neg_pm_streak` | DEMOTED | CF HR 64.5% (N=758) — blocking most profitable picks |
| `line_dropped_over` | DEMOTED | CF HR 60.0% (N=477) — toxic window original data |
| `flat_trend_under` | DEMOTED | CF HR 59.2% (N=211) — above breakeven |
| `mid_line_over` | DEMOTED | 55.8% full-season HR, 13.6pp weekly stddev = noise |
| `under_edge_7plus` | **KEPT** | BQ validation: v9 UNDER edge 7+ = **34.1% HR** (N=41). Session 427 CF HR of 60.2% was computed across ALL models, not just v9. Filter correctly targets v9 only. |
| `star_under` | Already removed (Session 400) | No action needed |
| `bench_under` | Already demoted (Session 419) | No action needed |

**Algorithm version:** `v428_filter_cleanup`
**Monitor:** Track BB HR for 7 days post-deployment (Mar 7-14).

### Phase 2: Model-Aware Filtering (MEDIUM IMPACT, MEDIUM RISK)

**Goal:** Different filter rules for different model families.

**Quick win (implement first):**
- Add `v9_mae_low_line_under` block: v9_mae + UNDER + line < 15 = 36.3% HR (N=124)
- This requires checking `system_id` in the filter logic

**Research needed:**
- How does the aggregator handle multi-model picks? A pick can come from multiple models. If v9_mae flags UNDER on a low-line player but v12_mae doesn't, does the pick survive?
- Check `ml/signals/cross_model_scorer.py` and `shared/config/cross_model_subsets.py` for how model families interact in scoring

**Architecture question:** Currently `aggregator.py` doesn't know which model(s) support a pick. Adding model-awareness means:
1. Passing model family info through to the aggregator
2. Either: per-model filter rules OR model-weighted edge (XGBoost edge counts more)
3. This touches `data_processors/publishing/signal_best_bets_exporter.py` → `aggregator.aggregate()`

### Phase 3: Monthly Filter Review (ONGOING)

**Goal:** Catch filter drift before it accumulates (like bench_under drifting +19.5pp).

**Process:**
1. Run `bin/post_filter_eval.py` monthly (1st of month)
2. Check counterfactual HR for each active filter
3. Any filter with CF HR > 55% for 2 consecutive months → demote to observation
4. Any observation filter with CF HR < 48% for 2 consecutive months → promote to active

**Could automate:** Add to the `daily-health-check` CF or create a monthly Cloud Scheduler trigger.

## Key Files

| File | What |
|------|------|
| `ml/signals/aggregator.py` | All filter logic (lines 580-700+) |
| `bin/post_filter_eval.py` | Pipeline simulation for filter evaluation |
| `nba_predictions.best_bets_filter_audit` | Daily filter block counts (4 days only) |
| `ml/signals/cross_model_scorer.py` | Multi-model scoring |
| `shared/config/cross_model_subsets.py` | Model family classification |
| `data_processors/publishing/signal_best_bets_exporter.py` | Best bets pipeline entry point |

## Key Queries

### Filter counterfactual HR (run monthly)
```sql
-- Replace FILTER_CONDITION with the specific filter logic
SELECT
  COUNT(*) as n,
  ROUND(AVG(CAST(prediction_correct AS INT64)) * 100, 1) as cf_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
  AND has_prop_line = TRUE
  AND recommendation IN ('OVER', 'UNDER')
  AND prediction_correct IS NOT NULL
  AND ABS(predicted_points - line_value) >= 3
  AND FILTER_CONDITION
```

### Model family BB performance
```sql
SELECT
  CASE
    WHEN system_id LIKE '%v9%mae%' THEN 'v9_mae'
    WHEN system_id LIKE '%v12%mae%' THEN 'v12_mae'
    WHEN system_id LIKE '%xgb%' THEN 'xgb'
    ELSE 'other'
  END as family,
  recommendation,
  COUNT(*) as n,
  ROUND(AVG(CAST(prediction_correct AS INT64)) * 100, 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND has_prop_line = TRUE AND is_best_bet = TRUE
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
```
