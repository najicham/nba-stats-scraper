#!/usr/bin/env python3
"""
Path: data_processors/raw/nbacom/nbac_team_boxscore_processor.py

NBA.com Team Boxscore Processor (v2.0)
Transforms NBA.com team box score data into BigQuery format.

Input: GCS files at gs://nba-scraped-data/nba-com/team-boxscore/
Output: BigQuery table nba_raw.nbac_team_boxscore
Strategy: MERGE_UPDATE (replace existing records per game)

Version 2.0 Changes:
- Added is_home boolean to distinguish home/away teams
- Standardized game_id format: YYYYMMDD_AWAY_HOME
- Preserved nba_game_id for NBA.com API traceability
"""

import json
import logging
import os
import re
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery

# Import base class
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Schedule service for season type detection
from shared.utils.schedule import NBAScheduleService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NbacTeamBoxscoreProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process NBA.com team box score data with smart idempotency.

    Transforms team-level statistics from NBA.com API into clean BigQuery records.
    Each game produces exactly 2 records (one per team).

    Input Format:
        {
            "gameId": "0022400561",
            "gameDate": "2025-01-15",
            "teams": [
                {
                    "teamAbbreviation": "LAL",  // Away team (typically teams[0])
                    "homeAway": "AWAY",          // Optional explicit indicator
                    "fieldGoals": {"made": 46, "attempted": 92, "percentage": 0.5},
                    ...
                },
                {
                    "teamAbbreviation": "PHI",  // Home team (typically teams[1])
                    "homeAway": "HOME",          // Optional explicit indicator
                    ...
                }
            ]
        }
    
    Output: nba_raw.nbac_team_boxscore (v2.0 with is_home and dual game IDs)
    """

    # Smart idempotency: Hash meaningful team boxscore fields only
    HASH_FIELDS = [
        'game_id',
        'team_abbr',
        'is_home',
        'fg_made',
        'fg_attempted',
        'three_pt_made',
        'three_pt_attempted',
        'ft_made',
        'ft_attempted',
        'offensive_rebounds',
        'defensive_rebounds',
        'total_rebounds',
        'assists',
        'steals',
        'blocks',
        'turnovers',
        'personal_fouls',
        'points',
        'plus_minus'
    ]

    # Primary keys for smart idempotency hash lookup
    PRIMARY_KEYS = ['game_id', 'team_abbr']

    # Valid NBA team codes - used to detect non-NBA games (All-Star, exhibition)
    VALID_NBA_TEAMS = {
        'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_team_boxscore'
        self.processing_strategy = 'MERGE_UPDATE'

        # CRITICAL: Initialize BigQuery client and project ID
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

        # Schedule service for season type detection
        self.schedule_service = NBAScheduleService()

        logger.info(f"Initialized {self.__class__.__name__} v2.0")
        logger.info(f"  Table: {self.table_name}")
        logger.info(f"  Strategy: {self.processing_strategy}")
        logger.info(f"  Project: {self.project_id}")
    
    def normalize_team_abbr(self, abbr: str) -> str:
        """
        Normalize team abbreviation for consistency.
        
        Args:
            abbr: Raw team abbreviation (e.g., "PHI", "NYK")
            
        Returns:
            Normalized uppercase team abbreviation
        """
        if not abbr:
            return ""
        return abbr.strip().upper()
    
    def normalize_text(self, text: str) -> str:
        """
        Normalize text for data consistency.
        
        Args:
            text: Raw text string
            
        Returns:
            Normalized text with consistent spacing
        """
        if not text:
            return ""
        normalized = text.strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized
    
    def extract_season_year(self, game_date: str) -> int:
        """
        Extract NBA season starting year from game date.
        
        NBA season starts in October. Games from Oct-Dec belong to that year's season,
        games from Jan-Sep belong to the previous year's season.
        
        Args:
            game_date: Game date in YYYY-MM-DD format
            
        Returns:
            Season starting year (e.g., 2024 for 2024-25 season)
            
        Examples:
            "2024-10-22" → 2024 (2024-25 season)
            "2025-01-15" → 2024 (2024-25 season)
            "2025-06-15" → 2024 (2024-25 playoffs)
        """
        try:
            if isinstance(game_date, str):
                game_date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            else:
                game_date_obj = game_date
                
            # NBA season starts in October
            if game_date_obj.month >= 10:
                return game_date_obj.year
            else:
                return game_date_obj.year - 1
                
        except (ValueError, AttributeError) as e:
            logger.warning(f"Could not parse game date '{game_date}': {e}")
            # Default to current year - 1 as fallback
            return datetime.now().year - 1
    
    def determine_home_away(self, teams: List[Dict]) -> Tuple[Dict, Dict]:
        """
        Determine which team is home and which is away.
        
        NBA.com API typically provides this in one of two ways:
        1. Explicit field: team['homeAway'] = "HOME" or "AWAY"
        2. Array order: teams[0] = away, teams[1] = home
        
        Args:
            teams: List of exactly 2 team dictionaries from NBA.com API
            
        Returns:
            Tuple of (away_team_dict, home_team_dict)
            
        Raises:
            ValueError: If home/away cannot be determined
        """
        if len(teams) != 2:
            raise ValueError(f"Expected exactly 2 teams, got {len(teams)}")
        
        # ✅ NEW: Validate teams are dictionaries
        for i, team in enumerate(teams):
            if not isinstance(team, dict):
                raise ValueError(f"Team {i} must be a dictionary, got {type(team).__name__}")
        
        # Method 1: Check for explicit homeAway field
        home_away_fields = []
        for team in teams:
            home_away = team.get('homeAway', '').upper()
            if home_away:
                home_away_fields.append(home_away)
        
        # If we have explicit indicators, use them
        if len(home_away_fields) == 2:
            if 'HOME' in home_away_fields and 'AWAY' in home_away_fields:
                away_team = next(t for t in teams if t.get('homeAway', '').upper() == 'AWAY')
                home_team = next(t for t in teams if t.get('homeAway', '').upper() == 'HOME')
                logger.debug("Home/away determined from explicit homeAway field")
                return (away_team, home_team)
        
        # Method 2: Use array order (NBA.com standard: teams[0] = away, teams[1] = home)
        logger.debug("Home/away determined from array order (teams[0]=away, teams[1]=home)")
        return (teams[0], teams[1])
    
    def generate_game_id(self, game_date: str, away_abbr: str, home_abbr: str) -> str:
        """
        Generate standardized game ID.
        
        Format: YYYYMMDD_AWAY_HOME
        
        Args:
            game_date: Game date in YYYY-MM-DD format
            away_abbr: Away team abbreviation (e.g., "LAL")
            home_abbr: Home team abbreviation (e.g., "PHI")
            
        Returns:
            Standardized game ID (e.g., "20250115_LAL_PHI")
            
        Examples:
            ("2025-01-15", "LAL", "PHI") → "20250115_LAL_PHI"
            ("2024-10-22", "BOS", "NYK") → "20241022_BOS_NYK"
        """
        # Remove hyphens from date: "2025-01-15" → "20250115"
        date_str = game_date.replace('-', '')
        
        # Build game_id: YYYYMMDD_AWAY_HOME
        game_id = f"{date_str}_{away_abbr}_{home_abbr}"
        
        logger.debug(f"Generated game_id: {game_id}")
        return game_id
    
    def safe_int(self, value, default=None) -> Optional[int]:
        """
        Safely convert value to integer.
        
        Args:
            value: Value to convert
            default: Default value if conversion fails
            
        Returns:
            Integer value or default
        """
        if value is None or value == '':
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert '{value}' to int, using default {default}")
            return default
    
    def safe_float(self, value, default=None) -> Optional[float]:
        """
        Safely convert value to float.
        
        Args:
            value: Value to convert
            default: Default value if conversion fails
            
        Returns:
            Float value or default
        """
        if value is None or value == '':
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert '{value}' to float, using default {default}")
            return default
    
    def validate_data(self, data: Dict) -> List[str]:
        """
        Validate the data structure.
        
        Args:
            data: Parsed JSON from GCS file
            
        Returns:
            List of error messages (empty list if valid)
        """
        errors = []
        
        # Check required top-level fields
        if 'gameId' not in data:
            errors.append("Missing required field: gameId")
        
        if 'gameDate' not in data:
            errors.append("Missing required field: gameDate")
        
        if 'teams' not in data:
            errors.append("Missing required field: teams")
            return errors  # Can't continue without teams
        
        # Validate teams structure
        if not isinstance(data['teams'], list):
            errors.append("'teams' field must be a list")
            return errors
        
        # Check team count
        if len(data['teams']) != 2:
            errors.append(f"Expected 2 teams, got {len(data['teams'])}")
        
        # Validate home/away can be determined
        try:
            away_team, home_team = self.determine_home_away(data['teams'])
            
            # Verify we have team abbreviations
            away_abbr = away_team.get('teamAbbreviation', '').strip()
            home_abbr = home_team.get('teamAbbreviation', '').strip()
            
            if not away_abbr:
                errors.append("Away team missing teamAbbreviation")
            if not home_abbr:
                errors.append("Home team missing teamAbbreviation")
            
        except ValueError as e:
            errors.append(f"Cannot determine home/away teams: {str(e)}")
        
        # Validate each team's structure
        for i, team in enumerate(data['teams']):
            if not isinstance(team, dict):
                errors.append(f"Team {i}: Must be an object")
                continue
            
            # Check required team fields
            required_team_fields = [
                'teamId', 'teamAbbreviation', 'teamName', 'teamCity',
                'fieldGoals', 'threePointers', 'freeThrows', 'rebounds',
                'assists', 'steals', 'blocks', 'turnovers', 'personalFouls', 'points'
            ]
            
            for field in required_team_fields:
                if field not in team:
                    errors.append(f"Team {i}: Missing required field '{field}'")
            
            # Validate nested shooting structures
            for stat_type in ['fieldGoals', 'threePointers', 'freeThrows']:
                if stat_type in team:
                    stat = team[stat_type]
                    if not isinstance(stat, dict):
                        errors.append(f"Team {i}: '{stat_type}' must be an object")
                        continue
                    
                    # Check required sub-fields
                    if 'made' not in stat or 'attempted' not in stat:
                        errors.append(f"Team {i}: '{stat_type}' missing made/attempted")
                    
                    # Validate math: made <= attempted
                    made = stat.get('made', 0)
                    attempted = stat.get('attempted', 0)
                    if made > attempted:
                        errors.append(f"Team {i}: {stat_type} made ({made}) > attempted ({attempted})")
            
            # Validate rebounds structure
            if 'rebounds' in team:
                rebounds = team['rebounds']
                if not isinstance(rebounds, dict):
                    errors.append(f"Team {i}: 'rebounds' must be an object")
                    continue
                
                if 'offensive' not in rebounds or 'defensive' not in rebounds or 'total' not in rebounds:
                    errors.append(f"Team {i}: 'rebounds' missing offensive/defensive/total")
                else:
                    # Validate math: offensive + defensive = total
                    offensive = rebounds.get('offensive', 0)
                    defensive = rebounds.get('defensive', 0)
                    total = rebounds.get('total', 0)
                    if offensive + defensive != total:
                        errors.append(
                            f"Team {i}: Rebounds don't add up: "
                            f"{offensive} + {defensive} != {total}"
                        )
            
            # Validate points calculation
            if all(k in team for k in ['fieldGoals', 'threePointers', 'freeThrows', 'points']):
                fg_made = team['fieldGoals'].get('made', 0)
                three_made = team['threePointers'].get('made', 0)
                ft_made = team['freeThrows'].get('made', 0)
                points = team.get('points', 0)
                
                # Calculate expected points: (FG2 * 2) + (3PT * 3) + (FT * 1)
                fg2_made = fg_made - three_made
                expected_points = (fg2_made * 2) + (three_made * 3) + ft_made
                
                if expected_points != points:
                    errors.append(
                        f"Team {i}: Points calculation error. "
                        f"Expected {expected_points} "
                        f"(FG2:{fg2_made}*2 + 3PT:{three_made}*3 + FT:{ft_made}), "
                        f"got {points}"
                    )
        
        return errors

    def load_data(self) -> None:
        """Load team boxscore JSON data from GCS."""
        self.raw_data = self.load_json_from_gcs()
        logger.info(f"Loaded team boxscore data from GCS")

    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """
        Transform raw data into BigQuery format.

        Args:
            raw_data: Parsed JSON from GCS file
            file_path: Full GCS path for tracking

        Returns:
            List of records ready for BigQuery insertion
        """
        rows = []

        # Extract top-level metadata
        nba_game_id = raw_data.get('gameId')  # NBA.com format (e.g., "0022400561")
        game_date = raw_data.get('gameDate')

        # Check game type - skip exhibition games (All-Star and Pre-Season)
        if game_date:
            season_type = self.schedule_service.get_season_type_for_date(game_date)

            # Skip exhibition games - they aren't useful for predictions
            # All-Star: Uses non-NBA teams (Team LeBron, Team Giannis, etc.)
            # Pre-Season: Teams rest starters, rosters not finalized, stats not indicative
            if season_type in ["All Star", "Pre Season"]:
                logger.info(f"Skipping {season_type} game data for {game_date} (NBA ID: {nba_game_id}) - "
                           "exhibition games not processed")
                self.transformed_data = []
                return

        # Calculate season year
        season_year = self.extract_season_year(game_date)
        
        # Determine home/away teams
        try:
            away_team, home_team = self.determine_home_away(raw_data.get('teams', []))
        except ValueError as e:
            logger.error(f"Cannot determine home/away for {file_path}: {e}")
            self.transformed_data = rows
        
        # Generate standardized game_id: YYYYMMDD_AWAY_HOME
        away_abbr = self.normalize_team_abbr(away_team.get('teamAbbreviation', ''))
        home_abbr = self.normalize_team_abbr(home_team.get('teamAbbreviation', ''))
        game_id = self.generate_game_id(game_date, away_abbr, home_abbr)
        
        logger.info(f"Processing game: {game_id} (NBA.com ID: {nba_game_id})")
        logger.info(f"  Away: {away_abbr} | Home: {home_abbr}")
        
        # Get current processing time
        processed_at = datetime.now(timezone.utc)
        created_at = datetime.now(timezone.utc)
        
        # Process both teams
        for team, is_home in [(away_team, False), (home_team, True)]:
            # Extract shooting stats
            fg = team.get('fieldGoals', {})
            three_pt = team.get('threePointers', {})
            ft = team.get('freeThrows', {})
            rebounds = team.get('rebounds', {})
            
            # Build BigQuery record
            row = {
                # Identity fields (v2.0: dual game ID system)
                'game_id': game_id,                    # Standardized: "20250115_LAL_PHI"
                'nba_game_id': nba_game_id,            # NBA.com format: "0022400561"
                'game_date': game_date,                # Keep as string for .isoformat() consistency
                'season_year': season_year,
                'team_id': self.safe_int(team.get('teamId')),
                'team_abbr': self.normalize_team_abbr(team.get('teamAbbreviation', '')),
                'team_name': self.normalize_text(team.get('teamName', '')),
                'team_city': self.normalize_text(team.get('teamCity', '')),
                'is_home': is_home,                    # v2.0: NEW home/away indicator
                
                # Game time
                'minutes': team.get('minutes'),  # Keep as string (e.g., "265:00")
                
                # Field goals
                'fg_made': self.safe_int(fg.get('made')),
                'fg_attempted': self.safe_int(fg.get('attempted')),
                'fg_percentage': self.safe_float(fg.get('percentage')),
                
                # Three pointers
                'three_pt_made': self.safe_int(three_pt.get('made')),
                'three_pt_attempted': self.safe_int(three_pt.get('attempted')),
                'three_pt_percentage': self.safe_float(three_pt.get('percentage')),
                
                # Free throws
                'ft_made': self.safe_int(ft.get('made')),
                'ft_attempted': self.safe_int(ft.get('attempted')),
                'ft_percentage': self.safe_float(ft.get('percentage')),
                
                # Rebounds
                'offensive_rebounds': self.safe_int(rebounds.get('offensive')),
                'defensive_rebounds': self.safe_int(rebounds.get('defensive')),
                'total_rebounds': self.safe_int(rebounds.get('total')),
                
                # Other stats
                'assists': self.safe_int(team.get('assists')),
                'steals': self.safe_int(team.get('steals')),
                'blocks': self.safe_int(team.get('blocks')),
                'turnovers': self.safe_int(team.get('turnovers')),
                'personal_fouls': self.safe_int(team.get('personalFouls')),
                'points': self.safe_int(team.get('points')),
                'plus_minus': self.safe_int(team.get('plusMinus')),
                
                # Metadata - CRITICAL: use .isoformat() for BigQuery
                'source_file_path': file_path,
                'created_at': created_at.isoformat(),
                'processed_at': processed_at.isoformat()
            }
            
            rows.append(row)

        logger.info(f"Transformed {len(rows)} team records for game {game_id}")
        self.transformed_data = rows

        # Add smart idempotency hash to each row
        self.add_data_hash()
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data()).

        Uses batch loading (load_table_from_json) instead of streaming inserts
        (insert_rows_json) to avoid:
        1. The 20 DML concurrent operation limit per table
        2. The 90-minute streaming buffer that blocks DELETE/UPDATE operations
        """
        rows = self.transformed_data

        if not rows:
            logger.warning("No rows to save")
            self.stats['rows_inserted'] = 0
            return

        # Smart idempotency check: Skip write if data unchanged
        if self.should_skip_write():
            logger.info("Skipping write - data unchanged (smart idempotency)")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.table_name}"

        try:
            # MERGE_UPDATE strategy: Delete existing records for this game
            # v2.0: Use standardized game_id for deletion
            game_id = rows[0].get('game_id')
            game_date = rows[0].get('game_date')
            if game_id and game_date:
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE game_id = @game_id
                  AND game_date = @game_date
                """

                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
                    ]
                )

                delete_job = self.bq_client.query(delete_query, job_config=job_config)
                delete_job.result(timeout=60)  # Wait for completion

                logger.info(f"Deleted existing records for game {game_id}")

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

            # Insert new records using batch loading
            logger.info(f"Loading {len(rows)} rows into {table_id} using batch load")
            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            logger.info(f"Successfully loaded {len(rows)} rows to {self.table_name}")

            # Update stats for processor_base tracking
            self.stats['rows_inserted'] = len(rows)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error loading data to BigQuery: {error_msg}")

            # Update stats for failure tracking
            self.stats['rows_inserted'] = 0

            raise
    
    def process_file(self, file_path: str, **kwargs) -> Dict:
        """
        Process a single file - main entry point for both Pub/Sub and backfill.
        
        Args:
            file_path: GCS path to file (gs://bucket/path/to/file.json)
            **kwargs: Additional options (dry_run supported)
            
        Returns:
            Dict with processing results
        """
        try:
            logger.info(f"Processing file: {file_path}")
            
            # Get file content
            raw_data = self.get_file_content(file_path)
            
            # Validate
            validation_errors = self.validate_data(raw_data)
            if validation_errors:
                logger.warning(f"Validation errors for {file_path}:")
                for error in validation_errors:
                    logger.warning(f"  - {error}")
                
                return {
                    'file_path': file_path,
                    'status': 'validation_failed',
                    'errors': validation_errors,
                    'rows_processed': 0
                }
            
            # Transform
            rows = self.transform_data(raw_data, file_path)
            
            if not rows:
                logger.warning(f"No rows generated from {file_path}")
                return {
                    'file_path': file_path,
                    'status': 'no_data',
                    'rows_processed': 0
                }
            
            # Load
            result = self.load_data(rows, **kwargs)
            
            # Determine status
            if result.get('errors'):
                status = 'partial_success' if result.get('rows_processed', 0) > 0 else 'failed'
                logger.warning(f"{status.title()}: {len(result['errors'])} errors for {file_path}")
            else:
                status = 'success'
                logger.info(f"✓ Successfully processed {file_path}: {result['rows_processed']} rows")
            
            return {
                'file_path': file_path,
                'status': status,
                'rows_processed': result.get('rows_processed', 0),
                'errors': result.get('errors', [])
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error processing file {file_path}: {error_msg}", exc_info=True)
            return {
                'file_path': file_path,
                'status': 'error',
                'error': error_msg,
                'rows_processed': 0
            }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }



# CLI entry point for testing
if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python nbac_team_boxscore_processor.py <gcs_file_path>")
        print("Example: python nbac_team_boxscore_processor.py gs://nba-scraped-data/nba-com/team-boxscore/20250115/0022400561/20250115_123045.json")
        sys.exit(1)
    
    file_path = sys.argv[1]
    
    # Initialize processor
    processor = NbacTeamBoxscoreProcessor()
    
    # Process file
    result = processor.process_file(file_path, dry_run=False)
    
    # Print results
    print("\n" + "="*70)
    print("PROCESSING RESULTS")
    print("="*70)
    print(f"File: {result['file_path']}")
    print(f"Status: {result['status']}")
    print(f"Rows Processed: {result['rows_processed']}")
    
    if result.get('errors'):
        print(f"\nErrors ({len(result['errors'])}):")
        for error in result['errors']:
            print(f"  - {error}")
    
    print("="*70)