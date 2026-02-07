#!/usr/bin/env python3
"""
Betting Line Source Validator

Validates betting line pipeline health at the GAME level:
1. Did our scrapers collect lines from Odds API and BettingPros for all scheduled games?
2. For players WITH sportsbook lines, did those lines flow into the feature store?

This complements check_vegas_line_coverage.sh (player-level %) by answering
whether missing lines are due to sportsbook gaps or pipeline failures.

Usage:
    python bin/monitoring/check_betting_line_sources.py [--date YYYY-MM-DD] [--days N]

Exit codes:
    0 = PASS (all games covered, no pipeline drops)
    1 = WARNING (1 game missing or pipeline drops > 0)
    2 = FAIL (2+ games missing from all sources)

Created: 2026-02-07
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Thresholds
FAIL_MISSING_GAMES = 2       # 2+ games missing from ALL sources = FAIL
WARN_PIPELINE_DROPS = 0      # Any pipeline drops = WARNING


class BettingLineSourceValidator:
    """Validates game-level betting line coverage across sources."""

    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def validate_date(self, game_date: str) -> Dict:
        """Validate betting line sources for a single date."""
        scheduled_games = self._get_scheduled_games(game_date)
        if not scheduled_games:
            return {
                'game_date': game_date,
                'scheduled_games': 0,
                'status': 'NO_GAMES',
                'message': 'No games scheduled',
                'game_coverage': [],
                'pipeline_check': {},
            }

        odds_api_coverage = self._get_odds_api_coverage(game_date)
        bettingpros_coverage = self._get_bettingpros_coverage(game_date)
        pipeline_drops = self._check_pipeline_flow(game_date)

        # Build per-game coverage report
        game_coverage = []
        games_missing_all = 0
        for game in scheduled_games:
            away = game['away_team_tricode']
            home = game['home_team_tricode']
            game_key = f"{away} @ {home}"

            # Odds API: match by home/away team pair
            oa_count = odds_api_coverage.get((home, away), 0)

            # BettingPros: match by either team appearing
            bp_home = bettingpros_coverage.get(home, 0)
            bp_away = bettingpros_coverage.get(away, 0)
            bp_count = bp_home + bp_away

            has_any = oa_count > 0 or bp_count > 0
            if not has_any:
                games_missing_all += 1

            game_coverage.append({
                'matchup': game_key,
                'odds_api_players': oa_count,
                'bettingpros_players': bp_count,
                'has_any_source': has_any,
            })

        # Calculate source-level stats
        total_games = len(scheduled_games)
        oa_games = sum(1 for g in game_coverage if g['odds_api_players'] > 0)
        bp_games = sum(1 for g in game_coverage if g['bettingpros_players'] > 0)
        either_games = sum(1 for g in game_coverage if g['has_any_source'])

        # Determine status
        if games_missing_all >= FAIL_MISSING_GAMES:
            status = 'FAIL'
        elif games_missing_all > 0 or pipeline_drops.get('dropped_count', 0) > WARN_PIPELINE_DROPS:
            status = 'WARNING'
        else:
            status = 'PASS'

        return {
            'game_date': game_date,
            'scheduled_games': total_games,
            'status': status,
            'game_coverage': game_coverage,
            'summary': {
                'odds_api_games': oa_games,
                'bettingpros_games': bp_games,
                'either_source_games': either_games,
                'games_missing_all': games_missing_all,
            },
            'pipeline_check': pipeline_drops,
        }

    def _get_scheduled_games(self, game_date: str) -> List[Dict]:
        """Get scheduled games for the date."""
        query = """
        SELECT DISTINCT
            game_date,
            home_team_tricode,
            away_team_tricode
        FROM `nba-props-platform.nba_reference.nba_schedule`
        WHERE game_date = @game_date
          AND game_status IN (1, 2, 3)
        ORDER BY home_team_tricode
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        results = self.bq_client.query(query, job_config=job_config).result()
        return [dict(row) for row in results]

    def _get_odds_api_coverage(self, game_date: str) -> Dict[Tuple[str, str], int]:
        """Get Odds API player count per game (home_team, away_team) -> count."""
        query = """
        SELECT
            home_team_abbr,
            away_team_abbr,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
        WHERE game_date = @game_date
          AND points_line IS NOT NULL
          AND points_line > 0
        GROUP BY home_team_abbr, away_team_abbr
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        results = self.bq_client.query(query, job_config=job_config).result()
        return {
            (row['home_team_abbr'], row['away_team_abbr']): row['player_count']
            for row in results
        }

    def _get_bettingpros_coverage(self, game_date: str) -> Dict[str, int]:
        """Get BettingPros player count per team -> count."""
        query = """
        SELECT
            player_team,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
        WHERE game_date = @game_date
          AND market_type = 'points'
          AND points_line IS NOT NULL
          AND points_line > 0
        GROUP BY player_team
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        results = self.bq_client.query(query, job_config=job_config).result()
        return {row['player_team']: row['player_count'] for row in results}

    def _check_pipeline_flow(self, game_date: str) -> Dict:
        """Check if players with raw lines made it into the feature store."""
        query = """
        WITH raw_players AS (
            SELECT DISTINCT player_lookup
            FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
              AND points_line IS NOT NULL
              AND points_line > 0
        ),
        feature_store_players AS (
            SELECT player_lookup, feature_25_quality
            FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
            WHERE game_date = @game_date
        )
        SELECT
            COUNT(r.player_lookup) as raw_player_count,
            COUNTIF(fs.player_lookup IS NOT NULL) as in_feature_store,
            COUNTIF(fs.player_lookup IS NOT NULL AND fs.feature_25_quality >= 50) as good_quality,
            COUNTIF(fs.player_lookup IS NULL) as not_in_feature_store
        FROM raw_players r
        LEFT JOIN feature_store_players fs
            ON r.player_lookup = fs.player_lookup
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        results = list(self.bq_client.query(query, job_config=job_config).result())
        if not results:
            return {'raw_count': 0, 'in_feature_store': 0, 'dropped_count': 0, 'dropped_players': []}

        row = results[0]
        raw_count = row['raw_player_count']
        in_fs = row['in_feature_store']
        not_in_fs = row['not_in_feature_store']

        # Get specific dropped players if any
        dropped_players = []
        if not_in_fs > 0:
            dropped_players = self._get_dropped_players(game_date)

        return {
            'raw_count': raw_count,
            'in_feature_store': in_fs,
            'good_quality': row['good_quality'],
            'dropped_count': not_in_fs,
            'dropped_players': dropped_players,
        }

    def _get_dropped_players(self, game_date: str) -> List[str]:
        """Get list of players with raw lines but missing from feature store."""
        query = """
        WITH raw_players AS (
            SELECT DISTINCT player_lookup
            FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
              AND points_line IS NOT NULL
              AND points_line > 0
        )
        SELECT r.player_lookup
        FROM raw_players r
        LEFT JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
            ON r.player_lookup = fs.player_lookup AND fs.game_date = @game_date
        WHERE fs.player_lookup IS NULL
        ORDER BY r.player_lookup
        LIMIT 20
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )
        results = self.bq_client.query(query, job_config=job_config).result()
        return [row['player_lookup'] for row in results]


