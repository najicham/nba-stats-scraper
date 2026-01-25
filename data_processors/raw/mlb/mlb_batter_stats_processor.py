#!/usr/bin/env python3
"""
MLB Ball Don't Lie Batter Stats Processor

Processes output from mlb_batter_stats scraper to BigQuery.
Key field: strikeouts (k) - critical for bottom-up strikeout model.

GCS Path: mlb-ball-dont-lie/batter-stats/{date}/{timestamp}.json
Target Table: mlb_raw.bdl_batter_stats

Data Format (input):
{
    "date": "2025-06-15",
    "timestamp": "2025-06-16T01:23:45Z",
    "rowCount": 180,
    "batterStats": [
        {
            "id": 12345,
            "k": 2,              # Strikeouts (CRITICAL FOR BOTTOM-UP MODEL!)
            "ab": 4,            # At bats
            "h": 1,             # Hits
            "bb": 0,            # Walks
            "hr": 0,            # Home runs
            ...
            "player": {"id": 1, "first_name": "Aaron", "last_name": "Judge", ...},
            "team": {"id": 10, "abbreviation": "NYY", "full_name": "New York Yankees"},
            "game": {"id": 123, "date": "2025-06-15", "status": "Final", ...}
        }
    ]
}

Bottom-Up Model:
    Pitcher K's ~ Sum of individual batter K probabilities
    If batter K lines don't sum to pitcher K line -> market inefficiency

Created: 2026-01-06
"""

import json
import os
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime, date, timezone
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)
from shared.config.sport_config import get_raw_dataset, get_bucket

logger = logging.getLogger(__name__)


# MLB team abbreviations
MLB_TEAM_ABBREVS = {
    'ARI', 'ATL', 'BAL', 'BOS', 'CHC', 'CHW', 'CIN', 'CLE', 'COL', 'DET',
    'HOU', 'KC', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY', 'OAK',
    'PHI', 'PIT', 'SD', 'SF', 'SEA', 'STL', 'TB', 'TEX', 'TOR', 'WSH'
}


