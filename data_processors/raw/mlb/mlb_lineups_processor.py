#!/usr/bin/env python3
"""
MLB Lineups Processor

Processes output from mlb_lineups scraper to BigQuery.
CRITICAL for bottom-up model - provides batting lineups.

GCS Path: mlb-stats-api/lineups/{date}/{timestamp}.json
Target Tables:
- mlb_raw.mlb_game_lineups (one row per game)
- mlb_raw.mlb_lineup_batters (one row per batter)

Data Format (input):
{
    "scrape_date": "2025-06-15",
    "total_games": 15,
    "lineups_available": 10,
    "games": [
        {
            "game_pk": 745263,
            "game_date": "2025-06-15",
            "away_team_abbr": "NYY",
            "home_team_abbr": "BOS",
            "away_lineup": [
                {"player_id": 123, "player_name": "Aaron Judge", "batting_order": 1, "position": "RF"},
                ...
            ],
            "home_lineup": [...],
            ...
        }
    ]
}

Processing Strategy: MERGE_UPDATE per game_pk
- Replaces lineups as they become available
- Supports re-scraping as lineups change

Created: 2026-01-06
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


class MlbLineupsProcessor(ProcessorBase):
    """
    MLB Lineups Processor

    Processes lineup data from MLB Stats API to BigQuery.
    Critical for bottom-up strikeout model - tells us which batters to sum.

    Writes to two tables:
    1. mlb_game_lineups - Summary per game
    2. mlb_lineup_batters - Individual batters (for joining with K rates)

    Processing Strategy: MERGE_UPDATE
    - Deletes existing records for each game before inserting
    - Allows lineup updates as they're announced
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()  # mlb_raw
        super().__init__()
        self.table_name_games = 'mlb_game_lineups'
        self.table_name_batters = 'mlb_lineup_batters'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load lineup data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_player_name(self, name: str) -> str:
        """Create normalized player lookup string."""
        if not name:
            return ""
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        return normalized

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if 'games' not in data:
            errors.append("Missing 'games' field")
            return errors

        if not isinstance(data['games'], list):
            errors.append("'games' is not a list")
            return errors

        return errors

    def transform_data(self) -> None:
        """Transform raw lineup data for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')

        game_rows = []
        batter_rows = []
        skipped_count = 0

        games = raw_data.get('games', [])
        logger.info(f"Processing lineups for {len(games)} games from {file_path}")

        for game in games:
            try:
                game_pk = game.get('game_pk')
                game_date = game.get('game_date')

                if not game_pk or not game_date:
                    skipped_count += 1
                    continue

                away_lineup = game.get('away_lineup', [])
                home_lineup = game.get('home_lineup', [])

                # Game summary row
                game_row = {
                    'game_pk': game_pk,
                    'game_date': game_date,
                    'game_time_utc': game.get('game_time_utc'),

                    'away_team_id': game.get('away_team_id'),
                    'away_team_name': game.get('away_team_name'),
                    'away_team_abbr': game.get('away_team_abbr', ''),
                    'home_team_id': game.get('home_team_id'),
                    'home_team_name': game.get('home_team_name'),
                    'home_team_abbr': game.get('home_team_abbr', ''),

                    'venue_name': game.get('venue_name'),
                    'status_code': game.get('status_code'),
                    'lineups_available': game.get('lineups_available', False),

                    'away_lineup_count': len(away_lineup),
                    'home_lineup_count': len(home_lineup),

                    'source_file_path': file_path,
                    'scraped_at': datetime.now(timezone.utc).isoformat(),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat(),
                }
                game_rows.append(game_row)

                # Get pitcher info for context
                away_pitchers = game.get('away_pitchers', [])
                home_pitchers = game.get('home_pitchers', [])
                away_starter = away_pitchers[0] if away_pitchers else {}
                home_starter = home_pitchers[0] if home_pitchers else {}

                # Process away lineup batters
                for batter in away_lineup:
                    batter_row = self._create_batter_row(
                        game_pk=game_pk,
                        game_date=game_date,
                        team_abbr=game.get('away_team_abbr', ''),
                        is_home=False,
                        opponent_team_abbr=game.get('home_team_abbr', ''),
                        opponent_pitcher=home_starter,
                        batter=batter,
                        file_path=file_path
                    )
                    if batter_row:
                        batter_rows.append(batter_row)

                # Process home lineup batters
                for batter in home_lineup:
                    batter_row = self._create_batter_row(
                        game_pk=game_pk,
                        game_date=game_date,
                        team_abbr=game.get('home_team_abbr', ''),
                        is_home=True,
                        opponent_team_abbr=game.get('away_team_abbr', ''),
                        opponent_pitcher=away_starter,
                        batter=batter,
                        file_path=file_path
                    )
                    if batter_row:
                        batter_rows.append(batter_row)

            except Exception as e:
                logger.error(f"Error processing game: {e}")
                skipped_count += 1
                continue

        logger.info(
            f"Transformed {len(game_rows)} games, {len(batter_rows)} batters, "
            f"skipped {skipped_count}"
        )

        self.transformed_data = {
            'game_rows': game_rows,
            'batter_rows': batter_rows,
        }

    def _create_batter_row(
        self,
        game_pk: int,
        game_date: str,
        team_abbr: str,
        is_home: bool,
        opponent_team_abbr: str,
        opponent_pitcher: Dict,
        batter: Dict,
        file_path: str
    ) -> Optional[Dict]:
        """Create a batter row for the lineup_batters table."""
        player_id = batter.get('player_id')
        player_name = batter.get('player_name')
        batting_order = batter.get('batting_order')

        if not player_id or not player_name or not batting_order:
            return None

        return {
            'game_pk': game_pk,
            'game_date': game_date,

            'team_abbr': team_abbr,
            'is_home': is_home,

            'player_id': player_id,
            'player_name': player_name,
            'player_lookup': self.normalize_player_name(player_name),

            'batting_order': batting_order,
            'position': batter.get('position'),
            'position_name': batter.get('position_name'),

            'opponent_team_abbr': opponent_team_abbr,
            'opponent_pitcher_id': opponent_pitcher.get('player_id'),
            'opponent_pitcher_name': opponent_pitcher.get('player_name'),

            'source_file_path': file_path,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat(),
        }

    def save_data(self) -> None:
        """Save transformed data to BigQuery (both tables)."""
        game_rows = self.transformed_data.get('game_rows', [])
        batter_rows = self.transformed_data.get('batter_rows', [])

        if not game_rows:
            logger.info("No game rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        errors = []

        try:
            # Get unique game PKs for delete operations
            game_pks = set(row['game_pk'] for row in game_rows)
            game_dates = set(row['game_date'] for row in game_rows)

            # Save game lineups table
            games_table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name_games}"
            self._save_to_table(games_table_id, game_rows, game_pks, 'game_pk')

            # Save batter lineups table
            batters_table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name_batters}"
            self._save_to_table(batters_table_id, batter_rows, game_pks, 'game_pk')

            self.stats['rows_inserted'] = len(game_rows) + len(batter_rows)

            # Stats for notification
            lineups_available = sum(1 for r in game_rows if r.get('lineups_available'))

            notify_info(
                title="MLB Lineups Processing Complete",
                message=f"Processed {len(game_rows)} games, {len(batter_rows)} batters",
                details={
                    'games': len(game_rows),
                    'batters': len(batter_rows),
                    'lineups_available': lineups_available,
                    'processor': 'MlbLineupsProcessor'
                },
                processor_name=self.__class__.__name__
            )

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")
            self.stats["rows_inserted"] = 0

            notify_error(
                title="MLB Lineups Processing Failed",
                message=f"Error: {str(e)[:200]}",
                details={
                    'error': error_msg,
                    'processor': 'MlbLineupsProcessor'
                },
                processor_name="MlbLineupsProcessor"
            )
            raise

        return {
            'rows_processed': len(game_rows) + len(batter_rows),
            'game_rows': len(game_rows),
            'batter_rows': len(batter_rows),
            'errors': errors
        }

    def _save_to_table(
        self,
        table_id: str,
        rows: List[Dict],
        game_pks: set,
        key_field: str
    ) -> None:
        """Save rows to a specific table."""
        if not rows:
            return

        # Delete existing records for these games
        for game_pk in game_pks:
            # Get game_date for partition filter
            game_date = next(
                (r['game_date'] for r in rows if r.get('game_pk') == game_pk),
                None
            )
            if not game_date:
                continue

            try:
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE {key_field} = {game_pk}
                  AND game_date = '{game_date}'
                """
                self.bq_client.query(delete_query).result(timeout=60)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.info(f"Table {table_id} doesn't exist yet")
                    break
                else:
                    logger.warning(f"Delete failed for game {game_pk}: {e}")

        # Insert new data
        try:
            table = self.bq_client.get_table(table_id)

            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)

            logger.info(f"Saved {len(rows)} rows to {table_id}")

        except Exception as e:
            if 'not found' in str(e).lower():
                logger.warning(f"Table {table_id} not found - run schema SQL first")
            raise

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'run_id': self.stats.get('run_id'),
        }


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB lineups from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')

    args = parser.parse_args()

    processor = MlbLineupsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
