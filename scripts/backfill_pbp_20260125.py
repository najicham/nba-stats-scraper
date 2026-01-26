#!/usr/bin/env python3
"""
Backfill Play-by-Play Data for 2026-01-25
------------------------------------------
Downloads NBA.com play-by-play data for all games on 2026-01-25.

This script was created in response to the 2026-01-25 orchestration failures
incident to ensure complete play-by-play data is available in GCS for
downstream shot zone analysis and other processors.

Usage:
    python3 scripts/backfill_pbp_20260125.py [--dry-run] [--verbose]

Options:
    --dry-run   Show what would be done without actually running scrapers
    --verbose   Show detailed scraper output
    --group     Export group to use (default: prod for GCS upload)

Exit Codes:
    0  - All games backfilled successfully
    1  - One or more games failed to backfill
    2  - Script configuration error
"""

import sys
import os
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scrapers.nbacom.nbac_play_by_play import GetNbaComPlayByPlay

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Games from 2026-01-25 (obtained from NBA.com scoreboard)
GAMES_20260125 = [
    {"game_id": "0022500650", "matchup": "SAC @ DET", "expected_events": 588},
    {"game_id": "0022500651", "matchup": "DEN @ MEM", "expected_events": None},
    {"game_id": "0022500644", "matchup": "GSW @ MIN", "expected_events": None},
    {"game_id": "0022500652", "matchup": "DAL @ MIL", "expected_events": None},
    {"game_id": "0022500653", "matchup": "TOR @ OKC", "expected_events": 565},
    {"game_id": "0022500654", "matchup": "NOP @ SAS", "expected_events": None},
    {"game_id": "0022500655", "matchup": "MIA @ PHX", "expected_events": 603},
    {"game_id": "0022500656", "matchup": "BKN @ LAC", "expected_events": 546},
]

GAME_DATE = "20260125"


def backfill_game(game_id: str, matchup: str, group: str = "prod", verbose: bool = False) -> Dict[str, Any]:
    """
    Backfill play-by-play data for a single game.

    Args:
        game_id: NBA game ID (e.g., "0022500656")
        matchup: Human-readable matchup (e.g., "BKN @ LAC")
        group: Export group to use (default: "prod" for GCS)
        verbose: Show detailed scraper output

    Returns:
        Dictionary with result information
    """
    logger.info(f"Backfilling {game_id} ({matchup})...")

    try:
        # Initialize scraper
        scraper = GetNbaComPlayByPlay()

        # Set log level based on verbose flag
        if not verbose:
            logging.getLogger("scraper_base").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("google").setLevel(logging.WARNING)

        # Run scraper
        opts = {
            "game_id": game_id,
            "gamedate": GAME_DATE,
            "group": group,
            "debug": verbose,
        }

        result = scraper.run(opts)

        # Extract stats
        stats = scraper.get_scraper_stats()
        event_count = stats.get("events", 0)

        logger.info(f"✅ {game_id} ({matchup}): {event_count} events")

        return {
            "game_id": game_id,
            "matchup": matchup,
            "success": True,
            "event_count": event_count,
            "error": None
        }

    except Exception as e:
        logger.error(f"❌ {game_id} ({matchup}): {str(e)}")
        return {
            "game_id": game_id,
            "matchup": matchup,
            "success": False,
            "event_count": 0,
            "error": str(e)
        }


