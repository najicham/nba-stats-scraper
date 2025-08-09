#!/bin/bash
# File: bin/analysis/jq_gamebook_analyzer.sh
# Purpose: Comprehensive jq-based analysis toolkit for NBA gamebook data

set -e

PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
JSON_PATH="nba-com/gamebooks-data"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}🔬 NBA GAMEBOOK JQ ANALYSIS TOOLKIT${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# Download a sample file for analysis
get_sample_file() {
    local temp_file="/tmp/nba_sample_$(date +%s).json"
    
    # Get the most recent file
    local recent_file=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" --long --format="value(name,timeCreated)" 2>/dev/null | \
        grep "\.json" | sort -k2 -r | head -1 | awk '{print $1}' | sed "s|^|gs://nba-scraped-data/|")
    
    if [[ -z "$recent_file" ]]; then
        echo "No files found"
        return 1
    fi
    
    echo "Using sample file: $(basename "$recent_file")"
    
    if gcloud storage cp "$recent_file" "$temp_file" >/dev/null 2>&1; then
        echo "$temp_file"
    else
        echo ""
    fi
}

# Analyze JSON structure
cmd_structure() {
    print_header
    echo -e "${BLUE}🏗️  JSON Structure Analysis:${NC}"
    echo ""
    
    local sample_file=$(get_sample_file)
    if [[ -z "$sample_file" ]]; then
        echo "Could not download sample file"
        return 1
    fi
    
    echo -e "${GREEN}Top-level keys:${NC}"
    jq -r 'keys[]' "$sample_file" | sed 's/^/  /'
    
    echo ""
    echo -e "${GREEN}Game info structure:${NC}"
    jq -r '.game_info | keys[]' "$sample_file" 2>/dev/null | sed 's/^/  /' || echo "  No game_info found"
    
    echo ""
    echo -e "${GREEN}Player object structure (first player):${NC}"
    jq -r '.players[0] | keys[]' "$sample_file" 2>/dev/null | sed 's/^/  /' || echo "  No players found"
    
    echo ""
    echo -e "${GREEN}Sample player data:${NC}"
    jq -r '.players[0]' "$sample_file" 2>/dev/null | head -10 | sed 's/^/  /'
    
    rm -f "$sample_file"
}

# Player statistics analysis
cmd_player_stats() {
    print_header
    echo -e "${BLUE}👥 Player Statistics Analysis:${NC}"
    echo ""
    
    local sample_file=$(get_sample_file)
    if [[ -z "$sample_file" ]]; then
        echo "Could not download sample file"
        return 1
    fi
    
    echo -e "${GREEN}Player status distribution:${NC}"
    jq -r '.players | group_by(.status) | map({status: .[0].status, count: length}) | .[] | "  \(.status): \(.count) players"' "$sample_file"
    
    echo ""
    echo -e "${GREEN}Players with stats (pts, min, reb, ast):${NC}"
    jq -r '
        .players | map(select(.pts != null and .pts != "")) | length as $with_pts |
        .players | map(select(.min != null and .min != "")) | length as $with_min |
        .players | map(select(.reb != null and .reb != "")) | length as $with_reb |
        .players | map(select(.ast != null and .ast != "")) | length as $with_ast |
        "  Points: \($with_pts)",
        "  Minutes: \($with_min)", 
        "  Rebounds: \($with_reb)",
        "  Assists: \($with_ast)"
    ' "$sample_file"
    
    echo ""
    echo -e "${GREEN}Top 5 scorers (if available):${NC}"
    jq -r '.players | map(select(.pts != null and .pts != "")) | sort_by(.pts | tonumber) | reverse | .[:5][] | "  \(.player_name): \(.pts) pts"' "$sample_file" 2>/dev/null || echo "  No scoring data available"
    
    echo ""
    echo -e "${GREEN}DNP reasons (if available):${NC}"
    jq -r '.players | map(select(.status == "DNP" and .dnp_reason != null)) | group_by(.dnp_reason) | map({reason: .[0].dnp_reason, count: length}) | .[] | "  \(.reason): \(.count) players"' "$sample_file" 2>/dev/null || echo "  No DNP reason data available"
    
    rm -f "$sample_file"
}

# Game information analysis
cmd_game_info() {
    print_header
    echo -e "${BLUE}🏀 Game Information Analysis:${NC}"
    echo ""
    
    local sample_file=$(get_sample_file)
    if [[ -z "$sample_file" ]]; then
        echo "Could not download sample file"
        return 1
    fi
    
    echo -e "${GREEN}Basic game info:${NC}"
    jq -r '.game_info | 
        "  Date: \(.date // "Unknown")",
        "  Arena: \(.arena // "Unknown")",
        "  Attendance: \(.attendance // "Unknown")",
        "  Home Team: \(.home_team // "Unknown")",
        "  Away Team: \(.away_team // "Unknown")",
        "  Officials: \(.officials // "Unknown")"
    ' "$sample_file"
    
    echo ""
    echo -e "${GREEN}Score information (if available):${NC}"
    jq -r '.game_info | 
        if .home_score and .away_score then
            "  Final Score: \(.away_team) \(.away_score) - \(.home_team) \(.home_score)"
        else
            "  Score data not available"
        end
    ' "$sample_file"
    
    echo ""
    echo -e "${GREEN}Team rosters:${NC}"
    jq -r '
        .players | group_by(.team) | map({team: .[0].team, count: length}) | .[] | "  \(.team): \(.count) players"
    ' "$sample_file" 2>/dev/null || echo "  Team information not available"
    
    rm -f "$sample_file"
}

# Data quality analysis
cmd_quality() {
    print_header
    echo -e "${BLUE}✅ Data Quality Analysis:${NC}"
    echo ""
    
    local sample_file=$(get_sample_file)
    if [[ -z "$sample_file" ]]; then
        echo "Could not download sample file"
        return 1
    fi
    
    echo -e "${GREEN}Data completeness:${NC}"
    jq -r '
        .players | length as $total |
        (.players | map(select(.player_name != null and .player_name != "")) | length) as $named |
        (.players | map(select(.status != null and .status != "")) | length) as $with_status |
        (.players | map(select(.team != null and .team != "")) | length) as $with_team |
        (.players | map(select(.position != null and .position != "")) | length) as $with_pos |
        "  Total players: \($total)",
        "  With names: \($named) (\(($named * 100 / $total) | floor)%)",
        "  With status: \($with_status) (\(($with_status * 100 / $total) | floor)%)",
        "  With team: \($with_team) (\(($with_team * 100 / $total) | floor)%)",
        "  With position: \($with_pos) (\(($with_pos * 100 / $total) | floor)%)"
    ' "$sample_file"
    
    echo ""
    echo -e "${GREEN}Statistical data availability:${NC}"
    jq -r '
        .players | length as $total |
        (.players | map(select(.pts != null and .pts != "")) | length) as $pts |
        (.players | map(select(.min != null and .min != "")) | length) as $min |
        (.players | map(select(.fg != null and .fg != "")) | length) as $fg |
        (.players | map(select(.three_pt != null and .three_pt != "")) | length) as $three |
        (.players | map(select(.ft != null and .ft != "")) | length) as $ft |
        "  Points: \($pts) (\(($pts * 100 / $total) | floor)%)",
        "  Minutes: \($min) (\(($min * 100 / $total) | floor)%)",
        "  Field goals: \($fg) (\(($fg * 100 / $total) | floor)%)",
        "  Three pointers: \($three) (\(($three * 100 / $total) | floor)%)",
        "  Free throws: \($ft) (\(($ft * 100 / $total) | floor)%)"
    ' "$sample_file"
    
    echo ""
    echo -e "${GREEN}Data anomalies:${NC}"
    jq -r '
        (.players | map(select(.player_name == null or .player_name == "")) | length) as $missing_names |
        (.players | map(select(.status == null or .status == "")) | length) as $missing_status |
        (.players | map(select(.team == null or .team == "")) | length) as $missing_team |
        if $missing_names > 0 then "  ⚠️  \($missing_names) players missing names" else "  ✅ All players have names" end,
        if $missing_status > 0 then "  ⚠️  \($missing_status) players missing status" else "  ✅ All players have status" end,
        if $missing_team > 0 then "  ⚠️  \($missing_team) players missing team" else "  ✅ All players have team" end
    ' "$sample_file"
    
    rm -f "$sample_file"
}

# Advanced statistical queries
cmd_advanced() {
    print_header
    echo -e "${BLUE}📊 Advanced Statistical Analysis:${NC}"
    echo ""
    
    local sample_file=$(get_sample_file)
    if [[ -z "$sample_file" ]]; then
        echo "Could not download sample file"
        return 1
    fi
    
    echo -e "${GREEN}Position distribution:${NC}"
    jq -r '.players | map(select(.position != null and .position != "")) | group_by(.position) | map({pos: .[0].position, count: length}) | sort_by(.count) | reverse | .[] | "  \(.pos): \(.count) players"' "$sample_file" 2>/dev/null || echo "  Position data not available"
    
    echo ""
    echo -e "${GREEN}Minutes played distribution (active players):${NC}"
    jq -r '
        .players | map(select(.status == "ACTIVE" and .min != null and .min != "")) | 
        map(.min | tonumber) | sort | 
        length as $count |
        if $count > 0 then
            (add / length) as $avg |
            .[0] as $min |
            .[$count-1] as $max |
            "  Active players with minutes: \($count)",
            "  Average minutes: \($avg | floor)",
            "  Range: \($min) - \($max) minutes"
        else
            "  No minutes data available"
        end
    ' "$sample_file" 2>/dev/null || echo "  Minutes data not available"
    
    echo ""
    echo -e "${GREEN}Scoring distribution (players with stats):${NC}"
    jq -r '
        .players | map(select(.pts != null and .pts != "")) | map(.pts | tonumber) | sort |
        length as $count |
        if $count > 0 then
            (add / length) as $avg |
            .[0] as $min |
            .[$count-1] as $max |
            "  Players with points: \($count)",
            "  Average points: \($avg | floor)",
            "  Range: \($min) - \($max) points"
        else
            "  No scoring data available"
        end
    ' "$sample_file" 2>/dev/null || echo "  Scoring data not available"
    
    rm -f "$sample_file"
}

# Custom jq query interface
cmd_custom() {
    local query="$1"
    
    if [[ -z "$query" ]]; then
        echo "Usage: $0 custom 'jq_query'"
        echo ""
        echo "Examples:"
        echo "  $0 custom '.players | length'"
        echo "  $0 custom '.players | map(select(.pts != null)) | length'"
        echo "  $0 custom '.game_info.arena'"
        return 1
    fi
    
    print_header
    echo -e "${BLUE}🔧 Custom JQ Query:${NC}"
    echo -e "Query: ${YELLOW}$query${NC}"
    echo ""
    
    local sample_file=$(get_sample_file)
    if [[ -z "$sample_file" ]]; then
        echo "Could not download sample file"
        return 1
    fi
    
    echo -e "${GREEN}Result:${NC}"
    if jq -r "$query" "$sample_file" 2>/dev/null; then
        echo ""
        echo -e "${GREEN}✅ Query executed successfully${NC}"
    else
        echo -e "${RED}❌ Query failed - check syntax${NC}"
    fi
    
    rm -f "$sample_file"
}

# Multi-file analysis (downloads multiple files)
cmd_multi() {
    local count=${1:-5}
    
    print_header
    echo -e "${BLUE}📁 Multi-file Analysis ($count files):${NC}"
    echo ""
    
    # Get recent files
    local files=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" --long --format="value(name,timeCreated)" 2>/dev/null | \
        grep "\.json" | sort -k2 -r | head -$count | awk '{print $1}' | sed "s|^|gs://nba-scraped-data/|")
    
    if [[ -z "$files" ]]; then
        echo "No files found"
        return 1
    fi
    
    local temp_dir="/tmp/nba_multi_$(date +%s)"
    mkdir -p "$temp_dir"
    
    echo "Downloading $count files for analysis..."
    
    local file_count=0
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_count=$((file_count + 1))
            local temp_file="$temp_dir/game_${file_count}.json"
            
            if gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
                echo "  Downloaded file $file_count"
            fi
        fi
    done <<< "$files"
    
    echo ""
    echo -e "${GREEN}Cross-game analysis:${NC}"
    
    # Combine all files into a single analysis
    jq -s '
        map(.players | length) as $player_counts |
        map(.players | map(select(.status == "ACTIVE")) | length) as $active_counts |
        map(.game_info.arena // "Unknown") as $arenas |
        {
            games_analyzed: length,
            avg_players_per_game: ($player_counts | add / length | floor),
            avg_active_per_game: ($active_counts | add / length | floor),
            unique_arenas: ($arenas | unique | length),
            arena_list: ($arenas | unique)
        }
    ' "$temp_dir"/*.json 2>/dev/null | jq -r '
        "  Games analyzed: \(.games_analyzed)",
        "  Avg players per game: \(.avg_players_per_game)",
        "  Avg active per game: \(.avg_active_per_game)",
        "  Unique arenas: \(.unique_arenas)",
        "  Arenas: \(.arena_list | join(", "))"
    '
    
    # Clean up
    rm -rf "$temp_dir"
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  structure              - Analyze JSON structure"
    echo "  players               - Player statistics analysis"
    echo "  game                  - Game information analysis"
    echo "  quality               - Data quality assessment"
    echo "  advanced              - Advanced statistical analysis"
    echo "  custom 'query'        - Run custom jq query"
    echo "  multi [N]             - Multi-file analysis (N files)"
    echo ""
    echo "Examples:"
    echo "  $0 structure          - Show JSON structure"
    echo "  $0 players            - Analyze player data"
    echo "  $0 quality            - Check data quality"
    echo "  $0 custom '.players | length'  - Count players"
    echo "  $0 multi 10           - Analyze 10 recent files"
}

# Main command handling
case "${1:-help}" in
    "structure")
        cmd_structure
        ;;
    "players")
        cmd_player_stats
        ;;
    "game")
        cmd_game_info
        ;;
    "quality")
        cmd_quality
        ;;
    "advanced")
        cmd_advanced
        ;;
    "custom")
        cmd_custom "$2"
        ;;
    "multi")
        cmd_multi "${2:-5}"
        ;;
    "help"|"-h"|"--help"|"")
        show_usage
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac