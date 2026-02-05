#!/bin/bash
#
# Game Code Validator
#
# Validates that game codes follow the correct format: YYYYMMDD/TEAMTEAM
# where TEAM is exactly 3 uppercase letters
#
# Usage:
#   ./bin/validate_game_codes.sh "20260204/OKCSAS"
#   ./bin/validate_game_codes.sh --file game_codes.txt
#
# Returns: 0 if all valid, 1 if any invalid

set -e

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Game code pattern: YYYYMMDD/XXXXXX (8 digits + slash + 6 uppercase letters)
PATTERN='^[0-9]{8}/[A-Z]{6}$'

# Known NBA team codes (30 teams)
NBA_TEAMS=(
  "ATL" "BOS" "BKN" "CHA" "CHI" "CLE" "DAL" "DEN" "DET" "GSW"
  "HOU" "IND" "LAC" "LAL" "MEM" "MIA" "MIL" "MIN" "NOP" "NYK"
  "OKC" "ORL" "PHI" "PHX" "POR" "SAC" "SAS" "TOR" "UTA" "WAS"
)

validate_game_code() {
  local code="$1"
  local errors=()

  # Check basic format
  if ! [[ $code =~ $PATTERN ]]; then
    errors+=("Format must be YYYYMMDD/TEAMTEAM (8 digits + slash + 6 uppercase letters)")
  fi

  # Check if we can extract date and teams
  if [[ $code =~ ^([0-9]{8})/([A-Z]{3})([A-Z]{3})$ ]]; then
    local date="${BASH_REMATCH[1]}"
    local away="${BASH_REMATCH[2]}"
    local home="${BASH_REMATCH[3]}"

    # Validate date format
    local year="${date:0:4}"
    local month="${date:4:2}"
    local day="${date:6:2}"

    if [ "$year" -lt 2000 ] || [ "$year" -gt 2100 ]; then
      errors+=("Year must be between 2000-2100, got: $year")
    fi

    if [ "$month" -lt 1 ] || [ "$month" -gt 12 ]; then
      errors+=("Month must be 01-12, got: $month")
    fi

    if [ "$day" -lt 1 ] || [ "$day" -gt 31 ]; then
      errors+=("Day must be 01-31, got: $day")
    fi

    # Validate team codes
    if [[ ! " ${NBA_TEAMS[@]} " =~ " ${away} " ]]; then
      errors+=("Unknown away team code: $away (must be one of: ${NBA_TEAMS[*]})")
    fi

    if [[ ! " ${NBA_TEAMS[@]} " =~ " ${home} " ]]; then
      errors+=("Unknown home team code: $home (must be one of: ${NBA_TEAMS[*]})")
    fi

    # Check for same team (can't play itself)
    if [ "$away" == "$home" ]; then
      errors+=("Away and home teams cannot be the same: $away")
    fi
  fi

  # Report results
  if [ ${#errors[@]} -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Valid: $code"
    return 0
  else
    echo -e "${RED}✗${NC} Invalid: $code"
    for error in "${errors[@]}"; do
      echo -e "  ${RED}→${NC} $error"
    done
    return 1
  fi
}

# Main script logic
main() {
  local all_valid=0

  if [ $# -eq 0 ]; then
    echo "Usage: $0 <game_code> [game_code...]"
    echo "   or: $0 --file <file_with_game_codes>"
    exit 1
  fi

  if [ "$1" == "--file" ]; then
    if [ ! -f "$2" ]; then
      echo -e "${RED}Error:${NC} File not found: $2"
      exit 1
    fi

    echo "Validating game codes from: $2"
    echo ""

    while IFS= read -r code; do
      # Skip empty lines and comments
      [[ -z "$code" || "$code" =~ ^# ]] && continue

      if ! validate_game_code "$code"; then
        all_valid=1
      fi
    done < "$2"
  else
    # Validate codes from arguments
    for code in "$@"; do
      if ! validate_game_code "$code"; then
        all_valid=1
      fi
    done
  fi

  echo ""
  if [ $all_valid -eq 0 ]; then
    echo -e "${GREEN}All game codes are valid!${NC}"
  else
    echo -e "${RED}Some game codes are invalid.${NC}"
  fi

  return $all_valid
}

main "$@"
