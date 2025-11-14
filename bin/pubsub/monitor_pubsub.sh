#!/bin/bash
# monitor_pubsub.sh
#
# File Path: bin/pubsub/monitor_pubsub.sh
#
# Purpose: Monitor Pub/Sub health and performance
#
# Checks:
# - Subscription backlog (should be near 0)
# - DLQ message count (should be 0)
# - Recent publish/delivery metrics
# - Processor response times
#
# Usage: ./bin/pubsub/monitor_pubsub.sh [--watch]
#
# Options:
#   --watch: Continuously monitor (refresh every 30 seconds)

PROJECT_ID="nba-props-platform"
REGION="us-west2"
TOPIC="nba-scraper-complete"
SUBSCRIPTION="nba-processors-sub"
DLQ_SUBSCRIPTION="nba-scraper-complete-dlq-sub"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored status
print_status() {
  local status=$1
  local message=$2
  
  case $status in
    "ok")
      echo -e "${GREEN}✅${NC} $message"
      ;;
    "warning")
      echo -e "${YELLOW}⚠️${NC}  $message"
      ;;
    "error")
      echo -e "${RED}❌${NC} $message"
      ;;
    "info")
      echo -e "${BLUE}ℹ️${NC}  $message"
      ;;
  esac
}

# Function to monitor Pub/Sub
monitor_pubsub() {
  clear
  echo "🔍 Pub/Sub Health Monitor - NBA Props Platform"
  echo "=============================================="
  echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
  echo ""
  
  # Phase 1: Topic Health
  echo "📋 Phase 1: Topic Health"
  echo "------------------------"
  
  if gcloud pubsub topics describe $TOPIC --project=$PROJECT_ID &>/dev/null; then
    print_status "ok" "Topic exists: $TOPIC"
  else
    print_status "error" "Topic not found: $TOPIC"
    echo ""
    return 1
  fi
  
  echo ""
  
  # Phase 2: Subscription Health
  echo "📋 Phase 2: Subscription Health"
  echo "--------------------------------"
  
  if gcloud pubsub subscriptions describe $SUBSCRIPTION --project=$PROJECT_ID &>/dev/null; then
    print_status "ok" "Subscription exists: $SUBSCRIPTION"
    
    # Check backlog
    BACKLOG=$(gcloud pubsub subscriptions describe $SUBSCRIPTION \
      --format='value(numUndeliveredMessages)' --project=$PROJECT_ID 2>/dev/null || echo "unknown")
    
    if [ "$BACKLOG" = "unknown" ]; then
      print_status "error" "Unable to check backlog"
    elif [ "$BACKLOG" -eq 0 ]; then
      print_status "ok" "Backlog: 0 messages (healthy)"
    elif [ "$BACKLOG" -lt 10 ]; then
      print_status "warning" "Backlog: $BACKLOG messages (minor lag)"
    else
      print_status "error" "Backlog: $BACKLOG messages (processing lag!)"
    fi
    
    # Check oldest unacked message age
    OLDEST_AGE=$(gcloud pubsub subscriptions describe $SUBSCRIPTION \
      --format='value(oldestUnackedMessageAge)' --project=$PROJECT_ID 2>/dev/null || echo "0s")
    
    if [ "$OLDEST_AGE" != "0s" ] && [ "$OLDEST_AGE" != "" ]; then
      # Convert to seconds for comparison
      AGE_SECONDS=$(echo "$OLDEST_AGE" | sed 's/s//')
      if [ "$AGE_SECONDS" -gt 300 ]; then
        print_status "error" "Oldest unacked message: $OLDEST_AGE (processing stuck!)"
      elif [ "$AGE_SECONDS" -gt 60 ]; then
        print_status "warning" "Oldest unacked message: $OLDEST_AGE"
      else
        print_status "ok" "Oldest unacked message: $OLDEST_AGE"
      fi
    fi
    
  else
    print_status "error" "Subscription not found: $SUBSCRIPTION"
  fi
  
  echo ""
  
  # Phase 3: Dead Letter Queue
  echo "📋 Phase 3: Dead Letter Queue"
  echo "------------------------------"
  
  if gcloud pubsub subscriptions describe $DLQ_SUBSCRIPTION --project=$PROJECT_ID &>/dev/null; then
    DLQ_COUNT=$(gcloud pubsub subscriptions describe $DLQ_SUBSCRIPTION \
      --format='value(numUndeliveredMessages)' --project=$PROJECT_ID 2>/dev/null || echo "unknown")
    
    if [ "$DLQ_COUNT" = "unknown" ]; then
      print_status "error" "Unable to check DLQ"
    elif [ "$DLQ_COUNT" -eq 0 ]; then
      print_status "ok" "DLQ: 0 messages (no failures)"
    else
      print_status "error" "DLQ: $DLQ_COUNT messages (failures detected!)"
      echo ""
      echo "   To investigate:"
      echo "   gcloud pubsub subscriptions pull $DLQ_SUBSCRIPTION --limit=5 --project=$PROJECT_ID"
    fi
  else
    print_status "warning" "DLQ subscription not found"
  fi
  
  echo ""
  
  # Phase 4: Cloud Run Service Health
  echo "📋 Phase 4: Cloud Run Services"
  echo "-------------------------------"
  
  # Check scraper service
  SCRAPER_URL=$(gcloud run services describe nba-scrapers \
    --region=$REGION \
    --format="value(status.url)" 2>/dev/null || echo "")
  
  if [ -n "$SCRAPER_URL" ]; then
    SCRAPER_HEALTH=$(curl -s "$SCRAPER_URL/health" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unknown")
    if [ "$SCRAPER_HEALTH" = "healthy" ]; then
      print_status "ok" "Scraper service: healthy"
    else
      print_status "warning" "Scraper service: $SCRAPER_HEALTH"
    fi
  else
    print_status "error" "Scraper service: not found"
  fi
  
  # Check processor service
  PROCESSOR_URL=$(gcloud run services describe nba-processors \
    --region=$REGION \
    --format="value(status.url)" 2>/dev/null || echo "")
  
  if [ -n "$PROCESSOR_URL" ]; then
    TOKEN=$(gcloud auth print-identity-token 2>/dev/null)
    PROCESSOR_HEALTH=$(curl -s -H "Authorization: Bearer $TOKEN" \
      "$PROCESSOR_URL/health" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unknown")
    if [ "$PROCESSOR_HEALTH" = "healthy" ]; then
      print_status "ok" "Processor service: healthy"
    else
      print_status "warning" "Processor service: $PROCESSOR_HEALTH"
    fi
  else
    print_status "error" "Processor service: not found"
  fi
  
  echo ""
  
  # Phase 5: Recent Activity
  echo "📋 Phase 5: Recent Activity (Last Hour)"
  echo "----------------------------------------"
  
  # Count recent scraper executions
  RECENT_EXECUTIONS=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) as count 
     FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\` 
     WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)" \
    2>/dev/null | tail -1)
  
  if [ -n "$RECENT_EXECUTIONS" ] && [ "$RECENT_EXECUTIONS" != "count" ]; then
    print_status "info" "Scraper executions (last hour): $RECENT_EXECUTIONS"
  fi
  
  # Count successful vs failed
  SUCCESS_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) as count 
     FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\` 
     WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
     AND status = 'success'" \
    2>/dev/null | tail -1)
  
  FAILED_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) as count 
     FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\` 
     WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
     AND status = 'failed'" \
    2>/dev/null | tail -1)
  
  if [ -n "$SUCCESS_COUNT" ] && [ "$SUCCESS_COUNT" != "count" ]; then
    print_status "info" "  ✓ Successful: $SUCCESS_COUNT"
  fi
  
  if [ -n "$FAILED_COUNT" ] && [ "$FAILED_COUNT" != "count" ] && [ "$FAILED_COUNT" -gt 0 ]; then
    print_status "warning" "  ✗ Failed: $FAILED_COUNT"
  fi
  
  echo ""
  
  # Phase 6: Summary & Recommendations
  echo "📋 Summary"
  echo "----------"
  
  # Overall health assessment
  HEALTH_OK=true
  
  if [ "$BACKLOG" != "unknown" ] && [ "$BACKLOG" -gt 10 ]; then
    HEALTH_OK=false
    print_status "warning" "High backlog detected - processors may be slow"
  fi
  
  if [ "$DLQ_COUNT" != "unknown" ] && [ "$DLQ_COUNT" -gt 0 ]; then
    HEALTH_OK=false
    print_status "error" "Failed messages in DLQ - investigate processor errors"
  fi
  
  if $HEALTH_OK; then
    print_status "ok" "All systems operational"
  fi
  
  echo ""
  echo "Last updated: $(date '+%H:%M:%S')"
  
  if [ "$1" = "--watch" ]; then
    echo ""
    echo "Press Ctrl+C to stop watching..."
  fi
}

# Main execution
if [ "$1" = "--watch" ]; then
  # Watch mode - refresh every 30 seconds
  while true; do
    monitor_pubsub "$1"
    sleep 30
  done
else
  # Single run
  monitor_pubsub
fi
