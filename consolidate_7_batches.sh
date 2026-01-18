#!/bin/bash
# Consolidate 7 December + January batches
# Auto-generated from regeneration output

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       CONSOLIDATING 7 BATCHES                                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Batch IDs from regeneration
BATCHES=(
  "batch_2025-12-05_1768698435:2025-12-05"
  "batch_2025-12-06_1768698776:2025-12-06"
  "batch_2025-12-07_1768699058:2025-12-07"
  "batch_2025-12-11_1768699337:2025-12-11"
  "batch_2025-12-13_1768699577:2025-12-13"
  "batch_2025-12-18_1768699801:2025-12-18"
  "batch_2026-01-10_1768700164:2026-01-10"
)

total=0
successful=0
failed=0

for batch_info in "${BATCHES[@]}"; do
  total=$((total + 1))
  batch_id=$(echo "$batch_info" | cut -d':' -f1)
  game_date=$(echo "$batch_info" | cut -d':' -f2)

  echo -e "${YELLOW}[$total/7] Consolidating $game_date ($batch_id)...${NC}"

  if python /home/naji/code/nba-stats-scraper/bin/predictions/consolidate/manual_consolidation.py \
    --batch-id "$batch_id" \
    --game-date "$game_date" \
    --no-cleanup 2>&1 | grep -E "(Found|MERGE|Consolidation|Rows affected)"; then
    successful=$((successful + 1))
    echo -e "  ${GREEN}✓ Success${NC}"
  else
    failed=$((failed + 1))
    echo -e "  ❌ Failed"
  fi
  echo ""
done

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              CONSOLIDATION COMPLETE                            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Summary:"
echo "  Total: $total"
echo "  Successful: $successful"
echo "  Failed: $failed"
echo ""
echo "Next: Validate final state (0 placeholders expected)"
