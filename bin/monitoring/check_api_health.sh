#!/bin/bash
# Check critical API endpoints health
# Run daily to detect API outages early

set -e

echo "=== NBA Pipeline API Health Check ==="
echo "Time: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

FAILURES=0

# Test NBA Stats API
echo -n "NBA Stats API: "
if timeout 10 curl -s "https://stats.nba.com/stats/boxscoretraditionalv2?GameID=0022500001&StartPeriod=0&EndPeriod=10&StartRange=0&EndRange=28800&RangeType=0" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  -H "Referer: https://stats.nba.com/" > /dev/null 2>&1; then
  echo "✓ OK"
else
  echo "✗ DOWN or SLOW"
  FAILURES=$((FAILURES + 1))
fi

# Test BDL API
echo -n "BallDontLie API: "
if timeout 10 curl -s -H "Authorization: $(gcloud secrets versions access latest --secret='BALLDONTLIE_API_KEY' 2>/dev/null || echo 'test')" \
  "https://api.balldontlie.io/v1/players?per_page=1" > /dev/null 2>&1; then
  echo "✓ OK"
else
  echo "✗ DOWN or UNAUTHORIZED"
  FAILURES=$((FAILURES + 1))
fi

# Test Odds API
echo -n "Odds API: "
if timeout 10 curl -s -H "Authorization: $(gcloud secrets versions access latest --secret='ODDS_API_KEY' 2>/dev/null || echo 'test')" \
  "https://api.the-odds-api.com/v4/sports" > /dev/null 2>&1; then
  echo "✓ OK"
else
  echo "✗ DOWN or UNAUTHORIZED"
  FAILURES=$((FAILURES + 1))
fi

# Test BigQuery connection
echo -n "BigQuery: "
if bq query --use_legacy_sql=false --format=csv "SELECT 1" > /dev/null 2>&1; then
  echo "✓ OK"
else
  echo "✗ CONNECTION FAILED"
  FAILURES=$((FAILURES + 1))
fi

# Test GCS connection
echo -n "Google Cloud Storage: "
if gsutil ls gs://nba-scraped-data/ > /dev/null 2>&1; then
  echo "✓ OK"
else
  echo "✗ ACCESS FAILED"
  FAILURES=$((FAILURES + 1))
fi

echo ""
echo "=== Summary ==="
if [ $FAILURES -eq 0 ]; then
  echo "✅ All APIs healthy"
  exit 0
else
  echo "❌ $FAILURES API(s) failing"
  echo "⚠️  ALERT: Pipeline dependencies degraded"
  exit 1
fi
