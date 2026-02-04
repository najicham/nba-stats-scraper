# L5 Feature DNP Bug - Project Overview

**Priority:** HIGH
**Status:** In Progress
**Created:** 2026-02-04 (Session 113)
**Owner:** Data Quality Team

## Executive Summary

The `points_avg_last_5` and `points_avg_last_10` features in the ML feature store have been incorrectly calculated since season start (Nov 4, 2025), affecting **100% of ~24,000 records**. The bug causes 10-25 point errors for star players with frequent DNPs (Did Not Play games).

**Impact:**
- **26% of predictions** significantly affected (players with DNPs in last 10 games)
- **Stars most impacted:** Jokic, Luka, Kawhi, Curry (load management DNPs)
- **Model performance:** Underestimated star scoring, reduced prediction accuracy
- **Financial impact:** Lower hit rates = reduced profitability

## Root Cause

**Location:** `data_processors/precompute/ml_feature_store/feature_extractor.py`
**Lines:** 1285-1289 (batch path), 1310-1314 (per-player path)

### The Bug

Phase 3 fallback calculation converted NULL points (DNP games) to 0, then included them in averages:

```python
# BUGGY CODE (before fix)
points_list = [(g.get('points') or 0) for g in last_10_games]
phase3_data['points_avg_last_10'] = sum(points_list) / len(points_list)
if len(last_10_games) >= 5:
    phase3_data['points_avg_last_5'] = sum(points_list[:5]) / 5
```

### Example - Kawhi Leonard (2026-01-30)

Kawhi's last 10 games: `21, 28, 24, NULL, NULL, NULL, 33, 35, 26, 26`

| Calculation | L5 Value | Explanation |
|-------------|----------|-------------|
| **Buggy** | 14.6 pts | (21+28+24+0+0)/5 = 14.6 (includes 2 DNPs as zeros) |
| **Correct** | 28.2 pts | (21+28+24+33+35)/5 = 28.2 (skips DNPs, gets 5 real games) |
| **Error** | **-13.6 pts** | **48% underestimate!** |

## Investigation Timeline

### Discovery (Session 113 - 2026-02-04)

1. **Initial Report:** Handoff doc reported 26% of records have L5 values 5+ points off
2. **Star Player Examples:**
   - Jokic: 6.2 vs 31.0 (24.8 pts off)
   - Luka: 18.4 vs 33.4 (15.0 pts off)
   - Kawhi: 9.0 vs 29.2 (20.2 pts off)
   - Curry: 13.2 vs 21.4 (8.2 pts off)

### Root Cause Analysis

1. **Checked player_daily_cache:** ✅ Values CORRECT (28.2 for Kawhi)
2. **Checked ML feature store:** ❌ Values WRONG (14.6 for Kawhi)
3. **Discovered:** ML feature store using Phase 3 fallback, not Phase 4
4. **Found bug:** Phase 3 fallback converting DNPs to 0

### Why 100% Phase 3 Fallback?

All ML feature store records show `data_source='mixed'`, meaning Phase 3 fallback is being used for some features. The L5/L10 features are falling back to Phase 3 calculation, which had the DNP bug.

Possible reasons:
- Phase 4 player_daily_cache has incomplete coverage (293 vs 351 players on Jan 30)
- ML feature store generates predictions for ALL players, Phase 4 only caches active players
- Missing players fall back to Phase 3 calculation

## Fix Applied

### Code Changes

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

**Batch cache path (lines 1283-1301):**
```python
# FIXED CODE
# Calculate aggregations from games
# FIX (Session 113): Filter out DNPs (NULL points) BEFORE taking windows
# Bug was: (g.get('points') or 0) converted NULL to 0, polluting averages
# For star players with DNPs (Kawhi, Jokic), this caused 10-20 pt errors
if last_10_games:
    # Filter to only games where player actually played (points > 0)
    played_games = [g for g in last_10_games if g.get('points') is not None and g.get('points') > 0]

    if played_games:
        points_list = [g.get('points') for g in played_games]

        # L10: Use up to 10 actual games
        if len(played_games) >= 10:
            phase3_data['points_avg_last_10'] = sum(points_list[:10]) / 10
        elif len(played_games) > 0:
            phase3_data['points_avg_last_10'] = sum(points_list) / len(played_games)

        # L5: Use up to 5 actual games
        if len(played_games) >= 5:
            phase3_data['points_avg_last_5'] = sum(points_list[:5]) / 5
```

**Per-player query path (lines 1308-1326):** Similar fix applied.

**Commit:** `8eba5ec3`
**Deployed:** `nba-phase4-precompute-processors` @ 2026-02-04 03:53 UTC

### Testing

Before fix validation:
```sql
-- Kawhi Leonard on 2026-01-30
-- Manual calculation: (21+28+24+33+35)/5 = 28.2 ✅
-- player_daily_cache: 28.2 ✅
-- ml_feature_store: 14.6 ❌ (WRONG!)
```

## Validation Results

### Comprehensive Season Audit (Nov 4 - Feb 4)

```sql
-- 91 days, ~24,000 records checked
SELECT
  COUNT(*) as total_records,
  COUNTIF(data_source = 'mixed') as mixed_records,
  ROUND(100.0 * COUNTIF(data_source = 'mixed') / COUNT(*), 1) as pct_mixed
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-04'
```

**Results:**
- **Total records:** 24,031
- **Using Phase 3 fallback:** 24,031 (100%)
- **Bad default pattern:** 15 records (0.06% - Nov 4-9 cold start)
- **L5 much higher than L10:** 5 records (0.02% - legitimate hot streaks)
- **Average quality score:** 84.2 (good despite bug)

### Feature-Level Validation

