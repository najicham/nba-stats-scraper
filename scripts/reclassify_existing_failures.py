#!/usr/bin/env python3
"""
Reclassify existing precompute_failures records with DNP vs DATA_GAP classification.

This script updates existing failure records that have failure_type=NULL by:
1. Querying unclassified INCOMPLETE_DATA failures
2. Using CompletenessChecker to classify each as PLAYER_DNP, DATA_GAP, MIXED, or COMPLETE
3. Updating the records in BigQuery with the classification

Usage:
    # Dry run (no updates)
    python scripts/reclassify_existing_failures.py --dry-run

    # Reclassify all unclassified failures
    python scripts/reclassify_existing_failures.py

    # Reclassify specific processor
    python scripts/reclassify_existing_failures.py --processor PlayerDailyCacheProcessor

    # Reclassify specific date range
    python scripts/reclassify_existing_failures.py --start-date 2021-12-01 --end-date 2021-12-31

    # Limit batch size
    python scripts/reclassify_existing_failures.py --batch-size 100
"""

import argparse
import logging
from datetime import date, datetime
from typing import Optional
from google.cloud import bigquery

from shared.utils.completeness_checker import CompletenessChecker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='Reclassify existing failure records')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be done without updating')
    parser.add_argument('--processor', type=str, help='Filter by processor name')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--batch-size', type=int, default=500, help='Number of records to process per batch')
    parser.add_argument('--project-id', type=str, default='nba-props-platform', help='GCP project ID')
    return parser.parse_args()


def get_unclassified_failures(
    bq_client: bigquery.Client,
    processor: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 500
) -> list:
    """Query unclassified INCOMPLETE_DATA failures."""

    # Only player-based processors can be classified for DNP detection
    player_processors = [
        'PlayerDailyCacheProcessor',
        'PlayerShotZoneAnalysisProcessor',
        'PlayerCompositFactorsProcessor',
        'MLFeatureStoreProcessor'
    ]

    where_clauses = [
        "failure_category = 'INCOMPLETE_DATA'",
        "failure_type IS NULL",
        f"processor_name IN ({', '.join([repr(p) for p in player_processors])})"
    ]

    if processor:
        where_clauses.append(f"processor_name = '{processor}'")
    if start_date:
        where_clauses.append(f"analysis_date >= '{start_date}'")
    if end_date:
        where_clauses.append(f"analysis_date <= '{end_date}'")

    query = f"""
    SELECT
        processor_name,
        analysis_date,
        entity_id,
        failure_category,
        failure_reason,
        created_at
    FROM nba_processing.precompute_failures
    WHERE {' AND '.join(where_clauses)}
    ORDER BY analysis_date, processor_name
    LIMIT {batch_size}
    """

    logger.info(f"Querying unclassified failures...")
    result = bq_client.query(query).result(timeout=60)
    rows = list(result)
    logger.info(f"Found {len(rows)} unclassified failures")
    return rows


def classify_failures_batch(
    checker: CompletenessChecker,
    failures: list
) -> dict:
    """Classify a batch of failures using CompletenessChecker."""

    # Group failures by analysis_date for efficient batch processing
    by_date = {}
    for f in failures:
        analysis_date = f.analysis_date
        if analysis_date not in by_date:
            by_date[analysis_date] = []
        by_date[analysis_date].append(f)

    classifications = {}

    for analysis_date, date_failures in by_date.items():
        logger.info(f"Classifying {len(date_failures)} failures for {analysis_date}")

        # Get player game dates for all players in this batch
        player_lookups = [f.entity_id for f in date_failures]

        try:
            game_dates = checker.get_player_game_dates_batch(
                player_lookups=player_lookups,
                analysis_date=analysis_date,
                lookback_days=14
            )

            # Classify each failure
            for f in date_failures:
                player_lookup = f.entity_id
                key = (f.processor_name, str(analysis_date), player_lookup)

                if player_lookup not in game_dates:
                    classifications[key] = {
                        'failure_type': 'UNKNOWN',
                        'is_correctable': None,
                        'expected_game_count': None,
                        'actual_game_count': None
                    }
                    continue

                player_data = game_dates[player_lookup]
                expected = player_data.get('expected_games', [])
                actual = player_data.get('actual_games', [])

                if len(expected) == 0:
                    # No expected games - can't classify
                    classifications[key] = {
                        'failure_type': 'INSUFFICIENT_HISTORY',
                        'is_correctable': False,
                        'expected_game_count': 0,
                        'actual_game_count': len(actual)
                    }
                elif len(actual) >= len(expected):
                    # Actually complete
                    classifications[key] = {
                        'failure_type': 'COMPLETE',
                        'is_correctable': False,
                        'expected_game_count': len(expected),
                        'actual_game_count': len(actual)
                    }
                else:
                    # Use full classification
                    result = checker.classify_failure(
                        player_lookup=player_lookup,
                        analysis_date=analysis_date,
                        expected_games=expected,
                        actual_games=actual,
                        check_raw_data=True
                    )
                    classifications[key] = {
                        'failure_type': result['failure_type'],
                        'is_correctable': result['is_correctable'],
                        'expected_game_count': len(expected),
                        'actual_game_count': len(actual)
                    }

        except Exception as e:
            logger.error(f"Error classifying failures for {analysis_date}: {e}")
            for f in date_failures:
                key = (f.processor_name, str(f.analysis_date), f.entity_id)
                classifications[key] = {
                    'failure_type': 'ERROR',
                    'is_correctable': None,
                    'expected_game_count': None,
                    'actual_game_count': None
                }

    return classifications


