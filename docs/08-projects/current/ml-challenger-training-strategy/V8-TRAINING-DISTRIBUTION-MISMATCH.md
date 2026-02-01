# V8 Training Distribution Mismatch Analysis

**Date:** 2026-02-01 (Session 62)
**Severity:** CRITICAL
**Status:** Root Causes Confirmed - Action Required

---

## Executive Summary

V8 model hit rate collapsed from **72.8%** (Jan 2025) to **55.5%** (Jan 2026) due to **three interrelated distribution mismatches** between training and inference data:

| Issue | Training Data | Inference Data (Jan 2026) | Impact |
|-------|---------------|---------------------------|--------|
| **team_win_pct** | Always 0.5 (100%) | Realistic 0.2-0.9 | MAJOR |
| **Vegas line coverage** | 99% had vegas_line | 43% have vegas_line | MEDIUM |
| **Vegas imputation** | Missing → season_avg | Missing → np.nan | MEDIUM |

**Key Finding:** The `team_win_pct` bug is likely the PRIMARY cause of degradation - the model was trained on broken data where this feature was always 0.5, but now sees realistic values (0.2-0.9) it has never encountered.

---

## Issue 1: team_win_pct Constant Value Bug (MAJOR)

### Discovery

| Period | Records | team_win_pct = 0.5 | Realistic Values |
|--------|---------|-------------------|------------------|
| V8 Training (2022-23) | 24,767 | **100%** | 0% |
| Jan 2025 (baseline) | 4,893 | **100%** | 0% |
| Nov 2025 | 6,563 | 51.5% | 48.5% |
| Dec 2025 | 6,873 | 27.0% | 73.0% |
| Jan 2026 (degraded) | 8,567 | 22.3% | **77.7%** |
| Feb 2026 | 326 | 0% | **100%** |

### Impact

V8 learned that `team_win_pct = 0.5` is **normal and expected**. When the feature store was fixed (Nov 2025+) to include realistic values (0.2-0.9), the model sees feature values it was **NEVER trained on**.

**Jan 2026 team_win_pct Distribution:**
```
0.2 → 677 records (losing teams)
0.3 → 809 records
0.4 → 992 records
0.5 → 3,151 records (league average)
0.6 → 1,770 records
0.7 → 816 records
0.8 → 316 records (winning teams)
0.9 → 36 records
```

### Why This Causes Degradation

1. Model's internal weights for `team_win_pct` are calibrated for constant 0.5
2. When model sees 0.2 (bad team) or 0.8 (good team), it extrapolates incorrectly
3. This affects ALL predictions, not just edge cases

### When Was It Fixed?

The bug was gradually fixed starting Nov 2025:
- **Before Nov 2025:** team_win_pct always 0.5 (bug)
- **Nov 2025:** 51.5% have 0.5 (partially fixed)
- **Dec 2025:** 27% have 0.5 (mostly fixed)
- **Jan 2026:** 22.3% have 0.5 (mostly fixed)
- **Feb 2026:** 0% have 0.5 (fully fixed)

**Root Cause:** The feature calculator wasn't receiving `team_abbr` and defaulted to 0.5. Fixed in Session 49 (commit `1c8d84d3`).

---

## Issue 2: Vegas Line Coverage Drop (MEDIUM)

### Discovery

| Period | Records/Day | Vegas Coverage | Source |
|--------|-------------|----------------|--------|
| V8 Training | 147 | 99.5% | Props-only players |
| Jan 2025 | 158 | 99.4% | Props-only players |
| Jan 2026 | 276 | **43.4%** | ALL players (backfill mode) |

### Impact

The backfill mode introduced in Dec 2025 includes ALL players who played (300-500/day), not just those with prop lines (130-190/day). But Vegas extraction still reads from Phase 3 which only has lines for expected players.

**Result:** 57% of feature store records have `vegas_points_line = 0`.

### Fix Applied (Session 62)

Modified `_batch_extract_vegas_lines()` to use raw betting tables in backfill mode instead of Phase 3.

**Status:** Code fix complete, backfill pending.

---

## Issue 3: Vegas Imputation Mismatch (MEDIUM)

### Discovery

| Phase | Missing Vegas Line Handling | Typical Value |
|-------|----------------------------|---------------|
| Training | Imputed with `player_season_avg` | ~6-8 points |
| Inference | Set to `np.nan` | np.nan |

### Impact

V8's training script (line 131):
```python
df['vegas_points_line_imp'] = df['vegas_points_line'].fillna(df['player_season_avg'])
```

But inference (catboost_v8.py line 763):
```python
vegas_line if vegas_line is not None else ... else np.nan
```

