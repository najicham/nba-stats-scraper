#!/usr/bin/env python3
"""
Reprocess games after aliases are created.

This tool identifies games that were affected by unresolved player names
and re-runs analytics processing for those specific games.

Usage:
    # Dry run - see what would be reprocessed
    python tools/player_registry/reprocess_resolved.py --resolved-since 2025-12-06 --dry-run

    # Actually reprocess
    python tools/player_registry/reprocess_resolved.py --resolved-since 2025-12-06

    # Reprocess specific game IDs
    python tools/player_registry/reprocess_resolved.py --game-ids 0022100001 0022100002
"""

import argparse
import logging
import sys
import os
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ReprocessingOrchestrator:
    """
    Identify and reprocess games affected by newly resolved player names.
    """

    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.bq_client = self.client  # Alias for consistency
        self.project_id = project_id

    def get_players_ready_to_reprocess(self) -> List[Dict]:
        """Get players that have been resolved but not yet reprocessed."""
        query = f"""
        SELECT
            player_lookup,
            COUNT(*) as dates_count,
            MIN(game_date) as first_date,
            MAX(game_date) as last_date,
            ARRAY_AGG(DISTINCT game_date ORDER BY game_date) as game_dates
        FROM `{self.project_id}.nba_processing.registry_failures`
        WHERE resolved_at IS NOT NULL
          AND reprocessed_at IS NULL
        GROUP BY player_lookup
        ORDER BY dates_count DESC
        """
        result = self.bq_client.query(query).result()
        return [dict(row) for row in result]

    def get_affected_games(self, resolved_since: date) -> List[Dict]:
        """
        Get all games affected by aliases created since a date.

        Uses example_games from unresolved_player_names table.
        """
        query = f"""
        WITH resolved_names AS (
            SELECT DISTINCT
                u.normalized_lookup,
                u.team_abbr,
                u.season,
                game_id
            FROM `{self.project_id}.nba_reference.unresolved_player_names` u,
            UNNEST(u.example_games) as game_id
            WHERE u.status = 'resolved'
            AND DATE(u.reviewed_at) >= @since_date
            AND u.example_games IS NOT NULL
            AND ARRAY_LENGTH(u.example_games) > 0
        )
        SELECT
            game_id,
            MIN(season) as season,
            COUNT(DISTINCT normalized_lookup) as affected_players,
            ARRAY_AGG(DISTINCT normalized_lookup) as player_names
        FROM resolved_names
        WHERE game_id IS NOT NULL
        GROUP BY game_id
        ORDER BY game_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("since_date", "DATE", resolved_since)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()

            affected_games = []
            for row in results:
                affected_games.append({
                    'game_id': row.game_id,
                    'season': row.season,
                    'affected_players': row.affected_players,
                    'player_names': list(row.player_names) if row.player_names else []
                })

            return affected_games
        except Exception as e:
            logger.error(f"Error querying affected games: {e}")
            return []

    def get_games_by_date_range(self,
                                start_date: date,
                                end_date: date,
                                alias_lookups: List[str]) -> List[Dict]:
        """
        Fallback: Get games from date range where alias players appeared.

        Used when example_games is empty.
        """
        if not alias_lookups:
            return []

        query = f"""
        SELECT DISTINCT
            game_id,
            season,
            game_date
        FROM `{self.project_id}.nba_raw.game_boxscores`
        WHERE game_date BETWEEN @start_date AND @end_date
        AND REGEXP_REPLACE(LOWER(player_name), r'[^a-z]', '') IN UNNEST(@lookups)
        ORDER BY game_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
                bigquery.ArrayQueryParameter("lookups", "STRING", alias_lookups)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()

            games = []
            for row in results:
                games.append({
                    'game_id': row.game_id,
                    'season': row.season,
                    'affected_players': 1,
                    'player_names': alias_lookups
                })

            return games
        except Exception as e:
            logger.error(f"Error querying games by date range: {e}")
            return []

    def reprocess_game(self, game_id: str, season: str) -> Tuple[bool, str]:
        """
        Reprocess analytics for a specific game.

        Returns (success, message)
        """
        logger.info(f"Reprocessing game {game_id} (season {season})")

        try:
            # Import processor
            from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

            processor = PlayerGameSummaryProcessor()

            # Get game date from boxscores
            game_date = self._get_game_date(game_id)
            if not game_date:
                return (False, f"Could not find game date for {game_id}")

            # Process this specific game
            # Note: The processor needs to handle single-game reprocessing
            result = processor.process_single_game(game_id, game_date, season)

            if result:
                return (True, f"Reprocessed {game_id}")
            else:
                return (False, f"No data returned for {game_id}")

        except AttributeError as e:
            # process_single_game might not exist
            return (False, f"Processor doesn't support single-game reprocess: {e}")
        except Exception as e:
            logger.error(f"Failed to reprocess {game_id}: {e}")
            return (False, str(e))

    def _get_game_date(self, game_id: str) -> Optional[date]:
        """Get game date from boxscores."""
        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.game_boxscores`
        WHERE game_id = @game_id
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())
            if results:
                return results[0].game_date
            return None
        except Exception as e:
            logger.error(f"Error getting game date: {e}")
            return None

    def mark_registry_failures_reprocessed(self, player_lookup: str, game_dates: List[date] = None) -> int:
        """Mark registry failures as reprocessed."""
        if game_dates:
            # Mark specific dates
            dates_str = ", ".join([f"DATE('{d}')" for d in game_dates])
            query = f"""
            UPDATE `{self.project_id}.nba_processing.registry_failures`
            SET reprocessed_at = CURRENT_TIMESTAMP()
            WHERE player_lookup = @player_lookup
              AND resolved_at IS NOT NULL
              AND reprocessed_at IS NULL
              AND game_date IN ({dates_str})
            """
        else:
            # Mark all resolved dates for this player
            query = f"""
            UPDATE `{self.project_id}.nba_processing.registry_failures`
            SET reprocessed_at = CURRENT_TIMESTAMP()
            WHERE player_lookup = @player_lookup
              AND resolved_at IS NOT NULL
              AND reprocessed_at IS NULL
            """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result()
        return result.num_dml_affected_rows or 0

    def mark_as_reprocessed(self, resolved_since: date) -> int:
        """Mark unresolved records as reprocessed."""
        query = f"""
        UPDATE `{self.project_id}.nba_reference.unresolved_player_names`
        SET
            notes = CONCAT(IFNULL(notes, ''), ' | Reprocessed: ', CAST(CURRENT_TIMESTAMP() AS STRING))
        WHERE status = 'resolved'
        AND DATE(reviewed_at) >= @since_date
        AND (notes IS NULL OR notes NOT LIKE '%Reprocessed%')
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("since_date", "DATE", resolved_since)
            ]
        )

        try:
            job = self.client.query(query, job_config=job_config)
            job.result()
            return job.num_dml_affected_rows or 0
        except Exception as e:
            logger.error(f"Error marking as reprocessed: {e}")
            return 0

    def reprocess_all(self,
                      resolved_since: date = None,
                      game_ids: List[str] = None,
                      dry_run: bool = False) -> Dict:
        """
        Reprocess all affected games.

        Args:
            resolved_since: Process games for aliases created since this date
            game_ids: Specific game IDs to reprocess (overrides resolved_since)
            dry_run: If True, just show what would be reprocessed

        Returns:
            Dict with results
        """
        # Get affected games
        if game_ids:
            # Specific games requested
            affected_games = []
            for gid in game_ids:
                game_date = self._get_game_date(gid)
                season = self._get_season_from_game_id(gid)
                if game_date:
                    affected_games.append({
                        'game_id': gid,
                        'season': season,
                        'affected_players': 1,
                        'player_names': ['(manual)']
                    })
        elif resolved_since:
            affected_games = self.get_affected_games(resolved_since)
        else:
            logger.error("Must provide either resolved_since or game_ids")
            return {'error': 'No games specified'}

        logger.info(f"Found {len(affected_games)} games to reprocess")

        # Also query registry_failures for players ready to reprocess
        players_ready = self.get_players_ready_to_reprocess()
        logger.info(f"Found {len(players_ready)} players in registry_failures ready to reprocess")

        if not affected_games:
            logger.info("No games to reprocess (example_games may be empty)")
            return {
                'total_games': 0,
                'note': 'No games found with example_games populated'
            }

        if dry_run:
            logger.info("DRY RUN - would reprocess:")
            for game in affected_games[:20]:
                players = ', '.join(game['player_names'][:3])
                if len(game['player_names']) > 3:
                    players += f" +{len(game['player_names'])-3} more"
                logger.info(f"  - {game['game_id']} ({game['season']}): {players}")

            if len(affected_games) > 20:
                logger.info(f"  ... and {len(affected_games) - 20} more games")

            # Also show registry_failures players in dry run
            if players_ready:
                logger.info("\nPlayers from registry_failures ready to reprocess:")
                for player in players_ready[:10]:
                    logger.info(f"  - {player['player_lookup']}: {player['dates_count']} dates "
                              f"({player['first_date']} to {player['last_date']})")
                if len(players_ready) > 10:
                    logger.info(f"  ... and {len(players_ready) - 10} more players")

            return {'dry_run': True, 'total_games': len(affected_games), 'players_ready': len(players_ready)}

        # Reprocess each game
        success_count = 0
        failed_count = 0
        failures = []

        # Track successfully reprocessed games per player
        reprocessed_by_player = {}  # player_lookup -> list of game_dates

        for i, game in enumerate(affected_games, 1):
            logger.info(f"[{i}/{len(affected_games)}] Processing {game['game_id']}")

            success, message = self.reprocess_game(game['game_id'], game['season'])

            if success:
                success_count += 1
                # Track which players were reprocessed
                game_date = self._get_game_date(game['game_id'])
                if game_date:
                    for player_name in game.get('player_names', []):
                        if player_name != '(manual)':
                            if player_name not in reprocessed_by_player:
                                reprocessed_by_player[player_name] = []
                            reprocessed_by_player[player_name].append(game_date)
            else:
                failed_count += 1
                failures.append({'game_id': game['game_id'], 'error': message})

        # Mark as reprocessed in unresolved table
        if resolved_since:
            marked = self.mark_as_reprocessed(resolved_since)
            logger.info(f"Marked {marked} records as reprocessed in unresolved_player_names")

        # Mark registry_failures as reprocessed for successfully processed players
        registry_failures_marked = 0
        for player_lookup, game_dates in reprocessed_by_player.items():
            marked = self.mark_registry_failures_reprocessed(player_lookup, game_dates)
            registry_failures_marked += marked
            if marked > 0:
                logger.info(f"Marked {marked} registry_failures as reprocessed for {player_lookup}")

        if registry_failures_marked > 0:
            logger.info(f"Total registry_failures marked as reprocessed: {registry_failures_marked}")

        result = {
            'total_games': len(affected_games),
            'success': success_count,
            'failed': failed_count,
            'registry_failures_marked': registry_failures_marked
        }

        if failures:
            result['failures'] = failures[:10]  # First 10 failures

        return result

    def _get_season_from_game_id(self, game_id: str) -> str:
        """Extract season from game ID."""
        # Game ID format: 00XXYYZZZZ where XX is season, YY is type, ZZZZ is game number
        # e.g., 0022100001 = 2021-22 season
        try:
            if len(game_id) >= 4:
                year_code = int(game_id[2:4])
                start_year = 2000 + year_code
                return f"{start_year}-{str(start_year + 1)[-2:]}"
        except (ValueError, IndexError) as e:
            logger.debug(f"Could not parse season from game_id '{game_id}': {e}")
        return "2024-25"  # Default to current


def main():
    parser = argparse.ArgumentParser(
        description="Reprocess games after player name resolution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # See what games would be reprocessed
    python tools/player_registry/reprocess_resolved.py --resolved-since 2025-12-06 --dry-run

    # Reprocess games for recently resolved names
    python tools/player_registry/reprocess_resolved.py --resolved-since 2025-12-06

    # Reprocess specific games
    python tools/player_registry/reprocess_resolved.py --game-ids 0022100001 0022100002
        """
    )
    parser.add_argument(
        '--resolved-since',
        type=str,
        help='Reprocess games for aliases created since this date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--game-ids',
        nargs='+',
        help='Specific game IDs to reprocess'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be reprocessed without actually doing it'
    )

    args = parser.parse_args()

    if not args.resolved_since and not args.game_ids:
        parser.error("Must provide either --resolved-since or --game-ids")

    resolved_since = None
    if args.resolved_since:
        resolved_since = datetime.strptime(args.resolved_since, '%Y-%m-%d').date()

    orchestrator = ReprocessingOrchestrator()
    results = orchestrator.reprocess_all(
        resolved_since=resolved_since,
        game_ids=args.game_ids,
        dry_run=args.dry_run
    )

    print("\n" + "=" * 60)
    print("REPROCESSING COMPLETE")
    print("=" * 60)
    print(f"Total games: {results.get('total_games', 0)}")

    if not args.dry_run:
        print(f"Successful: {results.get('success', 0)}")
        print(f"Failed: {results.get('failed', 0)}")

        if results.get('failures'):
            print("\nFailures:")
            for f in results['failures']:
                print(f"  - {f['game_id']}: {f['error']}")
    else:
        print("(dry run - no changes made)")

    print("=" * 60)

    # Return appropriate exit code
    if results.get('failed', 0) > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
