"""
Cloud Function to execute BigQuery table backups (Gen2).
Triggered daily by Cloud Scheduler.

Rewritten 2026-02-12 (Session 218) to use Python client libraries
instead of shell commands (gcloud/bq/gsutil not available in CF runtime).
"""
import json
import logging
from datetime import datetime, timezone

import functions_framework
from flask import jsonify
from google.cloud import bigquery, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
BACKUP_BUCKET = "nba-bigquery-backups"

PHASE3_TABLES = [
    "nba_analytics.player_game_summary",
    "nba_analytics.team_offense_game_summary",
    "nba_analytics.team_defense_game_summary",
    "nba_analytics.upcoming_player_game_context",
    "nba_analytics.upcoming_team_game_context",
]

PHASE4_TABLES = [
    "nba_precompute.player_composite_factors",
    "nba_precompute.player_shot_zone_analysis",
    "nba_precompute.team_defense_zone_analysis",
    "nba_precompute.player_daily_cache",
]

ORCHESTRATION_TABLES = [
    "nba_orchestration.processor_output_validation",
    "nba_orchestration.workflow_decisions",
]


def ensure_bucket(gcs_client):
    """Create backup bucket if it doesn't exist."""
    try:
        bucket = gcs_client.get_bucket(BACKUP_BUCKET)
        logger.info(f"Backup bucket exists: gs://{BACKUP_BUCKET}")
    except Exception:
        logger.info(f"Creating backup bucket: gs://{BACKUP_BUCKET}")
        bucket = gcs_client.create_bucket(BACKUP_BUCKET, location="US")
        bucket.add_lifecycle_delete_rule(age=90)
        bucket.patch()
        logger.info("Lifecycle policy set: delete after 90 days")
    return bucket


def export_table(bq_client, gcs_client, table_full_name, export_path, description):
    """Export a single BigQuery table to GCS in AVRO format."""
    logger.info(f"Exporting {description}: {table_full_name}")

    table_ref = f"{PROJECT_ID}.{table_full_name}"

    # Check if table exists and get row count
    try:
        table = bq_client.get_table(table_ref)
        row_count = table.num_rows
        logger.info(f"  Row count: {row_count}")
    except Exception as e:
        logger.warning(f"  Table not found: {table_full_name} (skipping): {e}")
        return False

    # Export to GCS (AVRO + SNAPPY)
    destination_uri = f"gs://{BACKUP_BUCKET}/{export_path}/*.avro"
    job_config = bigquery.ExtractJobConfig(
        destination_format=bigquery.DestinationFormat.AVRO,
        compression=bigquery.Compression.SNAPPY,
    )

    try:
        extract_job = bq_client.extract_table(
            table_ref,
            destination_uri,
            job_config=job_config,
        )
        extract_job.result()  # Wait for completion
        logger.info(f"  Export successful: gs://{BACKUP_BUCKET}/{export_path}")
    except Exception as e:
        logger.error(f"  Export failed: {table_full_name}: {e}")
        return False

    # Write metadata
    metadata = {
        "table": table_full_name,
        "export_date": datetime.now(timezone.utc).isoformat(),
        "row_count": row_count,
        "export_path": f"gs://{BACKUP_BUCKET}/{export_path}",
        "format": "AVRO",
        "compression": "SNAPPY",
    }

    bucket = gcs_client.bucket(BACKUP_BUCKET)
    blob = bucket.blob(f"{export_path}/_metadata.json")
    blob.upload_from_string(json.dumps(metadata, indent=2), content_type="application/json")

    return True


@functions_framework.http
def backup_bigquery_tables(request):
    """HTTP Cloud Function to execute BigQuery backup."""
    try:
        backup_type = request.args.get("type", "daily")
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        logger.info(f"Starting BigQuery backup (type: {backup_type})")

        bq_client = bigquery.Client(project=PROJECT_ID)
        gcs_client = storage.Client(project=PROJECT_ID)

        ensure_bucket(gcs_client)

        export_base = f"{backup_type}/{date_str}"
        success_count = 0
        failure_count = 0

        all_tables = [
            ("phase3", PHASE3_TABLES),
            ("phase4", PHASE4_TABLES),
            ("orchestration", ORCHESTRATION_TABLES),
        ]

        for phase_name, tables in all_tables:
            logger.info(f"--- {phase_name.title()} Tables ---")
            for table in tables:
                table_name = table.split(".")[1]
                export_path = f"{export_base}/{phase_name}/{table_name}"

                if export_table(bq_client, gcs_client, table, export_path, f"{phase_name} - {table_name}"):
                    success_count += 1
                else:
                    failure_count += 1

        # Upload index file
        index_text = (
            f"NBA Stats Scraper - BigQuery Backup\n"
            f"====================================\n"
            f"Date: {datetime.now(timezone.utc).isoformat()}\n"
            f"Backup Type: {backup_type}\n"
            f"Project: {PROJECT_ID}\n"
            f"Location: gs://{BACKUP_BUCKET}/{export_base}\n\n"
            f"Tables Exported: {success_count}\n"
            f"Tables Failed: {failure_count}\n"
        )
        bucket = gcs_client.bucket(BACKUP_BUCKET)
        blob = bucket.blob(f"{export_base}/_BACKUP_INDEX.txt")
        blob.upload_from_string(index_text, content_type="text/plain")

        logger.info(f"Backup complete: {success_count} succeeded, {failure_count} failed")

        status_code = 200 if failure_count == 0 else 207
        return jsonify({
            "status": "success" if failure_count == 0 else "partial",
            "message": f"Backup completed: {success_count} succeeded, {failure_count} failed",
            "backup_type": backup_type,
            "success_count": success_count,
            "failure_count": failure_count,
            "export_base": f"gs://{BACKUP_BUCKET}/{export_base}",
        }), status_code

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
