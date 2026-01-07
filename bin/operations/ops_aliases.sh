#!/bin/bash
###############################################################################
# NBA Stats Scraper - Operations Aliases & Helper Commands
#
# Quick shortcuts for common operational tasks
#
# Installation:
#   1. Add to your ~/.bashrc or ~/.zshrc:
#      source /home/naji/code/nba-stats-scraper/bin/operations/ops_aliases.sh
#
#   2. Reload shell:
#      source ~/.bashrc  # or source ~/.zshrc
#
# Created: 2026-01-03 (Session 6)
# Version: 1.0
###############################################################################

# Set project root
export NBA_PROJECT_ROOT="/home/naji/code/nba-stats-scraper"
export NBA_PROJECT_ID="nba-props-platform"
export NBA_REGION="us-west2"

###############################################################################
# MONITORING ALIASES
###############################################################################

# Quick status check
alias nba-status='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh quick'

# Full operations dashboard
alias nba-dash='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh'
alias nba-dashboard='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh'

# Specific dashboard sections
alias nba-pipeline='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh pipeline'
alias nba-workflows='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh workflows'
alias nba-errors='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh errors'
alias nba-backfill='${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh backfill'

# Python monitoring tool
alias nba-mon='python3 ${NBA_PROJECT_ROOT}/monitoring/scripts/nba-monitor'
alias nba-monitor='python3 ${NBA_PROJECT_ROOT}/monitoring/scripts/nba-monitor'

###############################################################################
# BIGQUERY ALIASES
###############################################################################

# Quick BigQuery access
alias bq-nba='bq --project_id=${NBA_PROJECT_ID}'

# Common BigQuery queries
alias bq-health='bq query --use_legacy_sql=false < ${NBA_PROJECT_ROOT}/bin/operations/monitoring_queries.sql'

# Check Phase 3 data
alias bq-phase3='bq query --use_legacy_sql=false "SELECT COUNT(*) as rows, COUNT(DISTINCT game_date) as dates FROM \`${NBA_PROJECT_ID}.nba_analytics.player_game_summary\` WHERE game_date >= \"2024-10-01\""'

# Check Phase 4 data
alias bq-phase4='bq query --use_legacy_sql=false "SELECT COUNT(*) as rows, COUNT(DISTINCT game_date) as dates FROM \`${NBA_PROJECT_ID}.nba_precompute.player_composite_factors\` WHERE game_date >= \"2024-10-01\""'

# List all datasets
alias bq-list='bq ls --project_id=${NBA_PROJECT_ID}'

# Show table schema
alias bq-schema='bq show --schema --format=prettyjson'

###############################################################################
# GCS ALIASES
###############################################################################

# Quick GCS access
alias gs-nba='gsutil ls gs://nba-scraped-data/'

# List today's data
alias gs-today='gsutil ls gs://nba-scraped-data/**/$(date +%Y-%m-%d)/'

# List yesterday's data
alias gs-yesterday='gsutil ls gs://nba-scraped-data/**/$(date -d yesterday +%Y-%m-%d)/ 2>/dev/null || gsutil ls gs://nba-scraped-data/**/$(date -v-1d +%Y-%m-%d)/'

# Count files by source
alias gs-count='gsutil ls gs://nba-scraped-data/** | wc -l'

# Check backups
alias gs-backups='gsutil ls gs://nba-bigquery-backups/'

###############################################################################
# CLOUD RUN ALIASES
###############################################################################

# List all Cloud Run services
alias run-list='gcloud run services list --platform=managed --region=${NBA_REGION}'

# Get service logs
alias run-logs='gcloud run services logs read --region=${NBA_REGION}'

# Describe service
alias run-describe='gcloud run services describe --region=${NBA_REGION}'

###############################################################################
# CLOUD SCHEDULER ALIASES
###############################################################################

# List all schedulers
alias sched-list='gcloud scheduler jobs list --location=${NBA_REGION}'

# Pause all schedulers (emergency)
alias sched-pause-all='for job in $(gcloud scheduler jobs list --location=${NBA_REGION} --format="value(ID)"); do gcloud scheduler jobs pause $job --location=${NBA_REGION}; done'

# Resume all schedulers
alias sched-resume-all='for job in $(gcloud scheduler jobs list --location=${NBA_REGION} --format="value(ID)"); do gcloud scheduler jobs resume $job --location=${NBA_REGION}; done'

