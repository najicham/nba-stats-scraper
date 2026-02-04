# Session 113 Handoff - L5 Feature Validation & Reprocessing

**Date:** 2026-02-04
**Session:** 113
**Status:** READY FOR THOROUGH VALIDATION
**Priority:** HIGH
**Context Used:** 72% (144k/200k tokens)

## Executive Summary

**What We Accomplished:**
- ✅ Identified L5/L10 DNP bug in `feature_extractor.py`
- ✅ Fixed the bug (filter DNPs before taking head(5))
- ✅ Deployed fix to production (commit 8eba5ec3)
- ✅ Created comprehensive documentation
- ✅ Partial validation (13/37 features, 1/5 players)

**What's Still Needed:**
- ⚠️ **CRITICAL:** Thorough validation before reprocessing 24K records
- ⚠️ Test the fix works correctly on one date
- ⚠️ Validate player_daily_cache doesn't have its own bugs
- ⚠️ Understand discrepancies found (team pace +12 pts, season avg +3 pts)
- ⚠️ Validate remaining 24/37 features

**Why We Stopped:**
- Found concerning discrepancies that we don't fully understand
- Only validated 35% of features - not confident enough to reprocess
- Better to be thorough now than reprocess with other bugs present

## The Bug (Confirmed & Fixed)

### Root Cause
**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`
**Lines:** 1285-1289 (batch path), 1310-1314 (per-player path)

**Before (BUGGY):**
```python
points_list = [(g.get('points') or 0) for g in last_10_games]
phase3_data['points_avg_last_5'] = sum(points_list[:5]) / 5
```
Converts NULL points (DNPs) to 0, then includes them in average.

**After (FIXED):**
```python
played_games = [g for g in last_10_games if g.get('points') is not None and g.get('points') > 0]
if len(played_games) >= 5:
    phase3_data['points_avg_last_5'] = sum(g['points'] for g in played_games[:5]) / 5
```
Filters out DNPs BEFORE taking head(5).

**Deployed:** ✅ Service `nba-phase4-precompute-processors` @ 2026-02-04 03:53 UTC

### Impact
- **Records affected:** 24,031 (100% of Nov-Feb data)
- **Significant errors:** ~6,240 (26% - players with DNPs)
- **Example:** Kawhi Leonard Jan 30 - Shows 14.6, should be 28.2 (13.6 pt error!)

## Validation Results So Far

### What We Validated (Donovan Mitchell, Nov 15, 2025)

| Feature | Name | ML Value | Manual Calc | Diff | Status |
|---------|------|----------|-------------|------|--------|
| 0 | points_avg_last_5 | 29.2 | 31.6 | -2.4 | ❌ DNP bug |
| 1 | points_avg_last_10 | 30.3 | 28.0 | +2.3 | ❌ DNP bug |
| 2 | points_avg_season | 30.2 | 27.2 | +3.0 | ⚠️ Unknown |
| 22 | team_pace_last_10 | 116.9 | 104.77 | +12.13 | ⚠️ **MAJOR ISSUE** |
| 23 | team_off_rating_last_10 | 115.35 | 115.84 | -0.49 | ✅ Close |
| 25 | vegas_points_line | 25.5 | 25.5 (DK) | 0.0 | ✅ Correct |
| 26 | vegas_opening_line | 28.5 | 28.5 | 0.0 | ✅ Correct |
| 27 | vegas_line_move | -3.0 | -3.0 | 0.0 | ✅ Correct |
| 5-8 | Composite factors | Various | [Valid ranges] | N/A | ✅ Pass |

**Validated:** 13/37 features (35%)

### Critical Discrepancies Found

#### 1. Team Pace Mismatch (+12.13 pts)
- **ML feature:** 116.9
- **Manual calc:** 104.77 (Cavaliers last 10 games)
- **Concern:** 116.9 is closer to offensive_rating than pace - possible field swap?
- **Impact:** If this is a bug, it affects ALL players and needs fixing BEFORE reprocessing

#### 2. Season Average Discrepancy (+3.0 pts)
- **ML feature:** 30.2
- **Manual calc:** 27.2
- **Possible causes:** Including playoff games? DNP handling in season calc? Wrong season_year filter?
- **Impact:** If systematic, affects feature 2 for all players

#### 3. L5/L10 Values Don't Match Expected Buggy Output
- **Current ML:** 29.2
- **Manual (correct):** 31.6
- **Buggy code would give:** 22.4 (if it converts NULL to 0)
- **Concern:** We don't fully understand where 29.2 comes from
- **Hypothesis:** ML features generated at different time? Different data? player_daily_cache has same values (29.2) so they're consistent, but both wrong?

### Data Quality Issues Found

#### Unmarked DNP - Oct 31, 2025 (Donovan Mitchell)
```
points = 0
minutes_played = NULL
is_dnp = NULL  # Should be TRUE!
```
This pollutes calculations if not properly filtered. Need to audit all games for unmarked DNPs.

## What Needs Validation

### Phase 1: Test the Fix (CRITICAL)
**Objective:** Verify our fixed code actually works correctly

**Process:**
1. Run ML feature processor on ONE recent date (e.g., 2026-02-03)
2. Compare output to manual calculations for 5 players
3. Confirm L5/L10 values match manual within 0.5 pts

**Command:**
```bash
PYTHONPATH=. python data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  --start-date 2026-02-03 \
  --end-date 2026-02-03 \
  --force  # Force reprocessing even if exists
