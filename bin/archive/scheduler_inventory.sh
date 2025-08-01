#!/usr/bin/env bash
# bin/monitoring/scheduler_inventory.sh
# Comprehensive monitoring script for all 23 NBA scrapers from operational document

set -e

# Shell compatibility check
if [[ -z "$BASH_VERSION" ]]; then
    echo "❌ This script requires bash"
    echo "💡 Run with: bash bin/monitoring/scheduler_inventory.sh"
    exit 1
fi

# Configuration
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "unknown")
REGION=${REGION:-us-west2}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Header
echo -e "${BLUE}🏀 NBA Scrapers - Comprehensive Scheduler Inventory${NC}"
echo -e "${BLUE}==================================================${NC}"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Shell: bash $BASH_VERSION"
echo "Timestamp: $(date)"
echo ""

# ALL 23 SCRAPERS from your operational document (complete list)
echo -e "${CYAN}📋 Complete Scraper Inventory (23 Total)${NC}"
echo "========================================"

# Critical Scrapers (4) - Business stopping if missing
CRITICAL_SCRAPERS=(
    "GetOddsApiEvents:foundation for all prop betting"
    "GetOddsApiCurrentEventOdds:core business revenue source"
    "GetNbaComPlayerList:official player-to-team mapping"
    "GetNbaComInjuryReport:player availability for props"
)

# High Priority Scrapers (4) - Affects revenue/quality
HIGH_PRIORITY_SCRAPERS=(
    "BdlActivePlayersScraper:player validation (5-6 API requests)"
    "GetDataNbaSeasonSchedule:comprehensive game scheduling"
    "GetOddsApiTeamPlayers:sportsbook player perspective"
    "GetEspnTeamRosterAPI:trade validation"
)

# Standard Scrapers (12) - Important for analysis
STANDARD_SCRAPERS=(
    "BdlGamesScraper:game status validation"
    "BdlPlayerBoxScoresScraper:player stats (post-game)"
    "BdlBoxScoresScraper:team stats (post-game)"
    "BdlInjuriesScraper:general injury context"
    "GetNbaComScheduleCdn:fast schedule updates"
    "GetNbaComScoreboardV2:game scores"
    "GetNbaComPlayByPlay:detailed game events"
    "GetNbaComPlayerBoxscore:official player stats"
    "GetNbaTeamRoster:basic team rosters"
    "GetNbaComPlayerMovement:transaction history"
    "GetEspnScoreboard:score validation"
    "GetEspnBoxscore:alternative boxscores"
)

# Analytical Scrapers (3) - Research/modeling
ANALYTICAL_SCRAPERS=(
    "GetOddsApiHistoricalEvents:historical research"
    "GetOddsApiHistoricalEventOdds:historical props"
    "BigDataBallPlayByPlay:enhanced analytics"
)

