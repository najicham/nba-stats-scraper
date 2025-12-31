"""
processors/basketball_ref/br_roster_processor.py
Basketball Reference Roster Processor
Processes roster JSON files from GCS and loads to BigQuery.
Matches the scraper patterns and naming conventions.
"""

import json
import logging
from datetime import date, datetime
from typing import Dict, List, Optional
from google.cloud import bigquery

# Import from parent directory
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processor_base import ProcessorBase
from utils.name_utils import normalize_name
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Notification imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class BasketballRefRosterProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process Basketball Reference roster files.
    Implements MERGE_UPDATE strategy with first_seen_date tracking and smart idempotency.
    """

    # Smart idempotency: Hash meaningful roster fields only
    HASH_FIELDS = [
        'season_year',
        'team_abbrev',
        'player_full_name',
        'position',
        'jersey_number',
        'height',
        'weight',
        'birth_date',
        'college',
        'experience_years'
    ]

    # Configuration
    required_opts = ["season_year", "team_abbrev", "file_path"]
    dataset_id = "nba_raw"

    def __init__(self):
        super().__init__()
        self.table_name = "br_rosters_current"
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
    
    def set_additional_opts(self) -> None:
        """Add season display format."""
        super().set_additional_opts()
        
        # Convert season_year to display format
        year = int(self.opts["season_year"])
        self.opts["season_display"] = f"{year}-{str(year + 1)[2:]}"
        
    def load_data(self) -> None:
        """Load roster JSON from GCS."""
        bucket_name = self.opts.get("bucket", "nba-scraped-data")
        file_path = self.opts["file_path"]
        
        self.step_info("load", f"Loading from gs://{bucket_name}/{file_path}")
        
        bucket = self.gcs_client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        
        if not blob.exists():
            error_msg = f"File not found: gs://{bucket_name}/{file_path}"
            
            # Notify critical error
            try:
                notify_error(
                    title="Basketball Reference Roster File Not Found",
                    message=f"Could not find roster file in GCS: {file_path}",
                    details={
                        'bucket': bucket_name,
                        'file_path': file_path,
                        'team_abbrev': self.opts.get('team_abbrev'),
                        'season_year': self.opts.get('season_year')
                    },
                    processor_name="Basketball Reference Roster Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise FileNotFoundError(error_msg)
        
        try:
            content = blob.download_as_text()
            self.raw_data = json.loads(content)
            logger.info(f"Loaded {len(self.raw_data.get('players', []))} players")
        except json.JSONDecodeError as e:
            # Notify JSON parse error
            try:
                notify_error(
                    title="Basketball Reference Roster JSON Parse Failed",
                    message=f"Failed to parse roster JSON: {str(e)}",
                    details={
                        'file_path': file_path,
                        'team_abbrev': self.opts.get('team_abbrev'),
                        'season_year': self.opts.get('season_year'),
                        'error_type': type(e).__name__
                    },
                    processor_name="Basketball Reference Roster Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def validate_loaded_data(self) -> None:
        """Validate roster data structure."""
        super().validate_loaded_data()
        
        errors = []
        warnings = []
        
        # Check required fields
        if "players" not in self.raw_data:
            errors.append("Missing 'players' field")
        if "team_abbrev" not in self.raw_data:
            errors.append("Missing 'team_abbrev' field")
        if "season" not in self.raw_data:
            errors.append("Missing 'season' field")
        
        # Check roster size
        players = self.raw_data.get("players", [])
        if len(players) < 10:
            warnings.append(f"Suspicious roster size: {len(players)} players")
        
        # Check for duplicate players
        names = [p.get("full_name") for p in players if p.get("full_name")]
        if len(names) != len(set(names)):
            warnings.append("Duplicate player names found")
        
        # Handle warnings
        if warnings:
            for warning in warnings:
                logger.warning(f"Validation warning: {warning}")
            
            # Notify data quality issues
            try:
                notify_warning(
                    title="Basketball Reference Roster Data Quality Issues",
                    message=f"Data quality issues detected: {', '.join(warnings)}",
                    details={
                        'team_abbrev': self.opts.get('team_abbrev'),
                        'season_year': self.opts.get('season_year'),
                        'player_count': len(players),
                        'issues': warnings
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
        
        # Handle critical errors
        if errors:
            for error in errors:
                logger.error(f"Validation error: {error}")
            
            # Notify validation failure
            try:
                notify_error(
                    title="Basketball Reference Roster Validation Failed",
                    message=f"Required fields missing: {', '.join(errors)}",
                    details={
                        'file_path': self.opts.get('file_path'),
                        'team_abbrev': self.opts.get('team_abbrev'),
                        'season_year': self.opts.get('season_year'),
                        'errors': errors
                    },
                    processor_name="Basketball Reference Roster Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(f"Validation failed: {'; '.join(errors)}")
    
    def transform_data(self) -> None:
        """
        Transform roster data for BigQuery with MERGE_UPDATE strategy.
        Matches the scraper's transform_data() pattern.
        """
        team_abbrev = self.raw_data["team_abbrev"]
        season_year = int(self.opts["season_year"])
        season_display = self.opts["season_display"]
        
        # Get existing roster for merge logic
        existing_players = self._get_existing_roster(season_year, team_abbrev)
        existing_lookups = {p["player_lookup"] for p in existing_players}
        
        rows = []
        new_players = []
        skipped_count = 0
        
        for player in self.raw_data.get("players", []):
            if not player.get("full_name"):
                logger.warning(f"Skipping player without name: {player}")
                skipped_count += 1
                continue
            
            # Transform player data (matching scraper patterns)
            row = {
                "season_year": season_year,
                "season_display": season_display,
                "team_abbrev": team_abbrev,
                
                # Player identity
                "player_full_name": player.get("full_name"),
                "player_last_name": player.get("last_name", ""),
                "player_normalized": player.get("normalized", ""),
                "player_lookup": normalize_name(player.get("full_name", "")),
                
                # Player details (keep as strings like scraper)
                "position": player.get("position"),
                "jersey_number": player.get("jersey_number"),
                "height": player.get("height"),
                "weight": player.get("weight"),
                "birth_date": player.get("birth_date"),
                "college": player.get("college"),
                
                # Parse experience
                "experience_years": self._parse_experience(player.get("experience")),
                
                # Tracking
                "last_scraped_date": date.today().isoformat(),
                "source_file_path": self.opts["file_path"],
                "processed_at": datetime.utcnow().isoformat(),
            }
            
            # Check if new player (for first_seen_date)
            if row["player_lookup"] not in existing_lookups:
                row["first_seen_date"] = date.today().isoformat()
                new_players.append(player.get("full_name"))
                logger.info(f"New player on {team_abbrev}: {player.get('full_name')}")
            
            rows.append(row)

        self.transformed_data = rows

        # Add smart idempotency hash to each row
        self.add_data_hash()

        self.stats["new_players"] = len(new_players)
        self.stats["total_players"] = len(rows)
        self.stats["skipped_players"] = skipped_count
        
        # Notify if players were skipped
        if skipped_count > 0:
            try:
                notify_warning(
                    title="Basketball Reference Roster Players Skipped",
                    message=f"Skipped {skipped_count} players without names",
                    details={
                        'team_abbrev': team_abbrev,
                        'season_year': season_year,
                        'skipped_count': skipped_count,
                        'total_players': len(rows)
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
    
    def save_data(self) -> None:
        """
        Override to implement MERGE_UPDATE strategy.
        Updates existing players, inserts new ones.
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
        
        table_id = f"{self.bq_client.project}.{self.dataset_id}.{self.table_name}"
        
        try:
            # Separate new vs existing players
            new_rows = [r for r in self.transformed_data if "first_seen_date" in r]
            update_rows = [r for r in self.transformed_data if "first_seen_date" not in r]
            
            # Insert new players using batch loading (not streaming insert)
            # This avoids the 20 DML limit and streaming buffer issues
            if new_rows:
                logger.info(f"Loading {len(new_rows)} new players using batch load")

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
                    new_rows,
                    table_id,
                    job_config=job_config
                )

                # Wait for completion
                load_job.result()
                logger.info(f"Successfully loaded {len(new_rows)} new players")
            
            # Update existing players (just update last_scraped_date)
            if update_rows:
                season_year = self.opts["season_year"]
                team_abbrev = self.opts["team_abbrev"]
                player_names = [r["player_full_name"] for r in update_rows]

                # Use parameterized query to safely handle special characters in names
                query = f"""
                UPDATE `{table_id}`
                SET last_scraped_date = CURRENT_DATE()
                WHERE season_year = @season_year
                  AND team_abbrev = @team_abbrev
                  AND player_full_name IN UNNEST(@player_names)
                """

                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("season_year", "INT64", season_year),
                        bigquery.ScalarQueryParameter("team_abbrev", "STRING", team_abbrev),
                        bigquery.ArrayQueryParameter("player_names", "STRING", player_names),
                    ]
                )

                logger.info(f"Updating {len(update_rows)} existing players")
                query_job = self.bq_client.query(query, job_config=job_config)
                query_job.result()  # Wait for completion
            
            self.stats["rows_inserted"] = len(new_rows)
            self.stats["rows_updated"] = len(update_rows)
            
            # Send success notification
            try:
                notify_info(
                    title="Basketball Reference Roster Processing Complete",
                    message=f"Successfully processed {self.stats['total_players']} players for {self.opts.get('team_abbrev')}",
                    details={
                        'team_abbrev': self.opts.get('team_abbrev'),
                        'season_year': self.opts.get('season_year'),
                        'total_players': self.stats['total_players'],
                        'new_players': self.stats['new_players'],
                        'rows_inserted': len(new_rows),
                        'rows_updated': len(update_rows)
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
                
        except Exception as e:
            # Notify unexpected error
            try:
                notify_error(
                    title="Basketball Reference Roster Processing Failed",
                    message=f"Unexpected error during save: {str(e)}",
                    details={
                        'team_abbrev': self.opts.get('team_abbrev'),
                        'season_year': self.opts.get('season_year'),
                        'error_type': type(e).__name__,
                        'total_players': len(self.transformed_data)
                    },
                    processor_name="Basketball Reference Roster Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def _get_existing_roster(self, season_year: int, team_abbrev: str) -> List[Dict]:
        """Get existing roster from BigQuery for merge logic."""
        table_id = f"{self.bq_client.project}.{self.dataset_id}.{self.table_name}"
        
        query = f"""
        SELECT 
            player_lookup,
            player_full_name,
            first_seen_date
        FROM `{table_id}`
        WHERE season_year = {season_year}
          AND team_abbrev = '{team_abbrev}'
        """
        
        try:
            results = self.bq_client.query(query).result()
            return [dict(row) for row in results]
        except Exception as e:
            # Table might not exist yet
            logger.info(f"Could not get existing roster: {e}")
            return []
    
    def _parse_experience(self, exp_str: Optional[str]) -> Optional[int]:
        """Parse experience string - matches scraper implementation."""
        if not exp_str:
            return None
        
        exp_lower = exp_str.lower()
        
        if exp_lower == "rookie":
            return 0
        elif "year" in exp_lower:
            try:
                return int(exp_lower.split()[0])
            except (ValueError, IndexError, AttributeError) as e:
                logger.debug(f"Could not parse experience '{exp_lower}': {e}")
                return None

        return None
    
    def get_processor_stats(self) -> Dict:
        """Return processor stats - matches get_scraper_stats()."""
        return {
            "team_abbrev": self.opts.get("team_abbrev"),
            "season_year": self.opts.get("season_year"),
            "total_players": self.stats.get("total_players", 0),
            "new_players": self.stats.get("new_players", 0),
            "rows_updated": self.stats.get("rows_updated", 0),
        }