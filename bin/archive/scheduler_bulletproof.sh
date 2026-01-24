#!/usr/bin/env bash
# bin/monitoring/scheduler_bulletproof.sh
# Bulletproof version using simple if/then instead of loops

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

# Manual processing of current jobs
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

total_scheduled=$(echo "$current_scrapers" | wc -w)
echo ""
echo "Total scrapers scheduled: $total_scheduled"
echo ""

# Function to check if scraper is scheduled
is_scheduled() {
    local scraper="$1"
    echo "$current_scrapers" | grep -q "$scraper"
}

# ALL 23 SCRAPERS - Complete Analysis using simple if/then
echo -e "${CYAN}📊 Complete Scraper Analysis (All 23 Scrapers)${NC}"
echo "=============================================="

# CRITICAL SCRAPERS (4 total) - Manual enumeration
echo -e "${RED}🔴 Critical Scrapers (Business Stopping if Missing)${NC}"
critical_scheduled=0

if is_scheduled "GetOddsApiEvents"; then
    echo -e "  ✅ GetOddsApiEvents - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ foundation for all prop betting"
    ((critical_scheduled++))
else
    echo -e "  ❌ GetOddsApiEvents - ${RED}MISSING${NC}"
    echo -e "     └─ foundation for all prop betting"
fi

if is_scheduled "GetOddsApiCurrentEventOdds"; then
    echo -e "  ✅ GetOddsApiCurrentEventOdds - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ core business revenue source"
    ((critical_scheduled++))
else
    echo -e "  ❌ GetOddsApiCurrentEventOdds - ${RED}MISSING${NC}"
    echo -e "     └─ core business revenue source"
fi

if is_scheduled "GetNbaComPlayerList"; then
    echo -e "  ✅ GetNbaComPlayerList - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ official player-to-team mapping"
    ((critical_scheduled++))
else
    echo -e "  ❌ GetNbaComPlayerList - ${RED}MISSING${NC}"
    echo -e "     └─ official player-to-team mapping"
fi

if is_scheduled "GetNbaComInjuryReport"; then
    echo -e "  ✅ GetNbaComInjuryReport - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ player availability for props"
    ((critical_scheduled++))
else
    echo -e "  ❌ GetNbaComInjuryReport - ${RED}MISSING${NC}"
    echo -e "     └─ player availability for props"
fi

echo ""

# HIGH PRIORITY SCRAPERS (4 total)
echo -e "${YELLOW}🟡 High Priority Scrapers${NC}"
high_scheduled=0

if is_scheduled "BdlActivePlayersScraper"; then
    echo -e "  ✅ BdlActivePlayersScraper - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ player validation (5-6 API requests)"
    ((high_scheduled++))
else
    echo -e "  ❌ BdlActivePlayersScraper - ${RED}MISSING${NC}"
    echo -e "     └─ player validation (5-6 API requests)"
fi

if is_scheduled "GetDataNbaSeasonSchedule"; then
    echo -e "  ✅ GetDataNbaSeasonSchedule - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ comprehensive game scheduling"
    ((high_scheduled++))
else
    echo -e "  ❌ GetDataNbaSeasonSchedule - ${RED}MISSING${NC}"
    echo -e "     └─ comprehensive game scheduling"
fi

if is_scheduled "GetOddsApiTeamPlayers"; then
    echo -e "  ✅ GetOddsApiTeamPlayers - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ sportsbook player perspective"
    ((high_scheduled++))
else
    echo -e "  ❌ GetOddsApiTeamPlayers - ${RED}MISSING${NC}"
    echo -e "     └─ sportsbook player perspective"
fi

if is_scheduled "GetEspnTeamRosterAPI"; then
    echo -e "  ✅ GetEspnTeamRosterAPI - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ trade validation"
    ((high_scheduled++))
else
    echo -e "  ❌ GetEspnTeamRosterAPI - ${RED}MISSING${NC}"
    echo -e "     └─ trade validation"
fi

echo ""

# STANDARD SCRAPERS (12 total)
echo -e "${GREEN}🟢 Standard Scrapers${NC}"
standard_scheduled=0

# Games and Results
if is_scheduled "BdlGamesScraper"; then
    echo -e "  ✅ BdlGamesScraper - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ game status validation"
    ((standard_scheduled++))
else
    echo -e "  ❌ BdlGamesScraper - ${RED}MISSING${NC}"
    echo -e "     └─ game status validation"
fi

if is_scheduled "BdlPlayerBoxScoresScraper"; then
    echo -e "  ✅ BdlPlayerBoxScoresScraper - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ player stats (post-game)"
    ((standard_scheduled++))
else
    echo -e "  ❌ BdlPlayerBoxScoresScraper - ${RED}MISSING${NC}"
    echo -e "     └─ player stats (post-game)"
fi

