#!/usr/bin/env python3
# File: processors/nbacom/nbac_player_boxscore_processor.py
# Description: Processor for NBA.com player boxscore data transformation

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from processors.processor_base import ProcessorBase
from shared.utils.nba_team_mapper import NBATeamMapper

class NbacPlayerBoxscoreProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_player_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'
        self.team_mapper = NBATeamMapper()
        
    def normalize_player_name(self, name: str) -> str:
        """Normalize player names for cross-source matching."""
        if not name:
            return ""
        
        # Convert to lowercase and remove common suffixes
        normalized = name.lower().strip()
        normalized = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', normalized, flags=re.IGNORECASE)
        
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def safe_int(self, value) -> Optional[int]:
        """Safely convert value to int, handling None, empty strings, etc."""
        if value is None or value == "":
            return None
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return None
    
    def safe_float(self, value) -> Optional[float]:
        """Safely convert value to float, handling None, empty strings, etc."""
        if value is None or value == "":
            return None
        try:
            return float(str(value))
        except (ValueError, TypeError):
            return None
    
    def determine_season_year(self, game_date: str) -> int:
        """Determine NBA season year from game date."""
        from datetime import datetime
        date_obj = datetime.strptime(game_date, '%Y-%m-%d')
        
        # NBA season runs Oct-June, so games Oct+ are start of new season
        if date_obj.month >= 10:
            return date_obj.year
        else:
            return date_obj.year - 1
    
    def construct_game_id(self, game_date: str, home_team_abbr: str, away_team_abbr: str) -> str:
        """Construct consistent game_id format."""
        date_str = game_date.replace('-', '')
        return f"{date_str}_{away_team_abbr}_{home_team_abbr}"
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the transformed data."""
        errors = []
        
        if 'game' not in data:
            errors.append("Missing 'game' section in data")
            return errors
        
        game = data['game']
        if 'gameId' not in game:
            errors.append("Missing gameId in game data")
        
        if 'players' not in data:
            errors.append("Missing 'players' section in data")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform NBA.com player boxscore data into BigQuery format."""
        try:
            # Parse the raw JSON data
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            
            # Validate data structure
            validation_errors = self.validate_data(data)
            if validation_errors:
                logging.error(f"Data validation failed for {file_path}: {validation_errors}")
                return []
            
            game_info = data['game']
            players_data = data.get('players', [])
            
            # Extract basic game information
            nba_game_id = str(game_info['gameId'])
            game_code = game_info.get('gameCode', '')
            game_status = game_info.get('gameStatusText', 'Final')
            period = self.safe_int(game_info.get('period', 4))
            
            # Parse game date from gameCode or file path
            if '/' in game_code:
                date_part = game_code.split('/')[0]
                game_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            else:
                # Extract date from file path as fallback
                import re
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_path)
                if date_match:
                    game_date = date_match.group(1)
                else:
                    logging.error(f"Could not extract game date from {file_path}")
                    return []
            
            season_year = self.determine_season_year(game_date)
            
            # Get team information
            home_team = game_info.get('homeTeam', {})
            away_team = game_info.get('awayTeam', {})
            
            home_team_abbr = self.team_mapper.normalize_team_abbr(
                home_team.get('teamTricode', home_team.get('teamName', ''))
            )
            away_team_abbr = self.team_mapper.normalize_team_abbr(
                away_team.get('teamTricode', away_team.get('teamName', ''))
            )
            
            if not home_team_abbr or not away_team_abbr:
                logging.error(f"Could not map team names for {file_path}")
                return []
            
            game_id = self.construct_game_id(game_date, home_team_abbr, away_team_abbr)
            
            rows = []
            current_time = datetime.now(timezone.utc).isoformat()
            
            # Process each player
            for player_data in players_data:
                try:
                    # Player identification
                    nba_player_id = self.safe_int(player_data.get('playerId'))
                    player_full_name = player_data.get('playerName', '').strip()
                    player_lookup = self.normalize_player_name(player_full_name)
                    
                    if not player_full_name or not nba_player_id:
                        logging.warning(f"Skipping player with missing name or ID in {game_id}")
                        continue
                    
                    # Team information for this player
                    player_team_id = self.safe_int(player_data.get('teamId'))
                    player_team_name = player_data.get('teamName', '')
                    team_abbr = self.team_mapper.normalize_team_abbr(player_team_name)
                    
                    if not team_abbr:
                        logging.warning(f"Could not map team for player {player_full_name}")
                        continue
                    
                    # Basic player info
                    jersey_number = str(player_data.get('jerseyNumber', '')) if player_data.get('jerseyNumber') else None
                    position = player_data.get('position', '')
                    starter = player_data.get('starter') == '1' or player_data.get('starter') is True
                    
                    # Playing time
                    minutes = player_data.get('minutes', '')
                    
                    # Core statistics
                    stats = player_data.get('statistics', {})
                    points = self.safe_int(stats.get('points'))
                    field_goals_made = self.safe_int(stats.get('fieldGoalsMade'))
                    field_goals_attempted = self.safe_int(stats.get('fieldGoalsAttempted'))
                    field_goal_percentage = self.safe_float(stats.get('fieldGoalsPercentage'))
                    
                    three_pointers_made = self.safe_int(stats.get('threePointersMade'))
                    three_pointers_attempted = self.safe_int(stats.get('threePointersAttempted'))
                    three_point_percentage = self.safe_float(stats.get('threePointersPercentage'))
                    
                    free_throws_made = self.safe_int(stats.get('freeThrowsMade'))
                    free_throws_attempted = self.safe_int(stats.get('freeThrowsAttempted'))
                    free_throw_percentage = self.safe_float(stats.get('freeThrowsPercentage'))
                    
                    # Rebounds and other stats
                    offensive_rebounds = self.safe_int(stats.get('reboundsOffensive'))
                    defensive_rebounds = self.safe_int(stats.get('reboundsDefensive'))
                    total_rebounds = self.safe_int(stats.get('reboundsTotal'))
                    assists = self.safe_int(stats.get('assists'))
                    steals = self.safe_int(stats.get('steals'))
                    blocks = self.safe_int(stats.get('blocks'))
                    turnovers = self.safe_int(stats.get('turnovers'))
                    personal_fouls = self.safe_int(stats.get('foulsPersonal'))
                    
                    # Advanced stats (may not be available in all data)
                    plus_minus = self.safe_int(stats.get('plusMinus'))
                    flagrant_fouls = self.safe_int(stats.get('foulsFlagrant'))
                    technical_fouls = self.safe_int(stats.get('foulsTechnical'))
                    
                    # Create the row
                    row = {
                        # Core identifiers
                        'game_id': game_id,
                        'game_date': game_date,
                        'season_year': season_year,
                        'season_type': 'Regular Season',  # Default, could be enhanced
                        
                        # Game context
                        'nba_game_id': nba_game_id,
                        'game_code': game_code,
                        'game_status': game_status,
                        'period': period,
                        'is_playoff_game': False,  # Could be enhanced based on season_type
                        
                        # Team information
                        'home_team_id': self.safe_int(home_team.get('teamId')),
                        'home_team_abbr': home_team_abbr,
                        'home_team_score': self.safe_int(game_info.get('homeTeamScore')),
                        'away_team_id': self.safe_int(away_team.get('teamId')),
                        'away_team_abbr': away_team_abbr,
                        'away_team_score': self.safe_int(game_info.get('awayTeamScore')),
                        
                        # Player identification
                        'nba_player_id': nba_player_id,
                        'player_full_name': player_full_name,
                        'player_lookup': player_lookup,
                        'team_id': player_team_id,
                        'team_abbr': team_abbr,
                        'jersey_number': jersey_number,
                        'position': position,
                        'starter': starter,
                        
                        # Core statistics
                        'minutes': minutes if minutes else None,
                        'points': points,
                        'field_goals_made': field_goals_made,
                        'field_goals_attempted': field_goals_attempted,
                        'field_goal_percentage': field_goal_percentage,
                        'three_pointers_made': three_pointers_made,
                        'three_pointers_attempted': three_pointers_attempted,
                        'three_point_percentage': three_point_percentage,
                        'free_throws_made': free_throws_made,
                        'free_throws_attempted': free_throws_attempted,
                        'free_throw_percentage': free_throw_percentage,
                        
                        # Advanced statistics
                        'offensive_rebounds': offensive_rebounds,
                        'defensive_rebounds': defensive_rebounds,
                        'total_rebounds': total_rebounds,
                        'assists': assists,
                        'steals': steals,
                        'blocks': blocks,
                        'turnovers': turnovers,
                        'personal_fouls': personal_fouls,
                        'flagrant_fouls': flagrant_fouls,
                        'technical_fouls': technical_fouls,
                        'plus_minus': plus_minus,
                        
                        # Enhanced metrics (set to None, could be calculated or extracted)
                        'true_shooting_pct': None,
                        'effective_fg_pct': None,
                        'usage_rate': None,
                        'offensive_rating': None,
                        'defensive_rating': None,
                        'pace': None,
                        'pie': None,
                        
                        # Quarter breakdown (set to None, would need quarter-by-quarter data)
                        'points_q1': None,
                        'points_q2': None,
                        'points_q3': None,
                        'points_q4': None,
                        'points_ot': None,
                        
                        # Processing metadata
                        'source_file_path': file_path,
                        'scrape_timestamp': game_info.get('timestamp', current_time),
                        'created_at': current_time,
                        'processed_at': current_time
                    }
                    
                    rows.append(row)
                    
                except Exception as e:
                    logging.error(f"Error processing player {player_data.get('playerName', 'unknown')} in {game_id}: {str(e)}")
                    continue
            
            logging.info(f"Transformed {len(rows)} player records for game {game_id}")
            return rows
            
        except Exception as e:
            logging.error(f"Error transforming data from {file_path}: {str(e)}")
            return []
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load transformed data into BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this game first
                game_id = rows[0]['game_id']
                delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}'"
                logging.info(f"Deleting existing records for game {game_id}")
                self.bq_client.query(delete_query).result()
            
            # Insert new data
            logging.info(f"Inserting {len(rows)} rows into {table_id}")
            result = self.bq_client.insert_rows_json(table_id, rows)
            
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully loaded {len(rows)} rows for game {rows[0]['game_id']}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data to BigQuery: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0, 
            'errors': errors,
            'game_id': rows[0]['game_id'] if rows else None
        }