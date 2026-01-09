#!/usr/bin/env python3
"""
Backfill News Export to GCS

This script exports existing news articles to GCS for the frontend.
Useful for initial data load or re-exporting after schema changes.

Usage:
    # Export all players with news (both NBA and MLB)
    python scripts/news/backfill_news_export.py

    # Export only NBA
    python scripts/news/backfill_news_export.py --sport nba

    # Export specific players
    python scripts/news/backfill_news_export.py --players lebronjames,stephencurry

    # Dry run (show what would be exported)
    python scripts/news/backfill_news_export.py --dry-run

    # Export with custom hours lookback for tonight summary
    python scripts/news/backfill_news_export.py --hours 168
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_all_players_with_news(sport: str = None) -> list:
    """Get list of all players that have news articles."""
    from google.cloud import bigquery

    client = bigquery.Client(project="nba-props-platform")

    sport_filter = ""
    if sport:
        sport_filter = f"WHERE sport = '{sport}'"

    query = f"""
    SELECT DISTINCT
        player_lookup,
        sport,
        COUNT(*) as article_count
    FROM `nba-props-platform.nba_analytics.news_player_links`
    {sport_filter}
    GROUP BY player_lookup, sport
    ORDER BY article_count DESC
    """

    results = client.query(query).result()
    players = [dict(row) for row in results]
    logger.info(f"Found {len(players)} players with news")
    return players


def export_news(
    sport: str = None,
    players: list = None,
    dry_run: bool = False,
    hours_lookback: int = 72
) -> dict:
    """
    Export news to GCS.

    Args:
        sport: Filter by sport ('nba' or 'mlb'), or None for all
        players: Optional list of specific player_lookups to export
        dry_run: If True, only show what would be exported
        hours_lookback: Hours to look back for tonight summary

    Returns:
        dict with export statistics
    """
    from data_processors.publishing.news_exporter import NewsExporter

    stats = {
        'tonight_summaries': 0,
        'player_files': 0,
        'errors': 0,
        'sports_processed': []
    }

    # Determine which sports to process
    sports_to_process = [sport] if sport else ['nba', 'mlb']

    for current_sport in sports_to_process:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {current_sport.upper()} news")
        logger.info(f"{'='*60}")

        try:
            exporter = NewsExporter(sport=current_sport)

            # Export tonight summary
            logger.info(f"Exporting tonight summary for {current_sport}...")
            if dry_run:
                summary = exporter.generate_tonight_summary()
                logger.info(f"[DRY RUN] Would export tonight-summary.json with {summary['total_players']} players")
            else:
                try:
                    path = exporter.export()
                    stats['tonight_summaries'] += 1
                    logger.info(f"Exported: {path}")
                except Exception as e:
                    logger.error(f"Failed to export tonight summary: {e}")
                    stats['errors'] += 1

            # Get players to export
            if players:
                players_to_export = [{'player_lookup': p, 'sport': current_sport} for p in players]
            else:
                players_to_export = get_all_players_with_news(sport=current_sport)

            logger.info(f"Exporting {len(players_to_export)} player news files...")

            for i, player in enumerate(players_to_export):
                player_lookup = player['player_lookup']

                if dry_run:
                    logger.info(f"[DRY RUN] Would export: player-news/{player_lookup}.json")
                    stats['player_files'] += 1
                else:
                    try:
                        path = exporter.export_player(player_lookup)
                        stats['player_files'] += 1

                        if (i + 1) % 25 == 0:
                            logger.info(f"Progress: {i + 1}/{len(players_to_export)} players exported")
                    except Exception as e:
                        logger.warning(f"Failed to export {player_lookup}: {e}")
                        stats['errors'] += 1

            stats['sports_processed'].append(current_sport)

        except Exception as e:
            logger.error(f"Failed to process {current_sport}: {e}")
            stats['errors'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill news export to GCS')
    parser.add_argument('--sport', choices=['nba', 'mlb'], help='Filter by sport')
    parser.add_argument('--players', type=str, help='Comma-separated list of player_lookups')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be exported')
    parser.add_argument('--hours', type=int, default=72, help='Hours lookback for tonight summary')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  News Export Backfill Script")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - no files will be uploaded")

    # Parse players if provided
    players = None
    if args.players:
        players = [p.strip() for p in args.players.split(',')]
        logger.info(f"Exporting specific players: {players}")

    # Run export
    stats = export_news(
        sport=args.sport,
        players=players,
        dry_run=args.dry_run,
        hours_lookback=args.hours
    )

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("  Export Summary")
    logger.info("=" * 60)
    logger.info(f"  Sports processed: {', '.join(stats['sports_processed'])}")
    logger.info(f"  Tonight summaries: {stats['tonight_summaries']}")
    logger.info(f"  Player files: {stats['player_files']}")
    logger.info(f"  Errors: {stats['errors']}")

    if not args.dry_run:
        logger.info("")
        logger.info("GCS URLs:")
        for sport in stats['sports_processed']:
            logger.info(f"  https://storage.googleapis.com/nba-props-platform-api/v1/player-news/tonight-summary.json")

    return 0 if stats['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
