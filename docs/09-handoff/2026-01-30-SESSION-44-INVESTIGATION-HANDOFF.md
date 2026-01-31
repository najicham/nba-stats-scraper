# Session 44 Handoff - Investigation and Documentation

**Date:** 2026-01-30
**Focus:** Critical bug fix, model drift investigation, prediction coverage analysis

---

## Session Summary

Session 44 fixed a critical syntax error, ran comprehensive daily validation, and performed deep investigation into model drift and prediction coverage issues.

### Key Accomplishments

1. **Fixed Critical Bug**: Syntax error in `injury_parser.py` deployed to both scraper services
2. **Investigated Model Drift**: 3 consecutive weeks below 55% hit rate - we're now WORSE than Vegas
3. **Explained Prediction Coverage**: 44% coverage is by design (minutes filter + prop line requirement)
4. **Documented Everything**: Created comprehensive project docs

---

## Critical Finding: Model is Losing to Vegas

### The Numbers

| Week | Our Hit Rate | Our MAE | Vegas MAE | Our Edge |
|------|--------------|---------|-----------|----------|
| Jan 25 | 50.6% | 5.87 | 4.71 | **-1.16** |
| Jan 18 | 51.6% | 5.80 | 5.04 | **-0.76** |
| Jan 11 | 51.1% | 5.85 | 4.91 | **-0.93** |
| Jan 04 | 62.7% | 4.46 | 4.65 | +0.19 |
| Dec 28 | 65.7% | 4.69 | 5.16 | +0.47 |

**We went from beating Vegas by 0.5 points to losing by 1+ point.**

### Root Cause: Star Players

| Tier | This Week Hit Rate | Bias |
|------|-------------------|------|
| Stars (25+ pts) | **30.0%** | **-10.26** |
| Starters (15-25) | 41.3% | -2.33 |
| Rotation (5-15) | 57.4% | +1.10 |
| Bench (<5) | 58.0% | +5.36 |

**Stars are scoring 10+ points MORE than predicted.** The model trained on 2021-2024 data can't capture current star usage patterns.

### Experiments That Failed

- **V9 Recency Weighting**: Made it worse (+1-4% MAE)
- **V11 Seasonal Features**: Made it worse (+0.86% MAE)

Both were deleted. V8 remains production model.

---

## Deployments Made

| Service | Revision | Commit | Fix |
|---------|----------|--------|-----|
| nba-scrapers | 00111-zn8 | e715694d | injury_parser.py syntax fix |
| nba-phase1-scrapers | 00025-wvt | e715694d | Same fix |

---

## Prediction Coverage Explained

**Why only 44% (141/319) players have predictions:**

| Category | Count | Gets Prediction? |
|----------|-------|------------------|
| Above 15 min/game average | 118 | ✅ Yes |
| Below 15 min + has prop line | 23 | ✅ Yes |
| Below 15 min + no prop line | 178 | ❌ No |

This is intentional - no point predicting low-minute players without betting lines.

---

## Next Session Checklist

### Priority 1: Decision on Model
- [ ] **Accept current V8** - 50% hit rate is still slightly better than random
- [ ] **OR explore matchup features** - may help star predictions (high effort)

### Priority 2: Monitoring Improvements
- [ ] Add star player tier (25+ pts) hit rate to daily validation
- [ ] Add Vegas edge tracking to daily validation
- [ ] Alert when edge goes negative for 2+ weeks

### Priority 3: Optional
- [ ] Investigate player trajectory features (pts_slope_10g) - but test carefully
- [ ] Look into game importance context features

---

## Documentation Created

| Path | Description |
|------|-------------|
| `docs/08-projects/current/2026-01-30-session-44-maintenance/README.md` | Session overview |
| `docs/08-projects/current/2026-01-30-session-44-maintenance/INVESTIGATION-FINDINGS.md` | Full investigation report |
| `docs/08-projects/current/2026-01-30-session-44-maintenance/MODEL-DRIFT-STATUS-UPDATE.md` | Model drift status |
| `docs/09-handoff/2026-01-30-SESSION-44-INVESTIGATION-HANDOFF.md` | This file |

---

## Key Queries for Future Reference

### Weekly Model Performance
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

### Star Player Performance
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND actual_points >= 25
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY 1
ORDER BY 1 DESC;
```

---

## System Status

- **Pipeline**: Healthy (Phase 3: 5/5, MERGE working)
- **Model**: Underperforming (50% hit rate, negative Vegas edge)
- **Coverage**: Working as designed (44%)
- **Scrapers**: Fixed and deployed

---

*Session 44 complete. Model drift is the primary issue requiring strategic decision.*
