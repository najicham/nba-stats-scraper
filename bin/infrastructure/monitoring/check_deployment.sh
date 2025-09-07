#!/usr/bin/env bash
# NBA Scrapers script - requires bash for consistency across environments
# Compatible with macOS zsh, Linux bash, and CI/CD systems

set -e

# Shell compatibility check
if [[ -z "$BASH_VERSION" ]]; then
    echo "❌ This script requires bash but is running in a different shell"
    echo "💡 Please run with: bash $(basename $0)"
    echo "   Or from zsh: bash $0"
    exit 1
fi

# Check bash version for advanced features
if [[ ${BASH_VERSION%%.*} -lt 3 ]]; then
    echo "❌ This script requires bash 3.0+ (found: $BASH_VERSION)"
    echo "💡 Please update bash or use a different system"
    exit 1
fi

echo "=== Cloud Run Status ==="
gcloud run services describe nba-scrapers --region us-west2 --format="table(
  metadata.name,
  status.conditions[0].status,
  status.url
)"

echo -e "\n=== Recent Logs ==="
gcloud run services logs read nba-scrapers --region us-west2 --limit 10

echo -e "\n=== Recent GCS Files ==="
gsutil ls -l gs://nba-analytics-raw-data/oddsapi/historical-events/ | tail -5
