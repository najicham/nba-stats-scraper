# URGENT: Fix Usage Rate Calculation in Phase 3 Backfill

## Context

Your SQL fix (revision 00122-js2) successfully fixed player coverage from 63.6% to 101.3%! 🎉 But we have a critical remaining issue: **usage_rate is still NULL for Jan 15-23** even though all the required data exists.

## The Problem

After running the Phase 3 backfill with your SQL fix:
- ✅ Player coverage: FIXED (12,233 records, 2.7x increase)
- ❌ Usage rate: NOT FIXED (still 0% for Jan 15-23)

**Current State:**
```
Jan 15-23: 0% usage_rate (0/205 active players)
Jan 24:    78% usage_rate (unchanged)
Jan 25:    35% usage_rate (unchanged)
```

**Star players with NULL usage_rate on Jan 22:**
- LeBron James (35 min): NULL
- Stephen Curry (34 min): NULL
- Kevin Durant (44 min): NULL
- Joel Embiid (46 min): NULL

## The Mystery: Everything SHOULD Work

**1. Team Stats Exist ✅**
```sql
SELECT game_date, COUNT(*) as team_records
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date = '2026-01-22'
-- Returns: 16 records (all teams, all fields populated)
```

**2. Manual JOIN Works Perfectly ✅**
```sql
SELECT
  p.player_lookup,
  t.fg_attempts as team_fg_attempts,
  t.ft_attempts as team_ft_attempts,
  t.turnovers as team_turnovers
FROM `nba-props-platform.nba_analytics.player_game_summary` p
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
  ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr AND t.game_date = '2026-01-22'
WHERE p.game_date = '2026-01-22' AND p.player_lookup = 'lebronjames'

-- Returns: team_fg_attempts=86, team_ft_attempts=18, team_turnovers=10 ✅
```

**3. Processor Has Calculation Logic ✅**
File: `data_processors/analytics/player_game_summary/player_game_summary_processor.py` lines 1259-1286

```python
# Calculate usage_rate (requires team stats)
usage_rate = None
if (pd.notna(row.get('team_fg_attempts')) and
    pd.notna(row.get('team_ft_attempts')) and
    pd.notna(row.get('team_turnovers')) and
    minutes_decimal and minutes_decimal > 0):

    player_poss_used = (fg_attempts + (0.44 * ft_attempts) + turnovers)
    team_poss_used = (row['team_fg_attempts'] + (0.44 * row['team_ft_attempts']) + row['team_turnovers'])

    if team_poss_used > 0:
        usage_rate = 100.0 * player_poss_used * 48.0 / (minutes_decimal * team_poss_used)
```

**4. SQL Query Structure Looks Correct ✅**
Lines 620-656:
```python
team_stats AS (
    SELECT
        game_id, team_abbr,
        fg_attempts as team_fg_attempts,
        ft_attempts as team_ft_attempts,
        turnovers as team_turnovers
    FROM `{project_id}.nba_analytics.team_offense_game_summary`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
)

SELECT wp.*, ts.team_fg_attempts, ts.team_ft_attempts, ts.team_turnovers
FROM with_props wp
LEFT JOIN team_stats ts ON wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr
```

**But usage_rate is still NULL! Why?**

## Your Mission

Investigate why the backfill doesn't calculate usage_rate even though:
1. Team stats are available
2. The SQL query should join them
3. The calculation logic exists
4. Manual queries prove the data is joinable

## Investigation Steps

### Step 1: Add Debug Logging

In `player_game_summary_processor.py` around line 1260, add:

```python
# DEBUG: Log what we're getting from the query
logger.info(f"DEBUG usage_rate calc for {player_lookup} on {row.get('game_date')}")
logger.info(f"  team_fg_attempts: {row.get('team_fg_attempts')} (type: {type(row.get('team_fg_attempts'))})")
logger.info(f"  team_ft_attempts: {row.get('team_ft_attempts')}")
logger.info(f"  team_turnovers: {row.get('team_turnovers')}")
logger.info(f"  minutes_decimal: {minutes_decimal}")

if (pd.notna(row.get('team_fg_attempts')) and ...):
    logger.info(f"  ✅ Conditions met - calculating")
else:
    logger.info(f"  ❌ Conditions NOT met - skipping")
    if pd.isna(row.get('team_fg_attempts')):
        logger.info(f"    Missing: team_fg_attempts")
    if pd.isna(row.get('team_ft_attempts')):
        logger.info(f"    Missing: team_ft_attempts")
```

Then re-run backfill for ONE date:
```bash
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --dates 2026-01-22 --no-resume
```

### Step 2: Check What the SQL Query Actually Returns

Add logging to see the actual query results in `extract_data()` (around line 660):

```python
logger.info(f"DEBUG: SQL query executing...")
df = self.bq_client.query(query).to_dataframe()
logger.info(f"DEBUG: Query returned {len(df)} rows")

# Sample first row
if not df.empty:
    sample = df.iloc[0]
    logger.info(f"DEBUG: Sample row columns: {df.columns.tolist()}")
    logger.info(f"DEBUG: Sample team_fg_attempts: {sample.get('team_fg_attempts')}")
```

### Step 3: Test Single Game Reprocess

Create a test script:

