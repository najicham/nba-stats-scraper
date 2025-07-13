#!/bin/bash
# NBA Development Helper Scripts

# Quick development workflow commands

dev_start() {
    echo "🚀 Starting NBA development environment..."
    docker-compose -f docker-compose.dev.yml build
    docker-compose -f docker-compose.dev.yml up -d
    sleep 10
    echo "✅ Environment started!"
    ~/code/nba-stats-scraper/monitoring/scripts/system_status.sh
}

dev_stop() {
    echo "🛑 Stopping NBA development environment..."
    docker-compose -f docker-compose.dev.yml down
    echo "✅ Environment stopped!"
}

dev_logs() {
    echo "📋 Following scraper logs (Ctrl+C to exit)..."
    docker-compose -f docker-compose.dev.yml logs -f scrapers
}

dev_test() {
    echo "🧪 Running quick scraper test..."
    curl -X POST http://localhost:8080/scrape \
      -H "Content-Type: application/json" \
      -d '{
        "sport": "basketball_nba",
        "date": "'$(date -u +%Y-%m-%d)'T00:00:00Z",
        "group": "dev",
        "debug": true
      }' | jq .
}

dev_debug() {
    echo "🔍 Debug mode - analyzing last scraper run..."
    ~/code/nba-stats-scraper/monitoring/scripts/scraper_debug.sh
}

# Export functions
export -f dev_start dev_stop dev_logs dev_test dev_debug
