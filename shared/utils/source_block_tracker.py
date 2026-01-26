"""
FILE: shared/utils/source_block_tracker.py

Source Block Tracker - Record and query resource-level source blocks.

Usage:
    from shared.utils.source_block_tracker import record_source_block, get_source_blocked_resources

    # Record a block
    record_source_block(
        resource_id="0022500651",
        resource_type="play_by_play",
        source_system="nba_com_cdn",
        source_url="https://...",
        http_status_code=403,
        game_date="2026-01-25"
    )

    # Query blocks
    blocked = get_source_blocked_resources(
        game_date="2026-01-25",
        resource_type="play_by_play"
    )
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def record_source_block(
    resource_id: str,
    resource_type: str,
    source_system: str,
    http_status_code: int,
    source_url: Optional[str] = None,
    game_date: Optional[str] = None,
    notes: Optional[str] = None,
    block_type: Optional[str] = None,
    created_by: str = "scraper"
) -> bool:
    """
    Record a source block in BigQuery.

    Uses MERGE to update if already exists (increments verification_count),
    or inserts new record if first time seeing this block.

    Args:
        resource_id: ID of blocked resource (e.g., game_id)
        resource_type: Type of resource (e.g., "play_by_play")
        source_system: Source that blocked it (e.g., "nba_com_cdn")
        http_status_code: HTTP status code (403, 404, 410, etc.)
        source_url: Full URL that returned error (optional)
        game_date: Associated game date in YYYY-MM-DD format (optional)
        notes: Human-readable explanation (optional)
        block_type: Override auto-classification (optional)
        created_by: Source of record (default: "scraper")

    Returns:
        True if successful, False otherwise
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client()
        now = datetime.now(timezone.utc)

        # Classify block type from HTTP status if not provided
        if block_type is None:
            block_type = classify_block_type(http_status_code)

        # Escape single quotes in strings for SQL
        def escape_sql(s):
            return s.replace("'", "\\'") if s else None

        resource_id_safe = escape_sql(resource_id)
        resource_type_safe = escape_sql(resource_type)
        source_system_safe = escape_sql(source_system)
        source_url_safe = escape_sql(source_url)
        notes_safe = escape_sql(notes)[:500] if notes else None  # Truncate notes
        block_type_safe = escape_sql(block_type)
        created_by_safe = escape_sql(created_by)

        # MERGE query: update if exists, insert if new
        query = f"""
        MERGE `nba-props-platform.nba_orchestration.source_blocked_resources` AS target
        USING (
          SELECT
            '{resource_id_safe}' AS resource_id,
            '{resource_type_safe}' AS resource_type,
            '{source_system_safe}' AS source_system
        ) AS source
        ON target.resource_id = source.resource_id
          AND target.resource_type = source.resource_type
          AND target.source_system = source.source_system
          AND target.is_resolved = FALSE
        WHEN MATCHED THEN
          UPDATE SET
            last_verified_at = TIMESTAMP '{now.isoformat()}',
            verification_count = verification_count + 1,
            http_status_code = {http_status_code}
        WHEN NOT MATCHED THEN
          INSERT (
            resource_id, resource_type, game_date, source_system, source_url,
            http_status_code, block_type, first_detected_at, last_verified_at,
            verification_count, available_from_alt_source, notes, created_by,
            is_resolved
          )
          VALUES (
            '{resource_id_safe}',
            '{resource_type_safe}',
            {'NULL' if game_date is None else f"DATE '{game_date}'"},
            '{source_system_safe}',
            {'NULL' if source_url_safe is None else f"'{source_url_safe}'"},
            {http_status_code},
            '{block_type_safe}',
            TIMESTAMP '{now.isoformat()}',
            TIMESTAMP '{now.isoformat()}',
            1,
            FALSE,
            {'NULL' if notes_safe is None else f"'{notes_safe}'"},
            '{created_by_safe}',
            FALSE
          )
        """

        query_job = client.query(query)
        query_job.result()  # Wait for completion

        logger.info(f"Recorded source block: {resource_id} ({resource_type}) from {source_system}")
        return True

    except Exception as e:
        logger.warning(f"Failed to record source block for {resource_id}: {e}")
        return False


