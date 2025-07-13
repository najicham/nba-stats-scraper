#!/bin/bash
# NBA Analytics Platform - Quick Aliases

# 🔥 FASTEST SYSTEM CHECK (30 seconds)
alias nba-status='
echo "🏀 NBA Platform Quick Status:";
echo "Containers: $(docker-compose -f docker-compose.dev.yml ps | grep Up | wc -l)/6 running";
echo "Scrapers: $(curl -s http://localhost:8080/health | jq -r ".status // \"DOWN\"")";
# ... (rest of the aliases)