The model learned that missing vegas_line means "low-scoring player" (~6-8 pts), but at inference it sees `np.nan` which CatBoost interprets differently.

### Note on Actual Impact

This issue is partially mitigated because:
1. Predictions are only made for players WITH prop lines
2. The worker overrides feature store vegas_line with fresh betting data
3. Players without prop lines don't get predictions

---

## Hit Rate Analysis by Edge

The degradation is consistent across ALL edge buckets:

| Edge Bucket | Jan 2025 | Jan 2026 | Drop |
|-------------|----------|----------|------|
| 5+ (high edge) | **86.1%** | **60.5%** | **-25.6** |
| 3-5 (medium) | 76.1% | 54.8% | -21.3 |
| 1-3 (low) | 63.4% | 55.0% | -8.4 |

**Key Insight:** High-edge predictions collapsed the most. When the model is MOST confident, it's now MOST wrong. This indicates fundamental miscalibration, not just edge cases.

---

## Implications for New Training

### What V8 Actually Trained On

| Feature | Training Value | Reality |
|---------|----------------|---------|
| team_win_pct | Always 0.5 | 0.2-0.9 |
| vegas_line coverage | 99% had real lines | ~50% typical |
| Missing vegas | Imputed with season avg | Should be np.nan |
| has_vegas_flag | ~55% correct | 95%+ correct in 2026 |
| Records/day | ~150 (props-only) | ~300 (all players) |

### Recommended Training Strategy

**Option A: Train on Recent Data (Nov 2025+) - RECOMMENDED**
- Uses fixed team_win_pct
- Uses fixed has_vegas_flag
- More realistic feature distributions
- **Tradeoff:** Less training data (~40K records vs 77K)

**Option B: Train on Historical + Recent with Feature Fixes**
- Recompute team_win_pct for historical data
- Fix has_vegas_flag consistency
- More data, but requires significant reprocessing

**Option C: Retrain V8 on Same Data, Accept Distribution Shift**
- Model will still be miscalibrated
- Not recommended

---

## Verification Queries

### Check team_win_pct Distribution
```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(100.0 * COUNTIF(CAST(features[OFFSET(24)] AS FLOAT64) = 0.5) / COUNT(*), 1) as pct_half,
  ROUND(STDDEV(CAST(features[OFFSET(24)] AS FLOAT64)), 3) as stddev
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-10-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

### Check Vegas Line Coverage
```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-10-01'
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1 ORDER BY 1
```

### Compare Predicted Players Feature Quality
```sql
WITH predictions AS (
  SELECT DISTINCT player_lookup, game_date
  FROM nba_predictions.prediction_accuracy
  WHERE system_id = 'catboost_v8' AND prediction_correct IS NOT NULL
)
SELECT
  FORMAT_DATE('%Y-%m', fs.game_date) as month,
  ROUND(AVG(CAST(fs.features[OFFSET(24)] AS FLOAT64)), 2) as avg_team_win_pct,
  COUNTIF(CAST(fs.features[OFFSET(24)] AS FLOAT64) = 0.5) as win_pct_half
FROM nba_predictions.ml_feature_store_v2 fs
INNER JOIN predictions p USING (player_lookup, game_date)
WHERE ARRAY_LENGTH(fs.features) >= 33
GROUP BY 1 ORDER BY 1
```

---

## Action Items

### Immediate
- [x] Document root causes (this document)
- [ ] Update experiment plan with findings
- [ ] Re-run feature store backfill with vegas fix

### Before Training Experiments
- [ ] Verify team_win_pct is realistic in training data
- [ ] Decide: train on recent data only OR fix historical data
- [ ] Verify vegas_line coverage after backfill

### Long-term Prevention
- [ ] Add team_win_pct variance check to `/validate-daily`
- [ ] Add feature distribution monitoring
- [ ] Create training data validation checklist

---

## Key Learnings

1. **Feature store bugs can silently corrupt training data** - V8 trained on broken team_win_pct for years
2. **Distribution shifts are hard to detect** - The model "worked" on test data with same bug
3. **Fixing bugs can break models** - When team_win_pct was fixed, it made V8 worse
4. **Always compare training vs inference distributions** - Would have caught this earlier

---

## Related Documents

- [V8 Training Data Analysis](./V8-TRAINING-DATA-ANALYSIS.md) - Bookmaker analysis
- [Vegas Line Root Cause](../feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md)
- [Experiment Plan](../ml-challenger-experiments/EXPERIMENT-PLAN.md)

---

*Created: 2026-02-01 Session 62*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
