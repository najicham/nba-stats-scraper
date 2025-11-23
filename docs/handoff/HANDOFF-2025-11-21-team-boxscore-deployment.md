# Handoff: Deploy Team Boxscore Stack

**Created**: 2025-11-21 15:10 PST
**Status**: Ready for deployment
**Priority**: Medium (blocks 2 Phase 3 processors)
**Estimated Time**: 1-2 hours

---

## Quick Summary

The NBA.com team boxscore processor is **fully implemented** but never deployed. All code exists and is ready - just needs table creation, scraper deployment, and testing.

---

## Current Status

### ✅ What Exists
- **Scraper**: `scrapers/nbacom/nbac_team_boxscore.py`
- **Processor**: `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
  - Smart idempotency implemented ✅
  - Modified: Nov 21 13:02 (today)
  - Uses HASH_FIELDS for selective hashing
  - Processing strategy: MERGE_UPDATE
- **Schema**: `schemas/bigquery/raw/nbac_team_boxscore_tables.sql`
  - Has `data_hash` column ✅
  - Version 2.0 with `is_home` boolean
  - Comprehensive validation queries included

### ❌ What's Missing
- Table not created in BigQuery
- No data in GCS (scraper never ran)
- Scraper not deployed to Cloud Run

### ⚠️ What's Blocked
Two Phase 3 processors need this data:
- `team_offense_game_summary` (Phase 3)
- `team_defense_game_summary` (Phase 3)

---

## Deployment Steps

### Step 1: Create BigQuery Table (5 min)

```bash
# Deploy schema
bq query --use_legacy_sql=false < schemas/bigquery/raw/nbac_team_boxscore_tables.sql

# Verify table created
bq show nba_raw.nbac_team_boxscore

# Expected output: Table details with columns game_id, team_abbr, is_home, etc.
```

**Verification**:
```bash
# Should show table schema
bq show --schema nba_raw.nbac_team_boxscore | grep data_hash
```

### Step 2: Deploy Scraper (15-20 min)

**Option A: Check if scraper already deployed**
```bash
gcloud run services list | grep -i team

# If exists, check logs to see if it's running
```

**Option B: Deploy new scraper**
```bash
# Navigate to scraper directory
cd scrapers/nbacom/

# Check scraper file exists
ls -lh nbac_team_boxscore.py

# Deploy to Cloud Run (adjust as needed for your deployment process)
# This depends on how your other scrapers are deployed
# Check existing scraper deployment scripts for reference
```

**Questions to answer**:
1. Is there a deployment script for nbacom scrapers?
2. Should this be triggered by Cloud Scheduler like other scrapers?
3. What's the expected scraping frequency? (Daily? Real-time?)

### Step 3: Test Scraper (10 min)

```bash
# Wait for scraper to run (or trigger manually)

# Check if data landed in GCS
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/

# Expected: JSON files for recent games
```

### Step 4: Test Processor (15 min)

```bash
# Run processor manually for recent date
python data_processors/raw/nbacom/nbac_team_boxscore_processor.py \
  --start-date 2024-11-20 \
  --end-date 2024-11-20

# Or use Python directly
python -c "
from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor
p = NbacTeamBoxscoreProcessor()
p.run({'start_date': '2024-11-20', 'end_date': '2024-11-20'})
"
```

**Expected output**:
```
INFO - Computing data hash for X rows
INFO - Data hash: a3f5c2... (new data)
INFO - Writing X rows to nba_raw.nbac_team_boxscore
INFO - Successfully wrote X rows
```

### Step 5: Verify Data in BigQuery (5 min)

```sql
-- Check data exists
SELECT COUNT(*) as row_count, COUNT(DISTINCT game_id) as game_count
FROM nba_raw.nbac_team_boxscore
WHERE game_date >= '2024-11-01';

-- Expected: 2 rows per game (one per team)

-- Verify smart idempotency fields
SELECT
  game_id,
  team_abbr,
  is_home,
  data_hash,
  processed_at
FROM nba_raw.nbac_team_boxscore
WHERE game_date >= '2024-11-01'
LIMIT 10;

-- Expected: data_hash should be populated
```

### Step 6: Run Data Quality Checks (10 min)

The schema includes comprehensive validation queries. Run these:

```sql
-- Check 1: Verify all games have exactly 2 teams
SELECT game_id, game_date, COUNT(*) as team_count
FROM nba_raw.nbac_team_boxscore
WHERE game_date >= '2024-11-01'
GROUP BY game_id, game_date
HAVING COUNT(*) != 2;
-- Expected: No rows (all games have 2 teams)

-- Check 2: Verify each game has exactly 1 home and 1 away team
SELECT game_id, game_date,
       SUM(CASE WHEN is_home THEN 1 ELSE 0 END) as home_count,
       SUM(CASE WHEN NOT is_home THEN 1 ELSE 0 END) as away_count
FROM nba_raw.nbac_team_boxscore
WHERE game_date >= '2024-11-01'
GROUP BY game_id, game_date
HAVING home_count != 1 OR away_count != 1;
-- Expected: No rows (each game has 1 home, 1 away)

-- Check 3: Verify points calculation
SELECT game_id, game_date, team_abbr, is_home, points,
       ((fg_made - three_pt_made) * 2) + (three_pt_made * 3) + ft_made as calculated_points
