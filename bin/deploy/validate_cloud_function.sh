#!/bin/bash
# Validate Cloud Function Before Deployment
#
# This script validates a cloud function's code before deployment by:
# 1. Checking that all Python imports resolve
# 2. Running a syntax check
# 3. Verifying required files exist
# 4. Testing the entry point is importable
#
# Usage:
#   ./bin/deploy/validate_cloud_function.sh daily_health_summary
#   ./bin/deploy/validate_cloud_function.sh news_fetcher
#   ./bin/deploy/validate_cloud_function.sh grading
#
# This prevents deployment failures from:
# - Import errors (missing modules, circular imports)
# - Syntax errors
# - Missing shared dependencies
# - Logger before defined errors

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check argument
if [ -z "$1" ]; then
    echo -e "${RED}Error: Function name required${NC}"
    echo ""
    echo "Usage: $0 <function_name>"
    echo ""
    echo "Available functions:"
    ls -d orchestration/cloud_functions/*/ 2>/dev/null | xargs -n1 basename
    exit 1
fi

FUNCTION_NAME="$1"
SOURCE_DIR="orchestration/cloud_functions/${FUNCTION_NAME}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Cloud Function Pre-Deploy Validation${NC}"
echo -e "${BLUE}Function: ${FUNCTION_NAME}${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Track validation results
ERRORS=0
WARNINGS=0

# Function to log errors
log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
    ERRORS=$((ERRORS + 1))
}

# Function to log warnings
log_warning() {
    echo -e "${YELLOW}[WARN]  $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

# Function to log success
log_success() {
    echo -e "${GREEN}[OK]    $1${NC}"
}

# ============================================================
# 1. Check source directory exists
# ============================================================
echo -e "${YELLOW}1. Checking source directory...${NC}"

if [ ! -d "$SOURCE_DIR" ]; then
    log_error "Source directory not found: $SOURCE_DIR"
    echo ""
    echo "Available functions:"
    ls -d orchestration/cloud_functions/*/ 2>/dev/null | xargs -n1 basename
    exit 1
fi
log_success "Source directory exists: $SOURCE_DIR"

# ============================================================
# 2. Check required files
# ============================================================
echo ""
echo -e "${YELLOW}2. Checking required files...${NC}"

if [ ! -f "$SOURCE_DIR/main.py" ]; then
    log_error "main.py not found"
else
    log_success "main.py found"
fi

if [ ! -f "$SOURCE_DIR/requirements.txt" ]; then
    log_error "requirements.txt not found"
else
    log_success "requirements.txt found"
fi

# ============================================================
# 3. Validate Python syntax
# ============================================================
echo ""
echo -e "${YELLOW}3. Validating Python syntax...${NC}"

# Check syntax of main.py
if python -m py_compile "$SOURCE_DIR/main.py" 2>&1; then
    log_success "main.py syntax OK"
else
    log_error "main.py has syntax errors"
fi

# Check syntax of any other .py files in the directory
for pyfile in $(find "$SOURCE_DIR" -maxdepth 1 -name "*.py" -not -name "main.py" 2>/dev/null); do
    if python -m py_compile "$pyfile" 2>&1; then
        log_success "$(basename $pyfile) syntax OK"
    else
        log_error "$(basename $pyfile) has syntax errors"
    fi
done

# ============================================================
# 4. Test imports resolve
# ============================================================
echo ""
echo -e "${YELLOW}4. Testing import resolution...${NC}"

# Create a temp directory simulating the deployment package
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

# Copy function files
cp "$SOURCE_DIR/main.py" "${TEMP_DIR}/"

# Copy shared module (same as deploy script)
REPO_ROOT="$(pwd)"
cp -r "$REPO_ROOT/shared" "${TEMP_DIR}/"

