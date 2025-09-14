#!/usr/bin/env python3
"""
File: scripts/generate_travel_distances.py

NBA Travel Distance Generator

Generates pre-calculated distance matrix for all NBA team-to-team combinations.
Creates CSV and BigQuery SQL files for loading into your analytics system.

Requirements:
    pip install pandas  # Optional, only for CSV validation

Usage:
    python scripts/generate_travel_distances.py

Outputs:
    - nba_travel_distances.csv
    - nba_travel_distances_insert.sql
"""

import math
import csv
import json
from typing import Dict, List, Tuple

# NBA Teams with coordinates and timezone information
NBA_TEAMS = {
    "ATL": {
        "city": "Atlanta",
        "state": "Georgia", 
        "arena": "State Farm Arena",
        "coordinates": [33.7573, -84.3963],
        "timezone": "America/New_York"
    },
    "BOS": {
        "city": "Boston",
        "state": "Massachusetts",
        "arena": "TD Garden", 
        "coordinates": [42.3662, -71.0621],
        "timezone": "America/New_York"
    },
    "BKN": {
        "city": "Brooklyn",
        "state": "New York",
        "arena": "Barclays Center",
        "coordinates": [40.6826, -73.9754],
        "timezone": "America/New_York"
    },
    "CHA": {
        "city": "Charlotte",
        "state": "North Carolina",
        "arena": "Spectrum Center",
        "coordinates": [35.2251, -80.8392],
        "timezone": "America/New_York"
    },
    "CHI": {
        "city": "Chicago", 
        "state": "Illinois",
        "arena": "United Center",
        "coordinates": [41.8807, -87.6742],
        "timezone": "America/Chicago"
    },
    "CLE": {
        "city": "Cleveland",
        "state": "Ohio", 
        "arena": "Rocket Mortgage FieldHouse",
        "coordinates": [41.4965, -81.6882],
        "timezone": "America/New_York"
    },
    "DAL": {
        "city": "Dallas",
        "state": "Texas",
        "arena": "American Airlines Center", 
        "coordinates": [32.7906, -96.8103],
        "timezone": "America/Chicago"
    },
    "DEN": {
        "city": "Denver",
        "state": "Colorado",
        "arena": "Ball Arena",
        "coordinates": [39.7487, -105.0077],
        "timezone": "America/Denver"
    },
    "DET": {
        "city": "Detroit", 
        "state": "Michigan",
        "arena": "Little Caesars Arena",
        "coordinates": [42.3411, -83.0553],
        "timezone": "America/New_York"
    },
    "GSW": {
        "city": "San Francisco",
        "state": "California", 
        "arena": "Chase Center",
        "coordinates": [37.7679, -122.3873],
        "timezone": "America/Los_Angeles"
    },
    "HOU": {
        "city": "Houston",
        "state": "Texas",
        "arena": "Toyota Center",
        "coordinates": [29.6807, -95.3615],
        "timezone": "America/Chicago"
    },
    "IND": {
        "city": "Indianapolis", 
        "state": "Indiana",
        "arena": "Gainbridge Fieldhouse",
        "coordinates": [39.7640, -86.1555],
        "timezone": "America/New_York"
    },
    "LAC": {
        "city": "Los Angeles",
        "state": "California",
        "arena": "Crypto.com Arena",
        "coordinates": [34.0430, -118.2673],
        "timezone": "America/Los_Angeles"
    },
    "LAL": {
        "city": "Los Angeles", 
        "state": "California",
        "arena": "Crypto.com Arena", 
        "coordinates": [34.0430, -118.2673],
        "timezone": "America/Los_Angeles"
    },
    "MEM": {
        "city": "Memphis",
        "state": "Tennessee",
        "arena": "FedExForum",
        "coordinates": [35.1382, -90.0505],
        "timezone": "America/Chicago"
    },
    "MIA": {
        "city": "Miami",
        "state": "Florida",
        "arena": "Kaseya Center", 
        "coordinates": [25.7814, -80.1870],
        "timezone": "America/New_York"
    },
    "MIL": {
        "city": "Milwaukee",
        "state": "Wisconsin",
        "arena": "Fiserv Forum",
        "coordinates": [43.0435, -87.9167],
        "timezone": "America/Chicago"
    },
    "MIN": {
        "city": "Minneapolis",
        "state": "Minnesota", 
        "arena": "Target Center",
        "coordinates": [44.9795, -93.2760],
        "timezone": "America/Chicago"
    },
    "NOP": {
        "city": "New Orleans",
        "state": "Louisiana",
        "arena": "Smoothie King Center",
        "coordinates": [29.9490, -90.0821],
        "timezone": "America/Chicago"
    },
    "NYK": {
        "city": "New York",
        "state": "New York", 
        "arena": "Madison Square Garden",
        "coordinates": [40.7505, -73.9934],
        "timezone": "America/New_York"
    },
    "OKC": {
        "city": "Oklahoma City",
        "state": "Oklahoma",
        "arena": "Paycom Center", 
        "coordinates": [35.4634, -97.5151],
        "timezone": "America/Chicago"
    },
    "ORL": {
        "city": "Orlando",
        "state": "Florida",
        "arena": "Kia Center",
        "coordinates": [28.5392, -81.3839],
        "timezone": "America/New_York"
    },
    "PHI": {
        "city": "Philadelphia",
        "state": "Pennsylvania", 
        "arena": "Wells Fargo Center",
        "coordinates": [39.9012, -75.1720],
        "timezone": "America/New_York"
    },
    "PHX": {
        "city": "Phoenix", 
        "state": "Arizona",
        "arena": "Footprint Center",
        "coordinates": [33.4457, -112.0712],
        "timezone": "America/Phoenix"
    },
    "POR": {
        "city": "Portland",
        "state": "Oregon",
        "arena": "Moda Center",
        "coordinates": [45.5316, -122.6668],
        "timezone": "America/Los_Angeles"
    },
    "SAC": {
        "city": "Sacramento", 
        "state": "California",
        "arena": "Golden 1 Center",
        "coordinates": [38.5816, -121.4999],
        "timezone": "America/Los_Angeles"
    },
    "SAS": {
        "city": "San Antonio",
        "state": "Texas",
        "arena": "Frost Bank Center",
        "coordinates": [29.4270, -98.4375],
        "timezone": "America/Chicago"
    },
    "TOR": {
        "city": "Toronto", 
        "state": "Ontario",
        "arena": "Scotiabank Arena",
        "coordinates": [43.6434, -79.3791],
        "timezone": "America/Toronto"
    },
    "UTA": {
        "city": "Salt Lake City",
        "state": "Utah",
        "arena": "Delta Center",
        "coordinates": [40.7683, -111.9011], 
        "timezone": "America/Denver"
    },
    "WAS": {
        "city": "Washington",
        "state": "District of Columbia",
        "arena": "Capital One Arena",
        "coordinates": [38.8981, -77.0209],
        "timezone": "America/New_York"
    }
}

