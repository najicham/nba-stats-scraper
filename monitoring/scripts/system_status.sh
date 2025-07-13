#!/bin/bash
# NBA Analytics Platform - Complete Monitoring Toolkit

echo "🏀 NBA Analytics Platform Status Check"
echo "====================================="

# ===== 1. CONTAINER STATUS =====
echo "📦 Container Status:"
docker-compose -f docker-compose.dev.yml ps

echo ""
echo "🏥 Health Checks:"
echo "Scrapers:   $(curl -s http://localhost:8080/health | jq -r '.status // "FAILED"')"
echo "Processors: $(curl -s http://localhost:8081/health | jq -r '.status // "FAILED"')"
echo "ReportGen:  $(curl -s http://localhost:8082/health | jq -r '.status // "FAILED"')"
