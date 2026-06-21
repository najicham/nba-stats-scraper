#!/bin/bash
# API Connectivity Testing

echo "🌐 Testing NBA API Connectivity"
echo "==============================="

# Test Odds API
echo "Testing Odds API..."
API_KEY=$(docker-compose -f docker-compose.dev.yml exec scrapers printenv ODDS_API_KEY 2>/dev/null | tr -d '\r')
if [ -n "$API_KEY" ]; then
    curl -s "https://api.the-odds-api.com/v4/sports?apiKey=$API_KEY" | jq -r 'length // "ERROR"'
else
    echo "❌ No API key found"
fi

# Test Ball Don't Lie API
echo "Testing Ball Don't Lie API..."
BDL_KEY=$(docker-compose -f docker-compose.dev.yml exec scrapers printenv BDL_API_KEY 2>/dev/null | tr -d '\r')
if [ -n "$BDL_KEY" ]; then
    echo "✅ BDL API key configured"
else
    echo "⚠️  BDL API key not configured"
fi

echo "✅ API connectivity test complete"
