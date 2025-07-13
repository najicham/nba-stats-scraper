#!/bin/bash
# NBA Scraper Debugging Toolkit

echo "🐛 NBA Scraper Debug Analysis"
echo "============================"

# Get run ID from user if provided
RUN_ID=${1:-$(docker-compose -f docker-compose.dev.yml logs scrapers | grep "run_id" | tail -1 | grep -o '"run_id":"[^"]*"' | cut -d'"' -f4)}

echo "Analyzing Run ID: $RUN_ID"
echo ""