| Feature | Source | Status |
|---------|--------|--------|
| points_avg_last_5 | Phase 3 fallback | ❌ BUGGY |
| points_avg_last_10 | Phase 3 fallback | ❌ BUGGY |
| points_avg_season | Phase 3 | ✅ CORRECT |
| fatigue_score | Phase 4 | ✅ CORRECT |
| shot_zone_mismatch | Phase 4 | ✅ CORRECT |
| vegas_points_line | Raw tables | ✅ CORRECT |

**Conclusion:** Only L5/L10 affected. Other 35 features working correctly.

## Reprocessing Plan

### Scope

**All ML feature store records since season start:**
- **Date range:** 2025-11-04 to 2026-02-04
- **Total days:** 91
- **Total records:** ~24,000
- **Services affected:** ml_feature_store_processor

### Commands

```bash
# 1. Reprocess ML feature store (entire season)
PYTHONPATH=. python data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  --start-date 2025-11-04 \
  --end-date 2026-02-04 \
  --backfill

# 2. Regenerate predictions (after ML features fixed)
# TBD - coordinate with prediction-coordinator team
```

### Validation After Reprocessing

```sql
-- 1. Check data source distribution (expect more Phase 4)
SELECT
  data_source,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-04'  -- After reprocessing
GROUP BY data_source;

-- 2. Spot check Kawhi Leonard (should be 28.2, not 14.6)
SELECT
  game_date,
  ROUND(features[OFFSET(0)], 1) as pts_l5,
  ROUND(features[OFFSET(1)], 1) as pts_l10,
  data_source
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'kawhileonard'
  AND game_date = '2026-01-30';

-- Expected: pts_l5 = 28.2 (not 14.6)

-- 3. Check for DNP handling across all star players
WITH star_players AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2026-01-30'
    AND features[OFFSET(0)] > 25  -- Stars averaging 25+ pts
  LIMIT 20
)
SELECT
  f.player_lookup,
  ROUND(f.features[OFFSET(0)], 1) as ml_l5,
  ROUND(c.points_avg_last_5, 1) as cache_l5,
  ROUND(ABS(f.features[OFFSET(0)] - c.points_avg_last_5), 1) as diff
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_precompute.player_daily_cache c
  ON f.player_lookup = c.player_lookup
  AND f.game_date = c.cache_date
WHERE f.game_date = '2026-01-30'
  AND f.player_lookup IN (SELECT player_lookup FROM star_players)
ORDER BY diff DESC;

-- Expected: diff < 1.0 for all players
```

## Impact Assessment

### Model Performance Impact

**Before fix (with bug):**
- Stars underestimated by 10-25 pts → Model predicts UNDER too often
- Bench players with injury DNPs overestimated → Model predicts OVER too often
- Net effect: Reduced hit rate, lower profitability

**Expected improvement after fix:**
- More accurate star player predictions
- Better calibration for players with DNPs
- Higher hit rate on high-confidence picks (edge >= 5)

### Historical Data Integrity

**Affected periods:**
- 2025-11-04 to 2026-02-04: ALL records need reprocessing

**Clean periods:**
- None - bug existed since ML feature store creation

### Business Impact

- **Predictions affected:** ~24,000 (all Nov-Feb)
- **User-facing predictions:** Likely showed incorrect confidence
- **Model training:** V9 model trained on buggy features (needs retraining?)

## Next Steps

### Immediate (Session 113)
- [x] Document bug in project directory
- [ ] Thorough spot check of November records (verify EVERY field)
- [ ] Update spot-check-features skill with new validation queries
- [ ] Reprocess ML feature store (Nov 4 - Feb 4)

### Short-term (Next session)
- [ ] Regenerate predictions with correct features
- [ ] Compare hit rates before/after fix
- [ ] Retrain V9 model on clean features
- [ ] Add feature validation to daily pipeline

### Long-term (Next week)
- [ ] Add pre-commit validation for feature calculations
- [ ] Implement feature store reconciliation checks (Phase 4 vs Phase 3)
- [ ] Add alerting for DNP calculation anomalies
- [ ] Document DNP handling patterns in code standards

## Lessons Learned

### What Went Wrong

1. **Implicit type coercion:** `(g.get('points') or 0)` silently converted NULL to 0
2. **No validation:** Feature store had no validation against source tables
3. **Silent fallback:** Phase 3 fallback happened without alerting
4. **No spot checks:** Never manually verified star player L5 values

### Prevention Measures

1. **Explicit NULL handling:** Always check `is not None` before `or` operator
2. **Reconciliation checks:** Daily validation of feature store vs source tables
3. **Fallback alerting:** Alert when >10% records use Phase 3 fallback
4. **Spot check automation:** Daily validation of known-good records (stars)

### Similar Risks

**Other features using `.get(field) or default` pattern:**
- Check all aggregators in precompute processors
- Check all feature calculators
- Audit for similar NULL-to-zero conversions

## Files Modified

| File | Lines | Change |
|------|-------|--------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 1283-1301 | Filter DNPs before L5/L10 calculation (batch path) |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 1308-1326 | Filter DNPs before L5/L10 calculation (per-player path) |

## Related Documentation

- **Handoff:** `docs/09-handoff/2026-02-04-SESSION-113-L5-FEATURE-BUG-HANDOFF.md`
- **Skill:** `.claude/skills/spot-check-features/` (needs update)
- **System Features:** `docs/02-operations/system-features.md`
- **Session Learnings:** `docs/02-operations/session-learnings.md` (add DNP handling pattern)

## Contacts

- **Bug Reporter:** Session 113 investigation
- **Fix Developer:** Claude Sonnet 4.5 (Session 113)
- **Deployment:** 2026-02-04 03:53 UTC
- **Verification:** Pending reprocessing completion
