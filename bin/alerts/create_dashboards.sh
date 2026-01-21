#!/bin/bash

#####################################################################
# NBA Prediction Worker - Create Cloud Monitoring Dashboards
#
# Creates three comprehensive dashboards:
# 1. NBA Prediction Metrics Dashboard
# 2. NBA Data Pipeline Health Dashboard
# 3. NBA Model Performance Dashboard
#
# Usage:
#   ./bin/alerts/create_dashboards.sh [PROJECT_ID] [ENVIRONMENT]
#
# Arguments:
#   PROJECT_ID   - GCP project ID (default: nba-props-platform)
#   ENVIRONMENT  - Environment: prod, staging, dev (default: prod)
#
# Example:
#   ./bin/alerts/create_dashboards.sh nba-props-platform prod
#
# Requirements:
#   - gcloud CLI installed and authenticated
#   - Permissions: monitoring.dashboards.create
#
# Created: 2026-01-17 (Week 3 - Option B Implementation)
#####################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
PROJECT_ID="${1:-nba-props-platform}"
ENVIRONMENT="${2:-prod}"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARDS_DIR="${SCRIPT_DIR}/dashboards"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  NBA Prediction Worker - Dashboard Deployment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Project ID:     ${GREEN}${PROJECT_ID}${NC}"
echo -e "Environment:    ${GREEN}${ENVIRONMENT}${NC}"
echo -e "Dashboards Dir: ${GREEN}${DASHBOARDS_DIR}${NC}"
echo ""

# Verify dashboards directory exists
if [ ! -d "$DASHBOARDS_DIR" ]; then
  echo -e "${RED}ERROR: Dashboards directory not found: ${DASHBOARDS_DIR}${NC}"
  exit 1
fi

# Dashboard configurations
declare -A DASHBOARDS=(
  ["nba_prediction_metrics_dashboard.json"]="NBA Prediction Metrics Dashboard"
  ["nba_data_pipeline_health_dashboard.json"]="NBA Data Pipeline Health Dashboard"
  ["nba_model_performance_dashboard.json"]="NBA Model Performance Dashboard"
)

# Function to create or update a dashboard
create_dashboard() {
  local config_file="$1"
  local display_name="$2"
  local config_path="${DASHBOARDS_DIR}/${config_file}"

  echo -e "${YELLOW}➜${NC} Creating dashboard: ${BLUE}${display_name}${NC}"

  # Check if config file exists
  if [ ! -f "$config_path" ]; then
    echo -e "${RED}  ✗ Config file not found: ${config_path}${NC}"
    return 1
  fi

  # Validate JSON syntax
  if ! jq empty "$config_path" 2>/dev/null; then
    echo -e "${RED}  ✗ Invalid JSON in config file: ${config_path}${NC}"
    return 1
  fi

  # Create dashboard
  if gcloud monitoring dashboards create \
    --config-from-file="$config_path" \
    --project="$PROJECT_ID" \
    --format=json > /tmp/dashboard_output.json 2>&1; then

    # Extract dashboard ID
    DASHBOARD_ID=$(jq -r '.name' /tmp/dashboard_output.json | sed 's/.*\/dashboards\///')

    # Construct dashboard URL
    DASHBOARD_URL="https://console.cloud.google.com/monitoring/dashboards/custom/${DASHBOARD_ID}?project=${PROJECT_ID}"

    echo -e "${GREEN}  ✓ Dashboard created successfully${NC}"
    echo -e "    Dashboard ID: ${DASHBOARD_ID}"
    echo -e "    URL: ${DASHBOARD_URL}"
    echo ""

    # Save URL to file for documentation
    echo "${display_name}: ${DASHBOARD_URL}" >> /tmp/dashboard_urls.txt

  else
    echo -e "${RED}  ✗ Failed to create dashboard${NC}"
    echo -e "${RED}  $(cat /tmp/dashboard_output.json)${NC}"
    echo ""
    return 1
  fi
}

# Clear previous URLs file
rm -f /tmp/dashboard_urls.txt

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 1: Creating Dashboards${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Create each dashboard
SUCCESS_COUNT=0
FAILURE_COUNT=0

for config_file in "${!DASHBOARDS[@]}"; do
  display_name="${DASHBOARDS[$config_file]}"

  if create_dashboard "$config_file" "$display_name"; then
    ((SUCCESS_COUNT++))
  else
    ((FAILURE_COUNT++))
  fi
done

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Deployment Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Dashboards created:  ${GREEN}${SUCCESS_COUNT}${NC}"
echo -e "Dashboards failed:   ${RED}${FAILURE_COUNT}${NC}"
echo ""

if [ -f /tmp/dashboard_urls.txt ]; then
  echo -e "${GREEN}📊 Dashboard URLs:${NC}"
  echo ""
  cat /tmp/dashboard_urls.txt
  echo ""

  # Copy URLs to clipboard-ready format
  echo -e "${YELLOW}💡 Tip: Dashboard URLs saved to /tmp/dashboard_urls.txt${NC}"
  echo ""
fi

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Next Steps${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "1. Open the dashboard URLs above in your browser"
echo "2. Verify all widgets are displaying data correctly"
echo "3. Add dashboard links to ALERT-RUNBOOKS.md"
echo "4. Share dashboard links with your team"
echo ""

if [ $FAILURE_COUNT -gt 0 ]; then
  echo -e "${YELLOW}⚠️  Some dashboards failed to create. Check the errors above.${NC}"
  echo ""
  exit 1
fi

echo -e "${GREEN}✅ All dashboards deployed successfully!${NC}"
echo ""
