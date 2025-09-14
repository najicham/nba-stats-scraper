#!/usr/bin/env python3
"""
File: scripts/add_international_venues.py

NBA International Venues System

Adds international game venues to the travel distance system.
Includes all historical NBA Global Games locations.

Usage:
    python scripts/add_international_venues.py

This will:
1. Add international venues to team_locations table
2. Calculate distances from all NBA teams to international venues
3. Generate new SQL insert statements
"""

import math
from typing import Dict, List

# International venues where NBA has played games
INTERNATIONAL_VENUES = {
    # Europe
    "MANCHESTER": {
        "city": "Manchester",
        "country": "United Kingdom",
        "venue": "AO Arena",
        "coordinates": [53.4808, -2.2426],
        "timezone": "Europe/London", 
        "airport_code": "MAN"
    },
    "LONDON": {
        "city": "London",
        "country": "United Kingdom",
        "venue": "The O2 Arena",
        "coordinates": [51.5030, -0.0099],  # The O2 Arena coordinates
        "timezone": "Europe/London",
        "airport_code": "LHR"
    },
    "PARIS": {
        "city": "Paris", 
        "country": "France",
        "venue": "AccorHotels Arena",
        "coordinates": [48.8396, 2.3781],  # AccorHotels Arena
        "timezone": "Europe/Paris",
        "airport_code": "CDG"
    },
    "BERLIN": {
        "city": "Berlin",
        "country": "Germany", 
        "venue": "Mercedes-Benz Arena",
        "coordinates": [52.5067, 13.4435],  # Mercedes-Benz Arena Berlin
        "timezone": "Europe/Berlin",
        "airport_code": "BER"
    },
    "BARCELONA": {
        "city": "Barcelona",
        "country": "Spain",
        "venue": "Palau de la Música Catalana",
        "coordinates": [41.3874, 2.1686],  # Barcelona center
        "timezone": "Europe/Madrid",
        "airport_code": "BCN"
    },
    "ISTANBUL": {
        "city": "Istanbul",
        "country": "Turkey",
        "venue": "Sinan Erdem Dome", 
        "coordinates": [41.0082, 28.9784],  # Istanbul center
        "timezone": "Europe/Istanbul",
        "airport_code": "IST"
    },
    
    # Americas
    "MEXICO_CITY": {
        "city": "Mexico City",
        "country": "Mexico",
        "venue": "Arena Ciudad de México",
        "coordinates": [19.4326, -99.1332],
        "timezone": "America/Mexico_City",
        "airport_code": "MEX"
    },
    "MONTREAL": {
        "city": "Montreal", 
        "country": "Canada",
        "venue": "Bell Centre",
        "coordinates": [45.5019, -73.5674],
        "timezone": "America/Montreal",
        "airport_code": "YUL"
    },
    "VANCOUVER": {
        "city": "Vancouver",
        "country": "Canada", 
        "venue": "Rogers Arena",
        "coordinates": [49.2778, -123.1089],
        "timezone": "America/Vancouver",
        "airport_code": "YVR"
    },
    
    # Asia-Pacific
    "TOKYO": {
        "city": "Tokyo",
        "country": "Japan",
        "venue": "Saitama Super Arena",
        "coordinates": [35.6762, 139.6503],
        "timezone": "Asia/Tokyo",
        "airport_code": "NRT"
    },
    "TAIPEI": {
        "city": "Taipei",
        "country": "Taiwan",
        "venue": "Taipei Arena", 
        "coordinates": [25.0330, 121.5654],
        "timezone": "Asia/Taipei",
        "airport_code": "TPE"
    },
    "MANILA": {
        "city": "Manila",
        "country": "Philippines",
        "venue": "Mall of Asia Arena",
        "coordinates": [14.5995, 120.9842],
        "timezone": "Asia/Manila", 
        "airport_code": "MNL"
    },
    "MUMBAI": {
        "city": "Mumbai",
        "country": "India",
        "venue": "NSCI Dome",
        "coordinates": [19.0760, 72.8777],
        "timezone": "Asia/Kolkata",
        "airport_code": "BOM"
    },
    
    # Middle East
    "ABU_DHABI": {
        "city": "Abu Dhabi",
        "country": "UAE",
        "venue": "Etihad Arena",
        "coordinates": [24.4539, 54.3773],
        "timezone": "Asia/Dubai", 
        "airport_code": "AUH"
    }
}

# Extended timezone offsets for international venues
INTERNATIONAL_TIMEZONE_OFFSETS = {
    "Europe/London": 0,        # GMT
    "Europe/Paris": 1,         # CET
    "Europe/Berlin": 1,        # CET  
    "Europe/Madrid": 1,        # CET
    "Europe/Istanbul": 3,      # TRT
    "America/Mexico_City": -6, # CST
    "America/Montreal": -5,    # EST
    "America/Vancouver": -8,   # PST
    "Asia/Tokyo": 9,           # JST
    "Asia/Taipei": 8,          # CST
    "Asia/Manila": 8,          # PHT
    "Asia/Kolkata": 5.5,       # IST (half hour offset)
    "Asia/Dubai": 4            # GST
}