FROM nba_raw.nbac_team_boxscore
WHERE points != ((fg_made - three_pt_made) * 2) + (three_pt_made * 3) + ft_made
  AND game_date >= '2024-11-01';
-- Expected: No rows (points math correct)
```

See schema file (lines 209-279) for complete list of validation queries.

### Step 7: Test Smart Idempotency (5 min)

```bash
# Run processor twice with same date
python -c "
from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor
p = NbacTeamBoxscoreProcessor()

# Run 1
print('=== First Run ===')
p.run({'start_date': '2024-11-20', 'end_date': '2024-11-20'})

# Run 2 (should skip write if data unchanged)
print('=== Second Run ===')
p.run({'start_date': '2024-11-20', 'end_date': '2024-11-20'})
"
```

**Expected output (Run 2)**:
```
Data hash unchanged, skipping write
```

### Step 8: Unblock Phase 3 Processors (5 min)

Once data exists, test the blocked Phase 3 processors:

```bash
# Test team offense processor
python -c "
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
p = TeamOffenseGameSummaryProcessor()
p.set_opts({'project_id': 'nba-props-platform'})
p.init_clients()
p.run({'start_date': '2024-11-20', 'end_date': '2024-11-20'})
"

# Test team defense processor
python -c "
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
p = TeamDefenseGameSummaryProcessor()
p.set_opts({'project_id': 'nba-props-platform'})
p.init_clients()
p.run({'start_date': '2024-11-20', 'end_date': '2024-11-20'})
"
```

**Expected**: Both should succeed (dependencies now met)

---

## Processor Details

### Key Configuration

```python
class NbacTeamBoxscoreProcessor(SmartIdempotencyMixin, ProcessorBase):
    """v2.0 with smart idempotency."""

    # Smart idempotency fields
    HASH_FIELDS = [
        'game_id', 'team_abbr', 'is_home',
        'fg_made', 'fg_attempted',
        'three_pt_made', 'three_pt_attempted',
        'ft_made', 'ft_attempted',
        'offensive_rebounds', 'defensive_rebounds', 'total_rebounds',
        'assists', 'steals', 'blocks', 'turnovers',
        'personal_fouls', 'points', 'plus_minus'
    ]

    # Table and strategy
    table_name = 'nba_raw.nbac_team_boxscore'
    processing_strategy = 'MERGE_UPDATE'
```

### Data Format

**Input**: GCS JSON files at `gs://nba-scraped-data/nba-com/team-boxscore/`

**Output**: 2 rows per game (one per team)
```json
{
  "game_id": "20241120_LAL_PHI",
  "nba_game_id": "0022400089",
  "team_abbr": "LAL",
  "is_home": false,
  "points": 106,
  "fg_made": 40,
  "assists": 25,
  "data_hash": "a3f5c2...",
  ...
}
```

---

## Troubleshooting

### Issue: "Scraper not found in Cloud Run"

**Cause**: Scraper never deployed

**Options**:
1. Check if there's a batch deployment script for nbacom scrapers
2. Deploy manually using gcloud run deploy
3. Ask about scraper deployment process

### Issue: "No data in GCS"

**Cause**: Scraper hasn't run yet

**Options**:
1. Trigger scraper manually (if possible)
2. Wait for scheduled run
3. Check scraper logs for errors

### Issue: "Table already exists" error

**Cause**: Table was created previously

**Fix**: Check if table exists, skip creation
```bash
bq show nba_raw.nbac_team_boxscore
```

### Issue: "Processor fails with missing columns"

**Cause**: Schema mismatch

**Fix**: Drop and recreate table
```bash
bq rm -f nba_raw.nbac_team_boxscore
bq query --use_legacy_sql=false < schemas/bigquery/raw/nbac_team_boxscore_tables.sql
```

---

## Success Criteria

- [ ] Table exists in BigQuery with correct schema
- [ ] Table has `data_hash` column (smart idempotency)
- [ ] Scraper deployed and running
- [ ] Data exists in GCS
- [ ] Processor successfully processes data
- [ ] Smart idempotency working (second run skips write)
- [ ] Data quality checks pass (2 teams per game, correct math)
- [ ] Phase 3 team processors unblocked

---

## Related Documentation

- **Processor code**: `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
- **Schema**: `schemas/bigquery/raw/nbac_team_boxscore_tables.sql`
- **Smart idempotency guide**: `docs/guides/processor-patterns/01-smart-idempotency.md`
- **Implementation plan**: `docs/implementation/IMPLEMENTATION_PLAN.md` (line 100-105)

---

## Questions for User

Before starting deployment, clarify:

1. **Scraper deployment**: How are nbacom scrapers typically deployed? Is there a deployment script?
2. **Scheduling**: Should this scraper run daily? Real-time? Manual only?
3. **Historical data**: Should we backfill historical team boxscore data? How far back?
4. **Priority**: Is this blocking anything critical, or can it wait?

---

## Notes

- Processor modified today (Nov 21 13:02) - already has latest patterns
- Schema is version 2.0 with `is_home` boolean for home/away distinction
- Smart idempotency already implemented (no changes needed)
- Comprehensive validation queries in schema file (lines 209-279)

---

**Estimated Total Time**: 1-2 hours (including testing and validation)

**Difficulty**: Low (all code exists, just deployment)

**Blocker Impact**: Medium (blocks 2 of 5 Phase 3 processors)

---

**Ready to deploy!** All code is production-ready with smart idempotency pattern already implemented.
