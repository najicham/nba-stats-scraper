#!/usr/bin/env bash
set -euo pipefail
# bin/monitoring/nba_monitor_scheduler.sh - Clean version without syntax errors

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

# Simple functions
get_current_jobs() {
    gcloud scheduler jobs list --location="$REGION" --format="value(name)" --quiet 2>/dev/null || echo ""
}

check_job() {
    local job_name="$1"
    if echo "$current_jobs" | grep -q "^${job_name}$"; then
        echo "SCHEDULED"
    else
        echo "MISSING"
    fi
}

main() {
    echo -e "${BLUE}🏀 NBA Priority Scrapers - Complete Operational Monitor${NC}"
    echo -e "${BLUE}======================================================${NC}"
    echo "Project: $PROJECT_ID"
    echo "Region: $REGION"  
    echo "Timestamp: $(date)"
    echo ""

    # Get current jobs
    current_jobs=$(get_current_jobs)
    
    echo -e "${CYAN}📋 Current Scheduler Jobs${NC}"
    echo "=========================="
    if [[ -n "$current_jobs" ]]; then
        gcloud scheduler jobs list --location="$REGION" --quiet
    else
        echo "No scheduler jobs found"
    fi
    echo ""

    echo -e "${PURPLE}📊 Complete Operational Analysis (17 Scrapers)${NC}"
    echo "=============================================="
    
    # Critical scrapers
    echo -e "${RED}🔴 CRITICAL SCRAPERS${NC}"
    echo "1. GetOddsApiEvents (nba-odds-events)"
    status=$(check_job "nba-odds-events")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Foundation for prop betting"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Foundation for prop betting"
    fi

    echo "2. GetOddsApiCurrentEventOdds (nba-odds-props)"
    status=$(check_job "nba-odds-props")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Core business revenue"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Core business revenue"
    fi

    echo "3. GetNbaComInjuryReport (nba-injury-report)"
    status=$(check_job "nba-injury-report")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Player availability"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Player availability"
    fi

    echo "4. GetNbaComPlayerList (nba-player-list)"
    status=$(check_job "nba-player-list")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Player-team mapping"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Player-team mapping"
    fi

    echo ""

    # High priority scrapers
    echo -e "${YELLOW}🟡 HIGH PRIORITY SCRAPERS${NC}"
    echo "5. GetDataNbaSeasonSchedule (nba-season-schedule)"
    status=$(check_job "nba-season-schedule")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Game scheduling"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Game scheduling"
    fi

    echo "6. GetOddsApiTeamPlayers (nba-odds-team-players)"
    status=$(check_job "nba-odds-team-players")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Sportsbook perspective"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Sportsbook perspective"
    fi

    echo "7. BdlActivePlayersScraper (nba-bdl-active-players)"
    status=$(check_job "nba-bdl-active-players")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Player validation"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Player validation"
    fi

    echo "8. GetEspnTeamRosterAPI (nba-espn-gsw-roster)"
    status=$(check_job "nba-espn-gsw-roster")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Trade validation"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Trade validation"
    fi

    echo ""

    # Additional operational scrapers
    echo -e "${BLUE}🔵 ADDITIONAL OPERATIONAL SCRAPERS${NC}"
    echo "9. GetNbaComPlayerMovement (nba-player-movement)"
    status=$(check_job "nba-player-movement")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Transaction history"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Transaction history"
    fi

    echo "10. GetNbaTeamRoster (nba-team-roster)"
    status=$(check_job "nba-team-roster")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - All 30 team rosters"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - All 30 team rosters"
    fi

    echo "11. GetEspnScoreboard (nba-espn-scoreboard)"
    status=$(check_job "nba-espn-scoreboard")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Game scores"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Game scores"
    fi

    echo "12. GetNbaComScoreboardV2 (nba-nbacom-scoreboard)"
    status=$(check_job "nba-nbacom-scoreboard")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Official NBA scores"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Official NBA scores"
    fi

    echo "13. BdlPlayerBoxScoresScraper (nba-bdl-player-boxscores)"
    status=$(check_job "nba-bdl-player-boxscores")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Individual player stats"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Individual player stats"
    fi

    echo "14. BdlBoxScoresScraper (nba-bdl-boxscores)"
    status=$(check_job "nba-bdl-boxscores")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Team stats with embedded players"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Team stats with embedded players"
    fi

    echo "15. GetNbaComPlayerBoxscore (nba-nbacom-player-boxscore)"
    status=$(check_job "nba-nbacom-player-boxscore")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Official player stats"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Official player stats"
    fi

    echo "16. GetEspnBoxscore (nba-espn-boxscore)"
    status=$(check_job "nba-espn-boxscore")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Alternative boxscores"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Alternative boxscores"
    fi

    echo "17. GetNbaComPlayByPlay (nba-nbacom-playbyplay)"
    status=$(check_job "nba-nbacom-playbyplay")
    if [[ "$status" == "SCHEDULED" ]]; then
        echo -e "   ✅ ${GREEN}SCHEDULED${NC} - Detailed play-by-play"
    else
        echo -e "   ❌ ${RED}MISSING${NC} - Detailed play-by-play"
    fi

    echo ""

    # Count all scrapers
    critical_count=0
    high_count=0
    additional_count=0

    # Count critical (4)
    [[ $(check_job "nba-odds-events") == "SCHEDULED" ]] && ((critical_count++))
    [[ $(check_job "nba-odds-props") == "SCHEDULED" ]] && ((critical_count++))
    [[ $(check_job "nba-injury-report") == "SCHEDULED" ]] && ((critical_count++))
    [[ $(check_job "nba-player-list") == "SCHEDULED" ]] && ((critical_count++))

    # Count high priority (4)
    [[ $(check_job "nba-season-schedule") == "SCHEDULED" ]] && ((high_count++))
    [[ $(check_job "nba-odds-team-players") == "SCHEDULED" ]] && ((high_count++))
    [[ $(check_job "nba-bdl-active-players") == "SCHEDULED" ]] && ((high_count++))
    [[ $(check_job "nba-espn-gsw-roster") == "SCHEDULED" ]] && ((high_count++))

    # Count additional (9)
    [[ $(check_job "nba-player-movement") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-team-roster") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-espn-scoreboard") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-nbacom-scoreboard") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-bdl-player-boxscores") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-bdl-boxscores") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-nbacom-player-boxscore") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-espn-boxscore") == "SCHEDULED" ]] && ((additional_count++))
    [[ $(check_job "nba-nbacom-playbyplay") == "SCHEDULED" ]] && ((additional_count++))

    total_count=$((critical_count + high_count + additional_count))
    coverage=$(( total_count * 100 / 17 ))

    echo -e "${PURPLE}📈 Complete Operational Summary${NC}"
    echo "==============================="
    echo "🔴 Critical: $critical_count / 4 scheduled"
    echo "🟡 High Priority: $high_count / 4 scheduled"  
    echo "🔵 Additional Operational: $additional_count / 9 scheduled"
    echo "📊 Total: $total_count / 17 scheduled"

    if [[ $coverage -ge 90 ]]; then
        coverage_color="${GREEN}"
        readiness="COMPLETE OPERATIONAL COVERAGE"
    elif [[ $coverage -ge 50 ]]; then
        coverage_color="${YELLOW}"
        readiness="PARTIAL OPERATIONAL COVERAGE"
    else
        coverage_color="${RED}"
        readiness="MINIMAL OPERATIONAL COVERAGE"
    fi
    echo -e "📈 Coverage: ${coverage_color}${coverage}%${NC} - ${readiness}"

    echo ""

    # Business dependencies
    echo -e "${RED}🔗 Business Dependencies${NC}"
    echo "======================="

    events_status=$(check_job "nba-odds-events")
    props_status=$(check_job "nba-odds-props")
    players_status=$(check_job "nba-player-list")

    if [[ "$events_status" == "SCHEDULED" && "$props_status" == "SCHEDULED" ]]; then
        echo -e "✅ ${GREEN}Events → Props: Both scheduled${NC}"
    elif [[ "$events_status" == "SCHEDULED" && "$props_status" == "MISSING" ]]; then
        echo -e "⚠️  ${YELLOW}Events scheduled, Props missing${NC}"
    elif [[ "$events_status" == "MISSING" && "$props_status" == "SCHEDULED" ]]; then
        echo -e "❌ ${RED}Props scheduled but Events missing - WILL FAIL${NC}"
    else
        echo -e "❌ ${RED}Neither Events nor Props scheduled - NO REVENUE${NC}"
    fi

    if [[ "$players_status" == "SCHEDULED" ]]; then
        echo -e "✅ ${GREEN}Player Intelligence: Available${NC}"
    else
        echo -e "❌ ${RED}Player Intelligence: Missing${NC}"
    fi

    echo ""
    echo "🔄 To schedule missing scrapers: ./$(basename $0) schedule-missing"
}

