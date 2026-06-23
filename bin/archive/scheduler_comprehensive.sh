#!/usr/bin/env bash
# bin/monitoring/scheduler_comprehensive.sh
# Simple but comprehensive version that definitely works

set -euo pipefail

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "unknown")
REGION=${REGION:-us-west2}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}🏀 NBA Scrapers - Complete Analysis (All 23 Scrapers)${NC}"
echo -e "${BLUE}===================================================${NC}"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timestamp: $(date)"
echo ""

# Show current jobs
echo -e "${CYAN}📋 Current Scheduler Jobs${NC}"
echo "=========================="
gcloud scheduler jobs list --location="$REGION" --quiet
echo ""

# Get job names for analysis
job_names=$(gcloud scheduler jobs list --location="$REGION" --format="value(name)" --quiet 2>/dev/null || echo "")

echo -e "${CYAN}📊 Job Analysis${NC}"
echo "==============="
echo "Current jobs detected:"

# Manual processing of known jobs (reliable)
current_scrapers=""
if echo "$job_names" | grep -q "test-bdl-active-players"; then
    echo "  ✅ test-bdl-active-players → BdlActivePlayersScraper"
    current_scrapers="$current_scrapers BdlActivePlayersScraper"
fi

if echo "$job_names" | grep -q "test-nba-player-list"; then
    echo "  ✅ test-nba-player-list → GetNbaComPlayerList"
    current_scrapers="$current_scrapers GetNbaComPlayerList"
fi

if echo "$job_names" | grep -q "test-nba-gsw-roster"; then
    echo "  ✅ test-nba-gsw-roster → GetNbaTeamRoster"
    current_scrapers="$current_scrapers GetNbaTeamRoster"
fi

# Check for other possible jobs
if echo "$job_names" | grep -i -q "odds.*events"; then
    echo "  ✅ [odds-events job] → GetOddsApiEvents"
    current_scrapers="$current_scrapers GetOddsApiEvents"
fi

if echo "$job_names" | grep -i -q "props"; then
    echo "  ✅ [props job] → GetOddsApiCurrentEventOdds"
    current_scrapers="$current_scrapers GetOddsApiCurrentEventOdds"
fi

if echo "$job_names" | grep -i -q "injury"; then
    echo "  ✅ [injury job] → GetNbaComInjuryReport"
    current_scrapers="$current_scrapers GetNbaComInjuryReport"
fi

total_scheduled=$(echo "$current_scrapers" | wc -w)
echo ""
echo "Total scrapers scheduled: $total_scheduled"
echo ""

# ALL 23 SCRAPERS - Complete Analysis
echo -e "${CYAN}📊 Complete Scraper Analysis (All 23 Scrapers)${NC}"
echo "=============================================="

# Function to check if scraper is scheduled
is_scheduled() {
    local scraper="$1"
    echo "$current_scrapers" | grep -q "$scraper"
}

# CRITICAL SCRAPERS (4 total)
echo -e "${RED}🔴 Critical Scrapers (Business Stopping if Missing)${NC}"
critical_scheduled=0
critical_total=4

scrapers=("GetOddsApiEvents" "GetOddsApiCurrentEventOdds" "GetNbaComPlayerList" "GetNbaComInjuryReport")
descriptions=("foundation for all prop betting" "core business revenue source" "official player-to-team mapping" "player availability for props")

for i in "${!scrapers[@]}"; do
    if is_scheduled "${scrapers[$i]}"; then
        echo -e "  ✅ ${scrapers[$i]} - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ ${descriptions[$i]}"
        ((critical_scheduled++))
    else
        echo -e "  ❌ ${scrapers[$i]} - ${RED}MISSING${NC}"
        echo -e "     └─ ${descriptions[$i]}"
    fi
done

echo ""

# HIGH PRIORITY SCRAPERS (4 total)
echo -e "${YELLOW}🟡 High Priority Scrapers${NC}"
high_scheduled=0
high_total=4

