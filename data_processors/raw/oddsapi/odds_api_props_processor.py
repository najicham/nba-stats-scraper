# processors/odds_api/odds_api_props_processor.py

import json
import logging
import re
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.utils.name_utils import normalize_name

logger = logging.getLogger(__name__)

class OddsApiPropsProcessor(ProcessorBase):
    """Process Odds API player props data."""
    
    # Team name mapping
    TEAM_MAPPING = {
        'Atlanta Hawks': 'ATL',
        'Boston Celtics': 'BOS',
        'Brooklyn Nets': 'BRK',
        'Charlotte Hornets': 'CHO',
        'Chicago Bulls': 'CHI',
        'Cleveland Cavaliers': 'CLE',
        'Dallas Mavericks': 'DAL',
        'Denver Nuggets': 'DEN',
        'Detroit Pistons': 'DET',
        'Golden State Warriors': 'GSW',
        'Houston Rockets': 'HOU',
        'Indiana Pacers': 'IND',
        'Los Angeles Clippers': 'LAC',
        'Los Angeles Lakers': 'LAL',
        'Memphis Grizzlies': 'MEM',
        'Miami Heat': 'MIA',
        'Milwaukee Bucks': 'MIL',
        'Minnesota Timberwolves': 'MIN',
        'New Orleans Pelicans': 'NOP',
        'New York Knicks': 'NYK',
        'Oklahoma City Thunder': 'OKC',
        'Orlando Magic': 'ORL',
        'Philadelphia 76ers': 'PHI',
        'Phoenix Suns': 'PHO',
        'Portland Trail Blazers': 'POR',
        'Sacramento Kings': 'SAC',
        'San Antonio Spurs': 'SAS',
        'Toronto Raptors': 'TOR',
        'Utah Jazz': 'UTA',
        'Washington Wizards': 'WAS'
    }
    
    # Abbreviated team codes for parsing file paths
    TEAM_ABBR_MAP = {v: k for k, v in TEAM_MAPPING.items()}

    def __init__(self):
        super().__init__()
        self.project_id = "nba-props-platform"
        self.bq_client = bigquery.Client(project=self.project_id)
        self.table_name = 'nba_raw.odds_api_player_points_props'
        self.processing_strategy = 'APPEND_ALWAYS'
        
    def get_team_abbr(self, team_name: str) -> str:
        """Get team abbreviation from full name."""
        # Direct lookup
        if team_name in self.TEAM_MAPPING:
            return self.TEAM_MAPPING[team_name]
        
        # Try partial matching for slight variations
        team_lower = team_name.lower()
        for full_name, abbr in self.TEAM_MAPPING.items():
            if team_lower in full_name.lower() or full_name.lower() in team_lower:
                return abbr
        
        logger.warning(f"Unknown team name: {team_name}")
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
    
    def extract_metadata_from_path(self, file_path: str) -> Dict:
        """
        Extract metadata from file path.
        Example: odds-api/player-props-history/2023-10-24/fd55db2fa9ee5be1f108be5151e2ecb0-LALDEN/20250812_035909-snap-2130.json
        """
        path_parts = file_path.split('/')
        
        # Extract date
        date_str = path_parts[-3]  # "2023-10-24"
        
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
            'source_file_path': file_path
        }
    
    def calculate_minutes_before_tipoff(self, game_start: datetime, snapshot: datetime) -> int:
        """Calculate minutes between snapshot and game start time."""
        diff = game_start - snapshot
        return int(diff.total_seconds() / 60)
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON data structure."""
        errors = []
        
        if not data:
            errors.append("Empty data")
            return errors
            
        if 'data' not in data:
            errors.append("Missing 'data' field")
            return errors
            
        game_data = data.get('data', {})
        
        # Check required fields
        required_fields = ['id', 'commence_time', 'home_team', 'away_team', 'bookmakers']
        for field in required_fields:
            if field not in game_data:
                errors.append(f"Missing required field: {field}")
        
        # Validate bookmakers
        bookmakers = game_data.get('bookmakers', [])
        if not bookmakers:
            errors.append("No bookmakers found")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform Odds API props data to BigQuery rows."""
        rows = []
        
        # Validate data first
        errors = self.validate_data(raw_data)
        if errors:
            logger.error(f"Validation errors for {file_path}: {errors}")
            return rows
        
        # Extract metadata from file path
        metadata = self.extract_metadata_from_path(file_path)
        
        # Get main data
        game_data = raw_data.get('data', {})
        
        # Parse timestamps
        snapshot_timestamp = raw_data.get('timestamp')
        if snapshot_timestamp:
            snapshot_dt = datetime.fromisoformat(snapshot_timestamp.replace('Z', '+00:00'))
        else:
            logger.warning(f"No snapshot timestamp in {file_path}")
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
        
        # Get team abbreviations
        home_team_abbr = self.get_team_abbr(game_data.get('home_team', ''))
        away_team_abbr = self.get_team_abbr(game_data.get('away_team', ''))
        
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
                        
                        # Teams
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
                        'source_file_path': file_path
                    }
                    
                    rows.append(row)
        
        logger.info(f"Processed {len(rows)} prop records from {file_path}")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        import datetime
        for row in rows:
            for key, value in row.items():
                if isinstance(value, (datetime.date, datetime.datetime)):
                    row[key] = value.isoformat()
        """Load data to BigQuery using APPEND_ALWAYS strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        
        # Load to BigQuery
        errors = []
        try:
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend(result)
                logger.error(f"BigQuery insert errors: {result}")
        except Exception as e:
            logger.error(f"Failed to insert rows: {e}")
            errors.append(str(e))
        
        return {
            'rows_processed': len(rows),
            'errors': errors
        }