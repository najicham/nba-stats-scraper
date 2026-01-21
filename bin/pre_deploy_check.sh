#!/bin/bash
#
# Pre-Deployment Check Script
#
# Validates code quality, imports, and tests before deployment.
# Prevents deployment of broken code (like Jan 16-20 ModuleNotFoundError).
#
# Usage:
#   ./bin/pre_deploy_check.sh [--strict]
#
# Options:
#   --strict: Fail on any warning (not just errors)
#
# Exit codes:
#   0: All checks passed, safe to deploy
#   1: Critical checks failed, DO NOT deploy
#   2: Warnings present (deploy with caution)
#
# Created: 2026-01-21

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
STRICT_MODE=false
if [[ "$1" == "--strict" ]]; then
    STRICT_MODE=true
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Pre-Deployment Validation Check${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Track failures
CRITICAL_FAILURES=0
WARNINGS=0

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}Project root: ${PROJECT_ROOT}${NC}"
echo ""

# ============================================================================
# CHECK 1: Python syntax validation
# ============================================================================
echo -e "${BLUE}[1/6] Checking Python syntax...${NC}"

# Find all Python files (exclude venv and __pycache__)
PYTHON_FILES=$(find . -type f -name "*.py" \
    ! -path "./.venv/*" \
    ! -path "*/__pycache__/*" \
    ! -path "./.git/*")

SYNTAX_ERRORS=0
for file in $PYTHON_FILES; do
    if ! python -m py_compile "$file" 2>/dev/null; then
        echo -e "${RED}  ❌ Syntax error: $file${NC}"
        SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
done

if [ $SYNTAX_ERRORS -eq 0 ]; then
    echo -e "${GREEN}  ✅ All Python files have valid syntax${NC}"
else
    echo -e "${RED}  ❌ Found $SYNTAX_ERRORS syntax errors${NC}"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
echo ""

# ============================================================================
# CHECK 2: Critical imports validation
# ============================================================================
echo -e "${BLUE}[2/6] Validating critical imports...${NC}"

if [ -f "tests/test_critical_imports.py" ]; then
    if pytest tests/test_critical_imports.py -v --tb=short 2>&1 | tee /tmp/import_test_output.log; then
        echo -e "${GREEN}  ✅ All critical imports validated${NC}"
    else
        echo -e "${RED}  ❌ Import validation failed${NC}"
        echo -e "${RED}     Review /tmp/import_test_output.log for details${NC}"
        CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
    fi
else
    echo -e "${YELLOW}  ⚠️  Import test file not found (tests/test_critical_imports.py)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# ============================================================================
# CHECK 3: Requirements.txt consistency
# ============================================================================
echo -e "${BLUE}[3/6] Checking requirements.txt consistency...${NC}"

# Check if all imported packages are in requirements.txt
MISSING_DEPS=0

# Sample of critical packages that must be present
CRITICAL_PACKAGES=(
    "google-cloud-firestore"
    "google-cloud-pubsub"
    "google-cloud-bigquery"
    "functions-framework"
    "requests"
)

for pkg in "${CRITICAL_PACKAGES[@]}"; do
    if ! grep -q "^${pkg}" requirements.txt 2>/dev/null; then
        echo -e "${RED}  ❌ Missing critical package: $pkg${NC}"
        MISSING_DEPS=$((MISSING_DEPS + 1))
    fi
done

if [ $MISSING_DEPS -eq 0 ]; then
    echo -e "${GREEN}  ✅ All critical dependencies present in requirements.txt${NC}"
else
    echo -e "${RED}  ❌ Found $MISSING_DEPS missing critical dependencies${NC}"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
echo ""

# ============================================================================
# CHECK 4: Orchestration config validation
# ============================================================================
echo -e "${BLUE}[4/6] Validating orchestration configuration...${NC}"

# Check if orchestration_config can be imported
if python -c "from shared.config.orchestration_config import get_orchestration_config; get_orchestration_config()" 2>&1; then
    echo -e "${GREEN}  ✅ Orchestration config loads successfully${NC}"
else
    echo -e "${RED}  ❌ Orchestration config failed to load${NC}"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
echo ""

# ============================================================================
# CHECK 5: Processor name consistency
# ============================================================================
echo -e "${BLUE}[5/6] Checking processor name consistency...${NC}"

# Verify br_rosters_current (not br_roster) is used
if grep -r "br_roster['\"]" --include="*.py" \
    --exclude-dir=".venv" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".git" . 2>/dev/null | grep -v "br_rosters_current"; then
    echo -e "${RED}  ❌ Found references to 'br_roster' (should be 'br_rosters_current')${NC}"
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "${GREEN}  ✅ All processor names consistent${NC}"
fi
echo ""

# ============================================================================
# CHECK 6: Cloud Function entry points
# ============================================================================
echo -e "${BLUE}[6/6] Validating Cloud Function entry points...${NC}"

# Check that orchestrator main.py files have correct entry points
ORCHESTRATORS=(
    "orchestration/cloud_functions/phase2_to_phase3/main.py:orchestrate_phase2_to_phase3"
    "orchestration/cloud_functions/phase3_to_phase4/main.py:orchestrate_phase3_to_phase4"
    "orchestration/cloud_functions/phase4_to_phase5/main.py:orchestrate_phase4_to_phase5"
    "orchestration/cloud_functions/phase5_to_phase6/main.py:orchestrate_phase5_to_phase6"
)

MISSING_ENTRYPOINTS=0
for entry in "${ORCHESTRATORS[@]}"; do
    IFS=':' read -r filepath function_name <<< "$entry"
    if [ -f "$filepath" ]; then
        if grep -q "def ${function_name}" "$filepath"; then
            echo -e "${GREEN}  ✅ $function_name exists in $filepath${NC}"
        else
            echo -e "${RED}  ❌ Missing entry point: $function_name in $filepath${NC}"
            MISSING_ENTRYPOINTS=$((MISSING_ENTRYPOINTS + 1))
        fi
    else
        echo -e "${YELLOW}  ⚠️  File not found: $filepath${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
done

if [ $MISSING_ENTRYPOINTS -gt 0 ]; then
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Validation Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ $CRITICAL_FAILURES -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✅ ALL CHECKS PASSED${NC}"
        echo -e "${GREEN}   Safe to deploy!${NC}"
        exit 0
    else
        echo -e "${YELLOW}⚠️  WARNINGS PRESENT: $WARNINGS${NC}"
        if [ "$STRICT_MODE" = true ]; then
            echo -e "${RED}   Strict mode: Failing due to warnings${NC}"
            exit 2
        else
            echo -e "${YELLOW}   Deploy with caution (use --strict to block on warnings)${NC}"
            exit 0
        fi
    fi
else
    echo -e "${RED}❌ DEPLOYMENT BLOCKED${NC}"
    echo -e "${RED}   Critical failures: $CRITICAL_FAILURES${NC}"
    echo -e "${RED}   Warnings: $WARNINGS${NC}"
    echo ""
    echo -e "${RED}   DO NOT DEPLOY until all critical checks pass!${NC}"
    exit 1
fi
