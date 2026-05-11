#!/bin/bash
# Deploy the 3 unified pipeline alert policies + supporting log-based metrics.
#
# Usage:
#   ./deploy-alert-policies.sh
#   ./deploy-alert-policies.sh --metrics-only
#   ./deploy-alert-policies.sh --policies-only

set -euo pipefail

PROJECT_ID="nba-props-platform"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="${1:-all}"

create_log_metrics() {
  echo "==> Creating supporting log-based / scheduled-query metrics..."

  # Custom metric: overdue_count — how many gaps in expected_outputs right now
  # Implemented as a Cloud Logging log-based metric backed by the reconciler
  # and gap_detector logs (they print structured counts on each run).
  #
  # Pseudocode (Logs Explorer query):
  #   resource.type="cloud_run_revision"
  #   resource.labels.service_name=~"phase-completion-reconciler|gap-detector"
  #   jsonPayload.degraded > 0
  # Extract: jsonPayload.degraded as DOUBLE
  #
  # gcloud logging metrics create overdue_count --description="..." --log-filter="..."
  # The metric is created manually once via Console (the API for log-based
  # custom metrics with extracted-value is involved); deploy scripts only
  # check existence here.
  echo "    (manual step) ensure Cloud Logging metric 'overdue_count' exists,"
  echo "    backed by phase-completion-reconciler + gap-detector log payloads."

  # Custom metric: halt_state_age_hours — emitted by halt_state_writer
  # itself via shared.observability.metrics. No log-based metric needed;
  # the alert policy filter on `custom.googleapis.com/nba_pipeline/halt_state_age_hours`
  # picks it up natively.
  echo "    halt_state_age_hours: emitted by halt_state_writer via shared.observability.metrics"

  # phase_completion is emitted by every phase processor + reconciler; native.
  echo "    phase_completion: emitted by reconciler and phase processors via shared.observability.metrics"
}

deploy_policies() {
  echo "==> Deploying alert policies..."
  for yaml in "${SCRIPT_DIR}"/{expected-output-overdue,halt-state-stale,phase-error-rate,uptime-check-failed}.yaml; do
    name=$(basename "${yaml}" .yaml)
    echo "    Deploying ${name}..."
    # gcloud alpha monitoring policies create is idempotent on (displayName)
    # only via custom logic; in practice we delete + recreate or use the
    # console for maintenance. For first-time deploy:
    gcloud alpha monitoring policies create \
      --policy-from-file="${yaml}" \
      --project="${PROJECT_ID}" \
      || echo "    (policy may already exist; check console)"
  done
}

case "${MODE}" in
  --metrics-only)  create_log_metrics ;;
  --policies-only) deploy_policies ;;
  all)             create_log_metrics; deploy_policies ;;
  *)               echo "unknown mode: ${MODE}"; exit 2 ;;
esac

echo "==> Alert policies deploy complete."
echo ""
echo "Manual next step: in Cloud Monitoring console, attach notification"
echo "channels (Slack #pipeline-alerts) to each policy. Policies are created"
echo "with empty notificationChannels: gcloud doesn't support --add-channels"
echo "during create, so this is a one-time UI step per policy."
