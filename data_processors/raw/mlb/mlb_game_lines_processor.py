#!/usr/bin/env python3
"""
MLB Odds API Game Lines Processor

Processes game odds (moneyline, spreads, totals) from The Odds API to BigQuery.
Context data for strikeout predictions:
- Low totals = pitcher's duel = more K's expected
- Large spreads = quality mismatch

GCS Path: mlb-odds-api/game-lines/{date}/{timestamp}.json
Target Table: mlb_raw.oddsa_game_lines

Data Format (input from scraper):
{
    "sport": "baseball_mlb",
    "game_date": "2025-06-15",
    "markets": "h2h,spreads,totals",
    "gameCount": 15,
    "outcomeCount": 180,
    "games": [
        {
            "id": "abc123...",
            "sport_key": "baseball_mlb",
            "commence_time": "2025-06-15T23:10:00Z",
            "home_team": "New York Yankees",
            "away_team": "Boston Red Sox",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": "2025-06-15T20:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "New York Yankees", "price": -150},
                                {"name": "Boston Red Sox", "price": +130}
                            ]
                        },
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "New York Yankees", "price": +140, "point": -1.5},
                                {"name": "Boston Red Sox", "price": -160, "point": 1.5}
                            ]
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -110, "point": 8.5},
                                {"name": "Under", "price": -110, "point": 8.5}
                            ]
                        }
                    ]
                }
            ]
        }
    ]
}

Created: 2026-01-06
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


# MLB team mappings
MLB_TEAM_MAP = {
    'arizona diamondbacks': 'ARI', 'atlanta braves': 'ATL',
    'baltimore orioles': 'BAL', 'boston red sox': 'BOS',
    'chicago cubs': 'CHC', 'chicago white sox': 'CHW',
    'cincinnati reds': 'CIN', 'cleveland guardians': 'CLE',
    'colorado rockies': 'COL', 'detroit tigers': 'DET',
    'houston astros': 'HOU', 'kansas city royals': 'KC',
    'los angeles angels': 'LAA', 'los angeles dodgers': 'LAD',
    'miami marlins': 'MIA', 'milwaukee brewers': 'MIL',
    'minnesota twins': 'MIN', 'new york mets': 'NYM',
    'new york yankees': 'NYY', 'oakland athletics': 'OAK',
    'philadelphia phillies': 'PHI', 'pittsburgh pirates': 'PIT',
    'san diego padres': 'SD', 'san francisco giants': 'SF',
    'seattle mariners': 'SEA', 'st. louis cardinals': 'STL',
    'st louis cardinals': 'STL', 'tampa bay rays': 'TB',
    'texas rangers': 'TEX', 'toronto blue jays': 'TOR',
    'washington nationals': 'WSH',
}


class MlbGameLinesProcessor(ProcessorBase):
    """
    MLB Odds API Game Lines Processor

    Processes moneyline, spread, and totals from GCS to BigQuery.
    Provides context for strikeout predictions.

    Processing Strategy: APPEND_ALWAYS
    - Time-series data for line movement tracking
    - Multiple snapshots per day
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()
        super().__init__()
        self.table_name = 'oddsa_game_lines'
        self.processing_strategy = 'APPEND_ALWAYS'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load game lines data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def get_team_abbr(self, team_name: str) -> str:
        """Get MLB team abbreviation from full name."""
        if not team_name:
            return ''

        team_lower = team_name.lower().strip()
        if team_lower in MLB_TEAM_MAP:
            return MLB_TEAM_MAP[team_lower]

        for full_name, abbr in MLB_TEAM_MAP.items():
            if full_name in team_lower or team_lower in full_name:
                return abbr

        return team_name[:3].upper() if team_name else ''

    def american_to_implied_prob(self, american_odds: int) -> Optional[float]:
        """Convert American odds to implied probability."""
        if american_odds is None:
            return None

        if american_odds < 0:
            return abs(american_odds) / (abs(american_odds) + 100)
        else:
            return 100 / (american_odds + 100)

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if not data:
            errors.append("Empty data")
            return errors

        if 'games' not in data:
            errors.append("Missing 'games' field")
            return errors

        if not isinstance(data['games'], list):
            errors.append("'games' is not a list")

        return errors

    def transform_data(self) -> None:
        """Transform raw data into rows for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            errors = self.validate_data(raw_data)
            if errors:
                logger.warning(f"Validation issues for {file_path}: {errors}")
                self.transformed_data = rows
                return

            game_date = raw_data.get('game_date')
            games = raw_data.get('games', [])
            snapshot_time = datetime.now(timezone.utc)

            for game in games:
                event_id = game.get('id')
                home_team = game.get('home_team', '')
                away_team = game.get('away_team', '')
                home_team_abbr = self.get_team_abbr(home_team)
                away_team_abbr = self.get_team_abbr(away_team)

                # Generate game_id
                if game_date and away_team_abbr and home_team_abbr:
                    game_id = f"{game_date.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
                else:
                    game_id = event_id

                # Process each bookmaker
                for bookmaker in game.get('bookmakers', []):
                    bookmaker_key = bookmaker.get('key', '')
                    last_update = bookmaker.get('last_update')

                    if last_update:
                        try:
                            last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            last_update_dt = None
                    else:
                        last_update_dt = None

                    # Initialize row with base data
                    row = {
                        'game_id': game_id,
                        'game_date': game_date,
                        'event_id': event_id,
                        'home_team': home_team,
                        'away_team': away_team,
                        'home_team_abbr': home_team_abbr,
                        'away_team_abbr': away_team_abbr,
                        'bookmaker': bookmaker_key,
                        'last_update': last_update_dt.isoformat() if last_update_dt else None,
                        'snapshot_time': snapshot_time.isoformat(),
                        'source_file_path': file_path,
                        'created_at': snapshot_time.isoformat(),
                        # Initialize all market fields to None
                        'home_ml': None,
                        'away_ml': None,
                        'home_ml_implied': None,
                        'away_ml_implied': None,
                        'home_spread': None,
                        'home_spread_price': None,
                        'away_spread': None,
                        'away_spread_price': None,
                        'total_runs': None,
                        'over_price': None,
                        'under_price': None,
                    }

                    # Process each market
                    for market in bookmaker.get('markets', []):
                        market_key = market.get('key', '')
                        outcomes = market.get('outcomes', [])

                        if market_key == 'h2h':
                            # Moneyline
                            for outcome in outcomes:
                                price = outcome.get('price')
                                if outcome.get('name') == home_team:
                                    row['home_ml'] = price
                                    row['home_ml_implied'] = self.american_to_implied_prob(price)
                                elif outcome.get('name') == away_team:
                                    row['away_ml'] = price
                                    row['away_ml_implied'] = self.american_to_implied_prob(price)

                        elif market_key == 'spreads':
                            # Run line
                            for outcome in outcomes:
                                point = outcome.get('point')
                                price = outcome.get('price')
                                if outcome.get('name') == home_team:
                                    row['home_spread'] = point
                                    row['home_spread_price'] = price
                                elif outcome.get('name') == away_team:
                                    row['away_spread'] = point
                                    row['away_spread_price'] = price

                        elif market_key == 'totals':
                            # Over/under
                            for outcome in outcomes:
                                point = outcome.get('point')
                                price = outcome.get('price')
                                if outcome.get('name') == 'Over':
                                    row['total_runs'] = point
                                    row['over_price'] = price
                                elif outcome.get('name') == 'Under':
                                    row['under_price'] = price

                    rows.append(row)

            logger.info(f"Transformed {len(rows)} game line rows from {file_path}")
            self.transformed_data = rows

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            notify_error(
                title="MLB Game Lines Transform Failed",
                message=f"Error transforming game lines: {str(e)[:200]}",
                details={'file_path': file_path, 'error': str(e)},
                processor_name="MlbGameLinesProcessor"
            )
            raise

    def save_data(self) -> None:
        """Save transformed data to BigQuery."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        try:
            try:
                target_table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.error(f"Table {table_id} not found - run schema SQL first")
                    raise
                raise

            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")
                return

            self.stats['rows_inserted'] = len(rows)

            # Summary
            unique_games = len(set(r.get('game_id') for r in rows))
            avg_total = sum(r.get('total_runs') or 0 for r in rows if r.get('total_runs')) / max(1, len([r for r in rows if r.get('total_runs')]))

            logger.info(f"Successfully loaded {len(rows)} game line rows to {table_id}")

            notify_info(
                title="MLB Game Lines Processing Complete",
                message=f"Loaded {len(rows)} game lines for {unique_games} games",
                details={
                    'rows_loaded': len(rows),
                    'unique_games': unique_games,
                    'avg_total': round(avg_total, 1) if avg_total else None,
                    'table': f"{self.dataset_id}.{self.table_name}",
                }
            )

        except Exception as e:
            logger.error(f"Failed to save data: {e}", exc_info=True)
            notify_error(
                title="MLB Game Lines Save Failed",
                message=f"Error saving to BigQuery: {str(e)[:200]}",
                details={'table': self.table_name, 'error': str(e)},
                processor_name="MlbGameLinesProcessor"
            )
            raise

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB game lines from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')

    args = parser.parse_args()

    processor = MlbGameLinesProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
