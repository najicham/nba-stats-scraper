#!/bin/bash
#
# Deploy NBA Grading System Dashboard to Cloud Monitoring
#
# This script creates or updates the Cloud Monitoring dashboard
# for monitoring grading system health, auto-heal performance,
# and Phase 3 analytics reliability.
#
# Usage:
#   ./deploy-grading-dashboard.sh [PROJECT_ID]
#
# Requirements:
#   - gcloud CLI installed and authenticated
#   - monitoring.dashboards.create permission (or Editor/Owner role)
#
# Created: 2026-01-18
# Session: 99

set -e  # Exit on error

# Configuration
PROJECT_ID="${1:-nba-props-platform}"
DASHBOARD_FILE="$(dirname "$0")/grading-system-dashboard-simple.json"
DASHBOARD_NAME="NBA Grading System - Health & Performance"

echo "=================================================="
echo "Deploy NBA Grading System Dashboard"
echo "=================================================="
echo ""
echo "Project: $PROJECT_ID"
echo "Dashboard: $DASHBOARD_NAME"
echo "Config File: $DASHBOARD_FILE"
echo ""

# Validate dashboard file exists
if [[ ! -f "$DASHBOARD_FILE" ]]; then
    echo "❌ Error: Dashboard config file not found: $DASHBOARD_FILE"
    exit 1
fi

# Validate JSON syntax
if ! jq empty "$DASHBOARD_FILE" 2>/dev/null; then
    echo "❌ Error: Invalid JSON in dashboard config file"
    exit 1
fi

echo "✅ Dashboard config file validated"
echo ""

# Check if dashboard already exists
echo "🔍 Checking for existing dashboard..."
EXISTING_DASHBOARD=$(gcloud monitoring dashboards list \
    --project="$PROJECT_ID" \
    --filter="displayName:'$DASHBOARD_NAME'" \
    --format="value(name)" \
    2>/dev/null || echo "")

if [[ -n "$EXISTING_DASHBOARD" ]]; then
    echo "📝 Existing dashboard found: $EXISTING_DASHBOARD"
    echo ""
    read -p "Do you want to update the existing dashboard? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🔄 Updating existing dashboard..."

        # Extract dashboard ID from full name (format: projects/*/dashboards/*)
        DASHBOARD_ID=$(basename "$EXISTING_DASHBOARD")

        gcloud monitoring dashboards update "$DASHBOARD_ID" \
            --project="$PROJECT_ID" \
            --config-from-file="$DASHBOARD_FILE"

        if [[ $? -eq 0 ]]; then
            echo ""
            echo "✅ Dashboard updated successfully!"
            echo ""
            echo "View dashboard:"
            echo "https://console.cloud.google.com/monitoring/dashboards/custom/$DASHBOARD_ID?project=$PROJECT_ID"
        else
            echo ""
            echo "❌ Dashboard update failed"
            exit 1
        fi
    else
        echo "⏭️  Skipping dashboard update"
        exit 0
    fi
else
    echo "📋 No existing dashboard found - creating new dashboard..."
    echo ""

    gcloud monitoring dashboards create \
        --project="$PROJECT_ID" \
        --config-from-file="$DASHBOARD_FILE"

    if [[ $? -eq 0 ]]; then
        echo ""
        echo "✅ Dashboard created successfully!"
        echo ""

        # Get the newly created dashboard ID
        DASHBOARD_ID=$(gcloud monitoring dashboards list \
            --project="$PROJECT_ID" \
            --filter="displayName:'$DASHBOARD_NAME'" \
            --format="value(name)" \
            2>/dev/null | head -1)

        if [[ -n "$DASHBOARD_ID" ]]; then
            DASHBOARD_SHORT_ID=$(basename "$DASHBOARD_ID")
            echo "View dashboard:"
            echo "https://console.cloud.google.com/monitoring/dashboards/custom/$DASHBOARD_SHORT_ID?project=$PROJECT_ID"
        else
            echo "View all dashboards:"
            echo "https://console.cloud.google.com/monitoring/dashboards?project=$PROJECT_ID"
        fi
    else
        echo ""
        echo "❌ Dashboard creation failed"
        exit 1
    fi
fi

echo ""
echo "=================================================="
echo "Dashboard Deployment Complete"
echo "=================================================="
echo ""
echo "📊 Dashboard Features:"
echo "  - Phase 3 Analytics 503 error tracking"
echo "  - Auto-heal success rate monitoring"
echo "  - Lock health metrics"
echo "  - Grading function performance"
echo "  - Retry distribution analysis"
echo ""
echo "📚 Related Documentation:"
echo "  - Monitoring Guide: docs/02-operations/GRADING-MONITORING-GUIDE.md"
echo "  - Troubleshooting: docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md"
echo ""
