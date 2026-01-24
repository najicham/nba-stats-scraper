#!/usr/bin/env python3
"""
MLB Travel Info

Stadium and travel data for MLB teams.
Used for travel-based analytics and fatigue modeling.

Features:
- Stadium locations (lat/long)
- Stadium characteristics (roof, surface, dimensions)
- Park factors for home run predictions
- Time zone and airport information
- Distance calculations between venues

Usage:
    from shared.utils.mlb_travel_info import (
        get_mlb_stadium_info,
        calculate_travel_distance,
        get_timezone_for_team
    )

    # Get stadium info
    info = get_mlb_stadium_info("NYY")
    print(info.stadium_name)  # "Yankee Stadium"

    # Calculate travel distance
    distance = calculate_travel_distance("NYY", "BOS")
    print(f"{distance:.0f} miles")

    # Get timezone
    tz = get_timezone_for_team("LAD")
    print(tz)  # "America/Los_Angeles"

Created: 2026-01-13
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, Optional, List

from .mlb_team_mapper import get_mlb_team_mapper, MLBTeamInfo

logger = logging.getLogger(__name__)


@dataclass
class StadiumInfo:
    """Detailed stadium information."""
    team_code: str
    team_name: str
    stadium_name: str

    # Location
    latitude: float
    longitude: float
    timezone: str
    airport_code: str

    # Stadium characteristics
    roof_type: str        # "Open", "Retractable", "Dome"
    surface: str          # "Grass", "Turf"
    capacity: int

    # Dimensions (feet)
    lf_distance: int
    cf_distance: int
    rf_distance: int

    # Park factors
    park_factor_runs: float
    park_factor_hr: float
    park_factor_hr_lhb: float  # Left-handed batters
    park_factor_hr_rhb: float  # Right-handed batters

    @property
    def is_outdoor(self) -> bool:
        """Check if stadium is outdoor (no roof)."""
        return self.roof_type == "Open"

    @property
    def has_retractable_roof(self) -> bool:
        """Check if stadium has retractable roof."""
        return self.roof_type == "Retractable"

    @property
    def is_dome(self) -> bool:
        """Check if stadium is a dome."""
        return self.roof_type == "Dome"

    @property
    def is_hitter_friendly(self) -> bool:
        """Check if park favors hitters (runs factor > 1.05)."""
        return self.park_factor_runs > 1.05

    @property
    def is_pitcher_friendly(self) -> bool:
        """Check if park favors pitchers (runs factor < 0.95)."""
        return self.park_factor_runs < 0.95


def get_mlb_stadium_info(team_code: str) -> Optional[StadiumInfo]:
    """
    Get stadium information for a team.

    Args:
        team_code: MLB team code (e.g., "NYY")

    Returns:
        StadiumInfo or None if team not found
    """
    mapper = get_mlb_team_mapper()
    team = mapper.get_team(team_code)

    if not team:
        return None

    return StadiumInfo(
        team_code=team.mlb_tricode,
        team_name=team.full_name,
        stadium_name=team.stadium_name,
        latitude=team.latitude,
        longitude=team.longitude,
        timezone=team.timezone,
        airport_code=team.airport_code,
        roof_type=team.roof_type,
        surface=team.surface,
        capacity=team.stadium_capacity,
        lf_distance=team.lf_distance,
        cf_distance=team.cf_distance,
        rf_distance=team.rf_distance,
        park_factor_runs=team.park_factor_runs,
        park_factor_hr=team.park_factor_hr,
        park_factor_hr_lhb=team.park_factor_hr_lhb,
        park_factor_hr_rhb=team.park_factor_hr_rhb,
    )


def calculate_travel_distance(
    team1_code: str,
    team2_code: str,
    unit: str = "miles"
) -> Optional[float]:
    """
    Calculate travel distance between two teams' stadiums.

    Uses the Haversine formula for great-circle distance.

    Args:
        team1_code: First team code
        team2_code: Second team code
        unit: "miles" or "km"

    Returns:
        Distance in specified units, or None if teams not found
    """
    mapper = get_mlb_team_mapper()
    team1 = mapper.get_team(team1_code)
    team2 = mapper.get_team(team2_code)

    if not team1 or not team2:
        return None

    return _haversine_distance(
        team1.latitude, team1.longitude,
        team2.latitude, team2.longitude,
        unit=unit
    )


def _haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    unit: str = "miles"
) -> float:
    """
    Calculate great-circle distance using Haversine formula.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
        unit: "miles" or "km"

    Returns:
        Distance in specified units
    """
    # Earth's radius
    R_km = 6371
    R_miles = 3959

    R = R_miles if unit == "miles" else R_km

    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    # Haversine formula
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_timezone_for_team(team_code: str) -> Optional[str]:
    """Get timezone for a team."""
    mapper = get_mlb_team_mapper()
    team = mapper.get_team(team_code)
    return team.timezone if team else None


def get_teams_by_timezone(timezone: str) -> List[str]:
    """Get all teams in a specific timezone."""
    mapper = get_mlb_team_mapper()
    return [
        team.mlb_tricode
        for team in mapper.get_all_teams()
        if team.timezone == timezone
    ]


def get_dome_stadiums() -> List[StadiumInfo]:
    """Get all teams with dome/indoor stadiums."""
    mapper = get_mlb_team_mapper()
    result = []
    for team in mapper.get_all_teams():
        if team.roof_type in ("Dome", "Retractable"):
            info = get_mlb_stadium_info(team.mlb_tricode)
            if info:
                result.append(info)
    return result


def get_hitter_friendly_parks(threshold: float = 1.05) -> List[StadiumInfo]:
    """Get parks with high run environment."""
    mapper = get_mlb_team_mapper()
    result = []
    for team in mapper.get_all_teams():
        if team.park_factor_runs >= threshold:
            info = get_mlb_stadium_info(team.mlb_tricode)
            if info:
                result.append(info)
    return sorted(result, key=lambda x: x.park_factor_runs, reverse=True)


def get_pitcher_friendly_parks(threshold: float = 0.95) -> List[StadiumInfo]:
    """Get parks with low run environment."""
    mapper = get_mlb_team_mapper()
    result = []
    for team in mapper.get_all_teams():
        if team.park_factor_runs <= threshold:
            info = get_mlb_stadium_info(team.mlb_tricode)
            if info:
                result.append(info)
    return sorted(result, key=lambda x: x.park_factor_runs)


def get_travel_schedule_impact(
    team_code: str,
    opponent_codes: List[str]
) -> Dict:
    """
    Calculate travel impact for a series of games.

    Args:
        team_code: Team traveling
        opponent_codes: List of opponents in order

    Returns:
        Dict with travel metrics
    """
    total_distance = 0.0
    distances = []
    timezone_changes = 0

    mapper = get_mlb_team_mapper()
    team = mapper.get_team(team_code)
    if not team:
        return {}

    current_location = team_code
    current_tz = team.timezone

    for opponent in opponent_codes:
        distance = calculate_travel_distance(current_location, opponent)
        if distance:
            total_distance += distance
            distances.append({
                'from': current_location,
                'to': opponent,
                'distance': round(distance, 0)
            })

        opp_team = mapper.get_team(opponent)
        if opp_team and opp_team.timezone != current_tz:
            timezone_changes += 1
            current_tz = opp_team.timezone

        current_location = opponent

    # Return trip
    return_distance = calculate_travel_distance(current_location, team_code)
    if return_distance:
        total_distance += return_distance
        distances.append({
            'from': current_location,
            'to': team_code,
            'distance': round(return_distance, 0)
        })

    return {
        'team': team_code,
        'total_distance_miles': round(total_distance, 0),
        'leg_count': len(distances),
        'legs': distances,
        'timezone_changes': timezone_changes,
        'avg_leg_distance': round(total_distance / max(len(distances), 1), 0)
    }


# Test
if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    logger.info("MLB Travel Info Test")
    logger.info("=" * 60)

    # Test stadium info
    for team_code in ["NYY", "LAD", "COL", "TB"]:
        info = get_mlb_stadium_info(team_code)
        if info:
            logger.info(f"{info.team_name} - {info.stadium_name}")
            logger.info(f"  Location: ({info.latitude:.4f}, {info.longitude:.4f})")
            logger.info(f"  Timezone: {info.timezone}")
            logger.info(f"  Roof: {info.roof_type}, Surface: {info.surface}")
            logger.info(f"  Park Factor (Runs): {info.park_factor_runs:.2f}")
            logger.info(f"  Dimensions: LF={info.lf_distance}, CF={info.cf_distance}, RF={info.rf_distance}")

    # Test distance calculation
    logger.info("=" * 60)
    logger.info("Travel Distances:")

    pairs = [
        ("NYY", "BOS"),  # Short trip
        ("NYY", "LAD"),  # Cross-country
        ("SEA", "MIA"),  # Longest possible
        ("SF", "OAK"),   # Shortest possible (Bay Area)
    ]

    for team1, team2 in pairs:
        distance = calculate_travel_distance(team1, team2)
        if distance:
            logger.info(f"  {team1} -> {team2}: {distance:.0f} miles")

    # Test hitter/pitcher friendly parks
    logger.info("=" * 60)
    logger.info("Hitter-Friendly Parks (runs factor > 1.05):")
    for park in get_hitter_friendly_parks()[:5]:
        logger.info(f"  {park.stadium_name}: {park.park_factor_runs:.2f}")

    logger.info("Pitcher-Friendly Parks (runs factor < 0.95):")
    for park in get_pitcher_friendly_parks()[:5]:
        logger.info(f"  {park.stadium_name}: {park.park_factor_runs:.2f}")

    # Test travel impact
    logger.info("=" * 60)
    logger.info("Travel Impact Example:")
    impact = get_travel_schedule_impact("NYY", ["BOS", "TOR", "TB"])
    logger.info(f"  Team: {impact['team']}")
    logger.info(f"  Total Distance: {impact['total_distance_miles']} miles")
    logger.info(f"  Timezone Changes: {impact['timezone_changes']}")
    logger.info("  Legs:")
    for leg in impact['legs']:
        logger.info(f"    {leg['from']} -> {leg['to']}: {leg['distance']} miles")