# Run specific scheduler
alias sched-run='gcloud scheduler jobs run --location=${NBA_REGION}'

###############################################################################
# WORKFLOW ALIASES
###############################################################################

# List workflow executions
alias wf-list='gcloud workflows executions list --location=${NBA_REGION}'

# Describe workflow
alias wf-describe='gcloud workflows describe --location=${NBA_REGION}'

###############################################################################
# LOGGING ALIASES
###############################################################################

# Recent errors (last 24h)
alias logs-errors='gcloud logging read "severity>=ERROR" --limit=50 --freshness=1d'

# Specific service logs
alias logs-scrapers='gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"nba-scrapers\"" --limit=50'

# Recent Cloud Function logs
alias logs-functions='gcloud logging read "resource.type=\"cloud_function\"" --limit=50'

###############################################################################
# VALIDATION ALIASES
###############################################################################

# Run Phase 3 validation
alias validate-phase3='${NBA_PROJECT_ROOT}/scripts/validation/validate_player_summary.sh'

# Run team offense validation
alias validate-team='${NBA_PROJECT_ROOT}/scripts/validation/validate_team_offense.sh'

###############################################################################
# BACKUP & RECOVERY ALIASES
###############################################################################

# Run daily backup
alias backup-now='${NBA_PROJECT_ROOT}/bin/operations/export_bigquery_tables.sh daily'

# List backups
alias backup-list='gsutil ls gs://nba-bigquery-backups/daily/'

# Disaster recovery quick reference
alias dr-help='cat ${NBA_PROJECT_ROOT}/docs/02-operations/runbooks/emergency/DR-QUICK-REFERENCE.md'

###############################################################################
# DEVELOPMENT ALIASES
###############################################################################

# Navigate to project root
alias cd-nba='cd ${NBA_PROJECT_ROOT}'

# Activate Python virtual environment
alias nba-venv='source ${NBA_PROJECT_ROOT}/.venv/bin/activate'

# Run tests
alias nba-test='cd ${NBA_PROJECT_ROOT} && PYTHONPATH=. pytest'

###############################################################################
# HELPER FUNCTIONS
###############################################################################

# Quick health check (combines multiple checks)
nba-health() {
    echo "=== NBA Stats Scraper Health Check ==="
    echo ""
    echo "📊 Pipeline Status:"
    ${NBA_PROJECT_ROOT}/bin/operations/ops_dashboard.sh quick
    echo ""
    echo "📅 Recent Schedulers:"
    gcloud scheduler jobs list --location=${NBA_REGION} --limit=5
    echo ""
    echo "🔄 Recent Workflows:"
    python3 ${NBA_PROJECT_ROOT}/monitoring/scripts/nba-monitor workflows 1 2>/dev/null || echo "nba-monitor not available"
}

# Check data for specific date
nba-check-date() {
    local date=${1:-$(date -d yesterday +%Y-%m-%d)}
    echo "Checking data for: $date"
    echo ""
    echo "Phase 3 (Analytics):"
    bq query --use_legacy_sql=false "SELECT COUNT(*) as player_games FROM \`${NBA_PROJECT_ID}.nba_analytics.player_game_summary\` WHERE game_date = '$date'"
    echo ""
    echo "Phase 4 (Precompute):"
    bq query --use_legacy_sql=false "SELECT COUNT(*) as player_composite_factors FROM \`${NBA_PROJECT_ID}.nba_precompute.player_composite_factors\` WHERE game_date = '$date'"
    echo ""
    echo "GCS Files:"
    gsutil ls "gs://nba-scraped-data/**/$date/" 2>/dev/null | wc -l
}

# Tail logs for specific service
nba-tail() {
    local service=${1:-nba-scrapers}
    echo "Tailing logs for: $service"
    gcloud logging tail "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"$service\"" --format=json
}

# Get identity token for authenticated requests
nba-token() {
    gcloud auth print-identity-token
}

# Test Cloud Run endpoint
nba-curl() {
    local url=$1
    local method=${2:-GET}
    local data=${3:-}

    local token=$(gcloud auth print-identity-token)

    if [[ -n "$data" ]]; then
        curl -X $method "$url" \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d "$data"
    else
        curl -X $method "$url" \
            -H "Authorization: Bearer $token"
    fi
}

