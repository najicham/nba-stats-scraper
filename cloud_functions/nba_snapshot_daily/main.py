"""Daily BigQuery snapshot of NBA critical pick/prediction tables.

Path C — backup coverage. Mirror of `cloud_functions/mlb_snapshot_daily`
covering the NBA-side tables that had ZERO snapshot coverage prior to
this CF: `prediction_accuracy` (419K rows), `signal_best_bets_picks`,
`player_prop_predictions`, `ml_feature_store_v2`. BQ's 7-day time-travel
is the only existing recovery layer for these tables; 30-day snapshots
in `nba_predictions_backups` extend the forensic window for incidents
like Sessions 412/468 that aren't caught within the time-travel window.

Naming: `<table>_<UTC YYYYMMDD_HHMMSS>`. 30-day expiry on each snapshot.
"""
import logging
import os
from datetime import datetime, timezone

import functions_framework
from flask import jsonify
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")
SRC_DATASET = os.environ.get("SRC_DATASET", "nba_predictions")
DEST_DATASET = os.environ.get("DEST_DATASET", "nba_predictions_backups")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))

TABLES = [
    "prediction_accuracy",
    "signal_best_bets_picks",
    "best_bets_published_picks",
    "player_prop_predictions",
    "ml_feature_store_v2",
]


@functions_framework.http
def nba_snapshot_daily(request):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bq = bigquery.Client(project=PROJECT_ID)

    succeeded = []
    failed = []

    for tbl in TABLES:
        dest = f"{tbl}_{ts}"
        sql = f"""
        CREATE SNAPSHOT TABLE `{PROJECT_ID}.{DEST_DATASET}.{dest}`
        CLONE `{PROJECT_ID}.{SRC_DATASET}.{tbl}`
        OPTIONS (
          expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {RETENTION_DAYS} DAY)
        )
        """
        try:
            bq.query(sql).result()
            logger.info(f"Snapshotted {SRC_DATASET}.{tbl} -> {DEST_DATASET}.{dest}")
            succeeded.append(dest)
        except Exception as e:
            logger.error(f"Snapshot failed for {tbl}: {e}")
            failed.append({"table": tbl, "error": str(e)})

    status = 200 if not failed else 207
    return jsonify({
        "status": "ok" if not failed else "partial",
        "timestamp": ts,
        "snapshots_created": succeeded,
        "failures": failed,
        "retention_days": RETENTION_DAYS,
    }), status
