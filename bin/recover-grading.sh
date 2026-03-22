#!/bin/bash
# bin/recover-grading.sh — Automated grading backfill for multi-day outages
#
# Automates the 8-step manual recovery process from Session 478.
#
# Usage:
#   ./bin/recover-grading.sh 2026-03-16 2026-03-21          # recover a date range
#   ./bin/recover-grading.sh 2026-03-19 2026-03-19          # single date
#
# What it does (in dependency order):
#   Phase A: Trigger grading for all dates via Pub/Sub
#   Phase B: Poll prediction_accuracy until graded records appear
#   Phase C: Trigger post_grading_export for each graded date
#            (which runs signal_health, model_performance, league_macro, picks export)
#   Phase D: Trigger Phase 6 export for the latest date
#   Phase E: Verify all downstream tables were populated
#
# If post_grading_export CF is broken, uncomment the fallback local commands in Phase C.

set -euo pipefail

PROJECT_ID="nba-props-platform"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

DATE_START="${1:?Usage: $0 DATE_START DATE_END (e.g. 2026-03-16 2026-03-21)}"
DATE_END="${2:?Usage: $0 DATE_START DATE_END (e.g. 2026-03-16 2026-03-21)}"

echo "=== Grading Recovery: ${DATE_START} → ${DATE_END} ==="
echo "Project: ${PROJECT_ID}"
echo ""

# Generate date list
DATES=()
current="$DATE_START"
while [[ "$current" < "$DATE_END" ]] || [[ "$current" == "$DATE_END" ]]; do
    DATES+=("$current")
    current=$(date -I -d "$current + 1 day")
done
echo "Dates to recover (${#DATES[@]}): ${DATES[*]}"
echo ""

# Helper: query BQ and return count
bq_count() {
    bq query --use_legacy_sql=false --format=csv --quiet "$1" 2>/dev/null | tail -1
}

# --- PHASE A: Trigger grading for all dates ---
echo "=== Phase A: Triggering grading ==="
for d in "${DATES[@]}"; do
    echo "  → Triggering grading for $d ..."
    gcloud pubsub topics publish nba-grading-trigger \
        --project="$PROJECT_ID" \
        --message="{\"target_date\":\"$d\",\"force\":true,\"trigger_source\":\"recover-grading-sh\"}"
    sleep 2  # avoid Pub/Sub rate limits
done
echo "  All grading triggers sent."
echo ""

# --- PHASE B: Poll for grading completion ---
echo "=== Phase B: Waiting for grading records ==="
MAX_WAIT=600  # 10 minutes per date
POLL_INTERVAL=20
GRADED_DATES=()
SKIPPED_DATES=()

for d in "${DATES[@]}"; do
    echo -n "  Waiting for $d ..."
    elapsed=0
    found=false
    while [ $elapsed -lt $MAX_WAIT ]; do
        count=$(bq_count "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_predictions.prediction_accuracy\` WHERE game_date = '$d' AND prediction_correct IS NOT NULL")
        if [ "$count" -gt 0 ] 2>/dev/null; then
            echo " done ($count graded records)"
            GRADED_DATES+=("$d")
            found=true
            break
        fi
        sleep $POLL_INTERVAL
        elapsed=$((elapsed + POLL_INTERVAL))
        echo -n "."
    done
    if [ "$found" = false ]; then
        echo " TIMEOUT — no records after ${MAX_WAIT}s. Check phase5b-grading CF logs."
        SKIPPED_DATES+=("$d")
    fi
done
echo ""

