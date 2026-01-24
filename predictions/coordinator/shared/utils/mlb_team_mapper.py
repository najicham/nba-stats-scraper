#!/usr/bin/env python3
"""
MLB Team Mapper

Comprehensive MLB team mapping utility for consistent team identification
across all data sources (Statcast, ESPN, Odds API, Ball Don't Lie, etc.).

Features:
- Multiple tricode systems (MLB, ESPN, Statcast, BR)
- Fuzzy matching for typos and variations
- League/Division structure (AL/NL)
- Stadium metadata (dimensions, elevation, surface)
- Team schedule integration

Usage:
    from shared.utils.mlb_team_mapper import MLBTeamMapper, get_mlb_team_mapper

    mapper = get_mlb_team_mapper()

    # Get team info
    team = mapper.get_team("NYY")
    print(team.full_name)  # "New York Yankees"

    # Fuzzy match
    team = mapper.fuzzy_match("yankees")
    print(team.mlb_tricode)  # "NYY"

    # Normalize team code
    code = mapper.normalize_team_code("New York Yankees")
    print(code)  # "NYY"

Created: 2026-01-13
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class MLBTeamInfo:
    """Complete MLB team information."""

    # Primary identifiers
    mlb_tricode: str              # Official MLB code (NYY, LAD, etc.)
    full_name: str                # Full team name (New York Yankees)
    city: str                     # City name (New York)
    nickname: str                 # Team nickname (Yankees)

    # Alternate codes from different sources
    espn_tricode: str = ""        # ESPN code (usually same)
    statcast_tricode: str = ""    # Baseball Savant code
    br_tricode: str = ""          # Baseball Reference code
    bdl_tricode: str = ""         # Ball Don't Lie code
    alternate_codes: List[str] = field(default_factory=list)

    # League structure
    league: str = ""              # "AL" or "NL"
    division: str = ""            # "East", "Central", "West"

    # Stadium info
    stadium_name: str = ""
    stadium_capacity: int = 0
    roof_type: str = ""           # "Open", "Retractable", "Dome"
    surface: str = ""             # "Grass", "Turf"

    # Park factors (affects predictions)
    park_factor_runs: float = 1.0    # 1.0 = neutral
    park_factor_hr: float = 1.0
    park_factor_hr_lhb: float = 1.0  # Left-handed batters
    park_factor_hr_rhb: float = 1.0  # Right-handed batters

    # Location
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = ""
    airport_code: str = ""

    # Field dimensions (feet)
    lf_distance: int = 0          # Left field
    cf_distance: int = 0          # Center field
    rf_distance: int = 0          # Right field

    @property
    def full_division(self) -> str:
        """Get full division name (e.g., 'AL East')."""
        return f"{self.league} {self.division}"

    @property
    def all_codes(self) -> Set[str]:
        """Get all possible codes for this team."""
        codes = {self.mlb_tricode}
        if self.espn_tricode:
            codes.add(self.espn_tricode)
        if self.statcast_tricode:
            codes.add(self.statcast_tricode)
        if self.br_tricode:
            codes.add(self.br_tricode)
        if self.bdl_tricode:
            codes.add(self.bdl_tricode)
        codes.update(self.alternate_codes)
        return codes


class MLBTeamMapper:
    """
    Comprehensive MLB team mapper.

    Handles team code normalization, fuzzy matching, and metadata lookup
    across multiple data sources.
    """

    def __init__(self):
        self._teams: Dict[str, MLBTeamInfo] = {}
        self._code_to_team: Dict[str, str] = {}  # Any code -> mlb_tricode
        self._name_variations: Dict[str, str] = {}  # Lowercase name -> mlb_tricode
        self._load_teams_data()
        self._build_lookup_tables()

    def _load_teams_data(self) -> None:
        """Load comprehensive team data for all 30 MLB teams."""
        teams = [
            # AL East
            MLBTeamInfo(
                mlb_tricode="BAL", full_name="Baltimore Orioles", city="Baltimore", nickname="Orioles",
                espn_tricode="BAL", statcast_tricode="BAL", br_tricode="BAL", bdl_tricode="BAL",
                league="AL", division="East",
                stadium_name="Oriole Park at Camden Yards", stadium_capacity=45971,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.02, park_factor_hr=1.05,
                latitude=39.2838, longitude=-76.6216, timezone="America/New_York", airport_code="BWI",
                lf_distance=333, cf_distance=400, rf_distance=318
            ),
            MLBTeamInfo(
                mlb_tricode="BOS", full_name="Boston Red Sox", city="Boston", nickname="Red Sox",
                espn_tricode="BOS", statcast_tricode="BOS", br_tricode="BOS", bdl_tricode="BOS",
                alternate_codes=["BSN"],
                league="AL", division="East",
                stadium_name="Fenway Park", stadium_capacity=37755,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.08, park_factor_hr=0.95, park_factor_hr_lhb=0.85, park_factor_hr_rhb=1.15,
                latitude=42.3467, longitude=-71.0972, timezone="America/New_York", airport_code="BOS",
                lf_distance=310, cf_distance=390, rf_distance=302
            ),
            MLBTeamInfo(
                mlb_tricode="NYY", full_name="New York Yankees", city="New York", nickname="Yankees",
                espn_tricode="NYY", statcast_tricode="NYY", br_tricode="NYY", bdl_tricode="NYY",
                alternate_codes=["NY", "NYA"],
                league="AL", division="East",
                stadium_name="Yankee Stadium", stadium_capacity=46537,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.05, park_factor_hr=1.15, park_factor_hr_lhb=1.25, park_factor_hr_rhb=1.05,
                latitude=40.8296, longitude=-73.9262, timezone="America/New_York", airport_code="LGA",
                lf_distance=318, cf_distance=408, rf_distance=314
            ),
            MLBTeamInfo(
                mlb_tricode="TB", full_name="Tampa Bay Rays", city="Tampa Bay", nickname="Rays",
                espn_tricode="TB", statcast_tricode="TB", br_tricode="TBR", bdl_tricode="TB",
                alternate_codes=["TBR", "TAM", "TBA"],
                league="AL", division="East",
                stadium_name="Tropicana Field", stadium_capacity=25000,
                roof_type="Dome", surface="Turf",
                park_factor_runs=0.92, park_factor_hr=0.88,
                latitude=27.7682, longitude=-82.6534, timezone="America/New_York", airport_code="TPA",
                lf_distance=315, cf_distance=404, rf_distance=322
            ),
            MLBTeamInfo(
                mlb_tricode="TOR", full_name="Toronto Blue Jays", city="Toronto", nickname="Blue Jays",
                espn_tricode="TOR", statcast_tricode="TOR", br_tricode="TOR", bdl_tricode="TOR",
                league="AL", division="East",
                stadium_name="Rogers Centre", stadium_capacity=49282,
                roof_type="Retractable", surface="Turf",
                park_factor_runs=1.03, park_factor_hr=1.08,
                latitude=43.6414, longitude=-79.3894, timezone="America/Toronto", airport_code="YYZ",
                lf_distance=328, cf_distance=400, rf_distance=328
            ),

            # AL Central
            MLBTeamInfo(
                mlb_tricode="CLE", full_name="Cleveland Guardians", city="Cleveland", nickname="Guardians",
                espn_tricode="CLE", statcast_tricode="CLE", br_tricode="CLE", bdl_tricode="CLE",
                alternate_codes=["CLV"],
                league="AL", division="Central",
                stadium_name="Progressive Field", stadium_capacity=34830,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.96, park_factor_hr=0.92,
                latitude=41.4962, longitude=-81.6852, timezone="America/New_York", airport_code="CLE",
                lf_distance=325, cf_distance=400, rf_distance=325
            ),
            MLBTeamInfo(
                mlb_tricode="CWS", full_name="Chicago White Sox", city="Chicago", nickname="White Sox",
                espn_tricode="CHW", statcast_tricode="CWS", br_tricode="CHW", bdl_tricode="CHW",
                alternate_codes=["CHW", "CHA"],
                league="AL", division="Central",
                stadium_name="Guaranteed Rate Field", stadium_capacity=40615,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.04, park_factor_hr=1.10,
                latitude=41.8299, longitude=-87.6338, timezone="America/Chicago", airport_code="ORD",
                lf_distance=330, cf_distance=400, rf_distance=335
            ),
            MLBTeamInfo(
                mlb_tricode="DET", full_name="Detroit Tigers", city="Detroit", nickname="Tigers",
                espn_tricode="DET", statcast_tricode="DET", br_tricode="DET", bdl_tricode="DET",
                league="AL", division="Central",
                stadium_name="Comerica Park", stadium_capacity=41083,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.94, park_factor_hr=0.85,
                latitude=42.3390, longitude=-83.0485, timezone="America/Detroit", airport_code="DTW",
                lf_distance=345, cf_distance=420, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="KC", full_name="Kansas City Royals", city="Kansas City", nickname="Royals",
                espn_tricode="KC", statcast_tricode="KC", br_tricode="KCR", bdl_tricode="KC",
                alternate_codes=["KCR", "KAN"],
                league="AL", division="Central",
                stadium_name="Kauffman Stadium", stadium_capacity=37903,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.01, park_factor_hr=0.95,
                latitude=39.0517, longitude=-94.4803, timezone="America/Chicago", airport_code="MCI",
                lf_distance=330, cf_distance=410, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="MIN", full_name="Minnesota Twins", city="Minnesota", nickname="Twins",
                espn_tricode="MIN", statcast_tricode="MIN", br_tricode="MIN", bdl_tricode="MIN",
                league="AL", division="Central",
                stadium_name="Target Field", stadium_capacity=38544,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.02, park_factor_hr=1.05,
                latitude=44.9817, longitude=-93.2776, timezone="America/Chicago", airport_code="MSP",
                lf_distance=339, cf_distance=404, rf_distance=328
            ),

            # AL West
            MLBTeamInfo(
                mlb_tricode="HOU", full_name="Houston Astros", city="Houston", nickname="Astros",
                espn_tricode="HOU", statcast_tricode="HOU", br_tricode="HOU", bdl_tricode="HOU",
                league="AL", division="West",
                stadium_name="Minute Maid Park", stadium_capacity=41168,
                roof_type="Retractable", surface="Grass",
                park_factor_runs=1.03, park_factor_hr=1.08,
                latitude=29.7573, longitude=-95.3555, timezone="America/Chicago", airport_code="IAH",
                lf_distance=315, cf_distance=409, rf_distance=326
            ),
            MLBTeamInfo(
                mlb_tricode="LAA", full_name="Los Angeles Angels", city="Anaheim", nickname="Angels",
                espn_tricode="LAA", statcast_tricode="LAA", br_tricode="LAA", bdl_tricode="LAA",
                alternate_codes=["ANA", "CAL", "ANH"],
                league="AL", division="West",
                stadium_name="Angel Stadium", stadium_capacity=45517,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.96, park_factor_hr=0.95,
                latitude=33.8003, longitude=-117.8827, timezone="America/Los_Angeles", airport_code="SNA",
                lf_distance=330, cf_distance=396, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="OAK", full_name="Oakland Athletics", city="Oakland", nickname="Athletics",
                espn_tricode="OAK", statcast_tricode="OAK", br_tricode="OAK", bdl_tricode="OAK",
                alternate_codes=["ATH"],
                league="AL", division="West",
                stadium_name="Oakland Coliseum", stadium_capacity=46847,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.90, park_factor_hr=0.82,
                latitude=37.7516, longitude=-122.2005, timezone="America/Los_Angeles", airport_code="OAK",
                lf_distance=330, cf_distance=400, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="SEA", full_name="Seattle Mariners", city="Seattle", nickname="Mariners",
                espn_tricode="SEA", statcast_tricode="SEA", br_tricode="SEA", bdl_tricode="SEA",
                league="AL", division="West",
                stadium_name="T-Mobile Park", stadium_capacity=47929,
                roof_type="Retractable", surface="Grass",
                park_factor_runs=0.93, park_factor_hr=0.88,
                latitude=47.5914, longitude=-122.3325, timezone="America/Los_Angeles", airport_code="SEA",
                lf_distance=331, cf_distance=401, rf_distance=326
            ),
            MLBTeamInfo(
                mlb_tricode="TEX", full_name="Texas Rangers", city="Arlington", nickname="Rangers",
                espn_tricode="TEX", statcast_tricode="TEX", br_tricode="TEX", bdl_tricode="TEX",
                league="AL", division="West",
                stadium_name="Globe Life Field", stadium_capacity=40300,
                roof_type="Retractable", surface="Grass",
                park_factor_runs=0.98, park_factor_hr=0.95,
                latitude=32.7512, longitude=-97.0832, timezone="America/Chicago", airport_code="DFW",
                lf_distance=329, cf_distance=407, rf_distance=326
            ),

            # NL East
            MLBTeamInfo(
                mlb_tricode="ATL", full_name="Atlanta Braves", city="Atlanta", nickname="Braves",
                espn_tricode="ATL", statcast_tricode="ATL", br_tricode="ATL", bdl_tricode="ATL",
                league="NL", division="East",
                stadium_name="Truist Park", stadium_capacity=41084,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.02, park_factor_hr=1.05,
                latitude=33.8907, longitude=-84.4677, timezone="America/New_York", airport_code="ATL",
                lf_distance=335, cf_distance=400, rf_distance=325
            ),
            MLBTeamInfo(
                mlb_tricode="MIA", full_name="Miami Marlins", city="Miami", nickname="Marlins",
                espn_tricode="MIA", statcast_tricode="MIA", br_tricode="MIA", bdl_tricode="MIA",
                alternate_codes=["FLA"],
                league="NL", division="East",
                stadium_name="LoanDepot Park", stadium_capacity=36742,
                roof_type="Retractable", surface="Grass",
                park_factor_runs=0.92, park_factor_hr=0.85,
                latitude=25.7781, longitude=-80.2196, timezone="America/New_York", airport_code="MIA",
                lf_distance=344, cf_distance=400, rf_distance=335
            ),
            MLBTeamInfo(
                mlb_tricode="NYM", full_name="New York Mets", city="New York", nickname="Mets",
                espn_tricode="NYM", statcast_tricode="NYM", br_tricode="NYM", bdl_tricode="NYM",
                alternate_codes=["NYN"],
                league="NL", division="East",
                stadium_name="Citi Field", stadium_capacity=41922,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.95, park_factor_hr=0.90,
                latitude=40.7571, longitude=-73.8458, timezone="America/New_York", airport_code="LGA",
                lf_distance=335, cf_distance=408, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="PHI", full_name="Philadelphia Phillies", city="Philadelphia", nickname="Phillies",
                espn_tricode="PHI", statcast_tricode="PHI", br_tricode="PHI", bdl_tricode="PHI",
                league="NL", division="East",
                stadium_name="Citizens Bank Park", stadium_capacity=42901,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.08, park_factor_hr=1.15,
                latitude=39.9061, longitude=-75.1665, timezone="America/New_York", airport_code="PHL",
                lf_distance=329, cf_distance=401, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="WSH", full_name="Washington Nationals", city="Washington", nickname="Nationals",
                espn_tricode="WSH", statcast_tricode="WSH", br_tricode="WSN", bdl_tricode="WSH",
                alternate_codes=["WSN", "WAS"],
                league="NL", division="East",
                stadium_name="Nationals Park", stadium_capacity=41339,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.98, park_factor_hr=0.95,
                latitude=38.8730, longitude=-77.0074, timezone="America/New_York", airport_code="DCA",
                lf_distance=336, cf_distance=402, rf_distance=335
            ),

            # NL Central
            MLBTeamInfo(
                mlb_tricode="CHC", full_name="Chicago Cubs", city="Chicago", nickname="Cubs",
                espn_tricode="CHC", statcast_tricode="CHC", br_tricode="CHC", bdl_tricode="CHC",
                league="NL", division="Central",
                stadium_name="Wrigley Field", stadium_capacity=41649,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.05, park_factor_hr=1.10,
                latitude=41.9484, longitude=-87.6553, timezone="America/Chicago", airport_code="ORD",
                lf_distance=355, cf_distance=400, rf_distance=353
            ),
            MLBTeamInfo(
                mlb_tricode="CIN", full_name="Cincinnati Reds", city="Cincinnati", nickname="Reds",
                espn_tricode="CIN", statcast_tricode="CIN", br_tricode="CIN", bdl_tricode="CIN",
                league="NL", division="Central",
                stadium_name="Great American Ball Park", stadium_capacity=42319,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.12, park_factor_hr=1.25,
                latitude=39.0974, longitude=-84.5065, timezone="America/New_York", airport_code="CVG",
                lf_distance=328, cf_distance=404, rf_distance=325
            ),
            MLBTeamInfo(
                mlb_tricode="MIL", full_name="Milwaukee Brewers", city="Milwaukee", nickname="Brewers",
                espn_tricode="MIL", statcast_tricode="MIL", br_tricode="MIL", bdl_tricode="MIL",
                league="NL", division="Central",
                stadium_name="American Family Field", stadium_capacity=41900,
                roof_type="Retractable", surface="Grass",
                park_factor_runs=1.02, park_factor_hr=1.05,
                latitude=43.0280, longitude=-87.9712, timezone="America/Chicago", airport_code="MKE",
                lf_distance=344, cf_distance=400, rf_distance=345
            ),
            MLBTeamInfo(
                mlb_tricode="PIT", full_name="Pittsburgh Pirates", city="Pittsburgh", nickname="Pirates",
                espn_tricode="PIT", statcast_tricode="PIT", br_tricode="PIT", bdl_tricode="PIT",
                league="NL", division="Central",
                stadium_name="PNC Park", stadium_capacity=38362,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.94, park_factor_hr=0.88,
                latitude=40.4469, longitude=-80.0057, timezone="America/New_York", airport_code="PIT",
                lf_distance=325, cf_distance=399, rf_distance=320
            ),
            MLBTeamInfo(
                mlb_tricode="STL", full_name="St. Louis Cardinals", city="St. Louis", nickname="Cardinals",
                espn_tricode="STL", statcast_tricode="STL", br_tricode="STL", bdl_tricode="STL",
                league="NL", division="Central",
                stadium_name="Busch Stadium", stadium_capacity=44494,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.96, park_factor_hr=0.92,
                latitude=38.6226, longitude=-90.1928, timezone="America/Chicago", airport_code="STL",
                lf_distance=336, cf_distance=400, rf_distance=335
            ),

            # NL West
            MLBTeamInfo(
                mlb_tricode="ARI", full_name="Arizona Diamondbacks", city="Phoenix", nickname="Diamondbacks",
                espn_tricode="ARI", statcast_tricode="ARI", br_tricode="ARI", bdl_tricode="ARI",
                alternate_codes=["AZ", "PHX"],
                league="NL", division="West",
                stadium_name="Chase Field", stadium_capacity=48519,
                roof_type="Retractable", surface="Grass",
                park_factor_runs=1.08, park_factor_hr=1.12,
                latitude=33.4455, longitude=-112.0667, timezone="America/Phoenix", airport_code="PHX",
                lf_distance=330, cf_distance=407, rf_distance=335
            ),
            MLBTeamInfo(
                mlb_tricode="COL", full_name="Colorado Rockies", city="Denver", nickname="Rockies",
                espn_tricode="COL", statcast_tricode="COL", br_tricode="COL", bdl_tricode="COL",
                league="NL", division="West",
                stadium_name="Coors Field", stadium_capacity=50144,
                roof_type="Open", surface="Grass",
                park_factor_runs=1.25, park_factor_hr=1.35,  # Highest in MLB due to altitude
                latitude=39.7559, longitude=-104.9942, timezone="America/Denver", airport_code="DEN",
                lf_distance=347, cf_distance=415, rf_distance=350
            ),
            MLBTeamInfo(
                mlb_tricode="LAD", full_name="Los Angeles Dodgers", city="Los Angeles", nickname="Dodgers",
                espn_tricode="LAD", statcast_tricode="LAD", br_tricode="LAD", bdl_tricode="LAD",
                alternate_codes=["LA", "LAN"],
                league="NL", division="West",
                stadium_name="Dodger Stadium", stadium_capacity=56000,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.95, park_factor_hr=0.92,
                latitude=34.0739, longitude=-118.2400, timezone="America/Los_Angeles", airport_code="LAX",
                lf_distance=330, cf_distance=395, rf_distance=330
            ),
            MLBTeamInfo(
                mlb_tricode="SD", full_name="San Diego Padres", city="San Diego", nickname="Padres",
                espn_tricode="SD", statcast_tricode="SD", br_tricode="SDP", bdl_tricode="SD",
                alternate_codes=["SDP", "SDG"],
                league="NL", division="West",
                stadium_name="Petco Park", stadium_capacity=42445,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.92, park_factor_hr=0.85,
                latitude=32.7076, longitude=-117.1570, timezone="America/Los_Angeles", airport_code="SAN",
                lf_distance=336, cf_distance=396, rf_distance=322
            ),
            MLBTeamInfo(
                mlb_tricode="SF", full_name="San Francisco Giants", city="San Francisco", nickname="Giants",
                espn_tricode="SF", statcast_tricode="SF", br_tricode="SFG", bdl_tricode="SF",
                alternate_codes=["SFG", "SFN"],
                league="NL", division="West",
                stadium_name="Oracle Park", stadium_capacity=41915,
                roof_type="Open", surface="Grass",
                park_factor_runs=0.90, park_factor_hr=0.82,
                latitude=37.7786, longitude=-122.3893, timezone="America/Los_Angeles", airport_code="SFO",
                lf_distance=339, cf_distance=399, rf_distance=309
            ),
        ]

        for team in teams:
            self._teams[team.mlb_tricode] = team

    def _build_lookup_tables(self) -> None:
        """Build fast lookup tables for various identifiers."""
        for tricode, team in self._teams.items():
            # Add all codes to lookup
            for code in team.all_codes:
                self._code_to_team[code.upper()] = tricode
                self._code_to_team[code.lower()] = tricode

            # Add name variations
            variations = [
                team.full_name.lower(),
                team.city.lower(),
                team.nickname.lower(),
                f"{team.city} {team.nickname}".lower(),
            ]
            for var in variations:
                self._name_variations[var] = tricode

    def get_team(self, identifier: str) -> Optional[MLBTeamInfo]:
        """
        Get team info by any identifier (code, name, city, nickname).

        Args:
            identifier: Team code, name, city, or nickname

        Returns:
            MLBTeamInfo or None if not found
        """
        if not identifier:
            return None

        # Try direct code lookup
        upper = identifier.upper()
        if upper in self._code_to_team:
            return self._teams[self._code_to_team[upper]]

        # Try name lookup
        lower = identifier.lower().strip()
        if lower in self._name_variations:
            return self._teams[self._name_variations[lower]]

        return None

    def normalize_team_code(self, identifier: str) -> Optional[str]:
        """
        Normalize any team identifier to standard MLB tricode.

        Args:
            identifier: Any team identifier

        Returns:
            Standard MLB tricode (e.g., "NYY") or None
        """
        team = self.get_team(identifier)
        return team.mlb_tricode if team else None

    def fuzzy_match(self, query: str, threshold: float = 0.6) -> Optional[MLBTeamInfo]:
        """
        Fuzzy match team name with configurable threshold.

        Args:
            query: Search query (partial name, misspelling, etc.)
            threshold: Minimum similarity score (0.0 to 1.0)

        Returns:
            Best matching MLBTeamInfo or None
        """
        if not query:
            return None

        # First try exact match
        exact = self.get_team(query)
        if exact:
            return exact

        query_lower = query.lower().strip()
        best_match = None
        best_score = 0.0

        for name, tricode in self._name_variations.items():
            score = self._similarity_score(query_lower, name)
            if score > best_score and score >= threshold:
                best_score = score
                best_match = self._teams[tricode]

        return best_match

    def _similarity_score(self, s1: str, s2: str) -> float:
        """Calculate similarity score between two strings."""
        # Simple substring matching + length ratio
        if s1 in s2 or s2 in s1:
            return 0.8 + 0.2 * (min(len(s1), len(s2)) / max(len(s1), len(s2)))

        # Character overlap
        s1_set = set(s1.replace(' ', ''))
        s2_set = set(s2.replace(' ', ''))
        overlap = len(s1_set & s2_set) / max(len(s1_set | s2_set), 1)

        return overlap * 0.7

    def get_all_teams(self) -> List[MLBTeamInfo]:
        """Get all 30 MLB teams."""
        return list(self._teams.values())

    def get_teams_by_league(self, league: str) -> List[MLBTeamInfo]:
        """Get all teams in a league (AL or NL)."""
        return [t for t in self._teams.values() if t.league == league.upper()]

    def get_teams_by_division(self, division: str) -> List[MLBTeamInfo]:
        """Get all teams in a division (e.g., 'AL East', 'NL Central')."""
        div_upper = division.upper()
        return [t for t in self._teams.values() if t.full_division.upper() == div_upper]

    def get_valid_codes(self) -> Set[str]:
        """Get all valid team codes."""
        codes = set()
        for team in self._teams.values():
            codes.update(team.all_codes)
        return codes

    def is_valid_code(self, code: str) -> bool:
        """Check if a code is a valid MLB team code."""
        return code.upper() in self._code_to_team or code.lower() in self._code_to_team


# Singleton instance
_mapper_instance: Optional[MLBTeamMapper] = None


def get_mlb_team_mapper() -> MLBTeamMapper:
    """Get singleton MLBTeamMapper instance."""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = MLBTeamMapper()
    return _mapper_instance


# Convenience functions
def normalize_mlb_team(identifier: str) -> Optional[str]:
    """Normalize any team identifier to MLB tricode."""
    return get_mlb_team_mapper().normalize_team_code(identifier)


def get_mlb_team_info(identifier: str) -> Optional[MLBTeamInfo]:
    """Get full team info for any identifier."""
    return get_mlb_team_mapper().get_team(identifier)


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    mapper = get_mlb_team_mapper()

    logger.info("MLB Team Mapper Test")
    logger.info("=" * 60)

    # Test various lookups
    test_cases = [
        "NYY", "yankees", "New York Yankees", "NY",
        "LAD", "dodgers", "Los Angeles Dodgers",
        "SF", "giants", "SFG",
        "TB", "rays", "TBR",
        "CWS", "white sox", "CHW",
    ]

    for query in test_cases:
        team = mapper.get_team(query)
        if team:
            logger.info(f"{query:25} -> {team.mlb_tricode} ({team.full_name})")
        else:
            logger.warning(f"{query:25} -> NOT FOUND")

    logger.info(f"Total teams: {len(mapper.get_all_teams())}")
    logger.info(f"AL teams: {len(mapper.get_teams_by_league('AL'))}")
    logger.info(f"NL teams: {len(mapper.get_teams_by_league('NL'))}")
