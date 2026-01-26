#!/usr/bin/env python3
# ============================================================================
# FILE: shared/utils/nba_team_mapper.py
# COMPLETE VERSION - Merged robust mapping + schedule integration
# ============================================================================
"""
Comprehensive NBA Team Mapper with Schedule Integration

Combines:
- Robust team mapping with fuzzy matching
- Multiple tricode systems (NBA.com, Basketball Reference, ESPN)
- Schedule-aware features (back-to-backs, rest days, game context)
- Player props context enrichment

Usage:
    from shared.utils.nba_team_mapper import NBATeamMapper
    
    mapper = NBATeamMapper()
    
    # ORIGINAL FEATURES (Backward Compatible)
    # ========================================
    
    # Basic mapping
    tricode = mapper.get_nba_tricode('Lakers')  # 'LAL'
    team_info = mapper.get_team_info('LAL')     # TeamInfo object
    
    # Fuzzy matching (handles typos)
    tricode = mapper.get_nba_tricode_fuzzy('Lakres', min_confidence=80)  # 'LAL'
    
    # Multiple tricode systems
    br_code = mapper.get_br_tricode('Lakers')    # Basketball Reference format
    espn_code = mapper.get_espn_tricode('Lakers') # ESPN format
    
    # Find by location
    la_teams = mapper.find_teams_by_city('Los Angeles')  # [LAL, LAC]
    
    # NEW SCHEDULE-AWARE FEATURES
    # ===========================
    
    # Team schedule
    schedule = mapper.get_team_schedule('LAL', season=2024)
    
    # Back-to-back detection
    b2b_games = mapper.get_back_to_back_games('LAL', season=2024)
    
    # Rest days
    rest = mapper.get_rest_days('LAL', '2024-01-15')
    
    # Comprehensive game context (perfect for player props!)
    context = mapper.get_game_context('LAL', '2024-01-15')
    # Returns: opponent, is_home_game, rest_days, is_back_to_back, matchup
"""

import re
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass

# Import schedule service for new features (optional - may not exist in all deployments)
try:
    from shared.utils.schedule import NBAScheduleService, GameType, NBAGame
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False
    NBAScheduleService = None
    GameType = None
    NBAGame = None
    logging.warning("schedule service not available - schedule features disabled")

# Fuzzy matching (optional - gracefully degrade if not available)
try:
    from fuzzywuzzy import fuzz, process
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False
    logging.warning("fuzzywuzzy not available - fuzzy matching disabled")

logger = logging.getLogger(__name__)