# Quick incident response
nba-incident() {
    local severity=${1:-P2}
    echo "🚨 Incident Response - Severity: $severity"
    echo ""
    echo "1. Pause schedulers (if needed):"
    echo "   sched-pause-all"
    echo ""
    echo "2. Check current status:"
    echo "   nba-dash"
    echo ""
    echo "3. Check recent errors:"
    echo "   nba-errors"
    echo ""
    echo "4. View incident response guide:"
    echo "   cat ${NBA_PROJECT_ROOT}/docs/02-operations/incident-response.md"
    echo ""
    echo "5. View disaster recovery (if needed):"
    echo "   cat ${NBA_PROJECT_ROOT}/docs/02-operations/disaster-recovery-runbook.md"
}

# Deploy service shortcut
nba-deploy() {
    local service=$1
    case $service in
        "analytics")
            ${NBA_PROJECT_ROOT}/bin/analytics/deploy/deploy_analytics_processors.sh
            ;;
        "precompute")
            ${NBA_PROJECT_ROOT}/bin/precompute/deploy/deploy_precompute_processors.sh
            ;;
        "predictions")
            ${NBA_PROJECT_ROOT}/bin/predictions/deploy/deploy_prediction_coordinator.sh
            ${NBA_PROJECT_ROOT}/bin/predictions/deploy/deploy_prediction_worker.sh
            ;;
        *)
            echo "Unknown service: $service"
            echo "Available: analytics, precompute, predictions"
            ;;
    esac
}

# Show all available aliases
nba-help() {
    echo "==================================================================="
    echo "NBA Stats Scraper - Operations Aliases"
    echo "==================================================================="
    echo ""
    echo "MONITORING:"
    echo "  nba-status          - Quick status check"
    echo "  nba-dash            - Full operations dashboard"
    echo "  nba-pipeline        - Pipeline health only"
    echo "  nba-workflows       - Workflow status only"
    echo "  nba-errors          - Recent errors only"
    echo "  nba-monitor         - Python monitoring CLI"
    echo "  nba-health          - Combined health check"
    echo ""
    echo "BIGQUERY:"
    echo "  bq-nba              - BigQuery with project ID"
    echo "  bq-health           - Run monitoring queries"
    echo "  bq-phase3           - Check Phase 3 data"
    echo "  bq-phase4           - Check Phase 4 data"
    echo "  bq-list             - List all datasets"
    echo ""
    echo "GCS:"
    echo "  gs-nba              - List GCS bucket"
    echo "  gs-today            - Today's data files"
    echo "  gs-yesterday        - Yesterday's data files"
    echo "  gs-backups          - List backups"
    echo ""
    echo "CLOUD RUN:"
    echo "  run-list            - List Cloud Run services"
    echo "  run-logs SERVICE    - View service logs"
    echo "  run-describe SERVICE - Describe service"
    echo ""
    echo "SCHEDULERS:"
    echo "  sched-list          - List all schedulers"
    echo "  sched-pause-all     - Pause all (emergency)"
    echo "  sched-resume-all    - Resume all"
    echo "  sched-run JOB       - Run specific job"
    echo ""
    echo "LOGGING:"
    echo "  logs-errors         - Recent errors (24h)"
    echo "  logs-scrapers       - Scraper logs"
    echo "  logs-functions      - Cloud Function logs"
    echo "  nba-tail SERVICE    - Tail service logs"
    echo ""
    echo "VALIDATION:"
    echo "  validate-phase3     - Validate Phase 3 data"
    echo "  validate-team       - Validate team offense"
    echo ""
    echo "BACKUP:"
    echo "  backup-now          - Run daily backup"
    echo "  backup-list         - List backups"
    echo "  dr-help             - DR quick reference"
    echo ""
    echo "DEVELOPMENT:"
    echo "  cd-nba              - Navigate to project"
    echo "  nba-venv            - Activate virtualenv"
    echo "  nba-test            - Run tests"
    echo ""
    echo "FUNCTIONS:"
    echo "  nba-check-date DATE - Check data for date"
    echo "  nba-token           - Get identity token"
    echo "  nba-curl URL        - Authenticated curl"
    echo "  nba-incident LEVEL  - Incident response guide"
    echo "  nba-deploy SERVICE  - Deploy service"
    echo "  nba-help            - Show this help"
    echo ""
    echo "==================================================================="
}

###############################################################################
# INITIALIZATION
###############################################################################

# Print welcome message
echo "✅ NBA Stats Scraper aliases loaded"
echo "   Type 'nba-help' for available commands"
echo "   Type 'nba-status' for quick health check"
