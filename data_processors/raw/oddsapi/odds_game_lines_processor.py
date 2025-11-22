#!/usr/bin/env python3
# File: processors/odds_api/odds_game_lines_processor.py
# Description: Unified processor for Odds API game lines (current and historical)

import json, logging, re, os, uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
import pytz
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class OddsGameLinesProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process Odds API game lines data.

    Handles both:
    - Current/live data: odds-api/game-lines/2025-10-21/...
    - Historical data: odds-api/game-lines-history/2023-10-24/...

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: game_id, game_date, bookmaker_key, market_key, outcome_name, outcome_point, snapshot_timestamp
        Expected Skip Rate: 50% when lines unchanged
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'game_id',
        'game_date',
        'bookmaker_key',
        'market_key',
        'outcome_name',
        'outcome_point',
        'snapshot_timestamp'
    ]

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
            if 'game-lines-history' in file_path or '/historical/' in file_path:
                return 'historical'
            elif 'game-lines' in file_path or '/current/' in file_path:
                return 'current'
        
        # Default to 'current' for live data
        return 'current'
    
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
    
    def validate_data(self, data: Dict, is_historical: bool) -> List[str]:
        """Validate required fields in the odds data."""
        errors = []
        
        # Get the game data (either wrapped or unwrapped)
        if is_historical:
            if 'timestamp' not in data:
                errors.append("Missing timestamp in historical format")
            
            if 'data' not in data:
                errors.append("Missing data section in historical format")
                return errors
            
            game_data = data['data']
        else:
            # Current format - data is the game object itself
            game_data = data
        
        required_fields = ['id', 'commence_time', 'home_team', 'away_team', 'bookmakers']
        
        for field in required_fields:
            if field not in game_data:
                errors.append(f"Missing required field in game data: {field}")
        
        if 'bookmakers' in game_data and not isinstance(game_data['bookmakers'], list):
            errors.append("Bookmakers must be an array")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform nested odds data into flat rows for BigQuery."""
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
                        title="Game Lines Data Validation Errors",
                        message=f"Validation errors found in odds API game lines data: {', '.join(errors[:3])}",
                        details={
                            'processor': 'OddsGameLinesProcessor',
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
            
            now = datetime.now(timezone.utc).isoformat()
            
            # Parse timestamps based on format
            if is_historical:
                snapshot_timestamp = self.parse_timestamp(raw_data.get('timestamp'))
                previous_timestamp = self.parse_timestamp(raw_data.get('previous_timestamp'))
                next_timestamp = self.parse_timestamp(raw_data.get('next_timestamp'))
                game_data = raw_data['data']
            else:
                # For current data, use the most recent market update time as snapshot
                # This represents when the odds data was last updated
                game_data = raw_data
                
                # Find the most recent update time from bookmakers/markets
                latest_update = None
                for bookmaker in game_data.get('bookmakers', []):
                    bm_update = bookmaker.get('last_update')
                    if bm_update:
                        bm_ts = self.parse_timestamp(bm_update)
                        if not latest_update or (bm_ts and bm_ts > latest_update):
                            latest_update = bm_ts
                    
                    for market in bookmaker.get('markets', []):
                        mk_update = market.get('last_update')
                        if mk_update:
                            mk_ts = self.parse_timestamp(mk_update)
                            if not latest_update or (mk_ts and mk_ts > latest_update):
                                latest_update = mk_ts
                
                # Use latest update as snapshot timestamp, or current time as fallback
                snapshot_timestamp = latest_update if latest_update else datetime.now(timezone.utc).isoformat()
                previous_timestamp = None
                next_timestamp = None
                
                logger.debug(f"Current data: using snapshot_timestamp = {snapshot_timestamp}")
            
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
                            'format': 'historical' if is_historical else 'current',
                            'data_source': data_source,
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
                self.transformed_data = rows
            
            # Get team abbreviations
            home_team_abbr = self.get_team_abbreviation(home_team)
            away_team_abbr = self.get_team_abbreviation(away_team)
            
            # Process each bookmaker
            for bookmaker in game_data.get('bookmakers', []):
                bookmaker_key = bookmaker.get('key', '')
                bookmaker_title = bookmaker.get('title', '')
                
                # For current data, bookmaker might not have last_update
                # Use first market's last_update as fallback
                bookmaker_last_update = self.parse_timestamp(bookmaker.get('last_update'))
                if not bookmaker_last_update and bookmaker.get('markets'):
                    # Use first market's update time as bookmaker update time
                    first_market = bookmaker['markets'][0]
                    bookmaker_last_update = self.parse_timestamp(first_market.get('last_update'))
                
                # Final fallback to snapshot timestamp if still None
                if not bookmaker_last_update:
                    bookmaker_last_update = snapshot_timestamp
                
                # Process each market (spreads, totals, etc.)
                for market in bookmaker.get('markets', []):
                    market_key = market.get('key', '')
                    market_last_update = self.parse_timestamp(market.get('last_update'))
                    
                    # Market last_update should exist, but use bookmaker's as fallback
                    if not market_last_update:
                        market_last_update = bookmaker_last_update
                    
                    # Process each outcome
                    for outcome in market.get('outcomes', []):
                        row = {
                            # Snapshot metadata (may be None for current data)
                            'snapshot_timestamp': snapshot_timestamp,
                            'previous_snapshot_timestamp': previous_timestamp,
                            'next_snapshot_timestamp': next_timestamp,
                            
                            # Game identifiers
                            'game_id': game_id,
                            'sport_key': sport_key,
                            'sport_title': sport_title,
                            'commence_time': commence_time,
                            'game_date': game_date,  # Correctly extracted in Eastern timezone
                            
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
                            'data_source': data_source,  # NEW: Track data source
                            'created_at': now,
                            'processed_at': now
                        }
                        rows.append(row)
            
            # Log successful transformation with game date info
            if rows:
                logger.info(
                    f"Transformed {len(rows)} rows for game {game_id} "
                    f"({away_team_abbr}@{home_team_abbr}) on {game_date} "
                    f"(commence_time: {game_data['commence_time']}) "
                    f"[data_source={data_source}, format={'historical' if is_historical else 'current'}]"
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

        self.transformed_data = rows

        # Smart Idempotency: Add data_hash to all records
        self.add_data_hash()

    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """
        Load data using staging table + MERGE approach (no streaming buffer).
        
        This avoids BigQuery's streaming buffer limitations by using batch loading
        and MERGE operations instead of DELETE + streaming insert.
        """
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        temp_table_id = None
        errors = []
        
        try:
            # Get metadata from first row
            game_id = rows[0]['game_id']
            snapshot_timestamp = rows[0]['snapshot_timestamp']
            game_date = rows[0]['game_date']
            away_team_abbr = rows[0]['away_team_abbr']
            home_team_abbr = rows[0]['home_team_abbr']
            data_source = rows[0].get('data_source', 'unknown')
            
            # 1. Create temporary table with unique name
            temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
            
            # Get target table schema
            target_table = self.bq_client.get_table(table_id)
            
            # Create temp table with same schema
            temp_table = bigquery.Table(temp_table_id, schema=target_table.schema)
            self.bq_client.create_table(temp_table)
            logger.info(f"Created temporary table: {temp_table_id}")
            
            # 2. Batch load to temp table (NO streaming buffer!)
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,  # Enforce exact schema
                autodetect=False,            # Don't infer schema
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
            )
            
            load_job = self.bq_client.load_table_from_json(
                rows, 
                temp_table_id, 
                job_config=job_config
            )
            load_job.result()  # Wait for completion
            
            logger.info(f"✅ Batch loaded {len(rows)} rows to temp table (no streaming buffer)")
            
            # 3. MERGE from temp to target (works immediately with batch loading!)
            merge_query = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON target.game_date = '{game_date}'
            AND target.game_id = source.game_id 
            AND COALESCE(target.snapshot_timestamp, TIMESTAMP('1970-01-01')) = COALESCE(source.snapshot_timestamp, TIMESTAMP('1970-01-01'))
            AND target.bookmaker_key = source.bookmaker_key
            AND target.market_key = source.market_key
            AND target.outcome_name = source.outcome_name
            AND target.game_date = source.game_date
            WHEN MATCHED THEN
                UPDATE SET
                    snapshot_timestamp = source.snapshot_timestamp,
                    previous_snapshot_timestamp = source.previous_snapshot_timestamp,
                    next_snapshot_timestamp = source.next_snapshot_timestamp,
                    sport_key = source.sport_key,
                    sport_title = source.sport_title,
                    commence_time = source.commence_time,
                    game_date = source.game_date,
                    home_team = source.home_team,
                    away_team = source.away_team,
                    home_team_abbr = source.home_team_abbr,
                    away_team_abbr = source.away_team_abbr,
                    bookmaker_title = source.bookmaker_title,
                    bookmaker_last_update = source.bookmaker_last_update,
                    market_last_update = source.market_last_update,
                    outcome_price = source.outcome_price,
                    outcome_point = source.outcome_point,
                    data_source = source.data_source,
                    processed_at = source.processed_at
            WHEN NOT MATCHED THEN
                INSERT (
                    snapshot_timestamp,
                    previous_snapshot_timestamp,
                    next_snapshot_timestamp,
                    game_id,
                    sport_key,
                    sport_title,
                    commence_time,
                    game_date,
                    home_team,
                    away_team,
                    home_team_abbr,
                    away_team_abbr,
                    bookmaker_key,
                    bookmaker_title,
                    bookmaker_last_update,
                    market_key,
                    market_last_update,
                    outcome_name,
                    outcome_price,
                    outcome_point,
                    source_file_path,
                    data_source,
                    created_at,
                    processed_at
                )
                VALUES (
                    source.snapshot_timestamp,
                    source.previous_snapshot_timestamp,
                    source.next_snapshot_timestamp,
                    source.game_id,
                    source.sport_key,
                    source.sport_title,
                    source.commence_time,
                    source.game_date,
                    source.home_team,
                    source.away_team,
                    source.home_team_abbr,
                    source.away_team_abbr,
                    source.bookmaker_key,
                    source.bookmaker_title,
                    source.bookmaker_last_update,
                    source.market_key,
                    source.market_last_update,
                    source.outcome_name,
                    source.outcome_price,
                    source.outcome_point,
                    source.source_file_path,
                    source.data_source,
                    source.created_at,
                    source.processed_at
                )
            """
            
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            
            # Get number of rows affected
            rows_affected = merge_result.total_rows if hasattr(merge_result, 'total_rows') else len(rows)
            
            logger.info(
                f"✅ MERGE completed successfully: {rows_affected} rows affected for game {game_id} "
                f"({away_team_abbr}@{home_team_abbr}) on {game_date} [data_source={data_source}]"
            )
            
            # Success notification
            try:
                notify_info(
                    title="Game Lines Processing Complete",
                    message=f"Successfully processed {len(rows)} game line records using staging table",
                    details={
                        'processor': 'OddsGameLinesProcessor',
                        'rows_processed': len(rows),
                        'rows_affected': rows_affected,
                        'table': self.table_name,
                        'strategy': 'staging_table_merge',
                        'game_id': game_id,
                        'game_date': game_date,
                        'teams': f"{away_team_abbr}@{home_team_abbr}",
                        'data_source': data_source
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
            
            return {'rows_processed': len(rows), 'errors': []}
            
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            
            # Check for streaming buffer error (graceful failure)
            if "streaming buffer" in error_msg.lower():
                logger.warning(
                    f"MERGE blocked by streaming buffer - {len(rows)} records skipped this run. "
                    f"Records will be processed on next run when buffer clears."
                )
                
                try:
                    notify_warning(
                        title="Game Lines Skipped - Streaming Buffer",
                        message=f"MERGE blocked by streaming buffer, {len(rows)} records skipped (will retry next run)",
                        details={
                            'processor': 'OddsGameLinesProcessor',
                            'table': self.table_name,
                            'game_id': rows[0]['game_id'] if rows else 'unknown',
                            'game_date': rows[0]['game_date'] if rows else 'unknown',
                            'rows_skipped': len(rows),
                            'note': 'System will self-heal on next run'
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {'rows_processed': 0, 'errors': [], 'skipped_streaming_buffer': True}
            else:
                # Non-streaming-buffer error - this is a real problem
                logger.error(f"Failed to load data: {e}", exc_info=True)
                
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
                
                return {'rows_processed': 0, 'errors': errors}
        
        finally:
            # Always cleanup temporary table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.debug(f"Cleaned up temporary table: {temp_table_id}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp table: {cleanup_error}")