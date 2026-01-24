#!/usr/bin/env python3
"""
BDL Data Structure Analysis Script
Purpose: Test BDL box score data to determine if backup sources needed
Usage: Run against 1-2 recent games to analyze data completeness
"""

import json
import requests
from datetime import datetime, timedelta
import os
from pathlib import Path

# Load .env file if it exists
def load_env_file():
    env_path = Path('.env')
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env_file()

class BdlDataAnalyzer:
    def __init__(self):
        self.api_key = os.getenv('BDL_API_KEY')
        self.base_url = "https://api.balldontlie.io/v1"  # Match your scraper
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
    
    def test_recent_game_data(self, test_date=None):
        """Test BDL data structure for recent games"""
        if not test_date:
            # Use yesterday as default test date
            test_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        print(f"🔍 Testing BDL data structure for {test_date}")
        
        # Get box scores for the test date (matching your actual scraper)
        url = f"{self.base_url}/box_scores"
        params = {
            'date': test_date,  # BDL box_scores uses 'date' not 'dates[]'
            'per_page': 100
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get('data'):
                print(f"❌ No games found for {test_date}")
                return None

            return self.analyze_data_structure(data, test_date)

        except requests.exceptions.Timeout:
            print(f"❌ Request timed out after 30 seconds")
            return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching data: {e}")
            return None
    
    def analyze_data_structure(self, data, test_date):
        """Analyze the structure and completeness of BDL data"""
        games = data['data']
        total_games = len(games)
        
        print(f"\n📊 Analysis Results for {test_date}")
        print(f"Total games: {total_games}")
        
        # Extract all player records from all games
        all_players = []
        for game in games:
            # Add home team players
            home_players = game.get('home_team', {}).get('players', [])
            for player in home_players:
                player['team'] = game['home_team']['abbreviation']
                player['game_id'] = f"{game['visitor_team']['abbreviation']}@{game['home_team']['abbreviation']}"
            all_players.extend(home_players)
            
            # Add visitor team players  
            visitor_players = game.get('visitor_team', {}).get('players', [])
            for player in visitor_players:
                player['team'] = game['visitor_team']['abbreviation']
                player['game_id'] = f"{game['visitor_team']['abbreviation']}@{game['home_team']['abbreviation']}"
            all_players.extend(visitor_players)
        
        total_players = len(all_players)
        print(f"Total player records: {total_players}")
        
        # Sample player record for structure analysis
        if all_players:
            sample_player = all_players[0]
            print(f"\n🏀 Sample Player Record Structure:")
            self.print_nested_dict(sample_player, indent=2)
        
        # Check for injury/DNP indicators
        dnp_indicators = []
        injury_indicators = []
        zero_minutes_count = 0
        
        # Analyze all players for patterns
        for player in all_players:
            # Check for zero/null minutes (potential DNP indicator)
            minutes = player.get('min')
            if minutes == '00' or minutes == '' or minutes is None:
                zero_minutes_count += 1
                
                # Look for DNP indicators in the record
                dnp_reasons = self.check_dnp_indicators(player)
                if dnp_reasons:
                    dnp_indicators.extend(dnp_reasons)
        
        print(f"\n📈 Data Completeness Analysis:")
        print(f"Players with 0 minutes: {zero_minutes_count}")
        print(f"Players who played: {total_players - zero_minutes_count}")
        print(f"Potential DNP indicators found: {len(set(dnp_indicators))}")
        if dnp_indicators:
            print(f"DNP indicator types: {set(dnp_indicators)}")
        
        # Show some examples of DNP vs played players
        dnp_players = [p for p in all_players if p.get('min') == '00']
        played_players = [p for p in all_players if p.get('min') != '00']
        
        if dnp_players:
            print(f"\n🚫 Sample DNP Player:")
            sample_dnp = dnp_players[0]
            player_info = sample_dnp.get('player', {})
            print(f"  {player_info.get('first_name', '')} {player_info.get('last_name', '')} ({sample_dnp.get('team', '')}) - {sample_dnp.get('min', '')} min")
        
        if played_players:
            print(f"\n✅ Sample Active Player:")
            sample_active = played_players[0]
            player_info = sample_active.get('player', {})
            print(f"  {player_info.get('first_name', '')} {player_info.get('last_name', '')} ({sample_active.get('team', '')}) - {sample_active.get('min', '')} min, {sample_active.get('pts', 0)} pts")
        
        # Check stat completeness on actual player records
        self.analyze_stat_completeness(all_players)
        
        return {
            'total_games': total_games,
            'total_players': total_players,
            'zero_minutes_count': zero_minutes_count,
            'dnp_indicators': list(set(dnp_indicators)),
            'sample_structure': sample_player if all_players else None
        }
    
    def check_dnp_indicators(self, player):
        """Look for DNP/injury indicators in player record"""
        indicators = []
        
        # Common fields that might contain DNP/injury info
        check_fields = ['comment', 'status', 'injury_status', 'dnp_reason', 
                       'game_status', 'player_status']
        
        for field in check_fields:
            if field in player and player[field]:
                indicators.append(field)
        
        # Check if all stats are zero (another DNP indicator)
        stat_fields = ['pts', 'reb', 'ast', 'stl', 'blk']
        all_zero_stats = all(player.get(field, 0) == 0 for field in stat_fields)
        if all_zero_stats and player.get('min') in ['00', '', None]:
            indicators.append('all_zero_stats_no_minutes')
        
        return indicators
    
    def analyze_stat_completeness(self, players):
        """Analyze what stats are available"""
        if not players:
            return
        
        # Get all available stat fields
        all_fields = set()
        for player in players:
            all_fields.update(player.keys())
        
        # Common NBA stats we need for prop betting (using BDL field names)
        prop_relevant_stats = [
            'pts', 'reb', 'ast', 'stl', 'blk', 'turnover', 
            'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta',  # BDL uses 'fgm' not 'fg_made'
            'oreb', 'dreb', 'min'
        ]
        
        print(f"\n📊 Stat Field Analysis:")
        print(f"Total fields available: {len(all_fields)}")
        print(f"All fields: {sorted(all_fields)}")
        
        print(f"\n🎯 Prop-Relevant Stats Coverage:")
        for stat in prop_relevant_stats:
            available = stat in all_fields
            status = "✅" if available else "❌"
            print(f"{status} {stat}")
        
        missing_stats = [stat for stat in prop_relevant_stats if stat not in all_fields]
        if missing_stats:
            print(f"\n⚠️  Missing stats: {missing_stats}")
        else:
            print(f"\n✅ All prop-relevant stats available!")
    
    def print_nested_dict(self, d, indent=0):
        """Pretty print nested dictionary structure"""
        for key, value in d.items():
            print("  " * indent + f"{key}: {type(value).__name__}")
            if isinstance(value, dict) and indent < 2:  # Limit recursion
                self.print_nested_dict(value, indent + 1)
            elif isinstance(value, list) and value and isinstance(value[0], dict) and indent < 2:
                print("  " * (indent + 1) + f"[0]: {type(value[0]).__name__}")
                if indent < 1:
                    self.print_nested_dict(value[0], indent + 2)
            else:
                # Show actual value for simple types
                display_value = value if not isinstance(value, str) or len(str(value)) < 50 else f"{str(value)[:47]}..."
                print("  " * indent + f"{key}: {display_value}")

def main():
    """Run the BDL data structure analysis"""
    analyzer = BdlDataAnalyzer()
    
    # Test with playoff dates (April 2024) when games were happening
    test_dates = [
        '2024-04-20',  # Playoffs Game 1 date
        '2024-04-22',  # Playoffs Game 2 date
        '2024-04-16',  # Regular season end
    ]
    
    for test_date in test_dates:
        result = analyzer.test_recent_game_data(test_date)
        if result:
            print(f"\n" + "="*60)
        else:
            print(f"Skipping {test_date} - no data available")

if __name__ == "__main__":
    main()