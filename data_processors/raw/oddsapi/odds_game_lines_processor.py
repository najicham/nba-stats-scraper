#!/usr/bin/env python3
# File: processors/odds_api/odds_game_lines_processor.py
# Description: Processor for Odds API game lines history data transformation

import json, logging, re, os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
import pytz
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class OddsGameLinesProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.odds_api_game_lines'
        self.processing_strategy = 'MERGE_UPDATE'  # Replace snapshots for same game/timestamp
        
        # CRITICAL: Initialize BigQuery client and project_id
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.unknown_teams = set()  # Track unknown teams for batch warning
        
        # Initialize Eastern timezone for game date conversions
        self.eastern_tz = pytz.timezone('US/Eastern')
    
    def normalize_team_name(self, team_name: str) -> str:
        """Aggressive normalization for team name consistency."""
        if not team_name:
            return ""
        
        normalized = team_name.lower().strip()
        
        # Handle common aliases first
        normalized = normalized.replace("la clippers", "los angeles clippers")
        normalized = normalized.replace("la lakers", "los angeles lakers")
        
        # Remove all non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', normalized)
    
    def get_team_abbreviation(self, team_name: str) -> str:
        """Convert team name to standard 3-letter abbreviation."""
        # Team name to abbreviation mapping
        team_mapping = {
            'atlantahawks': 'ATL',
            'bostonceltics': 'BOS',
            'brooklynnets': 'BKN',
            'charlottehornets': 'CHA',
            'chicagobulls': 'CHI',
            'clevelandcavaliers': 'CLE',
            'dallasmavericks': 'DAL',
            'denvernuggets': 'DEN',
            'detroitpistons': 'DET',
            'goldenstatewarriors': 'GSW',
            'houstonrockets': 'HOU',
            'indianapacers': 'IND',
            'losangelesclippers': 'LAC',
            'losangeleslakers': 'LAL',
            'memphisgrizzlies': 'MEM',
            'miamiheat': 'MIA',
            'milwaukeebucks': 'MIL',
            'minnesotatimberwolves': 'MIN',
            'neworleanspelicans': 'NOP',
            'newyorkknicks': 'NYK',
            'oklahomacitythunder': 'OKC',
            'orlandomagic': 'ORL',
            'philadelphia76ers': 'PHI',
            'phoenixsuns': 'PHX',
            'portlandtrailblazers': 'POR',
            'sacramentokings': 'SAC',
            'sanantoniospurs': 'SAS',
            'torontoraptors': 'TOR',
            'utahjazz': 'UTA',
            'washingtonwizards': 'WAS'
        }
        
        normalized = self.normalize_team_name(team_name)
        abbr = team_mapping.get(normalized)
        
        if not abbr:
            # Team not in mapping - use fallback and track
            self.unknown_teams.add(team_name)
            abbr = team_name[:3].upper()
        
        return abbr
    
    def parse_timestamp(self, timestamp_str: str) -> Optional[str]:
        """Parse ISO timestamp string to proper format."""
        if not timestamp_str:
            return None
        try:
            # Parse ISO format and convert to isoformat for BigQuery
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return dt.isoformat()
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}")
            return None
    
    def extract_game_date_from_commence_time(self, commence_time_str: str) -> Optional[str]:
        """
        Extract game date from commence_time by converting UTC to Eastern timezone.
        
        This is CRITICAL: NBA games are scheduled in Eastern time, but the API returns
        UTC timestamps. A game at "8:00 PM Nov 27 EST" is stored as "01:00 AM Nov 28 UTC".
        We must convert to Eastern before extracting the date.
        
        Args:
            commence_time_str: ISO format timestamp (e.g., "2021-11-28T01:10:00Z")
            
        Returns:
            Game date in ISO format (e.g., "2021-11-27") or None if parsing fails
        """
        if not commence_time_str:
            logger.warning("commence_time is empty, cannot extract game_date")
            return None
        
        try:
            # Parse the UTC timestamp
            dt_utc = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
            
            # Convert to Eastern timezone
            dt_eastern = dt_utc.astimezone(self.eastern_tz)
            
            # Extract the date in Eastern timezone
            game_date = dt_eastern.date().isoformat()
            
            logger.debug(
                f"Converted commence_time to game_date: "
                f"{commence_time_str} (UTC) -> {dt_eastern.isoformat()} (EST) -> {game_date}"
            )
            
            return game_date
            
        except Exception as e:
            logger.error(
                f"Failed to extract game_date from commence_time '{commence_time_str}': {e}",
                exc_info=True
            )
            return None
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate required fields in the odds data."""
        errors = []
        
        if 'timestamp' not in data:
            errors.append("Missing timestamp")
        
        if 'data' not in data:
            errors.append("Missing data section")
            return errors
        
        game_data = data['data']
        required_fields = ['id', 'commence_time', 'home_team', 'away_team', 'bookmakers']
        
        for field in required_fields:
            if field not in game_data:
                errors.append(f"Missing required field in game data: {field}")
        
        if 'bookmakers' in game_data and not isinstance(game_data['bookmakers'], list):
            errors.append("Bookmakers must be an array")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform nested odds data into flat rows for BigQuery."""
        rows = []
        
        try:
            # Validate data first
            errors = self.validate_data(raw_data)
            if errors:
                logger.error(f"Validation errors for {file_path}: {errors}")
                
                # Send warning notification for validation errors
                try:
                    notify_warning(
                        title="Game Lines Data Validation Errors",
                        message=f"Validation errors found in odds API game lines data: {', '.join(errors[:3])}",
                        details={
                            'processor': 'OddsGameLinesProcessor',
                            'file_path': file_path,
                            'error_count': len(errors),
                            'errors': errors[:5]  # First 5 errors
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return rows
            
            now = datetime.now(timezone.utc).isoformat()
            
            # Parse timestamps
            snapshot_timestamp = self.parse_timestamp(raw_data.get('timestamp'))
            previous_timestamp = self.parse_timestamp(raw_data.get('previous_timestamp'))
            next_timestamp = self.parse_timestamp(raw_data.get('next_timestamp'))
            
            game_data = raw_data['data']
            
            # Game-level data
            game_id = game_data['id']
            sport_key = game_data['sport_key']
            sport_title = game_data['sport_title']
            commence_time = self.parse_timestamp(game_data['commence_time'])
            home_team = game_data['home_team']
            away_team = game_data['away_team']
            
            # CRITICAL FIX: Extract game date from commence_time using Eastern timezone
            game_date = self.extract_game_date_from_commence_time(game_data['commence_time'])
            
            if not game_date:
                error_msg = f"Failed to extract game_date from commence_time for game {game_id}"
                logger.error(error_msg)
                
                try:
                    notify_error(
                        title="Game Date Extraction Failed",
                        message=error_msg,
                        details={
                            'processor': 'OddsGameLinesProcessor',
                            'file_path': file_path,
                            'game_id': game_id,
                            'commence_time': game_data.get('commence_time'),
                            'home_team': home_team,
                            'away_team': away_team
                        },
                        processor_name="Odds API Game Lines Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                # Skip this file if we can't get a valid game_date
                return rows
            
            # Get team abbreviations
            home_team_abbr = self.get_team_abbreviation(home_team)
            away_team_abbr = self.get_team_abbreviation(away_team)
            
            # Process each bookmaker
            for bookmaker in game_data.get('bookmakers', []):
                bookmaker_key = bookmaker.get('key', '')
                bookmaker_title = bookmaker.get('title', '')
                bookmaker_last_update = self.parse_timestamp(bookmaker.get('last_update'))
                
                # Process each market (spreads, totals, etc.)
                for market in bookmaker.get('markets', []):
                    market_key = market.get('key', '')
                    market_last_update = self.parse_timestamp(market.get('last_update'))
                    
                    # Process each outcome
                    for outcome in market.get('outcomes', []):
                        row = {
                            # Snapshot metadata
                            'snapshot_timestamp': snapshot_timestamp,
                            'previous_snapshot_timestamp': previous_timestamp,
                            'next_snapshot_timestamp': next_timestamp,
                            
                            # Game identifiers
                            'game_id': game_id,
                            'sport_key': sport_key,
                            'sport_title': sport_title,
                            'commence_time': commence_time,
                            'game_date': game_date,  # Now correctly extracted in Eastern timezone
                            
                            # Teams
                            'home_team': home_team,
                            'away_team': away_team,
                            'home_team_abbr': home_team_abbr,
                            'away_team_abbr': away_team_abbr,
                            
                            # Bookmaker info
                            'bookmaker_key': bookmaker_key,
                            'bookmaker_title': bookmaker_title,
                            'bookmaker_last_update': bookmaker_last_update,
                            
                            # Market info
                            'market_key': market_key,
                            'market_last_update': market_last_update,
                            
                            # Outcome info
                            'outcome_name': outcome.get('name', ''),
                            'outcome_price': float(outcome.get('price', 0)),
                            'outcome_point': float(outcome.get('point', 0)) if outcome.get('point') is not None else None,
                            
                            # Processing metadata
                            'source_file_path': file_path,
                            'created_at': now,
                            'processed_at': now
                        }
                        rows.append(row)
            
            # Log successful transformation with game date info
            if rows:
                logger.info(
                    f"Transformed {len(rows)} rows for game {game_id} "
                    f"({away_team_abbr}@{home_team_abbr}) on {game_date} "
                    f"(commence_time: {game_data['commence_time']})"
                )
            
        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            
            # Send error notification
            try:
                notify_error(
                    title="Game Lines Transform Failed",
                    message=f"Failed to transform odds API game lines data: {str(e)}",
                    details={
                        'processor': 'OddsGameLinesProcessor',
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="Odds API Game Lines Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data into BigQuery with MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this game and snapshot timestamp
                game_id = rows[0]['game_id']
                snapshot_timestamp = rows[0]['snapshot_timestamp']
                game_date = rows[0]['game_date']
                
                delete_query = f"""
                DELETE FROM `{table_id}` 
                WHERE game_date = '{game_date}'
                AND game_id = '{game_id}' 
                AND snapshot_timestamp = '{snapshot_timestamp}'
                """
                
                try:
                    delete_result = self.bq_client.query(delete_query).result()
                    logger.info(
                        f"Deleted existing records for game {game_id} "
                        f"on {game_date} at snapshot {snapshot_timestamp}"
                    )
                except Exception as delete_error:
                    error_msg = f"Failed to delete existing records: {str(delete_error)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    
                    # Send error notification for delete failure
                    try:
                        notify_error(
                            title="Game Lines Delete Failed",
                            message=f"Failed to delete existing game lines records before insert",
                            details={
                                'processor': 'OddsGameLinesProcessor',
                                'table': self.table_name,
                                'game_id': game_id,
                                'game_date': game_date,
                                'snapshot_timestamp': snapshot_timestamp,
                                'error_type': type(delete_error).__name__,
                                'error_message': str(delete_error)
                            },
                            processor_name="Odds API Game Lines Processor"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    
                    # Don't proceed with insert if delete failed
                    return {'rows_processed': 0, 'errors': errors}
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logger.error(f"BigQuery insert errors: {result}")
                
                # Send error notification for insert failures
                try:
                    notify_error(
                        title="Game Lines BigQuery Insert Failed",
                        message=f"Failed to insert {len(rows)} game line records into BigQuery",
                        details={
                            'processor': 'OddsGameLinesProcessor',
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'error_count': len(result),
                            'errors': [str(e) for e in result[:3]]  # First 3 errors
                        },
                        processor_name="Odds API Game Lines Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            else:
                logger.info(f"Successfully inserted {len(rows)} rows into {table_id}")
                
                # Success - send info notification
                try:
                    notify_info(
                        title="Game Lines Processing Complete",
                        message=f"Successfully processed {len(rows)} game line records",
                        details={
                            'processor': 'OddsGameLinesProcessor',
                            'rows_processed': len(rows),
                            'table': self.table_name,
                            'strategy': self.processing_strategy,
                            'game_id': rows[0]['game_id'],
                            'game_date': rows[0]['game_date'],
                            'teams': f"{rows[0]['away_team_abbr']}@{rows[0]['home_team_abbr']}"
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                # Warn about unknown teams if any were found
                if self.unknown_teams:
                    try:
                        notify_warning(
                            title="Unknown Team Names Detected",
                            message=f"Found {len(self.unknown_teams)} unknown team names in game lines data",
                            details={
                                'processor': 'OddsGameLinesProcessor',
                                'unknown_teams': list(self.unknown_teams)
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                        
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Failed to load data: {e}", exc_info=True)
            
            # Send critical error notification
            try:
                notify_error(
                    title="Game Lines Load Exception",
                    message=f"Critical failure loading game lines data: {str(e)}",
                    details={
                        'processor': 'OddsGameLinesProcessor',
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="Odds API Game Lines Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}