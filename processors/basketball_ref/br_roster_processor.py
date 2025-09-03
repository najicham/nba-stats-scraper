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

logger = logging.getLogger(__name__)


class BasketballRefRosterProcessor(ProcessorBase):
    """
    Process Basketball Reference roster files.
    Implements MERGE_UPDATE strategy with first_seen_date tracking.
    """
    
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
            raise FileNotFoundError(f"File not found: gs://{bucket_name}/{file_path}")
        
        content = blob.download_as_text()
        self.raw_data = json.loads(content)
        
        logger.info(f"Loaded {len(self.raw_data.get('players', []))} players")
    
    def validate_loaded_data(self) -> None:
        """Validate roster data structure."""
        super().validate_loaded_data()
        
        errors = []
        
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
            errors.append(f"Suspicious roster size: {len(players)} players")
        
        # Check for duplicate players
        names = [p.get("full_name") for p in players if p.get("full_name")]
        if len(names) != len(set(names)):
            errors.append("Duplicate player names found")
        
        if errors:
            for error in errors:
                logger.warning(f"Validation issue: {error}")
            
            # Critical errors stop processing
            if any("Missing" in e for e in errors):
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
        
        for player in self.raw_data.get("players", []):
            if not player.get("full_name"):
                logger.warning(f"Skipping player without name: {player}")
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
        self.stats["new_players"] = len(new_players)
        self.stats["total_players"] = len(rows)
    
    def save_data(self) -> None:
        """
        Override to implement MERGE_UPDATE strategy.
        Updates existing players, inserts new ones.
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
        
        table_id = f"{self.bq_client.project}.{self.dataset_id}.{self.table_name}"
        
        # Separate new vs existing players
        new_rows = [r for r in self.transformed_data if "first_seen_date" in r]
        update_rows = [r for r in self.transformed_data if "first_seen_date" not in r]
        
        # Insert new players
        if new_rows:
            logger.info(f"Inserting {len(new_rows)} new players")
            errors = self.bq_client.insert_rows_json(table_id, new_rows)
            if errors:
                raise Exception(f"Failed to insert new players: {errors}")
        
        # Update existing players (just update last_scraped_date)
        if update_rows:
            season_year = self.opts["season_year"]
            team_abbrev = self.opts["team_abbrev"]
            player_names = [r["player_full_name"] for r in update_rows]
            
            query = f"""
            UPDATE `{table_id}`
            SET last_scraped_date = CURRENT_DATE()
            WHERE season_year = {season_year}
              AND team_abbrev = '{team_abbrev}'
              AND player_full_name IN ({','.join([f"'{n}'" for n in player_names])})
            """
            
            logger.info(f"Updating {len(update_rows)} existing players")
            query_job = self.bq_client.query(query)
            query_job.result()  # Wait for completion
        
        self.stats["rows_inserted"] = len(new_rows)
        self.stats["rows_updated"] = len(update_rows)
    
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
            except:
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