def update_failures_in_bq(
    bq_client: bigquery.Client,
    failures: list,
    classifications: dict,
    dry_run: bool = False
) -> tuple:
    """Update failure records in BigQuery with classification data."""

    updated = 0
    skipped = 0

    for f in failures:
        key = (f.processor_name, str(f.analysis_date), f.entity_id)

        if key not in classifications:
            skipped += 1
            continue

        c = classifications[key]

        if c['failure_type'] in ['UNKNOWN', 'ERROR']:
            skipped += 1
            continue

        if dry_run:
            logger.info(f"[DRY RUN] Would update {f.entity_id} on {f.analysis_date}: {c['failure_type']} (correctable={c['is_correctable']})")
            updated += 1
            continue

        # Build UPDATE query
        update_query = f"""
        UPDATE nba_processing.precompute_failures
        SET
            failure_type = '{c['failure_type']}',
            is_correctable = {str(c['is_correctable']).lower() if c['is_correctable'] is not None else 'NULL'},
            expected_game_count = {c['expected_game_count'] if c['expected_game_count'] is not None else 'NULL'},
            actual_game_count = {c['actual_game_count'] if c['actual_game_count'] is not None else 'NULL'}
        WHERE
            processor_name = '{f.processor_name}'
            AND analysis_date = '{f.analysis_date}'
            AND entity_id = '{f.entity_id}'
            AND failure_type IS NULL
        """

        try:
            bq_client.query(update_query).result(timeout=60)
            updated += 1
        except Exception as e:
            logger.error(f"Error updating {key}: {e}")
            skipped += 1

    return updated, skipped


def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("FAILURE RECLASSIFICATION SCRIPT")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - No updates will be made")

    # Initialize clients
    bq_client = bigquery.Client(project=args.project_id)
    checker = CompletenessChecker(bq_client, args.project_id)

    total_updated = 0
    total_skipped = 0
    batch_num = 0

    # Safety guard: prevent infinite batch processing loops
    max_batches = 1000  # Should be plenty for any reasonable reclassification

    while True:
        batch_num += 1
        if batch_num > max_batches:
            logger.warning(f"Reached maximum batch limit ({max_batches}), stopping")
            break

        logger.info(f"\n--- Batch {batch_num} ---")

        # Get unclassified failures
        failures = get_unclassified_failures(
            bq_client,
            processor=args.processor,
            start_date=args.start_date,
            end_date=args.end_date,
            batch_size=args.batch_size
        )

        if not failures:
            logger.info("No more unclassified failures found")
            break

        # Classify failures
        classifications = classify_failures_batch(checker, failures)

        # Print summary
        type_counts = {}
        for c in classifications.values():
            ft = c['failure_type']
            type_counts[ft] = type_counts.get(ft, 0) + 1

        logger.info(f"Classification summary: {type_counts}")

        # Update records
        updated, skipped = update_failures_in_bq(
            bq_client, failures, classifications, dry_run=args.dry_run
        )

        total_updated += updated
        total_skipped += skipped

        logger.info(f"Batch {batch_num}: Updated {updated}, Skipped {skipped}")

        # In dry run, only do one batch
        if args.dry_run:
            break

    logger.info("\n" + "=" * 60)
    logger.info("RECLASSIFICATION COMPLETE")
    logger.info(f"Total updated: {total_updated}")
    logger.info(f"Total skipped: {total_skipped}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
