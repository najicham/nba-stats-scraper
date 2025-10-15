#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/utils/nba_schedule_api.py

Fetches NBA game schedule from Ball Don't Lie API.
Used to determine if there are games scheduled for a given date.
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import requests

logger = logging.getLogger(__name__)


class NBAScheduleAPI:
    """
    Fetches NBA game schedule from Ball Don't Lie API.
    
    Used to determine if game-dependent scrapers should be checked.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize NBA Schedule API client.
        
        Args:
            api_key: Ball Don't Lie API key (or None to read from env)
        """
        self.api_key = api_key or os.environ.get('BALL_DONT_LIE_API_KEY')
        self.base_url = "https://api.balldontlie.io/v1"
        
        if not self.api_key:
            logger.warning("No Ball Don't Lie API key found. Schedule checks may be limited.")
        
        logger.info("NBAScheduleAPI initialized")
    
    def get_games_for_date(self, check_date: date) -> List[Dict]:
        """
        Get list of NBA games scheduled for a specific date.
        
        Args:
            check_date: Date to check for games
        
        Returns:
            List of game dictionaries from Ball Don't Lie API
        """
        try:
            # Format date for API
            date_str = check_date.strftime('%Y-%m-%d')
            
            # Build request
            url = f"{self.base_url}/games"
            params = {
                'dates[]': date_str
            }
            
            headers = {}
            if self.api_key:
                headers['Authorization'] = self.api_key
            
            # Make request
            logger.debug(f"Fetching games for {date_str} from Ball Don't Lie API")
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            games = data.get('data', [])
            
            logger.info(f"Found {len(games)} games for {date_str}")
            return games
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch games from Ball Don't Lie API: {e}")
            return []
        except Exception as e:
            logger.error(f"Error processing game schedule: {e}")
            return []
    
    def has_games_on_date(self, check_date: date) -> bool:
        """
        Check if there are any NBA games scheduled for a date.
        
        Args:
            check_date: Date to check
        
        Returns:
            True if games are scheduled, False otherwise
        """
        games = self.get_games_for_date(check_date)
        return len(games) > 0
    
    def get_game_count_for_date(self, check_date: date) -> int:
        """
        Get count of games scheduled for a date.
        
        Args:
            check_date: Date to check
        
        Returns:
            Number of games scheduled
        """
        games = self.get_games_for_date(check_date)
        return len(games)
    
    def get_games_for_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, List[Dict]]:
        """
        Get games for a date range.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
        
        Returns:
            Dictionary mapping date strings to list of games
        """
        games_by_date = {}
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            games = self.get_games_for_date(current_date)
            games_by_date[date_str] = games
            
            current_date += timedelta(days=1)
        
        return games_by_date
    
    def get_today_game_info(self) -> Dict:
        """
        Get information about today's games.
        
        Returns:
            Dict with game count and basic info
        """
        today = datetime.utcnow().date()
        games = self.get_games_for_date(today)
        
        return {
            'date': today.isoformat(),
            'game_count': len(games),
            'has_games': len(games) > 0,
            'games': games
        }


# Convenience functions for easy import
def has_games_today(api_key: Optional[str] = None) -> bool:
    """
    Quick check if there are games today.
    
    Args:
        api_key: Ball Don't Lie API key (optional)
    
    Returns:
        True if games are scheduled today
    """
    client = NBAScheduleAPI(api_key=api_key)
    today = datetime.utcnow().date()
    return client.has_games_on_date(today)


def get_today_game_count(api_key: Optional[str] = None) -> int:
    """
    Get count of games scheduled today.
    
    Args:
        api_key: Ball Don't Lie API key (optional)
    
    Returns:
        Number of games today
    """
    client = NBAScheduleAPI(api_key=api_key)
    today = datetime.utcnow().date()
    return client.get_game_count_for_date(today)


# Cache for game schedule (avoid repeated API calls)
_schedule_cache = {}
_cache_expiry = None


def has_games_today_cached(api_key: Optional[str] = None, cache_minutes: int = 60) -> bool:
    """
    Check if there are games today, with caching.
    
    Caches result for specified minutes to avoid repeated API calls.
    
    Args:
        api_key: Ball Don't Lie API key (optional)
        cache_minutes: How long to cache result (default: 60 minutes)
    
    Returns:
        True if games are scheduled today
    """
    global _schedule_cache, _cache_expiry
    
    now = datetime.utcnow()
    today_str = now.date().isoformat()
    
    # Check if cache is valid
    if _cache_expiry and now < _cache_expiry and today_str in _schedule_cache:
        logger.debug(f"Using cached game schedule for {today_str}")
        return _schedule_cache[today_str]
    
    # Cache expired or not present, fetch fresh data
    logger.debug(f"Fetching fresh game schedule for {today_str}")
    has_games = has_games_today(api_key=api_key)
    
    # Update cache
    _schedule_cache = {today_str: has_games}
    _cache_expiry = now + timedelta(minutes=cache_minutes)
    
    return has_games


if __name__ == "__main__":
    # Test the API
    logging.basicConfig(level=logging.INFO)
    
    print("=== NBA Schedule API Test ===\n")
    
    # Test today's games
    print("1. Testing today's games:")
    today_info = get_today_game_count()
    print(f"   Games today: {today_info}")
    print(f"   Has games: {has_games_today()}")
    
    # Test with caching
    print("\n2. Testing cached lookup:")
    print(f"   First call: {has_games_today_cached()}")
    print(f"   Second call (cached): {has_games_today_cached()}")
    
    # Test specific date
    print("\n3. Testing specific date:")
    client = NBAScheduleAPI()
    test_date = date(2024, 12, 25)  # Christmas Day (usually has games)
    games = client.get_games_for_date(test_date)
    print(f"   Games on {test_date}: {len(games)}")
    
    print("\n=== Test Complete ===")