if is_scheduled "BdlBoxScoresScraper"; then
    echo -e "  ✅ BdlBoxScoresScraper - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ team stats (post-game)"
    ((standard_scheduled++))
else
    echo -e "  ❌ BdlBoxScoresScraper - ${RED}MISSING${NC}"
    echo -e "     └─ team stats (post-game)"
fi

if is_scheduled "BdlInjuriesScraper"; then
    echo -e "  ✅ BdlInjuriesScraper - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ general injury context"
    ((standard_scheduled++))
else
    echo -e "  ❌ BdlInjuriesScraper - ${RED}MISSING${NC}"
    echo -e "     └─ general injury context"
fi

# NBA.com Standard
if is_scheduled "GetNbaComScheduleCdn"; then
    echo -e "  ✅ GetNbaComScheduleCdn - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ fast schedule updates"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetNbaComScheduleCdn - ${RED}MISSING${NC}"
    echo -e "     └─ fast schedule updates"
fi

if is_scheduled "GetNbaComScoreboardV2"; then
    echo -e "  ✅ GetNbaComScoreboardV2 - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ game scores"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetNbaComScoreboardV2 - ${RED}MISSING${NC}"
    echo -e "     └─ game scores"
fi

if is_scheduled "GetNbaComPlayByPlay"; then
    echo -e "  ✅ GetNbaComPlayByPlay - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ detailed game events"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetNbaComPlayByPlay - ${RED}MISSING${NC}"
    echo -e "     └─ detailed game events"
fi

if is_scheduled "GetNbaComPlayerBoxscore"; then
    echo -e "  ✅ GetNbaComPlayerBoxscore - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ official player stats"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetNbaComPlayerBoxscore - ${RED}MISSING${NC}"
    echo -e "     └─ official player stats"
fi

if is_scheduled "GetNbaTeamRoster"; then
    echo -e "  ✅ GetNbaTeamRoster - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ basic team rosters"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetNbaTeamRoster - ${RED}MISSING${NC}"
    echo -e "     └─ basic team rosters"
fi

if is_scheduled "GetNbaComPlayerMovement"; then
    echo -e "  ✅ GetNbaComPlayerMovement - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ transaction history"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetNbaComPlayerMovement - ${RED}MISSING${NC}"
    echo -e "     └─ transaction history"
fi

# ESPN Standard
if is_scheduled "GetEspnScoreboard"; then
    echo -e "  ✅ GetEspnScoreboard - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ score validation"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetEspnScoreboard - ${RED}MISSING${NC}"
    echo -e "     └─ score validation"
fi

if is_scheduled "GetEspnBoxscore"; then
    echo -e "  ✅ GetEspnBoxscore - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ alternative boxscores"
    ((standard_scheduled++))
else
    echo -e "  ❌ GetEspnBoxscore - ${RED}MISSING${NC}"
    echo -e "     └─ alternative boxscores"
fi

echo ""

# ANALYTICAL SCRAPERS (3 total)
echo -e "${BLUE}🔵 Analytical Scrapers (Often Manual)${NC}"
analytical_scheduled=0

if is_scheduled "GetOddsApiHistoricalEvents"; then
    echo -e "  ✅ GetOddsApiHistoricalEvents - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ historical research"
    ((analytical_scheduled++))
else
    echo -e "  ⚪ GetOddsApiHistoricalEvents - ${BLUE}NOT SCHEDULED${NC} (Manual OK)"
    echo -e "     └─ historical research"
fi

if is_scheduled "GetOddsApiHistoricalEventOdds"; then
    echo -e "  ✅ GetOddsApiHistoricalEventOdds - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ historical props"
    ((analytical_scheduled++))
else
    echo -e "  ⚪ GetOddsApiHistoricalEventOdds - ${BLUE}NOT SCHEDULED${NC} (Manual OK)"
    echo -e "     └─ historical props"
fi

if is_scheduled "BigDataBallPlayByPlay"; then
    echo -e "  ✅ BigDataBallPlayByPlay - ${GREEN}SCHEDULED${NC}"
    echo -e "     └─ enhanced analytics"
    ((analytical_scheduled++))
else
    echo -e "  ⚪ BigDataBallPlayByPlay - ${BLUE}NOT SCHEDULED${NC} (Manual OK)"
    echo -e "     └─ enhanced analytics"
fi

echo ""

# COMPREHENSIVE STATISTICS
echo -e "${PURPLE}📈 Complete Coverage Statistics${NC}"
echo "==============================="

critical_total=4
high_total=4
standard_total=12
analytical_total=3

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
operational_coverage=$(( total_operational_scheduled * 100 / total_operational ))
if [[ $operational_coverage -ge 90 ]]; then
    coverage_color="${GREEN}"
elif [[ $operational_coverage -ge 70 ]]; then
    coverage_color="${YELLOW}"
else
    coverage_color="${RED}"
