#!/bin/bash
# File: bin/validation/validate_br_rosters.sh
# Purpose: Basketball Reference roster data validation wrapper
# Usage: ./bin/validation/validate_br_rosters.sh [options]
# Deploy with: backfill/br_rosters/deploy_br_rosters_backfill.sh

set -euo pipefail

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_VALIDATOR="${PROJECT_ROOT}/bin/validation/validate_br_rosters.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}🏀 BASKETBALL REFERENCE ROSTER VALIDATION${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo ""
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  quick          - Quick validation (2 sample teams, current season)"
    echo "  sample         - Sample validation (5 teams, current season)"  
    echo "  full           - Full validation (all 30 teams, current season)"
    echo "  all-seasons    - All seasons, sample teams"
    echo "  comprehensive  - All seasons, all teams (complete validation)"
    echo ""
    echo "Direct Options (passed to Python validator):"
    echo "  --seasons YEARS    - Comma-separated years (e.g., 2024,2025)"
    echo "  --teams TEAMS      - Comma-separated team abbreviations"
    echo "  --all-teams        - Validate all 30 teams"
    echo "  --quick           - Quick mode (LAL,MEM only)"
    echo "  --verbose         - Detailed output"
    echo "  --show-jq         - Show jq analysis output"
    echo "  --jq-only         - Only run jq commands"
    echo "  --output FILE     - Save results to JSON file"
    echo ""
    echo "Examples:"
    echo "  $0 quick                           # Quick check (2 teams, 2025)"
    echo "  $0 full                            # All teams, current season"
    echo "  $0 --seasons 2024,2025 --verbose  # Custom seasons with details"
    echo "  $0 comprehensive                   # Complete validation (all teams, all seasons)"
    echo ""
    echo "Data Analysis:"
    echo "  $0 --seasons 2024 --show-jq       # Include jq analysis output"
    echo "  $0 --seasons 2024 --jq-only       # Only jq analysis (no Python)"
}

# Check if Python validator exists
check_validator() {
    if [[ ! -f "$PYTHON_VALIDATOR" ]]; then
        echo -e "${RED}❌ Error: Python validator not found at: $PYTHON_VALIDATOR${NC}"
        echo -e "${YELLOW}Expected location: scripts/validate_br_data.py${NC}"
        exit 1
    fi
}

# Get current season (ending year)
get_current_season() {
    local current_year=$(date +%Y)
    local current_month=$(date +%m)
    
    # NBA season spans two calendar years, season name is the ending year
    # Season starts in October, so if we're before October, use current year
    # If October or later, use next year
    if [[ $current_month -ge 10 ]]; then
        echo $((current_year + 1))
    else
        echo $current_year
    fi
}

# Predefined validation modes
cmd_quick() {
    local season=$(get_current_season)
    echo -e "${BLUE}🚀 Quick Validation - 2 teams, season $season${NC}"
    echo ""
    python3 "$PYTHON_VALIDATOR" --seasons "$season" --quick "$@"
}

cmd_sample() {
    local season=$(get_current_season)
    echo -e "${BLUE}🚀 Sample Validation - 5 teams, season $season${NC}"
    echo ""
    python3 "$PYTHON_VALIDATOR" --seasons "$season" "$@"
}

cmd_full() {
    local season=$(get_current_season)
    echo -e "${BLUE}🚀 Full Validation - All 30 teams, season $season${NC}"
    echo ""
    python3 "$PYTHON_VALIDATOR" --seasons "$season" --all-teams "$@"
}

cmd_all_seasons() {
    echo -e "${BLUE}🚀 All Seasons Validation - Sample teams, 4 seasons${NC}"
    echo ""
    python3 "$PYTHON_VALIDATOR" --seasons "2022,2023,2024,2025" "$@"
}

cmd_comprehensive() {
    echo -e "${BLUE}🚀 Comprehensive Validation - All teams, all seasons${NC}"
    echo -e "${YELLOW}⚠️  This will analyze 120 files (30 teams × 4 seasons)${NC}"
    echo ""
    read -p "Continue? (y/N): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
    echo ""
    python3 "$PYTHON_VALIDATOR" --seasons "2022,2023,2024,2025" --all-teams --verbose "$@"
}

# Main execution
main() {
    print_header
    check_validator
    
    if [[ $# -eq 0 ]]; then
        show_usage
        exit 0
    fi
    
    case "$1" in
        "quick")
            shift
            cmd_quick "$@"
            ;;
        "sample")
            shift
            cmd_sample "$@"
            ;;
        "full")
            shift
            cmd_full "$@"
            ;;
        "all-seasons")
            shift
            cmd_all_seasons "$@"
            ;;
        "comprehensive")
            shift
            cmd_comprehensive "$@"
            ;;
        "help"|"-h"|"--help")
            show_usage
            ;;
        --*)
            # Direct pass-through to Python validator
            echo -e "${BLUE}🚀 Custom Validation${NC}"
            echo ""
            python3 "$PYTHON_VALIDATOR" "$@"
            ;;
        *)
            echo -e "${RED}❌ Unknown command: $1${NC}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Check dependencies
check_dependencies() {
    # Check Python 3
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ Error: python3 not found${NC}"
        exit 1
    fi
    
    # Check gcloud (used by Python validator)
    if ! command -v gcloud &> /dev/null; then
        echo -e "${RED}❌ Error: gcloud CLI not found${NC}"
        echo -e "${YELLOW}Install from: https://cloud.google.com/sdk/docs/install${NC}"
        exit 1
    fi
    
    # Check jq (used by Python validator for analysis)
    if ! command -v jq &> /dev/null; then
        echo -e "${YELLOW}⚠️  Warning: jq not found (required for --show-jq and --jq-only modes)${NC}"
        echo -e "${YELLOW}Install with: brew install jq (macOS) or apt-get install jq (Ubuntu)${NC}"
    fi
}

# Run dependency check first
check_dependencies

# Execute main function
main "$@"

# Capture exit code from Python validator
exit_code=$?

if [[ $exit_code -eq 0 ]]; then
    echo -e "\n${GREEN}✅ Validation completed successfully${NC}"
else
    echo -e "\n${RED}❌ Validation completed with issues (exit code: $exit_code)${NC}"
fi

exit $exit_code