@dataclass
class TeamInfo:
    """Complete team information with all identifier variations."""
    # Standard identifiers
    nba_tricode: str        # NBA.com standard (ATL, LAL, etc.)
    br_tricode: str         # Basketball Reference (ATL, LAL, BRK, etc.) 
    espn_tricode: str       # ESPN (ATL, LAL, GS, etc.)
    
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
    Comprehensive NBA team mapper combining robust matching + schedule integration.
    
    Features:
    - Multiple tricode systems (NBA.com, Basketball Reference, ESPN)
    - Fuzzy string matching for typos/variations
    - Forward and reverse lookups
    - City/state/conference queries
    - Schedule-aware features (back-to-backs, rest days, game context)
    """
    
    def __init__(self, use_database: bool = True):
        """
        Initialize team mapper with optional schedule integration.
        
        Args:
            use_database: If True, use database-first mode for faster schedule queries
        """
        # Load team data
        self.teams_data = self._load_teams_data()
        self.nba_tricode_lookup = {}
        self.fuzzy_lookup_cache = {}
        self._build_lookup_indexes()
        
        # Initialize schedule service for new features (if available)
        if SCHEDULE_AVAILABLE and NBAScheduleService is not None:
            self.schedule = NBAScheduleService(use_database=use_database)
        else:
            self.schedule = None

        # Cache for team schedules
        self._team_schedule_cache: Dict[Tuple[str, int], List] = {}
        
        logger.info("NBATeamMapper initialized with %d teams", len(self.teams_data))
    
    def _load_teams_data(self) -> List[TeamInfo]:
        """Load comprehensive team data for all 30 NBA teams."""
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
                common_variations=["nets", "brooklyn nets", "bkn nets", "brk nets"],
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
                common_variations=["hornets", "charlotte hornets", "cha hornets", "cho hornets"],
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
                common_variations=["warriors", "golden state warriors", "gsw warriors", "gs warriors", "dubs"],
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
                common_variations=["suns", "phoenix suns", "phx suns", "pho suns"],
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
                common_variations=["pelicans", "pels", "new orleans pelicans", "no pelicans", "nop pelicans"],
                state="Louisiana", division="Southwest", conference="Western"
            ),
            TeamInfo(
                nba_tricode="SAS", br_tricode="SAS", espn_tricode="SA", 
                full_name="San Antonio Spurs", city="San Antonio", nickname="Spurs",
                common_variations=["spurs", "san antonio spurs", "sas spurs", "sa spurs"],
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
    
    # ========================================================================
    # ORIGINAL MAPPING FEATURES (Backward Compatible)
    # ========================================================================
    
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
        
        # Fuzzy matching requires fuzzywuzzy
        if not FUZZY_AVAILABLE:
            logger.warning("Fuzzy matching not available - fuzzywuzzy not installed")
            return None
        
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
                    logger.info(
                        "Fuzzy matched '%s' → '%s' → %s (confidence: %d%%)",
                        team_identifier, matched_name, result, confidence
                    )
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
    
    def get_team_full_name(self, team_code: str) -> Optional[str]:
        """
        Get full team name from code (alias for compatibility).
        
        Args:
            team_code: Team code (e.g., 'LAL')
            
        Returns:
            Full team name (e.g., 'Los Angeles Lakers') or None
        """
        team_info = self.get_team_info(team_code)
        return team_info.full_name if team_info else None
    
    def get_team_code(self, team_name: str) -> Optional[str]:
        """
        Get team code from full name (alias for get_nba_tricode).
        
        Args:
            team_name: Full or partial team name
            
        Returns:
            Team code or None
        """
        return self.get_nba_tricode(team_name)
    
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
    
    def get_all_team_codes(self) -> List[str]:
        """Get list of all valid NBA team codes (alias)."""
        return self.get_all_nba_tricodes()
    
    def is_valid_team(self, team_code: str) -> bool:
        """
        Check if team code is valid.
        
        Args:
            team_code: Team code to validate
            
        Returns:
            True if valid NBA team code
        """
        return self.get_nba_tricode(team_code) is not None
    
    def validate_team_identifier(
        self, 
        team_identifier: str, 
        fuzzy: bool = True
    ) -> Tuple[bool, Optional[str], Optional[str]]:
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
        if fuzzy and FUZZY_AVAILABLE:
            fuzzy_match = self.get_nba_tricode_fuzzy(team_identifier)
            if fuzzy_match:
                return True, fuzzy_match, "fuzzy"
        
        return False, None, None
    
    # ========================================================================
    # NEW: Schedule-Aware Features
    # ========================================================================
    
    def get_team_schedule(
        self,
        team_code: str,
        season: int,
        game_type = None  # GameType.REGULAR_PLAYOFF if available
    ) -> List:
        """
        Get all games for a team in a season.
        
        Args:
            team_code: Team code (e.g., 'LAL')
            season: Season year (e.g., 2024 for 2024-25)
            game_type: Type of games to include
            
        Returns:
            List of NBAGame objects for this team, sorted by date
        """
        # Normalize team code
        team_code = self.get_nba_tricode(team_code)
        if not team_code:
            return []
        
        # Check cache
        cache_key = (team_code, season)
        if cache_key in self._team_schedule_cache:
            return self._team_schedule_cache[cache_key]
        
        # Get all games for season
        all_dates = self.schedule.get_all_game_dates(seasons=[season], game_type=game_type)
        
        # Filter to team's games
        team_games = []
        for date_info in all_dates:
            for game in date_info['games']:
                if game.away_team == team_code or game.home_team == team_code:
                    team_games.append(game)
        
        # Sort by date
        team_games.sort(key=lambda g: g.game_date)
        
        # Cache result
        self._team_schedule_cache[cache_key] = team_games
        
        logger.debug("Found %d games for %s in season %d", len(team_games), team_code, season)
        return team_games
    
    def get_back_to_back_games(self, team_code: str, season: int) -> List[Tuple]:
        """
        Find back-to-back games for a team.
        
        Useful for:
        - Rest analysis
        - Player load management
        - Betting props adjustments
        
        Args:
            team_code: Team code
            season: Season year
            
        Returns:
            List of (game1, game2) tuples for consecutive game dates
        """
        team_schedule = self.get_team_schedule(team_code, season)
        
        back_to_backs = []
        for i in range(len(team_schedule) - 1):
            date1 = datetime.strptime(team_schedule[i].game_date, '%Y-%m-%d').date()
            date2 = datetime.strptime(team_schedule[i+1].game_date, '%Y-%m-%d').date()
            
            if (date2 - date1).days == 1:
                back_to_backs.append((team_schedule[i], team_schedule[i+1]))
        
        logger.debug("Found %d back-to-back sets for %s", len(back_to_backs), team_code)
        return back_to_backs
    
    def get_rest_days(self, team_code: str, game_date: str, season: Optional[int] = None) -> int:
        """
        Calculate rest days before a game.
        
        Args:
            team_code: Team code
            game_date: Game date (YYYY-MM-DD)
            season: Season year (auto-detected if not provided)
            
        Returns:
            Number of rest days (0 = back-to-back, 1 = one day rest, etc.)
        """
        # Normalize team code
        team_code = self.get_nba_tricode(team_code)
        if not team_code:
            return 99
        
        if not season:
            date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            season = date_obj.year if date_obj.month >= 10 else date_obj.year - 1
        
        team_schedule = self.get_team_schedule(team_code, season)
        
        # Find this game and previous game
        current_game_idx = None
        for i, game in enumerate(team_schedule):
            if game.game_date == game_date:
                current_game_idx = i
                break
        
        if current_game_idx is None or current_game_idx == 0:
            return 99  # First game of season or not found
        
        prev_game = team_schedule[current_game_idx - 1]
        curr_date = datetime.strptime(game_date, '%Y-%m-%d').date()
        prev_date = datetime.strptime(prev_game.game_date, '%Y-%m-%d').date()
        
        rest_days = (curr_date - prev_date).days - 1
        return rest_days
    
    def is_home_game(self, team_code: str, game_date: str, season: Optional[int] = None) -> bool:
        """
        Check if team is playing at home on a specific date.
        
        Args:
            team_code: Team code
            game_date: Game date (YYYY-MM-DD)
            season: Season year (auto-detected if not provided)
            
        Returns:
            True if home game, False if away
        """
        # Normalize team code
        team_code = self.get_nba_tricode(team_code)
        if not team_code:
            return False
        
        if not season:
            date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            season = date_obj.year if date_obj.month >= 10 else date_obj.year - 1
        
        games = self.schedule.get_games_for_date(game_date)
        
        for game in games:
            if game.away_team == team_code:
                return False
            elif game.home_team == team_code:
                return True
        
        return False
    
    def get_opponent(self, team_code: str, game_date: str, season: Optional[int] = None) -> Optional[str]:
        """
        Get opponent team code for a game.
        
        Args:
            team_code: Team code
            game_date: Game date (YYYY-MM-DD)
            season: Season year (auto-detected if not provided)
            
        Returns:
            Opponent team code or None
        """
        # Normalize team code
        team_code = self.get_nba_tricode(team_code)
        if not team_code:
            return None
        
        if not season:
            date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            season = date_obj.year if date_obj.month >= 10 else date_obj.year - 1
        
        games = self.schedule.get_games_for_date(game_date)
        
        for game in games:
            if game.away_team == team_code:
                return game.home_team
            elif game.home_team == team_code:
                return game.away_team
        
        return None
    
    def get_home_away_splits(self, team_code: str, season: int) -> Dict[str, int]:
        """
        Get home/away game counts for a team.
        
        Args:
            team_code: Team code
            season: Season year
            
        Returns:
            Dictionary with 'home' and 'away' counts
        """
        team_schedule = self.get_team_schedule(team_code, season)
        
        # Normalize team code for comparison
        team_code = self.get_nba_tricode(team_code)
        
        home_count = sum(1 for game in team_schedule if game.home_team == team_code)
        away_count = sum(1 for game in team_schedule if game.away_team == team_code)
        
        return {
            'home': home_count,
            'away': away_count,
            'total': len(team_schedule)
        }
    
    def get_game_context(self, team_code: str, game_date: str, season: Optional[int] = None) -> Dict:
        """
        Get comprehensive game context for a team.
        
        Useful for player props analysis - provides all relevant context in one call.
        
        Args:
            team_code: Team code
            game_date: Game date (YYYY-MM-DD)
            season: Season year (auto-detected if not provided)
            
        Returns:
            Dictionary with game context:
            - opponent: Opponent team code
            - opponent_full_name: Opponent full name
            - is_home_game: Boolean
            - rest_days: Number of rest days
            - is_back_to_back: Boolean
            - matchup: Matchup string (e.g., 'LAL@GSW')
        """
        # Normalize team code
        team_code = self.get_nba_tricode(team_code)
        if not team_code:
            return {}
        
        if not season:
            date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            season = date_obj.year if date_obj.month >= 10 else date_obj.year - 1
        
        opponent = self.get_opponent(team_code, game_date, season)
        is_home = self.is_home_game(team_code, game_date, season)
        rest_days = self.get_rest_days(team_code, game_date, season)
        
        context = {
            'team': team_code,
            'team_full_name': self.get_team_full_name(team_code),
            'game_date': game_date,
            'opponent': opponent,
            'opponent_full_name': self.get_team_full_name(opponent) if opponent else None,
            'is_home_game': is_home,
            'location': 'HOME' if is_home else 'AWAY',
            'rest_days': rest_days,
            'is_back_to_back': rest_days == 0,
            'matchup': f"{team_code}@{opponent}" if not is_home else f"{opponent}@{team_code}"
        }
        
        return context
    
    def clear_cache(self):
        """Clear all caches (fuzzy lookup + team schedule)."""
        self.fuzzy_lookup_cache.clear()
        self._team_schedule_cache.clear()
        self.schedule.clear_cache()
        logger.info("All caches cleared")


# ============================================================================
# Global instance and convenience functions for backward compatibility
# ============================================================================

# Lazy-loaded global instance (initialized on first use to avoid cold start issues)
_nba_team_mapper: Optional['NBATeamMapper'] = None

def get_nba_team_mapper() -> 'NBATeamMapper':
    """Get or create the global NBATeamMapper instance."""
    global _nba_team_mapper
    if _nba_team_mapper is None:
        _nba_team_mapper = NBATeamMapper()
    return _nba_team_mapper

# Backward compatibility alias (deprecated, use convenience functions instead)
nba_team_mapper = get_nba_team_mapper

# Convenience functions
def get_nba_tricode(team_identifier: str) -> Optional[str]:
    """Convenience function - get NBA tricode."""
    return get_nba_team_mapper().get_nba_tricode(team_identifier)

def get_nba_tricode_fuzzy(team_identifier: str, min_confidence: int = 80) -> Optional[str]:
    """Convenience function - get NBA tricode with fuzzy matching."""
    return get_nba_team_mapper().get_nba_tricode_fuzzy(team_identifier, min_confidence)

def get_team_info(team_identifier: str) -> Optional[TeamInfo]:
    """Convenience function - get complete team info."""
    return get_nba_team_mapper().get_team_info(team_identifier)

def get_team_full_name(team_code: str) -> Optional[str]:
    """Convenience function - get full team name."""
    return get_nba_team_mapper().get_team_full_name(team_code)