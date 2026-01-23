#!/bin/bash
# File: validation/validation_health_check.sh
# Description: Quick health check for validation system - shows current status
# Usage: ./validation_health_check.sh

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}NBA Validation System Health Check${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Check 1: Current Processor Status
echo -e "${CYAN}📊 Current Processor Status:${NC}"
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT 
  processor_name,
  health_status,
  overall_status,
  CONCAT(passed_checks, '/', total_checks) as checks,
  CONCAT(ROUND(pass_rate, 1), '%') as pass_rate,
  CONCAT(hours_since_validation, 'h ago') as last_validated,
  CASE 
    WHEN remediation_available THEN CONCAT('✅ ', CAST(remediation_commands_count AS STRING), ' commands')
    ELSE '❌ None'
  END as remediation
FROM \`nba-props-platform.nba_processing.processor_status_current\`
ORDER BY 
  CASE health_status
    WHEN '🔴 FAILING' THEN 1
    WHEN '🟡 WARNING' THEN 2
    WHEN '⚠️ STALE' THEN 3
    ELSE 4
  END,
  processor_name
" 2>&1

echo ""

# Check 2: Recent Failures
echo -e "${CYAN}❌ Recent Failures (Last 7 Days):${NC}"
echo ""

FAILURES=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_processing.validation_failures_recent\`
WHERE severity IN ('critical', 'error')
" 2>&1 | tail -1)

if [ "$FAILURES" = "0" ]; then
    echo -e "${GREEN}✅ No critical or error failures in last 7 days!${NC}"
else
    echo -e "${YELLOW}Found $FAILURES failures:${NC}"
    echo ""
    bq query --use_legacy_sql=false --format=pretty "
    SELECT 
      DATE(validation_timestamp) as date,
      processor_name,
      check_name,
      severity,
      message,
      affected_count as affected
    FROM \`nba-props-platform.nba_processing.validation_failures_recent\`
    WHERE severity IN ('critical', 'error')
    ORDER BY validation_timestamp DESC
    LIMIT 10
    " 2>&1
fi

echo ""

# Check 3: Data Quality Trends
echo -e "${CYAN}📈 Data Quality Trends (Last 4 Weeks):${NC}"
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT 
  processor_name,
  week_start,
  CONCAT(ROUND(pass_rate, 1), '%') as pass_rate,
  CASE 
    WHEN pass_rate_change > 0 THEN CONCAT('📈 +', CAST(ROUND(pass_rate_change, 1) AS STRING), '%')
    WHEN pass_rate_change < 0 THEN CONCAT('📉 ', CAST(ROUND(pass_rate_change, 1) AS STRING), '%')
    ELSE '➡️ 0%'
  END as trend,
  validation_runs
FROM \`nba-props-platform.nba_processing.validation_trends\`
WHERE processor_name IN ('espn_scoreboard', 'bdl_boxscores', 'nbac_gamebook', 'nbac_schedule')
ORDER BY week_start DESC, processor_name
LIMIT 20
" 2>&1

echo ""

# Check 4: Validation Coverage
echo -e "${CYAN}📋 Validation Coverage:${NC}"
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT 
  validation_status,
  COUNT(*) as processor_count,
  STRING_AGG(processor_name, ', ') as processors
FROM \`nba-props-platform.nba_processing.validation_coverage\`
GROUP BY validation_status
ORDER BY 
  CASE validation_status
    WHEN '✅ Active (7d)' THEN 1
    WHEN '⚠️ Inactive (7d)' THEN 2
    ELSE 3
  END
" 2>&1

echo ""

# Check 5: System Statistics
echo -e "${CYAN}📊 System Statistics:${NC}"
echo ""

echo "Total Validation Runs (Last 30 Days):"
bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as total_runs
FROM \`nba-props-platform.nba_processing.validation_runs\`
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
" 2>&1 | tail -1

echo ""

echo "Total Checks Executed (Last 30 Days):"
bq query --use_legacy_sql=false --format=csv "
SELECT SUM(total_checks) as total_checks
FROM \`nba-props-platform.nba_processing.validation_runs\`
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
" 2>&1 | tail -1

echo ""

echo "Overall Pass Rate (Last 30 Days):"
bq query --use_legacy_sql=false --format=csv "
SELECT 
  CONCAT(
    ROUND(
      SUM(passed_checks) * 100.0 / SUM(total_checks), 
      2
    ),
    '%'
  ) as pass_rate
FROM \`nba-props-platform.nba_processing.validation_runs\`
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
" 2>&1 | tail -1

echo ""

# Check 6: Proxy Health (per provider)
echo -e "${CYAN}🌐 Proxy Health (Last 24 Hours):${NC}"
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT
  proxy_provider,
  target_host,
  COUNTIF(success) as success,
  COUNTIF(NOT success) as failed,
  CONCAT(ROUND(100 * COUNTIF(success) / COUNT(*), 1), '%') as success_rate
FROM \`nba-props-platform.nba_orchestration.proxy_health_metrics\`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY proxy_provider, target_host
ORDER BY target_host, proxy_provider
" 2>&1

echo ""
echo -e "${YELLOW}Note: proxy_provider should show 'proxyfuel' and 'decodo' separately.${NC}"
echo -e "${YELLOW}If only 'proxyfuel' appears, check _get_proxy_provider() in scraper_base.py${NC}"
echo ""

# Check 7: Remediation Available
echo -e "${CYAN}🔧 Remediation Commands Available:${NC}"
echo ""

REMEDIATION_COUNT=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_processing.validation_results\`
WHERE passed = FALSE
  AND remediation_commands IS NOT NULL
  AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
" 2>&1 | tail -1)

if [ "$REMEDIATION_COUNT" = "0" ]; then
    echo -e "${GREEN}✅ No remediation needed in last 24 hours${NC}"
else
    echo -e "${YELLOW}Found $REMEDIATION_COUNT checks with remediation commands available${NC}"
    echo ""
    echo "To view remediation commands:"
    echo ""
    echo "  bq query --use_legacy_sql=false \\"
    echo "    \"SELECT processor_name, check_name, message, remediation_commands \\"
    echo "     FROM \\\`nba-props-platform.nba_processing.validation_results\\\` \\"
    echo "     WHERE passed = FALSE AND remediation_commands IS NOT NULL \\"
    echo "       AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)\""
fi

echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Health Check Complete${NC}"
echo -e "${BLUE}================================================${NC}"

# Determine overall health status
FAILING_COUNT=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_processing.processor_status_current\`
WHERE health_status IN ('🔴 FAILING', '⚠️ STALE')
" 2>&1 | tail -1)

WARNING_COUNT=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_processing.processor_status_current\`
WHERE health_status = '🟡 WARNING'
" 2>&1 | tail -1)

echo ""
if [ "$FAILING_COUNT" != "0" ]; then
    echo -e "${RED}⚠️  ATTENTION NEEDED: $FAILING_COUNT processor(s) failing or stale${NC}"
    exit 1
elif [ "$WARNING_COUNT" != "0" ]; then
    echo -e "${YELLOW}⚠️  REVIEW NEEDED: $WARNING_COUNT processor(s) have warnings${NC}"
    exit 2
else
    echo -e "${GREEN}✅ ALL SYSTEMS HEALTHY${NC}"
    exit 0
fi