#!/usr/bin/env python3
"""
Fix Team Abbreviations in MLB Data

Updates all "UNK" team abbreviations in BigQuery tables with correct values
from the MLB Stats API.

This is a one-time fix for data collected before the bug fix in collect_season.py.

Usage:
    # Dry run - show what would be updated
    PYTHONPATH=. python scripts/mlb/fix_team_abbreviations.py --dry-run

    # Actually fix the data
    PYTHONPATH=. python scripts/mlb/fix_team_abbreviations.py

    # Fix specific table only
    PYTHONPATH=. python scripts/mlb/fix_team_abbreviations.py --table mlb_pitcher_stats
"""

import argparse
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MLB Stats API
MLB_GAME_API = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# Tables to fix
TABLES_TO_FIX = [
    'mlb_raw.mlb_game_lineups',
    'mlb_raw.mlb_lineup_batters',
    'mlb_raw.mlb_pitcher_stats',
    'mlb_raw.bdl_batter_stats',
]


class TeamAbbreviationFixer:
    """Fixes team abbreviations in BigQuery tables."""

    def __init__(self, project_id: str = 'nba-props-platform', dry_run: bool = False):
        self.project_id = project_id
        self.dry_run = dry_run
        self.client = bigquery.Client(project=project_id)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'mlb-abbr-fixer/1.0'})

        # Cache of game_pk -> (away_abbr, home_abbr)
        self.abbr_cache: Dict[int, Tuple[str, str]] = {}
        self.api_calls = 0
        self.cache_hits = 0

    def get_team_abbreviations(self, game_pk: int) -> Optional[Tuple[str, str]]:
        """Get team abbreviations for a game from MLB API."""
        # Check cache first
        if game_pk in self.abbr_cache:
            self.cache_hits += 1
            return self.abbr_cache[game_pk]

        url = MLB_GAME_API.format(game_pk=game_pk)

        try:
            time.sleep(0.1)  # Rate limit
            self.api_calls += 1

            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Get abbreviations from gameData.teams (the correct location!)
            teams = data.get('gameData', {}).get('teams', {})
            away_abbr = teams.get('away', {}).get('abbreviation')
            home_abbr = teams.get('home', {}).get('abbreviation')

            if away_abbr and home_abbr:
                self.abbr_cache[game_pk] = (away_abbr, home_abbr)
                return (away_abbr, home_abbr)

            return None

        except Exception as e:
            logger.warning(f"Error fetching game {game_pk}: {e}")
            return None

    def get_games_needing_fix(self, table: str) -> List[int]:
        """Get list of game_pks that have UNK abbreviations."""
        # Different tables have different column names
        if table == 'mlb_raw.mlb_game_lineups':
            query = f"""
            SELECT DISTINCT game_pk
            FROM `{self.project_id}.{table}`
            WHERE away_team_abbr = 'UNK' OR home_team_abbr = 'UNK'
            ORDER BY game_pk
            """
        elif table == 'mlb_raw.mlb_lineup_batters':
            query = f"""
            SELECT DISTINCT game_pk
            FROM `{self.project_id}.{table}`
            WHERE team_abbr = 'UNK' OR opponent_team_abbr = 'UNK'
            ORDER BY game_pk
            """
        elif table == 'mlb_raw.mlb_pitcher_stats':
            query = f"""
            SELECT DISTINCT game_pk
            FROM `{self.project_id}.{table}`
            WHERE team_abbr = 'UNK' OR opponent_team_abbr = 'UNK'
            ORDER BY game_pk
            """
        elif table == 'mlb_raw.bdl_batter_stats':
            # This table uses source_file_path to get game_pk
            query = f"""
            SELECT DISTINCT
                CAST(SPLIT(source_file_path, '/')[SAFE_OFFSET(3)] AS INT64) as game_pk
            FROM `{self.project_id}.{table}`
            WHERE home_team_abbr = 'UNK' OR away_team_abbr = 'UNK' OR team_abbr = 'UNK'
            ORDER BY game_pk
            """
        else:
            return []

        try:
            result = self.client.query(query).result()
            game_pks = [row.game_pk for row in result if row.game_pk]
            logger.info(f"Found {len(game_pks)} games needing fix in {table}")
            return game_pks
        except Exception as e:
            logger.error(f"Error querying {table}: {e}")
            return []

    def fix_table(self, table: str, game_pks: List[int]) -> int:
        """Fix abbreviations in a specific table."""
        if not game_pks:
            return 0

        fixed_count = 0

        # Build lookup of game_pk -> abbreviations
        logger.info(f"Fetching abbreviations for {len(game_pks)} games...")
        abbr_lookup = {}
        for i, game_pk in enumerate(game_pks):
            abbrs = self.get_team_abbreviations(game_pk)
            if abbrs:
                abbr_lookup[game_pk] = abbrs

            if (i + 1) % 100 == 0:
                logger.info(f"  Fetched {i + 1}/{len(game_pks)} ({self.cache_hits} cache hits)")

        logger.info(f"Got abbreviations for {len(abbr_lookup)} games")

        if self.dry_run:
            logger.info(f"[DRY RUN] Would update {len(abbr_lookup)} games in {table}")
            return len(abbr_lookup)

        # Update table based on its structure
        if table == 'mlb_raw.mlb_game_lineups':
            fixed_count = self._update_game_lineups(abbr_lookup)
        elif table == 'mlb_raw.mlb_lineup_batters':
            fixed_count = self._update_lineup_batters(abbr_lookup)
        elif table == 'mlb_raw.mlb_pitcher_stats':
            fixed_count = self._update_pitcher_stats(abbr_lookup)
        elif table == 'mlb_raw.bdl_batter_stats':
            fixed_count = self._update_batter_stats(abbr_lookup)

        return fixed_count

    def _update_game_lineups(self, abbr_lookup: Dict[int, Tuple[str, str]]) -> int:
        """Update mlb_game_lineups table."""
        updated = 0
        for game_pk, (away_abbr, home_abbr) in abbr_lookup.items():
            query = f"""
            UPDATE `{self.project_id}.mlb_raw.mlb_game_lineups`
            SET
                away_team_abbr = '{away_abbr}',
                home_team_abbr = '{home_abbr}'
            WHERE game_pk = {game_pk}
            """
            try:
                self.client.query(query).result()
                updated += 1
            except Exception as e:
                logger.warning(f"Error updating game_lineups for {game_pk}: {e}")

        logger.info(f"Updated {updated} rows in mlb_game_lineups")
        return updated

    def _update_lineup_batters(self, abbr_lookup: Dict[int, Tuple[str, str]]) -> int:
        """Update mlb_lineup_batters table."""
        updated = 0
        for game_pk, (away_abbr, home_abbr) in abbr_lookup.items():
            # Update away team batters
            query_away = f"""
            UPDATE `{self.project_id}.mlb_raw.mlb_lineup_batters`
            SET
                team_abbr = '{away_abbr}',
                opponent_team_abbr = '{home_abbr}'
            WHERE game_pk = {game_pk} AND is_home = FALSE
            """
            # Update home team batters
            query_home = f"""
            UPDATE `{self.project_id}.mlb_raw.mlb_lineup_batters`
            SET
                team_abbr = '{home_abbr}',
                opponent_team_abbr = '{away_abbr}'
            WHERE game_pk = {game_pk} AND is_home = TRUE
            """
            try:
                self.client.query(query_away).result()
                self.client.query(query_home).result()
                updated += 1
            except Exception as e:
                logger.warning(f"Error updating lineup_batters for {game_pk}: {e}")

        logger.info(f"Updated {updated} games in mlb_lineup_batters")
        return updated

    def _update_pitcher_stats(self, abbr_lookup: Dict[int, Tuple[str, str]]) -> int:
        """Update mlb_pitcher_stats table."""
        updated = 0
        for game_pk, (away_abbr, home_abbr) in abbr_lookup.items():
            # Update away team pitchers
            query_away = f"""
            UPDATE `{self.project_id}.mlb_raw.mlb_pitcher_stats`
            SET
                team_abbr = '{away_abbr}',
                opponent_team_abbr = '{home_abbr}',
                game_id = CONCAT(game_date, '_{away_abbr}_{home_abbr}')
            WHERE game_pk = {game_pk} AND is_home = FALSE
            """
            # Update home team pitchers
            query_home = f"""
            UPDATE `{self.project_id}.mlb_raw.mlb_pitcher_stats`
            SET
                team_abbr = '{home_abbr}',
                opponent_team_abbr = '{away_abbr}',
                game_id = CONCAT(game_date, '_{away_abbr}_{home_abbr}')
            WHERE game_pk = {game_pk} AND is_home = TRUE
            """
            try:
                self.client.query(query_away).result()
                self.client.query(query_home).result()
                updated += 1
            except Exception as e:
                logger.warning(f"Error updating pitcher_stats for {game_pk}: {e}")

        logger.info(f"Updated {updated} games in mlb_pitcher_stats")
        return updated

    def _update_batter_stats(self, abbr_lookup: Dict[int, Tuple[str, str]]) -> int:
        """Update bdl_batter_stats table."""
        updated = 0
        for game_pk, (away_abbr, home_abbr) in abbr_lookup.items():
            # This table stores game_pk in source_file_path
            # We need to update based on that
            query = f"""
            UPDATE `{self.project_id}.mlb_raw.bdl_batter_stats`
            SET
                home_team_abbr = '{home_abbr}',
                away_team_abbr = '{away_abbr}',
                game_id = CONCAT(game_date, '_{away_abbr}_{home_abbr}'),
                team_abbr = CASE
                    WHEN team_abbr = 'UNK' AND is_postseason = FALSE THEN
                        CASE WHEN home_team_score > away_team_score THEN '{home_abbr}' ELSE '{away_abbr}' END
                    ELSE team_abbr
                END
            WHERE CAST(SPLIT(source_file_path, '/')[SAFE_OFFSET(3)] AS INT64) = {game_pk}
            """
            try:
                self.client.query(query).result()
                updated += 1
            except Exception as e:
                logger.warning(f"Error updating batter_stats for {game_pk}: {e}")

        # Now fix team_abbr based on player being in home or away lineup
        # This requires joining with lineup_batters which now has correct abbrs
        fix_team_abbr_query = f"""
        UPDATE `{self.project_id}.mlb_raw.bdl_batter_stats` b
        SET team_abbr = COALESCE(lb.team_abbr, b.team_abbr)
        FROM `{self.project_id}.mlb_raw.mlb_lineup_batters` lb
        WHERE b.team_abbr = 'UNK'
          AND b.game_date = lb.game_date
          AND b.player_lookup = lb.player_lookup
        """
        try:
            result = self.client.query(fix_team_abbr_query).result()
            logger.info("Fixed team_abbr via lineup_batters join")
        except Exception as e:
            logger.warning(f"Error in team_abbr join fix: {e}")

        logger.info(f"Updated {updated} games in bdl_batter_stats")
        return updated

    def run(self, tables: List[str] = None) -> Dict[str, int]:
        """Run the fix for specified tables."""
        tables = tables or TABLES_TO_FIX
        results = {}

        logger.info("=" * 60)
        logger.info("MLB TEAM ABBREVIATION FIX")
        logger.info("=" * 60)
        logger.info(f"Dry run: {self.dry_run}")
        logger.info(f"Tables: {tables}")
        logger.info("")

        for table in tables:
            logger.info(f"\n--- Processing {table} ---")

            # Get games needing fix
            game_pks = self.get_games_needing_fix(table)

            if not game_pks:
                logger.info(f"No games need fixing in {table}")
                results[table] = 0
                continue

            # Fix the table
            fixed = self.fix_table(table, game_pks)
            results[table] = fixed

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"API calls: {self.api_calls}")
        logger.info(f"Cache hits: {self.cache_hits}")
        for table, count in results.items():
            logger.info(f"  {table}: {count} games fixed")

        if self.dry_run:
            logger.info("\n[DRY RUN] No actual changes made")

        return results


def main():
    parser = argparse.ArgumentParser(description='Fix MLB Team Abbreviations')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed')
    parser.add_argument('--table', help='Fix specific table only')

    args = parser.parse_args()

    tables = [args.table] if args.table else None

    fixer = TeamAbbreviationFixer(dry_run=args.dry_run)
    fixer.run(tables=tables)


if __name__ == '__main__':
    main()