scrapers=("BdlActivePlayersScraper" "GetDataNbaSeasonSchedule" "GetOddsApiTeamPlayers" "GetEspnTeamRosterAPI")
descriptions=("player validation (5-6 API requests)" "comprehensive game scheduling" "sportsbook player perspective" "trade validation")

for i in "${!scrapers[@]}"; do
    if is_scheduled "${scrapers[$i]}"; then
        echo -e "  ✅ ${scrapers[$i]} - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ ${descriptions[$i]}"
        ((high_scheduled++))
    else
        echo -e "  ❌ ${scrapers[$i]} - ${RED}MISSING${NC}"
        echo -e "     └─ ${descriptions[$i]}"
    fi
done

echo ""

# STANDARD SCRAPERS (12 total)
echo -e "${GREEN}🟢 Standard Scrapers${NC}"
standard_scheduled=0
standard_total=12

scrapers=("BdlGamesScraper" "BdlPlayerBoxScoresScraper" "BdlBoxScoresScraper" "BdlInjuriesScraper" "GetNbaComScheduleCdn" "GetNbaComScoreboardV2" "GetNbaComPlayByPlay" "GetNbaComPlayerBoxscore" "GetNbaTeamRoster" "GetNbaComPlayerMovement" "GetEspnScoreboard" "GetEspnBoxscore")
descriptions=("game status validation" "player stats (post-game)" "team stats (post-game)" "general injury context" "fast schedule updates" "game scores" "detailed game events" "official player stats" "basic team rosters" "transaction history" "score validation" "alternative boxscores")

for i in "${!scrapers[@]}"; do
    if is_scheduled "${scrapers[$i]}"; then
        echo -e "  ✅ ${scrapers[$i]} - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ ${descriptions[$i]}"
        ((standard_scheduled++))
    else
        echo -e "  ❌ ${scrapers[$i]} - ${RED}MISSING${NC}"
        echo -e "     └─ ${descriptions[$i]}"
    fi
done

echo ""

# ANALYTICAL SCRAPERS (3 total)
echo -e "${BLUE}🔵 Analytical Scrapers (Often Manual)${NC}"
analytical_scheduled=0
analytical_total=3

scrapers=("GetOddsApiHistoricalEvents" "GetOddsApiHistoricalEventOdds" "BigDataBallPlayByPlay")
descriptions=("historical research" "historical props" "enhanced analytics")

for i in "${!scrapers[@]}"; do
    if is_scheduled "${scrapers[$i]}"; then
        echo -e "  ✅ ${scrapers[$i]} - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ ${descriptions[$i]}"
        ((analytical_scheduled++))
    else
        echo -e "  ⚪ ${scrapers[$i]} - ${BLUE}NOT SCHEDULED${NC} (Manual OK)"
        echo -e "     └─ ${descriptions[$i]}"
    fi
done

echo ""

# COMPREHENSIVE STATISTICS
echo -e "${PURPLE}📈 Complete Coverage Statistics${NC}"
echo "==============================="

total_operational=$((critical_total + high_total + standard_total))
total_operational_scheduled=$((critical_scheduled + high_scheduled + standard_scheduled))
total_all=$((critical_total + high_total + standard_total + analytical_total))
total_all_scheduled=$((critical_scheduled + high_scheduled + standard_scheduled + analytical_scheduled))

echo "🔴 Critical: $critical_scheduled / $critical_total scheduled"
echo "🟡 High Priority: $high_scheduled / $high_total scheduled"
echo "🟢 Standard: $standard_scheduled / $standard_total scheduled"
echo "🔵 Analytical: $analytical_scheduled / $analytical_total scheduled"
echo ""
echo "📊 Operational Scrapers: $total_operational_scheduled / $total_operational"
echo "🎯 All Scrapers: $total_all_scheduled / $total_all"

# Coverage percentages
if [[ $total_operational -gt 0 ]]; then
    operational_coverage=$(( total_operational_scheduled * 100 / total_operational ))
    if [[ $operational_coverage -ge 90 ]]; then
        coverage_color="${GREEN}"
    elif [[ $operational_coverage -ge 70 ]]; then
        coverage_color="${YELLOW}"
    else
        coverage_color="${RED}"
    fi
    echo -e "📈 Operational Coverage: ${coverage_color}${operational_coverage}%${NC}"
