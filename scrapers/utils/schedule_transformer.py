"""
File: scrapers/utils/schedule_transformer.py

Shared schedule data enhancement logic for both API and CDN scrapers.
Ensures consistent data format regardless of source.

This module provides:
- Broadcaster analysis and primetime detection
- Game context flags (playoffs, All-Star, etc.)
- Scheduling metadata (time slots, weekends)
- Season progress tracking and metadata generation
"""

import logging
from typing import Dict, List, Any
from collections import Counter

logger = logging.getLogger(__name__)


class ScheduleTransformer:
    """
    Transform and enhance NBA schedule data with computed flags.
    
    Used by both nbac_schedule_api and nbac_schedule_cdn scrapers
    to ensure consistent output format.
    """
    
    # Network configuration based on NBA broadcast deals
    # Updated for 2024-25 current season and 2025-26+ future seasons
    PRIMETIME_NETWORKS = {
        # Traditional broadcast networks (highest priority - Finals, marquee games)
        'ABC': {'priority': 1, 'type': 'broadcast', 'seasons': 'all'},
        'NBC': {'priority': 2, 'type': 'broadcast', 'seasons': '2025-26+'},  # Returns next season
        
        # Premium cable networks  
        'ESPN': {'priority': 3, 'type': 'cable', 'seasons': 'all'},
        'TNT': {'priority': 4, 'type': 'cable', 'seasons': '2024-25'},  # Exits after this season
        
        # Major streaming platforms (lower priority but still primetime)
        'Amazon Prime': {'priority': 5, 'type': 'streaming', 'seasons': '2025-26+'},  # New exclusive games
        'Peacock': {'priority': 6, 'type': 'streaming', 'seasons': '2025-26+'},  # NBC streaming partner
    }
    
    # National but not traditionally "primetime" 
    NATIONAL_NETWORKS = ['NBA TV', 'NBATV']
    
    # Streaming supplements (simulcasts, not exclusive)
    STREAMING_SUPPLEMENTS = ['ESPN+', 'Max', 'Disney+', 'truTV']  # Max exits with TNT
    
    def __init__(self, season_nba_format: str):
        """
        Args:
            season_nba_format: NBA season format like "2024-25" or "2025-26"
        """
        self.season = season_nba_format
        self.active_networks = self._get_active_networks(season_nba_format)
        logger.debug(f"ScheduleTransformer initialized for {season_nba_format} with {len(self.active_networks)} active networks")
    
    def _get_active_networks(self, season: str) -> dict:
        """Filter networks based on season availability"""
        active = {}
        for network, config in self.PRIMETIME_NETWORKS.items():
            seasons = config['seasons']
            if seasons == 'all':
                active[network] = config
            elif seasons == '2024-25' and season == '2024-25':
                active[network] = config
            elif seasons == '2025-26+' and season >= '2025-26':
                active[network] = config
        return active
    
    def enhance_game(self, game: dict, game_date: str) -> dict:
        """
        Add computed flags to a game object while preserving raw data.
        
        Removes bulky fields for storage optimization.
        
        Args:
            game: Raw game dictionary from NBA.com
            game_date: Game date string
            
        Returns:
            Enhanced game dictionary with computed flags
        """
        enhanced = game.copy()
        
        # Remove bulky fields that aren't needed for props platform
        fields_to_remove = ['tickets', 'links', 'promotions', 'seriesText', 'pointsLeaders']
        for field in fields_to_remove:
            enhanced.pop(field, None)
        
        # Broadcaster analysis (extract before removing)
        broadcaster_info = self._analyze_broadcasters(game.get('broadcasters', {}))
        enhanced.update(broadcaster_info)
        
        # Remove broadcaster object after extracting flags (storage optimization)
        enhanced.pop('broadcasters', None)
        
        # Game context flags
        context_info = self._analyze_game_context(game, game_date)
        enhanced.update(context_info)
        
        # Scheduling flags
        scheduling_info = self._analyze_scheduling(game, game_date)
        enhanced.update(scheduling_info)
        
        return enhanced
    
    def _analyze_broadcasters(self, broadcasters_obj: dict) -> dict:
        """
        Extract broadcaster flags and primary network info.
        
        Returns dict with:
        - isPrimetime: bool (ABC, ESPN, NBC, etc.)
        - hasNationalTV: bool (any national broadcast)
        - primaryNetwork: str (highest priority network)
        - traditionalNetworks: list (cable/broadcast networks)
        - streamingPlatforms: list (streaming services)
        """
        if not broadcasters_obj:
            return {
                'isPrimetime': False,
                'hasNationalTV': False,
                'primaryNetwork': None,
                'traditionalNetworks': [],
                'streamingPlatforms': [],
            }
        
        national_tv = broadcasters_obj.get('nationalTvBroadcasters', [])
        if not isinstance(national_tv, list):
            national_tv = []
        
        # Extract network names safely
        national_networks = []
        for broadcaster in national_tv:
            if broadcaster and isinstance(broadcaster, dict):
                display_name = broadcaster.get('broadcasterDisplay', '')
                if display_name:
                    national_networks.append(display_name)
        
        # Parse traditional networks vs streaming platforms
        traditional_networks = []
        streaming_platforms = []
        
        for network_display in national_networks:
            # Split on '/' to handle cases like "ABC/ESPN+/Disney+"
            network_parts = [part.strip() for part in network_display.split('/')]
            
            for part in network_parts:
                part_upper = part.upper()
                
                # Check if it's a traditional primetime network
                is_traditional = False
                for network_key in self.active_networks.keys():
                    if network_key.upper() in part_upper:
                        if part not in traditional_networks:
                            traditional_networks.append(part)
                        is_traditional = True
                        break
                
                # Check if it's a streaming platform (if not traditional)
                if not is_traditional:
                    for streaming in self.STREAMING_SUPPLEMENTS:
                        if streaming.upper() in part_upper:
                            if part not in streaming_platforms:
                                streaming_platforms.append(part)
                            break
                    # Also check for standalone streaming services
                    standalone_streaming = ['PEACOCK', 'AMAZON PRIME', 'PRIME VIDEO', 'NETFLIX', 'APPLE TV']
                    for streaming in standalone_streaming:
                        if streaming in part_upper:
                            if part not in streaming_platforms:
                                streaming_platforms.append(part)
                            break
        
        # Determine primary network from traditional networks only
        primetime_networks_found = []
        is_primetime = False
        for network in traditional_networks:
            for network_key, network_info in self.active_networks.items():
                if network_key.upper() in network.upper():
                    is_primetime = True
                    primetime_networks_found.append((network_key, network, network_info['priority']))
                    break
        
        # Sort by priority to determine primary network
        primary_network = None
        if primetime_networks_found:
            primetime_networks_found.sort(key=lambda x: x[2])  # Sort by priority
            primary_network = primetime_networks_found[0][0]  # Take highest priority
        
        # If no primetime network, check for NBA TV in traditional networks
        if not primary_network:
            for network in traditional_networks:
                if any(nba_tv in network.upper() for nba_tv in self.NATIONAL_NETWORKS):
                    primary_network = 'NBA TV'
                    break
        
        return {
            'isPrimetime': is_primetime,
            'hasNationalTV': len(traditional_networks) > 0 or len(streaming_platforms) > 0,
            'primaryNetwork': primary_network,
            'traditionalNetworks': traditional_networks,
            'streamingPlatforms': streaming_platforms,
        }
    
    def _analyze_game_context(self, game: dict, game_date: str) -> dict:
        """
        Determine game type and importance context.
        
        Returns dict with:
        - isRegularSeason: bool
        - isPlayoffs: bool
        - isAllStar: bool
        - isEmiratesCup: bool
        - playoffRound: str or None
        - isChristmas: bool
        - isMLKDay: bool
        """
        game_label = (game.get("gameLabel", "") or "").lower()
        week_name = (game.get("weekName", "") or "").lower()
        game_sublabel = (game.get("gameSubLabel", "") or "").lower()
        
        # Game type flags
        is_regular_season = week_name.startswith("week")
        is_allstar = "all-star" in game_label or "rising stars" in game_label
        is_playoffs = any(term in game_label for term in [
            "first round", "conf", "finals", "play-in"
        ]) and not is_allstar
        is_emiratescup = "emirates" in game_label or "cup" in game_label
        
        # Special game flags
        is_christmas = "christmas" in game_sublabel or "12/25" in game_date
        is_mlk_day = "mlk" in game_sublabel or "01/15" in game_date  # MLK Day games
        
        # Playoff round detection
        playoff_round = None
        if is_playoffs:
            if "first round" in game_label:
                playoff_round = "first_round"
            elif "conf" in game_label and "semi" in game_label:
                playoff_round = "conf_semifinals"
            elif "conf" in game_label and "finals" in game_label:
                playoff_round = "conf_finals"
            elif "nba finals" in game_label:
                playoff_round = "nba_finals"
            elif "play-in" in game_label:
                playoff_round = "play_in"
        
        return {
            'isRegularSeason': is_regular_season,
            'isPlayoffs': is_playoffs,
            'isAllStar': is_allstar,
            'isEmiratesCup': is_emiratescup,
            'playoffRound': playoff_round,
            'isChristmas': is_christmas,
            'isMLKDay': is_mlk_day,
        }
    
    def _analyze_scheduling(self, game: dict, game_date: str) -> dict:
        """
        Extract scheduling and timing information.
        
        Returns dict with:
        - dayOfWeek: str (mon, tue, wed, etc.)
        - isWeekend: bool
        - timeSlot: str (afternoon, early_evening, primetime)
        """
        day_of_week = game.get("day", "").lower()
        game_time_est = game.get("gameTimeEst", "")
        
        # Weekend detection
        is_weekend = day_of_week in ["fri", "sat", "sun"]
        
        # Time slot detection (rough estimates based on common NBA scheduling)
        time_slot = "unknown"
        if game_time_est:
            try:
                # Extract hour from time string (format varies)
                hour = 12  # Default noon if can't parse
                if "T" in game_time_est:
                    time_part = game_time_est.split("T")[1]
                    hour = int(time_part.split(":")[0])
                
                if hour < 15:  # Before 3 PM ET
                    time_slot = "afternoon"
                elif hour < 20:  # 3-8 PM ET
                    time_slot = "early_evening"
                else:  # 8 PM ET and later
                    time_slot = "primetime"
            except (ValueError, IndexError, AttributeError):
                # ValueError: int conversion fails; IndexError: split fails; AttributeError: None.split()
                time_slot = "unknown"
        
        return {
            'dayOfWeek': day_of_week,
            'isWeekend': is_weekend,
            'timeSlot': time_slot,
        }
    
    def generate_metadata(self, all_games: List[dict]) -> dict:
        """
        Generate comprehensive season metadata for monitoring and analysis.
        
        Args:
            all_games: List of enhanced game dictionaries
            
        Returns:
            Metadata dictionary with season statistics and backfill tracking
        """
        
        # Initialize counters with completion status tracking
        regular_season = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        playoffs = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        allstar = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        preseason = {"total": 0, "completed": 0, "live": 0, "scheduled": 0}
        
        filtered_stats = {
            "allstar_games": 0,
            "invalid_team_codes": 0,
            "invalid_team_examples": []
        }
        
        backfill_games = 0
        
        for game in all_games:
            game_status = game.get("gameStatus", 1)  # 1=scheduled, 2=live, 3=final
            
            # Categorize by game type based on enhanced flags
            if game.get('isAllStar'):
                allstar["total"] += 1
                if game_status == 3:
                    allstar["completed"] += 1
                elif game_status == 2:
                    allstar["live"] += 1
                else:
                    allstar["scheduled"] += 1
                filtered_stats["allstar_games"] += 1
                    
            elif game.get('isPlayoffs'):
                playoffs["total"] += 1
                if game_status == 3:
                    playoffs["completed"] += 1
                    if self._should_include_in_backfill(game):
                        backfill_games += 1
                elif game_status == 2:
                    playoffs["live"] += 1
                else:
                    playoffs["scheduled"] += 1
                        
            elif game.get('isRegularSeason'):
                regular_season["total"] += 1
                if game_status == 3:
                    regular_season["completed"] += 1
                    if self._should_include_in_backfill(game):
                        backfill_games += 1
                elif game_status == 2:
                    regular_season["live"] += 1
                else:
                    regular_season["scheduled"] += 1
                        
            else:
                # Preseason or other games
                preseason["total"] += 1
                if game_status == 3:
                    preseason["completed"] += 1
                elif game_status == 2:
                    preseason["live"] += 1
                else:
                    preseason["scheduled"] += 1
            
            # Check for invalid team codes
            away_team = game.get("awayTeam", {}).get("teamTricode", "")
            home_team = game.get("homeTeam", {}).get("teamTricode", "")
            
            if (len(away_team) != 3 or len(home_team) != 3 or 
                not away_team.isalpha() or not home_team.isalpha()):
                filtered_stats["invalid_team_codes"] += 1
                if len(filtered_stats["invalid_team_examples"]) < 3:
                    filtered_stats["invalid_team_examples"].append({
                        "game_code": game.get("gameCode", "unknown"),
                        "away_team": away_team,
                        "home_team": home_team
                    })
        
        total_games = (regular_season["total"] + playoffs["total"] + 
                      allstar["total"] + preseason["total"])
        
        total_completed = (regular_season["completed"] + playoffs["completed"] + 
                          allstar["completed"] + preseason["completed"])
        
        total_remaining = (regular_season["scheduled"] + playoffs["scheduled"] + 
                          allstar["scheduled"] + preseason["scheduled"])
        
        # Calculate season progress
        season_completion_pct = (total_completed / total_games * 100) if total_games > 0 else 0
        
        # Estimate remaining backfill games (scheduled regular season + playoffs)
        estimated_remaining_backfill = regular_season["scheduled"] + playoffs["scheduled"]
        
        return {
            "season": self.season,
            "total_games": total_games,
            "regular_season": regular_season,
            "playoffs": playoffs,
            "allstar": allstar,
            "preseason": preseason,
            "season_progress": {
                "completion_percentage": round(season_completion_pct, 1),
                "total_completed": total_completed,
                "total_remaining": total_remaining,
                "estimated_final_backfill": backfill_games + estimated_remaining_backfill
            },
            "backfill": {
                "total_games": backfill_games,
                "estimated_remaining": estimated_remaining_backfill,
                "description": "Regular season + playoffs, completed games only, excluding All-Star and invalid teams"
            },
            "filtered": filtered_stats
        }
    
    def _should_include_in_backfill(self, game: dict) -> bool:
        """
        Determine if a game should be included in backfill count for monitoring.
        
        Excludes:
        - All-Star games
        - Games with invalid team codes
        - Incomplete games
        - Preseason games
        """
        
        # Exclude All-Star games
        if game.get('isAllStar'):
            return False
        
        # Exclude games with invalid team codes
        away_team = game.get("awayTeam", {}).get("teamTricode", "")
        home_team = game.get("homeTeam", {}).get("teamTricode", "")
        
        if (len(away_team) != 3 or len(home_team) != 3 or 
            not away_team.isalpha() or not home_team.isalpha()):
            return False
        
        # Only include completed games (status 3 = final)
        if game.get("gameStatus", 1) != 3:
            return False
        
        # Include regular season and playoff games
        if game.get('isRegularSeason') or game.get('isPlayoffs'):
            return True
        
        # Exclude preseason and other games
        return False