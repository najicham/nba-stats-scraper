#!/bin/bash
# File: bin/raw/validation/validate_br_roster_processor.sh
# Purpose: Validate Basketball Reference roster processor data quality in BigQuery
# Usage: ./bin/raw/validation/validate_br_roster_processor.sh [--season YEAR] [--team ABBREV]

set -euo pipefail

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}

# Parse arguments
SEASON_FILTER=""
TEAM_FILTER=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --season)
            SEASON_FILTER="$2"
            shift 2
            ;;
        --team)
            TEAM_FILTER="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--season YEAR] [--team ABBREV]"
            echo ""
            echo "Options:"
            echo "  --season YEAR    Filter by season year (e.g., 2025)"
            echo "  --team ABBREV    Filter by team abbreviation (e.g., LAL)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "Basketball Reference Roster Processor Validation"
echo "========================================"
echo ""

echo "1. Data Coverage by Season:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
  season_year,
  COUNT(DISTINCT team_abbrev) as teams,
  COUNT(*) as total_players,
  COUNT(DISTINCT player_full_name) as unique_players,
  ROUND(AVG(experience_years), 1) as avg_experience
FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
${SEASON_FILTER:+WHERE season_year = $SEASON_FILTER}
GROUP BY season_year
ORDER BY season_year DESC;
SQL

echo ""
echo "2. Team Coverage (Current Season):"
bq query --use_legacy_sql=false --format=pretty <<SQL
WITH current_season AS (
  SELECT MAX(season_year) as season
  FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
)
SELECT
  team_abbrev,
  COUNT(*) as roster_size,
  COUNT(DISTINCT position) as positions_covered,
  MAX(updated_at) as last_update
FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`, current_season
WHERE season_year = current_season.season
  ${TEAM_FILTER:+AND team_abbrev = '$TEAM_FILTER'}
GROUP BY team_abbrev
ORDER BY team_abbrev;
SQL

echo ""
echo "3. Data Quality Issues:"
bq query --use_legacy_sql=false --format=pretty <<SQL
WITH quality_checks AS (
  SELECT
    'Missing player names' as check_type,
    COUNT(*) as issue_count
  FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
  WHERE player_full_name IS NULL OR player_full_name = ''

  UNION ALL

  SELECT
    'Missing positions',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
  WHERE position IS NULL OR position = ''

  UNION ALL

  SELECT
    'Invalid jersey numbers',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
  WHERE jersey_number IS NOT NULL AND (jersey_number < 0 OR jersey_number > 99)

  UNION ALL

  SELECT
    'Missing birth dates',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
  WHERE birth_date IS NULL

  UNION ALL

  SELECT
    'Missing height/weight',
    COUNT(*)
  FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
  WHERE height IS NULL OR weight IS NULL
)
SELECT * FROM quality_checks WHERE issue_count > 0;
SQL

echo ""
echo "4. Position Distribution:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
  position,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
WHERE season_year = (SELECT MAX(season_year) FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`)
GROUP BY position
ORDER BY count DESC;
SQL

echo ""
echo "5. Recent Processing Activity:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
  DATE(processed_at) as process_date,
  COUNT(DISTINCT team_abbrev) as teams_updated,
  COUNT(*) as records_updated,
  MAX(processed_at) as last_update
FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
GROUP BY process_date
ORDER BY process_date DESC;
SQL

echo ""
echo "6. GCS Source Files Check:"
echo "Checking GCS for roster JSON files..."
BUCKET="gs://nba-scraped-data"
GCS_PATH="basketball-reference/rosters"

# Count files in GCS
file_count=$(gcloud storage ls -r "${BUCKET}/${GCS_PATH}/**/*.json" 2>/dev/null | wc -l || echo "0")
echo "  Total roster JSON files in GCS: $file_count"

# Show recent files
echo "  Recent files:"
gcloud storage ls -l "${BUCKET}/${GCS_PATH}/" 2>/dev/null | head -10 || echo "  No files found or path doesn't exist"

echo ""
echo "========================================"
echo "Validation Complete"
echo "========================================"
