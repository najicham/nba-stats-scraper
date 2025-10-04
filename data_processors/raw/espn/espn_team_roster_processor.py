#!/usr/bin/env python3
# File: data_processors/raw/espn/espn_team_roster_processor.py
# Description: Processor for ESPN team roster API data transformation
# Updated: 2025-10-04 - Fixed to follow ProcessorBase pattern with staging table MERGE

import json
import logging
import re
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone, date, timedelta
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class EspnTeamRosterProcessor(ProcessorBase):
    """Process ESPN team roster API data following ProcessorBase pattern."""
    
    # Configure for ProcessorBase
    required_opts = ['bucket', 'file_path']
    
    def __init__(self):
        super().__init__()
        self.table_name = 'espn_team_rosters'
        self.dataset_id = 'nba_raw'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        
        # Tracking
        self.players_processed = 0
        self.players_skipped = 0
    
    # ================================================================
    # STEP 1: LOAD DATA FROM GCS
    # ================================================================
    def load_data(self) -> None:
        """Load JSON data from GCS (implements ProcessorBase interface)."""
        self.raw_data = self.load_json_from_gcs()
    
    # ================================================================
    # STEP 2: VALIDATE LOADED DATA
    # ================================================================
    def validate_loaded_data(self) -> None:
        """Validate ESPN roster data structure."""
        if not self.raw_data:
            raise ValueError("No data loaded")
        
        errors = []
        
        if not isinstance(self.raw_data, dict):
            errors.append("Data is not a dictionary")
        
        if 'players' not in self.raw_data:
            errors.append("Missing 'players' field in data")
        
        if 'team_abbr' not in self.raw_data:
            errors.append("Missing 'team_abbr' field in data")
        
        if errors:
            error_msg = "; ".join(errors)
            logger.error(f"Validation failed: {error_msg}")
            raise ValueError(error_msg)
        
        logger.info(f"Validation passed for {self.raw_data.get('team_abbr')} roster")
    
    # ================================================================
    # STEP 3: TRANSFORM DATA
    # ================================================================
    def transform_data(self) -> None:
        """Transform ESPN roster data to BigQuery rows (implements ProcessorBase interface)."""
        rows = []
        file_path = self.opts.get('file_path', 'unknown')
        
        try:
            # Extract metadata from file path
            roster_date = self._extract_date_from_path(file_path)
            source_file_date = roster_date  # Same as roster_date for ESPN
            season_year = self._extract_season_year(roster_date)
            scrape_hour = self._extract_scrape_hour(file_path)
            
            # Extract top-level team information
            team_abbr = self.raw_data.get('team_abbr', '')
            team_display_name = self.raw_data.get('teamName', '')
            espn_team_id = self.raw_data.get('espn_team_id')
            players_data = self.raw_data.get('players', [])
            
            if not team_abbr:
                raise ValueError(f"Missing team_abbr in {file_path}")
            
            total_players = len(players_data)
            self.players_processed = 0
            self.players_skipped = 0
            
            # Process each player
            for player_data in players_data:
                if not isinstance(player_data, dict):
                    self.players_skipped += 1
                    continue
                
                # Extract player ID - required field
                espn_player_id = player_data.get('playerId')
                if not espn_player_id:
                    self.players_skipped += 1
                    logger.debug(f"Skipping player without playerId in {team_abbr} roster")
                    continue
                
                # Extract player name - required field
                full_name = player_data.get('fullName', '')
                if not full_name:
                    self.players_skipped += 1
                    logger.debug(f"Skipping player {espn_player_id} without fullName in {team_abbr} roster")
                    continue
                
                # Generate normalized lookup name
                player_lookup = self._normalize_player_name(full_name)
                
                # Extract player details
                jersey_number = player_data.get('jersey')
                if jersey_number is not None:
                    jersey_number = str(jersey_number)
                
                position_name = player_data.get('position', '')
                
                # Convert height and weight to display format
                height = self._convert_height_to_display(player_data.get('heightIn'))
                weight = self._convert_weight_to_display(player_data.get('weightLb'))
                
                # Determine player status from injuries
                injuries = player_data.get('injuries', [])
                status = self._determine_player_status(injuries)
                
                # Build the row
                row = {
                    'roster_date': roster_date.isoformat(),
                    'scrape_hour': scrape_hour,
                    'season_year': season_year,
                    'team_abbr': team_abbr,
                    'team_display_name': team_display_name,
                    'espn_player_id': int(espn_player_id),
                    'player_full_name': full_name,
                    'player_lookup': player_lookup,
                    'jersey_number': jersey_number,
                    'position': position_name if position_name else None,
                    'position_abbr': position_name if position_name else None,
                    'height': height,
                    'weight': weight,
                    'age': None,
                    'experience_years': None,
                    'college': None,
                    'birth_place': None,
                    'birth_date': None,
                    'status': status,
                    'roster_status': 'Active Roster',
                    'salary': None,
                    'espn_roster_url': None,
                    'source_file_path': file_path,
                    'source_file_date': source_file_date.isoformat(),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                rows.append(row)
                self.players_processed += 1
            
            # Data quality checks
            if len(rows) < 5:
                logger.warning(f"Low player count for {team_abbr}: {len(rows)} players")
            
            if total_players > 0 and self.players_skipped >= total_players * 0.3:
                logger.warning(f"High skip rate for {team_abbr}: {self.players_skipped}/{total_players}")
            
            # Store transformed data
            self.transformed_data = rows
            logger.info(f"Transformed {len(rows)} players from {team_abbr} roster (skipped {self.players_skipped})")
            
        except Exception as e:
            logger.error(f"Error transforming ESPN roster data from {file_path}: {str(e)}")
            raise
    
    # ================================================================
    # STEP 4: SAVE DATA (OVERRIDE WITH STAGING TABLE MERGE)
    # ================================================================
    def save_data(self) -> None:
        """Save using staging table MERGE to avoid streaming buffer issues."""
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
        
        rows = self.transformed_data if isinstance(self.transformed_data, list) else [self.transformed_data]
        
        if not rows:
            logger.warning("No rows to save")
            return
        
        logger.info(f"Using staging table MERGE for {len(rows)} rows")
        
        # Use staging table MERGE
        self._merge_via_staging_table(
            rows=rows,
            merge_keys=['roster_date', 'scrape_hour', 'team_abbr', 'espn_player_id']
        )
        
        self.stats["rows_inserted"] = len(rows)
        logger.info(f"Successfully merged {len(rows)} rows for {rows[0].get('team_abbr')}")
    
    def _merge_via_staging_table(self, rows: List[Dict], merge_keys: List[str]) -> None:
        """
        MERGE records using staging table approach (avoids streaming buffer issues).
        
        Pattern from nbac_player_list_processor - prevents DELETE errors on streaming buffer.
        
        Args:
            rows: List of record dictionaries
            merge_keys: Keys to match on for MERGE
        """
        if not rows:
            return
        
        project_id = self.bq_client.project
        table_id = f"{project_id}.{self.dataset_id}.{self.table_name}"
        staging_table_name = f"{self.table_name}_staging_{self.run_id}"
        staging_table_id = f"{project_id}.{self.dataset_id}.{staging_table_name}"
        
        try:
            # 1. Create staging table
            logger.debug(f"Creating staging table: {staging_table_id}")
            
            # Get main table schema
            main_table = self.bq_client.get_table(table_id)
            
            # Create staging table with same schema and 30 min expiration
            staging_table = bigquery.Table(staging_table_id, schema=main_table.schema)
            staging_table.expires = datetime.utcnow() + timedelta(minutes=30)
            self.bq_client.create_table(staging_table)
            
            # 2. Load data to staging table
            logger.debug(f"Loading {len(rows)} rows to staging table")
            
            # Convert types for JSON loading
            processed_rows = []
            for row in rows:
                converted = self._convert_for_json_load(row)
                processed_rows.append(converted)
            
            job_config = bigquery.LoadJobConfig(
                schema=main_table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
            )
            
            load_job = self.bq_client.load_table_from_json(
                processed_rows,
                staging_table_id,
                job_config=job_config
            )
            load_job.result()  # Wait for completion
            
            # 3. Execute MERGE from staging to main
            logger.debug("Executing MERGE from staging to main table")
            
            # Build ON clause
            on_conditions = " AND ".join([f"T.{key} = S.{key}" for key in merge_keys])
            
            # Build UPDATE SET clause (all fields except merge keys)
            all_fields = [field.name for field in main_table.schema]
            update_fields = [f for f in all_fields if f not in merge_keys]
            update_set = ", ".join([f"{field} = S.{field}" for field in update_fields])
            
            # Build INSERT clause
            insert_fields = ", ".join(all_fields)
            insert_values = ", ".join([f"S.{field}" for field in all_fields])
            
            merge_query = f"""
            MERGE `{table_id}` T
            USING `{staging_table_id}` S
            ON {on_conditions}
            WHEN MATCHED THEN
                UPDATE SET {update_set}
            WHEN NOT MATCHED THEN
                INSERT ({insert_fields})
                VALUES ({insert_values})
            """
            
            merge_job = self.bq_client.query(merge_query)
            merge_job.result()  # Wait for completion
            
            logger.info(f"MERGE completed for {rows[0].get('team_abbr')}")
            
        except Exception as e:
            logger.error(f"MERGE operation failed: {e}")
            raise
            
        finally:
            # Cleanup staging table
            try:
                self.bq_client.delete_table(staging_table_id, not_found_ok=True)
                logger.debug(f"Cleaned up staging table: {staging_table_id}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup staging table: {cleanup_error}")
    
    def _convert_for_json_load(self, record: Dict) -> Dict:
        """Convert record types for JSON loading (handles pandas types, dates, timestamps)."""
        import pandas as pd
        
        converted = {}
        
        timestamp_fields = {'processed_at', 'created_at', 'updated_at', 'last_roster_update'}
        date_fields = {'roster_date', 'birth_date', 'source_file_date'}
        
        for key, value in record.items():
            # Handle lists first
            if isinstance(value, list):
                converted[key] = value
                continue
            
            # Check for None/NaN on scalar values only
            if pd.isna(value):
                converted[key] = None
                continue
            
            # TIMESTAMP fields - convert to ISO strings
            if key in timestamp_fields:
                if isinstance(value, (datetime, pd.Timestamp)):
                    converted[key] = value.isoformat()
                elif isinstance(value, str):
                    converted[key] = value
                else:
                    converted[key] = None
            
            # DATE fields - convert to ISO date strings
            elif key in date_fields:
                if isinstance(value, (date, datetime)):
                    converted[key] = value.isoformat()
                elif isinstance(value, str):
                    converted[key] = value
                else:
                    converted[key] = None
            
            # Other types pass through
            else:
                converted[key] = value
        
        return converted
    
    # ================================================================
    # HELPER METHODS
    # ================================================================
    def _normalize_player_name(self, name: str) -> str:
        """Normalize player name for consistent lookup."""
        if not name:
            return ""
        
        normalized = name.lower().strip()
        
        # Remove common suffixes
        suffixes = [' jr.', ' jr', ' sr.', ' sr', ' ii', ' iii', ' iv', ' v']
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        return normalized
    
    def _extract_date_from_path(self, file_path: str) -> date:
        """Extract date from GCS file path."""
        parts = file_path.split('/')
        for part in parts:
            if len(part) == 10 and part.count('-') == 2:
                try:
                    return datetime.strptime(part, '%Y-%m-%d').date()
                except ValueError:
                    continue
        
        logger.warning(f"Could not extract date from path: {file_path}, using today's date")
        return date.today()
    
    def _extract_season_year(self, roster_date: date) -> int:
        """Calculate NBA season year from roster date."""
        if roster_date.month >= 10:
            return roster_date.year
        else:
            return roster_date.year - 1
    
    def _extract_scrape_hour(self, file_path: str) -> int:
        """Extract scrape hour from file path (defaults to 8 for morning operations)."""
        return 8
    
    def _determine_player_status(self, injuries: List[Dict]) -> str:
        """Determine player status from injuries array."""
        if not injuries or len(injuries) == 0:
            return 'Active'
        
        recent_injury = injuries[0]
        injury_status = recent_injury.get('status', '')
        
        if injury_status:
            return injury_status
        
        injury_type = recent_injury.get('type', {})
        if isinstance(injury_type, dict):
            type_name = injury_type.get('name', '')
            if 'OUT' in type_name.upper():
                return 'Out'
        
        return 'Day-To-Day'
    
    def _convert_height_to_display(self, height_inches: Optional[int]) -> Optional[str]:
        """Convert height in inches to display format like '6' 9"'."""
        if height_inches is None or not isinstance(height_inches, (int, float)):
            return None
        
        try:
            height_in = int(height_inches)
            feet = height_in // 12
            inches = height_in % 12
            return f"{feet}' {inches}\""
        except (TypeError, ValueError):
            return None
    
    def _convert_weight_to_display(self, weight_pounds: Optional[float]) -> Optional[str]:
        """Convert weight in pounds to display format like '250 lbs'."""
        if weight_pounds is None or not isinstance(weight_pounds, (int, float)):
            return None
        
        try:
            return f"{int(weight_pounds)} lbs"
        except (TypeError, ValueError):
            return None
    
    def get_processor_stats(self) -> Dict:
        """Return processor statistics."""
        return {
            'players_processed': self.players_processed,
            'players_skipped': self.players_skipped,
            'rows_transformed': len(self.transformed_data) if isinstance(self.transformed_data, list) else 0
        }


# CLI entry point
if __name__ == "__main__":
    import argparse
    from google.cloud import storage
    
    parser = argparse.ArgumentParser(description="Process ESPN team roster data")
    parser.add_argument("--bucket", default="nba-scraped-data", help="GCS bucket name")
    parser.add_argument("--date", required=True, help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--team", help="Process specific team only (e.g., LAL)")
    parser.add_argument("--project-id", default="nba-props-platform", help="GCP project ID")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Initialize storage client for file discovery
    storage_client = storage.Client(project=args.project_id)
    bucket_obj = storage_client.bucket(args.bucket)
    
    # Build prefix for file discovery
    prefix = f"espn/rosters/{args.date}/"
    if args.team:
        prefix += f"team_{args.team}/"
    
    logger.info(f"Discovering files in gs://{args.bucket}/{prefix}")
    
    # Discover files
    blobs = list(bucket_obj.list_blobs(prefix=prefix))
    json_files = [b for b in blobs if b.name.endswith('.json')]
    
    if not json_files:
        logger.error(f"No JSON files found in gs://{args.bucket}/{prefix}")
        exit(1)
    
    logger.info(f"Found {len(json_files)} files to process")
    
    # Process each file using ProcessorBase.run() pattern
    total_processed = 0
    total_errors = 0
    teams_processed = []
    failed_teams = []
    
    for blob in json_files:
        try:
            logger.info(f"\nProcessing {blob.name}...")
            
            # Create processor instance for this file
            processor = EspnTeamRosterProcessor()
            
            # Build opts for this specific file
            opts = {
                'bucket': args.bucket,
                'file_path': blob.name,
                'project_id': args.project_id
            }
            
            # Run processor (load → validate → transform → save)
            success = processor.run(opts)
            
            if success:
                stats = processor.get_processor_stats()
                team_abbr = processor.transformed_data[0].get('team_abbr') if processor.transformed_data else 'unknown'
                logger.info(f"  ✓ {team_abbr}: {stats['players_processed']} players processed")
                total_processed += stats['players_processed']
                teams_processed.append(team_abbr)
            else:
                team_abbr = 'unknown'
                try:
                    if processor.raw_data and 'team_abbr' in processor.raw_data:
                        team_abbr = processor.raw_data['team_abbr']
                except:
                    pass
                logger.error(f"  ✗ Failed to process {team_abbr}")
                failed_teams.append(team_abbr)
                total_errors += 1
                
        except Exception as e:
            logger.error(f"  ✗ Exception processing {blob.name}: {e}")
            total_errors += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"{'✅ COMPLETE' if total_errors == 0 else '⚠️  COMPLETE WITH ERRORS'}")
    print(f"{'='*60}")
    print(f"Date: {args.date}")
    print(f"Files processed: {len(json_files)}")
    print(f"Teams succeeded: {len(teams_processed)} {sorted(teams_processed)}")
    if failed_teams:
        print(f"Teams failed: {len(failed_teams)} {sorted(failed_teams)}")
    print(f"Total players loaded: {total_processed}")
    print(f"Errors: {total_errors}")
    print(f"{'='*60}")
    
    # Verify in BigQuery
    if total_processed > 0 and not args.debug:
        logger.info("\nVerifying data in BigQuery...")
        from google.cloud import bigquery
        bq_client = bigquery.Client(project=args.project_id)
        
        verify_query = f"""
        SELECT 
            COUNT(*) as total_records,
            COUNT(DISTINCT team_abbr) as teams,
            COUNT(DISTINCT player_lookup) as unique_players
        FROM `{args.project_id}.nba_raw.espn_team_rosters`
        WHERE roster_date = '{args.date}'
        """
        
        try:
            verify_result = bq_client.query(verify_query).to_dataframe()
            if not verify_result.empty:
                print(f"\nBigQuery verification:")
                print(f"  Records: {verify_result.iloc[0]['total_records']}")
                print(f"  Teams: {verify_result.iloc[0]['teams']}")
                print(f"  Unique players: {verify_result.iloc[0]['unique_players']}")
        except Exception as e:
            logger.warning(f"Verification query failed: {e}")