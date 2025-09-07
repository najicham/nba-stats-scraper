#!/bin/bash
# File: bin/monitoring/test_single_game.sh
# Purpose: Test single game download to validate entire pipeline before full backfill
# Tests: Direct scraper service call, file creation, JSON data quality

# Test Single Game Download
# This script tests the entire pipeline with a single game

PROJECT="nba-props-platform"
REGION="us-west2"
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
BUCKET="gs://nba-scraped-data"

# Test game from April 10, 2024 (MEM @ CLE)
TEST_GAME="20240410/MEMCLE"
TEST_DATE="2024-04-10"

echo "🧪 Testing single game download: $TEST_GAME"
echo "================================================"

echo "1️⃣  Testing scraper service directly..."
curl -X POST "${SERVICE_URL}/scrape" \
    -H "Content-Type: application/json" \
    -d "{\"scraper\": \"nbac_gamebook_pdf\", \"game_code\": \"${TEST_GAME}\", \"version\": \"short\", \"group\": \"prod\"}" \
    -w "\nHTTP Status: %{http_code}\n" \
    -s

echo ""
echo "2️⃣  Checking if files were created..."

# Check for PDF
PDF_PATH="${BUCKET}/nba-com/gamebooks-pdf/${TEST_DATE}/game_${TEST_GAME//\//_}/"
echo "PDF location: $PDF_PATH"
gsutil ls "${PDF_PATH}" 2>/dev/null && echo "✅ PDF found" || echo "❌ PDF not found"

# Check for JSON
JSON_PATH="${BUCKET}/nba-com/gamebooks-data/${TEST_DATE}/game_${TEST_GAME//\//_}/"
echo "JSON location: $JSON_PATH"
gsutil ls "${JSON_PATH}" 2>/dev/null && echo "✅ JSON found" || echo "❌ JSON not found"

echo ""
echo "3️⃣  Validating JSON data quality..."

# Download and inspect the JSON file
if gsutil ls "${JSON_PATH}*.json" &>/dev/null; then
    TEMP_FILE="/tmp/test_game.json"
    JSON_FILE=$(gsutil ls "${JSON_PATH}*.json" | head -1)
    gsutil cp "$JSON_FILE" "$TEMP_FILE" 2>/dev/null
    
    if [[ -f "$TEMP_FILE" ]]; then
        # Check file size
        SIZE=$(stat -f%z "$TEMP_FILE" 2>/dev/null || stat -c%s "$TEMP_FILE" 2>/dev/null)
        echo "File size: ${SIZE} bytes"
        
        # Check JSON structure
        if command -v jq &> /dev/null; then
            echo "Player counts:"
            jq -r '.players | length as $total | 
                   [.[] | select(.status == "ACTIVE")] | length as $active |
                   [.[] | select(.status == "DNP")] | length as $dnp |
                   [.[] | select(.status == "INACTIVE")] | length as $inactive |
                   "  Active: \($active), DNP: \($dnp), Inactive: \($inactive), Total: \($total)"' "$TEMP_FILE" 2>/dev/null || echo "  Could not parse player data"
            
            echo "Sample active player:"
            jq -r '.players[] | select(.status == "ACTIVE") | "  \(.player_name): \(.pts) pts, \(.min) min"' "$TEMP_FILE" 2>/dev/null | head -1 || echo "  Could not find active player"
            
            echo "Sample DNP player:"
            jq -r '.players[] | select(.status == "DNP") | "  \(.player_name): \(.dnp_reason // "No reason")"' "$TEMP_FILE" 2>/dev/null | head -1 || echo "  Could not find DNP player"
        else
            echo "Install 'jq' for detailed JSON analysis"
        fi
        
        rm "$TEMP_FILE"
    fi
else
    echo "❌ No JSON file found for validation"
fi

echo ""
echo "4️⃣  Testing with Python validation script..."

if [[ -f "scripts/validate_gamebook_data.py" ]]; then
    python scripts/validate_gamebook_data.py --game-code "$TEST_GAME" 2>/dev/null || echo "Python validation failed"
else
    echo "Python validation script not found"
fi

echo ""
echo "================================================"
echo "✅ Single game test complete!"
echo ""
echo "If everything looks good above, you can proceed with:"
echo "  1. Run deployment: ./deploy_gamebook_job.sh"
echo "  2. Start monitoring: ./monitor_backfill.sh --continuous"
echo "  3. Execute full backfill: gcloud run jobs execute nba-gamebook-backfill --region=us-west2"