```python
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

p = PlayerGameSummaryProcessor()
result = p.reprocess_single_game(
    game_id='20260122_LAL_LAC',
    game_date='2026-01-22',
    season=2025
)

print(f"Records: {len(result) if result else 0}")
if result:
    lebron = [r for r in result if r['player_lookup'] == 'lebronjames']
    if lebron:
        print(f"LeBron usage_rate: {lebron[0].get('usage_rate')}")
```

## Possible Root Causes

### Theory 1: MERGE Not Recalculating
The MERGE operation may be preserving old NULL values instead of recalculating. The processor generates fresh data with usage_rate, but MERGE might only update certain fields.

**Check**: `data_processors/analytics/operations/bigquery_save_ops.py`
Look at the MERGE statement - does it update ALL fields or just some?

### Theory 2: SQL Query Doesn't Actually Join Team Stats
The LEFT JOIN might not be returning team stats due to:
- Partition elimination issues
- Data type mismatches (game_id, team_abbr)
- BigQuery optimization dropping the join

**Test**: Log the actual SQL query string and run it manually in BigQuery console.

### Theory 3: Backfill Mode Skips Calculation
There might be a code path that skips calculation in backfill mode.

**Check**: Search for `backfill_mode` in processor and see if it affects calculation.

## Solution Options

### Option A: Fix MERGE to Recalculate All Fields

If MERGE is the issue, ensure it updates ALL columns:

```python
# In _save_with_proper_merge()
# Make sure the UPDATE SET includes usage_rate
UPDATE SET
    usage_rate = source.usage_rate,  # Add this explicitly
    ... (all other fields)
```

### Option B: Use DELETE+INSERT for Backfill

Change backfill to DELETE old records then INSERT new:

```python
if opts.get('backfill_mode'):
    # Delete existing records first
    delete_query = f"""
    DELETE FROM `{table_id}`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """
    self.bq_client.query(delete_query).result()

    # Then insert fresh records
    self._insert_records(records, table_id)
```

### Option C: Dedicated Usage Rate UPDATE Query

Run a separate UPDATE to recalculate usage_rate:

```sql
UPDATE `nba-props-platform.nba_analytics.player_game_summary` p
SET usage_rate = (
    SELECT
        100.0 * (p.fg_attempts + (0.44 * p.ft_attempts) + p.turnovers) * 48.0 /
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

### Option D: Backfill Team Stats First

Ensure team_offense_game_summary is complete:

```bash
# Run team stats backfill first
python -m backfill_jobs.analytics.team_offense_game_summary.team_offense_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 \
  --parallel --workers 15

# THEN re-run player backfill
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 \
  --parallel --workers 15 --no-resume
```

## Verification Queries

### Query 1: Check Current Usage Rate Coverage
```sql
SELECT game_date,
       COUNT(*) as total_active,
       COUNTIF(usage_rate IS NOT NULL) as has_usage,
       ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2026-01-15' AND '2026-01-25'
  AND minutes_played > 0
GROUP BY game_date
ORDER BY game_date
```

### Query 2: Manual Calculation Test
```sql
SELECT
  p.player_lookup,
  p.minutes_played,
  t.fg_attempts as team_fg,
  -- Manual calculation
  100.0 * (p.fg_attempts + (0.44 * p.ft_attempts) + p.turnovers) * 48.0 /
  (p.minutes_played * (t.fg_attempts + (0.44 * t.ft_attempts) + t.turnovers)) as calculated,
  p.usage_rate as stored
FROM `nba-props-platform.nba_analytics.player_game_summary` p
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
  ON p.game_id = t.game_id AND p.team_abbr = t.team_abbr AND t.game_date = p.game_date
WHERE p.game_date = '2026-01-22'
  AND p.player_lookup IN ('lebronjames', 'stephencurry')
```

## Success Criteria

After your fix, re-run Phase 3 backfill and verify:
- [ ] Jan 22 usage_rate coverage: >80% (currently 0%)
- [ ] LeBron James on Jan 22: usage_rate ~25-30 (currently NULL)
- [ ] Stephen Curry on Jan 22: usage_rate ~30-35 (currently NULL)

## Files to Review

**Main processor:**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
  - Lines 1259-1286: usage_rate calculation
  - Lines 620-656: SQL query with team stats join

**MERGE logic:**
- `data_processors/analytics/operations/bigquery_save_ops.py`

**Backfill script:**
- `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`

## Documentation

Full investigation details:
- `docs/09-handoff/2026-01-27-PHASE3-PARTIAL-SUCCESS.md`
- `docs/09-handoff/2026-01-27-REPROCESSING-FINAL-STATUS.md`

Backfill logs:
- `/home/naji/.claude/projects/-home-naji-code-nba-stats-scraper/a9a1e5a4-2cc3-4c9f-ad30-8fa83f90ee9e/tool-results/toolu_01S8csMNkMM16dpmKAQFjwKM.txt`

## Expected Outcome

After your fix, when we re-run:
```bash
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill \
  --start-date 2026-01-01 --end-date 2026-01-25 \
  --parallel --workers 15 --no-resume
```

We should see:
- Jan 15-23: usage_rate coverage jumps from 0% to 80%+
- All star players have calculated usage_rate values
- Phase 4 can proceed

Good luck! 🚀
