#!/bin/bash
# Quick progress checker for Phase 4 backfill

echo "============================================="
echo " PHASE 4 BACKFILL PROGRESS"
echo "============================================="
echo ""

# Check if backfill is running
if ps aux | grep -q "[p]ython3 scripts/backfill_phase4_2024_25.py"; then
    echo "✅ Backfill is RUNNING"
else
    echo "⚠️  Backfill is NOT running (may have completed or failed)"
fi

echo ""
echo "Latest progress from log:"
echo "----------------------------"
tail -30 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b55b243.output 2>/dev/null || echo "Log file not found"

echo ""
echo "============================================="
echo "To monitor live: tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b55b243.output"
echo "============================================="