# Function to extract scraper name from job name (comprehensive mapping)
extract_scraper_from_job() {
    local job_name="$1"
    local job_name_lower=$(echo "$job_name" | tr '[:upper:]' '[:lower:]')
    
    # Comprehensive mapping based on job naming patterns
    case "$job_name_lower" in
        # Odds API
        *"odds-events"*|*"oddsa-events"*) echo "GetOddsApiEvents" ;;
        *"player-props"*|*"oddsa-props"*) echo "GetOddsApiCurrentEventOdds" ;;
        *"odds-team-players"*) echo "GetOddsApiTeamPlayers" ;;
        *"odds-historical-events"*) echo "GetOddsApiHistoricalEvents" ;;
        *"odds-historical-props"*) echo "GetOddsApiHistoricalEventOdds" ;;
        
        # Ball Don't Lie
        *"bdl-active-players"*|*"active-players"*) echo "BdlActivePlayersScraper" ;;
        *"bdl-games"*) echo "BdlGamesScraper" ;;
        *"bdl-player-box-scores"*|*"bdl-player-boxscores"*) echo "BdlPlayerBoxScoresScraper" ;;
        *"bdl-box-scores"*|*"bdl-boxscores"*) echo "BdlBoxScoresScraper" ;;
        *"bdl-injuries"*) echo "BdlInjuriesScraper" ;;
        
        # NBA.com
        *"nba-player-list"*|*"player-list"*) echo "GetNbaComPlayerList" ;;
        *"nba-injury-report"*|*"injury-report"*) echo "GetNbaComInjuryReport" ;;
        *"nba-schedule"*|*"schedule"*) echo "GetDataNbaSeasonSchedule" ;;
        *"nba-schedule-cdn"*) echo "GetNbaComScheduleCdn" ;;
        *"nba-scoreboard"*) echo "GetNbaComScoreboardV2" ;;
        *"nba-play-by-play"*) echo "GetNbaComPlayByPlay" ;;
        *"nba-player-boxscore"*) echo "GetNbaComPlayerBoxscore" ;;
        *"nba-roster"*|*"roster"*) echo "GetNbaTeamRoster" ;;
        *"nba-player-movement"*) echo "GetNbaComPlayerMovement" ;;
        
        # ESPN
        *"espn-roster"*) echo "GetEspnTeamRosterAPI" ;;
        *"espn-scoreboard"*) echo "GetEspnScoreboard" ;;
        *"espn-boxscore"*) echo "GetEspnBoxscore" ;;
        
        # Big Data Ball
        *"big-data-ball"*|*"bigdataball"*) echo "BigDataBallPlayByPlay" ;;
        
        # Default
        *) echo "UNKNOWN" ;;
    esac
}

# Function to check if scraper is scheduled
is_scraper_scheduled() {
    local target_scraper="$1"
    local scheduled_scrapers="$2"
    echo "$scheduled_scrapers" | grep -q "$target_scraper"
}

# Get current jobs
echo -e "${CYAN}📋 Current Cloud Scheduler Jobs${NC}"
echo "================================"

# Get job data
job_names=$(gcloud scheduler jobs list --location="$REGION" --format="value(name)" --quiet 2>/dev/null || echo "")

if [[ -z "$job_names" ]]; then
    echo -e "${RED}❌ No Cloud Scheduler jobs found${NC}"
    echo ""
    total_jobs=0
    scheduled_scrapers=""
else
    echo "Raw scheduler jobs:"
    gcloud scheduler jobs list --location="$REGION" --quiet
    echo ""
    
    scheduled_scrapers=""
    unknown_jobs=""
    total_jobs=0
    
    echo "Job to Scraper Mapping:"
    echo "======================="
    
    while IFS= read -r job_name; do
        [[ -z "$job_name" ]] && continue
        ((total_jobs++))
        
        scraper=$(extract_scraper_from_job "$job_name")
        
        if [[ "$scraper" != "UNKNOWN" ]]; then
            echo -e "  ✅ ${BLUE}$job_name${NC} → ${GREEN}$scraper${NC}"
            scheduled_scrapers="$scheduled_scrapers $scraper"
        else
            echo -e "  ⚠️  ${BLUE}$job_name${NC} → ${YELLOW}UNKNOWN${NC}"
            unknown_jobs="$unknown_jobs $job_name"
        fi
        
    done <<< "$job_names"
    
    echo ""
    echo "Total scheduler jobs found: $total_jobs"
fi

echo ""

# Comprehensive Analysis - ALL 23 SCRAPERS
echo -e "${CYAN}📊 Comprehensive Scraper Analysis (All 23 Scrapers)${NC}"
echo "=================================================="

