#!/bin/bash
# Find data gaps and optionally trigger recovery
# Checks BigQuery for missing data and can create recovery messages

set -euo pipefail

# Default parameters
DAYS_TO_CHECK=${1:-7}
SCRAPER_TYPE=${2:-"bdl_injuries"}

echo "=================================="
echo "Data Coverage Gap Detection"
echo "=================================="
echo ""
echo "Checking last $DAYS_TO_CHECK days for: $SCRAPER_TYPE"
echo ""

# Configure based on scraper type
case "$SCRAPER_TYPE" in
  bdl_injuries)
    SCRAPER_NAME="bdl_injuries_scraper"
    TABLE="nba_raw.bdl_injuries"
    DATE_FIELD="scrape_date"
    GCS_PATH_TEMPLATE="gs://nba-scraped-data/bdl/2024-25/DATE_PLACEHOLDER/injuries.json"
    ;;

  bdl_standings)
    SCRAPER_NAME="bdl_standings_scraper"
    TABLE="nba_raw.bdl_standings"
    DATE_FIELD="date_recorded"
    GCS_PATH_TEMPLATE="gs://nba-scraped-data/bdl/2024-25/DATE_PLACEHOLDER/standings.json"
    ;;

  nbac_schedule)
    SCRAPER_NAME="nbac_schedule_api"
    TABLE="nba_raw.nbac_schedule"
    DATE_FIELD="game_date"
    GCS_PATH_TEMPLATE="gs://nba-scraped-data/nbacom/2024-25/DATE_PLACEHOLDER/schedule.json"
    ;;

  *)
    echo "❌ Unknown scraper type: $SCRAPER_TYPE"
    echo "Supported types: bdl_injuries, bdl_standings, nbac_schedule"
    exit 1
    ;;
esac

echo "Configuration:"
echo "  Scraper: $SCRAPER_NAME"
echo "  Table: $TABLE"
echo "  Date Field: $DATE_FIELD"
echo ""

# Check each date
GAPS_FOUND=0

for i in $(seq 0 $((DAYS_TO_CHECK - 1))); do
  DATE=$(date -d "$i days ago" +%Y-%m-%d 2>/dev/null || date -v-${i}d +%Y-%m-%d)

  # Query BigQuery
  ROWS=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
    "SELECT COUNT(*) FROM \`nba-props-platform.$TABLE\`
     WHERE $DATE_FIELD = '$DATE'" 2>&1 | tail -n1)

  if [ "$ROWS" = "0" ] || [ -z "$ROWS" ]; then
    echo "❌ GAP FOUND: $DATE (no data)"
    GAPS_FOUND=$((GAPS_FOUND + 1))

    # Offer to create recovery message
    read -p "   Trigger recovery for $DATE? (y/n) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
      GCS_PATH="${GCS_PATH_TEMPLATE/DATE_PLACEHOLDER/$DATE}"

      # Create recovery message
      gcloud pubsub topics publish nba-phase1-scrapers-complete \
        --message="{
          \"scraper_name\": \"$SCRAPER_NAME\",
          \"gcs_path\": \"$GCS_PATH\",
          \"status\": \"success\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
          \"recovery\": true,
          \"execution_id\": \"recovery-$(date +%s)\"
        }"

      echo "   ✅ Recovery message sent to nba-phase1-scrapers-complete"
      echo "   Phase 2 will attempt to process: $GCS_PATH"
    else
      echo "   Skipped"
    fi
    echo ""

  else
    echo "✅ OK: $DATE ($ROWS rows)"
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Summary: Found $GAPS_FOUND data gaps"

if [ $GAPS_FOUND -gt 0 ]; then
  echo ""
  echo "Note: Recovery messages sent. Check Phase 2 logs to verify processing:"
  echo "  gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=50"
fi
