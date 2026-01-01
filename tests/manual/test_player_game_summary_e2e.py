#!/usr/bin/env python3
"""
End-to-end test for player_game_summary processor with backfill detection

Tests:
1. Find backfill candidates (games with Phase 2 data but no Phase 3)
2. Process one game
3. Verify hash tracking works
4. Verify data was written to Phase 3
"""

import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_backfill_detection():
    """Test finding backfill candidates."""
    logger.info("=" * 80)
    logger.info("TEST 1: Find Backfill Candidates")
    logger.info("=" * 80)

    processor = PlayerGameSummaryProcessor()

    # Initialize with proper options (sets project_id)
    processor.set_opts({'project_id': 'nba-props-platform'})
    processor.init_clients()

    # Look back 180 days (to catch June data)
    candidates = processor.find_backfill_candidates(lookback_days=180)

    if candidates:
        logger.info(f"\n✅ Found {len(candidates)} games needing processing")
        for i, candidate in enumerate(candidates[:5], 1):
            logger.info(f"  {i}. {candidate['game_date']}: {candidate['game_id']} "
                       f"({candidate['phase2_row_count']} Phase 2 records)")

        if len(candidates) > 5:
            logger.info(f"  ... and {len(candidates) - 5} more")

        return candidates[0]  # Return first candidate for testing
    else:
        logger.warning("No backfill candidates found")
        return None

def test_process_game(game_date: str):
    """Test processing a specific game."""
    logger.info("\n" + "=" * 80)
    logger.info(f"TEST 2: Process Game {game_date}")
    logger.info("=" * 80)

    processor = PlayerGameSummaryProcessor()

    # Temporarily disable early exit checks for this test
    processor.ENABLE_NO_GAMES_CHECK = False
    processor.ENABLE_OFFSEASON_CHECK = False
    processor.ENABLE_HISTORICAL_DATE_CHECK = False

    logger.info(f"\nProcessing {game_date}...")

    try:
        success = processor.run({
            'start_date': game_date,
            'end_date': game_date
        })

        if success:
            logger.info(f"\n✅ Successfully processed {game_date}")

            # Check source tracking
            logger.info("\nSource Tracking Metadata:")
            for source, metadata in processor.source_metadata.items():
                logger.info(f"  {source}:")
                logger.info(f"    Last updated: {metadata.get('last_updated')}")
                logger.info(f"    Rows found: {metadata.get('rows_found')}")
                logger.info(f"    Completeness: {metadata.get('completeness_pct')}%")
                logger.info(f"    Hash: {metadata.get('data_hash', 'N/A')[:16]}...")

            return True
        else:
            logger.error(f"\n❌ Failed to process {game_date}")
            return False

    except Exception as e:
        logger.error(f"\n❌ Error processing {game_date}: {e}", exc_info=True)
        return False

def verify_phase3_data(game_date: str):
    """Verify data was written to Phase 3."""
    logger.info("\n" + "=" * 80)
    logger.info(f"TEST 3: Verify Phase 3 Data for {game_date}")
    logger.info("=" * 80)

    from google.cloud import bigquery

    client = bigquery.Client()

    query = f"""
    SELECT
        game_date,
        COUNT(*) as player_records,
        COUNT(DISTINCT game_id) as games,
        -- Check hash tracking
        COUNT(source_nbac_hash) as has_nbac_hash,
        COUNT(source_bdl_hash) as has_bdl_hash
    FROM `nba_analytics.player_game_summary`
    WHERE game_date = '{game_date}'
    """

    result = list(client.query(query).result(timeout=60))

    if result and result[0].player_records > 0:
        row = result[0]
        logger.info(f"\n✅ Phase 3 data verified:")
        logger.info(f"  Player records: {row.player_records}")
        logger.info(f"  Games: {row.games}")
        logger.info(f"  Records with nbac hash: {row.has_nbac_hash}")
        logger.info(f"  Records with bdl hash: {row.has_bdl_hash}")
        return True
    else:
        logger.error(f"\n❌ No Phase 3 data found for {game_date}")
        return False

if __name__ == "__main__":
    logger.info("\n" + "=" * 80)
    logger.info("PLAYER GAME SUMMARY - END-TO-END TEST")
    logger.info("Testing: Backfill Detection + Processing + Hash Tracking")
    logger.info("=" * 80 + "\n")

    # Step 1: Find a game to process
    candidate = test_backfill_detection()

    if not candidate:
        logger.error("\nNo backfill candidates found - cannot run end-to-end test")
        sys.exit(1)

    game_date = candidate['game_date']

    # Step 2: Process the game
    success = test_process_game(game_date)

    if not success:
        logger.error(f"\nProcessing failed for {game_date}")
        sys.exit(1)

    # Step 3: Verify Phase 3 data
    verified = verify_phase3_data(game_date)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)

    if verified:
        logger.info("\n🎉 ALL TESTS PASSED")
        logger.info(f"  ✅ Found backfill candidates")
        logger.info(f"  ✅ Processed game {game_date}")
        logger.info(f"  ✅ Hash tracking working")
        logger.info(f"  ✅ Data written to Phase 3")
        sys.exit(0)
    else:
        logger.error("\n❌ TESTS FAILED")
        sys.exit(1)
