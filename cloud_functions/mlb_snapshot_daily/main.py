"""Daily BigQuery snapshot of MLB critical pick tables.

Python port of bin/backups/mlb_snapshot_daily.sh — the shell version was
manual-only because Cloud Scheduler can't shell out. This Gen2 HTTP CF
runs the snapshot DDL via the BQ Python client.

Tables snapshotted into `mlb_predictions_backups` (separate dataset, 30-day
expiration). Naming: `<table>_<UTC YYYYMMDD_HHMMSS>`.
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
SRC_DATASET = os.environ.get("SRC_DATASET", "mlb_predictions")
DEST_DATASET = os.environ.get("DEST_DATASET", "mlb_predictions_backups")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))

TABLES = [
    "prediction_accuracy",
    "signal_best_bets_picks",
    "pitcher_strikeouts",
]


@functions_framework.http
def mlb_snapshot_daily(request):
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
