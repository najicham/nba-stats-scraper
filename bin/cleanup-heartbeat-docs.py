#!/usr/bin/env python3
"""
Cleanup Old Heartbeat Documents

This script removes heartbeat documents that use old doc_id formats
and keeps only the new format (processor_name).

Background:
- Old implementation created a new document for every processor run
- This resulted in 100k+ documents for just 30 unique processors
- New implementation uses processor_name as doc_id (one doc per processor)

Old formats detected (all cleaned):
- Date-based: ProcessorName_2026-01-31_abc123
- None-based: ProcessorName_None_abc123 (from backfill jobs)
- Year-based: ProcessorName_202601_abc123

New formats (kept):
- ProcessorName (e.g., PlayerGameSummaryProcessor)
- p2_tablename (e.g., p2_nba_raw.nbac_team_boxscore)

This script:
1. Queries all heartbeat documents
2. Identifies documents with old formats (date, _None_, _202)
3. Groups by processor name
4. Deletes old format documents in batches

Usage:
    python bin/cleanup-heartbeat-docs.py --dry-run  # Preview what will be deleted
    python bin/cleanup-heartbeat-docs.py            # Actually delete

Created: 2026-02-01
Updated: 2026-02-01 (Session 63 Part 2 - Added _None_ and _202 detection)
"""

import argparse
import logging
from datetime import datetime, timezone
from collections import defaultdict
from google.cloud import firestore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_old_format_doc_id(doc_id: str) -> bool:
    """
    Check if document ID uses old format.

    Old format examples (all to be cleaned):
    - PlayerGameSummaryProcessor_2026-01-31_abc123  (date-based)
    - NbacTeamBoxscoreProcessor_None_097ffc9c       (_None_ format from backfill jobs)
    - BettingPropsProcessor_2026_abc123             (year-based)
    - SomeProcessor_202601_abc123                   (_202 prefix from timestamps)

    New format examples (keep):
    - PlayerGameSummaryProcessor
    - p2_nba_raw.nbac_team_boxscore
    - AsyncUpcomingPlayerGameContextProcessor
    """
    # Pattern 1: Contains "_None_" (from backfill jobs)
    if '_None_' in doc_id:
        return True

    # Pattern 2: Contains "_202" (year prefix or timestamp)
    if '_202' in doc_id:
        return True

    # Pattern 3: Contains date pattern (YYYY-MM-DD)
    parts = doc_id.split('_')

    # Old format has at least 3 parts: processor_name, date/None/year, run_id
    if len(parts) < 3:
        return False

    # Check if any part looks like a date (YYYY-MM-DD format)
    for part in parts:
        if len(part) == 10 and part.count('-') == 2:
            try:
                datetime.strptime(part, '%Y-%m-%d')
                return True
            except ValueError:
                continue

    return False


def cleanup_old_heartbeats(dry_run: bool = True):
    """
    Clean up old heartbeat documents.

    Args:
        dry_run: If True, only preview deletions without actually deleting
    """
    db = firestore.Client(project='nba-props-platform')
    collection_ref = db.collection('processor_heartbeats')

    logger.info("Fetching all heartbeat documents...")
    all_docs = list(collection_ref.stream())
    logger.info(f"Total documents: {len(all_docs)}")

    # Categorize documents
    old_format_docs = []
    new_format_docs = []

    for doc in all_docs:
        if is_old_format_doc_id(doc.id):
            old_format_docs.append(doc)
        else:
            new_format_docs.append(doc)

    logger.info(f"Old format documents: {len(old_format_docs)}")
    logger.info(f"New format documents: {len(new_format_docs)}")

    # Group old docs by processor name (extract from doc_id)
    processor_groups = defaultdict(list)
    for doc in old_format_docs:
        # Extract processor name (everything before the first date/None/year pattern)
        parts = doc.id.split('_')
        processor_name_parts = []

        for part in parts:
            # Stop when we hit a date pattern (YYYY-MM-DD)
            if len(part) == 10 and part.count('-') == 2:
                try:
                    datetime.strptime(part, '%Y-%m-%d')
                    break
                except ValueError:
                    pass
            # Stop when we hit "None"
            if part == 'None':
                break
            # Stop when we hit a year (202X)
            if part.startswith('202') and len(part) >= 4:
                break
            processor_name_parts.append(part)

        processor_name = '_'.join(processor_name_parts) if processor_name_parts else 'unknown'
        processor_groups[processor_name].append(doc)

    logger.info(f"\nUnique processors in old format: {len(processor_groups)}")

    # Show breakdown
    print(f"\n{'='*80}")
    print("PROCESSOR BREAKDOWN")
    print(f"{'='*80}\n")

    total_to_delete = 0
    for processor_name, docs in sorted(processor_groups.items(), key=lambda x: len(x[1]), reverse=True):
        count = len(docs)
        total_to_delete += count
        print(f"{count:6} docs - {processor_name}")

    print(f"\n{'='*80}")
    print(f"Total documents to delete: {total_to_delete:,}")
    print(f"Documents to keep: {len(new_format_docs)}")
    print(f"{'='*80}\n")

    if dry_run:
        logger.info("DRY RUN - No documents will be deleted")
        logger.info("Run without --dry-run to actually delete documents")
        return 0

    # Confirm deletion
    print(f"\n⚠️  WARNING: About to delete {total_to_delete:,} documents!")
    response = input("Type 'DELETE' to confirm: ")

    if response != 'DELETE':
        logger.info("Deletion cancelled")
        return 0

    # Delete in batches (Firestore batch limit is 500)
    logger.info("\nDeleting old format documents...")
    batch_size = 500
    deleted_count = 0

    for i in range(0, len(old_format_docs), batch_size):
        batch = db.batch()
        batch_docs = old_format_docs[i:i + batch_size]

        for doc in batch_docs:
            batch.delete(doc.reference)

        batch.commit()
        deleted_count += len(batch_docs)

        logger.info(f"Deleted {deleted_count:,} / {len(old_format_docs):,} documents...")

    logger.info(f"\n✅ Cleanup complete! Deleted {deleted_count:,} documents")
    logger.info(f"Remaining documents: {len(new_format_docs)}")

    return deleted_count


def main():
    parser = argparse.ArgumentParser(
        description='Cleanup old heartbeat documents from Firestore'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview deletions without actually deleting'
    )

    args = parser.parse_args()

    try:
        cleanup_old_heartbeats(dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
