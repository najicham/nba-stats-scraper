#!/bin/bash
# Restore a BigQuery snapshot from nba_predictions_backups (or mlb equivalent)
# into a *_dr_test_<date> table for validation. Used by the DR runbook.
#
# Snapshots are written daily 11 AM ET by `nba-snapshot-daily` /
# `mlb-snapshot-daily` Cloud Functions; retention is 30 days.
#
# Usage:
#   bin/operations/dr_restore_snapshot.sh <table_name> [snapshot_timestamp]
#
# Examples:
#   # Latest snapshot of ml_feature_store_v2 into nba_predictions_backups.ml_feature_store_v2_dr_test_<date>
#   bin/operations/dr_restore_snapshot.sh ml_feature_store_v2
#
#   # Specific snapshot timestamp (UTC YYYYMMDD_HHMMSS suffix)
#   bin/operations/dr_restore_snapshot.sh prediction_accuracy 20260515_150003
#
#   # MLB dataset
#   DATASET=mlb_predictions_backups bin/operations/dr_restore_snapshot.sh mlb_predictions
#
# Drill verified 2026-05-15: ml_feature_store_v2 (1GB / 147K rows) cloned in 3s.
# CLONE is metadata-only — restore time is independent of table size.
#
# Restored table auto-expires in 24h to keep the backups dataset tidy.
set -euo pipefail

TABLE="${1:-}"
TS="${2:-}"
PROJECT="${PROJECT:-nba-props-platform}"
DATASET="${DATASET:-nba_predictions_backups}"
DEST_DATE="$(date +%Y%m%d)"

if [[ -z "$TABLE" ]]; then
  echo "ERROR: table_name required."
  echo "Usage: $0 <table_name> [snapshot_timestamp]"
  exit 1
fi

if [[ -z "$TS" ]]; then
  echo "Finding latest snapshot for ${DATASET}.${TABLE}..."
  TS=$(bq ls --max_results=200 --format=json "${PROJECT}:${DATASET}" \
    | python3 -c "
import json, sys
rows = json.load(sys.stdin)
prefix = '${TABLE}_'
snaps = sorted(
    (r['tableReference']['tableId'] for r in rows
     if r['tableReference']['tableId'].startswith(prefix)),
    reverse=True,
)
if not snaps:
    sys.exit('No snapshots found for prefix ' + prefix)
# Snapshot id format: <table>_YYYYMMDD_HHMMSS — strip prefix
print(snaps[0][len(prefix):])
")
  echo "Latest snapshot timestamp: $TS"
fi

SRC="${PROJECT}:${DATASET}.${TABLE}_${TS}"
DEST="${PROJECT}:${DATASET}.${TABLE}_dr_test_${DEST_DATE}"
SRC_FQ="${PROJECT}.${DATASET}.${TABLE}_${TS}"
DEST_FQ="${PROJECT}.${DATASET}.${TABLE}_dr_test_${DEST_DATE}"

echo
echo "Planned restore:"
echo "  source:      $SRC"
echo "  destination: $DEST"
echo "  retention:   24h auto-expire on destination"
echo
read -r -p "Proceed? [y/N] " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

START=$(date +%s)
bq query --use_legacy_sql=false --quiet --format=none "
CREATE TABLE \`${DEST_FQ}\`
CLONE \`${SRC_FQ}\`
OPTIONS (
  expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 DAY),
  description = 'DR drill / restore from ${TABLE}_${TS} on $(date -Iseconds)'
)
"
END=$(date +%s)
echo "Restore complete in $((END - START))s: $DEST"

echo
echo "Validation: row counts (snapshot vs restore vs live)"
LIVE_DATASET="${LIVE_DATASET:-nba_predictions}"
bq query --use_legacy_sql=false --format=pretty "
SELECT 'snapshot' AS source, COUNT(*) AS row_count
FROM \`${SRC_FQ}\`
UNION ALL
SELECT 'restored', COUNT(*) FROM \`${DEST_FQ}\`
UNION ALL
SELECT 'live', COUNT(*) FROM \`${PROJECT}.${LIVE_DATASET}.${TABLE}\`
ORDER BY source
"

echo
echo "Next steps:"
echo "  - Inspect: bq head ${DEST}"
echo "  - To promote into live: bq cp -f ${DEST_FQ} ${PROJECT}:${LIVE_DATASET}.${TABLE}"
echo "    (irreversible — confirm row counts above first)"
echo "  - To clean up early: bq rm -f -t ${DEST}"