# Remove __pycache__ to avoid stale imports
find "${TEMP_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Try to import the main module
echo "  Testing import of main module..."
IMPORT_TEST=$(cd "${TEMP_DIR}" && PYTHONPATH=. python -c "
import sys
try:
    import main
    print('SUCCESS')
except ImportError as e:
    print(f'IMPORT_ERROR: {e}')
except Exception as e:
    print(f'ERROR: {type(e).__name__}: {e}')
" 2>&1)

if [[ "$IMPORT_TEST" == "SUCCESS" ]]; then
    log_success "main module imports successfully"
else
    log_error "Import failed: $IMPORT_TEST"
fi

# ============================================================
# 5. Check for common issues
# ============================================================
echo ""
echo -e "${YELLOW}5. Checking for common issues...${NC}"

# Check for logger before defined (common issue)
if grep -n "logger\." "$SOURCE_DIR/main.py" | head -1 | grep -q '^[0-9]*:'; then
    FIRST_LOGGER=$(grep -n "logger\." "$SOURCE_DIR/main.py" | head -1 | cut -d: -f1)
    LOGGER_DEF=$(grep -n "logger = " "$SOURCE_DIR/main.py" | head -1 | cut -d: -f1)

    if [ -n "$FIRST_LOGGER" ] && [ -n "$LOGGER_DEF" ]; then
        if [ "$FIRST_LOGGER" -lt "$LOGGER_DEF" ]; then
            log_error "logger used on line $FIRST_LOGGER before defined on line $LOGGER_DEF"
        else
            log_success "logger defined before use"
        fi
    fi
fi

# Check for hardcoded secrets
if grep -qE "(sk-|api_key|password|secret)" "$SOURCE_DIR/main.py" 2>/dev/null; then
    log_warning "Potential hardcoded secret found in main.py"
else
    log_success "No obvious hardcoded secrets"
fi

# Check requirements.txt has entries
if [ -f "$SOURCE_DIR/requirements.txt" ]; then
    REQ_COUNT=$(grep -c -v "^#" "$SOURCE_DIR/requirements.txt" 2>/dev/null || echo "0")
    REQ_COUNT=$(echo "$REQ_COUNT" | tr -d ' ')
    if [ "$REQ_COUNT" -gt 0 ]; then
        log_success "requirements.txt has $REQ_COUNT dependencies"
    else
        log_warning "requirements.txt appears empty"
    fi
fi

# ============================================================
# 6. Check shared module dependencies
# ============================================================
echo ""
echo -e "${YELLOW}6. Checking shared module dependencies...${NC}"

# Extract imports from main.py
SHARED_IMPORTS=$(grep -E "^from shared\." "$SOURCE_DIR/main.py" 2>/dev/null || true)

if [ -n "$SHARED_IMPORTS" ]; then
    echo "  Found shared imports:"
    while IFS= read -r line; do
        # Extract module path from import
        MODULE_PATH=$(echo "$line" | sed 's/from //' | sed 's/ import.*//' | tr '.' '/')
        EXPECTED_FILE="$REPO_ROOT/${MODULE_PATH}.py"
        EXPECTED_DIR="$REPO_ROOT/${MODULE_PATH}/__init__.py"

        if [ -f "$EXPECTED_FILE" ] || [ -f "$EXPECTED_DIR" ]; then
            log_success "$MODULE_PATH exists"
        else
            log_error "$MODULE_PATH not found (expected $EXPECTED_FILE)"
        fi
    done <<< "$SHARED_IMPORTS"
else
    log_success "No shared module imports"
fi

# ============================================================
# 7. Entry point check
# ============================================================
echo ""
echo -e "${YELLOW}7. Checking entry point...${NC}"

# Extract entry point from deploy script if it exists
DEPLOY_SCRIPT="bin/deploy/deploy_${FUNCTION_NAME}.sh"
if [ -f "$DEPLOY_SCRIPT" ]; then
    ENTRY_POINT=$(grep "ENTRY_POINT=" "$DEPLOY_SCRIPT" | head -1 | cut -d'"' -f2)
    if [ -n "$ENTRY_POINT" ]; then
        # Check if entry point exists in main.py
        if grep -qE "^def ${ENTRY_POINT}\(" "$SOURCE_DIR/main.py"; then
            log_success "Entry point '$ENTRY_POINT' found in main.py"
        else
            log_error "Entry point '$ENTRY_POINT' not found in main.py"
        fi
    fi
else
    log_warning "Deploy script not found at $DEPLOY_SCRIPT - cannot verify entry point"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Validation Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}All checks passed! Function is ready for deployment.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}Validation completed with $WARNINGS warning(s)${NC}"
    echo -e "${YELLOW}Function can be deployed but review warnings above.${NC}"
    exit 0
else
    echo -e "${RED}Validation failed with $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo -e "${RED}Fix errors before deploying.${NC}"
    exit 1
fi