class MlbBatterStatsProcessor(ProcessorBase):
    """
    MLB Ball Don't Lie Batter Stats Processor

    Processes batter game stats from GCS to BigQuery.
    Critical source for bottom-up strikeout prediction model.

    Processing Strategy: MERGE_UPDATE
    - Deletes existing records for the game before inserting
    - Prevents duplicate batter records
    """

    def __init__(self):
        # Set dataset before calling super().__init__
        self.dataset_id = get_raw_dataset()  # Will be 'mlb_raw' when SPORT=mlb
        super().__init__()
        self.table_name = 'bdl_batter_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load batter stats data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_player_name(self, first_name: str, last_name: str) -> str:
        """Create normalized player lookup string."""
        full_name = f"{first_name} {last_name}".strip()
        # Remove spaces, punctuation, and convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', full_name.lower())
        return normalized

    def extract_team_abbr(self, team_data: Dict) -> str:
        """Extract team abbreviation from team object."""
        if not team_data:
            return ""

        # Try abbreviation field first
        abbr = team_data.get('abbreviation', '')
        if abbr and abbr.upper() in MLB_TEAM_ABBREVS:
            return abbr.upper()

        # Fallback to first 3 chars of city
        city = team_data.get('city', '')
        if city:
            return city.upper()[:3]

        return ""

    def extract_season_year(self, game_date: str) -> int:
        """Extract season year from date."""
        # Handle dates with time component (e.g., '2024-10-30T00:08:00.000Z')
        if 'T' in game_date:
            game_date = game_date.split('T')[0]
        game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
        # MLB season is April-October, simple year extraction
        return game_dt.year

    def normalize_game_date(self, game_date: str) -> str:
        """Normalize date to YYYY-MM-DD format."""
        if not game_date:
            return ''
        # Handle dates with time component
        if 'T' in game_date:
            game_date = game_date.split('T')[0]
        return game_date

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if 'batterStats' not in data:
            errors.append("Missing 'batterStats' field")
            return errors

        if not isinstance(data['batterStats'], list):
            errors.append("'batterStats' is not a list")
            return errors

        if not data['batterStats']:
            # Empty stats is valid (no games on that date)
            logger.info("Empty batterStats array - no batter data for this date")

        return errors

    def transform_data(self) -> None:
        """Transform raw data into transformed data for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []
        skipped_count = 0

        batter_stats = raw_data.get('batterStats', [])
        logger.info(f"Processing {len(batter_stats)} batter stat rows from {file_path}")

        # Process all stats
        for stat in batter_stats:
            try:
                game = stat.get('game', {})
                player = stat.get('player', {})

                # Team info can be in 'team' dict or 'team_name' string
                team = stat.get('team', {})
                team_name = stat.get('team_name', '')

                if not game or not player:
                    logger.debug(f"Skipping stat - missing game or player")
                    skipped_count += 1
                    continue

                # Extract team abbreviations from game object
                home_team = game.get('home_team', {})
                away_team = game.get('away_team', {})
                home_abbr = home_team.get('abbreviation', 'UNK') if home_team else 'UNK'
                away_abbr = away_team.get('abbreviation', 'UNK') if away_team else 'UNK'

                # Get game scores from scoring summary if available
                scoring = game.get('scoring_summary', [])
                if scoring and isinstance(scoring, list) and len(scoring) > 0:
                    last_play = scoring[-1]
                    home_score = last_play.get('home_score')
                    away_score = last_play.get('away_score')
                else:
                    home_score = None
                    away_score = None

                game_date = self.normalize_game_date(game.get('date', ''))
                bdl_game_id = game.get('id')

                # Build game_id: just use BDL ID for now
                game_id = str(bdl_game_id)

                # Player info
                first_name = player.get('first_name', '')
                last_name = player.get('last_name', '')
                if not first_name or not last_name:
                    logger.debug(f"Skipping stat - missing player name")
                    skipped_count += 1
                    continue

                player_full_name = f"{first_name} {last_name}"
                player_lookup = self.normalize_player_name(first_name, last_name)

                # Determine batter's team abbreviation
                if team and isinstance(team, dict):
                    team_abbr = self.extract_team_abbr(team)
                elif team_name:
                    # Match team_name to one of home/away team names
                    if team_name == home_team.get('name') or team_name == home_team.get('display_name'):
                        team_abbr = home_abbr
                    elif team_name == away_team.get('name') or team_name == away_team.get('display_name'):
                        team_abbr = away_abbr
                    else:
                        # Try partial match
                        if home_team.get('name', '') in team_name or team_name in home_team.get('display_name', ''):
                            team_abbr = home_abbr
                        elif away_team.get('name', '') in team_name or team_name in away_team.get('display_name', ''):
                            team_abbr = away_abbr
                        else:
                            team_abbr = 'UNK'
                else:
                    team_abbr = 'UNK'

                # Helper functions
                def safe_int(val):
                    return int(val) if val is not None else 0

                def safe_float(val):
                    if val is None:
                        return None
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return None

                # Extract batting stats with various field name possibilities
                strikeouts = safe_int(
                    stat.get('k') or stat.get('strikeouts') or stat.get('so') or stat.get('_strikeouts')
                )
                at_bats = safe_int(
                    stat.get('ab') or stat.get('at_bats') or stat.get('_at_bats')
                )
                hits = safe_int(
                    stat.get('h') or stat.get('hits') or stat.get('_hits')
                )
                walks = safe_int(
                    stat.get('bb') or stat.get('walks')
                )

                # Build row matching BigQuery schema
                row = {
                    # Core identifiers
                    'game_id': game_id,
                    'game_date': game_date,
                    'season_year': self.extract_season_year(game_date) if game_date else None,
                    'is_postseason': game.get('postseason', False),

                    # Game context
                    'home_team_abbr': home_abbr or '',
                    'away_team_abbr': away_abbr or '',
                    'home_team_score': home_score,
                    'away_team_score': away_score,
                    'venue': game.get('venue', ''),
                    'game_status': game.get('status', ''),

                    # Batter identification
                    'bdl_player_id': player.get('id'),
                    'player_full_name': player_full_name,
                    'player_lookup': player_lookup,
                    'team_abbr': team_abbr,
                    'position': player.get('position', ''),
                    'jersey_number': player.get('jersey_number'),
                    'batting_order': safe_int(stat.get('batting_order')),

                    # Batting stats - CORE (for bottom-up model)
                    'strikeouts': strikeouts,
                    'at_bats': at_bats,
                    'hits': hits,
                    'walks': walks,

                    # Batting stats - Extended
                    'runs': safe_int(stat.get('r') or stat.get('runs')),
                    'rbi': safe_int(stat.get('rbi')),
                    'home_runs': safe_int(stat.get('hr') or stat.get('home_runs')),
                    'doubles': safe_int(stat.get('2b') or stat.get('doubles')),
                    'triples': safe_int(stat.get('3b') or stat.get('triples')),
                    'stolen_bases': safe_int(stat.get('sb') or stat.get('stolen_bases')),
                    'caught_stealing': safe_int(stat.get('cs') or stat.get('caught_stealing')),
                    'hit_by_pitch': safe_int(stat.get('hbp') or stat.get('hit_by_pitch')),
                    'sacrifice_hits': safe_int(stat.get('sac') or stat.get('sacrifice_hits')),
                    'sacrifice_flies': safe_int(stat.get('sf') or stat.get('sacrifice_flies')),

                    # Calculated stats
                    'batting_average': safe_float(stat.get('avg') or stat.get('batting_average')),
                    'on_base_pct': safe_float(stat.get('obp') or stat.get('on_base_pct')),
                    'slugging_pct': safe_float(stat.get('slg') or stat.get('slugging_pct')),
                    'ops': safe_float(stat.get('ops')),

                    # Processing metadata
                    'source_file_path': file_path,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                rows.append(row)

            except Exception as e:
                logger.error(f"Error processing batter stat row: {e}")
                skipped_count += 1
                continue

        # Log summary stats for bottom-up model validation
        total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
        total_abs = sum(r.get('at_bats', 0) or 0 for r in rows)
        k_rate = total_ks / total_abs if total_abs > 0 else 0

        logger.info(f"Transformed {len(rows)} rows, skipped {skipped_count}")
        logger.info(f"Total strikeouts: {total_ks}, Total ABs: {total_abs}, K rate: {k_rate:.3f}")
        self.transformed_data = rows

    def save_data(self) -> None:
        """Save transformed data to BigQuery."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            # Get unique game IDs for logging
            game_ids = set(row['game_id'] for row in rows)
            logger.info(f"Loading {len(rows)} rows for {len(game_ids)} games using batch load")

            # Delete existing data for these games (MERGE_UPDATE strategy)
            for game_id in game_ids:
                game_date = next((row['game_date'] for row in rows if row['game_id'] == game_id), None)
                if game_date is None:
                    logger.warning(f"game_id {game_id} not found in rows, skipping delete")
                    continue
                try:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE game_id = '{game_id}'
                      AND game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result(timeout=60)
                except Exception as e:
                    if 'streaming buffer' in str(e).lower():
                        logger.warning(f"Streaming buffer prevents delete for {game_id}")
                    elif 'not found' in str(e).lower():
                        # Table doesn't exist yet - will be created on insert
                        logger.info(f"Table doesn't exist yet, will create on first insert")
                    else:
                        raise

            # Get table schema for load job
            try:
                table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.warning(f"Table {table_id} not found - run schema SQL first")
                    raise

            # Configure batch load job
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            # Load using batch job
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )

            # Wait for completion
            load_job.result(timeout=60)
            logger.info(f"Successfully loaded {len(rows)} rows for {len(game_ids)} games")

            # Update stats
            self.stats['rows_inserted'] = len(rows)

            # Calculate summary for notification
            total_ks = sum(r.get('strikeouts', 0) or 0 for r in rows)
            total_abs = sum(r.get('at_bats', 0) or 0 for r in rows)
            k_rate = total_ks / total_abs if total_abs > 0 else 0

            # Send success notification
            try:
                notify_info(
                    title="MLB Batter Stats Processing Complete",
                    message=f"Processed {len(rows)} batter stats from {len(game_ids)} games",
                    details={
                        'batter_records': len(rows),
                        'games_processed': len(game_ids),
                        'total_strikeouts': total_ks,
                        'total_at_bats': total_abs,
                        'k_rate': round(k_rate, 3),
                        'table': f"{self.dataset_id}.{self.table_name}",
                        'processor': 'MlbBatterStatsProcessor'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")
            self.stats["rows_inserted"] = 0

            try:
                notify_error(
                    title="MLB Batter Stats Processing Failed",
                    message=f"Error during processing: {str(e)[:200]}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'MlbBatterStatsProcessor'
                    },
                    processor_name="MlbBatterStatsProcessor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            raise

        return {'rows_processed': len(rows), 'errors': errors}

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

    parser = argparse.ArgumentParser(description='Process MLB batter stats from GCS')
    parser.add_argument('--bucket', default='mlb-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)')

    args = parser.parse_args()

    processor = MlbBatterStatsProcessor()
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
        'date': args.date
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