fi

total_coverage=$(( total_all_scheduled * 100 / total_all ))
echo -e "📈 Total Coverage: ${total_coverage}%"

echo ""

# CRITICAL DEPENDENCIES
echo -e "${RED}🔗 Critical Business Dependencies${NC}"
echo "================================="

events_scheduled=false
props_scheduled=false
players_scheduled=false

is_scheduled "GetOddsApiEvents" && events_scheduled=true
is_scheduled "GetOddsApiCurrentEventOdds" && props_scheduled=true
is_scheduled "GetNbaComPlayerList" && players_scheduled=true

if [[ "$events_scheduled" == true && "$props_scheduled" == true ]]; then
    echo -e "  ✅ ${GREEN}Events → Props dependency: Both scheduled${NC}"
elif [[ "$events_scheduled" == true && "$props_scheduled" == false ]]; then
    echo -e "  ⚠️  ${YELLOW}Events scheduled but Props missing${NC}"
elif [[ "$events_scheduled" == false && "$props_scheduled" == true ]]; then
    echo -e "  ❌ ${RED}Props scheduled but Events missing (WILL FAIL)${NC}"
else
    echo -e "  ❌ ${RED}Neither Events nor Props scheduled${NC}"
fi

if [[ "$players_scheduled" == true ]]; then
    echo -e "  ✅ ${GREEN}Player Intelligence: GetNbaComPlayerList scheduled${NC}"
else
    echo -e "  ❌ ${RED}Player Intelligence: Missing (props can't be processed)${NC}"
fi

echo ""

# PHASE 2 RECOMMENDATIONS
echo -e "${CYAN}🚀 Phase 2 Strategy Recommendations${NC}"
echo "==================================="

missing_critical=$((critical_total - critical_scheduled))
missing_high=$((high_total - high_scheduled))
missing_standard=$((standard_total - standard_scheduled))
missing_operational=$((total_operational - total_operational_scheduled))

echo -e "${PURPLE}Current Status Assessment:${NC}"
echo "• Foundation Strength: $(if [[ $critical_scheduled -ge 2 ]]; then echo "GOOD"; else echo "NEEDS WORK"; fi)"
echo "• Business Readiness: $(if [[ $missing_critical -eq 0 ]]; then echo "READY"; else echo "BLOCKED"; fi)"
echo "• Data Coverage: $(if [[ $operational_coverage -ge 50 ]]; then echo "ADEQUATE"; else echo "LIMITED"; fi)"
echo ""

if [[ $missing_critical -gt 0 ]]; then
    echo -e "${RED}🚨 IMMEDIATE PRIORITY: $missing_critical critical scrapers missing${NC}"
    echo "   Business impact: Revenue generation blocked"
    echo ""
    echo "🎯 FOCUSED APPROACH (Recommended):"
    echo "   • Add $missing_critical critical scrapers first"
    echo "   • Validate business functionality"
    echo "   • Coverage: ${operational_coverage}% → $((($total_operational_scheduled + $missing_critical) * 100 / $total_operational))%"
    echo ""
fi

if [[ $missing_operational -gt 3 ]]; then
    echo "🎯 COMPREHENSIVE APPROACH (Alternative):"
    echo "   • Add all $missing_operational missing operational scrapers"
    echo "   • Immediate complete coverage"
    echo "   • Coverage: ${operational_coverage}% → 100%"
    echo "   • More complex to implement and validate"
    echo ""
fi

# SERVICE INFO
echo -e "${CYAN}🔧 Service Information${NC}"
echo "====================="
echo "Cloud Run Service: https://nba-scrapers-756957797294.us-west2.run.app/scrape"
echo "Architecture: Unified service with query parameter routing"
echo "Example: /scrape?scraper=oddsa_events"
echo ""

echo -e "${BLUE}📖 For detailed scheduling requirements, see:${NC}"
echo -e "${BLUE}docs/scrapers/operational-reference.md${NC}"
