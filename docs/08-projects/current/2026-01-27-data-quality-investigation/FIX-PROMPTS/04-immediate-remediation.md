# Sonnet Fix Task: Immediate Data Remediation

## Objective
Fix existing data issues WITHOUT code changes. This can run in parallel with code fixes.

## Issues to Remediate

1. **Jan 27 predictions**: 0 predictions exist, games happening today
2. **Jan 26 usage_rate**: Only 29% coverage
3. **Jan 8 & 13 duplicates**: 93 duplicate records total
4. **Jan 24-25 incomplete analytics**: 66-88% coverage

## Priority Order

### P0: Generate Predictions for Jan 27 (URGENT - games today)

**Step 1**: Verify betting lines exist
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_lookup) as players_with_lines
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = '2026-01-27'"
```
Expected: 40+ players

**Step 2**: Re-run upcoming_player_game_context processor
```bash
# Option A: Trigger via Cloud Run (preferred)
curl -X POST "https://nba-analytics-processors-xxx.run.app/process" \
  -H "Content-Type: application/json" \
  -d '{
    "output_table": "odds_api_player_points_props",
    "game_date": "2026-01-27",
    "force_reprocess": true
  }'

# Option B: Run locally
cd /home/naji/code/nba-stats-scraper
python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor \
    --start-date 2026-01-27 --end-date 2026-01-27
```

**Step 3**: Verify has_prop_line is now TRUE
```bash
bq query --use_legacy_sql=false "
SELECT COUNTIF(has_prop_line = TRUE) as with_lines, COUNT(*) as total
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-27'"
```
Expected: 40+ with_lines

**Step 4**: Trigger prediction coordinator
```bash
# Find the prediction coordinator endpoint/trigger
# Option A: HTTP trigger
curl -X POST "https://prediction-coordinator-xxx.run.app/start" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-27"}'

# Option B: Pub/Sub trigger
gcloud pubsub topics publish nba-phase4-trigger \
  --message='{"game_date": "2026-01-27", "action": "generate_predictions"}'
```

**Step 5**: Verify predictions generated
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27' AND is_active = TRUE"
```
Expected: 80-150 predictions, 30-50 players

---

### P1: Fix Jan 26 Usage Rate

**Step 1**: Verify team stats exist
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as team_records
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date = '2026-01-26'"
```
Expected: 14 records (7 games × 2 teams)

**Step 2**: If team stats missing, run team processor first
```bash
python -m data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor \
    --start-date 2026-01-26 --end-date 2026-01-26
```

**Step 3**: Re-run player_game_summary processor
```bash
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
    --start-date 2026-01-26 --end-date 2026-01-26
```

**Step 4**: Verify usage_rate improved
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) as valid,
  COUNTIF(usage_rate > 50) as invalid,
  COUNTIF(usage_rate IS NULL) as null_usage,
  COUNT(*) as total
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-26'"
```
Expected: valid > 180, null_usage < 50

---

### P2: Clean Up Duplicates (Jan 8, 13)

**Step 1**: Count duplicates
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup,'_',game_id)) as dupes
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date IN ('2026-01-08', '2026-01-13')
GROUP BY game_date"
```

**Step 2**: Execute deduplication (CAREFUL - this rewrites the table)
```bash
bq query --use_legacy_sql=false "
CREATE OR REPLACE TABLE \`nba-props-platform.nba_analytics.player_game_summary\` AS
SELECT * EXCEPT(rn) FROM (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY game_id, player_lookup
            ORDER BY processed_at DESC
        ) as rn
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
) WHERE rn = 1"
```

**Step 3**: Verify no duplicates remain
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup,'_',game_id)) as dupes
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2026-01-01'
GROUP BY game_date
HAVING dupes > 0"
```
Expected: Empty result

---

### P2: Reprocess Incomplete Dates (Jan 24-25)

**Step 1**: Run team stats first
```bash
python -m data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor \
    --start-date 2026-01-24 --end-date 2026-01-25
```

**Step 2**: Run player stats
```bash
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
    --start-date 2026-01-24 --end-date 2026-01-25
```

**Step 3**: Verify coverage improved
```bash
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNT(*) as total,
  COUNTIF(usage_rate IS NOT NULL) as has_usage,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2026-01-24' AND '2026-01-26'
GROUP BY game_date
ORDER BY game_date"
```
Expected: usage_pct > 55% for all dates

---

## Execution Checklist

- [ ] P0: Jan 27 predictions generated (verify before games start)
- [ ] P1: Jan 26 usage_rate fixed (valid > 180)
- [ ] P2: Duplicates cleaned (0 duplicates remain)
- [ ] P2: Jan 24-25 reprocessed (usage_pct > 55%)

## Validation Summary Query
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) as valid_usage,
  COUNTIF(usage_rate > 50) as invalid_usage,
  COUNTIF(usage_rate IS NULL) as null_usage,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup,'_',game_id)) as duplicates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2026-01-24'
GROUP BY game_date
ORDER BY game_date DESC"
```

After all fixes:
- valid_usage should be > 50% of total
- invalid_usage should be 0-5
- null_usage should be < 50% of total
- duplicates should be 0
