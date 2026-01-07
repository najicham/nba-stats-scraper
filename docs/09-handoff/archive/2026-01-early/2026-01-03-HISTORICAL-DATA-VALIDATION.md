# Historical Data Validation - 4 Seasons Backfill Check

**Date**: 2026-01-03
**Priority**: HIGH
**Estimated Time**: 2-4 hours
**Objective**: Verify all 4 seasons of historical data are properly backfilled across all pipeline phases

---

## 🎯 Mission

Validate that the past 4 NBA seasons have complete data coverage across all pipeline phases (Phase 1 through Phase 6):

**Seasons to Check:**
- 2024-25 (current season)
- 2023-24
- 2022-23
- 2021-22

**Phases to Validate:**
1. Phase 1: Raw scrapers (GCS files)
2. Phase 2: Raw processors (BigQuery raw tables)
3. Phase 3: Analytics processors (BigQuery analytics tables)
4. Phase 4: Precompute processors (BigQuery precompute tables)
5. Phase 5: Predictions
6. Phase 6: Final exports

---

## 📊 Phase 1: Raw Scrapers (GCS Validation)

**Goal**: Verify all game files exist in GCS for each season

### Key Data Sources to Check:

1. **NBA.com Gamebooks** (critical)
   ```bash
   # Check file counts by season
   for season in 2021-22 2022-23 2023-24 2024-25; do
     echo "=== Season $season ==="
     gsutil ls -r "gs://nba-scraped-data/nba-com/gamebooks-data/" | \
       grep -c "$season"
   done
   ```

2. **Ball Don't Lie Box Scores**
   ```bash
   # Check by date ranges
   # 2021-22: Oct 2021 - June 2022
   # 2022-23: Oct 2022 - June 2023
   # 2023-24: Oct 2023 - June 2024
   # 2024-25: Oct 2024 - present

   gsutil ls "gs://nba-scraped-data/ball-dont-lie/boxscores/" | wc -l
   gsutil ls "gs://nba-scraped-data/ball-dont-lie/player-box-scores/" | wc -l
   ```

3. **Odds API Data**
   ```bash
   gsutil ls "gs://nba-scraped-data/odds-api/player-props/" | wc -l
   gsutil ls "gs://nba-scraped-data/odds-api/game-lines/" | wc -l
   ```

**Expected Volumes:**
- NBA.com gamebooks: ~82 games × 30 teams = ~2,460 games per season
- Actual: ~1,230 game files per season (each game has 1 file)

---

## 📊 Phase 2: Raw Processors (BigQuery Raw Tables)

**Goal**: Verify all raw data loaded into BigQuery

### Query Template:

```sql
-- Game counts by season for gamebook data
SELECT
  season,
  COUNT(DISTINCT game_code) as total_games,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
GROUP BY season
ORDER BY season;
```

**Expected Results:**
- Each season should have ~1,230 games
- 2021-22: Oct 2021 - Apr 2022 (regular) + Apr-June 2022 (playoffs)
- 2022-23: Oct 2022 - Apr 2023 (regular) + Apr-June 2023 (playoffs)
- 2023-24: Oct 2023 - Apr 2024 (regular) + Apr-June 2024 (playoffs)
- 2024-25: Oct 2024 - present (ongoing)

### Key Raw Tables to Check:

1. **NBA.com Gamebook Tables**
   ```sql
   -- nbac_gamebook_player_stats
   SELECT season, COUNT(*) as rows
   FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
   WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
   GROUP BY season;
   -- Expected: ~40,000 rows per season (1,230 games × 32 players avg)

   -- nbac_gamebook_team_stats
   SELECT season, COUNT(*) as rows
   FROM `nba-props-platform.nba_raw.nbac_gamebook_team_stats`
   WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
   GROUP BY season;
   -- Expected: ~2,460 rows per season (1,230 games × 2 teams)
   ```

2. **Ball Don't Lie Tables**
   ```sql
   -- bdl_player_boxscores
   SELECT
     EXTRACT(YEAR FROM game_date) as year,
     COUNT(DISTINCT game_id) as games,
     COUNT(*) as player_rows
   FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
   WHERE game_date >= '2021-10-01'
   GROUP BY year
   ORDER BY year;
   ```

3. **Odds API Tables**
   ```sql
   -- odds_api_player_points_props
   SELECT
     EXTRACT(YEAR FROM game_date) as year,
     COUNT(DISTINCT game_id) as games,
     COUNT(*) as prop_rows
   FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
   WHERE game_date >= '2021-10-01'
   GROUP BY year
   ORDER BY year;
   ```

---

## 📊 Phase 3: Analytics Processors

**Goal**: Verify analytics tables populated from raw data

### Key Analytics Tables:

