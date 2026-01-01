#!/usr/bin/env python3
# File: data_processors/raw/nbacom/nbac_player_boxscore_processor.py
# Description: Processor for NBA.com player boxscore data (leaguegamelog format)
# Handles data from stats.nba.com/stats/leaguegamelog endpoint

import json
import logging
import re
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.nba_team_mapper import NBATeamMapper
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)
from shared.utils.schedule import NBAScheduleService

class NbacPlayerBoxscoreProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Processes NBA.com leaguegamelog API data into player boxscore format.

    Input format (from stats.nba.com/stats/leaguegamelog):
      {
        "resultSets": [{
          "headers": ["SEASON_ID", "PLAYER_ID", "PLAYER_NAME", ...],
          "rowSet": [
            ["22024", 1629627, "Zion Williamson", ...],
            ...
          ]
        }]
      }

    Output: Player boxscore rows for BigQuery table nba_raw.nbac_player_boxscores

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: game_id, player_lookup, points, rebounds, assists, minutes, field_goals_made, field_goals_attempted
        Expected Skip Rate: 30% when boxscores unchanged
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'game_id',
        'player_lookup',
        'points',
        'total_rebounds',
        'assists',
        'minutes',
        'field_goals_made',
        'field_goals_attempted'
    ]

    # Valid NBA team codes - used to detect non-NBA games (All-Star, exhibition)
    VALID_NBA_TEAMS = {
        'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }

    def __init__(self):
        super().__init__()
        self.table_name = 'nbac_player_boxscores'
        self.dataset_id = 'nba_raw'
        self.processing_strategy = 'MERGE_UPDATE'
        self.team_mapper = NBATeamMapper()
        self.schedule_service = NBAScheduleService()

        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Column index mapping (based on leaguegamelog headers)
        self.COLUMN_MAP = {
            'SEASON_ID': 0,
            'PLAYER_ID': 1,
            'PLAYER_NAME': 2,
            'TEAM_ID': 3,
            'TEAM_ABBREVIATION': 4,
            'TEAM_NAME': 5,
            'GAME_ID': 6,
            'GAME_DATE': 7,
            'MATCHUP': 8,
            'WL': 9,
            'MIN': 10,
            'FGM': 11,
            'FGA': 12,
            'FG_PCT': 13,
            'FG3M': 14,
            'FG3A': 15,
            'FG3_PCT': 16,
            'FTM': 17,
            'FTA': 18,
            'FT_PCT': 19,
            'OREB': 20,
            'DREB': 21,
            'REB': 22,
            'AST': 23,
            'STL': 24,
            'BLK': 25,
            'TOV': 26,
            'PF': 27,
            'PTS': 28,
            'PLUS_MINUS': 29,
            'FANTASY_PTS': 30,
            'VIDEO_AVAILABLE': 31
        }
        
        # Tracking
        self.players_processed = 0
        self.players_failed = 0
        self.games_found = set()
    
    def normalize_player_name(self, name: str) -> str:
        """Normalize player names for cross-source matching."""
        if not name:
            return ""
        normalized = name.lower().strip()
        normalized = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        return normalized
    
    def safe_int(self, value) -> Optional[int]:
        """Safely convert value to int."""
        if value is None or value == "":
            return None
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return None
    
    def safe_float(self, value) -> Optional[float]:
        """Safely convert value to float."""
        if value is None or value == "":
            return None
        try:
            return float(str(value))
        except (ValueError, TypeError):
            return None
    
    def determine_season_year(self, game_date: str) -> int:
        """Determine NBA season year from game date."""
        date_obj = datetime.strptime(game_date, '%Y-%m-%d')
        if date_obj.month >= 10:
            return date_obj.year
        else:
            return date_obj.year - 1
    
    def parse_matchup(self, matchup: str) -> Dict[str, str]:
        """
        Parse MATCHUP field to get home/away teams.
        Format: "NOP @ GSW" or "LAL vs. BOS"
        """
        if '@' in matchup:
            parts = matchup.split('@')
            away = parts[0].strip()
            home = parts[1].strip()
            return {'away': away, 'home': home}
        elif 'vs' in matchup.lower():
            parts = re.split(r'\s+vs\.?\s+', matchup, flags=re.IGNORECASE)
            home = parts[0].strip()
            away = parts[1].strip()
            return {'away': away, 'home': home}
        else:
            logging.warning(f"Could not parse matchup: {matchup}")
            return {'away': '', 'home': ''}
    
    def construct_game_id(self, game_date: str, home_team: str, away_team: str) -> str:
        """Construct consistent game_id format: YYYYMMDD_AWAY_HOME"""
        date_str = game_date.replace('-', '')
        return f"{date_str}_{away_team}_{home_team}"

    def _extract_game_date(self, rows_data: List) -> Optional[str]:
        """Extract game date from data rows or file path."""
        # Try to get from file path first (format: .../player-boxscores/2024-01-15/...)
        file_path = self.opts.get('file_path', '')
        if file_path:
            import re
            match = re.search(r'/(\d{4}-\d{2}-\d{2})/', file_path)
            if match:
                return match.group(1)

        # Fallback to first row's game date
        if rows_data and len(rows_data) > 0:
            game_date_idx = self.COLUMN_MAP.get('GAME_DATE', 7)
            if len(rows_data[0]) > game_date_idx:
                return rows_data[0][game_date_idx]

        return None

    def _validate_team_code(self, team_code: str, game_date: str, context: str) -> bool:
        """
        Validate team code is a real NBA team.

        For non-All-Star games, invalid team codes indicate a data quality issue.
        """
        if not team_code:
            return False

        if team_code in self.VALID_NBA_TEAMS:
            return True

        # Check game type - only alert for non-All-Star games
        season_type = self.schedule_service.get_season_type_for_date(game_date)
        if season_type == "All Star":
            # All-Star teams (DRT, LBN, etc.) are expected
            logging.debug(f"All-Star team code {team_code} in {context} - expected")
            return False  # Still invalid for processing, but don't alert

        # Non-All-Star game with invalid team - this is a real problem!
        logging.error(f"Invalid team code '{team_code}' in {context} for {game_date} "
                      f"(season_type={season_type}) - possible data quality issue")
        notify_warning(
            title="Invalid Team Code in Player Boxscore",
            message=f"Found non-NBA team code '{team_code}' in a {season_type} game",
            details={
                'team_code': team_code,
                'game_date': game_date,
                'season_type': season_type,
                'context': context
            }
        )
        return False

    def load_data(self) -> None:
        """Load JSON from GCS."""
        self.raw_data = self.load_json_from_gcs()
        logging.info(f"Loaded leaguegamelog data from GCS")
    
    def validate_loaded_data(self) -> None:
        """Validate the leaguegamelog structure."""
        if not self.raw_data:
            raise ValueError("No data loaded")
        
        if 'resultSets' not in self.raw_data:
            raise ValueError("Missing 'resultSets' in data")
        
        result_sets = self.raw_data['resultSets']
        if not result_sets or len(result_sets) == 0:
            raise ValueError("Empty resultSets")
        
        if 'rowSet' not in result_sets[0]:
            raise ValueError("Missing 'rowSet' in resultSets[0]")
        
        if 'headers' not in result_sets[0]:
            raise ValueError("Missing 'headers' in resultSets[0]")
        
        row_count = len(result_sets[0]['rowSet'])
        logging.info(f"Validated {row_count} player rows in leaguegamelog data")
    
    def transform_data(self) -> None:
        """Transform leaguegamelog format to BigQuery player boxscore format."""
        try:
            result_set = self.raw_data['resultSets'][0]
            headers = result_set['headers']
            rows_data = result_set['rowSet']

            # Extract game date from file path or first row to check game type
            game_date = self._extract_game_date(rows_data)
            if game_date:
                season_type = self.schedule_service.get_season_type_for_date(game_date)

                # Skip All-Star games - they use non-NBA teams and aren't useful for predictions
                if season_type == "All Star":
                    logging.info(f"Skipping All-Star game data for {game_date} - "
                                 "exhibition games not processed")
                    self.transformed_data = []
                    return

            # Validate column structure matches expectations
            if len(headers) != 32:
                logging.warning(f"Expected 32 columns, got {len(headers)}")
            
            rows = []
            current_time = datetime.now(timezone.utc).isoformat()
            self.players_processed = 0
            self.players_failed = 0
            
            for row_data in rows_data:
                try:
                    # Extract data using column map
                    col = self.COLUMN_MAP
                    
                    # Player identification
                    nba_player_id = self.safe_int(row_data[col['PLAYER_ID']])
                    player_full_name = row_data[col['PLAYER_NAME']]
                    player_lookup = self.normalize_player_name(player_full_name)
                    
                    if not nba_player_id or not player_full_name:
                        self.players_failed += 1
                        continue
                    
                    # Team info
                    team_abbr = self.team_mapper.get_nba_tricode(
                        row_data[col['TEAM_ABBREVIATION']]
                    )
                    team_id = self.safe_int(row_data[col['TEAM_ID']])
                    
                    # Game info
                    nba_game_id = row_data[col['GAME_ID']]
                    game_date_str = row_data[col['GAME_DATE']]  # "2024-10-29"
                    matchup = row_data[col['MATCHUP']]
                    
                    # Parse matchup to get home/away
                    teams = self.parse_matchup(matchup)
                    home_team_abbr = self.team_mapper.get_nba_tricode(teams['home'])
                    away_team_abbr = self.team_mapper.get_nba_tricode(teams['away'])
                    
                    # Construct our standard game_id
                    game_id = self.construct_game_id(game_date_str, home_team_abbr, away_team_abbr)
                    self.games_found.add(game_id)
                    
                    # Season info
                    season_year = self.determine_season_year(game_date_str)
                    
                    # Stats
                    minutes = str(row_data[col['MIN']]) if row_data[col['MIN']] else None
                    points = self.safe_int(row_data[col['PTS']])
                    field_goals_made = self.safe_int(row_data[col['FGM']])
                    field_goals_attempted = self.safe_int(row_data[col['FGA']])
                    field_goal_percentage = self.safe_float(row_data[col['FG_PCT']])
                    
                    three_pointers_made = self.safe_int(row_data[col['FG3M']])
                    three_pointers_attempted = self.safe_int(row_data[col['FG3A']])
                    three_point_percentage = self.safe_float(row_data[col['FG3_PCT']])
                    
                    free_throws_made = self.safe_int(row_data[col['FTM']])
                    free_throws_attempted = self.safe_int(row_data[col['FTA']])
                    free_throw_percentage = self.safe_float(row_data[col['FT_PCT']])
                    
                    offensive_rebounds = self.safe_int(row_data[col['OREB']])
                    defensive_rebounds = self.safe_int(row_data[col['DREB']])
                    total_rebounds = self.safe_int(row_data[col['REB']])
                    assists = self.safe_int(row_data[col['AST']])
                    steals = self.safe_int(row_data[col['STL']])
                    blocks = self.safe_int(row_data[col['BLK']])
                    turnovers = self.safe_int(row_data[col['TOV']])
                    personal_fouls = self.safe_int(row_data[col['PF']])
                    plus_minus = self.safe_int(row_data[col['PLUS_MINUS']])
                    
                    # Build row matching BigQuery schema
                    row = {
                        # Core identifiers
                        'game_id': game_id,
                        'game_date': game_date_str,
                        'season_year': season_year,
                        'season_type': 'Regular Season',
                        
                        # Game context
                        'nba_game_id': nba_game_id,
                        'game_code': None,  # Not available in leaguegamelog
                        'game_status': 'Final',  # Assume final
                        'period': 4,  # Assume regulation
                        'is_playoff_game': False,
                        
                        # Team information (we don't have scores in leaguegamelog)
                        'home_team_id': None,
                        'home_team_abbr': home_team_abbr,
                        'home_team_score': None,
                        'away_team_id': None,
                        'away_team_abbr': away_team_abbr,
                        'away_team_score': None,
                        
                        # Player identification
                        'nba_player_id': nba_player_id,
                        'player_full_name': player_full_name,
                        'player_lookup': player_lookup,
                        'team_id': team_id,
                        'team_abbr': team_abbr,
                        'jersey_number': None,  # Not in leaguegamelog
                        'position': None,  # Not in leaguegamelog
                        'starter': None,  # Not in leaguegamelog
                        
                        # Core statistics
                        'minutes': minutes,
                        'points': points,
                        'field_goals_made': field_goals_made,
                        'field_goals_attempted': field_goals_attempted,
                        'field_goal_percentage': field_goal_percentage,
                        'three_pointers_made': three_pointers_made,
                        'three_pointers_attempted': three_pointers_attempted,
                        'three_point_percentage': three_point_percentage,
                        'free_throws_made': free_throws_made,
                        'free_throws_attempted': free_throws_attempted,
                        'free_throw_percentage': free_throw_percentage,
                        
                        # Advanced statistics
                        'offensive_rebounds': offensive_rebounds,
                        'defensive_rebounds': defensive_rebounds,
                        'total_rebounds': total_rebounds,
                        'assists': assists,
                        'steals': steals,
                        'blocks': blocks,
                        'turnovers': turnovers,
                        'personal_fouls': personal_fouls,
                        'flagrant_fouls': None,  # Not in leaguegamelog
                        'technical_fouls': None,  # Not in leaguegamelog
                        'plus_minus': plus_minus,
                        
                        # Enhanced metrics (not available)
                        'true_shooting_pct': None,
                        'effective_fg_pct': None,
                        'usage_rate': None,
                        'offensive_rating': None,
                        'defensive_rating': None,
                        'pace': None,
                        'pie': None,
                        
                        # Quarter breakdown (not available)
                        'points_q1': None,
                        'points_q2': None,
                        'points_q3': None,
                        'points_q4': None,
                        'points_ot': None,
                        
                        # Processing metadata
                        'source_file_path': self.opts.get('file_path', ''),
                        'scrape_timestamp': current_time,
                        'created_at': current_time,
                        'processed_at': current_time
                    }
                    
                    rows.append(row)
                    self.players_processed += 1
                    
                except Exception as e:
                    self.players_failed += 1
                    logging.error(f"Error processing player row: {str(e)}", exc_info=True)
                    continue
            
            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()

            logging.info(f"Transformed {len(rows)} player records from {len(self.games_found)} games")
            
            # Warn if high failure rate
            total_players = len(rows_data)
            if total_players > 0:
                failure_rate = self.players_failed / total_players
                if failure_rate > 0.1:
                    logging.warning(f"High failure rate: {failure_rate:.1%} ({self.players_failed}/{total_players})")
            
        except Exception as e:
            logging.error(f"Error in transform_data: {str(e)}", exc_info=True)
            raise
    
    def load_data_to_bq(self, rows: List[Dict]) -> Dict:
        """Load transformed data into BigQuery with MERGE strategy.

        Uses batch loading (load_table_from_json) instead of streaming inserts
        (insert_rows_json) to avoid:
        1. The 20 DML concurrent operation limit per table
        2. The 90-minute streaming buffer that blocks DELETE/UPDATE operations
        """
        if not rows:
            logging.warning("No rows to load")
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        errors = []

        try:
            # Get all unique game_ids and game_dates in this batch
            game_ids = list(self.games_found)
            game_dates = list(set(row['game_date'] for row in rows))

            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for these games
                # MUST include game_date filter for partitioned table
                game_ids_str = "', '".join(game_ids)
                game_dates_str = "', '".join(game_dates)
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE game_date IN ('{game_dates_str}')
                  AND game_id IN ('{game_ids_str}')
                """
                logging.info(f"Deleting existing records for {len(game_ids)} games on {len(game_dates)} dates")

                try:
                    self.bq_client.query(delete_query).result(timeout=60)
                except Exception as e:
                    logging.error(f"Error deleting existing data: {e}")
                    raise e

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            # Insert new data using batch loading
            logging.info(f"Loading {len(rows)} rows into {table_id} using batch load")
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logging.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            logging.info(f"Successfully loaded {len(rows)} rows for {len(game_ids)} games")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data to BigQuery: {error_msg}")

        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors,
            'games_processed': len(game_ids)
        }
    
    def save_data(self) -> None:
        """Override save to use custom load method."""
        result = self.load_data_to_bq(self.transformed_data)
        self.stats['rows_inserted'] = result.get('rows_processed', 0)
        self.stats['games_processed'] = result.get('games_processed', 0)
        
        if result.get('errors'):
            raise Exception(f"BigQuery load errors: {result['errors']}")
    
    def get_processor_stats(self) -> Dict:
        """Return processor statistics."""
        return {
            'players_processed': self.players_processed,
            'players_failed': self.players_failed,
            'games_found': len(self.games_found),
            'rows_transformed': len(self.transformed_data) if self.transformed_data else 0
        }


# CLI entry point for manual execution
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Process NBA.com leaguegamelog data')
    parser.add_argument('--bucket', default='nba-scraped-data', help='GCS bucket name')
    parser.add_argument('--file', required=True, help='File path in bucket (e.g., nba-com/player-boxscores/2024-10-29/file.json)')
    parser.add_argument('--project', default='nba-props-platform', help='GCP project ID')
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 3 (for backfills)'
    )

    args = parser.parse_args()

    # Extract bucket and file_path from full gs:// URI if provided
    file_input = args.file
    if file_input.startswith('gs://'):
        # Parse gs://bucket/path format
        parts = file_input.replace('gs://', '').split('/', 1)
        bucket = parts[0]
        file_path = parts[1] if len(parts) > 1 else ''
    else:
        bucket = args.bucket
        file_path = file_input

    processor = NbacPlayerBoxscoreProcessor()
    opts = {
        'bucket': bucket,
        'file_path': file_path,
        'project_id': args.project,
        'skip_downstream_trigger': args.skip_downstream_trigger
    }

    success = processor.run(opts)
    sys.exit(0 if success else 1)