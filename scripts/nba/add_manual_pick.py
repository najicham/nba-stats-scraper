#!/usr/bin/env python3
"""
Manual Pick CLI — Add or remove manual best bets picks.

Usage:
    # Add a pick
    python scripts/nba/add_manual_pick.py \
      --player gui_santos_GSW \
      --team GSW --opponent LAL \
      --direction OVER --line 13.5 \
      --date 2026-02-28 \
      [--edge 5.2] \
      [--notes "Line moved after injury report"] \
      [--export]  # optionally trigger re-export

    # Remove a manual pick (soft delete)
    python scripts/nba/add_manual_pick.py \
      --remove --player gui_santos_GSW --date 2026-02-28

Created: 2026-02-28 (Session 340)
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def lookup_game_id(bq_client: bigquery.Client, team: str, opponent: str, game_date: str) -> str:
    """Look up game_id from schedule for this team/opponent/date."""
    query = """
    SELECT
      CONCAT(
        FORMAT_DATE('%Y%m%d', game_date), '_',
        away_team_tricode, '_',
        home_team_tricode
      ) AS game_id
    FROM `nba-props-platform.nba_raw.nbac_schedule`
    WHERE game_date = @game_date
      AND (
        (home_team_tricode = @team AND away_team_tricode = @opponent)
        OR (away_team_tricode = @team AND home_team_tricode = @opponent)
      )
    LIMIT 1
    """
    params = [
        bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
        bigquery.ScalarQueryParameter('team', 'STRING', team),
        bigquery.ScalarQueryParameter('opponent', 'STRING', opponent),
    ]
    rows = list(bq_client.query(
        query, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result(timeout=30))

    if not rows:
        logger.error(f"No game found for {team} vs {opponent} on {game_date}")
        sys.exit(1)

    return rows[0].game_id


def lookup_player_name(bq_client: bigquery.Client, player_lookup: str, game_date: str) -> str:
    """Look up player full name, trying multiple sources."""
    params = [
        bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
        bigquery.ScalarQueryParameter('game_date', 'DATE', game_date),
    ]

    # Source 1: signal_best_bets_picks (recent best bets history)
    # Source 2: player_game_summary (any player who's played this season)
    queries = [
        """
        SELECT player_name
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
        WHERE player_lookup = @player_lookup
          AND game_date >= DATE_SUB(@game_date, INTERVAL 60 DAY)
          AND game_date <= @game_date
        ORDER BY game_date DESC
        LIMIT 1
        """,
        """
        SELECT player_full_name AS player_name
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
          AND game_date <= @game_date
        ORDER BY game_date DESC
        LIMIT 1
        """,
    ]

    for query in queries:
        try:
            rows = list(bq_client.query(
                query, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result(timeout=30))
            if rows and rows[0].player_name:
                return rows[0].player_name
        except Exception:
            continue

    logger.warning(f"Could not find display name for {player_lookup} in any source")
    return player_lookup


def add_pick(args) -> None:
    """Add a manual pick to best_bets_manual_picks and signal_best_bets_picks."""
    bq_client = get_bigquery_client(project_id=PROJECT_ID)
    now = datetime.now(timezone.utc)

    # Check for existing active manual pick (prevent duplicates)
    dup_query = """
    SELECT COUNT(*) as cnt
    FROM `nba-props-platform.nba_predictions.best_bets_manual_picks`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND is_active = TRUE
    """
    dup_params = [
        bigquery.ScalarQueryParameter('player_lookup', 'STRING', args.player),
        bigquery.ScalarQueryParameter('game_date', 'DATE', args.date),
    ]
    dup_rows = list(bq_client.query(
        dup_query, job_config=bigquery.QueryJobConfig(query_parameters=dup_params)
    ).result(timeout=30))
    if dup_rows and dup_rows[0].cnt > 0:
        logger.error(
            f"Active manual pick already exists for {args.player} on {args.date}. "
            f"Remove it first with --remove before adding a new one."
        )
        sys.exit(1)

    game_id = lookup_game_id(bq_client, args.team, args.opponent, args.date)
    player_name = lookup_player_name(bq_client, args.player, args.date)

    logger.info(f"Adding manual pick: {player_name} ({args.player}) {args.direction} {args.line}")
    logger.info(f"Game: {game_id} ({args.team} vs {args.opponent}) on {args.date}")

    # Step 1: Write to best_bets_manual_picks
    manual_row = {
        'player_lookup': args.player,
        'game_id': game_id,
        'game_date': args.date,
        'player_name': player_name,
        'team_abbr': args.team,
        'opponent_team_abbr': args.opponent,
        'recommendation': args.direction.upper(),
        'line_value': args.line,
        'stat': 'PTS',
        'edge': args.edge,
        'rank': None,
        'pick_angles': [],
        'added_by': os.environ.get('USER', 'manual'),
        'added_at': now.isoformat(),
        'notes': args.notes,
        'is_active': True,
    }

    manual_table = f'{PROJECT_ID}.nba_predictions.best_bets_manual_picks'
    manual_schema = [
        bigquery.SchemaField('player_lookup', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('game_id', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('game_date', 'DATE', mode='REQUIRED'),
        bigquery.SchemaField('player_name', 'STRING'),
        bigquery.SchemaField('team_abbr', 'STRING'),
        bigquery.SchemaField('opponent_team_abbr', 'STRING'),
        bigquery.SchemaField('recommendation', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('line_value', 'NUMERIC'),
        bigquery.SchemaField('stat', 'STRING'),
        bigquery.SchemaField('edge', 'NUMERIC'),
        bigquery.SchemaField('rank', 'INTEGER'),
        bigquery.SchemaField('pick_angles', 'STRING', mode='REPEATED'),
        bigquery.SchemaField('added_by', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('added_at', 'TIMESTAMP', mode='REQUIRED'),
        bigquery.SchemaField('notes', 'STRING'),
        bigquery.SchemaField('is_active', 'BOOLEAN', mode='REQUIRED'),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=manual_schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    bq_client.load_table_from_json(
        [manual_row], manual_table, job_config=job_config
    ).result(timeout=30)
    logger.info(f"Wrote to best_bets_manual_picks")

    # Step 2: Also write to signal_best_bets_picks so grading pipeline picks it up
    signal_row = {
        'player_lookup': args.player,
        'game_id': game_id,
        'game_date': args.date,
        'system_id': 'manual_override',
        'player_name': player_name,
        'team_abbr': args.team,
        'opponent_team_abbr': args.opponent,
        'predicted_points': args.line + (args.edge or 0),
        'line_value': args.line,
        'recommendation': args.direction.upper(),
        'edge': args.edge,
        'rank': 99,  # Low priority rank; exporter will re-rank
        'pick_angles': [],
        'algorithm_version': 'manual_override',
    }

    signal_table = f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks'
    signal_schema = [
        bigquery.SchemaField('player_lookup', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('game_id', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('game_date', 'DATE', mode='REQUIRED'),
        bigquery.SchemaField('system_id', 'STRING', mode='REQUIRED'),
        bigquery.SchemaField('player_name', 'STRING'),
        bigquery.SchemaField('team_abbr', 'STRING'),
        bigquery.SchemaField('opponent_team_abbr', 'STRING'),
        bigquery.SchemaField('predicted_points', 'NUMERIC'),
        bigquery.SchemaField('line_value', 'NUMERIC'),
        bigquery.SchemaField('recommendation', 'STRING'),
        bigquery.SchemaField('edge', 'NUMERIC'),
        bigquery.SchemaField('rank', 'INTEGER'),
        bigquery.SchemaField('pick_angles', 'STRING', mode='REPEATED'),
        bigquery.SchemaField('algorithm_version', 'STRING'),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=signal_schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    bq_client.load_table_from_json(
        [signal_row], signal_table, job_config=job_config
    ).result(timeout=30)
    logger.info(f"Wrote to signal_best_bets_picks (system_id=manual_override)")

    # Step 3: Optionally trigger re-export
    if args.export:
        logger.info("Triggering best-bets-all re-export...")
        from data_processors.publishing.best_bets_all_exporter import BestBetsAllExporter
        exporter = BestBetsAllExporter()
        path = exporter.export(args.date, trigger_source='manual')
        logger.info(f"Re-exported to: {path}")

    logger.info("Done.")


def remove_pick(args) -> None:
    """Soft-delete a manual pick by setting is_active = FALSE."""
    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    # Step 1: Soft-delete from manual picks table
    query = f"""
    UPDATE `{PROJECT_ID}.nba_predictions.best_bets_manual_picks`
    SET is_active = FALSE,
        updated_at = CURRENT_TIMESTAMP()
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND is_active = TRUE
    """
    params = [
        bigquery.ScalarQueryParameter('player_lookup', 'STRING', args.player),
        bigquery.ScalarQueryParameter('game_date', 'DATE', args.date),
    ]
    bq_client.query(
        query, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result(timeout=30)
    logger.info(f"Deactivated manual pick: {args.player} on {args.date}")

    # Step 2: Delete from signal_best_bets_picks so the pick doesn't
    # reappear via _query_all_picks() on the next export
    signal_delete = f"""
    DELETE FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND system_id = 'manual_override'
    """
    bq_client.query(
        signal_delete, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result(timeout=30)
    logger.info(f"Deleted manual_override row from signal_best_bets_picks")

    # Step 3: Delete from published picks so the pick locking system
    # doesn't resurrect it on the next export
    pub_delete = f"""
    DELETE FROM `{PROJECT_ID}.nba_predictions.best_bets_published_picks`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND source = 'manual'
    """
    bq_client.query(
        pub_delete, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result(timeout=30)
    logger.info(f"Deleted manual pick from best_bets_published_picks")

    if args.export:
        logger.info("Triggering best-bets-all re-export...")
        from data_processors.publishing.best_bets_all_exporter import BestBetsAllExporter
        exporter = BestBetsAllExporter()
        path = exporter.export(args.date, trigger_source='manual')
        logger.info(f"Re-exported to: {path}")

    logger.info("Done.")


def main():
    parser = argparse.ArgumentParser(
        description='Add or remove manual best bets picks'
    )
    parser.add_argument('--player', required=True, help='Player lookup key (e.g. gui_santos_GSW)')
    parser.add_argument('--date', required=True, help='Game date (YYYY-MM-DD)')
    parser.add_argument('--remove', action='store_true', help='Remove (soft-delete) the pick')

    # Add-mode args
    parser.add_argument('--team', help='Team abbreviation (e.g. GSW)')
    parser.add_argument('--opponent', help='Opponent abbreviation (e.g. LAL)')
    parser.add_argument('--direction', help='OVER or UNDER')
    parser.add_argument('--line', type=float, help='Line value (e.g. 13.5)')
    parser.add_argument('--edge', type=float, default=None, help='Edge value (optional)')
    parser.add_argument('--notes', type=str, default=None, help='Notes/reason for the pick')
    parser.add_argument('--export', action='store_true', help='Trigger re-export after adding/removing')

    args = parser.parse_args()

    if args.remove:
        remove_pick(args)
    else:
        # Validate required args for add mode
        if not all([args.team, args.opponent, args.direction, args.line is not None]):
            parser.error('--team, --opponent, --direction, and --line are required when adding a pick')
        if args.direction.upper() not in ('OVER', 'UNDER'):
            parser.error('--direction must be OVER or UNDER')
        add_pick(args)


if __name__ == '__main__':
    main()
