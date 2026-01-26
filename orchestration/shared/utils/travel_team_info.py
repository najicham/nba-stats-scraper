#!/usr/bin/env python3
"""
File: shared/utils/travel_team_info.py

Extended TeamInfo class with travel/distance data for analytics processors.

Extends the existing shared/utils/nba_team_mapper.py with travel-specific fields.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from shared.utils.nba_team_mapper import TeamInfo as BaseTeamInfo

@dataclass 
class TravelTeamInfo(BaseTeamInfo):
    """Extended TeamInfo with travel/distance fields for analytics."""
    
    # Travel-specific fields
    arena_name: str = ""         # "State Farm Arena" 
    latitude: float = 0.0        # 33.7573
    longitude: float = 0.0       # -84.3963
    timezone: str = ""           # "America/New_York"
    airport_code: str = ""       # "ATL"
    
    # For international games
    country: str = "USA"         # "USA" for all NBA teams, "CAN" for Toronto

# Enhanced team data with travel information
TRAVEL_ENHANCED_TEAMS = {
    # Using your existing team data structure but adding travel fields
    "ATL": TravelTeamInfo(
        nba_tricode="ATL", br_tricode="ATL", espn_tricode="ATL",
        full_name="Atlanta Hawks", city="Atlanta", nickname="Hawks",
        common_variations=["hawks", "atlanta hawks", "atl hawks"],
        state="Georgia", division="Southeast", conference="Eastern",
        # Travel fields
        arena_name="State Farm Arena",
        latitude=33.7573, longitude=-84.3963,
        timezone="America/New_York", airport_code="ATL"
    ),
    "BOS": TravelTeamInfo(
        nba_tricode="BOS", br_tricode="BOS", espn_tricode="BOS",
        full_name="Boston Celtics", city="Boston", nickname="Celtics",
        common_variations=["celtics", "boston celtics", "bos celtics"],
        state="Massachusetts", division="Atlantic", conference="Eastern",
        arena_name="TD Garden",
        latitude=42.3662, longitude=-71.0621,
        timezone="America/New_York", airport_code="BOS"
    ),
    # ... continue for all 30 teams
    "TOR": TravelTeamInfo(
        nba_tricode="TOR", br_tricode="TOR", espn_tricode="TOR",
        full_name="Toronto Raptors", city="Toronto", nickname="Raptors",
        common_variations=["raptors", "toronto raptors", "tor raptors"],
        state="Ontario", division="Atlantic", conference="Eastern",
        arena_name="Scotiabank Arena",
        latitude=43.6434, longitude=-79.3791,
        timezone="America/Toronto", airport_code="YYZ",
        country="CAN"  # Only non-USA team
    ),
}