1. **Player Performance Analytics**
   ```sql
   SELECT
     season,
     COUNT(DISTINCT player_id) as unique_players,
     COUNT(*) as total_records
   FROM `nba-props-platform.nba_analytics.player_game_stats`
   WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
   GROUP BY season
   ORDER BY season;
   -- Expected: 400-500 unique players per season
   ```

2. **Team Analytics**
   ```sql
   SELECT
     season,
     COUNT(DISTINCT team_id) as teams,
     COUNT(*) as team_games
   FROM `nba-props-platform.nba_analytics.team_game_stats`
   WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
   GROUP BY season
   ORDER BY season;
   -- Expected: 30 teams, ~2,460 team-games per season
   ```

---

## 📊 Phase 4: Precompute Processors

**Goal**: Verify precomputed features exist for predictions

### Key Precompute Tables:

1. **Player Rolling Averages**
   ```sql
   SELECT
     season,
     COUNT(DISTINCT player_id) as players,
     COUNT(*) as records
   FROM `nba-props-platform.nba_precompute.player_rolling_stats`
   WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
   GROUP BY season
   ORDER BY season;
   ```

2. **Matchup Features**
   ```sql
   SELECT
     season,
     COUNT(*) as matchup_records
   FROM `nba-props-platform.nba_precompute.player_matchup_features`
   WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
   GROUP BY season
   ORDER BY season;
   ```

---

## 📊 Phase 5: Predictions

**Goal**: Verify predictions exist for historical games

### Predictions Check:

```sql
-- Check prediction coverage by season
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_id) as games_with_predictions,
  COUNT(*) as total_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2021-10-01'
GROUP BY year
ORDER BY year;
```

**Note**: Historical predictions may not exist for all games if prediction system was deployed mid-season. Focus on:
- Are predictions running for current season? ✅
- Are there predictions for recent seasons (2023-24, 2024-25)? ✅

---

## 📊 Phase 6: Exports

**Goal**: Verify final exports are complete

### Firestore Exports:

```bash
# Check if Firestore has current season data
# This requires Firestore access or checking export logs

gcloud logging read 'resource.labels.service_name="phase6-export"
  AND textPayload=~"Exported"' \
  --limit=100 \
  --freshness=7d
```

---

## 🔍 Gap Identification Process

### Step 1: Find Missing Games

```sql
-- Cross-reference schedule with actual data
WITH expected AS (
  SELECT
    season,
    game_date,
    game_code,
    CONCAT(away_team_tricode, '@', home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
    AND game_status_text NOT IN ('PPD', 'Canceled')
),
actual AS (
  SELECT DISTINCT
    season,
    REPLACE(game_code, '/', '') as game_code
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE season IN ('2021-22', '2022-23', '2023-24', '2024-25')
)
SELECT
  e.season,
  e.game_date,
  e.game_code,
  e.matchup,
  CASE
    WHEN a.game_code IS NOT NULL THEN 'PRESENT'
    ELSE 'MISSING'
  END as status
FROM expected e
LEFT JOIN actual a
  ON REPLACE(e.game_code, '/', '') = a.game_code
  AND e.season = a.season
WHERE a.game_code IS NULL  -- Only show missing
ORDER BY e.season, e.game_date;
```

### Step 2: Check If Files Exist in GCS

For each missing game, check if raw file exists:

```bash
# Example for a missing game
SEASON="2023-24"
GAME_CODE="20231015-LALBOS"

gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-data/*/${GAME_CODE}/*.json"
```

### Step 3: Categorize Gaps

**Category A: File exists in GCS, missing from BigQuery**
- ✅ Can backfill easily
- Use the same process as tonight's gamebook backfill
- Process the Pub/Sub message manually

**Category B: File missing from GCS**
- ⚠️ Need to re-scrape
- Check if game actually occurred (not postponed/canceled)
- May need to trigger historical scraper

**Category C: Game postponed/canceled**
- ✅ Expected gap
- Update schedule table if needed
- No action required

---

## 🔧 Backfill Procedures

### If Gaps Found in Phase 2 (Raw Data):

**Use the gamebook backfill script from tonight:**

```python
# Modify /tmp/backfill_games.py to process historical games
# Change file paths to match the missing games

python3 /tmp/backfill_games.py
```

**Or manual processing:**

```bash
# Get auth token
TOKEN=$(gcloud auth print-identity-token)

# Process single game
python3 -c "
import json, base64, requests

payload = {'bucket': 'nba-scraped-data', 'name': 'FILE_PATH_HERE'}
encoded = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
envelope = {'message': {'data': encoded}}

response = requests.post(
    'https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process',
    headers={'Authorization': f'Bearer $TOKEN', 'Content-Type': 'application/json'},
    json=envelope,
    timeout=300
)
print(response.text)
"
```

### If Gaps Found in Phase 3/4/5:

**Trigger orchestration for date range:**

```bash
# Example: Trigger Phase 3 for missing dates
curl -X POST "https://phase3-analytics-processors-URL/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2023-10-15",
    "end_date": "2023-10-20"
  }'
```

---

## 📋 Validation Checklist

**Phase 1: GCS Files**
- [ ] NBA.com gamebooks: ~1,230 game files per season ✅
- [ ] Ball Don't Lie boxscores: Present for all game dates ✅
- [ ] Odds API data: Present for 2023-24, 2024-25 (may not exist for earlier seasons) ✅

**Phase 2: Raw BigQuery Tables**
- [ ] nbac_gamebook_player_stats: ~40k rows per season ✅
- [ ] nbac_gamebook_team_stats: ~2,460 rows per season ✅
- [ ] bdl_player_boxscores: Present for all seasons ✅
- [ ] odds_api tables: Present for recent seasons ✅

**Phase 3: Analytics Tables**
- [ ] player_game_stats: 400-500 players per season ✅
- [ ] team_game_stats: 30 teams, ~2,460 games per season ✅

**Phase 4: Precompute Tables**
- [ ] player_rolling_stats: Features computed for all games ✅
- [ ] matchup_features: Present for all matchups ✅

**Phase 5: Predictions**
- [ ] Predictions exist for current season ✅
- [ ] Predictions exist for recent historical games ✅

**Phase 6: Exports**
- [ ] Firestore exports running regularly ✅
- [ ] Export logs show recent activity ✅

---

## 📊 Expected Volumes Reference

**Per Season (Regular + Playoffs):**
- Total games: ~1,230 (1,230 regular + playoffs)
- Player game records: ~40,000 (1,230 games × 32 players avg)
- Team game records: ~2,460 (1,230 games × 2 teams)
- Unique players: ~400-500
- Teams: 30

**Across 4 Seasons:**
- Total games: ~4,920
- Player records: ~160,000
- Team records: ~9,840

---

## 🎯 Success Criteria

**Green Light (No Action Needed):**
- All seasons have >95% game coverage
- Missing games are PPD/Canceled only
- All phases have data for covered games
- Current season (2024-25) is 100% up to date

**Yellow Light (Minor Gaps):**
- <5% of games missing per season
- Files exist in GCS for missing games
- Can backfill easily with existing scripts

**Red Light (Major Issues):**
- >5% of games missing in any season
- Large date ranges with no data
- Files missing from GCS (need re-scraping)
- Pipeline phases out of sync

---

## 🚀 Prioritization

**Priority 1: Current Season (2024-25)**
- Must be 100% complete and up to date
- Any gaps block real-time predictions

**Priority 2: Last Season (2023-24)**
- Important for model training
- Should be complete for all phases

**Priority 3: 2022-23, 2021-22**
- Historical data for model improvement
- Less critical if mostly complete

---

## 📝 Output Format

Create a summary report:

```markdown
# Historical Data Validation Report - 2026-01-03

## Summary
- Seasons checked: 4 (2021-22 through 2024-25)
- Total expected games: ~4,920
- Total actual games: X,XXX
- Completeness: XX%

## Phase 1: GCS Files
- Season 2024-25: XXX/XXX games (XX%)
- Season 2023-24: XXX/XXX games (XX%)
- Season 2022-23: XXX/XXX games (XX%)
- Season 2021-22: XXX/XXX games (XX%)

## Phase 2: Raw BigQuery
[Similar breakdown]

## Identified Gaps
- Total missing games: XX
- Category A (can backfill): XX games
- Category B (need re-scrape): XX games
- Category C (expected/canceled): XX games

## Recommended Actions
1. [Action items in priority order]
2. [Estimated time for each]

## Status
✅ GREEN / ⚠️ YELLOW / 🚨 RED
```

---

## 🔧 Troubleshooting

**If queries timeout:**
- Add date range filters to limit scope
- Query one season at a time
- Use COUNT(*) instead of SELECT *

**If game counts seem low:**
- Check for data partitioning (some tables partition by date)
- Verify season format matches ('2023-24' vs '2023-2024')
- Check if playoffs included

**If can't access certain tables:**
- Verify BigQuery permissions
- Check if table exists: `bq ls nba-props-platform:nba_raw`
- Some tables may not exist for all seasons

---

## ⏱️ Time Estimates

- **GCS validation**: 30 min
- **Phase 2 validation**: 30 min
- **Phase 3-5 validation**: 45 min
- **Gap analysis**: 30 min
- **Backfill (if needed)**: 1-3 hours depending on gaps
- **Documentation**: 15 min

**Total**: 2-4 hours

---

**Start this in a NEW chat session to avoid context overflow.**

**Use this handoff doc**: `docs/09-handoff/2026-01-03-HISTORICAL-DATA-VALIDATION.md`

🎯 **The goal is to ensure we have complete historical data for model training and predictions!**
