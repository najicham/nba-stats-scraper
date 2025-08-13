#!/bin/bash
# File: bin/monitoring/lib/utils.sh
# Purpose: Common utility functions

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}🏀 NBA BETTINGPROS DATA VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Events: $BUCKET/$BP_EVENTS_PATH/"
    echo -e "Props:  $BUCKET/$BP_PROPS_PATH/"
    echo ""
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  test           - Basic test of GCS access and file validation"
    echo "  summary        - Schedule-aware overview of data completeness"
    echo "  missing        - Smart analysis of the 14 known missing dates using NBA schedule"
    echo "  recent [N]     - Validate N most recent dates (default: 3)"
    echo "  dates DATE ... - Validate specific dates (YYYY-MM-DD format)"
    echo "  debug [DATE]   - Debug schedule data parsing for specific date"
    echo ""
    echo "Examples:"
    echo "  $0 test                    - Test basic functionality"
    echo "  $0 summary                 - Quick schedule-aware data overview"
    echo "  $0 missing                 - Smart analysis: preseason vs actual missing"
    echo "  $0 recent 5                - Check 5 most recent dates"
    echo "  $0 dates 2021-10-19       - Check specific date"
    echo "  $0 debug 2021-10-03       - Debug schedule parsing issues"
    echo ""
    echo "🧠 Schedule-Aware Features:"
    echo "  ✅ Distinguishes preseason from regular season games"
    echo "  ✅ Identifies All-Star and special events (no props expected)"
    echo "  ✅ Shows true completion rate (regular season only)"
    echo "  ✅ Only flags actual missing data needing attention"
}

# Cleanup function for temporary files
cleanup_temp_files() {
    if [[ -d "$SCHEDULE_CACHE_DIR" ]]; then
        rm -rf "$SCHEDULE_CACHE_DIR"
    fi
}

# Get file size in a Mac-compatible way
get_file_size() {
    local file="$1"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        stat -f%z "$file" 2>/dev/null || echo "0"
    else
        stat -c%s "$file" 2>/dev/null || echo "0"
    fi
}