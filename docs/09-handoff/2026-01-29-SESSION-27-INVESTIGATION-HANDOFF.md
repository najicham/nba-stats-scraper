# Session 27 Investigation Handoff

**Date:** 2026-01-29
**Focus:** Feature store bug investigation and experiment re-validation
**Status:** Complete

---

## Session Summary

This session investigated the feature store bug root cause and re-validated all 2024-25 experiments with corrected data.

### Key Accomplishments

1. **Root cause identified:** L5/L10 feature calculation used `<=` instead of `<` date comparison, including current game in averages (future information leak)

2. **Verified patch:** Confirmed 100% L5/L10 match rate after fix (8,456 records patched)

3. **Re-ran experiments:** A3, B1, B2, B3 now validated on clean 2024-25 data

4. **Production comparison:** Confirmed production model (70.7%) matches experimental results

---

## Root Cause Analysis

### The Bug
```sql
-- BUGGY: Included current game
WHERE game_date <= '2025-01-09'

-- CORRECT: Excludes current game
WHERE game_date < '2025-01-09'
```

### Impact
| Data | Before Fix | After Fix |
|------|------------|-----------|
| 2024-25 L5 match rate | 57% | 100% |
| 2025-26 L5 match rate | 46-92% | 100% |
| Experiment hit rates | 73-74% | 69-71% |

### Evidence
For player `cadecunningham` on 2025-01-09:
- Cache L5 (correct): **24.4** (games before Jan 9)
- Feature store L5 (buggy): **27.0** (included Jan 9 game)

---

## Experiment Results Summary

### Clean Data Performance

| Experiment | Training | Evaluation | Hit Rate | ROI |
|------------|----------|------------|----------|-----|
| A1 | 2021-22 | 2022-23 | 72.1% | +37.5% |
| A2 | 2021-23 | 2023-24 | 73.9% | +41.1% |
| **A3_fixed** | 2021-24 | 2024-25 | **70.8%** | +35.0% |
| **B1_fixed** | 2021-23 | 2024-25 | **70.6%** | +34.7% |
| **B2_fixed** | 2023-24 | 2024-25 | **69.5%** | +32.7% |
| **B3_fixed** | 2022-24 | 2024-25 | **70.7%** | +34.9% |

### Production Validation
| Model | Predictions | Hit Rate | Date Range |
|-------|-------------|----------|------------|
| catboost_v8 (production) | 17,561 | 70.7% | Nov 2024 - Jan 2026 |

**Conclusion:** Production matches experiments. Model is validated.

---

## Documentation Created

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-ROOT-CAUSE.md` | Detailed bug analysis |
| `docs/08-projects/current/catboost-v8-performance-analysis/EXPERIMENT-RESULTS-2026-01-29.md` | Complete experiment documentation |
| This handoff | Session summary |

---

## Files Modified/Created

### Documentation
- `FEATURE-STORE-BUG-ROOT-CAUSE.md` (new)
- `EXPERIMENT-RESULTS-2026-01-29.md` (new)

### Experiment Artifacts
```
ml/experiments/results/
├── A3_fixed_results.json (new)
├── B1_fixed_results.json (new)
├── B2_fixed_results.json (new)
├── B3_fixed_results.json (new)
├── catboost_v9_exp_A3_fixed_20260129_*.cbm (new)
├── catboost_v9_exp_B1_fixed_20260129_*.cbm (new)
├── catboost_v9_exp_B2_fixed_20260129_*.cbm (new)
└── catboost_v9_exp_B3_fixed_20260129_*.cbm (new)
```

---

## Key Findings

1. **Model performs as expected:** 70%+ hit rate validated across 3 seasons
2. **Bug inflation quantified:** 3-4% artificial boost from future information
3. **Production stable:** No deployment needed - production already correct
4. **Slight 2024-25 decline:** 70% vs 72-74% in prior seasons (may warrant investigation)

---

## Next Steps (Future Sessions)

### P1: Investigate 2024-25 Performance Decline
- Is 70% vs 74% statistically significant?
- Market efficiency improving?
- Feature drift?

### P2: Prevent Future Bugs
- Add pre-commit hook for date comparison validation
- Add feature store consistency checks to daily validation

### P3: Consider Model Retraining
- Train new model including 2024-25 data
- Test if recent data improves performance

---

## Quick Reference Commands

```bash
# Compare all experiments
PYTHONPATH=. python ml/experiments/compare_results.py

# Verify feature store
bq query --use_legacy_sql=false "
SELECT CASE WHEN game_date < '2025-07-01' THEN '2024-25' ELSE '2025-26' END as season,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as l5_match_pct
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01' GROUP BY 1"

# Check production accuracy
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as n, ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2024-10-01' AND system_id = 'catboost_v8' AND recommendation IN ('OVER','UNDER')
GROUP BY 1"
```

---

*Session 27 - Investigation Complete*
*Parallel session handled the patch application*
