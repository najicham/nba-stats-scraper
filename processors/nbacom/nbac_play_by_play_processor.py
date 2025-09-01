#!/usr/bin/env python3
# File: processors/nbacom/nbac_play_by_play_processor.py
# Description: Processor for NBA.com play-by-play data transformation

import json
import logging
import re
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class NbacPlayByPlayProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_play_by_play'
        self.processing_strategy = 'MERGE_UPDATE'  # Replace existing game data
        
        # NBA team ID to abbreviation mapping
        self.team_id_mapping = {
            1610612737: 'ATL', 1610612738: 'BOS', 1610612751: 'BRK', 1610612766: 'CHA',
            1610612741: 'CHI', 1610612739: 'CLE', 1610612742: 'DAL', 1610612743: 'DEN',
            1610612765: 'DET', 1610612744: 'GSW', 1610612745: 'HOU', 1610612754: 'IND',
            1610612746: 'LAC', 1610612747: 'LAL', 1610612763: 'MEM', 1610612748: 'MIA',
            1610612749: 'MIL', 1610612750: 'MIN', 1610612740: 'NOP', 1610612752: 'NYK',
            1610612760: 'OKC', 1610612753: 'ORL', 1610612755: 'PHI', 1610612756: 'PHX',
            1610612757: 'POR', 1610612758: 'SAC', 1610612759: 'SAS', 1610612761: 'TOR',
            1610612762: 'UTA', 1610612764: 'WAS'
        }
    
    def normalize_player_name(self, name: str) -> str:
        """Normalize player name for cross-table joins."""
        if not name:
            return ""
        
        # Remove common suffixes and normalize
        name = name.lower().strip()
        name = re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', name)
        name = re.sub(r'[^a-z0-9]', '', name)
        return name
    
    def parse_game_clock(self, clock_str: str) -> Tuple[str, int, int]:
        """
        Parse NBA.com clock format PT11M46.00S to components.
        Returns: (original_string, seconds_remaining, total_elapsed_seconds)
        """
        if not clock_str or not clock_str.startswith('PT'):
            return clock_str or "", 0, 0
        
        try:
            # Extract minutes and seconds from PT11M46.00S format
            time_part = clock_str[2:]  # Remove 'PT'
            
            if 'M' in time_part and 'S' in time_part:
                minutes_part = time_part.split('M')[0]
                seconds_part = time_part.split('M')[1].replace('S', '')
                
                minutes = int(float(minutes_part))
                seconds = float(seconds_part)
                
                total_seconds_remaining = minutes * 60 + int(seconds)
                
                # Calculate elapsed time (12 minutes = 720 seconds per quarter)
                quarter_length = 720
                total_elapsed = quarter_length - total_seconds_remaining
                
                return f"{minutes:02d}:{int(seconds):02d}", total_seconds_remaining, total_elapsed
            
        except (ValueError, IndexError) as e:
            logging.warning(f"Failed to parse clock: {clock_str}, error: {e}")
        
        return clock_str, 0, 0
    
    def calculate_shot_distance(self, x: float, y: float) -> float:
        """Calculate shot distance from basket coordinates."""
        if x is None or y is None:
            return 0.0
        
        # NBA court: basket is at (25, 5.25) in feet coordinates
        basket_x, basket_y = 25.0, 5.25
        distance = math.sqrt((x - basket_x) ** 2 + (y - basket_y) ** 2)
        return round(distance, 1)
    
    def determine_shot_zone(self, x: float, y: float, distance: float) -> Tuple[str, str]:
        """
        Determine shot zone and category from coordinates.
        Returns: (detailed_zone, category)
        """
        if x is None or y is None or distance == 0:
            return "Unknown", "Unknown"
        
        if distance < 4:
            return "Paint", "Paint"
        elif distance < 23:
            # Mid-range zones based on court position
            if y < 8:  # Below free throw line
                return "Mid-Range Baseline", "Mid-Range"
            elif y > 19:  # Above 3PT line
                return "Mid-Range Elbow", "Mid-Range"
            else:
                return "Mid-Range", "Mid-Range"
        else:
            # 3-point zones
            if y < 8 or y > 39:  # Corner 3s
                return f"Corner 3PT {'Left' if x < 25 else 'Right'}", "3PT"
            else:
                return "Above Break 3PT", "3PT"
    
    def build_player_team_lookup(self, actions: List[Dict]) -> Dict[int, str]:
        """Build player_id -> team_abbr mapping from play-by-play actions."""
        player_teams = {}
        for action in actions:
            if action.get('personId') and action.get('teamTricode') and action.get('personId') != 0:
                player_teams[action['personId']] = action['teamTricode']
            
            # Also collect secondary players with teams
            if action.get('jumpBallWonPersonId') and action.get('teamTricode'):
                player_teams[action['jumpBallWonPersonId']] = action['teamTricode']
            
            # For jump ball lost player, they're typically on the opposing team
            # We'll handle this in the player extraction method
        
        return player_teams
    
    def extract_players_from_action(self, action: Dict, player_team_lookup: Dict[int, str]) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
        """Extract up to 3 players from an action using game-based team lookup."""
        players = [None, None, None]
        
        # Primary player (personId)
        if action.get('personId') and action.get('personId') != 0:
            player_id = action['personId']
            players[0] = {
                'id': player_id,
                'lookup': self.normalize_player_name(action.get('playerName', '')),
                'team_abbr': player_team_lookup.get(player_id, action.get('teamTricode', ''))
            }
        
        # Secondary players from specific event types
        if action.get('actionType') == 'jumpball':
            # Jump ball won player
            if action.get('jumpBallWonPersonId'):
                won_player_id = action['jumpBallWonPersonId']
                players[1] = {
                    'id': won_player_id,
                    'lookup': self.normalize_player_name(action.get('jumpBallWonPlayerName', '')),
                    'team_abbr': player_team_lookup.get(won_player_id, '')
                }
            
            # Jump ball lost player  
            if action.get('jumpBallLostPersonId'):
                lost_player_id = action['jumpBallLostPersonId']
                players[2] = {
                    'id': lost_player_id,
                    'lookup': self.normalize_player_name(action.get('jumpBallLostPlayerName', '')),
                    'team_abbr': player_team_lookup.get(lost_player_id, '')
                }
        
        elif action.get('foulDrawnPersonId'):
            # Foul drawn player
            drawn_player_id = action['foulDrawnPersonId']
            players[1] = {
                'id': drawn_player_id,
                'lookup': self.normalize_player_name(action.get('foulDrawnPlayerName', '')),
                'team_abbr': player_team_lookup.get(drawn_player_id, '')
            }
        
        return tuple(players)
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate play-by-play data structure."""
        errors = []
        
        if 'playByPlay' not in data:
            errors.append("Missing playByPlay field")
            return errors
        
        if 'game' not in data['playByPlay']:
            errors.append("Missing game field in playByPlay")
            return errors
        
        if 'actions' not in data['playByPlay']['game']:
            errors.append("Missing actions array in game")
            return errors
        
        actions = data['playByPlay']['game']['actions']
        if not actions:
            errors.append("Empty actions array")
            return errors
        
        # Validate key fields in first few actions
        for i, action in enumerate(actions[:5]):
            if 'actionNumber' not in action:
                errors.append(f"Missing actionNumber in action {i}")
            if 'period' not in action:
                errors.append(f"Missing period in action {i}")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform NBA.com play-by-play JSON to BigQuery rows."""
        rows = []
        
        try:
            # Extract metadata
            metadata = raw_data.get('metadata', {})
            play_by_play = raw_data['playByPlay']
            game_info = play_by_play['game']
            
            nba_game_id = metadata.get('game_id') or game_info.get('gameId')
            season_str = metadata.get('season', '2024-25')
            season_year = int(season_str.split('-')[0])
            
            # Extract game date from file path
            # Format: /nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json
            path_parts = file_path.split('/')
            game_date_str = None
            for part in path_parts:
                if re.match(r'\d{4}-\d{2}-\d{2}', part):
                    game_date_str = part
                    break
            
            # Process actions
            actions = game_info.get('actions', [])
            
            # First pass: build comprehensive player-team lookup from game data
            player_team_lookup = self.build_player_team_lookup(actions)
            logging.info(f"Built player-team lookup for {len(player_team_lookup)} players")
            
            # Determine teams that played (we still can't determine home/away without schedule)
            teams_in_game = set()
            for action in actions:
                if action.get('teamTricode'):
                    teams_in_game.add(action['teamTricode'])
            
            teams_list = list(teams_in_game)
            # For now, assign teams arbitrarily - this needs schedule cross-reference
            team_1 = teams_list[0] if len(teams_list) > 0 else None
            team_2 = teams_list[1] if len(teams_list) > 1 else None
            
            # NOTE: Home/away determination requires schedule cross-reference (future enhancement)
            home_team_abbr = team_1  # First team found - not necessarily home team
            away_team_abbr = team_2  # Second team found - not necessarily away team
            
            # Second pass: process each action with complete context
            for action in actions:
                # Parse game clock
                game_clock, clock_seconds, elapsed_seconds = self.parse_game_clock(action.get('clock', ''))
                
                # Extract shot data
                x = action.get('x')
                y = action.get('y')
                shot_distance = 0.0
                shot_made = None
                shot_type = None
                
                # Calculate shot distance if coordinates available
                if x is not None and y is not None:
                    shot_distance = self.calculate_shot_distance(x, y)
                
                # Determine if shot was made and type
                if action.get('isFieldGoal') == 1 or action.get('actionType') in ['fieldgoal', 'fieldgoalmade']:
                    shot_made = action.get('subType') == 'made' if action.get('subType') else None
                    # Determine shot type from action details
                    if '3pt' in str(action.get('subType', '')).lower() or '3pt' in str(action.get('actionType', '')).lower():
                        shot_type = "3PT"
                    else:
                        shot_type = "2PT"
                elif action.get('actionType') == 'freethrow':
                    shot_made = action.get('subType') == 'made'
                    shot_type = "FT"
                
                # Extract players using game-based team lookup
                player_1, player_2, player_3 = self.extract_players_from_action(action, player_team_lookup)
                
                # Build game_id in consistent format
                if home_team_abbr and away_team_abbr and game_date_str:
                    game_id = f"{game_date_str.replace('-', '')}_{away_team_abbr}_{home_team_abbr}"
                else:
                    game_id = f"unknown_{nba_game_id}"
                
                row = {
                    # Core identifiers
                    'game_id': game_id,
                    'nba_game_id': str(nba_game_id),
                    'game_date': game_date_str,
                    'season_year': season_year,
                    'home_team_abbr': home_team_abbr,  # NOTE: Requires schedule lookup for accurate assignment
                    'away_team_abbr': away_team_abbr,  # NOTE: Requires schedule lookup for accurate assignment
                    
                    # Event identifiers
                    'event_id': str(action.get('actionNumber', 0)),
                    'event_sequence': action.get('actionNumber', 0),
                    'period': action.get('period', 1),
                    
                    # Game clock
                    'game_clock': game_clock,
                    'game_clock_seconds': clock_seconds,
                    'time_elapsed_seconds': elapsed_seconds,
                    
                    # Event details
                    'event_type': action.get('actionType', ''),
                    'event_action_type': action.get('subType', ''),
                    'event_description': action.get('description', ''),
                    'score_home': int(action.get('scoreHome', 0)),
                    'score_away': int(action.get('scoreAway', 0)),
                    
                    # Players (now with accurate team assignments from game data)
                    'player_1_id': player_1['id'] if player_1 else None,
                    'player_1_lookup': player_1['lookup'] if player_1 else None,
                    'player_1_team_abbr': player_1['team_abbr'] if player_1 else None,
                    'player_2_id': player_2['id'] if player_2 else None,
                    'player_2_lookup': player_2['lookup'] if player_2 else None,
                    'player_2_team_abbr': player_2['team_abbr'] if player_2 else None,
                    'player_3_id': player_3['id'] if player_3 else None,
                    'player_3_lookup': player_3['lookup'] if player_3 else None,
                    'player_3_team_abbr': player_3['team_abbr'] if player_3 else None,
                    
                    # Shot details (simplified - no complex zones)
                    'shot_made': shot_made,
                    'shot_type': shot_type,
                    'shot_x': x,
                    'shot_y': y,
                    'shot_distance': shot_distance,
                    
                    # Video (not available in current data)
                    'video_available': False,
                    'video_url': None,
                    
                    # Processing metadata
                    'source_file_path': file_path,
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                rows.append(row)
        
        except Exception as e:
            logging.error(f"Error transforming play-by-play data: {e}")
            return []
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load play-by-play data to BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this game first
                game_id = rows[0]['game_id']
                delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}'"
                self.bq_client.query(delete_query).result()
                logging.info(f"Deleted existing data for game_id: {game_id}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
            else:
                logging.info(f"Successfully inserted {len(rows)} play-by-play events")
        
        except Exception as e:
            errors.append(str(e))
            logging.error(f"Error loading play-by-play data: {e}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors,
            'events_processed': len(rows)
        }