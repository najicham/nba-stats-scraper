# Phase 3 Backfill - Partial Success (Jan 27, 2026)
**Status**: ✅ Player Coverage Fixed | ❌ Usage Rate Still NULL
**Time**: 18:22 UTC

---

## Summary

Phase 3 backfill with SQL fix (revision 00122-js2) successfully fixed player coverage but did NOT fix usage_rate.

### ✅ SUCCESS: Player Coverage

**Before Fix:**
- Jan 15: 63.6% coverage (201/316 players)
- Jan 22: 282 records
- Total records: 4,482 (avg 179/day)

**After Fix:**
- Jan 15: **101.3% coverage** (320/316 players) ✅ EXCEEDED TARGET
- Jan 22: 282 records
- Total records: **12,233 (avg 489/day)** ✅ **2.7x INCREASE**

**Major Players Now Have Records:**
- Jayson Tatum: 6 records (all DNP - Did Not Play)
- Coverage includes 205 active + 115 DNP players

### ❌ PROBLEM: Usage Rate Still NULL

**Current State:**
```
Jan 15-23: 0% usage_rate (0/205 active players)
Jan 24:    78% usage_rate (99/127 players)
Jan 25:    35% usage_rate (49/139 players)
```

**All Star Players Have NULL usage_rate on Jan 22:**
- LeBron James (35 min): NULL
- Stephen Curry (34 min): NULL
- Kevin Durant (44 min): NULL
- Joel Embiid (46 min): NULL

---

## Root Cause Analysis

### Team Stats ARE Available

Team stats were created on **2026-01-23 11:30:10** and exist for all dates:

```sql
-- Verified: Team stats exist for Jan 22 with 16 team records
-- Manual JOIN test WORKS:
SELECT p.player_lookup, t.fg_attempts as team_fg_attempts, ...
FROM player_game_summary p
LEFT JOIN team_offense_game_summary t ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr
WHERE p.game_date = '2026-01-22' AND p.player_lookup = 'lebronjames'

Result:
  lebronjames | team_fg_attempts=86, team_ft_attempts=18, team_turnovers=10 ✅
```

### Processor HAS Usage Rate Calculation

The processor code (lines 1259-1286) includes full usage_rate calculation logic:

```python
# Calculate usage_rate (requires team stats)
usage_rate = None
if (pd.notna(row.get('team_fg_attempts')) and
    pd.notna(row.get('team_ft_attempts')) and
    pd.notna(row.get('team_turnovers')) and
    minutes_decimal and minutes_decimal > 0):

    # Calculate player possessions used
    player_poss_used = (
        fg_attempts +
        (0.44 * ft_attempts) +
        turnovers
    )

    # Calculate team possessions used
    team_poss_used = (
        row['team_fg_attempts'] +
        (0.44 * row['team_ft_attempts']) +
        row['team_turnovers']
    )

    if team_poss_used > 0:
        usage_rate = 100.0 * player_poss_used * 48.0 / (minutes_decimal * team_poss_used)
```

### SQL Query Structure

The processor SQL query includes:

```sql
-- team_stats CTE
team_stats AS (
    SELECT
        game_id,
        team_abbr,
        fg_attempts as team_fg_attempts,
        ft_attempts as team_ft_attempts,
        turnovers as team_turnovers,
        possessions as team_possessions
    FROM `{project_id}.nba_analytics.team_offense_game_summary`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
)

-- Main query
SELECT
    wp.*,
    ts.team_fg_attempts,  -- Should be populated
    ts.team_ft_attempts,  -- Should be populated
    ts.team_turnovers,    -- Should be populated
    ...
FROM with_props wp
LEFT JOIN team_stats ts ON wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr
```

---

## The Mystery

**Why didn't usage_rate get calculated?**

**Evidence:**
1. ✅ Team stats exist for Jan 15-25 (created 2026-01-23)
2. ✅ Backfill ran 2026-01-27 (4 days AFTER team stats created)
3. ✅ Manual JOIN test works perfectly
4. ✅ Processor has calculation logic
5. ✅ SQL query structure looks correct
6. ❌ But usage_rate is still NULL for Jan 15-23

**Possible Explanations:**

### Theory 1: MERGE Not Updating Calculated Fields
The MERGE may be updating the record but NOT recalculating derived fields. If the SQL query returns the OLD data (with NULL usage_rate) and MERGE just overwrites it, the calculation never happens.

**Evidence:**
- Jan 24-25 have usage_rate (processed AFTER team stats existed originally)
- Jan 15-23 have NULL (processed BEFORE team stats existed)
- Backfill MERGE may preserve original NULL values

### Theory 2: SQL Query Doesn't Pull Team Stats
The LEFT JOIN in the processor SQL might not be returning team stats for Jan 15-23, even though manual queries work.

**To Test:**
- Log the actual SQL query executed during backfill
- Check what the query returns for team_fg_attempts

### Theory 3: Backfill Mode Skips Calculation
The processor might have a code path that skips calculation in backfill mode.

**Evidence:**
- Logs show "BACKFILL_MODE: Skipping defensive checks"
- May also skip recalculation

---

## Recommended Next Steps for Opus

### Immediate Investigation

