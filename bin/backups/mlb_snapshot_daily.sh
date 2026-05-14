#!/usr/bin/env bash
# Daily BQ snapshot of MLB critical pick tables.
#
# Why: BigQuery's built-in time-travel covers 7 days. Snapshots in
# `mlb_predictions_backups` extend that to 30+ days for forensic recovery
# when an incident isn't noticed within the time-travel window.
#
# Tables:
#   - mlb_predictions.prediction_accuracy  (grading results, source of truth)
#   - mlb_predictions.signal_best_bets_picks  (published BB picks)
#   - mlb_predictions.pitcher_strikeouts  (raw predictions)
#
# Snapshot table names: <table>_<UTC YYYYMMDD_HHMMSS>
#
# Retention: snapshots get a 30-day expiration via the `expiration` option.
# After expiry, BQ auto-drops them. To keep one longer, copy it out of the
# dataset before its expiration.
#
# Wire to Cloud Scheduler:
#   gcloud scheduler jobs create http mlb-bq-snapshot-daily \
#     --schedule="0 11 * * *" --time-zone="America/New_York" \
#     --uri="..." --http-method=POST --oidc-service-account-email=...
# Or run locally / from CI as a smoke test.

set -e

PROJECT="${PROJECT:-nba-props-platform}"
SRC_DATASET="${SRC_DATASET:-mlb_predictions}"
DEST_DATASET="${DEST_DATASET:-mlb_predictions_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

TABLES=(
    prediction_accuracy
    signal_best_bets_picks
    pitcher_strikeouts
)

TS=$(date -u +%Y%m%d_%H%M%S)
# Snapshots are point-in-time references — they don't take long but they
# do hold a reference into time-travel storage. Use expiration to age out.
EXPIRY_EPOCH=$(( $(date -u +%s) + RETENTION_DAYS * 86400 ))
EXPIRY_MS=$(( EXPIRY_EPOCH * 1000 ))

echo "Daily MLB BQ snapshot — $TS UTC"
echo "  Project: $PROJECT"
echo "  Source:  $SRC_DATASET → $DEST_DATASET"
echo "  Retain:  $RETENTION_DAYS days (until $(date -u -d @$EXPIRY_EPOCH '+%Y-%m-%d %H:%M:%S UTC'))"
echo ""

for TBL in "${TABLES[@]}"; do
    DEST="${TBL}_${TS}"
    echo "Snapshotting $SRC_DATASET.$TBL → $DEST_DATASET.$DEST"
    bq cp --snapshot --no_clobber \
        "${PROJECT}:${SRC_DATASET}.${TBL}" \
        "${PROJECT}:${DEST_DATASET}.${DEST}"

    # Apply expiration so old snapshots auto-drop.
    bq update --expiration "$RETENTION_DAYS" \
        "${PROJECT}:${DEST_DATASET}.${DEST}" >/dev/null 2>&1 || \
        bq update --expiration_ms "$EXPIRY_MS" \
            "${PROJECT}:${DEST_DATASET}.${DEST}" >/dev/null 2>&1 || \
        echo "  (warning: could not set expiration on $DEST — manual cleanup needed)"
done

echo ""
echo "Current snapshot inventory:"
bq ls --max_results=50 "${PROJECT}:${DEST_DATASET}" | tail -20
