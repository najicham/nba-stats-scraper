#!/usr/bin/env python3
"""
Referee Data Backfill Script                                    v1.0 - 2026-03-04
---------------------------------------------------------------------------------
Convenience wrapper to reprocess referee data from GCS into BigQuery.

The referee processor (NbacRefereeProcessor) was missing load_data() until
Session 402. ~59 dates of GCS files from December 2025 onward need reprocessing.

This script can run locally or trigger the existing Cloud Run backfill job.

Usage:
  # Local: Process all files from Dec 2025 onward
  PYTHONPATH=. python bin/backfill_referee_data.py --start-date 2025-12-01

  # Local: Dry run to see what files exist
  PYTHONPATH=. python bin/backfill_referee_data.py --start-date 2025-12-01 --dry-run

  # Local: Process specific date range
  PYTHONPATH=. python bin/backfill_referee_data.py --start-date 2025-12-01 --end-date 2026-01-31

  # Cloud Run: Trigger existing backfill job
  PYTHONPATH=. python bin/backfill_referee_data.py --cloud-run
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

from google.cloud import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

GCS_BUCKET = "nba-scraped-data"
GCS_PREFIX = "nba-com/referee-assignments"
CLOUD_RUN_JOB = "nbac-referee-processor-backfill"
REGION = "us-west2"


def list_gcs_files(start_date: date, end_date: date) -> list[str]:
    """List referee assignment files in GCS within date range."""
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    files = []

    current = start_date
    while current <= end_date:
        prefix = f"{GCS_PREFIX}/{current.strftime('%Y-%m-%d')}/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        for blob in blobs:
            if blob.name.endswith(".json"):
                files.append(blob.name)
        current += timedelta(days=1)

    return sorted(files)


def process_local(start_date: date, end_date: date, dry_run: bool = False) -> None:
    """Process referee files locally using the processor directly."""
    files = list_gcs_files(start_date, end_date)
    logger.info("Found %d referee JSON files in GCS (%s to %s)", len(files), start_date, end_date)

    if not files:
        logger.warning("No files found. Check GCS path: gs://%s/%s/", GCS_BUCKET, GCS_PREFIX)
        return

    if dry_run:
        for f in files:
            logger.info("  [DRY RUN] Would process: gs://%s/%s", GCS_BUCKET, f)
        logger.info("Dry run complete. %d files would be processed.", len(files))
        return

    # Import processor
    from data_processors.raw.nbacom.nbac_referee_processor import NbacRefereeProcessor

    success = 0
    errors = 0

    for i, file_path in enumerate(files, 1):
        logger.info("[%d/%d] Processing: %s", i, len(files), file_path)
        try:
            # Load JSON from GCS
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET)
            blob = bucket.blob(file_path)
            raw_data = json.loads(blob.download_as_text())

            # Extract date from path: .../2025-12-01/timestamp.json
            parts = file_path.split("/")
            game_date = None
            for part in parts:
                try:
                    game_date = datetime.strptime(part, "%Y-%m-%d").strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

            if not game_date:
                logger.warning("Could not extract date from path: %s", file_path)
                errors += 1
                continue

            # Process via the processor
            processor = NbacRefereeProcessor()
            processor.raw_data = raw_data
            processor.game_date = game_date
            processor.gcs_path = f"gs://{GCS_BUCKET}/{file_path}"
            processor.transform_data()
            processor.save_data()
            success += 1
            logger.info("  -> Success: %d records", len(processor.records) if hasattr(processor, 'records') else 0)

        except Exception as e:
            logger.error("  -> Error processing %s: %s", file_path, e)
            errors += 1

    logger.info("Backfill complete: %d success, %d errors out of %d files", success, errors, len(files))


def trigger_cloud_run() -> None:
    """Trigger the existing Cloud Run backfill job."""
    cmd = [
        "gcloud", "run", "jobs", "execute", CLOUD_RUN_JOB,
        f"--region={REGION}",
        "--args=--start-date=2025-12-01",
    ]
    logger.info("Triggering Cloud Run job: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        logger.info("Cloud Run job triggered successfully")
        logger.info(result.stdout)
    else:
        logger.error("Failed to trigger Cloud Run job: %s", result.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Backfill referee data from GCS to BigQuery")
    parser.add_argument("--start-date", default="2025-12-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=date.today().strftime("%Y-%m-%d"), help="End date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="List files without processing")
    parser.add_argument("--cloud-run", action="store_true", help="Trigger Cloud Run job instead of local processing")
    args = parser.parse_args()

    if args.cloud_run:
        trigger_cloud_run()
    else:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        process_local(start, end, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