# Command-line handling
case "${1:-}" in
    "schedule-missing")
        echo -e "${CYAN}🚀 Scheduling Missing Operational Scrapers${NC}"
        echo "=========================================="
        current_jobs=$(get_current_jobs)
        SERVICE_URL="https://nba-scrapers-756957797294.us-west2.run.app/scrape"
        scheduled_count=0
        
        echo "🔵 Scheduling 9 Additional Operational Scrapers"
        echo ""
        
        # Daily 8 AM scrapers
        if [[ $(check_job "nba-player-movement") == "MISSING" ]]; then
            echo "Scheduling: nba-player-movement"
            gcloud scheduler jobs create http nba-player-movement \
                --schedule='0 8 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=nbac_player_movement" \
                --http-method=POST \
                --location="$REGION" \
                --description="Complete transaction history" \
                --quiet
            echo "✅ Scheduled: nba-player-movement"
            ((scheduled_count++))
        fi
        
        if [[ $(check_job "nba-team-roster") == "MISSING" ]]; then
            echo "Scheduling: nba-team-roster"
            gcloud scheduler jobs create http nba-team-roster \
                --schedule='15 8 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=nbac_roster" \
                --http-method=POST \
                --location="$REGION" \
                --description="All 30 team rosters (basic format)" \
                --quiet
            echo "✅ Scheduled: nba-team-roster"
            ((scheduled_count++))
        fi
        
        # Game day evening scrapers
        if [[ $(check_job "nba-espn-scoreboard") == "MISSING" ]]; then
            echo "Scheduling: nba-espn-scoreboard"
            gcloud scheduler jobs create http nba-espn-scoreboard \
                --schedule='0 18,21,23 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=espn_scoreboard_api" \
                --http-method=POST \
                --location="$REGION" \
                --description="Game scores and status validation" \
                --quiet
            echo "✅ Scheduled: nba-espn-scoreboard"
            ((scheduled_count++))
        fi
        
        if [[ $(check_job "nba-nbacom-scoreboard") == "MISSING" ]]; then
            echo "Scheduling: nba-nbacom-scoreboard"
            gcloud scheduler jobs create http nba-nbacom-scoreboard \
                --schedule='0 18,21,23 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=nbac_scoreboard_v2" \
                --http-method=POST \
                --location="$REGION" \
                --description="Official NBA scores with quarter data" \
                --quiet
            echo "✅ Scheduled: nba-nbacom-scoreboard"
            ((scheduled_count++))
        fi
        
        # Post-game scrapers (9 PM ET after games complete)
        if [[ $(check_job "nba-bdl-player-boxscores") == "MISSING" ]]; then
            echo "Scheduling: nba-bdl-player-boxscores"
            gcloud scheduler jobs create http nba-bdl-player-boxscores \
                --schedule='0 21 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=bdl_player_box_scores" \
                --http-method=POST \
                --location="$REGION" \
                --description="Individual player statistics for completed games" \
                --quiet
            echo "✅ Scheduled: nba-bdl-player-boxscores"
            ((scheduled_count++))
        fi
        
        if [[ $(check_job "nba-bdl-boxscores") == "MISSING" ]]; then
            echo "Scheduling: nba-bdl-boxscores"
            gcloud scheduler jobs create http nba-bdl-boxscores \
                --schedule='5 21 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=bdl_box_scores" \
                --http-method=POST \
                --location="$REGION" \
                --description="Team boxscores with embedded player stats" \
                --quiet
            echo "✅ Scheduled: nba-bdl-boxscores"
            ((scheduled_count++))
        fi
        
        if [[ $(check_job "nba-nbacom-player-boxscore") == "MISSING" ]]; then
            echo "Scheduling: nba-nbacom-player-boxscore"
            gcloud scheduler jobs create http nba-nbacom-player-boxscore \
                --schedule='10 21 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=nbac_player_boxscore" \
                --http-method=POST \
                --location="$REGION" \
                --description="Official player stats with fantasy points" \
                --quiet
            echo "✅ Scheduled: nba-nbacom-player-boxscore"
            ((scheduled_count++))
        fi
        
        if [[ $(check_job "nba-espn-boxscore") == "MISSING" ]]; then
            echo "Scheduling: nba-espn-boxscore"
            gcloud scheduler jobs create http nba-espn-boxscore \
                --schedule='15 21 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=espn_game_boxscore" \
                --http-method=POST \
                --location="$REGION" \
                --description="Alternative boxscore validation" \
                --quiet
            echo "✅ Scheduled: nba-espn-boxscore"
            ((scheduled_count++))
        fi
        
        if [[ $(check_job "nba-nbacom-playbyplay") == "MISSING" ]]; then
            echo "Scheduling: nba-nbacom-playbyplay"
            gcloud scheduler jobs create http nba-nbacom-playbyplay \
                --schedule='20 21 * * *' \
                --time-zone='America/Los_Angeles' \
                --uri="${SERVICE_URL}?scraper=nbac_play_by_play" \
                --http-method=POST \
                --location="$REGION" \
                --description="Detailed play-by-play with coordinates" \
                --quiet
            echo "✅ Scheduled: nba-nbacom-playbyplay"
            ((scheduled_count++))
        fi
        
        echo ""
        echo "📊 Scheduled $scheduled_count new jobs"
        echo "🔄 Run './$(basename $0)' to verify complete operational coverage"
        ;;
        
    "help"|"-h"|"--help")
        echo "NBA Complete Operational Scrapers Monitor"
        echo ""
        echo "Usage:"
        echo "  $(basename $0)                 # Show current status of all 17 operational scrapers"
        echo "  $(basename $0) schedule-missing # Schedule all missing operational scrapers"
        echo "  $(basename $0) help            # Show this help"
        echo ""
        echo "Complete Operational Coverage (17 scrapers from operational document):"
        echo "  Critical (4): Events, Props, Player List, Injury Report"
        echo "  High Priority (4): Schedule, Team Players, BDL Players, ESPN Roster"
        echo "  Additional Operational (9): Player Movement, Team Rosters, Scoreboards, Boxscores, Play-by-Play"
        ;;
        
    *)
        main
        ;;
esac