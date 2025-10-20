#!/bin/bash
# ============================================================================
# FILE: scripts/espn_validation_bq_commands.sh
# ============================================================================
# Quick reference of all BQ commands for ESPN boxscore validation
# ============================================================================

# ============================================================================
# VERIFICATION COMMANDS (Before Deletion)
# ============================================================================

# Check what ESPN data exists
bq query --use_legacy_sql=false "
SELECT
  game_date,
  game_id,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup,
  COUNT(*) as player_count,
  STRING_AGG(DISTINCT team_abbr ORDER BY team_abbr) as teams
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
GROUP BY game_date, game_id, away_team_abbr, home_team_abbr
"

# Verify which teams' players are in ESPN data
bq query --use_legacy_sql=false "
SELECT 
  team_abbr,
  COUNT(*) as player_count,
  STRING_AGG(player_full_name ORDER BY points DESC LIMIT 3) as top_players
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
GROUP BY team_abbr
ORDER BY team_abbr
"

# Check if game exists in schedule
bq query --use_legacy_sql=false "
SELECT
  CASE 
    WHEN COUNT(*) > 0 THEN '✅ HOU @ PHI in schedule'
    ELSE '🔴 HOU @ PHI NOT in schedule'
  END as schedule_status,
  MAX(game_id) as schedule_game_id
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '2025-01-15'
  AND home_team_tricode = 'PHI'
  AND away_team_tricode = 'HOU'
"

# Check what PHI games actually happened
bq query --use_legacy_sql=false "
SELECT
  game_id,
  CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup,
  game_status_text
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '2025-01-15'
  AND (home_team_tricode = 'PHI' OR away_team_tricode = 'PHI')
"

# ============================================================================
# DELETION COMMAND (Execute after verification)
# ============================================================================

# DELETE phantom game
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
  AND game_id = '20250115_HOU_PHI'
"

# ============================================================================
# POST-DELETION VERIFICATION
# ============================================================================

# Verify deletion was successful
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as remaining_espn_games,
  CASE 
    WHEN COUNT(*) = 0 THEN '✅ Phantom game successfully deleted'
    ELSE '🔴 ERROR: Records still exist'
  END as status
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
  AND game_id = '20250115_HOU_PHI'
"

# Check total ESPN data after deletion
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_id) as total_espn_games,
  COUNT(*) as total_player_records,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
"

# Re-run cross-validation
bq query --use_legacy_sql=false "
WITH espn_games AS (
  SELECT DISTINCT game_id FROM \`nba-props-platform.nba_raw.espn_boxscores\`
),
bdl_games AS (
  SELECT DISTINCT game_id FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
  WHERE game_date >= '2020-01-01'
)
SELECT
  'ESPN Only' as source,
  COUNT(*) as game_count,
  CASE 
    WHEN COUNT(*) = 0 THEN '✅ No phantom games'
    ELSE '⚠️ ESPN has games BDL does not'
  END as status
FROM espn_games e
LEFT JOIN bdl_games b ON e.game_id = b.game_id
WHERE b.game_id IS NULL

UNION ALL

SELECT
  'BDL Only' as source,
  COUNT(*) as game_count,
  '⚪ Normal (BDL is primary)' as status
FROM bdl_games b
LEFT JOIN espn_games e ON b.game_id = e.game_id
WHERE e.game_id IS NULL

UNION ALL

SELECT
  'Both Sources' as source,
  COUNT(*) as game_count,
  CASE 
    WHEN COUNT(*) > 0 THEN '✅ Can validate'
    ELSE '⚪ No overlap'
  END as status
FROM espn_games e
INNER JOIN bdl_games b ON e.game_id = b.game_id
"

# ============================================================================
# MONITORING COMMANDS (Ongoing)
# ============================================================================

# Daily check: Any new ESPN data?
bq query --use_legacy_sql=false "
SELECT 
  game_date,
  COUNT(DISTINCT game_id) as games,
  STRING_AGG(CONCAT(away_team_abbr, '@', home_team_abbr), ', ') as matchups
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
"

# Check for ESP-only games (should be 0)
bq query --use_legacy_sql=false "
WITH espn_only AS (
  SELECT 
    e.game_date,
    e.game_id,
    CONCAT(e.away_team_abbr, ' @ ', e.home_team_abbr) as matchup
  FROM (SELECT DISTINCT game_date, game_id, away_team_abbr, home_team_abbr 
        FROM \`nba-props-platform.nba_raw.espn_boxscores\`) e
  LEFT JOIN (SELECT DISTINCT game_id FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
             WHERE game_date >= '2020-01-01') b
    ON e.game_id = b.game_id
  WHERE b.game_id IS NULL
)
SELECT
  CASE 
    WHEN COUNT(*) = 0 THEN '✅ No phantom games detected'
    ELSE CONCAT('⚠️ ', CAST(COUNT(*) AS STRING), ' potential phantom games')
  END as alert,
  STRING_AGG(CONCAT(CAST(game_date AS STRING), ': ', matchup), ', ') as details
FROM espn_only
"
