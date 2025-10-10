#!/bin/bash
# FILE: backfill_jobs/scrapers/odds_api_lines/deploy.sh

# Deploy Odds API Game Lines Scraper Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Odds API Game Lines Scraper Backfill Job..."

# Use scraper-specific backfill deployment script (FIXED: added 's' to make plural)
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh odds_api_lines

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check game dates without API calls):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2024|--limit=10|--dry-run\" --region=us-west2"
echo ""
echo "  # Small test (limit to 5 dates):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2024|--limit=5\" --region=us-west2"
echo ""
echo "  # Test January 2025 (includes Clippers games to verify fix):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2024|--limit=50\" --region=us-west2"
echo ""
echo "  # Single season (2023-24):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2023\" --region=us-west2"
echo ""
echo "  # Two seasons with different strategy:"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2023,2024|--strategy=pregame\" --region=us-west2"
echo ""
echo "  # Full 4-season backfill (conservative strategy):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2021,2022,2023,2024|--strategy=conservative\" --region=us-west2"
echo ""
echo "  # Final odds strategy (1 hour before games):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=\"^|^--seasons=2024|--strategy=final\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • SCRAPER JOB: Collects historical game lines data from Odds API (not a processor)"
echo "  • Collects ~1,200 game dates across 4 NBA seasons (2021-22 through 2024-25)"
echo "  • Two-step process per date: (1) collect events, (2) collect game lines per game"
echo "  • Includes regular season, playoffs, and play-in games (same filtering as gamebook)"
echo "  • Excludes preseason and All-Star special events"
echo "  • Job has 4-hour timeout with 4GB memory and 2 CPUs"
echo "  • Rate limited: 1 second between API calls (Odds API requirement)"
echo "  • Expected duration: ~4 hours for full 4-season backfill"
echo "  • Resume logic: automatically skips already processed dates"
echo "  • Data saved to: gs://nba-scraped-data/odds-api/game-lines-history/"
echo "  • Requires scraper service URL (set via SCRAPER_SERVICE_URL env var)"
echo ""
echo "  • TIMING STRATEGIES (when to collect odds):"
echo "    - conservative (default): 4 hours before game time"
echo "    - pregame: 2 hours before game time"
echo "    - final: 1 hour before game time"
echo ""
echo "  • CRITICAL: Use pipe delimiter for comma-separated seasons:"
echo "    --args=\"^|^--seasons=2021,2022,2023,2024\""
echo "  • Strategy parameter also needs pipe when combined:"
echo "    --args=\"^|^--seasons=2023,2024|--strategy=pregame\""
echo ""
echo "  • FIXED IN THIS VERSION:"
echo "    - LAC team name mapping: 'LA Clippers' → 'Los Angeles Clippers'"
echo "    - Improved event matching logic to handle team name variants"
echo "    - Added comprehensive notification system for failures"
echo "    - Better error tracking for unmatched games"
echo ""

print_section_header "Validate results"
echo "  # Check collected game lines in GCS"
echo "  gsutil ls -r gs://nba-scraped-data/odds-api/game-lines-history/ | wc -l"
echo ""
echo "  # Count dates with game lines data:"
echo "  gsutil ls gs://nba-scraped-data/odds-api/game-lines-history/ | grep -E '[0-9]{4}-[0-9]{2}-[0-9]{2}' | wc -l"
echo ""
echo "  # Check specific date (example):"
echo "  gsutil ls gs://nba-scraped-data/odds-api/game-lines-history/2025-01-15/"
echo ""
echo "  # Verify Clippers games are captured:"
echo "  gsutil ls gs://nba-scraped-data/odds-api/game-lines-history/2025-01-15/ | grep LAC"
echo ""
echo "  # Sample a file to verify structure:"
echo "  gsutil cat gs://nba-scraped-data/odds-api/game-lines-history/2025-01-15/*LAC*.json | head -50"
echo ""
echo "  # Check for all teams in January 2025:"
echo "  for team in ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS; do"
echo "    count=\$(gsutil ls gs://nba-scraped-data/odds-api/game-lines-history/2025-01-*/ 2>/dev/null | grep -c \$team || echo 0)"
echo "    echo \"\$team: \$count games\""
echo "  done"

# Print final timing summary
print_deployment_summary