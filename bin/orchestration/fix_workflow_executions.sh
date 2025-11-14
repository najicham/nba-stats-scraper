#!/bin/bash
# Fix workflow_executions.sql - Remove NOT NULL from ARRAY fields
# Save this as: bin/orchestration/fix_workflow_executions.sh

FILE="schemas/bigquery/nba_orchestration/workflow_executions.sql"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Fixing workflow_executions.sql"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ! -f "$FILE" ]; then
    echo "❌ Error: File not found: $FILE"
    exit 1
fi

# Backup original
cp "$FILE" "${FILE}.backup"
echo "✅ Backup created: ${FILE}.backup"

# Fix the ARRAY field - remove NOT NULL
sed -i 's/scrapers_requested ARRAY<STRING> NOT NULL,/scrapers_requested ARRAY<STRING>,/' "$FILE"

echo "✅ Fixed ARRAY field constraint"
echo ""
echo "Changes made:"
echo "  BEFORE: scrapers_requested ARRAY<STRING> NOT NULL,"
echo "  AFTER:  scrapers_requested ARRAY<STRING>,"
echo ""
echo "Next: Deploy the table with:"
echo "  bq query --use_legacy_sql=false < $FILE"
