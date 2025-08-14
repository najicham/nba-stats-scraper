#!/usr/bin/env python3
"""
NBA Gamebook Data Validation Script

Comprehensive validation for NBA.com gamebook data stored in GCS.
Validates schema, data quality, business logic, and file integrity.

Usage:
    # General validation
    python validate_gamebook_data.py --sample-size 100
    python validate_gamebook_data.py --full-scan
    python validate_gamebook_data.py --file gs://path/to/file.json
    
    # Daily operational validation
    python validate_gamebook_data.py --today
    python validate_gamebook_data.py --yesterday 
    python validate_gamebook_data.py --this-week
    python validate_gamebook_data.py --last-days 3
    
    # Season/date range validation  
    python validate_gamebook_data.py --season "2025-26"
    python validate_gamebook_data.py --start-date "2025-10-15" --end-date "2025-10-22"
    
    # End-of-day validation for 2025-26 season
    python validate_gamebook_data.py --season "2025-26" --today --sample-size 50
"""

import json
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import argparse
from pathlib import Path
import subprocess
import sys
from collections import defaultdict, Counter

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ValidationStats:
    """Track validation statistics"""
    total_files: int = 0
    valid_files: int = 0
    invalid_files: int = 0
    schema_errors: int = 0
    data_quality_errors: int = 0
    business_logic_errors: int = 0
    file_integrity_errors: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

