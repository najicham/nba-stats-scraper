# CRITICAL: game_id Format Mismatch Between Tables

**Date**: 2026-01-27 19:05 UTC
**Severity**: CRITICAL - Blocks usage_rate calculation
**Status**: Root cause identified, requires Opus fix

---

## Problem Summary

Usage_rate is **0% for Jan 15-21** but **96%+ for Jan 22-23** after the BDL shooting stats fix. The root cause is:

**game_id formats are REVERSED between `player_game_summary` and `team_offense_game_summary`**

This causes the LEFT JOIN to fail, preventing usage_rate calculation.

---

## Evidence

### Example: LeBron James on Jan 15, 2026

**Player table (`nba_analytics.player_game_summary`):**
```
game_id: 20260115_CHA_LAL  (Away_Home format)
team_abbr: LAL
```

**Team table (`nba_analytics.team_offense_game_summary`):**
```
game_id: 20260115_LAL_CHA  (Home_Away format)
team_abbr: LAL
```

### The Problem

Processor SQL (lines 620-656):
```sql
LEFT JOIN team_stats ts
  ON wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr
```

This JOIN fails because:
- `'20260115_CHA_LAL' != '20260115_LAL_CHA'`

Result:
- `team_fg_attempts`: NULL
- `team_ft_attempts`: NULL
- `team_turnovers`: NULL
- `usage_rate`: Not calculated (all conditions fail)

---

## Why Jan 22-23 Work

For some games, the game_id format happens to match between tables (likely when player table and team table both use the same convention for that specific game).

Jan 22 example likely has matching formats by coincidence.

---

## Impact

**Current State:**
```
Jan 15-21: 0% usage_rate (game_id mismatch)
Jan 22:    96.4% usage_rate (format matches)
Jan 23:    98.7% usage_rate (format matches)
Jan 24:    80.3% usage_rate (format matches)
```

**Player Coverage:** ✅ 101.3% (fixed by SQL bug fix)
**Usage Rate:** ❌ Broken for 50% of dates due to game_id mismatch

---

## Solution Options for Opus

### Option 1: Normalize game_id in One Table (RECOMMENDED)

Create a stored procedure or one-time UPDATE to fix game_id format in one of the tables:

```sql
-- Option A: Fix player_game_summary to match team format
UPDATE `nba-props-platform.nba_analytics.player_game_summary` p
SET game_id = (
  -- Reconstruct game_id in alphabetical order
  CONCAT(
    SUBSTR(game_id, 1, 9),  -- Date part: 20260115_
    CASE
      WHEN SPLIT(game_id, '_')[OFFSET(1)] < SPLIT(game_id, '_')[OFFSET(2)]
        THEN CONCAT(SPLIT(game_id, '_')[OFFSET(1)], '_', SPLIT(game_id, '_')[OFFSET(2)])
      ELSE CONCAT(SPLIT(game_id, '_')[OFFSET(2)], '_', SPLIT(game_id, '_')[OFFSET(1)])
    END
  )
)
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-21'
  AND game_id LIKE '%_%_%'
```

### Option 2: Fix JOIN Logic to Handle Both Formats

Modify the processor SQL to join on BOTH possible game_id formats:

```sql
LEFT JOIN team_stats ts ON (
  (wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr)
  OR
  -- Try reversed format
  (CONCAT(
     SUBSTR(wp.game_id, 1, 9),
     SPLIT(ts.game_id, '_')[OFFSET(2)], '_',
     SPLIT(ts.game_id, '_')[OFFSET(1)]
   ) = ts.game_id AND wp.team_abbr = ts.team_abbr)
)
```

### Option 3: Standardize game_id Format Going Forward

Update BOTH processors to use a canonical game_id format (e.g., always alphabetical by team_abbr):

```python
def canonical_game_id(date_str, team1, team2):
    """Generate game_id in canonical format: YYYYMMDD_TEAM1_TEAM2 (alphabetical)"""
    teams_sorted = sorted([team1, team2])
    return f"{date_str}_{teams_sorted[0]}_{teams_sorted[1]}"
```

