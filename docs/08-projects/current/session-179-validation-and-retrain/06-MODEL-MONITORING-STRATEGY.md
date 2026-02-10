# Model Monitoring Strategy

Session 187: Per-model strength profiles and monitoring strategy for the 5-model landscape.

## Model Landscape (Feb 2026)

| Model | Type | Status | Key Metric |
|-------|------|--------|------------|
| `catboost_v9` | RMSE champion | Decaying (47.9% edge 3+) | HR Edge 3+ |
| `catboost_v9_train1102_0108` | RMSE challenger | Best current edge HR (58.3%) | HR Edge 3+ |
| `catboost_v9_train1102_0131_tuned` | RMSE baseline | Few edge picks | HR All |
| `catboost_v9_q43_train1102_0131` | Quantile 0.43 | NEW shadow (Session 186) | UNDER HR, HR Edge 3+ |
| `catboost_v9_q45_train1102_0131` | Quantile 0.45 | NEW shadow (Session 186) | UNDER HR, HR Edge 3+ |

## Per-Model Strength Profiles

### Champion (`catboost_v9`)
- **Type:** RMSE, trained Nov 2 - Jan 8
- **Profile:** All-around, decaying with staleness (33 days stale as of Feb 10)
- **Historical peak:** 71.2% edge 3+ (Jan 12 week), now 47.9% (Feb 2 week)
- **Monitor:** HR Edge 3+ weekly — below 52.4% breakeven means losing money
- **Action:** Already below breakeven. Promotion of a challenger is P0.

### `catboost_v9_train1102_0108`
- **Type:** RMSE, same train dates as champion, cleaner feature quality
- **Profile:** Balanced OVER/UNDER, best edge 3+ HR (58.3% in backtest)
- **Strengths:** Stars, Starters, Mid lines
- **Monitor:** HR Edge 3+, OVER/UNDER balance, comparison vs champion
- **Promotion criteria:** Sustained 3+ pp better than champion over 5+ game days

### `catboost_v9_train1102_0131_tuned`
- **Type:** RMSE, extended training (91 days), tuned hyperparams + 30d recency
- **Profile:** Baseline for comparison — 53.4% HR All but only 6 edge picks
- **Strengths:** None specific (few edge picks to analyze)
- **Monitor:** HR All for baseline comparison, edge pick volume
- **Action:** If still < 10 edge picks after 7 days, low value as comparison

### `catboost_v9_q43_train1102_0131` (Session 186 Discovery)
- **Type:** Quantile regression alpha=0.43
- **Profile:** UNDER specialist — systematic negative prediction bias
- **Backtest:** 65.8% HR 3+ (n=38), 67.6% UNDER HR, -1.62 Vegas bias
- **Key Strengths (from Session 186 analysis):**
  - Starters UNDER: 85.7% HR
  - High Lines (>20.5): 76.5% HR
  - Edge [3-5): 71.4% HR
  - Stars UNDER: strong
- **Monitor:** UNDER HR (target >= 60%), Starters UNDER, High Line HR
- **Why this works:** Edge comes from loss function bias, not model drift (staleness)
- **Expected production:** 55-60% HR 3+ (5-10pp backtest gap is normal)
- **Promotion criteria:** 55%+ HR 3+ in production for 5+ game days, UNDER HR >= 58%
- **Red flag:** UNDER HR < 55% or Vegas bias outside [-2.5, -0.5]

### `catboost_v9_q45_train1102_0131`
- **Type:** Quantile regression alpha=0.45 (less aggressive than Q43)
- **Profile:** Less aggressive UNDER — fewer edge picks but potentially more precise
- **Backtest:** 61.9% HR 3+ (n=21), 65.0% UNDER HR, -1.28 Vegas bias
- **Key Strengths:**
  - Role UNDER: 78.6% HR
  - Mid Lines (12.5-20.5): solid
- **Monitor:** UNDER HR (target >= 58%), Role UNDER, edge pick volume
- **Expected production:** 52-57% HR 3+
- **Promotion criteria:** Similar to Q43 but with lower bar (fewer picks expected)
- **Red flag:** Fewer than 10 edge 3+ picks in 7 days (too conservative)

## Monitoring Cadence

### Daily (~5 min)
```bash
# Quick check: Are shadows generating predictions?
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_%'
  AND game_date >= CURRENT_DATE() - 1
GROUP BY 1, 2 ORDER BY 2 DESC, 1"
```

### Every 2-3 Days (~10 min)
```bash
# Landscape view — all models at once
PYTHONPATH=. python bin/compare-model-performance.py --all --days 7
```

### Weekly (~20 min)
```bash
# Full landscape with segment breakdowns
PYTHONPATH=. python bin/compare-model-performance.py --all --segments --days 7

# Deep dive on quantile models (primary promotion candidates)
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --segments --days 7
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q45_train1102_0131 --segments --days 7
```

### Weekly Checklist

- [ ] Run `--all --days 7` landscape view
- [ ] Check champion HR 3+ (still below breakeven?)
- [ ] Check Q43 UNDER HR and Starters UNDER segment
- [ ] Check Q45 Role UNDER segment
- [ ] Check _0108 HR 3+ vs champion
- [ ] Verify all models generating predictions (no silent failures)
- [ ] Record weekly HR 3+ for each model in tracking spreadsheet
- [ ] If Q43 or Q45 at 55%+ HR 3+ for 5+ days: initiate promotion review

## Promotion Criteria

### RMSE Models (Standard)
1. HR Edge 3+ >= 55% over 5+ game days
2. HR Edge 3+ >= champion + 3pp
3. Vegas bias within +/- 1.5
4. OVER/UNDER balance (neither below 45%)
5. MAE within 0.5 of champion

### Quantile Models (Session 186)
1. HR Edge 3+ >= 55% over 5+ game days
2. UNDER HR >= 58% (expected strength direction)
3. Vegas bias within [-2.5, -0.5] (quantile models are UNDER-biased by design)
4. OVER HR is secondary — quantile models are UNDER specialists
5. Edge 3+ pick volume >= 3 per game day on average
6. **No staleness decay** — verify HR is stable across evaluation windows

### Promotion Process
1. Model meets criteria for 5+ game days
2. Run extended walkforward evaluation (`quick_retrain.py --walkforward`)
3. Update governance gates if needed (quantile models need different OVER threshold)
4. Upload to GCS production path
5. Update `CATBOOST_V9_MODEL_PATH` env var
6. Monitor first 48 hours post-promotion

## Retirement Criteria

- HR Edge 3+ below breakeven (52.4%) for 7+ consecutive days
- Zero edge 3+ picks generated for 3+ days
- Model loading errors in worker logs
- Superseded by a promoted model of the same type

## Key Lessons (Sessions 179-186)

1. **RMSE models decay with staleness** — champion went from 71.2% to 47.9% in 33 days
2. **Quantile models resist staleness** — edge comes from loss function, not drift
3. **Better MAE does NOT mean better betting** — Session 163 proved this definitively
4. **Combos don't work** — NO_VEG + quantile, CHAOS + quantile perform WORSE
5. **Segment monitoring catches issues early** — overall HR can hide directional collapse