# Critical scrapers analysis
echo -e "${RED}🔴 Critical Scrapers (Business Stopping if Missing)${NC}"
critical_scheduled=0
critical_total=${#CRITICAL_SCRAPERS[@]}

for scraper_entry in "${CRITICAL_SCRAPERS[@]}"; do
    scraper_name="${scraper_entry%%:*}"
    scraper_desc="${scraper_entry##*:}"
    
    if is_scraper_scheduled "$scraper_name" "$scheduled_scrapers"; then
        echo -e "  ✅ $scraper_name - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ $scraper_desc"
        ((critical_scheduled++))
    else
        echo -e "  ❌ $scraper_name - ${RED}MISSING${NC}"
        echo -e "     └─ $scraper_desc"
    fi
done

echo ""

# High priority scrapers analysis
echo -e "${YELLOW}🟡 High Priority Scrapers${NC}"
high_scheduled=0
high_total=${#HIGH_PRIORITY_SCRAPERS[@]}

for scraper_entry in "${HIGH_PRIORITY_SCRAPERS[@]}"; do
    scraper_name="${scraper_entry%%:*}"
    scraper_desc="${scraper_entry##*:}"
    
    if is_scraper_scheduled "$scraper_name" "$scheduled_scrapers"; then
        echo -e "  ✅ $scraper_name - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ $scraper_desc"
        ((high_scheduled++))
    else
        echo -e "  ❌ $scraper_name - ${RED}MISSING${NC}"
        echo -e "     └─ $scraper_desc"
    fi
done

echo ""

# Standard scrapers analysis
echo -e "${GREEN}🟢 Standard Scrapers${NC}"
standard_scheduled=0
standard_total=${#STANDARD_SCRAPERS[@]}

for scraper_entry in "${STANDARD_SCRAPERS[@]}"; do
    scraper_name="${scraper_entry%%:*}"
    scraper_desc="${scraper_entry##*:}"
    
    if is_scraper_scheduled "$scraper_name" "$scheduled_scrapers"; then
        echo -e "  ✅ $scraper_name - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ $scraper_desc"
        ((standard_scheduled++))
    else
        echo -e "  ❌ $scraper_name - ${RED}MISSING${NC}"
        echo -e "     └─ $scraper_desc"
    fi
done

echo ""

# Analytical scrapers analysis
echo -e "${BLUE}🔵 Analytical Scrapers (Often Manual)${NC}"
analytical_scheduled=0
analytical_total=${#ANALYTICAL_SCRAPERS[@]}

for scraper_entry in "${ANALYTICAL_SCRAPERS[@]}"; do
    scraper_name="${scraper_entry%%:*}"
    scraper_desc="${scraper_entry##*:}"
    
    if is_scraper_scheduled "$scraper_name" "$scheduled_scrapers"; then
        echo -e "  ✅ $scraper_name - ${GREEN}SCHEDULED${NC}"
        echo -e "     └─ $scraper_desc"
        ((analytical_scheduled++))
    else
        echo -e "  ⚪ $scraper_name - ${BLUE}NOT SCHEDULED${NC} (Manual OK)"
        echo -e "     └─ $scraper_desc"
    fi
done

echo ""

# Comprehensive statistics
total_operational_scrapers=$((critical_total + high_total + standard_total))
total_scheduled_operational=$((critical_scheduled + high_scheduled + standard_scheduled))
total_all_scrapers=$((critical_total + high_total + standard_total + analytical_total))
total_all_scheduled=$((critical_scheduled + high_scheduled + standard_scheduled + analytical_scheduled))

echo -e "${PURPLE}📈 Comprehensive Coverage Statistics${NC}"
echo "===================================="
echo "🔴 Critical: $critical_scheduled / $critical_total scheduled"
echo "🟡 High Priority: $high_scheduled / $high_total scheduled"  
echo "🟢 Standard: $standard_scheduled / $standard_total scheduled"
echo "🔵 Analytical: $analytical_scheduled / $analytical_total scheduled"
echo ""
echo "📊 Operational Scrapers: $total_scheduled_operational / $total_operational_scrapers"
echo "🎯 All Scrapers: $total_all_scheduled / $total_all_scrapers"

# Coverage percentages
if [[ $total_operational_scrapers -gt 0 ]]; then
    operational_coverage=$(( total_scheduled_operational * 100 / total_operational_scrapers ))
    if [[ $operational_coverage -ge 90 ]]; then
        coverage_color="${GREEN}"
    elif [[ $operational_coverage -ge 70 ]]; then
        coverage_color="${YELLOW}"
    else
        coverage_color="${RED}"
    fi
    echo -e "📈 Operational Coverage: ${coverage_color}${operational_coverage}%${NC}"
fi

if [[ $total_all_scrapers -gt 0 ]]; then
    total_coverage=$(( total_all_scheduled * 100 / total_all_scrapers ))
    echo -e "📈 Total Coverage: ${total_coverage}%"
fi

echo ""

# Unknown jobs
if [[ -n "$unknown_jobs" ]]; then
    echo -e "${YELLOW}⚠️  Unknown/Unmatched Jobs${NC}"
    echo "========================="
    for job in $unknown_jobs; do
        echo "  - $job (could not map to known scraper)"
    done
    echo ""
fi

# Critical dependencies analysis
echo -e "${RED}🔗 Critical Business Dependencies${NC}"
echo "================================="

events_scheduled=false
props_scheduled=false
players_scheduled=false

is_scraper_scheduled "GetOddsApiEvents" "$scheduled_scrapers" && events_scheduled=true
is_scraper_scheduled "GetOddsApiCurrentEventOdds" "$scheduled_scrapers" && props_scheduled=true
is_scraper_scheduled "GetNbaComPlayerList" "$scheduled_scrapers" && players_scheduled=true

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

# Next steps recommendations based on comprehensive analysis
echo -e "${CYAN}🚀 Comprehensive Phase 2 Recommendations${NC}"
echo "========================================"

missing_critical=$((critical_total - critical_scheduled))
missing_high=$((high_total - high_scheduled))
missing_standard=$((standard_total - standard_scheduled))

if [[ $missing_critical -gt 0 ]]; then
    echo -e "${RED}🚨 URGENT: $missing_critical critical scrapers missing${NC}"
    echo "   These must be added first (business blocking):"
    
    for scraper_entry in "${CRITICAL_SCRAPERS[@]}"; do
        scraper_name="${scraper_entry%%:*}"
        if ! is_scraper_scheduled "$scraper_name" "$scheduled_scrapers"; then
            echo "   • $scraper_name"
        fi
    done
    echo ""
fi

if [[ $missing_high -gt 0 ]]; then
    echo -e "${YELLOW}⚠️  HIGH PRIORITY: $missing_high high-priority scrapers missing${NC}"
    echo "   These significantly improve data quality:"
    
    for scraper_entry in "${HIGH_PRIORITY_SCRAPERS[@]}"; do
        scraper_name="${scraper_entry%%:*}"
        if ! is_scraper_scheduled "$scraper_name" "$scheduled_scrapers"; then
            echo "   • $scraper_name"
        fi
    done
    echo ""
fi

if [[ $missing_standard -gt 0 ]]; then
    echo -e "${GREEN}📋 STANDARD: $missing_standard standard scrapers missing${NC}"
    echo "   These provide comprehensive analysis capabilities"
    echo ""
fi

# Phase 2 approach recommendations
echo -e "${CYAN}💡 Recommended Phase 2 Approach${NC}"
echo "==============================="

if [[ $missing_critical -gt 0 ]]; then
    echo "🎯 FOCUSED APPROACH (Recommended):"
    echo "   1. Add $missing_critical critical scrapers first"
    echo "   2. Validate business functionality"  
    echo "   3. Then expand to high-priority and standard scrapers"
    echo ""
    echo "🎯 COMPREHENSIVE APPROACH (Alternative):"
    echo "   • Add all $((missing_critical + missing_high + missing_standard)) missing operational scrapers at once"
    echo "   • Provides complete coverage immediately"
    echo "   • More complex to validate and troubleshoot"
else
    echo -e "🎉 ${GREEN}All critical scrapers scheduled!${NC}"
    echo "   Focus on expanding high-priority and standard coverage"
fi

echo ""
echo "🔧 Service URL: https://nba-scrapers-756957797294.us-west2.run.app/scrape"
echo ""
echo -e "${BLUE}📖 For detailed scheduling requirements, see:${NC}"
echo -e "${BLUE}docs/scrapers/operational-reference.md${NC}"