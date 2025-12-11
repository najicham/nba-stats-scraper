# processors/odds_api/odds_api_props_processor.py

import json
import logging
import re
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from data_processors.raw.utils.name_utils import normalize_name
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import NBATeamMapper for proper team code normalization
from shared.utils.nba_team_mapper import NBATeamMapper

logger = logging.getLogger(__name__)

class OddsApiPropsProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process Odds API player props data.

    Handles both:
    - Current/live data: odds-api/player-props/2025-10-21/...
    - Historical data: odds-api/player-props-history/2023-10-24/...

    Processing Strategy: APPEND_ALWAYS
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: player_lookup, game_date, game_id, bookmaker, points_line, snapshot_timestamp
        Expected Skip Rate: N/A (APPEND_ALWAYS always writes, hash for monitoring only)
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'player_lookup',
        'game_date',
        'game_id',
        'bookmaker',
        'points_line',
        'snapshot_timestamp'
    ]

    def __init__(self):
        super().__init__()
        self.project_id = "nba-props-platform"
        self.bq_client = bigquery.Client(project=self.project_id)
        self.table_name = 'nba_raw.odds_api_player_points_props'
        self.processing_strategy = 'APPEND_ALWAYS'
        self.unknown_teams = set()  # Track unknown teams for batch warning
        
        # Initialize team mapper for proper normalization
        # use_database=False to avoid dependency on BigQuery during processing
        self.team_mapper = NBATeamMapper(use_database=False)
        
        logger.info("OddsApiPropsProcessor initialized with NBATeamMapper")
        
    def is_historical_format(self, data: Dict) -> bool:
        """
        Detect if data is in historical format (wrapped) or current format (unwrapped).
        
        Historical format has:
        - 'data' key containing the event
        - 'timestamp' key for snapshot time
        - 'previous_timestamp' and 'next_timestamp'
        
        Current format is just the event object directly.
        """
        return 'data' in data and 'timestamp' in data
    
    def detect_data_source(self, raw_data: Dict, file_path: str = None) -> str:
        """
        Detect whether data came from historical or current endpoint.
        
        Args:
            raw_data: Raw API response
            file_path: Optional source file path
            
        Returns:
            'historical' or 'current'
        """
        # Primary detection: Check data structure
        if self.is_historical_format(raw_data):
            return 'historical'
        
        # Secondary detection: Check file path pattern
        if file_path:
            if 'player-props-history' in file_path or '/historical/' in file_path:
                return 'historical'
            elif 'player-props' in file_path or '/current/' in file_path:
                return 'current'
        
        # Default to 'current' for live data
        return 'current'
        
    def get_team_abbr(self, team_name: str) -> str:
        """
        Get NBA standard team abbreviation from full name using NBATeamMapper.
        
        This normalizes all team names to NBA.com standard (e.g., PHO → PHX).
        """
        if not team_name:
            return ''
        
        # Use team mapper to get NBA standard tricode
        tricode = self.team_mapper.get_nba_tricode(team_name)
        
        if tricode:
            return tricode
        
        # If not found, try fuzzy matching
        tricode = self.team_mapper.get_nba_tricode_fuzzy(team_name, min_confidence=85)
        
        if tricode:
            logger.info(f"Fuzzy matched team: '{team_name}' → {tricode}")
            return tricode
        
        # Still not found - log warning and track
        logger.warning(f"Unknown team name: {team_name}")
        self.unknown_teams.add(team_name)
        return team_name  # Return as-is if not found
    
    def decimal_to_american(self, decimal_odds: float) -> int:
        """Convert decimal odds to American odds."""
        if not decimal_odds or decimal_odds == 0:
            return None
            
        if decimal_odds >= 2.0:
            # Positive American odds
            return int((decimal_odds - 1) * 100)
        else:
            # Negative American odds
            return int(-100 / (decimal_odds - 1))
    
    def extract_metadata_from_path(self, file_path: str, is_historical: bool) -> Dict:
        """
        Extract metadata from file path.
        
        Historical: odds-api/player-props-history/2023-10-24/fd55db2fa9ee5be1f108be5151e2ecb0-LALDEN/20250812_035909-snap-2130.json
        Current:    odds-api/player-props/2025-10-21/bbde7751a144b98ed150d7a5f7dc8f87-HOUOKC/20251019_032435-snap-0324.json
        """
        path_parts = file_path.split('/')
        
        # Extract date (same position for both formats)
        date_str = path_parts[-3]  # "2023-10-24" or "2025-10-21"
        
        # Extract event ID and teams
        event_folder = path_parts[-2]  # "fd55db2fa9ee5be1f108be5151e2ecb0-LALDEN"
        
        # Split by last hyphen to separate event_id from teams
        # Using regex to find the event ID (hex string) and team codes
        match = re.match(r'^([a-f0-9]+)-([A-Z]{3})([A-Z]{3})$', event_folder)
        if match:
            event_id = match.group(1)
            away_team = match.group(2)  # First team is away
            home_team = match.group(3)  # Second team is home
        else:
            # Fallback parsing
            parts = event_folder.rsplit('-', 1)
            event_id = parts[0] if parts else event_folder
            teams = parts[1] if len(parts) > 1 else ""
            # Parse team codes (assuming 3 letters each)
            away_team = teams[:3] if len(teams) >= 3 else None
            home_team = teams[3:6] if len(teams) >= 6 else None
        
        # Extract snapshot info from filename
        filename = path_parts[-1].replace('.json', '')  # "20250812_035909-snap-2130"
        snapshot_parts = filename.split('-snap-')
        capture_timestamp = snapshot_parts[0] if snapshot_parts else None
        snapshot_tag = f"snap-{snapshot_parts[1]}" if len(snapshot_parts) > 1 else None
        
        return {
            'game_date': date_str,
            'event_id': event_id,
            'away_team_abbr': away_team,
            'home_team_abbr': home_team,
            'capture_timestamp': capture_timestamp,
            'snapshot_tag': snapshot_tag,
            'source_file_path': file_path,
            'is_historical': is_historical
        }
    
    def calculate_minutes_before_tipoff(self, game_start: datetime, snapshot: datetime) -> int:
        """Calculate minutes between snapshot and game start time."""
        diff = game_start - snapshot
        return int(diff.total_seconds() / 60)
    
    def validate_data(self, data: Dict, is_historical: bool) -> List[str]:
        """Validate the JSON data structure."""
        errors = []
        
        if not data:
            errors.append("Empty data")
            return errors
        
        # Get the game data (either wrapped or unwrapped)
        if is_historical:
            if 'data' not in data:
                errors.append("Missing 'data' field in historical format")
                return errors
            game_data = data.get('data', {})
            
            # Validate historical-specific fields
            if 'timestamp' not in data:
                errors.append("Missing 'timestamp' field in historical format")
        else:
            # Current format - data is the game object itself
            game_data = data
            
        # Check required fields in game data
        required_fields = ['id', 'commence_time', 'home_team', 'away_team', 'bookmakers']
        for field in required_fields:
            if field not in game_data:
                errors.append(f"Missing required field: {field}")
        
        # Validate bookmakers
        bookmakers = game_data.get('bookmakers', [])
        if not bookmakers:
            errors.append("No bookmakers found")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform Odds API props data to BigQuery rows."""
        rows = []
        
        try:
            # Detect format and data source
            is_historical = self.is_historical_format(raw_data)
            data_source = self.detect_data_source(raw_data, file_path)
            
            logger.debug(
                f"Processing {data_source} data ({'historical' if is_historical else 'current'} format) "
                f"from {file_path}"
            )
            
            # Validate data first
            errors = self.validate_data(raw_data, is_historical)
            if errors:
                logger.error(f"Validation errors for {file_path}: {errors}")
                
                # Send warning notification for validation errors
                try:
                    notify_warning(
                        title="Props Data Validation Errors",
                        message=f"Validation errors found in odds API props data: {', '.join(errors[:3])}",
                        details={
                            'processor': 'OddsApiPropsProcessor',
                            'file_path': file_path,
                            'format': 'historical' if is_historical else 'current',
                            'data_source': data_source,
                            'error_count': len(errors),
                            'errors': errors[:5]  # First 5 errors
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                self.transformed_data = rows
            
            # Extract metadata from file path
            metadata = self.extract_metadata_from_path(file_path, is_historical)
            
            # Get game data based on format
            if is_historical:
                game_data = raw_data.get('data', {})
                snapshot_timestamp = raw_data.get('timestamp')
            else:
                game_data = raw_data
                # For current data, snapshot timestamp might not be in the data
                # Try to extract from filename or use current time
                snapshot_timestamp = None
                if metadata.get('capture_timestamp'):
                    try:
                        # Convert capture timestamp to ISO format
                        capture_dt = datetime.strptime(metadata['capture_timestamp'], '%Y%m%d_%H%M%S')
                        snapshot_timestamp = capture_dt.isoformat() + 'Z'
                    except:
                        pass
            
            # Parse timestamps
            if snapshot_timestamp:
                snapshot_dt = datetime.fromisoformat(snapshot_timestamp.replace('Z', '+00:00'))
            else:
                logger.warning(f"No snapshot timestamp in {file_path}, using current time")
                snapshot_dt = datetime.now()
            
            game_date = datetime.strptime(metadata['game_date'], '%Y-%m-%d').date()
            
            commence_time_str = game_data.get('commence_time')
            if commence_time_str:
                game_start_dt = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
            else:
                game_start_dt = None
            
            # Calculate minutes before tipoff
            minutes_before = None
            if game_start_dt:
                minutes_before = self.calculate_minutes_before_tipoff(game_start_dt, snapshot_dt)
            
            # Get team abbreviations using NBATeamMapper (PHO → PHX, etc.)
            home_team_full = game_data.get('home_team', '')
            away_team_full = game_data.get('away_team', '')
            
            home_team_abbr = self.get_team_abbr(home_team_full)
            away_team_abbr = self.get_team_abbr(away_team_full)
            
            # Log the conversion for debugging
            if home_team_full and home_team_abbr:
                logger.debug(f"Normalized home team: '{home_team_full}' → {home_team_abbr}")
            if away_team_full and away_team_abbr:
                logger.debug(f"Normalized away team: '{away_team_full}' → {away_team_abbr}")
            
            # Create game_id in format YYYYMMDD_AWAY_HOME
            game_id = f"{metadata['game_date'].replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
            
            # Parse capture timestamp
            capture_dt = None
            if metadata.get('capture_timestamp'):
                # Format: 20250812_035909
                try:
                    capture_dt = datetime.strptime(metadata['capture_timestamp'], '%Y%m%d_%H%M%S')
                except:
                    logger.warning(f"Could not parse capture timestamp: {metadata.get('capture_timestamp')}")
            
            # Process each bookmaker
            for bookmaker in game_data.get('bookmakers', []):
                bookmaker_key = bookmaker.get('key', '')
                bookmaker_title = bookmaker.get('title', bookmaker_key)
                bookmaker_last_update = bookmaker.get('last_update')
                
                if bookmaker_last_update:
                    bookmaker_update_dt = datetime.fromisoformat(bookmaker_last_update.replace('Z', '+00:00'))
                else:
                    bookmaker_update_dt = None
                
                # Find player_points market
                for market in bookmaker.get('markets', []):
                    if market.get('key') != 'player_points':
                        continue
                    
                    # Process outcomes - group by player
                    player_props = {}
                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description', '')
                        outcome_type = outcome.get('name', '')  # 'Over' or 'Under'
                        price = outcome.get('price', 0)
                        points_line = outcome.get('point', 0)
                        
                        if not player_name:
                            continue
                        
                        if player_name not in player_props:
                            player_props[player_name] = {
                                'points_line': points_line,
                                'over_price': None,
                                'under_price': None
                            }
                        
                        if outcome_type == 'Over':
                            player_props[player_name]['over_price'] = price
                        elif outcome_type == 'Under':
                            player_props[player_name]['under_price'] = price
                    
                    # Create a row for each player
                    for player_name, props in player_props.items():
                        row = {
                            # Game identifiers
                            'game_id': game_id,
                            'odds_api_event_id': game_data.get('id', ''),
                            'game_date': game_date.isoformat() if hasattr(game_date, "isoformat") else game_date,
                            'game_start_time': game_start_dt,
                            
                            # Teams (NORMALIZED TO NBA STANDARD)
                            'home_team_abbr': home_team_abbr,
                            'away_team_abbr': away_team_abbr,
                            
                            # Snapshot tracking
                            'snapshot_timestamp': snapshot_dt,
                            'snapshot_tag': metadata.get('snapshot_tag'),
                            'capture_timestamp': capture_dt,
                            'minutes_before_tipoff': minutes_before,
                            
                            # Prop details
                            'bookmaker': bookmaker_key,
                            'player_name': player_name,
                            'player_lookup': normalize_name(player_name),
                            
                            # Points line
                            'points_line': props['points_line'],
                            'over_price': props['over_price'],
                            'over_price_american': self.decimal_to_american(props['over_price']) if props['over_price'] else None,
                            'under_price': props['under_price'],
                            'under_price_american': self.decimal_to_american(props['under_price']) if props['under_price'] else None,
                            
                            # Metadata
                            'bookmaker_last_update': bookmaker_update_dt,
                            'source_file_path': file_path,
                            'data_source': data_source  # NEW: Track data source
                        }
                        
                        rows.append(row)
            
            logger.info(
                f"Processed {len(rows)} prop records from {file_path} "
                f"(data_source={data_source}, format={'historical' if is_historical else 'current'})"
            )
            
        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            
            # Send error notification
            try:
                notify_error(
                    title="Props Transform Failed",
                    message=f"Failed to transform odds API props data: {str(e)}",
                    details={
                        'processor': 'OddsApiPropsProcessor',
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="Odds API Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            raise

        self.transformed_data = rows

        # Smart Idempotency: Add data_hash to all records
        self.add_data_hash()
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """
        Load data to BigQuery using batch loading (no streaming buffer).
        
        Uses load_table_from_json instead of insert_rows_json to avoid
        streaming buffer issues and enable immediate DML operations.
        """
        import datetime
        
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        # Convert datetime objects to ISO format strings
        for row in rows:
            for key, value in row.items():
                if isinstance(value, (datetime.date, datetime.datetime)):
                    row[key] = value.isoformat()
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Get target table for schema
            target_table = self.bq_client.get_table(table_id)
            
            # Use batch loading instead of streaming insert
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,  # Enforce exact schema
                autodetect=False,            # Don't infer schema
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,  # Append mode
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )
            
            # Batch load (NO streaming buffer!)
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result()  # Wait for completion

            if load_job.errors:
                errors.extend([str(e) for e in load_job.errors])
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")

                # Send error notification
                try:
                    notify_error(
                        title="Props BigQuery Load Errors",
                        message=f"Encountered {len(load_job.errors)} errors loading props data",
                        details={
                            'processor': 'OddsApiPropsProcessor',
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'error_count': len(load_job.errors),
                            'errors': str(load_job.errors)[:500]
                        },
                        processor_name="Odds API Props Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

                return {'rows_processed': 0, 'errors': errors}

            logger.info(f"✅ Batch loaded {len(rows)} prop records (no streaming buffer)")

            # Success - send info notification
            try:
                notify_info(
                    title="Props Processing Complete",
                    message=f"Successfully processed {len(rows)} prop records using batch loading",
                    details={
                        'processor': 'OddsApiPropsProcessor',
                        'rows_processed': len(rows),
                        'table': self.table_name,
                        'strategy': 'batch_append',
                        'data_source': rows[0].get('data_source') if rows else None
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
                
            # Warn about unknown teams if any were found
            if self.unknown_teams:
                try:
                    notify_warning(
                        title="Unknown Team Names Detected",
                        message=f"Found {len(self.unknown_teams)} unknown team names in props data",
                        details={
                            'processor': 'OddsApiPropsProcessor',
                            'unknown_teams': list(self.unknown_teams)
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': len(rows), 'errors': []}
                    
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            
            # Check for streaming buffer error (shouldn't happen with batch loading, but handle gracefully)
            if "streaming buffer" in error_msg.lower():
                logger.warning(
                    f"Unexpected streaming buffer issue - {len(rows)} records skipped. "
                    f"Records will be processed on next run."
                )
                
                try:
                    notify_warning(
                        title="Props Skipped - Streaming Buffer",
                        message=f"Unexpected streaming buffer conflict, {len(rows)} records skipped",
                        details={
                            'processor': 'OddsApiPropsProcessor',
                            'table': self.table_name,
                            'rows_skipped': len(rows),
                            'note': 'Should not happen with batch loading - investigate'
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {'rows_processed': 0, 'errors': [], 'skipped_streaming_buffer': True}
            else:
                # Real error
                logger.error(f"Failed to insert rows: {e}", exc_info=True)
                
                try:
                    notify_error(
                        title="Props BigQuery Insert Exception",
                        message=f"Critical failure inserting props data: {str(e)}",
                        details={
                            'processor': 'OddsApiPropsProcessor',
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'error_type': type(e).__name__,
                            'error_message': str(e)
                        },
                        processor_name="Odds API Props Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {'rows_processed': 0, 'errors': errors}