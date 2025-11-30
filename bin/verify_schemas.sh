#!/bin/bash
# ============================================================================
# Schema Verification Script
# ============================================================================
# Purpose: Verify that all production BigQuery tables have schema files
# Usage: ./bin/verify_schemas.sh
# Exit Codes:
#   0 = All production tables have schemas
#   1 = Some production tables missing schemas
#   2 = Script error
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 Schema Verification"
echo "================================================================================

"

# Check if Python script exists
if [ ! -f "$PROJECT_ROOT/scripts/schema_verification_quick.py" ]; then
    echo "❌ Error: schema_verification_quick.py not found"
    exit 2
fi

# Run Python verification script
cd "$PROJECT_ROOT"
if python3 scripts/schema_verification_quick.py; then
    echo ""
    echo "================================================================================
"
    echo "✅ SUCCESS: All production tables have schema files!"
    echo "================================================================================
"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo "================================================================================
"
    echo "⚠️  Some tables are missing schema files (see above for details)"
    echo ""
    echo "NOTE: Temp/test/backup tables (with _temp_, _backup_, _FIXED, _test_ in name)"
    echo "      are expected to not have schemas and can be ignored."
    echo ""
    echo "To generate missing schemas for production tables:"
    echo "  python3 scripts/generate_missing_schemas.py"
    echo "================================================================================
"
    exit $EXIT_CODE
fi
