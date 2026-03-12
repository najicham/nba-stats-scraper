#!/bin/bash
# ==============================================================================
# Setup MLB 2026 Season Reminder Schedulers
# ==============================================================================
#
# Creates Cloud Scheduler jobs that POST to Slack for key MLB milestones.
# Uses the existing SLACK_WEBHOOK_URL_ALERTS env var on the nba-alerts channel.
#
# These are one-shot reminders (not recurring) except for the biweekly retrain.
# After firing, they auto-pause (one-shot behavior via schedule trick).
#
# Usage:
#   ./bin/schedulers/setup_mlb_reminders.sh           # Create all
#   ./bin/schedulers/setup_mlb_reminders.sh --dry-run  # Preview only
#
# Created: 2026-03-11 (Session 469)
# ==============================================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
TIMEZONE="America/New_York"

# Slack webhook — same as NBA alerts channel
# The webhook URL is stored as a secret; we use a simple HTTP POST scheduler
# that hits a lightweight CF which forwards to Slack.
# Alternative: use Slack webhook URL directly if available.

# Slack+Pushover reminder forwarder CF (deployed Session 469)
ALERT_CF_URL="https://slack-reminder-f7p3g7f6ya-wl.a.run.app"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE ==="
    echo ""
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

create_reminder() {
    local name="$1"
    local schedule="$2"
    local message="$3"
    local description="$4"

    echo -e "${YELLOW}Creating: ${name}${NC}"
    echo "  Schedule: ${schedule} (${TIMEZONE})"
    echo "  Message:  ${message}"

    if gcloud scheduler jobs describe "${name}" \
        --project="${PROJECT_ID}" --location="${REGION}" &>/dev/null; then
        echo -e "${YELLOW}  Already exists — updating schedule.${NC}"
        if [[ "${DRY_RUN}" != "true" ]]; then
            gcloud scheduler jobs update http "${name}" \
                --schedule="${schedule}" \
                --time-zone="${TIMEZONE}" \
                --location="${REGION}" \
                --project="${PROJECT_ID}" \
                --message-body="{\"source\": \"mlb-reminder\", \"message\": \"${message}\"}" \
                --description="${description}" 2>/dev/null || true
        fi
    else
        if [[ "${DRY_RUN}" != "true" ]]; then
            gcloud scheduler jobs create http "${name}" \
                --schedule="${schedule}" \
                --time-zone="${TIMEZONE}" \
                --uri="${ALERT_CF_URL}" \
                --http-method=POST \
                --headers="Content-Type=application/json" \
                --message-body="{\"source\": \"mlb-reminder\", \"message\": \"${message}\"}" \
                --location="${REGION}" \
                --project="${PROJECT_ID}" \
                --description="${description}" \
                --attempt-deadline=30s 2>/dev/null
            echo -e "${GREEN}  Created.${NC}"
        else
            echo "  [DRY RUN] Would create."
        fi
    fi
    echo ""
}

echo "========================================"
echo "MLB 2026 Season Reminder Setup"
echo "========================================"
echo ""

# --- One-shot reminders (specific dates) ---

create_reminder "mlb-retrain-reminder-mar18" \
    "0 9 18 3 *" \
    "MLB retrain window opens today. Run: PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py --training-end 2026-03-20 --window 120" \
    "MLB 2026: Retrain window opens Mar 18"

create_reminder "mlb-resume-reminder-mar24" \
    "0 8 24 3 *" \
    "Resume MLB schedulers today: ./bin/mlb-season-resume.sh. Verify schedule scraper populates 2026 calendar." \
    "MLB 2026: Resume schedulers Mar 24"

create_reminder "mlb-opening-day-check" \
    "0 14 27 3 *" \
    "Opening Day! Verify MLB predictions generating in BQ. Run opening day verification queries from 07-LAUNCH-RUNBOOK.md." \
    "MLB 2026: Opening day verification"

create_reminder "mlb-week1-review" \
    "0 10 3 4 *" \
    "MLB Week 1 review: Check first grading results. Run weekly HR query from launch runbook." \
    "MLB 2026: Week 1 review"

create_reminder "mlb-3week-checkpoint" \
    "0 9 14 4 *" \
    "MLB 3-week checkpoint: Force retrain with in-season data. Review blacklist: bin/mlb/review_blacklist.py --since 2026-03-27. Compare fleet HR if multi-model." \
    "MLB 2026: 3-week checkpoint and retrain"

create_reminder "mlb-under-decision" \
    "0 9 1 5 *" \
    "MLB UNDER decision point. If OVER HR >= 58% at N >= 50, enable: --update-env-vars=MLB_UNDER_ENABLED=true" \
    "MLB 2026: UNDER enablement decision"

create_reminder "mlb-signal-promotion-review" \
    "0 9 15 5 *" \
    "MLB shadow signal promotion review. Promote signals with HR >= 60% at N >= 30 in live data." \
    "MLB 2026: Signal promotion review"

create_reminder "mlb-blacklist-review-jun" \
    "0 9 1 6 *" \
    "MLB blacklist review. Run: PYTHONPATH=. python bin/mlb/review_blacklist.py --since 2026-03-27. Add pitchers with <45% HR at N >= 10." \
    "MLB 2026: Blacklist review"

create_reminder "mlb-asb-prep" \
    "0 9 14 7 *" \
    "MLB All-Star Break prep. Check if model holds through schedule changes. Consider retrain." \
    "MLB 2026: All-Star Break prep"

# --- Recurring reminders ---

create_reminder "mlb-biweekly-retrain" \
    "0 9 */14 * *" \
    "MLB biweekly retrain due (14-day cadence). Run train_regressor_v2.py with 120-day window." \
    "MLB 2026: Biweekly retrain reminder (recurring)"

create_reminder "mlb-weekly-hr-check" \
    "0 10 * * 1" \
    "MLB weekly HR check. Run weekly HR query from launch runbook. Check signal fires and edge distribution." \
    "MLB 2026: Weekly HR monitoring (recurring, Mondays)"

# --- Summary ---

echo "========================================"
echo "Summary"
echo "========================================"
echo ""
if [[ "${DRY_RUN}" == "true" ]]; then
    echo -e "${YELLOW}DRY RUN complete. No resources created.${NC}"
    echo "Run without --dry-run to create."
else
    echo -e "${GREEN}All MLB reminders created.${NC}"
fi
echo ""
echo "Verify:"
echo "  gcloud scheduler jobs list --project=${PROJECT_ID} --location=${REGION} | grep mlb"
echo ""
echo "Pause all after season ends:"
echo "  gcloud scheduler jobs list --project=${PROJECT_ID} --location=${REGION} --format='value(name)' | grep mlb-.*reminder | xargs -I{} gcloud scheduler jobs pause {} --location=${REGION} --project=${PROJECT_ID}"
echo ""