Apply to:
- `player_game_summary_processor.py`
- `team_offense_game_summary_processor.py`

### Option 4: Quick Fix - Update Existing Records

Since we know Jan 15-21 have the issue, run a targeted UPDATE:

```sql
-- Fix Jan 15-21 player records to match team format
UPDATE `nba-props-platform.nba_analytics.player_game_summary`
SET game_id = CONCAT(
  SUBSTR(game_id, 1, 9),
  SPLIT(game_id, '_')[OFFSET(2)], '_',
  SPLIT(game_id, '_')[OFFSET(1)]
)
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-21'
  AND game_id IN (
    SELECT DISTINCT CONCAT(
      SUBSTR(p.game_id, 1, 9),
      SPLIT(p.game_id, '_')[OFFSET(2)], '_',
      SPLIT(p.game_id, '_')[OFFSET(1)]
    )
    FROM `nba-props-platform.nba_analytics.team_offense_game_summary` t
    WHERE t.game_date BETWEEN '2026-01-15' AND '2026-01-21'
  )
```

Then re-run Phase 3 backfill to recalculate usage_rate.

---

## Verification Queries

### Check game_id Format Discrepancies

```sql
SELECT
  p.game_date,
  p.game_id as player_game_id,
  t.game_id as team_game_id,
  p.team_abbr,
  CASE
    WHEN p.game_id = t.game_id THEN 'MATCH'
    ELSE 'MISMATCH'
  END as status
FROM `nba-props-platform.nba_analytics.player_game_summary` p
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
  ON t.game_date = p.game_date AND p.team_abbr = t.team_abbr
WHERE p.game_date BETWEEN '2026-01-15' AND '2026-01-25'
  AND p.player_lookup = 'lebronjames'
ORDER BY p.game_date
```

### Count Affected Games

```sql
SELECT
  game_date,
  COUNT(DISTINCT game_id) as unique_player_game_ids,
  COUNT(DISTINCT (
    SELECT t.game_id
    FROM `nba-props-platform.nba_analytics.team_offense_game_summary` t
    WHERE t.game_date = p.game_date
    LIMIT 1
  )) as unique_team_game_ids
FROM `nba-props-platform.nba_analytics.player_game_summary` p
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-25'
GROUP BY game_date
ORDER BY game_date
```

---

## Recommended Approach

**For Immediate Fix:**
1. Use **Option 4** (Quick Fix) to update Jan 15-21 player records
2. Re-run Phase 3 backfill for Jan 15-21
3. Verify usage_rate improves to 80%+

**For Long-term Solution:**
1. Implement **Option 3** (Standardize) in both processors
2. Run backfill to fix all historical data
3. Add validation to prevent future mismatches

---

## Files to Review

**Player Processor:**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
  - Lines 620-656: team_stats CTE and JOIN

**Team Processor:**
- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
  - Check how game_id is generated

---

## Expected Result After Fix

```
Jan 15-21: 80%+ usage_rate (currently 0%)
Jan 22-25: 80%+ usage_rate (currently 96%+)
All dates: Consistent usage_rate calculation
```

---

## Test Plan

After implementing fix:

```bash
# 1. Fix game_ids (using chosen option)

# 2. Re-run Phase 3 backfill
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --start-date 2026-01-15 --end-date 2026-01-21 \
  --parallel --workers 15 --no-resume

# 3. Verify improvement
bq query --use_legacy_sql=false "
SELECT game_date,
       COUNT(*) as total,
       COUNTIF(usage_rate IS NOT NULL) as has_usage,
       ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-25'
  AND minutes_played > 0
GROUP BY game_date
ORDER BY game_date"

# Expected: Jan 15-21 should show 80%+ usage_rate
```

---

## Priority

**CRITICAL** - This blocks:
- Phase 4 cache regeneration (needs complete usage_rate data)
- ML feature quality (missing key feature)
- Production data quality

**Estimate:** 30-60 minutes to implement Option 4 (Quick Fix) + re-run backfill

Good luck! 🚀
