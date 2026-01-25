#!/usr/bin/env python3
# processors/balldontlie/bdl_boxscores_processor.py

import json
import os
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime, date, timezone
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

class BdlBoxscoresProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Ball Don't Lie Boxscores Processor

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: game_id, player_lookup, points, rebounds, assists, field_goals_made, field_goals_attempted
        Expected Skip Rate: 30% when boxscores unchanged
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'game_id',
        'player_lookup',
        'points',
        'rebounds',
        'assists',
        'field_goals_made',
        'field_goals_attempted'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_player_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = get_bigquery_client(self.project_id)
        
        # Team abbreviation mapping for consistency
        self.team_mapping = {
            'atlanta hawks': 'ATL', 'boston celtics': 'BOS', 'brooklyn nets': 'BKN',
            'charlotte hornets': 'CHA', 'chicago bulls': 'CHI', 'cleveland cavaliers': 'CLE',
            'dallas mavericks': 'DAL', 'denver nuggets': 'DEN', 'detroit pistons': 'DET',
            'golden state warriors': 'GSW', 'houston rockets': 'HOU', 'indiana pacers': 'IND',
            'los angeles clippers': 'LAC', 'los angeles lakers': 'LAL', 'memphis grizzlies': 'MEM',
            'miami heat': 'MIA', 'milwaukee bucks': 'MIL', 'minnesota timberwolves': 'MIN',
            'new orleans pelicans': 'NOP', 'new york knicks': 'NYK', 'oklahoma city thunder': 'OKC',
            'orlando magic': 'ORL', 'philadelphia 76ers': 'PHI', 'phoenix suns': 'PHX',
            'portland trail blazers': 'POR', 'sacramento kings': 'SAC', 'san antonio spurs': 'SAS',
            'toronto raptors': 'TOR', 'utah jazz': 'UTA', 'washington wizards': 'WAS'
        }
        
        # Standard NBA team abbreviations for validation
        self.valid_team_abbrevs = set(self.team_mapping.values())

    def load_data(self) -> None:
        """Load boxscores data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_team_name(self, team_name: str) -> str:
        """Normalize team name to standard abbreviation."""
        if not team_name:
            return ""
        
        # Convert to lowercase and remove extra whitespace
        normalized = team_name.lower().strip()
        
        # Handle common aliases
        aliases = {
            'la lakers': 'los angeles lakers',
            'la clippers': 'los angeles clippers'
        }
        
        if normalized in aliases:
            normalized = aliases[normalized]
            
        mapped_abbrev = self.team_mapping.get(normalized, "")
        
        # If mapping failed, try extracting from original team name
        if not mapped_abbrev:
            # Fallback: use first 3 characters of team name in uppercase
            fallback_abbrev = team_name.upper()[:3]
            logger.warning(f"Unknown team name '{team_name}', using fallback abbreviation '{fallback_abbrev}'")
            
            # Notify about unknown team name
            try:
                notify_warning(
                    title="Unknown Team Name",
                    message=f"Unknown team name encountered: {team_name}",
                    details={
                        'team_name': team_name,
                        'fallback_abbrev': fallback_abbrev,
                        'processor': 'BDL Box Scores'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
            
            return fallback_abbrev
            
        return mapped_abbrev
    
    def extract_team_abbreviation(self, team_data: Dict) -> str:
        """Extract team abbreviation with multiple fallback strategies."""
        if not team_data:
            return ""
        
        # Strategy 1: Use full_name mapping
        full_name = team_data.get('full_name', '')
        if full_name:
            abbrev = self.normalize_team_name(full_name)
            if abbrev and abbrev in self.valid_team_abbrevs:
                return abbrev
        
        # Strategy 2: Use abbreviation field directly
        direct_abbrev = team_data.get('abbreviation', '')
        if direct_abbrev and direct_abbrev.upper() in self.valid_team_abbrevs:
            return direct_abbrev.upper()
        
        # Strategy 3: Use city + name combination
        city = team_data.get('city', '')
        name = team_data.get('name', '')
        if city and name:
            combined_name = f"{city} {name}"
            abbrev = self.normalize_team_name(combined_name)
            if abbrev and abbrev in self.valid_team_abbrevs:
                return abbrev
        
        # Log detailed error for debugging
        logger.error(f"Failed to extract team abbreviation from: {team_data}")
        return ""
    
    def normalize_player_name(self, first_name: str, last_name: str) -> str:
        """Create normalized player lookup string."""
        full_name = f"{first_name} {last_name}".strip()
        # Remove spaces, punctuation, and convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', full_name.lower())
        return normalized
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []
        
        if 'boxScores' not in data:
            errors.append("Missing 'boxScores' field")
            return errors
            
        if not isinstance(data['boxScores'], list):
            errors.append("'boxScores' is not a list")
            return errors
            
        if not data['boxScores']:
            errors.append("Empty boxScores array")
            
        return errors
    
    def extract_season_year(self, game_date: str, season_field: Optional[int] = None) -> int:
        """Extract season year from date or season field."""
        if season_field:
            return season_field
            
        # Fall back to date-based calculation
        game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
        if game_dt.month >= 10:  # October or later = start of season
            return game_dt.year
        else:  # Before October = second year of season
            return game_dt.year - 1
    
    def validate_game_id_format(self, game_id: str) -> bool:
        """Validate that game ID follows YYYYMMDD_AWAY_HOME format."""
        parts = game_id.split('_')
        if len(parts) != 3:
            return False
        
        date_part, away_team, home_team = parts
        
        # Validate date part (8 digits)
        if len(date_part) != 8 or not date_part.isdigit():
            return False
        
        # Validate team abbreviations (3 characters each)
        if len(away_team) != 3 or len(home_team) != 3:
            return False
        
        # Validate teams are known abbreviations
        if away_team not in self.valid_team_abbrevs or home_team not in self.valid_team_abbrevs:
            logger.warning(f"Unknown team abbreviations in game_id {game_id}: {away_team}, {home_team}")
        
        return True
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform BDL box scores JSON to BigQuery rows."""
        rows = []
        skipped_games = []
        
        box_scores = raw_data.get('boxScores', [])
        
        for game_idx, game in enumerate(box_scores):
            # Extract game-level data
            game_date_str = game.get('date')
            if not game_date_str:
                logger.warning(f"Skipping game {game_idx} with no date in {file_path}")
                skipped_games.append({'reason': 'no_date', 'game_idx': game_idx})
                continue
                
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
            game_date_str = game_date.strftime('%Y-%m-%d')
            season_year = self.extract_season_year(game_date_str, game.get('season'))
            
            # Extract team information - improved extraction
            home_team = game.get('home_team', {})
            away_team = game.get('visitor_team', {})  # Note: BDL calls it visitor_team
            
            home_team_abbr = self.extract_team_abbreviation(home_team)
            away_team_abbr = self.extract_team_abbreviation(away_team)
            
            # Validate both teams were successfully extracted
            if not home_team_abbr or not away_team_abbr:
                logger.error(f"Failed to extract team abbreviations for game {game_idx} in {file_path}")
                logger.error(f"Home team data: {home_team}")
                logger.error(f"Away team data: {away_team}")
                
                skipped_games.append({
                    'reason': 'team_extraction_failed',
                    'game_idx': game_idx,
                    'home_team': home_team.get('full_name', 'unknown'),
                    'away_team': away_team.get('full_name', 'unknown')
                })
                
                # Notify about team extraction failure
                try:
                    notify_error(
                        title="Team Extraction Failed",
                        message=f"Failed to extract team abbreviations for game {game_idx}",
                        details={
                            'file_path': file_path,
                            'game_idx': game_idx,
                            'home_team_data': str(home_team)[:200],
                            'away_team_data': str(away_team)[:200],
                            'processor': 'BDL Box Scores'
                        },
                        processor_name="BDL Box Scores Processor"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
                
                continue
            
            # CRITICAL FIX: Create game_id in CORRECT format: YYYYMMDD_AWAY_HOME
            game_id = f"{game_date.strftime('%Y%m%d')}_{away_team_abbr}_{home_team_abbr}"
            
            # Validate game ID format
            if not self.validate_game_id_format(game_id):
                logger.error(f"Invalid game_id format generated: {game_id}")
                
                skipped_games.append({
                    'reason': 'invalid_game_id',
                    'game_id': game_id,
                    'game_idx': game_idx
                })
                
                # Notify about invalid game ID
                try:
                    notify_error(
                        title="Invalid Game ID Format",
                        message=f"Generated invalid game_id: {game_id}",
                        details={
                            'game_id': game_id,
                            'file_path': file_path,
                            'game_idx': game_idx,
                            'expected_format': 'YYYYMMDD_AWAY_HOME',
                            'processor': 'BDL Box Scores'
                        },
                        processor_name="BDL Box Scores Processor"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
                
                continue
            
            logger.info(f"Processing game {game_id} ({away_team_abbr} @ {home_team_abbr})")
            
            # Process home team players
            home_players = home_team.get('players', [])
            for player_stats in home_players:
                player_info = player_stats.get('player', {})
                
                # Create player row
                row = self.create_player_row(
                    game_id=game_id,
                    game_date=game_date_str,
                    season_year=season_year,
                    game_status=game.get('status', ''),
                    period=game.get('period'),
                    is_postseason=game.get('postseason', False),
                    home_team_abbr=home_team_abbr,
                    away_team_abbr=away_team_abbr,
                    home_team_score=game.get('home_team_score'),
                    away_team_score=game.get('visitor_team_score'),
                    team_abbr=home_team_abbr,
                    player_info=player_info,
                    player_stats=player_stats,
                    file_path=file_path
                )
                
                if row:
                    rows.append(row)
            
            # Process away team players (renamed from visitor for clarity)
            away_players = away_team.get('players', [])
            for player_stats in away_players:
                player_info = player_stats.get('player', {})
                
                # Create player row
                row = self.create_player_row(
                    game_id=game_id,
                    game_date=game_date_str,
                    season_year=season_year,
                    game_status=game.get('status', ''),
                    period=game.get('period'),
                    is_postseason=game.get('postseason', False),
                    home_team_abbr=home_team_abbr,
                    away_team_abbr=away_team_abbr,
                    home_team_score=game.get('home_team_score'),
                    away_team_score=game.get('visitor_team_score'),
                    team_abbr=away_team_abbr,
                    player_info=player_info,
                    player_stats=player_stats,
                    file_path=file_path
                )
                
                if row:
                    rows.append(row)
        
        logger.info(f"Generated {len(rows)} player records from {len(box_scores)} games in {file_path}")

        # Data Quality Check: Detect if 0 records due to upcoming games
        if len(rows) == 0 and len(box_scores) > 0:
            # Check if all games are upcoming (period=0, no player data)
            upcoming_games = sum(1 for game in box_scores if game.get('period', 0) == 0)

            if upcoming_games == len(box_scores):
                logger.warning(
                    f"⚠️  Processed 0 records - all {len(box_scores)} games are upcoming (period=0, no player data yet). "
                    f"File: {file_path}"
                )
                # Notify about upcoming games (info level, not error)
                try:
                    notify_info(
                        title="BDL Boxscores: Upcoming Games Only",
                        message=f"Processed {len(box_scores)} upcoming games with no player data yet",
                        details={
                            'file_path': file_path,
                            'game_count': len(box_scores),
                            'upcoming_games': upcoming_games,
                            'reason': 'Games not yet played - player data not available',
                            'processor': 'BDL Box Scores'
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
            else:
                logger.error(
                    f"⚠️  Processed 0 records from {len(box_scores)} games, but only {upcoming_games} are upcoming. "
                    f"This may indicate a data quality issue. File: {file_path}"
                )

        # Send warning if games were skipped
        if skipped_games:
            try:
                notify_warning(
                    title="Games Skipped During Processing",
                    message=f"Skipped {len(skipped_games)} games during BDL box scores processing",
                    details={
                        'file_path': file_path,
                        'skipped_count': len(skipped_games),
                        'total_games': len(box_scores),
                        'skip_reasons': [g['reason'] for g in skipped_games[:5]],
                        'sample_games': skipped_games[:3]
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        self.transformed_data = rows

        # Smart Idempotency: Add data_hash to all records
        self.add_data_hash()
    def create_player_row(self, **kwargs) -> Optional[Dict]:
        """Create a single player performance row."""
        try:
            player_info = kwargs['player_info']
            player_stats = kwargs['player_stats']
            
            first_name = player_info.get('first_name', '')
            last_name = player_info.get('last_name', '')
            
            if not first_name or not last_name:
                logger.warning(f"Skipping player with incomplete name: {player_info}")
                return None
            
            player_full_name = f"{first_name} {last_name}"
            player_lookup = self.normalize_player_name(first_name, last_name)
            
            # Handle nullable percentage fields
            def safe_float(value):
                return float(value) if value is not None else None
            
            def safe_int(value):
                return int(value) if value is not None else 0
            
            row = {
                # Core identifiers
                'game_id': kwargs['game_id'],
                'game_date': kwargs['game_date'],
                'season_year': kwargs['season_year'],
                'game_status': kwargs['game_status'],
                'period': kwargs['period'],
                'is_postseason': kwargs['is_postseason'],
                
                # Team context
                'home_team_abbr': kwargs['home_team_abbr'],
                'away_team_abbr': kwargs['away_team_abbr'],
                'home_team_score': kwargs['home_team_score'],
                'away_team_score': kwargs['away_team_score'],
                'team_abbr': kwargs['team_abbr'],
                
                # Player identification
                'player_full_name': player_full_name,
                'player_lookup': player_lookup,
                'bdl_player_id': player_info.get('id'),
                'jersey_number': player_info.get('jersey_number'),
                'position': player_info.get('position'),
                
                # Performance stats
                'minutes': player_stats.get('min'),
                'points': safe_int(player_stats.get('pts')),
                'assists': safe_int(player_stats.get('ast')),
                'rebounds': safe_int(player_stats.get('reb')),
                'offensive_rebounds': safe_int(player_stats.get('oreb')),
                'defensive_rebounds': safe_int(player_stats.get('dreb')),
                'steals': safe_int(player_stats.get('stl')),
                'blocks': safe_int(player_stats.get('blk')),
                'turnovers': safe_int(player_stats.get('turnover')),
                'personal_fouls': safe_int(player_stats.get('pf')),
                
                # Shooting stats
                'field_goals_made': safe_int(player_stats.get('fgm')),
                'field_goals_attempted': safe_int(player_stats.get('fga')),
                'field_goal_pct': safe_float(player_stats.get('fg_pct')),
                'three_pointers_made': safe_int(player_stats.get('fg3m')),
                'three_pointers_attempted': safe_int(player_stats.get('fg3a')),
                'three_point_pct': safe_float(player_stats.get('fg3_pct')),
                'free_throws_made': safe_int(player_stats.get('ftm')),
                'free_throws_attempted': safe_int(player_stats.get('fta')),
                'free_throw_pct': safe_float(player_stats.get('ft_pct')),
                
                # Processing metadata
                'source_file_path': kwargs['file_path'],
                'created_at': datetime.now(timezone.utc).isoformat(),
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            
            return row
            
        except Exception as e:
            logger.error(f"Error creating player row: {e}")
            logger.error(f"Player info: {kwargs.get('player_info', {})}")
            logger.error(f"Player stats: {kwargs.get('player_stats', {})}")
            return None
    
    def is_streaming_buffer_error(self, error_message: str) -> bool:
        """Check if error is related to streaming buffer."""
        streaming_indicators = [
            "streaming buffer",
            "streaming insert",
            "table is being streamed",
            "delete from table with streaming",
            "cannot modify streaming table"
        ]
        error_lower = error_message.lower()
        return any(indicator in error_lower for indicator in streaming_indicators)
    
    def safe_delete_existing_data(self, table_id: str, game_id: str, game_date: str) -> Dict:
        """Safely delete existing data with streaming buffer protection."""
        delete_query = f"""
        DELETE FROM `{table_id}` 
        WHERE game_id = '{game_id}' 
          AND game_date = '{game_date}'
          AND DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) >= 90
        """
        
        try:
            delete_job = self.bq_client.query(delete_query)
            delete_result = delete_job.result(timeout=60)
            
            # Handle empty result when no rows to delete
            try:
                rows_deleted = delete_result.num_dml_affected_rows
            except AttributeError:
                # EmptyRowIterator when no rows deleted
                rows_deleted = 0
            
            if rows_deleted > 0:
                logger.info(f"Deleted {rows_deleted} existing rows for game {game_id}")
                return {'success': True, 'rows_deleted': rows_deleted, 'streaming_conflict': False}
            else:
                # Check if data exists but couldn't be deleted (streaming buffer)
                check_query = f"""
                SELECT COUNT(*) as total_rows,
                       COUNTIF(DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) < 90) as recent_rows
                FROM `{table_id}` 
                WHERE game_id = '{game_id}' AND game_date = '{game_date}'
                """
                check_result = list(self.bq_client.query(check_query))[0]
                
                if check_result.total_rows > 0 and check_result.recent_rows > 0:
                    logger.warning(f"Game {game_id} has {check_result.recent_rows} recent rows in streaming buffer")
                    
                    # Notify about streaming buffer conflict
                    try:
                        notify_warning(
                            title="Streaming Buffer Conflict",
                            message=f"Game {game_id} has recent data in streaming buffer",
                            details={
                                'game_id': game_id,
                                'game_date': game_date,
                                'recent_rows': check_result.recent_rows,
                                'total_rows': check_result.total_rows,
                                'processor': 'BDL Box Scores'
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
                    
                    return {'success': False, 'rows_deleted': 0, 'streaming_conflict': True, 
                           'recent_rows': check_result.recent_rows}
                else:
                    logger.info(f"No existing data found for game {game_id}")
                    return {'success': True, 'rows_deleted': 0, 'streaming_conflict': False}
                    
        except Exception as e:
            if self.is_streaming_buffer_error(str(e)):
                logger.error(f"Streaming buffer prevents deletion of {game_id}: {e}")
                return {'success': False, 'rows_deleted': 0, 'streaming_conflict': True, 'error': str(e)}
            else:
                logger.error(f"Unexpected deletion error for {game_id}: {e}")
                
                # Notify about unexpected deletion error
                try:
                    notify_error(
                        title="Unexpected Deletion Error",
                        message=f"Unexpected error deleting data for game {game_id}",
                        details={
                            'game_id': game_id,
                            'game_date': game_date,
                            'error': str(e),
                            'error_type': type(e).__name__,
                            'processor': 'BDL Box Scores'
                        },
                        processor_name="BDL Box Scores Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise e
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load transformed data to BigQuery with streaming buffer protection."""
        if not rows:
            self.stats["rows_inserted"] = 0  # Fix for tracking bug - Session 32
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        streaming_conflicts = []
        
        try:
            # Validate all game IDs before processing
            invalid_game_ids = []
            for row in rows:
                if not self.validate_game_id_format(row['game_id']):
                    invalid_game_ids.append(row['game_id'])
            
            if invalid_game_ids:
                error_msg = f"Invalid game_id formats detected: {invalid_game_ids[:5]}"
                errors.append(error_msg)
                logger.error(error_msg)
                
                # Notify about invalid game IDs
                try:
                    notify_error(
                        title="Invalid Game IDs Detected",
                        message=f"Found {len(invalid_game_ids)} invalid game_id formats",
                        details={
                            'invalid_count': len(invalid_game_ids),
                            'sample_ids': invalid_game_ids[:5],
                            'expected_format': 'YYYYMMDD_AWAY_HOME',
                            'processor': 'BDL Box Scores'
                        },
                        processor_name="BDL Box Scores Processor"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")

                self.stats["rows_inserted"] = 0  # Fix for tracking bug - Session 32
                return {'rows_processed': 0, 'errors': errors}
            
            if self.processing_strategy == 'MERGE_UPDATE':
                # Get all unique game_ids in this batch
                game_ids = set(row['game_id'] for row in rows)
                
                for game_id in game_ids:
                    # Get the game_date for this game_id
                    game_date = next((row['game_date'] for row in rows if row['game_id'] == game_id), None)
                    if game_date is None:
                        logger.warning(f"game_id {game_id} not found in rows, skipping delete")
                        continue

                    # Attempt safe deletion
                    delete_result = self.safe_delete_existing_data(table_id, game_id, game_date)
                    
                    if not delete_result['success'] and delete_result['streaming_conflict']:
                        streaming_conflicts.append({
                            'game_id': game_id,
                            'game_date': game_date,
                            'recent_rows': delete_result.get('recent_rows', 'unknown')
                        })
                
                # Session 6 (2026-01-10): Instead of aborting entire batch on streaming conflicts,
                # skip only the conflicting games and load the rest. This allows new games to be
                # processed even when some games have streaming buffer issues.
                if streaming_conflicts:
                    conflict_game_ids = {c['game_id'] for c in streaming_conflicts}
                    original_row_count = len(rows)

                    # Check for --force flag to bypass streaming buffer protection
                    force_mode = self.opts.get('force', False)

                    if force_mode:
                        logger.warning(f"FORCE MODE: Ignoring {len(streaming_conflicts)} streaming conflicts and loading all data")
                    else:
                        # Filter out rows for games with streaming conflicts
                        rows = [row for row in rows if row['game_id'] not in conflict_game_ids]
                        skipped_rows = original_row_count - len(rows)

                        logger.warning(
                            f"Skipping {len(streaming_conflicts)} games with streaming buffer conflicts: "
                            f"{[c['game_id'] for c in streaming_conflicts[:3]]}"
                        )
                        logger.info(f"Proceeding with {len(rows)} rows for games without conflicts")

                        # If all games had conflicts, nothing to load
                        if not rows:
                            error_msg = f"All {len(streaming_conflicts)} games have streaming conflicts, nothing to load"
                            errors.append(error_msg)
                            logger.warning(error_msg)

                            try:
                                notify_error(
                                    title="Streaming Buffer Conflicts - All Games Skipped",
                                    message=f"Skipped all {len(streaming_conflicts)} games due to streaming conflicts",
                                    details={
                                        'conflict_count': len(streaming_conflicts),
                                        'affected_games': [c['game_id'] for c in streaming_conflicts[:5]],
                                        'action_taken': 'skipped_all_games',
                                        'hint': 'Use --force to bypass streaming buffer protection',
                                        'processor': 'BDL Box Scores'
                                    },
                                    processor_name="BDL Box Scores Processor"
                                )
                            except Exception as e:
                                logger.warning(f"Failed to send notification: {e}")

                            self.stats["rows_inserted"] = 0  # Fix for tracking bug - Session 32
                            return {'rows_processed': 0, 'errors': errors, 'streaming_conflicts': streaming_conflicts}

                        # Notify that some games were skipped but processing continues
                        try:
                            notify_info(
                                title="Streaming Buffer Conflicts - Partial Processing",
                                message=f"Skipped {len(streaming_conflicts)} games, processing {len(rows)} rows for remaining games",
                                details={
                                    'conflict_count': len(streaming_conflicts),
                                    'skipped_games': [c['game_id'] for c in streaming_conflicts[:5]],
                                    'remaining_rows': len(rows),
                                    'action_taken': 'partial_processing',
                                    'hint': 'Conflicting games will be retried in next window',
                                    'processor': 'BDL Box Scores'
                                }
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send notification: {e}")
            
            # Insert new data using batch loading (not streaming insert)
            # This avoids the 20 DML limit and streaming buffer issues
            game_ids = set(row['game_id'] for row in rows)
            logger.info(f"Loading {len(rows)} rows for {len(game_ids)} games using batch load")

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

            # Set stats for run_history tracking (fix for tracking bug - Session 32)
            self.stats["rows_inserted"] = len(rows)

            logger.info(f"Successfully loaded {len(rows)} rows for {len(game_ids)} games")

            # Log game ID format compliance
            sample_game_ids = list(game_ids)[:3]
            logger.info(f"Sample game IDs inserted (AWAY_HOME format): {sample_game_ids}")

            # Send success notification
            try:
                notify_info(
                    title="BDL Box Scores Processing Complete",
                    message=f"Successfully processed {len(rows)} player box scores from {len(game_ids)} games",
                    details={
                        'player_records': len(rows),
                        'games_processed': len(game_ids),
                        'sample_game_ids': sample_game_ids,
                        'table': self.table_name,
                        'processor': 'BDL Box Scores'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")
            
            # Notify about general processing error
            try:
                notify_error(
                    title="BDL Box Scores Processing Failed",
                    message=f"Unexpected error during box scores processing: {str(e)}",
                    details={
                        'error': error_msg,
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'BDL Box Scores'
                    },
                    processor_name="BDL Box Scores Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            # Set stats to 0 on error (fix for tracking bug - Session 32)
            self.stats["rows_inserted"] = 0

        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors,
            'streaming_conflicts': streaming_conflicts
        }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }
