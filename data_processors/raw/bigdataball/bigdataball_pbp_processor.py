#!/usr/bin/env python3
# File: processors/bigdataball/bigdataball_pbp_processor.py
# Description: Processor for BigDataBall play-by-play data transformation
# UPDATED: Now handles both CSV and JSON formats
# UPDATED: 2026-01-28 - Added NBA.com PBP fallback when BDB data unavailable

import os
import json
import logging
import re
import io
import math
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from google.cloud import bigquery, storage
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Notification imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

class BigDataBallPbpProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process BigDataBall play-by-play data with smart idempotency.
    """

    # Smart idempotency: Hash meaningful play-by-play event fields only
    HASH_FIELDS = [
        'game_id',
        'event_sequence',
        'period',
        'game_clock',
        'event_type',
        'event_subtype',
        'score_home',
        'score_away',
        'player_1_name',
        'player_2_name',
        'player_3_name',
        'shot_made',
        'shot_type',
        'points_scored'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bigdataball_play_by_play'
        self.processing_strategy = 'MERGE_UPDATE'

        # CRITICAL: These two lines are REQUIRED for all processors
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

        # GCS client for fallback NBA.com PBP data
        self.storage_client = storage.Client()
        self.bucket_name = os.environ.get('GCS_BUCKET', 'nba-scraped-data')

        # Track data source for quality tracking
        self.data_source = 'bigdataball'  # 'bigdataball' or 'nbacom_fallback'

        # NBA team ID to abbreviation mapping for NBA.com fallback
        self.team_id_mapping = {
            1610612737: 'ATL', 1610612738: 'BOS', 1610612751: 'BRK', 1610612766: 'CHA',
            1610612741: 'CHI', 1610612739: 'CLE', 1610612742: 'DAL', 1610612743: 'DEN',
            1610612765: 'DET', 1610612744: 'GSW', 1610612745: 'HOU', 1610612754: 'IND',
            1610612746: 'LAC', 1610612747: 'LAL', 1610612763: 'MEM', 1610612748: 'MIA',
            1610612749: 'MIL', 1610612750: 'MIN', 1610612740: 'NOP', 1610612752: 'NYK',
            1610612760: 'OKC', 1610612753: 'ORL', 1610612755: 'PHI', 1610612756: 'PHX',
            1610612757: 'POR', 1610612758: 'SAC', 1610612759: 'SAS', 1610612761: 'TOR',
            1610612762: 'UTA', 1610612764: 'WAS'
        }

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def parse_json(self, json_content: str, file_path: str) -> Dict:
        """
        Parse BigDataBall data - handles BOTH JSON and CSV formats.
        
        Args:
            json_content: File content (either JSON or CSV format)
            file_path: GCS file path for context
            
        Returns:
            Standardized dict with 'game_info' and 'playByPlay' keys
        """
        try:
            # Try JSON first (backward compatibility with existing files)
            data = json.loads(json_content)
            logging.info(f"Parsed as JSON format: {file_path}")
            return data
            
        except json.JSONDecodeError:
            # Not JSON - try CSV format
            logging.info(f"JSON parse failed, trying CSV format: {file_path}")
            
            try:
                # Read CSV content
                df = pd.read_csv(io.StringIO(json_content))
                
                if df.empty:
                    raise ValueError("CSV file is empty")
                
                # Extract game info from first row
                first_row = df.iloc[0]
                
                # Extract team names from filename
                # Pattern: [2024-10-22]-0022400001-NYK@BOS.csv
                filename = os.path.basename(file_path)
                teams = self._extract_teams_from_filename(filename)
                
                # Build standardized structure matching JSON format
                game_info = {
                    'game_id': str(first_row.get('game_id', '')),
                    'date': str(first_row.get('date', '')),
                    'data_set': str(first_row.get('data_set', '')),
                    'away_team': teams['away_team'],
                    'home_team': teams['home_team']
                }
                
                # Convert DataFrame to dict records, handling NaN values
                play_records = df.to_dict('records')
                
                # Clean up NaN values
                import math
                for record in play_records:
                    for key, value in record.items():
                        if pd.isna(value) or (isinstance(value, float) and math.isnan(value)):
                            record[key] = None
                
                # Return in same format as JSON files
                data = {
                    'file_info': {
                        'name': filename,
                        'processed_at': datetime.utcnow().isoformat(),
                        'total_plays': len(df),
                        'columns': df.columns.tolist()
                    },
                    'game_info': game_info,
                    'playByPlay': play_records
                }
                
                logging.info(f"Successfully parsed CSV: {len(play_records)} plays")
                return data
                
            except Exception as csv_error:
                logging.error(f"Failed to parse as CSV: {csv_error}")
                
                # Notify parse failure
                try:
                    notify_error(
                        title="BigDataBall Play-by-Play Parse Failed",
                        message=f"Failed to parse file as both JSON and CSV: {str(csv_error)}",
                        details={
                            'file_path': file_path,
                            'json_error': 'JSONDecodeError',
                            'csv_error': str(csv_error),
                            'content_preview': json_content[:200]
                        },
                        processor_name="BigDataBall Play-by-Play Processor"
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(f"Could not parse file as JSON or CSV: {csv_error}")
    
    def _extract_teams_from_filename(self, filename: str) -> Dict[str, str]:
        """
        Extract team abbreviations from filename.
        Pattern: [2024-10-22]-0022400001-NYK@BOS.csv
        """
        import re
        
        # Try to match the standard pattern
        pattern = r'\[[\d-]+\]-\d+-(.+)@(.+)\.csv'
        match = re.search(pattern, filename)
        
        if match:
            return {
                'away_team': match.group(1),
                'home_team': match.group(2)
            }
        
        # Fallback if pattern doesn't match
        logging.warning(f"Could not extract teams from filename: {filename}")
        return {
            'away_team': 'UNK',
            'home_team': 'UNK'
        }
    
    def normalize_player_name(self, name: str) -> str:
        """Convert player name to lookup format: 'LeBron James' -> 'lebronjames'"""
        if not name:
            return ""
        
        # Remove common suffixes
        name = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV)$', '', name, flags=re.IGNORECASE)
        
        # Convert to lowercase and remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        return normalized
    
    def construct_game_id(self, game_date: str, away_team: str, home_team: str) -> str:
        """Construct consistent game_id format: '20241101_NYK_DET'"""
        date_part = game_date.replace('-', '')
        return f"{date_part}_{away_team}_{home_team}"
    
    def parse_game_date(self, date_str: str) -> tuple:
        """
        Parse game date and return (iso_date_string, season_year)
        Handles both formats: '11/12/2024' and '2024-11-12'
        """
        if '/' in date_str:
            # Format: MM/DD/YYYY
            month, day, year = date_str.split('/')
            iso_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            year_int = int(year)
        else:
            # Format: YYYY-MM-DD
            iso_date = date_str
            year_int = int(date_str.split('-')[0])
        
        # Extract month for season determination
        month_int = int(iso_date.split('-')[1])
        
        # Determine season year (October+ = new season starts)
        if month_int >= 10:
            season_year = year_int
        else:
            season_year = year_int - 1
        
        return iso_date, season_year
    
    def determine_player_role(self, event: Dict) -> Optional[str]:
        """Determine the role of player_2 based on event data"""
        if event.get('assist'):
            return 'assist'
        elif event.get('block'):
            return 'block'
        elif event.get('steal'):
            return 'steal'
        elif event.get('away') and event.get('event_type') == 'jump ball':
            return 'jump_ball_away'
        elif event.get('entered'):
            return 'substitution_in'
        elif event.get('possession'):
            return 'possession'
        return None
    
    def determine_player_3_role(self, event: Dict) -> Optional[str]:
        """Determine the role of player_3 based on event data"""
        if event.get('home') and event.get('event_type') == 'jump ball':
            return 'jump_ball_home'
        elif event.get('left'):
            return 'substitution_out'
        return None
    
    def get_player_2_name(self, event: Dict) -> Optional[str]:
        """Get player_2 name based on event context"""
        if event.get('assist'):
            return event.get('assist')
        elif event.get('block'):
            return event.get('block')
        elif event.get('steal'):
            return event.get('steal')
        elif event.get('away') and event.get('event_type') == 'jump ball':
            return event.get('away')
        elif event.get('entered'):
            return event.get('entered')
        elif event.get('possession'):
            return event.get('possession')
        return None
    
    def get_player_3_name(self, event: Dict) -> Optional[str]:
        """Get player_3 name based on event context"""
        if event.get('home') and event.get('event_type') == 'jump ball':
            return event.get('home')
        elif event.get('left'):
            return event.get('left')
        return None
    
    def convert_time_to_seconds(self, time_str: str) -> Optional[int]:
        """Convert time string '0:11:40' to seconds"""
        if not time_str:
            return None
        try:
            parts = time_str.split(':')
            if len(parts) == 3:  # H:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            return None
        except (ValueError, IndexError):
            return None
    
    def determine_shot_type(self, event_type: str) -> Optional[str]:
        """Map BigDataBall shot types to standard format"""
        if not event_type:
            return None
        
        event_type_lower = event_type.lower()
        
        if '3pt' in event_type_lower:
            return '3PT'
        elif 'free throw' in event_type_lower or 'ft' in event_type_lower:
            return 'FT'
        else:
            return '2PT'
    
    # =========================================================================
    # NBA.COM PBP FALLBACK METHODS
    # =========================================================================
    # When BigDataBall data is unavailable, we can fall back to NBA.com PBP.
    # NBA.com PBP lacks lineup data but provides basic play-by-play events.
    # =========================================================================

    def fetch_nbacom_pbp_fallback(self, game_id: str, game_date: str) -> Optional[Dict]:
        """
        Fetch NBA.com PBP data as fallback when BDB is unavailable.

        Args:
            game_id: NBA game ID (e.g., '0022400561')
            game_date: Game date in YYYY-MM-DD format

        Returns:
            NBA.com PBP data dict or None if not available
        """
        try:
            # NBA.com PBP files are stored at:
            # nba-com/play-by-play/{date}/game-{game_id}/{timestamp}.json
            bucket = self.storage_client.bucket(self.bucket_name)
            prefix = f"nba-com/play-by-play/{game_date}/game-{game_id}/"

            # List files in the directory
            blobs = list(bucket.list_blobs(prefix=prefix))

            if not blobs:
                logger.warning(f"No NBA.com PBP data found for game {game_id} on {game_date}")
                return None

            # Get the most recent file (sorted by name/timestamp)
            latest_blob = sorted(blobs, key=lambda b: b.name, reverse=True)[0]

            # Download and parse
            json_content = latest_blob.download_as_text()
            data = json.loads(json_content)

            logger.info(f"Loaded NBA.com PBP fallback data from {latest_blob.name}")

            # Add metadata for tracking
            data['_fallback_source'] = 'nbacom'
            data['_fallback_file'] = latest_blob.name

            return data

        except Exception as e:
            logger.error(f"Failed to fetch NBA.com PBP fallback for game {game_id}: {e}")
            return None

    def transform_nbacom_to_bdb_schema(self, nbacom_data: Dict, game_date: str) -> List[Dict]:
        """
        Transform NBA.com PBP data to match BigDataBall schema.

        NBA.com data lacks:
        - Lineup data (a1-a5, h1-h5)
        - elapsed_time, play_length
        - converted_x, converted_y (shot coordinates)
        - possession player

        Args:
            nbacom_data: NBA.com PBP response data
            game_date: Game date in YYYY-MM-DD format

        Returns:
            List of rows matching BigDataBall schema
        """
        rows = []

        try:
            play_by_play = nbacom_data.get('playByPlay', {})
            game = play_by_play.get('game', {})
            actions = game.get('actions', [])

            if not actions:
                logger.warning("No actions found in NBA.com PBP data")
                return []

            # Extract game metadata
            nba_game_id = game.get('gameId', '')
            metadata = nbacom_data.get('metadata', {})

            # Derive season year from game date
            game_date_parts = game_date.split('-')
            year = int(game_date_parts[0])
            month = int(game_date_parts[1])
            season_year = year if month >= 10 else year - 1

            # Build player-team lookup from actions
            player_team_lookup = {}
            teams_in_game = set()
            for action in actions:
                if action.get('personId') and action.get('teamTricode'):
                    player_team_lookup[action['personId']] = action['teamTricode']
                if action.get('teamTricode'):
                    teams_in_game.add(action['teamTricode'])

            teams_list = list(teams_in_game)
            away_team_abbr = teams_list[0] if len(teams_list) > 0 else 'UNK'
            home_team_abbr = teams_list[1] if len(teams_list) > 1 else 'UNK'

            # Construct game_id in BDB format
            game_id = f"{game_date.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"

            file_path = nbacom_data.get('_fallback_file', 'nbacom_fallback')

            for action in actions:
                # Parse game clock from NBA.com format (PT11M46.00S)
                clock_str = action.get('clock', '')
                game_clock = ''
                game_clock_seconds = 0

                if clock_str.startswith('PT'):
                    try:
                        time_part = clock_str[2:]
                        if 'M' in time_part and 'S' in time_part:
                            minutes = int(float(time_part.split('M')[0]))
                            seconds = float(time_part.split('M')[1].replace('S', ''))
                            game_clock = f"0:{minutes:02d}:{int(seconds):02d}"
                            game_clock_seconds = minutes * 60 + int(seconds)
                    except (ValueError, IndexError):
                        pass

                # Extract shot data
                x = action.get('x')
                y = action.get('y')
                shot_made = None
                shot_type = None
                points_scored = None

                action_type = action.get('actionType', '').lower()

                if action.get('shotResult') == 'Made' or 'made' in str(action.get('subType', '')).lower():
                    shot_made = True
                elif action.get('shotResult') == 'Missed' or 'missed' in str(action.get('subType', '')).lower():
                    shot_made = False

                if '3pt' in action_type or '3pt' in str(action.get('subType', '')).lower():
                    shot_type = '3PT'
                    if shot_made:
                        points_scored = 3
                elif 'freethrow' in action_type:
                    shot_type = 'FT'
                    if shot_made:
                        points_scored = 1
                elif action_type in ['2pt', 'shot', 'dunk', 'layup'] or 'made' in str(action.get('subType', '')).lower():
                    shot_type = '2PT'
                    if shot_made:
                        points_scored = 2

                # Extract player info
                player_1_name = action.get('playerName', '')
                player_1_lookup = self.normalize_player_name(player_1_name) if player_1_name else None
                player_1_team = action.get('teamTricode', '')

                # Secondary player (assist, block, etc.)
                player_2_name = None
                player_2_lookup = None
                player_2_role = None

                if action.get('assistPlayerName'):
                    player_2_name = action.get('assistPlayerName')
                    player_2_role = 'assist'
                elif action.get('blockPlayerName'):
                    player_2_name = action.get('blockPlayerName')
                    player_2_role = 'block'
                elif action.get('stealPlayerName'):
                    player_2_name = action.get('stealPlayerName')
                    player_2_role = 'steal'

                if player_2_name:
                    player_2_lookup = self.normalize_player_name(player_2_name)

                row = {
                    # Core Game Identifiers
                    'game_id': game_id,
                    'bdb_game_id': None,  # No BDB game ID for fallback
                    'game_date': game_date,
                    'season_year': season_year,
                    'data_set': f"NBA {season_year}-{(season_year + 1) % 100:02d} Regular Season (NBA.com Fallback)",
                    'home_team_abbr': home_team_abbr,
                    'away_team_abbr': away_team_abbr,

                    # Event Identifiers
                    'event_id': f"{game_id}_{action.get('actionNumber', 0)}",
                    'event_sequence': action.get('actionNumber', 0),
                    'period': action.get('period', 1),

                    # Game Clock (NBA.com has limited timing data)
                    'game_clock': game_clock,
                    'game_clock_seconds': game_clock_seconds,
                    'elapsed_time': None,  # Not available in NBA.com
                    'elapsed_seconds': None,
                    'play_length': None,  # Not available in NBA.com
                    'play_length_seconds': None,

                    # Event Details
                    'event_type': action.get('actionType', ''),
                    'event_subtype': action.get('subType', ''),
                    'event_description': action.get('description', ''),

                    # Score Tracking
                    'score_home': int(action.get('scoreHome', 0)) if action.get('scoreHome') else 0,
                    'score_away': int(action.get('scoreAway', 0)) if action.get('scoreAway') else 0,

                    # Primary Player
                    'player_1_name': player_1_name,
                    'player_1_lookup': player_1_lookup,
                    'player_1_team_abbr': player_1_team,

                    # Secondary Player
                    'player_2_name': player_2_name,
                    'player_2_lookup': player_2_lookup,
                    'player_2_team_abbr': None,
                    'player_2_role': player_2_role,

                    # Tertiary Player (rarely used in NBA.com)
                    'player_3_name': None,
                    'player_3_lookup': None,
                    'player_3_team_abbr': None,
                    'player_3_role': None,

                    # Shot Details
                    'shot_made': shot_made,
                    'shot_type': shot_type,
                    'shot_distance': None,  # Could calculate from x,y if needed
                    'points_scored': points_scored,

                    # Shot Coordinates (NBA.com has some, but not dual coordinates)
                    'original_x': x,
                    'original_y': y,
                    'converted_x': None,  # Not available in NBA.com
                    'converted_y': None,

                    # Lineup Data - NOT AVAILABLE in NBA.com (critical difference!)
                    'away_player_1_lookup': None,
                    'away_player_2_lookup': None,
                    'away_player_3_lookup': None,
                    'away_player_4_lookup': None,
                    'away_player_5_lookup': None,
                    'home_player_1_lookup': None,
                    'home_player_2_lookup': None,
                    'home_player_3_lookup': None,
                    'home_player_4_lookup': None,
                    'home_player_5_lookup': None,

                    # Additional Fields
                    'possession_player_name': None,
                    'possession_player_lookup': None,
                    'reason': action.get('foulType', None),
                    'opponent': None,
                    'num': None,
                    'outof': None,

                    # Processing Metadata
                    'source_file_path': file_path,
                    'csv_filename': None,
                    'csv_row_number': None,
                    'data_source': 'nbacom_fallback',  # Mark as fallback data
                    'processed_at': datetime.utcnow().isoformat(),
                    'created_at': datetime.utcnow().isoformat()
                }

                rows.append(row)

            logger.info(f"Transformed {len(rows)} NBA.com PBP events to BDB schema (fallback)")

            # Notify about fallback usage
            try:
                notify_warning(
                    title="Using NBA.com PBP Fallback",
                    message=f"BigDataBall PBP unavailable for game {game_id}, using NBA.com fallback",
                    details={
                        'game_id': game_id,
                        'game_date': game_date,
                        'nba_game_id': nba_game_id,
                        'events_count': len(rows),
                        'limitations': 'No lineup data, limited timing data'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            return rows

        except Exception as e:
            logger.error(f"Failed to transform NBA.com PBP to BDB schema: {e}")

            try:
                notify_error(
                    title="NBA.com PBP Fallback Transform Failed",
                    message=f"Failed to transform NBA.com PBP data: {str(e)}",
                    details={
                        'error_type': type(e).__name__,
                        'game_date': game_date
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            return []

    def try_nbacom_fallback(self, game_id: str, game_date: str) -> Optional[List[Dict]]:
        """
        Attempt to use NBA.com PBP as fallback when BDB data is unavailable.

        Args:
            game_id: NBA game ID
            game_date: Game date in YYYY-MM-DD format

        Returns:
            List of transformed rows or None if fallback also fails
        """
        logger.info(f"Attempting NBA.com PBP fallback for game {game_id} on {game_date}")

        nbacom_data = self.fetch_nbacom_pbp_fallback(game_id, game_date)
        if not nbacom_data:
            return None

        rows = self.transform_nbacom_to_bdb_schema(nbacom_data, game_date)
        if rows:
            self.data_source = 'nbacom_fallback'
        return rows

    # =========================================================================
    # END NBA.COM PBP FALLBACK METHODS
    # =========================================================================

    def validate_data(self, data: Dict) -> List[str]:
        """Validate required fields in BigDataBall data"""
        errors = []

        if 'game_info' not in data:
            errors.append("Missing game_info")
            return errors
            
        game_info = data['game_info']
        required_fields = ['game_id', 'date', 'away_team', 'home_team']
        for field in required_fields:
            if field not in game_info:
                errors.append(f"Missing game_info.{field}")
        
        if 'playByPlay' not in data:
            errors.append("Missing playByPlay")
        elif not isinstance(data['playByPlay'], list):
            errors.append("playByPlay is not a list")
        elif len(data['playByPlay']) == 0:
            errors.append("playByPlay is empty")
        
        # Notify if validation errors found
        if errors:
            try:
                notify_error(
                    title="BigDataBall Play-by-Play Validation Failed",
                    message=f"Data validation errors: {', '.join(errors)}",
                    details={
                        'game_id': game_info.get('game_id') if 'game_info' in data else 'unknown',
                        'errors': errors,
                        'has_game_info': 'game_info' in data,
                        'has_playbyplay': 'playByPlay' in data
                    },
                    processor_name="BigDataBall Play-by-Play Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform BigDataBall JSON to BigQuery rows"""
        game_info = raw_data['game_info']
        play_by_play = raw_data['playByPlay']
        
        # Parse date and determine season
        game_date_raw = game_info['date']
        game_date, season_year = self.parse_game_date(game_date_raw)

        # Construct consistent game_id
        game_id = self.construct_game_id(
            game_date,  # Use ISO format date
            game_info['away_team'], 
            game_info['home_team']
        )
        
        rows = []
        
        for event in play_by_play:
            # Determine player roles and names
            player_2_name = self.get_player_2_name(event)
            player_2_role = self.determine_player_role(event)
            player_3_name = self.get_player_3_name(event)
            player_3_role = self.determine_player_3_role(event)
            
            row = {
                # Core Game Identifiers
                'game_id': game_id,
                'bdb_game_id': event.get('game_id'),
                'game_date': game_date,
                'season_year': season_year,
                'data_set': event.get('data_set'),
                'home_team_abbr': game_info['home_team'],
                'away_team_abbr': game_info['away_team'],
                
                # Event Identifiers
                'event_id': f"{game_id}_{event.get('play_id')}",
                'event_sequence': int(event.get('play_id')) if event.get('play_id') is not None else None,
                'period': int(event.get('period')) if event.get('period') is not None else None,
                
                # Game Clock
                'game_clock': event.get('remaining_time'),
                'game_clock_seconds': self.convert_time_to_seconds(event.get('remaining_time')),
                'elapsed_time': event.get('elapsed'),
                'elapsed_seconds': self.convert_time_to_seconds(event.get('elapsed')),
                'play_length': event.get('play_length'),
                'play_length_seconds': self.convert_time_to_seconds(event.get('play_length')),
                
                # Event Details
                'event_type': event.get('event_type'),
                'event_subtype': event.get('type'),
                'event_description': event.get('description'),
                
                # Score Tracking
                'score_home': int(event.get('home_score')) if event.get('home_score') is not None else None,
                'score_away': int(event.get('away_score')) if event.get('away_score') is not None else None,
                
                # Primary Player
                'player_1_name': event.get('player'),
                'player_1_lookup': self.normalize_player_name(event.get('player')) if event.get('player') else None,
                'player_1_team_abbr': event.get('team'),
                
                # Secondary Player
                'player_2_name': player_2_name,
                'player_2_lookup': self.normalize_player_name(player_2_name) if player_2_name else None,
                'player_2_team_abbr': None,
                'player_2_role': player_2_role,
                
                # Tertiary Player
                'player_3_name': player_3_name,
                'player_3_lookup': self.normalize_player_name(player_3_name) if player_3_name else None,
                'player_3_team_abbr': None,
                'player_3_role': player_3_role,
                
                # Shot Details
                'shot_made': event.get('result') == 'made' if event.get('event_type') == 'shot' else None,
                'shot_type': self.determine_shot_type(event.get('type')) if event.get('event_type') == 'shot' else None,
                'shot_distance': event.get('shot_distance'),
                'points_scored': int(event.get('points')) if event.get('points') is not None else None,
                
                # Shot Coordinates
                'original_x': event.get('original_x'),
                'original_y': event.get('original_y'),
                'converted_x': event.get('converted_x'),
                'converted_y': event.get('converted_y'),
                
                # Lineup Data (lookup-only)
                'away_player_1_lookup': self.normalize_player_name(event.get('a1')) if event.get('a1') else None,
                'away_player_2_lookup': self.normalize_player_name(event.get('a2')) if event.get('a2') else None,
                'away_player_3_lookup': self.normalize_player_name(event.get('a3')) if event.get('a3') else None,
                'away_player_4_lookup': self.normalize_player_name(event.get('a4')) if event.get('a4') else None,
                'away_player_5_lookup': self.normalize_player_name(event.get('a5')) if event.get('a5') else None,
                'home_player_1_lookup': self.normalize_player_name(event.get('h1')) if event.get('h1') else None,
                'home_player_2_lookup': self.normalize_player_name(event.get('h2')) if event.get('h2') else None,
                'home_player_3_lookup': self.normalize_player_name(event.get('h3')) if event.get('h3') else None,
                'home_player_4_lookup': self.normalize_player_name(event.get('h4')) if event.get('h4') else None,
                'home_player_5_lookup': self.normalize_player_name(event.get('h5')) if event.get('h5') else None,
                
                # Additional BigDataBall Fields
                'possession_player_name': event.get('possession'),
                'possession_player_lookup': self.normalize_player_name(event.get('possession')) if event.get('possession') else None,
                'reason': event.get('reason'),
                'opponent': event.get('opponent'),
                'num': event.get('num'),
                'outof': event.get('outof'),
                
                # Processing Metadata
                'source_file_path': file_path,
                'csv_filename': raw_data.get('file_info', {}).get('name'),
                'csv_row_number': None,
                'data_source': 'bigdataball',  # Primary data source
                'processed_at': datetime.utcnow().isoformat(),
                'created_at': datetime.utcnow().isoformat()
            }

            rows.append(row)

        self.transformed_data = rows
        self.data_source = 'bigdataball'

        # Add smart idempotency hash to each row
        self.add_data_hash()

    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load data to BigQuery using streaming-compatible strategy"""
        if not rows:
            logging.warning("No rows to load")
            self.stats['rows_inserted'] = 0
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            game_id = rows[0]['game_id']
            game_date = rows[0]['game_date']
            
            # Check if this is the first file for this game today
            check_query = f"""
            SELECT COUNT(*) as existing_rows
            FROM `{table_id}` 
            WHERE game_id = '{game_id}' AND game_date = '{game_date}'
            """
            
            query_job = self.bq_client.query(check_query)
            result = query_job.result(timeout=60)
            existing_rows = next(result).existing_rows
            
            if existing_rows > 0:
                # Data already exists - this is likely a duplicate file for the same game
                logging.info(f"Game {game_id} already has {existing_rows} rows - skipping to avoid streaming buffer conflict")
                
                # Notify duplicate processing attempt
                try:
                    notify_warning(
                        title="BigDataBall Play-by-Play Duplicate Game Skipped",
                        message=f"Game {game_id} already processed with {existing_rows} rows - skipping to avoid conflicts",
                        details={
                            'game_id': game_id,
                            'game_date': game_date,
                            'existing_rows': existing_rows,
                            'attempted_rows': len(rows)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")

                self.stats['rows_inserted'] = 0
                return {
                    'rows_processed': 0,
                    'errors': [],
                    'game_id': game_id,
                    'message': f'Skipped - game already processed with {existing_rows} rows'
                }
            else:
                # First time processing this game - safe to insert
                # Use batch loading (not streaming insert) to avoid DML limit and streaming buffer issues
                logging.info(f"Loading {len(rows)} rows for new game {game_id} using batch load")

                # Get table schema for load job
                table = self.bq_client.get_table(table_id)

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
                logging.info(f"Successfully loaded {len(rows)} play-by-play events for game {game_id}")

                # Update stats for processor_base tracking
                self.stats['rows_inserted'] = len(rows)

                # Success - send info notification
                try:
                    source_label = 'NBA.com Fallback' if self.data_source == 'nbacom_fallback' else 'BigDataBall'
                    notify_info(
                        title=f"PBP Processing Complete ({source_label})",
                        message=f"Successfully processed {len(rows)} play-by-play events for game {game_id}",
                        details={
                            'game_id': game_id,
                            'game_date': game_date,
                            'rows_processed': len(rows),
                            'away_team': rows[0]['away_team_abbr'],
                            'home_team': rows[0]['home_team_abbr'],
                            'data_source': self.data_source
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                        
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data: {error_msg}")

            # Update stats for failure tracking
            self.stats['rows_inserted'] = 0

            # Notify unexpected error
            try:
                notify_error(
                    title="BigDataBall Play-by-Play Processing Failed",
                    message=f"Unexpected error during processing: {error_msg}",
                    details={
                        'game_id': rows[0]['game_id'] if rows else 'unknown',
                        'error_type': type(e).__name__,
                        'error_message': error_msg,
                        'rows_attempted': len(rows)
                    },
                    processor_name="BigDataBall Play-by-Play Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'rows_processed': len(rows) if not errors else 0, 
            'errors': errors,
            'game_id': rows[0]['game_id'] if rows else None
        }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0),
            'data_source': self.data_source
        }

    def process_with_fallback(self, nba_game_id: str, game_date: str) -> Dict:
        """
        Process BigDataBall PBP data with NBA.com fallback.

        This method tries to load and process BigDataBall data first.
        If BDB data is unavailable, it falls back to NBA.com PBP data.

        Args:
            nba_game_id: NBA game ID (e.g., '0022400561')
            game_date: Game date in YYYY-MM-DD format

        Returns:
            Dict with processing results including data_source used
        """
        result = {
            'game_id': None,
            'game_date': game_date,
            'nba_game_id': nba_game_id,
            'rows_processed': 0,
            'data_source': None,
            'used_fallback': False,
            'errors': []
        }

        # Try BigDataBall first
        try:
            # Attempt to load BDB data for this game
            bdb_data = self._find_bdb_data(nba_game_id, game_date)

            if bdb_data:
                # Process BDB data normally
                self.raw_data = bdb_data
                validation_errors = self.validate_data(bdb_data)

                if not validation_errors:
                    self.transform_data()

                    if self.transformed_data:
                        save_result = self.save_data()
                        result['rows_processed'] = save_result.get('rows_processed', 0)
                        result['game_id'] = save_result.get('game_id')
                        result['data_source'] = 'bigdataball'
                        result['errors'] = save_result.get('errors', [])
                        return result
                    else:
                        logger.warning(f"BDB transform yielded no rows for game {nba_game_id}")
                else:
                    logger.warning(f"BDB validation failed for game {nba_game_id}: {validation_errors}")
            else:
                logger.info(f"No BigDataBall data found for game {nba_game_id} on {game_date}")

        except Exception as e:
            logger.warning(f"Error processing BigDataBall data for game {nba_game_id}: {e}")
            result['errors'].append(f"BDB error: {str(e)}")

        # Fall back to NBA.com PBP
        logger.info(f"Attempting NBA.com fallback for game {nba_game_id}")
        fallback_rows = self.try_nbacom_fallback(nba_game_id, game_date)

        if fallback_rows:
            self.transformed_data = fallback_rows
            self.add_data_hash()
            save_result = self.save_data()

            result['rows_processed'] = save_result.get('rows_processed', 0)
            result['game_id'] = save_result.get('game_id')
            result['data_source'] = 'nbacom_fallback'
            result['used_fallback'] = True
            result['errors'] = save_result.get('errors', [])

            logger.info(f"Successfully used NBA.com fallback for game {nba_game_id}: {result['rows_processed']} rows")
        else:
            result['errors'].append("Both BigDataBall and NBA.com fallback failed")
            logger.error(f"Both BDB and NBA.com fallback failed for game {nba_game_id}")

            try:
                notify_error(
                    title="PBP Data Unavailable from All Sources",
                    message=f"No play-by-play data available for game {nba_game_id}",
                    details={
                        'nba_game_id': nba_game_id,
                        'game_date': game_date,
                        'sources_tried': ['bigdataball', 'nbacom'],
                        'errors': result['errors']
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        return result

    def _find_bdb_data(self, nba_game_id: str, game_date: str) -> Optional[Dict]:
        """
        Find BigDataBall PBP data for a specific game.

        Args:
            nba_game_id: NBA game ID
            game_date: Game date in YYYY-MM-DD format

        Returns:
            BDB data dict or None if not found
        """
        try:
            bucket = self.storage_client.bucket(self.bucket_name)

            # Calculate season for path
            game_date_parts = game_date.split('-')
            year = int(game_date_parts[0])
            month = int(game_date_parts[1])
            season_year = year if month >= 10 else year - 1
            season = f"{season_year}-{(season_year + 1) % 100:02d}"

            # BigDataBall files are stored at:
            # big-data-ball/{season}/{date}/game_{game_id}/{filename}.csv
            prefix = f"big-data-ball/{season}/{game_date}/game_{nba_game_id}/"

            blobs = list(bucket.list_blobs(prefix=prefix))

            if not blobs:
                # Try without the game_ prefix
                prefix = f"big-data-ball/{season}/{game_date}/"
                blobs = [b for b in bucket.list_blobs(prefix=prefix)
                        if nba_game_id in b.name]

            if not blobs:
                return None

            # Get the most recent file
            latest_blob = sorted(blobs, key=lambda b: b.name, reverse=True)[0]

            # Download and parse
            content = latest_blob.download_as_text()
            data = self.parse_json(content, latest_blob.name)

            if data:
                data['metadata'] = data.get('metadata', {})
                data['metadata']['source_file'] = latest_blob.name

            return data

        except Exception as e:
            logger.error(f"Error finding BDB data for game {nba_game_id}: {e}")
            return None
