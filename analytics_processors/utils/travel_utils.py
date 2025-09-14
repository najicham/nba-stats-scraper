"""
File: analytics_processors/utils/travel_utils.py

NBA Travel Distance Utilities
Simple interface for processors to get travel distances and time zone information
"""

from google.cloud import bigquery
from typing import Optional, Dict, List, Tuple
import pandas as pd
from datetime import datetime, timedelta

class NBATravel:
    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id
        
        # Cache for frequently accessed data
        self._distance_cache = {}
        self._team_locations_cache = None
    
    def get_travel_distance(self, from_team: str, to_team: str) -> Optional[Dict]:
        """
        Get travel information between two NBA teams
        
        Args:
            from_team: 3-letter team abbreviation (e.g., 'LAL')
            to_team: 3-letter team abbreviation (e.g., 'BOS')
            
        Returns:
            Dict with distance_miles, time_zones_crossed, travel_direction, jet_lag_factor
            None if teams are invalid or same
        """
        if from_team == to_team:
            return {
                'distance_miles': 0,
                'time_zones_crossed': 0,
                'travel_direction': 'neutral',
                'jet_lag_factor': 0.0
            }
        
        # Check cache first
        cache_key = f"{from_team}_{to_team}"
        if cache_key in self._distance_cache:
            return self._distance_cache[cache_key]
        
        query = f"""
        SELECT 
            distance_miles,
            time_zones_crossed,
            travel_direction,
            jet_lag_factor
        FROM `{self.project_id}.nba_enriched.travel_distances`
        WHERE from_team = @from_team AND to_team = @to_team
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("from_team", "STRING", from_team),
                bigquery.ScalarQueryParameter("to_team", "STRING", to_team)
            ]
        )
        
        try:
            result = self.client.query(query, job_config=job_config).to_dataframe()
            if len(result) > 0:
                travel_info = {
                    'distance_miles': int(result.iloc[0]['distance_miles']),
                    'time_zones_crossed': int(result.iloc[0]['time_zones_crossed']),
                    'travel_direction': result.iloc[0]['travel_direction'],
                    'jet_lag_factor': float(result.iloc[0]['jet_lag_factor'])
                }
                # Cache the result
                self._distance_cache[cache_key] = travel_info
                return travel_info
        except Exception as e:
            print(f"Error getting travel distance: {e}")
        
        return None
    
    def get_team_location(self, team_abbr: str) -> Optional[Dict]:
        """
        Get location information for a team
        
        Args:
            team_abbr: 3-letter team abbreviation
            
        Returns:
            Dict with city, state, arena_name, latitude, longitude, timezone, airport_code
        """
        if self._team_locations_cache is None:
            self._load_team_locations_cache()
        
        return self._team_locations_cache.get(team_abbr)
    
    def _load_team_locations_cache(self):
        """Load all team locations into cache"""
        query = f"""
        SELECT 
            team_abbr,
            city,
            state,
            arena_name,
            latitude,
            longitude,
            timezone,
            airport_code
        FROM `{self.project_id}.nba_enriched.team_locations`
        """
        
        try:
            df = self.client.query(query).to_dataframe()
            self._team_locations_cache = df.set_index('team_abbr').to_dict('index')
        except Exception as e:
            print(f"Error loading team locations: {e}")
            self._team_locations_cache = {}
    
    def calculate_road_trip_travel(self, team_schedule: List[Tuple[str, str]]) -> Dict:
        """
        Calculate cumulative travel for a road trip or series of games
        
        Args:
            team_schedule: List of (from_team, to_team) tuples in chronological order
            
        Returns:
            Dict with total_miles, total_jet_lag_factor, max_single_trip_miles
        """
        total_miles = 0
        total_jet_lag = 0.0
        max_single_trip = 0
        
        for from_team, to_team in team_schedule:
            travel = self.get_travel_distance(from_team, to_team)
            if travel:
                total_miles += travel['distance_miles']
                total_jet_lag += travel['jet_lag_factor']
                max_single_trip = max(max_single_trip, travel['distance_miles'])
        
        return {
            'total_miles': total_miles,
            'total_jet_lag_factor': round(total_jet_lag, 1),
            'max_single_trip_miles': max_single_trip,
            'number_of_trips': len(team_schedule)
        }
    
    def get_travel_last_n_days(self, team_abbr: str, current_date: datetime, days: int = 14) -> Dict:
        """
        Calculate travel metrics for last N days (for fatigue analysis)
        
        This is a placeholder - you'll need to integrate with your game schedule data
        
        Args:
            team_abbr: Team abbreviation
            current_date: Current date  
            days: Number of days to look back
            
        Returns:
            Dict with miles_traveled, time_zones_crossed, jet_lag_factor
        """
        # TODO: Integrate with your game schedule data to get actual game locations
        # For now, return placeholder structure
        return {
            'miles_traveled_last_14_days': 0,
            'time_zones_crossed_last_14_days': 0,
            'jet_lag_factor_last_14_days': 0.0,
            'games_played_last_14_days': 0
        }
    
    def estimate_international_distance(self, from_team: str, international_city: str) -> int:
        """
        Rough estimate for international games (NBA Global Games, etc.)
        
        Args:
            from_team: NBA team abbreviation
            international_city: City name (e.g., "London", "Mexico City", "Paris")
            
        Returns:
            Estimated distance in miles
        """
        # Rough estimates for common international NBA game locations
        international_distances = {
            # From major US cities (approximate averages)
            "london": 4000,
            "paris": 4200, 
            "mexico_city": 2000,
            "toronto": 500,  # Already in our data, but included for completeness
            "berlin": 4500,
            "barcelona": 4800
        }
        
        city_key = international_city.lower().replace(" ", "_")
        base_distance = international_distances.get(city_key, 5000)  # Default 5000 miles
        
        # Adjust based on team location (rough adjustment)
        team_location = self.get_team_location(from_team)
        if team_location:
            # West coast teams generally travel further to Europe
            if team_location['longitude'] < -100:  # West of 100W longitude
                return base_distance + 500
            # East coast teams travel less to Europe
            elif team_location['longitude'] > -80:   # East of 80W longitude  
                return base_distance - 500
        
        return base_distance

# Example usage functions for your processors
def get_game_travel_context(home_team: str, away_team: str, away_team_last_game_location: str = None) -> Dict:
    """
    Get travel context for a specific game - useful for analytics processors
    
    Args:
        home_team: Home team abbreviation
        away_team: Away team abbreviation  
        away_team_last_game_location: Where away team played last (optional)
        
    Returns:
        Dict with travel metrics for the away team
    """
    travel = NBATravel()
    
    context = {
        'game_location': home_team,
        'away_team': away_team,
        'home_team': home_team,
        'away_team_travel_miles': 0,
        'away_team_time_zones_crossed': 0,
        'away_team_jet_lag_factor': 0.0
    }
    
    if away_team_last_game_location and away_team_last_game_location != home_team:
        travel_info = travel.get_travel_distance(away_team_last_game_location, home_team)
        if travel_info:
            context.update({
                'away_team_travel_miles': travel_info['distance_miles'],
                'away_team_time_zones_crossed': travel_info['time_zones_crossed'], 
                'away_team_jet_lag_factor': travel_info['jet_lag_factor']
            })
    
    return context

def quick_distance_lookup(team1: str, team2: str) -> int:
    """
    Simple function to get distance between two teams
    Returns distance in miles, 0 if same team
    """
    travel = NBATravel()
    result = travel.get_travel_distance(team1, team2)
    return result['distance_miles'] if result else 0

# Test/validation functions
def validate_setup():
    """Test that the BigQuery tables are set up correctly"""
    travel = NBATravel()
    
    print("Testing NBA Travel Distance utilities...")
    
    # Test known distances
    test_cases = [
        ('LAL', 'BOS', 2600),  # Coast to coast
        ('LAL', 'GSW', 380),   # California teams
        ('LAL', 'LAC', 0),     # Same city
        ('NYK', 'BKN', 50),    # NYC area teams
    ]
    
    for from_team, to_team, expected_distance in test_cases:
        result = travel.get_travel_distance(from_team, to_team)
        if result:
            actual = result['distance_miles']
            diff = abs(actual - expected_distance)
            status = "✓" if diff < 100 else "⚠"
            print(f"  {status} {from_team} → {to_team}: {actual} miles (expected ~{expected_distance})")
        else:
            print(f"  ✗ {from_team} → {to_team}: No data found")
    
    # Test team location lookup
    lal_location = travel.get_team_location('LAL')
    if lal_location:
        print(f"  ✓ LAL location: {lal_location['city']}, {lal_location['arena_name']}")
    else:
        print("  ✗ LAL location lookup failed")

if __name__ == "__main__":
    validate_setup()