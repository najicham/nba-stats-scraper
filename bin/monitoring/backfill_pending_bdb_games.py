#!/usr/bin/env python3
"""
Backfill Pending BDB Games

Identifies games with missing or incomplete BDB data and adds them to pending_bdb_games table.

Usage:
    # Backfill Jan 17-24 (the period with poor BDB coverage)
    python bin/monitoring/backfill_pending_bdb_games.py --start-date 2026-01-17 --end-date 2026-01-24

    # Dry run first
    python bin/monitoring/backfill_pending_bdb_games.py --start-date 2026-01-17 --end-date 2026-01-24 --dry-run

Created: Session 53 (2026-01-31)
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PendingBDBBackfiller:
    """Backfill pending_bdb_games table for games with missing BDB data."""

    MIN_SHOTS_PER_GAME = 50

    def __init__(self, dry_run: bool = False):
        self.client = bigquery.Client()
        self.project_id = self.client.project
        self.dry_run = dry_run

    def find_games_needing_backfill(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Find completed games that don't have complete BDB data.

        Returns list of games with metadata.
        """
        query = f"""
        WITH scheduled_games AS (
            SELECT
                s.game_date,
                s.game_id as nba_game_id,
                s.home_team_tricode,
                s.away_team_tricode,
                EXTRACT(YEAR FROM s.game_date) as season_year
            FROM `{self.project_id}.nba_raw.nbac_schedule` s
            WHERE s.game_date BETWEEN '{start_date}' AND '{end_date}'
              AND s.game_status = 3  -- Completed games only
        ),
        bdb_coverage AS (
            SELECT
                LPAD(CAST(bdb_game_id AS STRING), 10, '0') as nba_game_id,
                game_date,
                COUNTIF(event_type = 'shot' AND shot_distance IS NOT NULL) as shots_with_distance
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 1, 2
        ),
        existing_pending AS (
            SELECT
                game_id,
                game_date
            FROM `{self.project_id}.nba_orchestration.pending_bdb_games`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        player_summary_source AS (
            -- Check what source was used for shot zones
            SELECT
                game_id,
                game_date,
                -- Check if any records have shot zone data
                COUNTIF(paint_attempts IS NOT NULL) as records_with_zones,
                COUNT(*) as total_records
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 1, 2
        )
        SELECT
            s.game_date,
            s.nba_game_id,
            s.home_team_tricode,
            s.away_team_tricode,
            s.season_year,
            COALESCE(b.shots_with_distance, 0) as bdb_shots,
            CASE
                WHEN b.shots_with_distance >= {self.MIN_SHOTS_PER_GAME} THEN 'complete'
                WHEN b.shots_with_distance > 0 THEN 'partial'
                ELSE 'missing'
            END as bdb_status,
            CASE
                WHEN pgs.records_with_zones > 0 THEN 'nbac_play_by_play'
                ELSE 'none'
            END as fallback_source,
            pgs.records_with_zones > 0 as has_fallback_zones
        FROM scheduled_games s
        LEFT JOIN bdb_coverage b ON s.nba_game_id = b.nba_game_id
        LEFT JOIN existing_pending ep ON s.nba_game_id = ep.game_id AND s.game_date = ep.game_date
        LEFT JOIN player_summary_source pgs ON s.nba_game_id = pgs.game_id AND s.game_date = pgs.game_date
        WHERE ep.game_id IS NULL  -- Not already in pending table
          AND (b.shots_with_distance IS NULL OR b.shots_with_distance < {self.MIN_SHOTS_PER_GAME})  -- Missing or incomplete BDB
        ORDER BY s.game_date, s.nba_game_id
        """

        try:
            result = self.client.query(query).to_dataframe()
            games = result.to_dict('records')
            logger.info(f"Found {len(games)} games needing backfill")
            return games
        except Exception as e:
            logger.error(f"Error finding games for backfill: {e}")
            return []

    def backfill_pending_games(self, games: List[Dict]) -> int:
        """
        Insert games into pending_bdb_games table.

        Returns number of games inserted.
        """
        if not games:
            logger.info("No games to backfill")
            return 0

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would backfill {len(games)} games:")
            for game in games:
                logger.info(
                    f"  {game['game_date']} {game['away_team_tricode']}@{game['home_team_tricode']} "
                    f"(BDB: {game['bdb_status']}, fallback: {game['fallback_source']})"
                )
            return len(games)

        # Prepare records for insertion
        records = []
        now = datetime.now(timezone.utc).isoformat()

        for game in games:
            records.append({
                'game_date': str(game['game_date']),
                'game_id': game['nba_game_id'],
                'nba_game_id': game['nba_game_id'],
                'home_team': game['home_team_tricode'],
                'away_team': game['away_team_tricode'],
                'season_year': int(game['season_year']) if game['season_year'] else None,
                'fallback_source': game['fallback_source'],
                'original_processed_at': now,
                'status': 'pending_bdb',
                'quality_before_rerun': 'silver' if game['has_fallback_zones'] else 'bronze',
                'shot_zones_complete_before': bool(game['has_fallback_zones']),
                'bdb_check_count': 0,
                'bdb_shots_found': int(game['bdb_shots']) if game['bdb_shots'] else 0,
                'created_at': now,
                'updated_at': now
            })

        # Insert using batch insert
        table_id = f"{self.project_id}.nba_orchestration.pending_bdb_games"

        try:
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
            )

            load_job = self.client.load_table_from_json(
                records, table_id, job_config=job_config
            )
            load_job.result(timeout=60)

            logger.info(f"✅ Backfilled {len(records)} games to pending_bdb_games table")
            return len(records)

        except Exception as e:
            logger.error(f"Failed to backfill games: {e}")
            return 0

    def run(self, start_date: str, end_date: str) -> Dict:
        """
        Main backfill process.

        Returns summary stats.
        """
        logger.info(f"{'='*60}")
        logger.info(f"PENDING BDB GAMES BACKFILL - {datetime.now().isoformat()}")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"{'='*60}")

        # Find games needing backfill
        games = self.find_games_needing_backfill(start_date, end_date)

        if not games:
            logger.info("No games need backfilling")
            return {'games_found': 0, 'games_backfilled': 0}

        # Show summary by status
        from collections import Counter
        status_counts = Counter(g['bdb_status'] for g in games)
        fallback_counts = Counter(g['fallback_source'] for g in games)

        logger.info(f"\nGames by BDB status:")
        for status, count in status_counts.items():
            logger.info(f"  {status}: {count}")

        logger.info(f"\nGames by fallback source:")
        for source, count in fallback_counts.items():
            logger.info(f"  {source}: {count}")

        # Backfill
        backfilled = self.backfill_pending_games(games)

        stats = {
            'games_found': len(games),
            'games_backfilled': backfilled
        }

        logger.info(f"\n{'='*60}")
        logger.info(f"SUMMARY: {stats}")
        logger.info(f"{'='*60}")

        return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill pending BDB games')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be backfilled without making changes')
    args = parser.parse_args()

    # Validate dates
    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
        if start_date > end_date:
            logger.error("Start date must be before end date")
            sys.exit(1)
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    backfiller = PendingBDBBackfiller(dry_run=args.dry_run)
    stats = backfiller.run(args.start_date, args.end_date)

    # Exit with success
    sys.exit(0)


if __name__ == '__main__':
    main()
