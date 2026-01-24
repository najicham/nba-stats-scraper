#!/bin/bash
# =============================================================================
# File: scripts/test-validate-schedule.sh
# Purpose: Test the validate-schedule CLI tool
# Usage: ./scripts/test-validate-schedule.sh
# =============================================================================

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Base directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
CLI_SCRIPT="$PROJECT_ROOT/scripts/validate-schedule"
QUERIES_DIR="$PROJECT_ROOT/validation/queries/raw/nbac_schedule"

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}Testing validate-schedule CLI Tool${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# Test 1: Check script exists
echo -e "${YELLOW}Test 1: Check script exists${NC}"
if [ -f "$CLI_SCRIPT" ]; then
    echo -e "${GREEN}✅ Script found at: $CLI_SCRIPT${NC}"
else
    echo -e "${RED}❌ Script not found at: $CLI_SCRIPT${NC}"
    exit 1
fi
echo ""

# Test 2: Check script is executable
echo -e "${YELLOW}Test 2: Check script is executable${NC}"
if [ -x "$CLI_SCRIPT" ]; then
    echo -e "${GREEN}✅ Script is executable${NC}"
else
    echo -e "${YELLOW}⚠️  Script not executable. Making it executable...${NC}"
    chmod +x "$CLI_SCRIPT"
    echo -e "${GREEN}✅ Script is now executable${NC}"
fi
echo ""

# Test 3: Check queries directory exists
echo -e "${YELLOW}Test 3: Check queries directory exists${NC}"
if [ -d "$QUERIES_DIR" ]; then
    echo -e "${GREEN}✅ Queries directory found${NC}"
    query_count=$(ls -1 "$QUERIES_DIR"/*.sql 2>/dev/null | wc -l)
    echo -e "${GREEN}   Found $query_count SQL query files${NC}"
else
    echo -e "${RED}❌ Queries directory not found at: $QUERIES_DIR${NC}"
    echo -e "${YELLOW}   You need to create the query files first${NC}"
    exit 1
fi
echo ""

# Test 4: List all query files
echo -e "${YELLOW}Test 4: List query files${NC}"
if [ -d "$QUERIES_DIR" ]; then
    for query in "$QUERIES_DIR"/*.sql; do
        if [ -f "$query" ]; then
            basename "$query"
        fi
    done | sed 's/^/   /'
fi
echo ""

# Test 5: Test help command
echo -e "${YELLOW}Test 5: Test help command${NC}"
if "$CLI_SCRIPT" help > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Help command works${NC}"
else
    echo -e "${RED}❌ Help command failed${NC}"
    exit 1
fi
echo ""

# Test 6: Test list command
echo -e "${YELLOW}Test 6: Test list command${NC}"
if "$CLI_SCRIPT" list > /dev/null 2>&1; then
    echo -e "${GREEN}✅ List command works${NC}"
else
    echo -e "${RED}❌ List command failed${NC}"
    exit 1
fi
echo ""

# Test 7: Check if bq command is available
echo -e "${YELLOW}Test 7: Check BigQuery CLI (bq)${NC}"
if command -v bq &> /dev/null; then
    echo -e "${GREEN}✅ bq command available${NC}"
    bq_version=$(bq version 2>&1 | head -n 1)
    echo -e "${GREEN}   Version: $bq_version${NC}"
else
    echo -e "${YELLOW}⚠️  bq command not found${NC}"
    echo -e "${YELLOW}   Install gcloud CLI to use BigQuery features${NC}"
fi
echo ""

# Test 8: Verify all expected queries exist
echo -e "${YELLOW}Test 8: Verify all expected query files exist${NC}"
expected_queries=(
    "season_completeness_check.sql"
    "find_missing_regular_season_games.sql"
    "verify_playoff_completeness.sql"
    "team_balance_check.sql"
    "team_schedule_gaps.sql"
    "daily_freshness_check.sql"
    "schedule_horizon_check.sql"
    "enhanced_field_quality.sql"
)

missing_count=0
for query in "${expected_queries[@]}"; do
    if [ -f "$QUERIES_DIR/$query" ]; then
        echo -e "${GREEN}   ✅ $query${NC}"
    else
        echo -e "${RED}   ❌ $query (missing)${NC}"
        ((missing_count++))
    fi
done

if [ $missing_count -eq 0 ]; then
    echo -e "${GREEN}✅ All expected query files present${NC}"
else
    echo -e "${RED}❌ $missing_count query file(s) missing${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}=================================================${NC}"

if [ $missing_count -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Run: validate-schedule help"
    echo "  2. Run: validate-schedule list"
    echo "  3. Try: validate-schedule yesterday"
    echo "  4. Try: validate-schedule completeness"
    echo ""
    echo -e "${YELLOW}Note:${NC} Queries will require BigQuery access to run"
else
    echo -e "${RED}❌ Some tests failed${NC}"
    echo -e "${YELLOW}Please create missing query files before using the CLI${NC}"
fi
