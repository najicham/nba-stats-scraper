#!/bin/bash
# File: monitoring/scrapers/freshness/test-local.sh
#
# Test freshness monitoring locally before deploying

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Testing Freshness Monitor${NC}"
echo -e "${GREEN}================================${NC}"

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../" && pwd)"

# Load environment
if [ -f "${PROJECT_ROOT}/.env" ]; then
    echo -e "${GREEN}Loading environment from .env${NC}"
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
else
    echo -e "${YELLOW}Warning: .env file not found${NC}"
fi

echo ""
echo "Running tests..."
echo ""

# Test 1: Check configuration files
echo -e "${YELLOW}Test 1: Checking configuration files...${NC}"
if [ -f "${SCRIPT_DIR}/config/monitoring_config.yaml" ]; then
    echo -e "  ${GREEN}✓${NC} monitoring_config.yaml found"
else
    echo -e "  ${RED}✗${NC} monitoring_config.yaml not found"
    exit 1
fi

if [ -f "${SCRIPT_DIR}/config/nba_schedule_config.yaml" ]; then
    echo -e "  ${GREEN}✓${NC} nba_schedule_config.yaml found"
else
    echo -e "  ${RED}✗${NC} nba_schedule_config.yaml not found"
    exit 1
fi

# Test 2: Check Python dependencies
echo ""
echo -e "${YELLOW}Test 2: Checking Python dependencies...${NC}"
cd "${PROJECT_ROOT}"

if python3 -c "import yaml" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} PyYAML installed"
else
    echo -e "  ${RED}✗${NC} PyYAML not installed"
    echo "    Install with: pip install PyYAML"
    exit 1
fi

if python3 -c "from google.cloud import storage" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} google-cloud-storage installed"
else
    echo -e "  ${RED}✗${NC} google-cloud-storage not installed"
    echo "    Install with: pip install google-cloud-storage"
    exit 1
fi

# Test 3: Dry run
echo ""
echo -e "${YELLOW}Test 3: Running dry-run test...${NC}"
python3 "${SCRIPT_DIR}/runners/scheduled_monitor.py" --dry-run --test

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Dry run successful!${NC}"
else
    echo ""
    echo -e "${RED}✗ Dry run failed${NC}"
    exit 1
fi

# Test 4: Configuration validation
echo ""
echo -e "${YELLOW}Test 4: Validating configuration...${NC}"
python3 << EOF
import yaml
import sys

# Load and validate monitoring config
with open('${SCRIPT_DIR}/config/monitoring_config.yaml') as f:
    config = yaml.safe_load(f)

scrapers = config.get('scrapers', {})
print(f"  Found {len(scrapers)} scrapers configured")

# Check for required fields
errors = []
for name, scraper_config in scrapers.items():
    if 'gcs' not in scraper_config:
        errors.append(f"{name}: missing 'gcs' config")
    if 'schedule' not in scraper_config:
        errors.append(f"{name}: missing 'schedule' config")

if errors:
    print("\033[0;31m  Errors found:\033[0m")
    for error in errors:
        print(f"    - {error}")
    sys.exit(1)
else:
    print("\033[0;32m  ✓ Configuration valid\033[0m")
EOF

if [ $? -ne 0 ]; then
    exit 1
fi

# Summary
echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}All Tests Passed!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Deploy to Cloud Run: ./deploy.sh"
echo "  2. Set up scheduler: ./setup-scheduler.sh"
echo ""