if [ ${#SKIPPED_DATES[@]} -gt 0 ]; then
    echo "  WARNING: Timed out waiting for: ${SKIPPED_DATES[*]}"
    echo "  These dates may have no games, or grading CF may still be failing."
    echo "  Check: gcloud functions logs read phase5b-grading --region=us-west2 --project=${PROJECT_ID} --limit=50"
    echo ""
fi

if [ ${#GRADED_DATES[@]} -eq 0 ]; then
    echo "  ERROR: No dates graded. Aborting — check grading CF logs."
    exit 1
fi

# --- PHASE C: Trigger post_grading_export for each graded date ---
echo "=== Phase C: Running post-grading analytics ==="
for d in "${GRADED_DATES[@]}"; do
    graded_count=$(bq_count "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_predictions.prediction_accuracy\` WHERE game_date = '$d' AND prediction_correct IS NOT NULL")
    echo "  → post_grading_export for $d (graded_count=$graded_count) ..."

    # Trigger post_grading_export via Pub/Sub (runs signal_health, model_performance, league_macro, picks exports)
    # NOTE: message MUST have target_date + status=success for picks exports to run
    gcloud pubsub topics publish nba-grading-complete \
        --project="$PROJECT_ID" \
        --message="{\"target_date\":\"$d\",\"status\":\"success\",\"graded_count\":$graded_count,\"trigger_source\":\"recover-grading-sh\"}"

    # Allow CF time to start processing before triggering the next date
    sleep 5

    # --- FALLBACK: Run analytics locally if the CF is broken ---
    # Uncomment these if post_grading_export CF is broken and you need immediate results:
    #
    # echo "    Running signal_health locally..."
    # PYTHONPATH=. .venv/bin/python3 ml/signals/signal_health.py --date "$d"
    #
    # echo "    Running league_macro locally..."
    # PYTHONPATH=. .venv/bin/python3 ml/analysis/league_macro.py --backfill --start "$d" --end "$d"
done
echo ""

# Wait for post-grading analytics to complete (give CFs time to run)
echo "  Waiting 90s for post-grading analytics CFs to complete..."
sleep 90
echo ""

# --- PHASE D: Trigger Phase 6 export for latest date ---
LATEST_DATE="${GRADED_DATES[-1]}"
echo "=== Phase D: Phase 6 export for ${LATEST_DATE} ==="
gcloud pubsub topics publish nba-phase6-export-trigger \
    --project="$PROJECT_ID" \
    --message="{\"export_types\":[\"signal-best-bets\"],\"target_date\":\"${LATEST_DATE}\"}"
echo "  Phase 6 trigger sent."
echo ""

# --- PHASE E: Verification ---
echo "=== Phase E: Verification ==="
echo ""
printf "  %-12s %8s %15s %14s %13s\n" "Date" "Graded" "Signal Health" "League Macro" "BB Picks"
printf "  %-12s %8s %15s %14s %13s\n" "----" "------" "-------------" "------------" "--------"

all_ok=true
for d in "${GRADED_DATES[@]}"; do
    graded=$(bq_count "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_predictions.prediction_accuracy\` WHERE game_date = '$d' AND prediction_correct IS NOT NULL" || echo "err")
    signal=$(bq_count "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_predictions.signal_health_daily\` WHERE game_date = '$d'" || echo "err")
    macro=$(bq_count "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_predictions.league_macro_daily\` WHERE game_date = '$d'" || echo "err")
    picks=$(bq_count "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_predictions.signal_best_bets_picks\` WHERE game_date = '$d' AND actual_points IS NOT NULL" || echo "err")

    graded_ok=$([[ "$graded" -gt 0 ]] 2>/dev/null && echo "✓" || echo "✗")
    signal_ok=$([[ "$signal" -gt 0 ]] 2>/dev/null && echo "✓" || echo "✗")
    macro_ok=$([[ "$macro" -gt 0 ]] 2>/dev/null && echo "✓" || echo "-")  # may be N/A for LGBM-only dates
    picks_ok=$([[ "$picks" -gt 0 ]] 2>/dev/null && echo "✓" || echo "-")  # may be 0 picks legitimately

    printf "  %-12s %8s %15s %14s %13s\n" \
        "$d" "${graded_ok} ${graded}" "${signal_ok} ${signal}" "${macro_ok} ${macro}" "${picks_ok} ${picks}"

    if [[ "$graded_ok" == "✗" ]] || [[ "$signal_ok" == "✗" ]]; then
        all_ok=false
    fi
done
echo ""

if [ "$all_ok" = true ]; then
    echo "  ✅ Recovery complete — all required tables populated."
else
    echo "  ⚠️  Some tables still missing data. Check logs:"
    echo "     gcloud functions logs read post-grading-export --region=us-west2 --project=${PROJECT_ID} --limit=50"
fi

echo ""
echo "UI JSON status:"
gsutil ls -l "gs://${PROJECT_ID}-api/v1/signal-best-bets/" 2>/dev/null | tail -3 || echo "  (gsutil ls failed)"