```

**Validation Query:**
```sql
-- After running processor, check if values match manual
WITH manual_calc AS (
  SELECT
    player_lookup,
    ROUND(AVG(points), 1) as manual_l5
  FROM (
    SELECT player_lookup, points,
      ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
    FROM nba_analytics.player_game_summary
    WHERE game_date < '2026-02-03'
      AND points IS NOT NULL
  )
  WHERE rn <= 5
  GROUP BY player_lookup
)
SELECT
  f.player_lookup,
  ROUND(f.features[OFFSET(0)], 1) as ml_l5,
  m.manual_l5,
  ROUND(ABS(f.features[OFFSET(0)] - m.manual_l5), 1) as diff
FROM nba_predictions.ml_feature_store_v2 f
JOIN manual_calc m ON f.player_lookup = m.player_lookup
WHERE f.game_date = '2026-02-03'
  AND m.manual_l5 > 20  -- Stars only
ORDER BY diff DESC
LIMIT 20;
```

**Success Criteria:** All diff < 1.0

### Phase 2: Validate player_daily_cache (CRITICAL)
**Objective:** Ensure Phase 4 doesn't have its own bugs

**Concern:** We saw player_daily_cache shows 29.2 (same as ML feature store), but manual calc shows 31.6. This suggests player_daily_cache might have the SAME bug or a different bug.

**Check:** Does player_daily_cache's StatsAggregator have the same DNP bug?

**File to check:** `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py`

**Look at line 28:**
```python
last_5_games = player_games.head(5)
```

Does it filter DNPs before head(5)? Or does it have the same bug?

**Validation Query:**
```sql
-- Check if player_daily_cache matches manual for 10 random stars
WITH star_sample AS (
  SELECT DISTINCT player_lookup
  FROM nba_precompute.player_daily_cache
  WHERE cache_date = '2026-02-03'
    AND points_avg_last_5 > 20
  ORDER BY RAND()
  LIMIT 10
),
manual_calc AS (
  SELECT
    player_lookup,
    ROUND(AVG(points), 1) as manual_l5
  FROM (
    SELECT player_lookup, points,
      ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
    FROM nba_analytics.player_game_summary
    WHERE game_date < '2026-02-03'
      AND points IS NOT NULL
  )
  WHERE rn <= 5
  GROUP BY player_lookup
)
SELECT
  c.player_lookup,
  ROUND(c.points_avg_last_5, 1) as cache_l5,
  m.manual_l5,
  ROUND(ABS(c.points_avg_last_5 - m.manual_l5), 1) as diff
FROM nba_precompute.player_daily_cache c
JOIN manual_calc m ON c.player_lookup = m.player_lookup
WHERE c.cache_date = '2026-02-03'
  AND c.player_lookup IN (SELECT player_lookup FROM star_sample)
ORDER BY diff DESC;
```

**If diff > 1.0:** player_daily_cache ALSO has bugs and needs fixing!

### Phase 3: Investigate Team Pace Issue (HIGH PRIORITY)
**Objective:** Understand +12.13 pt discrepancy

**Hypothesis 1:** Fields are swapped (pace ↔ offensive_rating)
**Hypothesis 2:** Different calculation method
**Hypothesis 3:** Different game window

**Validation:**
```sql
-- Check team_offense_game_summary source data
SELECT game_date, team_abbr, pace, offensive_rating
FROM nba_analytics.team_offense_game_summary
WHERE team_abbr = 'CLE'
  AND game_date < '2025-11-15'
ORDER BY game_date DESC
LIMIT 10;

-- Manual calculation
SELECT
  ROUND(AVG(pace), 2) as avg_pace,
  ROUND(AVG(offensive_rating), 2) as avg_off_rating
FROM (
  SELECT pace, offensive_rating
  FROM nba_analytics.team_offense_game_summary
  WHERE team_abbr = 'CLE'
    AND game_date < '2025-11-15'
  ORDER BY game_date DESC
  LIMIT 10
);
```

**Check TeamAggregator code:**
`data_processors/precompute/player_daily_cache/aggregators/team_aggregator.py` line 27

**If bug found:** Fix before reprocessing!

### Phase 4: Validate ALL 37 Features
**Objective:** Ensure no other systematic bugs

**Sample Players:**
1. donovanmitchell (star, 30.2 PPG) - Already started
2. juliusrandle (starter, 25.6 PPG)
3. dontedivincenzo (role, 13.9 PPG)
4. jakobpoeltl (role, 11.1 PPG)
5. tjmcconnell (bench, 3.4 PPG)

**Date:** 2025-11-15 (mid-season, after cold start)

**Process:** For EACH player, validate ALL 37 features against source tables.

**Reference:** See `docs/08-projects/current/2026-02-04-l5-feature-dnp-bug/VALIDATION-PLAN.md` for detailed queries.

**Time Estimate:** 2-3 hours for complete validation

### Phase 5: Investigate Unmarked DNPs
**Objective:** Understand data quality issue

**Query:**
```sql
-- Find all games that look like DNPs but aren't marked
SELECT
  game_date,
  player_lookup,
  points,
  minutes_played,
  is_dnp,
  dnp_reason,
  team_abbr