# US timezone offsets (from existing system)
US_TIMEZONE_OFFSETS = {
    "America/New_York": -5,
    "America/Chicago": -6,
    "America/Denver": -7,
    "America/Los_Angeles": -8,
    "America/Phoenix": -7,
    "America/Toronto": -5
}

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Calculate distance using haversine formula"""
    if lat1 == lat2 and lon1 == lon2:
        return 0
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = (math.sin(dlat/2)**2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
    
    c = 2 * math.asin(math.sqrt(a))
    earth_radius_miles = 3959
    
    return round(c * earth_radius_miles)

def calculate_international_jet_lag(from_tz_offset: float, to_tz_offset: float) -> tuple:
    """Calculate jet lag for international travel (handles half-hour timezones)"""
    
    # Convert to total hours difference
    hours_diff = abs(to_tz_offset - from_tz_offset)
    
    # Calculate zones crossed (round to nearest zone for half-hour timezones)
    zones_crossed = round(hours_diff)
    
    if zones_crossed == 0:
        return 0, 'neutral', 0.0
    
    # Determine direction
    if from_tz_offset < to_tz_offset:
        direction = 'east'
        jet_lag_factor = zones_crossed * 1.5  # Eastward harder
    else:
        direction = 'west' 
        jet_lag_factor = zones_crossed * 1.0  # Westward easier
    
    return zones_crossed, direction, round(jet_lag_factor, 1)

def generate_international_venue_sql() -> str:
    """Generate SQL to add international venues to team_locations table"""
    
    sql_lines = []
    sql_lines.append("-- Insert international NBA game venues")
    sql_lines.append("INSERT INTO `nba-props-platform.nba_enriched.team_locations`")
    sql_lines.append("(team_abbr, city, state, arena_name, latitude, longitude, timezone, airport_code, country) VALUES")
    
    values = []
    for venue_code, venue_data in INTERNATIONAL_VENUES.items():
        lat, lon = venue_data['coordinates']
        values.append(
            f"('{venue_code}', '{venue_data['city']}', '{venue_data['country']}', "
            f"'{venue_data['venue']}', {lat}, {lon}, '{venue_data['timezone']}', "
            f"'{venue_data['airport_code']}', '{venue_data['country']}')"
        )
    
    sql_lines.append(",\n".join(values) + ";")
    return "\n".join(sql_lines)

def generate_international_distances_sql() -> str:
    """Generate distances from all NBA teams to international venues"""
    
    # NBA team coordinates (from your existing system)
    nba_teams = {
        "ATL": {"city": "Atlanta", "coordinates": [33.7573, -84.3963], "timezone": "America/New_York"},
        "BOS": {"city": "Boston", "coordinates": [42.3662, -71.0621], "timezone": "America/New_York"},
        "BKN": {"city": "Brooklyn", "coordinates": [40.6826, -73.9754], "timezone": "America/New_York"},
        "CHA": {"city": "Charlotte", "coordinates": [35.2251, -80.8392], "timezone": "America/New_York"},
        "CHI": {"city": "Chicago", "coordinates": [41.8807, -87.6742], "timezone": "America/Chicago"},
        "CLE": {"city": "Cleveland", "coordinates": [41.4965, -81.6882], "timezone": "America/New_York"},
        "DAL": {"city": "Dallas", "coordinates": [32.7906, -96.8103], "timezone": "America/Chicago"},
        "DEN": {"city": "Denver", "coordinates": [39.7487, -105.0077], "timezone": "America/Denver"},
        "DET": {"city": "Detroit", "coordinates": [42.3411, -83.0553], "timezone": "America/New_York"},
        "GSW": {"city": "San Francisco", "coordinates": [37.7679, -122.3873], "timezone": "America/Los_Angeles"},
        "HOU": {"city": "Houston", "coordinates": [29.6807, -95.3615], "timezone": "America/Chicago"},
        "IND": {"city": "Indianapolis", "coordinates": [39.7640, -86.1555], "timezone": "America/New_York"},
        "LAC": {"city": "Los Angeles", "coordinates": [34.0430, -118.2673], "timezone": "America/Los_Angeles"},
        "LAL": {"city": "Los Angeles", "coordinates": [34.0430, -118.2673], "timezone": "America/Los_Angeles"},
        "MEM": {"city": "Memphis", "coordinates": [35.1382, -90.0505], "timezone": "America/Chicago"},
        "MIA": {"city": "Miami", "coordinates": [25.7814, -80.1870], "timezone": "America/New_York"},
        "MIL": {"city": "Milwaukee", "coordinates": [43.0435, -87.9167], "timezone": "America/Chicago"},
        "MIN": {"city": "Minneapolis", "coordinates": [44.9795, -93.2760], "timezone": "America/Chicago"},
        "NOP": {"city": "New Orleans", "coordinates": [29.9490, -90.0821], "timezone": "America/Chicago"},
        "NYK": {"city": "New York", "coordinates": [40.7505, -73.9934], "timezone": "America/New_York"},
        "OKC": {"city": "Oklahoma City", "coordinates": [35.4634, -97.5151], "timezone": "America/Chicago"},
        "ORL": {"city": "Orlando", "coordinates": [28.5392, -81.3839], "timezone": "America/New_York"},
        "PHI": {"city": "Philadelphia", "coordinates": [39.9012, -75.1720], "timezone": "America/New_York"},
        "PHX": {"city": "Phoenix", "coordinates": [33.4457, -112.0712], "timezone": "America/Phoenix"},
        "POR": {"city": "Portland", "coordinates": [45.5316, -122.6668], "timezone": "America/Los_Angeles"},
        "SAC": {"city": "Sacramento", "coordinates": [38.5816, -121.4999], "timezone": "America/Los_Angeles"},
        "SAS": {"city": "San Antonio", "coordinates": [29.4270, -98.4375], "timezone": "America/Chicago"},
        "TOR": {"city": "Toronto", "coordinates": [43.6434, -79.3791], "timezone": "America/Toronto"},
        "UTA": {"city": "Salt Lake City", "coordinates": [40.7683, -111.9011], "timezone": "America/Denver"},
        "WAS": {"city": "Washington", "coordinates": [38.8981, -77.0209], "timezone": "America/New_York"}
    }
    
    all_timezone_offsets = {**US_TIMEZONE_OFFSETS, **INTERNATIONAL_TIMEZONE_OFFSETS}
    
    sql_lines = []
    sql_lines.append("-- Insert distances from NBA teams to international venues")
    sql_lines.append("INSERT INTO `nba-props-platform.nba_enriched.travel_distances`")
    sql_lines.append("(from_team, to_team, from_city, to_city, distance_miles, time_zones_crossed, travel_direction, jet_lag_factor) VALUES")
    
    values = []
    
    # Generate distances: NBA teams → International venues
    for nba_team, nba_data in nba_teams.items():
        nba_lat, nba_lon = nba_data['coordinates']
        nba_tz_offset = all_timezone_offsets[nba_data['timezone']]
        
        for venue_code, venue_data in INTERNATIONAL_VENUES.items():
            venue_lat, venue_lon = venue_data['coordinates']
            venue_tz_offset = all_timezone_offsets[venue_data['timezone']]
            
            distance = haversine_distance(nba_lat, nba_lon, venue_lat, venue_lon)
            zones_crossed, direction, jet_lag_factor = calculate_international_jet_lag(nba_tz_offset, venue_tz_offset)
            
            values.append(
                f"('{nba_team}', '{venue_code}', '{nba_data['city']}', '{venue_data['city']}', "
                f"{distance}, {zones_crossed}, '{direction}', {jet_lag_factor})"
            )
            
            # Also add reverse direction (international venue → NBA team)
            reverse_zones_crossed, reverse_direction, reverse_jet_lag_factor = calculate_international_jet_lag(venue_tz_offset, nba_tz_offset)
            
            values.append(
                f"('{venue_code}', '{nba_team}', '{venue_data['city']}', '{nba_data['city']}', "
                f"{distance}, {reverse_zones_crossed}, '{reverse_direction}', {reverse_jet_lag_factor})"
            )
    
    sql_lines.append(",\n".join(values) + ";")
    return "\n".join(sql_lines)

def main():
    """Generate international venue additions"""
    
    print("=" * 60)
    print("NBA International Venues System")
    print("=" * 60)
    print(f"Adding {len(INTERNATIONAL_VENUES)} international venues:")
    
    for code, venue in INTERNATIONAL_VENUES.items():
        print(f"  {code}: {venue['city']}, {venue['country']} - {venue['venue']}")
    
    # Generate venue additions
    venues_sql = generate_international_venue_sql()
    with open('add_international_venues.sql', 'w') as f:
        f.write(venues_sql)
    
    # Generate distance calculations  
    distances_sql = generate_international_distances_sql()
    with open('add_international_distances.sql', 'w') as f:
        f.write(distances_sql)
    
    print(f"\n✓ Generated add_international_venues.sql")
    print(f"✓ Generated add_international_distances.sql")
    
    # Calculate total new distance combinations
    total_new_distances = len(INTERNATIONAL_VENUES) * 30 * 2  # 30 NBA teams * 2 directions
    print(f"✓ Will add {total_new_distances} new distance combinations")
    
    print(f"\n" + "=" * 60)
    print("Next Steps:")
    print("1. bq query --use_legacy_sql=false < add_international_venues.sql")
    print("2. bq query --use_legacy_sql=false < add_international_distances.sql")
    print("3. Test: SELECT * FROM team_locations WHERE country != 'USA'")
    print("=" * 60)

if __name__ == "__main__":
    main()