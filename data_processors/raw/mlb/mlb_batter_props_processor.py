#!/usr/bin/env python3
"""
MLB Odds API Batter Props Processor

Processes batter prop odds from The Odds API to BigQuery.
CRITICAL for bottom-up K prediction model: Pitcher K's ≈ Σ (batter K probabilities)

GCS Path: mlb-odds-api/batter-props/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
Target Table: mlb_raw.oddsa_batter_props

Data Format (input from scraper):
{
    "sport": "baseball_mlb",
    "eventId": "abc123",
    "game_date": "2025-06-15",
    "markets": "batter_strikeouts,batter_hits,...",
    "rowCount": 48,
    "batterStrikeoutLineCount": 18,
    "totalImpliedKs": 9.5,
    "strikeoutLines": [...],
    "odds": {  # Full Odds API response
        "id": "abc123",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "batter_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Aaron Judge", "price": -125, "point": 0.5},
                            {"name": "Under", "description": "Aaron Judge", "price": +105, "point": 0.5},
                        ]
                    }
                ]
            }
        ]
    }
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
from shared.utils.player_name_normalizer import normalize_name_for_lookup
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


# MLB team abbreviations and mappings (shared with pitcher props)
MLB_TEAM_ABBREVS = {
    'ARI', 'ATL', 'BAL', 'BOS', 'CHC', 'CHW', 'CIN', 'CLE', 'COL', 'DET',
    'HOU', 'KC', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY', 'OAK',
    'PHI', 'PIT', 'SD', 'SF', 'SEA', 'STL', 'TB', 'TEX', 'TOR', 'WSH'
}

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


class MlbBatterPropsProcessor(ProcessorBase):
    """
    MLB Odds API Batter Props Processor

    Processes batter prop odds from GCS to BigQuery.
    Critical for bottom-up K prediction model:
      Pitcher K's ≈ Σ (individual batter K probabilities)

    Processing Strategy: APPEND_ALWAYS
    - Time-series data - each snapshot is stored
    - Multiple snapshots per game for line movement tracking
    """

    def __init__(self):
        self.dataset_id = get_raw_dataset()
        super().__init__()
        self.table_name = 'oddsa_batter_props'
        self.processing_strategy = 'APPEND_ALWAYS'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.unknown_teams = set()

    def load_data(self) -> None:
        """Load batter props data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def get_team_abbr(self, team_name: str) -> str:
        """Get MLB standard team abbreviation from full name."""
        if not team_name:
            return ''

        if team_name.upper() in MLB_TEAM_ABBREVS:
            return team_name.upper()

        team_lower = team_name.lower().strip()
        if team_lower in MLB_TEAM_MAP:
            return MLB_TEAM_MAP[team_lower]

        for full_name, abbr in MLB_TEAM_MAP.items():
            if full_name in team_lower or team_lower in full_name:
                return abbr

        logger.warning(f"Unknown MLB team: {team_name}")
        self.unknown_teams.add(team_name)
        return team_name[:3].upper() if team_name else ''

    def american_to_implied_prob(self, american_odds: int) -> Optional[float]:
        """Convert American odds to implied probability."""
        if american_odds is None:
            return None

        if american_odds < 0:
            return abs(american_odds) / (abs(american_odds) + 100)
        else:
            return 100 / (american_odds + 100)

    def calculate_expected_ks(self, point: float, over_prob: Optional[float]) -> Optional[float]:
        """
        Calculate expected strikeouts for a batter based on line and probability.

        For batter strikeout lines (usually 0.5 or 1.5):
        - If line is 0.5 and over_prob is 0.55, expected ≈ 0.55 K's
        - If line is 1.5 and over_prob is 0.40, expected ≈ 1.5 * 0.40 + 0.5 * 0.60 ≈ 0.9 K's

        Simplified calculation: weighted average based on probability
        """
        if point is None or over_prob is None:
            return None

        # For typical 0.5 lines: expected = over_prob (probability of 1+ K's)
        if point == 0.5:
            return over_prob

        # For 1.5 lines: more complex - approximate
        # Expected = P(over) * 2 + P(under) * 0.5 (simplified)
        if point == 1.5:
            under_prob = 1 - over_prob
            return over_prob * 2 + under_prob * 0.5

        # Generic approximation
        return point * over_prob

    def extract_metadata_from_path(self, file_path: str) -> Dict:
        """Extract metadata from GCS file path."""
        path_parts = file_path.split('/')

        if len(path_parts) < 4:
            return {'game_date': None, 'event_id': None, 'teams_suffix': None, 'snapshot_tag': None}

        date_str = path_parts[-3] if len(path_parts) >= 3 else None
        event_folder = path_parts[-2] if len(path_parts) >= 2 else ''
        parts = event_folder.rsplit('-', 1)
        event_id = parts[0] if parts else event_folder
        teams_suffix = parts[1] if len(parts) > 1 else None

        filename = path_parts[-1].replace('.json', '') if path_parts else ''
        snapshot_parts = filename.split('-snap-')
        snapshot_tag = f"snap-{snapshot_parts[1]}" if len(snapshot_parts) > 1 else None

        return {
            'game_date': date_str,
            'event_id': event_id,
            'teams_suffix': teams_suffix,
            'snapshot_tag': snapshot_tag,
            'source_file_path': file_path,
        }

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if not data:
            errors.append("Empty data")
            return errors

        if 'odds' not in data:
            errors.append("Missing 'odds' field")
            return errors

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

            metadata = self.extract_metadata_from_path(file_path)

            game_date = raw_data.get('game_date') or metadata.get('game_date')
            event_id = raw_data.get('eventId') or metadata.get('event_id')

            odds_data = raw_data.get('odds', {})
            if isinstance(odds_data, list):
                odds_data = odds_data[0] if odds_data else {}

            # Get team info
            home_team_full = odds_data.get('home_team', '')
            away_team_full = odds_data.get('away_team', '')
            home_team_abbr = self.get_team_abbr(home_team_full)
            away_team_abbr = self.get_team_abbr(away_team_full)

            # Generate game_id
            if event_id:
                game_id = event_id
            elif game_date and away_team_abbr and home_team_abbr:
                game_id = f"{game_date.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
            else:
                game_id = None

            snapshot_time = datetime.now(timezone.utc)

            # Process each bookmaker
            for bookmaker in odds_data.get('bookmakers', []):
                bookmaker_key = bookmaker.get('key', '')
                last_update = bookmaker.get('last_update')

                if last_update:
                    try:
                        last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        last_update_dt = None
                else:
                    last_update_dt = None

                # Process each market
                for market in bookmaker.get('markets', []):
                    market_key = market.get('key', '')

                    # Group outcomes by player
                    player_props = {}
                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description', '')
                        outcome_type = outcome.get('name', '')
                        price = outcome.get('price')
                        point = outcome.get('point')

                        if not player_name:
                            continue

                        if player_name not in player_props:
                            player_props[player_name] = {
                                'point': point,
                                'over_price': None,
                                'under_price': None,
                            }

                        if outcome_type == 'Over':
                            player_props[player_name]['over_price'] = price
                            player_props[player_name]['point'] = point
                        elif outcome_type == 'Under':
                            player_props[player_name]['under_price'] = price

                    # Create a row for each batter's prop
                    for player_name, props in player_props.items():
                        # Calculate implied probabilities
                        over_implied = self.american_to_implied_prob(props['over_price'])
                        under_implied = self.american_to_implied_prob(props['under_price'])

                        # Calculate expected K's (for bottom-up model)
                        expected_ks = None
                        if market_key == 'batter_strikeouts' and over_implied is not None:
                            expected_ks = self.calculate_expected_ks(props['point'], over_implied)

                        # Batter's team is unknown from odds data alone
                        # Would need roster lookup - for now leave as None
                        team_abbr = None

                        # Opposing team is also unknown without roster data
                        # The batter faces the opposing pitcher's team
                        opposing_team_abbr = None

                        row = {
                            # Identifiers
                            'game_id': game_id,
                            'game_date': game_date,
                            'event_id': event_id,

                            # Batter
                            'player_name': player_name,
                            'player_lookup': normalize_name_for_lookup(player_name),
                            'team_abbr': team_abbr,

                            # Game context
                            'home_team_abbr': home_team_abbr,
                            'away_team_abbr': away_team_abbr,
                            'opposing_team_abbr': opposing_team_abbr,

                            # Market
                            'market_key': market_key,
                            'bookmaker': bookmaker_key,

                            # Line details
                            'point': props['point'],
                            'over_price': props['over_price'],
                            'under_price': props['under_price'],
                            'over_implied_prob': over_implied,
                            'under_implied_prob': under_implied,

                            # Derived for model
                            'expected_ks': expected_ks,

                            # Metadata
                            'last_update': last_update_dt.isoformat() if last_update_dt else None,
                            'snapshot_time': snapshot_time.isoformat(),
                            'source_file_path': file_path,
                            'created_at': snapshot_time.isoformat(),
                        }

                        rows.append(row)

            # Calculate summary stats
            strikeout_rows = [r for r in rows if r.get('market_key') == 'batter_strikeouts']
            total_expected_ks = sum(r.get('expected_ks') or 0 for r in strikeout_rows)
            unique_batters = len(set(r.get('player_lookup') for r in strikeout_rows))

            logger.info(
                f"Transformed {len(rows)} batter prop rows ({len(strikeout_rows)} strikeout lines, "
                f"~{total_expected_ks:.1f} expected K's) from {file_path}"
            )

            self.transformed_data = rows

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            notify_error(
                title="MLB Batter Props Transform Failed",
                message=f"Error transforming batter props: {str(e)[:200]}",
                details={
                    'file_path': file_path,
                    'error_type': type(e).__name__,
                    'error': str(e),
                },
                processor_name="MlbBatterPropsProcessor"
            )
            raise

    def save_data(self) -> None:
        """Save transformed data to BigQuery using batch loading."""
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
                notify_error(
                    title="MLB Batter Props Load Errors",
                    message=f"Encountered {len(load_job.errors)} errors",
                    details={
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'errors': str(load_job.errors)[:500],
                    },
                    processor_name="MlbBatterPropsProcessor"
                )
                return

            self.stats['rows_inserted'] = len(rows)

            # Summary
            strikeout_rows = [r for r in rows if r.get('market_key') == 'batter_strikeouts']
            total_expected_ks = sum(r.get('expected_ks') or 0 for r in strikeout_rows)
            unique_batters = len(set(r.get('player_lookup') for r in strikeout_rows))

            logger.info(f"Successfully loaded {len(rows)} batter prop rows to {table_id}")

            notify_info(
                title="MLB Batter Props Processing Complete",
                message=f"Loaded {len(rows)} prop lines ({len(strikeout_rows)} strikeouts, ~{total_expected_ks:.1f} expected K's)",
                details={
                    'rows_loaded': len(rows),
                    'strikeout_lines': len(strikeout_rows),
                    'unique_batters': unique_batters,
                    'total_expected_ks': round(total_expected_ks, 1),
                    'table': f"{self.dataset_id}.{self.table_name}",
                },
                processor_name=self.__class__.__name__
            )

            if self.unknown_teams:
                notify_warning(
                    title="Unknown MLB Teams Detected",
                    message=f"Found {len(self.unknown_teams)} unknown team names",
                    details={'unknown_teams': list(self.unknown_teams)},
                    processor_name=self.__class__.__name__
                )

        except Exception as e:
            logger.error(f"Failed to save data: {e}", exc_info=True)
            self.stats["rows_inserted"] = 0
            notify_error(
                title="MLB Batter Props Save Failed",
                message=f"Error saving to BigQuery: {str(e)[:200]}",
                details={
                    'table': self.table_name,
                    'rows_attempted': len(rows),
                    'error_type': type(e).__name__,
                    'error': str(e),
                },
                processor_name="MlbBatterPropsProcessor"
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


# CLI entry point for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB batter props from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')

    args = parser.parse_args()

    processor = MlbBatterPropsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
