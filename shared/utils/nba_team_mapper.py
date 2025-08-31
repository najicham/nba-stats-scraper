#!/usr/bin/env python3
"""
File: shared/utils/nba_team_mapper.py

Comprehensive NBA team mapping utility supporting:
- Multiple team name formats (full names, nicknames, abbreviations)
- Different tricode systems (NBA.com vs Basketball Reference vs ESPN)
- Fuzzy string matching for robustness
- Forward and reverse lookups
- City/state variations

Used across scrapers, processors, and report generators for consistent team identification.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from fuzzywuzzy import fuzz, process

logger = logging.getLogger(__name__)

@dataclass
class TeamInfo:
    """Complete team information with all identifier variations."""
    # Standard identifiers
    nba_tricode: str        # NBA.com standard (ATL, LAL, etc.)
    br_tricode: str         # Basketball Reference (ATL, LAL, etc.) 
    espn_tricode: str       # ESPN (ATL, LAL, etc.)
    
    # Names
    full_name: str          # "Atlanta Hawks"
    city: str              # "Atlanta" 
    nickname: str          # "Hawks"
    
    # Variations
    common_variations: List[str]  # ["Hawks", "atlanta hawks", "ATL Hawks"]
    
    # Geographic
    state: str             # "Georgia"
    division: str          # "Southeast"
    conference: str        # "Eastern"

class NBATeamMapper:
    """
    Robust NBA team mapping with fuzzy matching and multiple identifier systems.
    
    Usage:
        mapper = NBATeamMapper()
        
        # Basic lookups
        abbr = mapper.get_nba_tricode("hawks")  # "ATL"
        team = mapper.get_team_info("LAL")      # TeamInfo object
        
        # Fuzzy matching
        abbr = mapper.get_nba_tricode_fuzzy("Hawkss", min_confidence=80)  # "ATL"
        
        # Reverse lookups
        teams = mapper.find_teams_by_city("Los Angeles")  # [TeamInfo for LAL, LAC]
    """
    
    def __init__(self):
        self.teams_data = self._load_teams_data()
        self.nba_tricode_lookup = {}
        self.fuzzy_lookup_cache = {}
        self._build_lookup_indexes()
    
    def _load_teams_data(self) -> List[TeamInfo]:
        """Load comprehensive team data. In production, could load from external source."""
        return [
            # Eastern Conference - Atlantic
            TeamInfo(
                nba_tricode="BOS", br_tricode="BOS", espn_tricode="BOS",
                full_name="Boston Celtics", city="Boston", nickname="Celtics",
                common_variations=["celtics", "boston celtics", "bos celtics"],
                state="Massachusetts", division="Atlantic", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="BKN", br_tricode="BRK", espn_tricode="BKN", 
                full_name="Brooklyn Nets", city="Brooklyn", nickname="Nets",
                common_variations=["nets", "brooklyn nets", "bkn nets"],
                state="New York", division="Atlantic", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="NYK", br_tricode="NYK", espn_tricode="NY",
                full_name="New York Knicks", city="New York", nickname="Knicks", 
                common_variations=["knicks", "new york knicks", "ny knicks"],
                state="New York", division="Atlantic", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="PHI", br_tricode="PHI", espn_tricode="PHI",
                full_name="Philadelphia 76ers", city="Philadelphia", nickname="76ers",
                common_variations=["76ers", "sixers", "philadelphia 76ers", "philadelphia sixers"],
                state="Pennsylvania", division="Atlantic", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="TOR", br_tricode="TOR", espn_tricode="TOR",
                full_name="Toronto Raptors", city="Toronto", nickname="Raptors",
                common_variations=["raptors", "toronto raptors", "tor raptors"],
                state="Ontario", division="Atlantic", conference="Eastern"
            ),
            
            # Eastern Conference - Central  
            TeamInfo(
                nba_tricode="CHI", br_tricode="CHI", espn_tricode="CHI",
                full_name="Chicago Bulls", city="Chicago", nickname="Bulls",
                common_variations=["bulls", "chicago bulls", "chi bulls"],
                state="Illinois", division="Central", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="CLE", br_tricode="CLE", espn_tricode="CLE", 
                full_name="Cleveland Cavaliers", city="Cleveland", nickname="Cavaliers",
                common_variations=["cavaliers", "cavs", "cleveland cavaliers", "cleveland cavs"],
                state="Ohio", division="Central", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="DET", br_tricode="DET", espn_tricode="DET",
                full_name="Detroit Pistons", city="Detroit", nickname="Pistons",
                common_variations=["pistons", "detroit pistons", "det pistons"], 
                state="Michigan", division="Central", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="IND", br_tricode="IND", espn_tricode="IND",
                full_name="Indiana Pacers", city="Indiana", nickname="Pacers",
                common_variations=["pacers", "indiana pacers", "ind pacers"],
                state="Indiana", division="Central", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="MIL", br_tricode="MIL", espn_tricode="MIL",
                full_name="Milwaukee Bucks", city="Milwaukee", nickname="Bucks",
                common_variations=["bucks", "milwaukee bucks", "mil bucks"],
                state="Wisconsin", division="Central", conference="Eastern"
            ),
            
            # Eastern Conference - Southeast
            TeamInfo(
                nba_tricode="ATL", br_tricode="ATL", espn_tricode="ATL",
                full_name="Atlanta Hawks", city="Atlanta", nickname="Hawks",
                common_variations=["hawks", "atlanta hawks", "atl hawks"],
                state="Georgia", division="Southeast", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="CHA", br_tricode="CHO", espn_tricode="CHA", 
                full_name="Charlotte Hornets", city="Charlotte", nickname="Hornets",
                common_variations=["hornets", "charlotte hornets", "cha hornets"],
                state="North Carolina", division="Southeast", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="MIA", br_tricode="MIA", espn_tricode="MIA",
                full_name="Miami Heat", city="Miami", nickname="Heat",
                common_variations=["heat", "miami heat", "mia heat"],
                state="Florida", division="Southeast", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="ORL", br_tricode="ORL", espn_tricode="ORL",
                full_name="Orlando Magic", city="Orlando", nickname="Magic",
                common_variations=["magic", "orlando magic", "orl magic"],
                state="Florida", division="Southeast", conference="Eastern"
            ),
            TeamInfo(
                nba_tricode="WAS", br_tricode="WAS", espn_tricode="WAS",
                full_name="Washington Wizards", city="Washington", nickname="Wizards",
                common_variations=["wizards", "washington wizards", "was wizards"],
                state="District of Columbia", division="Southeast", conference="Eastern"
            ),
            
            # Western Conference - Northwest
            TeamInfo(
                nba_tricode="DEN", br_tricode="DEN", espn_tricode="DEN",
                full_name="Denver Nuggets", city="Denver", nickname="Nuggets",
                common_variations=["nuggets", "denver nuggets", "den nuggets"],
                state="Colorado", division="Northwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="MIN", br_tricode="MIN", espn_tricode="MIN",
                full_name="Minnesota Timberwolves", city="Minnesota", nickname="Timberwolves",
                common_variations=["timberwolves", "wolves", "minnesota timberwolves", "min wolves"],
                state="Minnesota", division="Northwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="OKC", br_tricode="OKC", espn_tricode="OKC",
                full_name="Oklahoma City Thunder", city="Oklahoma City", nickname="Thunder", 
                common_variations=["thunder", "oklahoma city thunder", "okc thunder"],
                state="Oklahoma", division="Northwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="POR", br_tricode="POR", espn_tricode="POR",
                full_name="Portland Trail Blazers", city="Portland", nickname="Trail Blazers",
                common_variations=["trail blazers", "blazers", "portland trail blazers", "portland blazers"],
                state="Oregon", division="Northwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="UTA", br_tricode="UTA", espn_tricode="UTAH",
                full_name="Utah Jazz", city="Utah", nickname="Jazz",
                common_variations=["jazz", "utah jazz", "uta jazz"],
                state="Utah", division="Northwest", conference="Western"
            ),
            
            # Western Conference - Pacific
            TeamInfo(
                nba_tricode="GSW", br_tricode="GSW", espn_tricode="GS", 
                full_name="Golden State Warriors", city="Golden State", nickname="Warriors",
                common_variations=["warriors", "golden state warriors", "gsw warriors", "dubs"],
                state="California", division="Pacific", conference="Western"
            ),
            TeamInfo(
                nba_tricode="LAC", br_tricode="LAC", espn_tricode="LAC",
                full_name="Los Angeles Clippers", city="Los Angeles", nickname="Clippers",
                common_variations=["clippers", "los angeles clippers", "la clippers", "lac clippers"],
                state="California", division="Pacific", conference="Western"
            ),
            TeamInfo(
                nba_tricode="LAL", br_tricode="LAL", espn_tricode="LAL",
                full_name="Los Angeles Lakers", city="Los Angeles", nickname="Lakers", 
                common_variations=["lakers", "los angeles lakers", "la lakers", "lal lakers"],
                state="California", division="Pacific", conference="Western"
            ),
            TeamInfo(
                nba_tricode="PHX", br_tricode="PHO", espn_tricode="PHX",
                full_name="Phoenix Suns", city="Phoenix", nickname="Suns",
                common_variations=["suns", "phoenix suns", "phx suns"],
                state="Arizona", division="Pacific", conference="Western"
            ),
            TeamInfo(
                nba_tricode="SAC", br_tricode="SAC", espn_tricode="SAC",
                full_name="Sacramento Kings", city="Sacramento", nickname="Kings",
                common_variations=["kings", "sacramento kings", "sac kings"],
                state="California", division="Pacific", conference="Western"
            ),
            
            # Western Conference - Southwest
            TeamInfo(
                nba_tricode="DAL", br_tricode="DAL", espn_tricode="DAL",
                full_name="Dallas Mavericks", city="Dallas", nickname="Mavericks",
                common_variations=["mavericks", "mavs", "dallas mavericks", "dallas mavs"],
                state="Texas", division="Southwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="HOU", br_tricode="HOU", espn_tricode="HOU",
                full_name="Houston Rockets", city="Houston", nickname="Rockets",
                common_variations=["rockets", "houston rockets", "hou rockets"],
                state="Texas", division="Southwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="MEM", br_tricode="MEM", espn_tricode="MEM",
                full_name="Memphis Grizzlies", city="Memphis", nickname="Grizzlies",
                common_variations=["grizzlies", "grizz", "memphis grizzlies", "mem grizzlies"],
                state="Tennessee", division="Southwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="NOP", br_tricode="NOP", espn_tricode="NO",
                full_name="New Orleans Pelicans", city="New Orleans", nickname="Pelicans",
                common_variations=["pelicans", "pels", "new orleans pelicans", "no pelicans"],
                state="Louisiana", division="Southwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="SAS", br_tricode="SAS", espn_tricode="SA", 
                full_name="San Antonio Spurs", city="San Antonio", nickname="Spurs",
                common_variations=["spurs", "san antonio spurs", "sas spurs"],
                state="Texas", division="Southwest", conference="Western"
            ),
        ]
    
    def _build_lookup_indexes(self):
        """Build fast lookup indexes for all team identifiers."""
        for team in self.teams_data:
            # Build comprehensive lookup dictionary
            identifiers = [
                # Official tricodes
                team.nba_tricode.lower(),
                team.br_tricode.lower(), 
                team.espn_tricode.lower(),
                
                # Names
                team.full_name.lower(),
                team.nickname.lower(),
                team.city.lower(),
                
                # Common variations
                *[var.lower() for var in team.common_variations],
                
                # Normalized versions (remove spaces, punctuation)
                self._normalize_string(team.full_name),
                self._normalize_string(team.nickname),
                self._normalize_string(team.city)
            ]
            
            # Remove duplicates and empty strings
            identifiers = list(set(filter(None, identifiers)))
            
            # Map all identifiers to this team
            for identifier in identifiers:
                self.nba_tricode_lookup[identifier] = team.nba_tricode
    
    def _normalize_string(self, text: str) -> str:
        """Normalize string for matching (remove spaces, punctuation, lowercase)."""
        if not text:
            return ""
        return re.sub(r'[^a-z0-9]', '', text.lower())
    
    def get_nba_tricode(self, team_identifier: str) -> Optional[str]:
        """
        Get NBA tricode from any team identifier.
        
        Args:
            team_identifier: Team name, nickname, city, or abbreviation
            
        Returns:
            NBA tricode (e.g. "ATL") or None if not found
        """
        if not team_identifier:
            return None
            
        # Try exact lookup first (fast)
        normalized = team_identifier.lower().strip()
        result = self.nba_tricode_lookup.get(normalized)
        if result:
            return result
        
        # Try normalized lookup
        normalized = self._normalize_string(team_identifier)
        return self.nba_tricode_lookup.get(normalized)
    
    def get_nba_tricode_fuzzy(self, team_identifier: str, min_confidence: int = 80) -> Optional[str]:
        """
        Get NBA tricode using fuzzy string matching.
        
        Args:
            team_identifier: Team identifier that might have typos/variations
            min_confidence: Minimum fuzzy match confidence (0-100)
            
        Returns:
            NBA tricode or None if no confident match found
        """
        if not team_identifier:
            return None
        
        # Try exact match first
        exact_match = self.get_nba_tricode(team_identifier)
        if exact_match:
            return exact_match
        
        # Check cache
        cache_key = (team_identifier.lower(), min_confidence)
        if cache_key in self.fuzzy_lookup_cache:
            return self.fuzzy_lookup_cache[cache_key]
        
        # Fuzzy match against all team full names
        team_names = [team.full_name for team in self.teams_data]
        match_result = process.extractOne(
            team_identifier,
            team_names,
            scorer=fuzz.partial_ratio,
            score_cutoff=min_confidence
        )
        
        result = None
        if match_result:
            matched_name, confidence = match_result
            # Find the team with this full name
            for team in self.teams_data:
                if team.full_name == matched_name:
                    result = team.nba_tricode
                    logger.info(f"Fuzzy matched '{team_identifier}' → '{matched_name}' → {result} (confidence: {confidence}%)")
                    break
        
        # Cache result
        self.fuzzy_lookup_cache[cache_key] = result
        return result
    
    def get_team_info(self, team_identifier: str) -> Optional[TeamInfo]:
        """Get complete team information."""
        tricode = self.get_nba_tricode(team_identifier)
        if not tricode:
            return None
        
        for team in self.teams_data:
            if team.nba_tricode == tricode:
                return team
        return None
    
    def get_br_tricode(self, team_identifier: str) -> Optional[str]:
        """Get Basketball Reference tricode."""
        team_info = self.get_team_info(team_identifier)
        return team_info.br_tricode if team_info else None
    
    def get_espn_tricode(self, team_identifier: str) -> Optional[str]:
        """Get ESPN tricode.""" 
        team_info = self.get_team_info(team_identifier)
        return team_info.espn_tricode if team_info else None
    
    def find_teams_by_city(self, city: str) -> List[TeamInfo]:
        """Find all teams in a city (e.g., Los Angeles has Lakers and Clippers)."""
        normalized_city = city.lower().strip()
        return [team for team in self.teams_data if team.city.lower() == normalized_city]
    
    def find_teams_by_state(self, state: str) -> List[TeamInfo]:
        """Find all teams in a state."""
        normalized_state = state.lower().strip()
        return [team for team in self.teams_data if team.state.lower() == normalized_state]
    
    def get_all_nba_tricodes(self) -> List[str]:
        """Get list of all NBA tricodes."""
        return [team.nba_tricode for team in self.teams_data]
    
    def validate_team_identifier(self, team_identifier: str, fuzzy: bool = True) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate and normalize a team identifier.
        
        Returns:
            (is_valid, normalized_tricode, resolution_method)
        """
        if not team_identifier:
            return False, None, None
        
        # Try exact match
        exact_match = self.get_nba_tricode(team_identifier)
        if exact_match:
            return True, exact_match, "exact"
        
        # Try fuzzy match if enabled
        if fuzzy:
            fuzzy_match = self.get_nba_tricode_fuzzy(team_identifier)
            if fuzzy_match:
                return True, fuzzy_match, "fuzzy"
        
        return False, None, None


# Global instance for easy importing
nba_team_mapper = NBATeamMapper()

# Convenience functions for backward compatibility
def get_nba_tricode(team_identifier: str) -> Optional[str]:
    """Convenience function - get NBA tricode."""
    return nba_team_mapper.get_nba_tricode(team_identifier)

def get_nba_tricode_fuzzy(team_identifier: str, min_confidence: int = 80) -> Optional[str]:
    """Convenience function - get NBA tricode with fuzzy matching.""" 
    return nba_team_mapper.get_nba_tricode_fuzzy(team_identifier, min_confidence)

def get_team_info(team_identifier: str) -> Optional[TeamInfo]:
    """Convenience function - get complete team info."""
    return nba_team_mapper.get_team_info(team_identifier)