# Timezone UTC offsets (standard time, not accounting for DST)
TIMEZONE_OFFSETS = {
    "America/New_York": -5,
    "America/Chicago": -6, 
    "America/Denver": -7,
    "America/Los_Angeles": -8,
    "America/Phoenix": -7,  # Arizona doesn't observe DST
    "America/Toronto": -5
}

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """
    Calculate the great circle distance between two points in miles.
    Uses the haversine formula for accuracy over long distances.
    
    Args:
        lat1, lon1: Latitude and longitude of first point (degrees)
        lat2, lon2: Latitude and longitude of second point (degrees)
    
    Returns:
        Distance in miles (rounded to nearest mile)
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0
    
    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = (math.sin(dlat/2)**2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
    
    c = 2 * math.asin(math.sqrt(a))
    
    # Earth radius in miles (mean radius)
    earth_radius_miles = 3959
    
    return round(c * earth_radius_miles)

def calculate_jet_lag_metrics(from_timezone: str, to_timezone: str) -> Tuple[int, str, float]:
    """
    Calculate time zone changes and jet lag impact factor.
    
    Args:
        from_timezone: Origin timezone string
        to_timezone: Destination timezone string
    
    Returns:
        Tuple of (zones_crossed, direction, jet_lag_factor)
    """
    from_offset = TIMEZONE_OFFSETS.get(from_timezone, 0)
    to_offset = TIMEZONE_OFFSETS.get(to_timezone, 0)
    
    zones_crossed = abs(from_offset - to_offset)
    
    if zones_crossed == 0:
        return 0, 'neutral', 0.0
    
    # Determine travel direction
    if from_offset > to_offset:
        # Moving east (losing time) - harder on circadian rhythms
        direction = 'east'
        jet_lag_factor = zones_crossed * 1.5
    else:
        # Moving west (gaining time) - easier adjustment
        direction = 'west' 
        jet_lag_factor = zones_crossed * 1.0
    
    return zones_crossed, direction, round(jet_lag_factor, 1)

def generate_all_distances() -> List[Dict]:
    """
    Generate distance matrix for all NBA team combinations.
    
    Returns:
        List of dictionaries containing distance data for each team pair
    """
    print(f"Calculating distances for {len(NBA_TEAMS)} NBA teams...")
    
    distances = []
    
    for from_team, from_data in NBA_TEAMS.items():
        from_lat, from_lon = from_data['coordinates']
        
        for to_team, to_data in NBA_TEAMS.items():
            if from_team == to_team:
                continue  # Skip same team
            
            to_lat, to_lon = to_data['coordinates']
            
            # Calculate distance
            distance_miles = haversine_distance(from_lat, from_lon, to_lat, to_lon)
            
            # Calculate jet lag metrics
            zones_crossed, direction, jet_lag_factor = calculate_jet_lag_metrics(
                from_data['timezone'], to_data['timezone']
            )
            
            distances.append({
                'from_team': from_team,
                'to_team': to_team,
                'from_city': from_data['city'],
                'to_city': to_data['city'],
                'distance_miles': distance_miles,
                'time_zones_crossed': zones_crossed,
                'travel_direction': direction,
                'jet_lag_factor': jet_lag_factor
            })
    
    return distances

def validate_distances(distances: List[Dict]) -> None:
    """Validate calculated distances against known benchmarks."""
    
    # Known approximate distances for validation
    benchmarks = {
        ('LAL', 'BOS'): 2605,  # Coast to coast
        ('LAL', 'GSW'): 382,   # California teams
        ('LAL', 'LAC'): 0,     # Same arena
        ('MIA', 'POR'): 2739,  # Long diagonal
        ('NYK', 'BKN'): 8,     # Same metro area
    }
    
    print("\nValidating calculated distances:")
    
    # Create lookup dictionary for fast access
    distance_lookup = {
        (d['from_team'], d['to_team']): d['distance_miles'] 
        for d in distances
    }
    
    for (from_team, to_team), expected in benchmarks.items():
        actual = distance_lookup.get((from_team, to_team), None)
        
        if actual is not None:
            diff = abs(actual - expected)
            status = "✓" if diff <= 100 else "⚠"
            print(f"  {status} {from_team} → {to_team}: {actual} miles "
                  f"(expected ~{expected}, diff: {diff})")
        else:
            print(f"  ✗ {from_team} → {to_team}: Not found in results")

def export_to_csv(distances: List[Dict], filename: str = 'nba_travel_distances.csv') -> None:
    """Export distance data to CSV file."""
    
    fieldnames = [
        'from_team', 'to_team', 'from_city', 'to_city',
        'distance_miles', 'time_zones_crossed', 'travel_direction', 'jet_lag_factor'
    ]
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(distances)
    
    print(f"\n✓ Exported {len(distances)} distances to {filename}")

def generate_bigquery_sql(distances: List[Dict], filename: str = 'nba_travel_distances_insert.sql') -> None:
    """Generate BigQuery INSERT statement."""
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("""-- Generated NBA Travel Distances INSERT Statement
-- File: nba_travel_distances_insert.sql
-- 
-- Load with:
--   bq query --use_legacy_sql=false < nba_travel_distances_insert.sql
--
-- This will insert all 870 team-to-team distance combinations into:
--   nba-props-platform.nba_enriched.travel_distances