FROM nba_analytics.player_game_summary
WHERE game_date >= '2025-10-01'
  AND (
    (points = 0 AND minutes_played IS NULL AND is_dnp IS NULL)
    OR (points IS NULL AND minutes_played IS NULL AND is_dnp IS NULL)
  )
ORDER BY game_date DESC
LIMIT 100;
```

**If systematic:** May need to fix upstream scraper or add validation.

## Recommended Approach

### Option 1: Single New Chat (Sequential)
**Pros:** Single context, easier to track
**Cons:** Slower (4-5 hours total)
**Process:**
1. Test fix on one date
2. Validate player_daily_cache
3. Fix team pace if needed
4. Validate all 37 features
5. Reprocess

### Option 2: Multiple Parallel Chats (Faster)
**Pros:** Much faster (1-2 hours total)
**Cons:** Need coordination
**Process:**
- **Chat A:** Test fix on Feb 3 + validate output
- **Chat B:** Investigate team pace issue + fix if needed
- **Chat C:** Validate player_daily_cache + fix if needed
- **Chat D:** Complete 37-feature validation for remaining players
- **Chat E (final):** Compile results + reprocess if all clear

## Success Criteria Before Reprocessing

- [ ] Fix tested on one date and produces correct L5/L10 values (diff < 1.0)
- [ ] player_daily_cache validated and confirmed correct (or fixed)
- [ ] Team pace issue understood and resolved
- [ ] All 37 features validated for at least 2 players across different tiers
- [ ] No major bugs found in other feature categories
- [ ] Confidence level: HIGH that reprocessing will produce correct data

## Files & Documentation

### Code Files
- `data_processors/precompute/ml_feature_store/feature_extractor.py` - FIXED (lines 1285-1314)
- `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py` - NEEDS CHECKING
- `data_processors/precompute/player_daily_cache/aggregators/team_aggregator.py` - NEEDS CHECKING

### Documentation
- `docs/08-projects/current/2026-02-04-l5-feature-dnp-bug/PROJECT-OVERVIEW.md` - Complete analysis
- `docs/08-projects/current/2026-02-04-l5-feature-dnp-bug/VALIDATION-PLAN.md` - 37-feature validation strategy
- `docs/08-projects/current/2026-02-04-l5-feature-dnp-bug/VALIDATION-RESULTS.md` - Partial results
- `docs/08-projects/current/2026-02-04-l5-feature-dnp-bug/ACTION-PLAN.md` - Reprocessing steps

### Updated Skills
- `.claude/skills/spot-check-features/SKILL.md` - Added DNP validation checks

## Key Queries

### Test Fix on One Date
```bash
# Run processor for Feb 3 only
PYTHONPATH=. python data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  --start-date 2026-02-03 --end-date 2026-02-03 --force
```

### Validate Output
See Phase 1 validation query above.

### Full Reprocessing (ONLY AFTER ALL VALIDATION PASSES)
```bash
PYTHONPATH=. python data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  --start-date 2025-11-04 --end-date 2026-02-04 --backfill
```

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| player_daily_cache has same bug | MEDIUM | HIGH | Validate Phase 4 first, fix if needed |
| Team pace is systematic bug | MEDIUM | HIGH | Investigate before reprocessing |
| Other features have bugs | LOW | HIGH | Complete 37-feature validation |
| Fix doesn't work as expected | LOW | CRITICAL | Test on one date first |
| Reprocessing creates new issues | LOW | MEDIUM | Can rollback, have backups |

## Next Session Checklist

**Start here:**
1. Read this handoff doc
2. Review `docs/08-projects/current/2026-02-04-l5-feature-dnp-bug/VALIDATION-PLAN.md`
3. Decide: Single chat or parallel chats?
4. **CRITICAL:** Test fix on Feb 3 FIRST
5. Validate player_daily_cache
6. Investigate team pace issue
7. Only reprocess if ALL validation passes

## Questions to Answer

1. **Why does ML feature show 29.2 when manual shows 31.6?** Is this the DNP bug or something else?
2. **Why does team_pace show 116.9 vs manual 104.77?** Field swap? Calc bug?
3. **Does player_daily_cache have the same DNP bug?** Need to check StatsAggregator
4. **Are there other bugs in the 24 features we haven't validated?**
5. **Will our fix actually work correctly when we reprocess?**

**DO NOT reprocess 24,000 records until these questions are answered!**

---

**Session 113 Status:** PAUSED for thorough validation
**Next Session:** Start with Phase 1 (test fix on one date)
**Estimated Time to Complete:** 4-5 hours (single chat) or 1-2 hours (parallel chats)
**Priority:** HIGH - Affects all predictions since Nov 4