def format_report(result: Dict) -> str:
    """Format a single date's result as a readable report."""
    lines = []
    game_date = result['game_date']
    total = result['scheduled_games']

    lines.append(f"=== Betting Line Source Validation: {game_date} ===")
    lines.append(f"Scheduled Games: {total}")

    if total == 0:
        lines.append("No games scheduled.")
        return '\n'.join(lines)

    lines.append("")
    lines.append("GAME COVERAGE:")

    for g in result['game_coverage']:
        oa = g['odds_api_players']
        bp = g['bettingpros_players']
        tag = "OK" if g['has_any_source'] else "MISSING"
        lines.append(
            f"  {g['matchup']:<14s}  OddsAPI: {oa:>3d} players   "
            f"BettingPros: {bp:>3d} players   {tag}"
        )

    summary = result['summary']
    lines.append("")
    lines.append("SUMMARY:")
    lines.append(f"  Odds API:      {summary['odds_api_games']}/{total} games "
                 f"({100 * summary['odds_api_games'] / total:.1f}%)")
    lines.append(f"  BettingPros:   {summary['bettingpros_games']}/{total} games "
                 f"({100 * summary['bettingpros_games'] / total:.1f}%)")
    lines.append(f"  Either source: {summary['either_source_games']}/{total} games "
                 f"({100 * summary['either_source_games'] / total:.1f}%)")

    pc = result['pipeline_check']
    if pc.get('raw_count', 0) > 0:
        lines.append("")
        lines.append("PIPELINE CHECK:")
        lines.append(f"  Players with raw lines: {pc['raw_count']}")
        lines.append(f"  Players in feature store: {pc['in_feature_store']}")
        if pc.get('good_quality', 0) > 0:
            lines.append(f"  With good vegas quality (>=50): {pc['good_quality']}")
        if pc['dropped_count'] > 0:
            dropped_list = ', '.join(pc['dropped_players'][:10])
            lines.append(f"  Dropped in pipeline: {pc['dropped_count']} ({dropped_list})")
        else:
            lines.append(f"  Dropped in pipeline: 0")

    lines.append("")
    status = result['status']
    if status == 'PASS':
        lines.append("Status: PASS")
    elif status == 'WARNING':
        reasons = []
        if summary['games_missing_all'] > 0:
            reasons.append(f"{summary['games_missing_all']} game(s) missing from all sources")
        if pc.get('dropped_count', 0) > 0:
            reasons.append(f"{pc['dropped_count']} player(s) dropped in pipeline")
        lines.append(f"Status: WARNING ({'; '.join(reasons)})")
    elif status == 'FAIL':
        lines.append(f"Status: FAIL ({summary['games_missing_all']} games missing from all sources)")
    elif status == 'NO_GAMES':
        lines.append("Status: NO_GAMES (no games scheduled)")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Validate betting line pipeline health at the game level'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Target date (YYYY-MM-DD, default: today)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=1,
        help='Number of days to check (default: 1)'
    )
    parser.add_argument(
        '--project',
        type=str,
        default=None,
        help='GCP project ID (default: nba-props-platform)'
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    validator = BettingLineSourceValidator(project_id=args.project)

    target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    worst_status = 'PASS'
    status_order = {'NO_GAMES': 0, 'PASS': 0, 'WARNING': 1, 'FAIL': 2}

    for i in range(args.days):
        check_date = target_date - timedelta(days=i)
        result = validator.validate_date(check_date.isoformat())
        print(format_report(result))
        print()

        # Track worst status across all days
        if status_order.get(result['status'], 0) > status_order.get(worst_status, 0):
            worst_status = result['status']

    # Exit code based on worst status seen
    if worst_status == 'FAIL':
        sys.exit(2)
    elif worst_status == 'WARNING':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
