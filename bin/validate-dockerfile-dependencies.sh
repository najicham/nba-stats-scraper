#!/bin/bash
#
# Dockerfile Dependency Validator
#
# Validates that all Python imports have corresponding COPY or pip install in Dockerfile.
# Prevents "silent failure" bugs where services import modules not included in the container.
#
# Usage:
#   ./bin/validate-dockerfile-dependencies.sh data_processors/grading/nba
#   ./bin/validate-dockerfile-dependencies.sh predictions/worker
#
# Exit codes:
#   0 - All dependencies validated
#   1 - Missing dependencies found
#   2 - Usage error

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 <service-directory>"
    echo ""
    echo "Examples:"
    echo "  $0 data_processors/grading/nba"
    echo "  $0 predictions/worker"
    echo "  $0 predictions/coordinator"
    exit 2
}

# Check arguments
if [ $# -ne 1 ]; then
    usage
fi

SERVICE_DIR="$1"

# Validate service directory exists
if [ ! -d "$SERVICE_DIR" ]; then
    echo -e "${RED}ERROR: Service directory not found: $SERVICE_DIR${NC}"
    exit 2
fi

# Find Dockerfile
DOCKERFILE="$SERVICE_DIR/Dockerfile"
if [ ! -f "$DOCKERFILE" ]; then
    echo -e "${RED}ERROR: Dockerfile not found: $DOCKERFILE${NC}"
    exit 2
fi

echo "=== Dockerfile Dependency Validation ==="
echo "Service: $SERVICE_DIR"
echo "Dockerfile: $DOCKERFILE"
echo ""

# Extract Python imports from service code (only internal modules)
echo "Analyzing Python imports..."
IMPORTS=$(find "$SERVICE_DIR" -name "*.py" -type f 2>/dev/null | \
    xargs grep -h "^import\|^from" 2>/dev/null | \
    sed 's/from \([^ ]*\).*/\1/' | \
    sed 's/import \([^ ]*\).*/\1/' | \
    grep -E "^(shared|predictions|data_processors|ml)" | \
    cut -d. -f1 | \
    sort -u || true)

if [ -z "$IMPORTS" ]; then
    echo -e "${GREEN}✓ No internal module imports found${NC}"
    exit 0
fi

echo "Found imports:"
echo "$IMPORTS" | sed 's/^/  - /'
echo ""

# Extract COPY commands from Dockerfile
echo "Analyzing Dockerfile COPY commands..."
COPIES=$(grep "^COPY" "$DOCKERFILE" | awk '{print $2}' | grep -v requirements || true)

if [ -z "$COPIES" ]; then
    echo -e "${YELLOW}⚠️  No COPY commands found in Dockerfile${NC}"
fi

echo "Found COPY commands:"
echo "$COPIES" | sed 's/^/  - /' || echo "  (none)"
echo ""

# Check for missing dependencies
missing=()
for import in $IMPORTS; do
    # Check if the base module is copied
    if ! echo "$COPIES" | grep -q "^$import"; then
        # Also check for patterns like "COPY ./shared shared/"
        if ! grep -q "COPY.*$import" "$DOCKERFILE"; then
            missing+=("$import")
        fi
    fi
done

# Report results
if [ ${#missing[@]} -gt 0 ]; then
    echo -e "${RED}❌ DOCKERFILE VALIDATION FAILED${NC}"
    echo ""
    echo "The following imports are used but not copied in Dockerfile:"
    for m in "${missing[@]}"; do
        echo -e "  ${RED}✗${NC} $m"
    done
    echo ""
    echo "Fix by adding to $DOCKERFILE:"
    for m in "${missing[@]}"; do
        echo "  COPY ./$m $m/"
    done
    echo ""
    exit 1
else
    echo -e "${GREEN}✅ Dockerfile validation passed${NC}"
    echo "All imported modules are included in the container."
    exit 0
fi
