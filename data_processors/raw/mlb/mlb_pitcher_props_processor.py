#!/usr/bin/env python3
"""
MLB Odds API Pitcher Props Processor

Processes pitcher prop odds from The Odds API to BigQuery.
PRIMARY TARGET: pitcher_strikeouts for K prediction model.

GCS Path: mlb-odds-api/pitcher-props/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
Target Table: mlb_raw.oddsa_pitcher_props

Data Format (input from scraper):
{
    "sport": "baseball_mlb",
    "eventId": "abc123",
    "game_date": "2025-06-15",
    "markets": "pitcher_strikeouts,pitcher_outs,...",
    "rowCount": 24,
    "strikeoutLineCount": 4,
    "strikeoutLines": [...],
    "odds": {  # Full Odds API response
        "id": "abc123",
        "commence_time": "2025-06-15T23:10:00Z",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Gerrit Cole", "price": -115, "point": 6.5},
                            {"name": "Under", "description": "Gerrit Cole", "price": -105, "point": 6.5},
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
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.utils.player_name_normalizer import normalize_name_for_lookup
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


# MLB team abbreviations for validation
MLB_TEAM_ABBREVS = {
    'ARI', 'ATL', 'BAL', 'BOS', 'CHC', 'CHW', 'CIN', 'CLE', 'COL', 'DET',
    'HOU', 'KC', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY', 'OAK',
    'PHI', 'PIT', 'SD', 'SF', 'SEA', 'STL', 'TB', 'TEX', 'TOR', 'WSH'
}

# Common team name to abbreviation mappings
MLB_TEAM_MAP = {
    # Full names
    'arizona diamondbacks': 'ARI',
    'atlanta braves': 'ATL',
    'baltimore orioles': 'BAL',
    'boston red sox': 'BOS',
    'chicago cubs': 'CHC',
    'chicago white sox': 'CHW',
    'cincinnati reds': 'CIN',
    'cleveland guardians': 'CLE',
    'colorado rockies': 'COL',
    'detroit tigers': 'DET',
    'houston astros': 'HOU',
    'kansas city royals': 'KC',
    'los angeles angels': 'LAA',
    'los angeles dodgers': 'LAD',
    'miami marlins': 'MIA',
    'milwaukee brewers': 'MIL',
    'minnesota twins': 'MIN',
    'new york mets': 'NYM',
    'new york yankees': 'NYY',
    'oakland athletics': 'OAK',
    'philadelphia phillies': 'PHI',
    'pittsburgh pirates': 'PIT',
    'san diego padres': 'SD',
    'san francisco giants': 'SF',
    'seattle mariners': 'SEA',
    'st. louis cardinals': 'STL',
    'st louis cardinals': 'STL',
    'tampa bay rays': 'TB',
    'texas rangers': 'TEX',
    'toronto blue jays': 'TOR',
    'washington nationals': 'WSH',
    # City only
    'arizona': 'ARI',
    'atlanta': 'ATL',
    'baltimore': 'BAL',
    'boston': 'BOS',
    'chicago': 'CHC',  # Ambiguous - default to Cubs
    'cincinnati': 'CIN',
    'cleveland': 'CLE',
    'colorado': 'COL',
    'detroit': 'DET',
    'houston': 'HOU',
    'kansas city': 'KC',
    'los angeles': 'LAD',  # Ambiguous - default to Dodgers
    'miami': 'MIA',
    'milwaukee': 'MIL',
    'minnesota': 'MIN',
    'new york': 'NYY',  # Ambiguous - default to Yankees
    'oakland': 'OAK',
    'philadelphia': 'PHI',
    'pittsburgh': 'PIT',
    'san diego': 'SD',
    'san francisco': 'SF',
    'seattle': 'SEA',
    'st. louis': 'STL',
    'tampa bay': 'TB',
    'texas': 'TEX',
    'toronto': 'TOR',
    'washington': 'WSH',
}


class MlbPitcherPropsProcessor(ProcessorBase):
    """
    MLB Odds API Pitcher Props Processor

    Processes pitcher prop odds from GCS to BigQuery.
    Primary source for strikeout prediction model.

    Processing Strategy: APPEND_ALWAYS
    - Time-series data - each snapshot is stored
    - Multiple snapshots per game for line movement tracking
    """

    def __init__(self):
        # Set dataset before calling super().__init__
        self.dataset_id = get_raw_dataset()  # Will be 'mlb_raw' when SPORT=mlb
        super().__init__()
        self.table_name = 'oddsa_pitcher_props'
        self.processing_strategy = 'APPEND_ALWAYS'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.unknown_teams = set()

    def load_data(self) -> None:
        """Load pitcher props data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def get_team_abbr(self, team_name: str) -> str:
        """
        Get MLB standard team abbreviation from full name.

        Args:
            team_name: Full team name (e.g., "New York Yankees")

        Returns:
            Team abbreviation (e.g., "NYY")
        """
        if not team_name:
            return ''

        # Check if already an abbreviation
        if team_name.upper() in MLB_TEAM_ABBREVS:
            return team_name.upper()

        # Normalize and lookup
        team_lower = team_name.lower().strip()
        if team_lower in MLB_TEAM_MAP:
            return MLB_TEAM_MAP[team_lower]

        # Try partial matches
        for full_name, abbr in MLB_TEAM_MAP.items():
            if full_name in team_lower or team_lower in full_name:
                return abbr

        # Unknown team
        logger.warning(f"Unknown MLB team: {team_name}")
        self.unknown_teams.add(team_name)
        return team_name[:3].upper() if team_name else ''

    def american_to_implied_prob(self, american_odds: int) -> float:
        """
        Convert American odds to implied probability.

        Args:
            american_odds: American odds (e.g., -115, +105)

        Returns:
            Implied probability (0.0 to 1.0)
        """
        if american_odds is None:
            return None

        if american_odds < 0:
            # Favorite: prob = |odds| / (|odds| + 100)
            return abs(american_odds) / (abs(american_odds) + 100)
        else:
            # Underdog: prob = 100 / (odds + 100)
            return 100 / (american_odds + 100)

    def extract_metadata_from_path(self, file_path: str) -> Dict:
        """
        Extract metadata from GCS file path.

        Path format: mlb-odds-api/pitcher-props/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
        Example: mlb-odds-api/pitcher-props/2025-06-15/abc123-BOSNYYY/20250615_180000-snap-1800.json
        """
        path_parts = file_path.split('/')

        if len(path_parts) < 4:
            logger.warning(f"Invalid path format: {file_path}")
            return {
                'game_date': None,
                'event_id': None,
                'teams_suffix': None,
                'snapshot_tag': None,
            }

        # Extract date
        date_str = path_parts[-3] if len(path_parts) >= 3 else None

        # Extract event folder (e.g., "abc123-BOSNYYY")
        event_folder = path_parts[-2] if len(path_parts) >= 2 else ''
        parts = event_folder.rsplit('-', 1)
        event_id = parts[0] if parts else event_folder
        teams_suffix = parts[1] if len(parts) > 1 else None

        # Extract snapshot from filename
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
            errors.append("Missing 'odds' field - not a valid pitcher props file")
            return errors

        odds_data = data.get('odds')
        if not odds_data:
            # Empty odds is valid (no props available yet)
            logger.info("Empty odds data - no pitcher props for this event")
            return errors

        # Check for bookmakers
        if isinstance(odds_data, dict):
            bookmakers = odds_data.get('bookmakers', [])
            if not bookmakers:
                logger.info("No bookmakers found - props may not be posted yet")

        return errors

    def transform_data(self) -> None:
        """Transform raw data into rows for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            # Validate first
            errors = self.validate_data(raw_data)
            if errors:
                logger.warning(f"Validation issues for {file_path}: {errors}")

            # Extract metadata from file path
            metadata = self.extract_metadata_from_path(file_path)

            # Get game date from data or path
            game_date = raw_data.get('game_date') or metadata.get('game_date')
            event_id = raw_data.get('eventId') or metadata.get('event_id')

            # Get the full odds response
            odds_data = raw_data.get('odds', {})
            if isinstance(odds_data, list):
                odds_data = odds_data[0] if odds_data else {}

            # Parse commence time for snapshot calculations
            commence_time = odds_data.get('commence_time')
            if commence_time:
                try:
                    commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    commence_dt = None
            else:
                commence_dt = None

            # Get team info
            home_team_full = odds_data.get('home_team', '')
            away_team_full = odds_data.get('away_team', '')
            home_team_abbr = self.get_team_abbr(home_team_full)
            away_team_abbr = self.get_team_abbr(away_team_full)

            # Generate game_id (use event_id as primary, or create from teams)
            if event_id:
                game_id = event_id
            elif game_date and away_team_abbr and home_team_abbr:
                game_id = f"{game_date.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
            else:
                game_id = None

            # Current timestamp for snapshot
            snapshot_time = datetime.now(timezone.utc)

            # Process each bookmaker
            for bookmaker in odds_data.get('bookmakers', []):
                bookmaker_key = bookmaker.get('key', '')
                bookmaker_title = bookmaker.get('title', bookmaker_key)
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

                    # Group outcomes by player (Over/Under pairs)
                    player_props = {}
                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description', '')
                        outcome_type = outcome.get('name', '')  # 'Over' or 'Under'
                        price = outcome.get('price')  # American odds
                        point = outcome.get('point')  # Line value

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

                    # Create a row for each player's prop
                    for player_name, props in player_props.items():
                        # Determine pitcher's team (heuristic: if name contains team city)
                        # For now, leave as None - would need roster lookup
                        team_abbr = None

                        # Calculate implied probabilities
                        over_implied = self.american_to_implied_prob(props['over_price'])
                        under_implied = self.american_to_implied_prob(props['under_price'])

                        row = {
                            # Identifiers
                            'game_id': game_id,
                            'game_date': game_date,
                            'event_id': event_id,

                            # Pitcher
                            'player_name': player_name,
                            'player_lookup': normalize_name_for_lookup(player_name),
                            'team_abbr': team_abbr,

                            # Game context
                            'home_team_abbr': home_team_abbr,
                            'away_team_abbr': away_team_abbr,

                            # Market
                            'market_key': market_key,
                            'bookmaker': bookmaker_key,

                            # Line details
                            'point': props['point'],
                            'over_price': props['over_price'],
                            'under_price': props['under_price'],
                            'over_implied_prob': over_implied,
                            'under_implied_prob': under_implied,

                            # Metadata
                            'last_update': last_update_dt.isoformat() if last_update_dt else None,
                            'snapshot_time': snapshot_time.isoformat(),
                            'source_file_path': file_path,
                            'created_at': snapshot_time.isoformat(),
                        }

                        rows.append(row)

            # Count strikeout lines specifically
            strikeout_count = sum(1 for r in rows if r.get('market_key') == 'pitcher_strikeouts')

            logger.info(
                f"Transformed {len(rows)} pitcher prop rows ({strikeout_count} strikeout lines) "
                f"from {file_path}"
            )

            self.transformed_data = rows

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            notify_error(
                title="MLB Pitcher Props Transform Failed",
                message=f"Error transforming pitcher props: {str(e)[:200]}",
                details={
                    'file_path': file_path,
                    'error_type': type(e).__name__,
                    'error': str(e),
                },
                processor_name="MlbPitcherPropsProcessor"
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
            # Get target table schema
            try:
                target_table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.error(f"Table {table_id} not found - run schema SQL first")
                    raise
                raise

            # Configure batch load
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            # Batch load (no streaming buffer)
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")
                notify_error(
                    title="MLB Pitcher Props Load Errors",
                    message=f"Encountered {len(load_job.errors)} errors",
                    details={
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'errors': str(load_job.errors)[:500],
                    },
                    processor_name="MlbPitcherPropsProcessor"
                )
                return

            # Track stats
            self.stats['rows_inserted'] = len(rows)

            # Calculate summary
            strikeout_count = sum(1 for r in rows if r.get('market_key') == 'pitcher_strikeouts')
            unique_pitchers = len(set(r.get('player_lookup') for r in rows))

            logger.info(f"Successfully loaded {len(rows)} pitcher prop rows to {table_id}")

            notify_info(
                title="MLB Pitcher Props Processing Complete",
                message=f"Loaded {len(rows)} prop lines ({strikeout_count} strikeouts)",
                details={
                    'rows_loaded': len(rows),
                    'strikeout_lines': strikeout_count,
                    'unique_pitchers': unique_pitchers,
                    'table': f"{self.dataset_id}.{self.table_name}",
                }
            )

            # Warn about unknown teams
            if self.unknown_teams:
                notify_warning(
                    title="Unknown MLB Teams Detected",
                    message=f"Found {len(self.unknown_teams)} unknown team names",
                    details={'unknown_teams': list(self.unknown_teams)}
                )

        except Exception as e:
            logger.error(f"Failed to save data: {e}", exc_info=True)
            notify_error(
                title="MLB Pitcher Props Save Failed",
                message=f"Error saving to BigQuery: {str(e)[:200]}",
                details={
                    'table': self.table_name,
                    'rows_attempted': len(rows),
                    'error_type': type(e).__name__,
                    'error': str(e),
                },
                processor_name="MlbPitcherPropsProcessor"
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

    parser = argparse.ArgumentParser(description='Process MLB pitcher props from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')

    args = parser.parse_args()

    processor = MlbPitcherPropsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