INSERT INTO `nba-props-platform.nba_enriched.travel_distances` 
(from_team, to_team, from_city, to_city, distance_miles, time_zones_crossed, travel_direction, jet_lag_factor)
VALUES
""")
        
        # Generate VALUES clauses
        value_rows = []
        for d in distances:
            value_rows.append(
                f"('{d['from_team']}', '{d['to_team']}', '{d['from_city']}', '{d['to_city']}', "
                f"{d['distance_miles']}, {d['time_zones_crossed']}, '{d['travel_direction']}', {d['jet_lag_factor']})"
            )
        
        f.write(",\n".join(value_rows))
        f.write(";\n")
    
    print(f"✓ Generated BigQuery SQL: {filename}")

def print_summary_stats(distances: List[Dict]) -> None:
    """Print summary statistics about the distance data."""
    
    all_distances = [d['distance_miles'] for d in distances]
    jet_lag_factors = [d['jet_lag_factor'] for d in distances]
    
    print(f"\n=== Distance Matrix Summary ===")
    print(f"Total combinations: {len(distances)}")
    print(f"Distance range: {min(all_distances)} - {max(all_distances)} miles")
    print(f"Average distance: {sum(all_distances) // len(all_distances)} miles")
    print(f"Max jet lag factor: {max(jet_lag_factors)}")
    
    # Show a few sample distances
    print(f"\nSample distances:")
    for i in range(min(5, len(distances))):
        d = distances[i]
        print(f"  {d['from_team']} → {d['to_team']}: {d['distance_miles']} miles, "
              f"{d['time_zones_crossed']} zones {d['travel_direction']}")

def main():
    """Main execution function."""
    
    print("=" * 50)
    print("NBA Travel Distance Generator")
    print("=" * 50)
    
    # Generate all distance combinations
    distances = generate_all_distances()
    
    if not distances:
        print("❌ No distances generated. Check team data.")
        return
    
    print(f"✓ Generated {len(distances)} team-to-team combinations")
    
    # Validate results
    validate_distances(distances)
    
    # Export data
    export_to_csv(distances)
    generate_bigquery_sql(distances)
    
    # Show summary
    print_summary_stats(distances)
    
    print(f"\n{'=' * 50}")
    print("🎯 Files ready for BigQuery!")
    print("Next steps:")
    print("1. Tables already created ✓")
    print("2. bq query --use_legacy_sql=false < nba_travel_distances_insert.sql")
    print("3. Verify data: SELECT COUNT(*) FROM `nba-props-platform.nba_enriched.travel_distances`")
    print("=" * 50)

if __name__ == "__main__":
    main()