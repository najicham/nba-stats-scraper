#!/bin/bash
# Deployment Verification Aliases
# Source this file to add convenient deployment commands to your shell
#
# Usage:
#   source bin/deployment-aliases.sh
#
# Or add to your ~/.bashrc or ~/.zshrc:
#   source ~/path/to/nba-stats-scraper/bin/deployment-aliases.sh

# Pre-deployment checks
alias pre-deploy='./bin/pre-deployment-checklist.sh'
alias check-drift='./bin/check-deployment-drift.sh --verbose'

# Quick deployment verification
alias verify-deploy='function _verify_deploy() {
  echo "Verifying deployment for: $1"
  echo ""
  echo "=== Service Health ==="
  gcloud run services describe "$1" --region=us-west2 --format="table(status.url,status.latestReadyRevisionName,metadata.labels.commit-sha)"
  echo ""
  echo "=== Recent Logs ==="
  gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"$1\"" --limit=10 --format="table(timestamp,severity,textPayload)"
}; _verify_deploy'

# Check deployed commit
alias deployed-commit='function _deployed_commit() {
  COMMIT=$(gcloud run services describe "$1" --region=us-west2 --format="value(metadata.labels.commit-sha)" 2>/dev/null)
  if [ -n "$COMMIT" ]; then
    echo "Service: $1"
    echo "Deployed commit: $COMMIT"
    echo ""
    git log --oneline -1 "$COMMIT" 2>/dev/null || echo "(commit not in local repo)"
  else
    echo "Could not get deployed commit for: $1"
  fi
}; _deployed_commit'

# Check all service deployments
alias check-all-services='function _check_all() {
  echo "=== Deployment Status for All Services ==="
  echo ""
  SERVICES="prediction-worker prediction-coordinator nba-phase3-analytics-processors nba-phase4-precompute-processors nba-scrapers nba-grading-service"
  for svc in $SERVICES; do
    COMMIT=$(gcloud run services describe "$svc" --region=us-west2 --format="value(metadata.labels.commit-sha)" 2>/dev/null || echo "N/A")
    echo "$svc: $COMMIT"
  done
}; _check_all'

# Quick health check for service
alias health-check='function _health_check() {
  URL=$(gcloud run services describe "$1" --region=us-west2 --format="value(status.url)" 2>/dev/null)
  if [ -n "$URL" ]; then
    echo "Checking health: $URL/health"
    curl -s "$URL/health" | jq . || echo "Failed to reach service"
  else
    echo "Could not get URL for: $1"
  fi
}; _health_check'

# Run unified health check
alias system-health='./bin/monitoring/unified-health-check.sh --verbose'

# Check predictions for today
alias check-predictions='function _check_preds() {
  bq query --use_legacy_sql=false "
    SELECT
      system_id,
      COUNT(*) as predictions,
      COUNTIF(line_source = '\''ACTUAL_PROP'\'') as with_lines,
      MIN(created_at) as first_prediction,
      MAX(created_at) as last_prediction
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = CURRENT_DATE()
    GROUP BY system_id
    ORDER BY predictions DESC"
}; _check_preds'

# Check Vegas line coverage
alias check-lines='./bin/monitoring/check_vegas_line_coverage.sh'

# Check grading completeness
alias check-grading='./bin/monitoring/check_grading_completeness.sh'

# Deployment workflow shortcuts
alias full-deploy='function _full_deploy() {
  echo "=== Full Deployment Process for: $1 ==="
  echo ""
  echo "[1/3] Pre-deployment checklist..."
  ./bin/pre-deployment-checklist.sh "$1" || return 1
  echo ""
  echo "[2/3] Deploying..."
  ./bin/deploy-service.sh "$1" || return 1
  echo ""
  echo "[3/3] Post-deployment verification..."
  sleep 30
  health-check "$1"
}; _full_deploy'

# Quick rollback
alias rollback='function _rollback() {
  SERVICE=$1
  echo "Available revisions for $SERVICE:"
  gcloud run revisions list --service="$SERVICE" --region=us-west2 --limit=5
  echo ""
  echo "To rollback, run:"
  echo "  gcloud run services update-traffic $SERVICE --region=us-west2 --to-revisions=REVISION_NAME=100"
}; _rollback'

echo "✅ Deployment aliases loaded!"
echo ""
echo "Available commands:"
echo "  pre-deploy <service>         - Run pre-deployment checklist"
echo "  check-drift                  - Check for deployment drift"
echo "  deployed-commit <service>    - Show deployed commit hash"
echo "  health-check <service>       - Check service health endpoint"
echo "  verify-deploy <service>      - Verify deployment (health + logs)"
echo "  check-all-services           - Show deployment status for all services"
echo "  system-health                - Run unified health check"
echo "  check-predictions            - Query today's predictions"
echo "  check-lines                  - Check Vegas line coverage"
echo "  check-grading                - Check grading completeness"
echo "  full-deploy <service>        - Run full deployment workflow"
echo "  rollback <service>           - Show rollback instructions"
echo ""
echo "Example usage:"
echo "  pre-deploy prediction-worker"
echo "  deployed-commit prediction-worker"
echo "  health-check prediction-worker"