def get_source_blocked_resources(
    game_date: Optional[str] = None,
    resource_type: Optional[str] = None,
    source_system: Optional[str] = None,
    include_resolved: bool = False
) -> List[Dict[str, Any]]:
    """
    Query source-blocked resources.

    Args:
        game_date: Filter by game date (YYYY-MM-DD format)
        resource_type: Filter by resource type (e.g., "play_by_play")
        source_system: Filter by source system (e.g., "nba_com_cdn")
        include_resolved: Include resolved blocks (default: False)

    Returns:
        List of blocked resources as dictionaries
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client()

        where_clauses = []
        if game_date:
            where_clauses.append(f"game_date = DATE '{game_date}'")
        if resource_type:
            where_clauses.append(f"resource_type = '{resource_type}'")
        if source_system:
            where_clauses.append(f"source_system = '{source_system}'")
        if not include_resolved:
            where_clauses.append("is_resolved = FALSE")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        query = f"""
        SELECT
          resource_id,
          resource_type,
          game_date,
          source_system,
          source_url,
          http_status_code,
          block_type,
          first_detected_at,
          last_verified_at,
          verification_count,
          available_from_alt_source,
          alt_source_system,
          notes,
          is_resolved,
          resolved_at,
          resolution_notes
        FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
        WHERE {where_sql}
        ORDER BY game_date DESC, resource_id
        """

        query_job = client.query(query)
        results = query_job.result()

        return [dict(row) for row in results]

    except Exception as e:
        logger.warning(f"Failed to query source blocks: {e}")
        return []


def classify_block_type(http_status_code: int) -> str:
    """
    Classify block type from HTTP status code.

    Args:
        http_status_code: HTTP status code

    Returns:
        Block type classification
    """
    if http_status_code == 403:
        return "access_denied"
    elif http_status_code == 404:
        return "not_found"
    elif http_status_code == 410:
        return "removed"
    elif http_status_code >= 500:
        return "server_error"
    else:
        return "http_error"


def mark_block_resolved(
    resource_id: str,
    resource_type: str,
    source_system: str,
    resolution_notes: Optional[str] = None
) -> bool:
    """
    Mark a source block as resolved.

    Args:
        resource_id: ID of the resource
        resource_type: Type of resource
        source_system: Source system
        resolution_notes: Optional notes about resolution

    Returns:
        True if successful, False otherwise
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client()
        now = datetime.now(timezone.utc)

        # Escape single quotes
        resolution_notes_safe = resolution_notes.replace("'", "\\'") if resolution_notes else None

        query = f"""
        UPDATE `nba-props-platform.nba_orchestration.source_blocked_resources`
        SET
          is_resolved = TRUE,
          resolved_at = TIMESTAMP '{now.isoformat()}',
          resolution_notes = {'NULL' if resolution_notes_safe is None else f"'{resolution_notes_safe}'"}
        WHERE resource_id = '{resource_id}'
          AND resource_type = '{resource_type}'
          AND source_system = '{source_system}'
          AND is_resolved = FALSE
        """

        query_job = client.query(query)
        query_job.result()

        logger.info(f"Marked source block as resolved: {resource_id}")
        return True

    except Exception as e:
        logger.warning(f"Failed to mark block as resolved: {e}")
        return False


# Self-test when run directly
if __name__ == '__main__':
    print("Source Block Tracker - Self Test\n")

    # Test classify_block_type
    print("Testing classify_block_type:")
    assert classify_block_type(403) == "access_denied"
    assert classify_block_type(404) == "not_found"
    assert classify_block_type(410) == "removed"
    assert classify_block_type(500) == "server_error"
    print("✓ All classifications correct\n")

    # Test record_source_block
    print("Testing record_source_block:")
    success = record_source_block(
        resource_id="TEST_GAME_001",
        resource_type="test_resource",
        source_system="test_system",
        http_status_code=403,
        source_url="https://test.example.com/game/001",
        game_date="2026-01-26",
        notes="Test block for self-test",
        created_by="self_test"
    )
    print(f"  Record result: {'✓ Success' if success else '✗ Failed'}\n")

    # Test get_source_blocked_resources
    print("Testing get_source_blocked_resources:")
    blocks = get_source_blocked_resources(
        game_date="2026-01-26",
        resource_type="test_resource"
    )
    print(f"  Found {len(blocks)} blocks")
    if blocks:
        print(f"  First block: {blocks[0]['resource_id']} - {blocks[0]['block_type']}")
    print()

    # Test mark_block_resolved
    print("Testing mark_block_resolved:")
    success = mark_block_resolved(
        resource_id="TEST_GAME_001",
        resource_type="test_resource",
        source_system="test_system",
        resolution_notes="Test resolved"
    )
    print(f"  Resolve result: {'✓ Success' if success else '✗ Failed'}\n")

    # Verify resolved
    blocks_after = get_source_blocked_resources(
        game_date="2026-01-26",
        resource_type="test_resource",
        include_resolved=True
    )
    if blocks_after:
        print(f"  Verified: is_resolved = {blocks_after[0].get('is_resolved', False)}")

    print("\n✓ Self-test complete")