fi
echo -e "📈 Operational Coverage: ${coverage_color}${operational_coverage}%${NC}"

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
    echo -e "  ❌ ${RED}Neither Events nor Props scheduled - Business revenue blocked${NC}"
fi

if [[ "$players_scheduled" == true ]]; then
    echo -e "  ✅ ${GREEN}Player Intelligence: GetNbaComPlayerList scheduled${NC}"
else
    echo -e "  ❌ ${RED}Player Intelligence: Missing (props can't be processed)${NC}"
fi

echo ""

# PHASE 2 RECOMMENDATIONS
echo -e "${CYAN}🚀 Phase 2 Strategy Analysis${NC}"
echo "============================"

missing_critical=$((critical_total - critical_scheduled))
missing_high=$((high_total - high_scheduled))
missing_standard=$((standard_total - standard_scheduled))
missing_operational=$((total_operational - total_operational_scheduled))

echo -e "${PURPLE}Current Foundation Assessment:${NC}"
echo "• Player Intelligence: $(if [[ $players_scheduled == true ]]; then echo "✅ OPERATIONAL"; else echo "❌ MISSING"; fi)"
echo "• Business Revenue: $(if [[ $missing_critical -eq 0 ]]; then echo "✅ READY"; else echo "❌ BLOCKED ($missing_critical critical missing)"; fi)"
echo "• Data Coverage: $(if [[ $operational_coverage -ge 50 ]]; then echo "GOOD"; elif [[ $operational_coverage -ge 25 ]]; then echo "ADEQUATE"; else echo "LIMITED"; fi) (${operational_coverage}%)"
echo ""

if [[ $missing_critical -gt 0 ]]; then
    echo -e "${RED}🚨 IMMEDIATE ACTION REQUIRED${NC}"
    echo "Missing $missing_critical critical business scrapers:"
    
    is_scheduled "GetOddsApiEvents" || echo "   • GetOddsApiEvents (foundation for all prop betting)"
    is_scheduled "GetOddsApiCurrentEventOdds" || echo "   • GetOddsApiCurrentEventOdds (core business revenue)"
    is_scheduled "GetNbaComInjuryReport" || echo "   • GetNbaComInjuryReport (player availability)"
    
    echo ""
    echo "🎯 FOCUSED APPROACH (Recommended):"
    echo "   Add $missing_critical critical scrapers first"
    echo "   Impact: Unlock business revenue generation"
    echo "   Coverage: ${operational_coverage}% → $((($total_operational_scheduled + $missing_critical) * 100 / $total_operational))%"
    echo ""
fi

echo "🎯 COMPREHENSIVE APPROACH (Alternative):"
echo "   Add all $missing_operational missing operational scrapers"
echo "   Impact: Complete data collection system"
echo "   Coverage: ${operational_coverage}% → 100%"
echo ""

# READY-TO-EXECUTE COMMANDS
echo -e "${CYAN}🔧 Ready-to-Execute Commands${NC}"
echo "============================"
echo "Service URL: https://nba-scrapers-756957797294.us-west2.run.app/scrape"
echo ""

if [[ $missing_critical -gt 0 ]]; then
    echo "Critical business scrapers (run in order):"
    echo ""
    
    if ! is_scheduled "GetOddsApiEvents"; then
        echo "# 1. Events (foundation - must run first)"
        echo "gcloud scheduler jobs create http nba-odds-events \\"
        echo "  --schedule='0 */2 * * *' \\"
        echo "  --uri='https://nba-scrapers-756957797294.us-west2.run.app/scrape?scraper=oddsa_events' \\"
        echo "  --http-method=POST --location=us-west2"
        echo ""
    fi
    
    if ! is_scheduled "GetOddsApiCurrentEventOdds"; then
        echo "# 2. Props (revenue - depends on events)"
        echo "gcloud scheduler jobs create http nba-player-props \\"
        echo "  --schedule='30 */2 * * *' \\"
        echo "  --uri='https://nba-scrapers-756957797294.us-west2.run.app/scrape?scraper=oddsa_player_props' \\"
        echo "  --http-method=POST --location=us-west2"
        echo ""
    fi
    
    if ! is_scheduled "GetNbaComInjuryReport"; then
        echo "# 3. Injuries (availability)"
        echo "gcloud scheduler jobs create http nba-injury-report \\"
        echo "  --schedule='0 */4 * * *' \\"
        echo "  --uri='https://nba-scrapers-756957797294.us-west2.run.app/scrape?scraper=nbac_injury_report' \\"
        echo "  --http-method=POST --location=us-west2"
        echo ""
    fi
else
    echo "🎉 All critical scrapers scheduled! Focus on expanding coverage."
fi

echo "🔄 After adding schedulers, run this script again to verify!"
echo ""
echo -e "${BLUE}📖 For detailed scheduling requirements, see:${NC}"
echo -e "${BLUE}docs/scrapers/operational-reference.md${NC}"