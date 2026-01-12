"""
BDL Late Game Recovery - finds files in wrong date folders and reprocesses them.

This module addresses the "west coast game gap" issue where late-night games
(finishing after midnight ET) may have been written to the next day's GCS folder
instead of the game date folder.

Usage:
    # Check for orphaned files (dry run)
    python -m data_processors.raw.balldontlie.bdl_late_game_recovery \
        --date 2026-01-11 --dry-run

    # Full report with both live-boxscores and boxscores
    python -m data_processors.raw.balldontlie.bdl_late_game_recovery \
        --date 2026-01-11

    # Check specific source only
    python -m data_processors.raw.balldontlie.bdl_late_game_recovery \
        --date 2026-01-11 --source live-boxscores
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from google.cloud import storage

logger = logging.getLogger(__name__)


class BdlLateGameRecovery:
    """
    Find and report orphaned BDL files that ended up in wrong date folders.

    This typically happens when:
    1. Live scraper runs after midnight ET but games are from previous day
    2. The scraper used current ET date for folder path instead of game date

    Example:
        - Game: LAL @ GSW on 2026-01-11 (10 PM ET start)
        - Game ends: 2026-01-12 12:30 AM ET
        - Wrong folder: gs://.../live-boxscores/2026-01-12/...
        - Correct folder: gs://.../live-boxscores/2026-01-11/...
    """

    BUCKET_NAME = "nba-scraped-data"
    SOURCES = ["live-boxscores", "boxscores"]

    def __init__(self, bucket_name: Optional[str] = None):
        """
        Initialize the recovery helper.

        Args:
            bucket_name: GCS bucket name (defaults to nba-scraped-data)
        """
        self.bucket_name = bucket_name or self.BUCKET_NAME
        self.gcs_client = storage.Client()
        self.bucket = self.gcs_client.bucket(self.bucket_name)

    def find_orphaned_files(
        self,
        game_date: str,
        source: str = "live-boxscores"
    ) -> List[Dict]:
        """
        Find files for game_date that ended up in next day's folder.

        Args:
            game_date: The game date to check (YYYY-MM-DD format)
            source: "live-boxscores" or "boxscores"

        Returns:
            List of dicts with: path, game_date, folder_date, game_ids
        """
        if source not in self.SOURCES:
            raise ValueError(f"source must be one of {self.SOURCES}")

        # Parse game_date and calculate next day
        game_dt = datetime.strptime(game_date, "%Y-%m-%d")
        next_day = (game_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        # Check next day's folder for files with game_date games
        prefix = f"ball-dont-lie/{source}/{next_day}/"
        orphaned = []

        logger.info(f"Checking {prefix} for {game_date} games...")

        blobs = list(self.bucket.list_blobs(prefix=prefix))
        logger.info(f"Found {len(blobs)} files in {next_day} folder")

        for blob in blobs:
            if not blob.name.endswith('.json'):
                continue

            try:
                data = json.loads(blob.download_as_string())

                # Handle both live-boxscores and boxscores formats
                games = data.get("liveBoxes", data.get("data", []))

                game_ids_for_date = []
                for game in games:
                    # Live format: game["game"]["date"]
                    # Boxscores format: game["date"]
                    game_obj = game.get("game", game)
                    file_game_date = game_obj.get("date")

                    if file_game_date == game_date:
                        game_id = game_obj.get("id")
                        if game_id:
                            game_ids_for_date.append(game_id)

                if game_ids_for_date:
                    orphaned.append({
                        "path": blob.name,
                        "game_date": game_date,
                        "folder_date": next_day,
                        "game_ids": game_ids_for_date,
                        "game_count": len(game_ids_for_date),
                    })

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {blob.name}: {e}")
            except Exception as e:
                logger.warning(f"Error checking {blob.name}: {e}")

        return orphaned

    def report(
        self,
        game_date: str,
        sources: Optional[List[str]] = None
    ) -> Dict[str, List[Dict]]:
        """
        Generate a report of orphaned files for a game date.

        Args:
            game_date: The game date to check (YYYY-MM-DD)
            sources: List of sources to check (defaults to all)

        Returns:
            Dict mapping source -> list of orphaned files
        """
        sources = sources or self.SOURCES
        results = {}

        print(f"\n{'='*60}")
        print(f"BDL Late Game Recovery Report")
        print(f"Game Date: {game_date}")
        print(f"{'='*60}")

        for source in sources:
            orphaned = self.find_orphaned_files(game_date, source)
            results[source] = orphaned

            print(f"\n{source}:")
            print(f"  Found {len(orphaned)} orphaned files")

            if orphaned:
                for f in orphaned[:10]:
                    print(f"    - {f['path']}")
                    print(f"      Games: {f['game_count']} "
                          f"(IDs: {f['game_ids'][:3]}{'...' if len(f['game_ids']) > 3 else ''})")

                if len(orphaned) > 10:
                    print(f"    ... and {len(orphaned) - 10} more files")

        # Summary
        total_files = sum(len(v) for v in results.values())
        print(f"\n{'='*60}")
        print(f"Total orphaned files: {total_files}")

        if total_files > 0:
            print(f"\nNote: These files contain {game_date} games but are stored")
            print(f"in the {(datetime.strptime(game_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')} folder.")
            print(f"\nThis has been fixed in the live scraper (Option B).")
            print(f"New files will be stored in the correct folder.")
        else:
            print(f"\nNo orphaned files found - data is correctly organized!")

        print(f"{'='*60}\n")

        return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Find orphaned BDL files in wrong date folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --date 2026-01-11
  %(prog)s --date 2026-01-11 --source live-boxscores
  %(prog)s --date 2026-01-11 --dry-run
        """
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Game date to check (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--source",
        choices=BdlLateGameRecovery.SOURCES,
        help="Check specific source only (default: all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Just report, don't take any action (same as normal mode currently)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Validate date format
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        parser.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")

    # Run report
    recovery = BdlLateGameRecovery()
    sources = [args.source] if args.source else None
    recovery.report(args.date, sources)


if __name__ == "__main__":
    main()