1. **Add Debug Logging to Backfill**
   Add these logs to `player_game_summary_processor.py` around line 1260:

   ```python
   logger.info(f"DEBUG: Player {player_lookup} on {row['game_date']}")
   logger.info(f"  team_fg_attempts: {row.get('team_fg_attempts')}")
   logger.info(f"  team_ft_attempts: {row.get('team_ft_attempts')}")
   logger.info(f"  team_turnovers: {row.get('team_turnovers')}")
   logger.info(f"  minutes_decimal: {minutes_decimal}")

   if (pd.notna(row.get('team_fg_attempts')) and ...):
       logger.info(f"  ✅ Calculating usage_rate")
   else:
       logger.info(f"  ❌ Skipping usage_rate - missing team stats")
   ```

2. **Test Single Game Reprocess**
   Run a minimal test for ONE game on Jan 22:

   ```python
   python -c "
   from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
   p = PlayerGameSummaryProcessor()
   result = p.reprocess_single_game(
       game_id='20260122_LAL_LAC',
       game_date='2026-01-22',
       season=2025
   )
   print(f'Records processed: {len(result)}')
   "
   ```

3. **Check MERGE Behavior**
   Verify what fields the MERGE actually updates. Check `bigquery_save_ops.py` for the MERGE statement.

### Option A: Force Recalculation via DELETE+INSERT

If MERGE is the problem, change backfill to use DELETE+INSERT instead:

```python
# In backfill mode, use DELETE+INSERT instead of MERGE
if opts.get('backfill_mode'):
    # Delete existing records
    delete_query = f"""
    DELETE FROM `{table_id}`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    self.bq_client.query(delete_query).result()

    # Insert fresh records
    self._insert_records(records, table_id)
else:
    # Normal mode: use MERGE
    self._save_with_proper_merge(records, table_id, table_schema)
```

### Option B: Dedicated Usage Rate Backfill

Create a separate script to ONLY recalculate usage_rate:

```sql
UPDATE `nba-props-platform.nba_analytics.player_game_summary` p
SET usage_rate = (
    SELECT
        100.0 *
        (p.fg_attempts + (0.44 * p.ft_attempts) + p.turnovers) *
        48.0 /
        (p.minutes_played * (t.fg_attempts + (0.44 * t.ft_attempts) + t.turnovers))
    FROM `nba-props-platform.nba_analytics.team_offense_game_summary` t
    WHERE t.game_id = p.game_id
      AND t.team_abbr = p.team_abbr
      AND t.game_date = p.game_date
)
WHERE p.game_date BETWEEN '2026-01-15' AND '2026-01-23'
  AND p.minutes_played > 0
  AND p.usage_rate IS NULL
```

### Option C: Re-run Team Stats Processor First

Ensure team_offense_game_summary is fully backfilled before player_game_summary:

```bash
# Step 1: Backfill team stats
python -m backfill_jobs.analytics.team_offense_game_summary.team_offense_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 \
  --parallel --workers 15

# Step 2: THEN re-run player backfill
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 \
  --parallel --workers 15 --no-resume
```

---

## Test Queries for Opus

### Query 1: Verify Team Stats Exist
```sql
SELECT game_date, COUNT(*) as team_records
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-23'
GROUP BY game_date
ORDER BY game_date
```
**Expected**: 12-18 records per date

### Query 2: Test Manual Usage Rate Calculation
```sql
SELECT
  p.player_lookup,
  p.game_date,
  p.minutes_played,
  p.fg_attempts,
  p.ft_attempts,
  p.turnovers,
  t.fg_attempts as team_fg_attempts,
  t.ft_attempts as team_ft_attempts,
  t.turnovers as team_turnovers,
  -- Manual calculation
  100.0 *
  (p.fg_attempts + (0.44 * p.ft_attempts) + p.turnovers) *
  48.0 /
  (p.minutes_played * (t.fg_attempts + (0.44 * t.ft_attempts) + t.turnovers)) as calculated_usage_rate,
  p.usage_rate as stored_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary` p
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
  ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr AND t.game_date = p.game_date
WHERE p.game_date = '2026-01-22'
  AND p.player_lookup IN ('lebronjames', 'stephencurry', 'kevindurant')
```
**Expected**: calculated_usage_rate should have values, stored_usage_rate is NULL

### Query 3: Check What's in Player Table
```sql
SELECT game_date,
       COUNT(*) as total_records,
       COUNTIF(usage_rate IS NULL) as null_usage,
       COUNTIF(usage_rate IS NOT NULL) as has_usage
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-25'
  AND minutes_played > 0
GROUP BY game_date
ORDER BY game_date
```

---

## Current Status

**Phase 3 Backfill:**
- ✅ Player coverage: FIXED (101.3%)
- ❌ Usage rate: NOT FIXED (0% for Jan 15-23)
- ⏸️ Phase 4: BLOCKED until usage_rate resolved

**Next Action:** Opus chat to investigate why usage_rate calculation isn't happening during backfill.

**Files:**
- Investigation: `docs/09-handoff/2026-01-27-REPROCESSING-BLOCKER-INVESTIGATION.md`
- This doc: `docs/09-handoff/2026-01-27-PHASE3-PARTIAL-SUCCESS.md`
- Backfill logs: `/home/naji/.claude/projects/.../toolu_01S8csMNkMM16dpmKAQFjwKM.txt`