def verify_results(results: List[Dict[str, Any]], expected_games: List[Dict[str, str]]) -> bool:
    """
    Verify backfill results against expectations.

    Args:
        results: List of backfill results
        expected_games: List of expected game metadata

    Returns:
        True if all games succeeded, False otherwise
    """
    logger.info("\n" + "="*80)
    logger.info("BACKFILL SUMMARY")
    logger.info("="*80)

    total_games = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total_games - successful
    total_events = sum(r["event_count"] for r in results if r["success"])

    logger.info(f"Total Games: {total_games}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total Events: {total_events}")
    logger.info("")

    # Show successful games
    if successful > 0:
        logger.info("✅ SUCCESSFUL:")
        for result in results:
            if result["success"]:
                expected = next((g for g in expected_games if g["game_id"] == result["game_id"]), None)
                expected_count = expected.get("expected_events") if expected else None

                status = ""
                if expected_count:
                    if result["event_count"] == expected_count:
                        status = " (matches expected)"
                    else:
                        diff = result["event_count"] - expected_count
                        status = f" (expected {expected_count}, diff: {diff:+d})"

                logger.info(f"  {result['game_id']} ({result['matchup']}): {result['event_count']} events{status}")
        logger.info("")

    # Show failed games
    if failed > 0:
        logger.info("❌ FAILED:")
        for result in results:
            if not result["success"]:
                logger.info(f"  {result['game_id']} ({result['matchup']}): {result['error']}")
        logger.info("")

    # Verification checks
    logger.info("VERIFICATION:")

    # Check 1: All games processed
    if successful == total_games:
        logger.info("  ✅ All games processed successfully")
    else:
        logger.warning(f"  ⚠️  {failed} game(s) failed to process")

    # Check 2: Reasonable event counts
    avg_events = total_events / successful if successful > 0 else 0
    if 400 <= avg_events <= 700:
        logger.info(f"  ✅ Average event count reasonable: {avg_events:.0f} events/game")
    else:
        logger.warning(f"  ⚠️  Average event count unusual: {avg_events:.0f} events/game (expected 400-700)")

    # Check 3: Expected event counts match (where available)
    mismatches = []
    for result in results:
        if result["success"]:
            expected = next((g for g in expected_games if g["game_id"] == result["game_id"]), None)
            if expected and expected.get("expected_events"):
                if result["event_count"] != expected["expected_events"]:
                    mismatches.append((result["game_id"], result["event_count"], expected["expected_events"]))

    if not mismatches:
        logger.info("  ✅ All event counts match expected values (where known)")
    else:
        logger.warning(f"  ⚠️  {len(mismatches)} event count mismatch(es):")
        for game_id, actual, expected in mismatches:
            logger.warning(f"      {game_id}: got {actual}, expected {expected}")

    logger.info("="*80)

    return failed == 0


def main():
    """Main entry point for backfill script."""
    parser = argparse.ArgumentParser(
        description="Backfill play-by-play data for 2026-01-25",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually running scrapers"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed scraper output"
    )
    parser.add_argument(
        "--group",
        default="prod",
        choices=["dev", "prod", "test"],
        help="Export group to use (default: prod for GCS upload)"
    )
    parser.add_argument(
        "--game-id",
        help="Only backfill specific game ID (for testing)"
    )

    args = parser.parse_args()

    # Filter games if specific game_id requested
    games = GAMES_20260125
    if args.game_id:
        games = [g for g in games if g["game_id"] == args.game_id]
        if not games:
            logger.error(f"Game ID {args.game_id} not found in 2026-01-25 games")
            return 2

    # Show plan
    logger.info("="*80)
    logger.info("PLAY-BY-PLAY BACKFILL FOR 2026-01-25")
    logger.info("="*80)
    logger.info(f"Date: {GAME_DATE}")
    logger.info(f"Total Games: {len(games)}")
    logger.info(f"Export Group: {args.group}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info("")

    logger.info("Games to backfill:")
    for i, game in enumerate(games, 1):
        expected = f" (expect ~{game['expected_events']} events)" if game.get('expected_events') else ""
        logger.info(f"  {i}. {game['game_id']}: {game['matchup']}{expected}")
    logger.info("")

    if args.dry_run:
        logger.info("DRY RUN - No scrapers will be executed")
        logger.info("="*80)
        return 0

    # Execute backfill
    logger.info("Starting backfill...")
    logger.info("")

    results = []
    for game in games:
        result = backfill_game(
            game_id=game["game_id"],
            matchup=game["matchup"],
            group=args.group,
            verbose=args.verbose
        )
        results.append(result)

    # Verify results
    success = verify_results(results, games)

    # Return appropriate exit code
    if success:
        logger.info("\n✅ Backfill completed successfully")
        return 0
    else:
        logger.error("\n❌ Backfill completed with errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())