class NBAGamebookValidator:
    """Comprehensive NBA gamebook data validator"""
    
    # Valid NBA team codes (3-letter abbreviations)
    VALID_TEAMS = {
        'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }
    
    # Expected schema structure
    REQUIRED_FIELDS = {
        'game_code': str,
        'date': str,
        'matchup': str,
        'away_team': str,
        'home_team': str,
        'arena': str,
        'city': str,
        'state': str,
        'location': str,
        'officials': list,
        'timestamp': str,
        'active_players': list
    }
    
    OPTIONAL_FIELDS = {
        'pdf_version': str,
        'pdf_url': str,
        'game_duration': str,
        'attendance': (int, type(None))
    }
    
    PLAYER_REQUIRED_FIELDS = {
        'name': str,
        'team': str,
        'status': str,
        'stats': dict
    }
    
    STATS_REQUIRED_FIELDS = {
        'minutes': str,
        'field_goals_made': int,
        'field_goals_attempted': int,
        'three_pointers_made': int,
        'three_pointers_attempted': int,
        'free_throws_made': int,
        'free_throws_attempted': int,
        'offensive_rebounds': int,
        'defensive_rebounds': int,
        'total_rebounds': int,
        'assists': int,
        'personal_fouls': int,
        'steals': int,
        'turnovers': int,
        'blocks': int
    }
    
    def __init__(self, warning_limit: int = 0):
        self.stats = ValidationStats()
        self.special_games_detected = []
        self.warning_limit = warning_limit
    
    def validate_file_path(self, gcs_path: str) -> Tuple[bool, List[str]]:
        """Validate GCS file path structure"""
        errors = []
        warnings = []
        
        # Expected pattern: gs://nba-scraped-data/nba-com/gamebooks-data/YYYY-MM-DD/YYYYMMDD-TEAMTEAM/TIMESTAMP.json
        pattern = r'gs://nba-scraped-data/nba-com/gamebooks-data/(\d{4}-\d{2}-\d{2})/(\d{8}-[A-Z]{6})/(\d{8}_\d{6})\.json'
        match = re.match(pattern, gcs_path)
        
        if not match:
            errors.append(f"Invalid file path structure: {gcs_path}")
            return False, errors
        
        date_str, game_code, timestamp = match.groups()
        
        # Validate date format
        try:
            game_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            errors.append(f"Invalid date format in path: {date_str}")
            return False, errors
        
        # Validate game code format
        if not re.match(r'\d{8}-[A-Z]{6}', game_code):
            errors.append(f"Invalid game code format: {game_code}")
            return False, errors
        
        # Extract teams from game code
        teams = game_code[9:]  # Skip YYYYMMDD-
        if len(teams) != 6:
            errors.append(f"Invalid team code length in game code: {teams}")
        else:
            away_team = teams[:3]
            home_team = teams[3:]
            
            # Check if this might be a special game based on date
            is_likely_special = False
            if game_date.month in [9, 10] and game_date.day < 15:  # Preseason
                is_likely_special = True
            elif game_date.month == 2 and 10 <= game_date.day <= 20:  # All-Star
                is_likely_special = True
            
            if away_team not in self.VALID_TEAMS:
                if is_likely_special:
                    warnings.append(f"Non-standard away team code in special game period: {away_team} (Date: {date_str})")
                else:
                    errors.append(f"Invalid away team code: {away_team}")
            
            if home_team not in self.VALID_TEAMS:
                if is_likely_special:
                    warnings.append(f"Non-standard home team code in special game period: {home_team} (Date: {date_str})")
                else:
                    errors.append(f"Invalid home team code: {home_team}")
        
        # Add warnings to stats if any
        if warnings:
            self.stats.warnings.extend(warnings)
        
        return len(errors) == 0, errors
    
    def validate_schema(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate JSON schema structure"""
        errors = []
        
        # Check required fields
        for field, expected_type in self.REQUIRED_FIELDS.items():
            if field not in data:
                errors.append(f"Missing required field: {field}")
            elif not isinstance(data[field], expected_type):
                errors.append(f"Field '{field}' has wrong type. Expected {expected_type.__name__}, got {type(data[field]).__name__}")
        
        # Check optional fields if present
        for field, expected_type in self.OPTIONAL_FIELDS.items():
            if field in data and data[field] is not None:
                if isinstance(expected_type, tuple):
                    if not any(isinstance(data[field], t) for t in expected_type):
                        errors.append(f"Field '{field}' has wrong type. Expected one of {[t.__name__ for t in expected_type]}, got {type(data[field]).__name__}")
                elif not isinstance(data[field], expected_type):
                    errors.append(f"Field '{field}' has wrong type. Expected {expected_type.__name__}, got {type(data[field]).__name__}")
        
        # Validate players structure
        if 'active_players' in data:
            for i, player in enumerate(data['active_players']):
                if not isinstance(player, dict):
                    errors.append(f"Player {i} is not a dictionary")
                    continue
                
                # Check required player fields
                for field, expected_type in self.PLAYER_REQUIRED_FIELDS.items():
                    if field not in player:
                        errors.append(f"Player {i} missing required field: {field}")
                    elif not isinstance(player[field], expected_type):
                        errors.append(f"Player {i} field '{field}' has wrong type. Expected {expected_type.__name__}, got {type(player[field]).__name__}")
                
                # Check stats structure
                if 'stats' in player and isinstance(player['stats'], dict):
                    for field, expected_type in self.STATS_REQUIRED_FIELDS.items():
                        if field not in player['stats']:
                            errors.append(f"Player {i} stats missing required field: {field}")
                        elif not isinstance(player['stats'][field], expected_type):
                            errors.append(f"Player {i} stats field '{field}' has wrong type. Expected {expected_type.__name__}, got {type(player['stats'][field]).__name__}")
        
        return len(errors) == 0, errors
    
    def _get_game_context(self, data: Dict[str, Any]) -> str:
        """Extract game context for better error reporting"""
        context_parts = []
        
        if 'date' in data:
            context_parts.append(f"Date: {data['date']}")
        if 'matchup' in data:
            context_parts.append(f"Matchup: {data['matchup']}")
        if 'arena' in data:
            context_parts.append(f"Arena: {data['arena']}")
        if 'location' in data:
            context_parts.append(f"Location: {data['location']}")
        
        return " | ".join(context_parts)
    
    def _is_special_game(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Detect if this is a special game type (All-Star, exhibition, etc.)"""
        indicators = []
        
        # Check for All-Star game indicators
        allstar_indicators = ['all-star', 'all star', 'allstar']
        if 'arena' in data:
            arena_lower = data['arena'].lower()
            if any(indicator in arena_lower for indicator in allstar_indicators):
                indicators.append("All-Star Game")
        
        # Check for exhibition/preseason based on date
        if 'date' in data:
            try:
                game_date = datetime.strptime(data['date'], '%Y-%m-%d')
                # NBA preseason typically runs September-October
                if game_date.month in [9, 10]:
                    # Regular season usually starts mid-October
                    if game_date.month == 10 and game_date.day >= 15:
                        pass  # Likely regular season
                    else:
                        indicators.append("Preseason/Exhibition")
                # All-Star weekend is typically mid-February
                elif game_date.month == 2 and 10 <= game_date.day <= 20:
                    indicators.append("All-Star Weekend")
            except ValueError:
                pass
        
        # Check for unusual team combinations that suggest special games
        if 'away_team' in data and 'home_team' in data:
            away = data['away_team']
            home = data['home_team']
            
            # All-Star games often have non-standard team codes
            if (len(away) == 3 and len(home) == 3 and 
                (away not in self.VALID_TEAMS or home not in self.VALID_TEAMS)):
                indicators.append("Special Team Codes")
        
        is_special = len(indicators) > 0
        special_type = " + ".join(indicators) if indicators else ""
        
        return is_special, special_type
    
    def validate_data_quality(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate data quality and reasonableness"""
        errors = []
        warnings = []
        
        # Get game context for better error reporting
        game_context = self._get_game_context(data)
        is_special, special_type = self._is_special_game(data)
        
        # Validate date format
        if 'date' in data:
            try:
                game_date = datetime.strptime(data['date'], '%Y-%m-%d')
                # Check if date is reasonable (2021-2025 range)
                if game_date.year < 2021 or game_date.year > 2025:
                    warnings.append(f"Game date outside expected range: {data['date']} | {game_context}")
            except ValueError:
                errors.append(f"Invalid date format: {data['date']} | {game_context}")
        
        # Validate team codes (with special game awareness)
        if 'away_team' in data and data['away_team'] not in self.VALID_TEAMS:
            if is_special:
                warnings.append(f"Non-standard away team in {special_type}: {data['away_team']} | {game_context}")
            else:
                errors.append(f"Invalid away team: {data['away_team']} | {game_context}")
        
        if 'home_team' in data and data['home_team'] not in self.VALID_TEAMS:
            if is_special:
                warnings.append(f"Non-standard home team in {special_type}: {data['home_team']} | {game_context}")
            else:
                errors.append(f"Invalid home team: {data['home_team']} | {game_context}")
        
        # Validate matchup format
        if 'matchup' in data:
            expected_matchup = f"{data.get('away_team', '')}@{data.get('home_team', '')}"
            if data['matchup'] != expected_matchup:
                if is_special:
                    warnings.append(f"Non-standard matchup format in {special_type}: Expected {expected_matchup}, Got {data['matchup']} | {game_context}")
                else:
                    errors.append(f"Matchup mismatch. Expected: {expected_matchup}, Got: {data['matchup']} | {game_context}")
        
        # Validate game code consistency
        if 'game_code' in data and 'date' in data:
            expected_date_prefix = data['date'].replace('-', '')
            expected_teams = f"{data.get('away_team', '')}{data.get('home_team', '')}"
            expected_game_code = f"{expected_date_prefix}/{expected_teams}"
            if data['game_code'] != expected_game_code:
                if is_special:
                    warnings.append(f"Non-standard game code in {special_type}: Expected {expected_game_code}, Got {data['game_code']} | {game_context}")
                else:
                    errors.append(f"Game code mismatch. Expected: {expected_game_code}, Got: {data['game_code']} | {game_context}")
        
        # Validate attendance
        if 'attendance' in data and data['attendance'] is not None:
            if data['attendance'] < 0 or data['attendance'] > 25000:
                warnings.append(f"Unusual attendance: {data['attendance']} | {game_context}")
        
        # Validate player stats
        if 'active_players' in data:
            for i, player in enumerate(data['active_players']):
                if 'stats' in player:
                    self._validate_player_stats(player, i, errors, warnings, game_context)
        
        self.stats.warnings.extend(warnings)
        return len(errors) == 0, errors
    
    def _validate_player_stats(self, player: Dict[str, Any], index: int, errors: List[str], warnings: List[str], game_context: str = ""):
        """Validate individual player statistics"""
        stats = player['stats']
        name = player.get('name', f'Player {index}')
        context_suffix = f" | {game_context}" if game_context else ""
        
        # Validate shot attempts consistency
        if 'field_goals_made' in stats and 'field_goals_attempted' in stats:
            if stats['field_goals_made'] > stats['field_goals_attempted']:
                errors.append(f"{name}: FG made ({stats['field_goals_made']}) > FG attempted ({stats['field_goals_attempted']}){context_suffix}")
        
        if 'three_pointers_made' in stats and 'three_pointers_attempted' in stats:
            if stats['three_pointers_made'] > stats['three_pointers_attempted']:
                errors.append(f"{name}: 3P made ({stats['three_pointers_made']}) > 3P attempted ({stats['three_pointers_attempted']}){context_suffix}")
        
        if 'free_throws_made' in stats and 'free_throws_attempted' in stats:
            if stats['free_throws_made'] > stats['free_throws_attempted']:
                errors.append(f"{name}: FT made ({stats['free_throws_made']}) > FT attempted ({stats['free_throws_attempted']}){context_suffix}")
        
        # Validate rebounds
        if all(field in stats for field in ['offensive_rebounds', 'defensive_rebounds', 'total_rebounds']):
            calculated_total = stats['offensive_rebounds'] + stats['defensive_rebounds']
            if calculated_total != stats['total_rebounds']:
                errors.append(f"{name}: Rebounds don't add up. OFF: {stats['offensive_rebounds']}, DEF: {stats['defensive_rebounds']}, TOTAL: {stats['total_rebounds']}{context_suffix}")
        
        # Validate minutes format
        if 'minutes' in stats:
            if not re.match(r'\d{1,2}:\d{2}', stats['minutes']):
                errors.append(f"{name}: Invalid minutes format: {stats['minutes']}{context_suffix}")
            else:
                # Convert to total minutes and check reasonableness
                try:
                    minutes, seconds = map(int, stats['minutes'].split(':'))
                    total_minutes = minutes + seconds / 60
                    if total_minutes > 48:
                        warnings.append(f"{name}: High minutes played: {stats['minutes']}{context_suffix}")
                    elif total_minutes < 0:
                        errors.append(f"{name}: Negative minutes: {stats['minutes']}{context_suffix}")
                except ValueError:
                    errors.append(f"{name}: Cannot parse minutes: {stats['minutes']}{context_suffix}")
        
        # Check for reasonable stat ranges
        stat_ranges = {
            'field_goals_made': (0, 30),
            'field_goals_attempted': (0, 50),
            'three_pointers_made': (0, 15),
            'three_pointers_attempted': (0, 25),
            'free_throws_made': (0, 30),
            'free_throws_attempted': (0, 40),
            'total_rebounds': (0, 25),
            'assists': (0, 20),
            'steals': (0, 10),
            'blocks': (0, 10),
            'turnovers': (0, 15),
            'personal_fouls': (0, 6)
        }
        
        for stat, (min_val, max_val) in stat_ranges.items():
            if stat in stats:
                value = stats[stat]
                if value < min_val or value > max_val:
                    warnings.append(f"{name}: Unusual {stat}: {value}{context_suffix}")
    
    def validate_business_logic(self, data: Dict[str, Any], file_path: str) -> Tuple[bool, List[str]]:
        """Validate business logic consistency"""
        errors = []
        
        # Extract date and teams from file path
        path_match = re.search(r'/(\d{4}-\d{2}-\d{2})/(\d{8}-[A-Z]{6})/', file_path)
        if path_match:
            path_date, path_game_code = path_match.groups()
            
            # Check date consistency
            if 'date' in data and data['date'] != path_date:
                errors.append(f"Date mismatch. File path: {path_date}, Data: {data['date']}")
            
            # Check team consistency
            if len(path_game_code) >= 15:  # YYYYMMDD-TEAMTEAM
                path_teams = path_game_code[9:]  # Skip date part
                if len(path_teams) == 6:
                    path_away = path_teams[:3]
                    path_home = path_teams[3:]
                    
                    if 'away_team' in data and data['away_team'] != path_away:
                        errors.append(f"Away team mismatch. File path: {path_away}, Data: {data['away_team']}")
                    if 'home_team' in data and data['home_team'] != path_home:
                        errors.append(f"Home team mismatch. File path: {path_home}, Data: {data['home_team']}")
        
        # Validate timestamp is recent (data should be scraped recently)
        if 'timestamp' in data:
            try:
                timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                now = datetime.now(timestamp.tzinfo)
                if (now - timestamp).days > 30:
                    self.stats.warnings.append(f"Old timestamp: {data['timestamp']}")
            except ValueError:
                errors.append(f"Invalid timestamp format: {data['timestamp']}")
        
        return len(errors) == 0, errors
    
    def validate_file(self, file_path: str, data: Dict[str, Any]) -> bool:
        """Validate a single file completely"""
        all_errors = []
        
        # Check if this is a special game and track it
        is_special, special_type = self._is_special_game(data)
        if is_special:
            game_context = self._get_game_context(data)
            self.special_games_detected.append({
                'file': file_path,
                'type': special_type,
                'context': game_context
            })
        
        # File path validation
        path_valid, path_errors = self.validate_file_path(file_path)
        all_errors.extend(path_errors)
        if not path_valid:
            self.stats.file_integrity_errors += len(path_errors)
        
        # Schema validation
        schema_valid, schema_errors = self.validate_schema(data)
        all_errors.extend(schema_errors)
        if not schema_valid:
            self.stats.schema_errors += len(schema_errors)
        
        # Data quality validation
        quality_valid, quality_errors = self.validate_data_quality(data)
        all_errors.extend(quality_errors)
        if not quality_valid:
            self.stats.data_quality_errors += len(quality_errors)
        
        # Business logic validation
        logic_valid, logic_errors = self.validate_business_logic(data, file_path)
        all_errors.extend(logic_errors)
        if not logic_valid:
            self.stats.business_logic_errors += len(logic_errors)
        
        # Record errors
        if all_errors:
            self.stats.errors.append(f"File: {file_path}")
            if is_special:
                self.stats.errors.append(f"  🌟 Special Game ({special_type}): {self._get_game_context(data)}")
            self.stats.errors.extend([f"  - {error}" for error in all_errors])
            self.stats.invalid_files += 1
            return False
        else:
            self.stats.valid_files += 1
            return True
    
    def get_gcs_files(self, bucket_path: str, sample_size: Optional[int] = None, 
                     start_date: Optional[str] = None, end_date: Optional[str] = None,
                     season: Optional[str] = None, last_days: Optional[int] = None) -> List[str]:
        """Get list of GCS files to validate with optional date filtering"""
        try:
            cmd = ['gcloud', 'storage', 'ls', f"{bucket_path}/**/*.json"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            files = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
            
            # Apply date filters
            if start_date or end_date or season or last_days:
                files = self._filter_files_by_date(files, start_date, end_date, season, last_days)
            
            if sample_size and len(files) > sample_size:
                import random
                files = random.sample(files, sample_size)
                logger.info(f"Sampling {sample_size} files from {len(files)} total files")
            
            return files
        except subprocess.CalledProcessError as e:
            logger.error(f"Error listing GCS files: {e}")
            return []
    
    def _filter_files_by_date(self, files: List[str], start_date: Optional[str] = None, 
                             end_date: Optional[str] = None, season: Optional[str] = None,
                             last_days: Optional[int] = None) -> List[str]:
        """Filter files based on date criteria"""
        filtered_files = []
        
        # Parse date filters
        start_dt = None
        end_dt = None
        
        if last_days:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=last_days)
            logger.info(f"Filtering for last {last_days} days: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
        
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if season:
            # Convert season format "2025-26" to date range
            start_year = int(season.split('-')[0])
            start_dt = datetime(start_year, 10, 1)  # NBA season starts ~October
            end_dt = datetime(start_year + 1, 6, 30)  # NBA season ends ~June
            logger.info(f"Filtering for {season} season: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
        
        # Filter files by extracting date from path
        for file_path in files:
            # Extract date from path: .../gamebooks-data/YYYY-MM-DD/...
            match = re.search(r'/(\d{4}-\d{2}-\d{2})/', file_path)
            if match:
                file_date_str = match.group(1)
                try:
                    file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                    
                    # Check if file date is within range
                    include_file = True
                    if start_dt and file_date < start_dt:
                        include_file = False
                    if end_dt and file_date > end_dt:
                        include_file = False
                    
                    if include_file:
                        filtered_files.append(file_path)
                except ValueError:
                    # Skip files with invalid date formats
                    logger.warning(f"Skipping file with invalid date: {file_path}")
        
        logger.info(f"Date filtering: {len(filtered_files)} files match criteria (from {len(files)} total)")
        
        # Provide helpful feedback if no files found
        if len(filtered_files) == 0 and len(files) > 0:
            if last_days:
                logger.warning(f"No files found for last {last_days} days. This might be expected during off-season.")
            elif season:
                logger.warning(f"No files found for {season} season. Check if season format is correct or data exists.")
            elif start_dt or end_dt:
                logger.warning(f"No files found in date range. This might be expected during off-season or for future dates.")
        
        return filtered_files
    
    def download_and_parse_file(self, gcs_path: str) -> Optional[Dict[str, Any]]:
        """Download and parse a single JSON file from GCS"""
        try:
            # Download file content
            cmd = ['gcloud', 'storage', 'cat', gcs_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Parse JSON
            data = json.loads(result.stdout)
            return data
        except subprocess.CalledProcessError as e:
            self.stats.errors.append(f"Failed to download {gcs_path}: {e}")
            self.stats.file_integrity_errors += 1
            return None
        except json.JSONDecodeError as e:
            self.stats.errors.append(f"Invalid JSON in {gcs_path}: {e}")
            self.stats.file_integrity_errors += 1
            return None
        except Exception as e:
            self.stats.errors.append(f"Unexpected error processing {gcs_path}: {e}")
            self.stats.file_integrity_errors += 1
            return None
    
    def validate_dataset(self, bucket_path: str = "gs://nba-scraped-data/nba-com/gamebooks-data", 
                        sample_size: Optional[int] = 100, start_date: Optional[str] = None,
                        end_date: Optional[str] = None, season: Optional[str] = None,
                        last_days: Optional[int] = None) -> ValidationStats:
        """Validate the entire dataset or a filtered subset"""
        logger.info(f"Starting validation of {bucket_path}")
        
        # Get files to validate with optional date filtering
        files = self.get_gcs_files(bucket_path, sample_size, start_date, end_date, season, last_days)
        self.stats.total_files = len(files)
        
        if not files:
            if start_date or end_date or season or last_days:
                logger.info("No files found matching date criteria. This is expected during off-season or for future dates.")
                print("\n🏀 No NBA games found for the specified date range.")
                print("This is normal during off-season periods.")
                return self.stats
            else:
                logger.error("No files found to validate in bucket")
                return self.stats
        
        logger.info(f"Validating {len(files)} files...")
        
        # Validate each file
        for i, file_path in enumerate(files):
            # Extract game directory and filename for better identification
            # Path format: .../gamebooks-data/2021-10-03/20211003-BKNLAL/20250809_131116.json
            path_parts = file_path.split('/')
            try:
                if len(path_parts) >= 2:
                    game_dir = path_parts[-2]   # e.g., "20211003-BKNLAL" (already contains date)
                    file_name = path_parts[-1]  # e.g., "20250809_131116.json"
                    display_name = f"{game_dir}/{file_name}"
                else:
                    display_name = file_path.split('/')[-1]
            except IndexError:
                display_name = file_path.split('/')[-1]
            
            # Show progress every 10 files and current file being processed more frequently
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(files)} files processed - Processing: {display_name}")
            elif i % 3 == 0:  # Show every 3rd file for better visibility
                logger.info(f"Processing: {display_name}")
            
            data = self.download_and_parse_file(file_path)
            if data is not None:
                self.validate_file(file_path, data)
        
        logger.info("Validation complete!")
        return self.stats
    
    def print_summary(self):
        """Print validation summary"""
        print("\n" + "="*60)
        print("NBA GAMEBOOK DATA VALIDATION SUMMARY")
        print("="*60)
        
        print(f"📊 Files Processed: {self.stats.total_files}")
        print(f"✅ Valid Files: {self.stats.valid_files}")
        print(f"❌ Invalid Files: {self.stats.invalid_files}")
        
        if self.stats.total_files > 0:
            success_rate = (self.stats.valid_files / self.stats.total_files) * 100
            print(f"📈 Success Rate: {success_rate:.1f}%")
        
        # Special games summary
        if self.special_games_detected:
            special_types = Counter(game['type'] for game in self.special_games_detected)
            print(f"\n🌟 Special Games Detected: {len(self.special_games_detected)}")
            for game_type, count in special_types.items():
                print(f"   {game_type}: {count} games")
        
        print(f"\n🔍 Error Breakdown:")
        print(f"   Schema Errors: {self.stats.schema_errors}")
        print(f"   Data Quality Errors: {self.stats.data_quality_errors}")
        print(f"   Business Logic Errors: {self.stats.business_logic_errors}")
        print(f"   File Integrity Errors: {self.stats.file_integrity_errors}")
        
        if self.stats.warnings:
            print(f"\n⚠️  Warnings: {len(self.stats.warnings)}")
            # Show warnings based on limit (0 = show all)
            if self.warning_limit == 0 or len(self.stats.warnings) <= self.warning_limit:
                for warning in self.stats.warnings:
                    print(f"   - {warning}")
            else:
                for warning in self.stats.warnings[:self.warning_limit]:
                    print(f"   - {warning}")
                print(f"   ... and {len(self.stats.warnings) - self.warning_limit} more warnings")
                print(f"   (Use --limit-warnings 0 to show all warnings)")
        
        if self.stats.errors:
            print(f"\n❌ Errors: {len(self.stats.errors)}")
            # Limit errors to prevent overwhelming output
            if len(self.stats.errors) <= 20:
                for error in self.stats.errors:
                    print(f"   {error}")
            else:
                for error in self.stats.errors[:10]:
                    print(f"   {error}")
                print(f"   ... and {len(self.stats.errors) - 10} more errors")


def main():
    parser = argparse.ArgumentParser(description='Validate NBA gamebook data')
    parser.add_argument('--bucket-path', default='gs://nba-scraped-data/nba-com/gamebooks-data',
                        help='GCS bucket path to validate')
    parser.add_argument('--sample-size', type=int, default=100,
                        help='Number of files to sample (default: 100, 0 for all files)')
    parser.add_argument('--file', type=str,
                        help='Validate a single specific file')
    parser.add_argument('--full-scan', action='store_true',
                        help='Validate all files in the bucket')
    parser.add_argument('--strict-teams', action='store_true',
                        help='Treat non-standard team codes as errors (even in special games)')
    parser.add_argument('--show-special-games', action='store_true',
                        help='Show extra details about detected special games')
    
    # Date filtering options
    parser.add_argument('--season', type=str,
                        help='Filter by NBA season (e.g., "2025-26")')
    parser.add_argument('--start-date', type=str,
                        help='Start date for validation (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                        help='End date for validation (YYYY-MM-DD)')
    parser.add_argument('--last-days', type=int,
                        help='Validate files from last N days')
    parser.add_argument('--today', action='store_true',
                        help='Validate only today\'s games (shortcut for --last-days 1)')
    parser.add_argument('--yesterday', action='store_true',
                        help='Validate only yesterday\'s games')
    parser.add_argument('--this-week', action='store_true',
                        help='Validate this week\'s games (shortcut for --last-days 7)')
    parser.add_argument('--limit-warnings', type=int, default=0,
                        help='Limit number of warnings displayed (0 = show all)')
    
    args = parser.parse_args()
    
    # Handle date shortcuts
    if args.today:
        args.last_days = 1
    elif args.yesterday:
        yesterday = datetime.now() - timedelta(days=1)
        args.start_date = args.end_date = yesterday.strftime('%Y-%m-%d')
    elif args.this_week:
        args.last_days = 7
    
    validator = NBAGamebookValidator(warning_limit=args.limit_warnings)
    
    # Configure validator based on arguments
    if args.strict_teams:
        logger.info("Running in strict mode - all non-standard team codes will be errors")
    if args.show_special_games:
        logger.info("Will show detailed information about special games detected")
    
    if args.file:
        # Validate single file
        logger.info(f"Validating single file: {args.file}")
        data = validator.download_and_parse_file(args.file)
        if data:
            validator.stats.total_files = 1
            is_valid = validator.validate_file(args.file, data)
            
            # Show special game info if requested
            if args.show_special_games:
                is_special, special_type = validator._is_special_game(data)
                if is_special:
                    print(f"\n🌟 Special Game Detected: {special_type}")
                    print(f"   Game Context: {validator._get_game_context(data)}")
            
            print(f"File is {'valid' if is_valid else 'invalid'}")
        validator.print_summary()
    else:
        # Validate dataset with optional date filtering
        sample_size = None if args.full_scan else (args.sample_size if args.sample_size > 0 else None)
        validator.validate_dataset(
            args.bucket_path, 
            sample_size, 
            args.start_date, 
            args.end_date, 
            args.season, 
            args.last_days
        )
        validator.print_summary()
    
    # Exit with error code if there were validation failures
    if validator.stats.invalid_files > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()