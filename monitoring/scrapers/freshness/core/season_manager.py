#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/core/season_manager.py

Manages NBA season awareness for monitoring thresholds.
Determines current season phase and provides season-adjusted parameters.
"""

import logging
from datetime import datetime, date
from typing import Dict, Optional
import yaml

logger = logging.getLogger(__name__)


class SeasonManager:
    """
    Manages NBA season calendar and phase detection.
    
    Uses nba_schedule_config.yaml to determine:
    - Current season phase (offseason, preseason, regular_season, playoffs)
    - Monitoring thresholds for current phase
    - Special dates and breaks
    """
    
    def __init__(self, config_path: str):
        """
        Initialize season manager.
        
        Args:
            config_path: Path to nba_schedule_config.yaml
        """
        self.config_path = config_path
        self.config = self._load_config()
        logger.info(f"SeasonManager initialized with config: {config_path}")
    
    def _load_config(self) -> Dict:
        """Load season configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info("Season configuration loaded successfully")
            return config
        except Exception as e:
            logger.error(f"Failed to load season config: {e}")
            # Return minimal default config
            return {
                'current_season': {'year': 2024, 'label': '2024-25'},
                'seasons': {},
                'monitoring_profiles': {}
            }
    
    def get_current_season_phase(self, check_date: Optional[date] = None) -> str:
        """
        Determine current NBA season phase.
        
        Args:
            check_date: Date to check (defaults to today)
        
        Returns:
            Season phase: 'offseason', 'preseason', 'regular_season', 
                         'play_in', or 'playoffs'
        """
        if check_date is None:
            check_date = datetime.utcnow().date()
        
        # Get current season config
        current_season_label = self.config.get('current_season', {}).get('label', '2024-25')
        season_config = self.config.get('seasons', {}).get(current_season_label, {})
        
        if not season_config:
            logger.warning(f"No config for season {current_season_label}, defaulting to regular_season")
            return 'regular_season'
        
        # Check each phase
        for phase_name in ['playoffs', 'play_in_tournament', 'regular_season', 'preseason', 'offseason']:
            phase_config = season_config.get(phase_name)
            if not phase_config:
                continue
            
            start_date = self._parse_date(phase_config.get('start_date'))
            end_date = self._parse_date(phase_config.get('end_date'))
            
            if start_date and end_date:
                if start_date <= check_date <= end_date:
                    # Normalize phase name (remove _tournament suffix)
                    if phase_name == 'play_in_tournament':
                        return 'play_in'
                    return phase_name
        
        # Default fallback
        logger.warning(f"Could not determine phase for {check_date}, defaulting to regular_season")
        return 'regular_season'
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse date string to date object."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.error(f"Failed to parse date '{date_str}': {e}")
            return None
    
    def get_monitoring_profile(self, season_phase: str) -> Dict:
        """
        Get monitoring profile for a season phase.
        
        Args:
            season_phase: Season phase name
        
        Returns:
            Monitoring profile configuration
        """
        profile = self.config.get('monitoring_profiles', {}).get(season_phase, {})
        
        if not profile:
            logger.warning(f"No monitoring profile for {season_phase}, using defaults")
            profile = {
                'description': f'Default profile for {season_phase}',
                'scraper_activity': 'full',
                'alert_threshold_multiplier': 1.0,
                'expected_data_frequency': 'daily'
            }
        
        return profile
    
    def adjust_threshold_for_season(
        self,
        base_threshold_hours: float,
        season_phase: str
    ) -> float:
        """
        Adjust monitoring threshold based on season phase.
        
        Args:
            base_threshold_hours: Base threshold in hours
            season_phase: Current season phase
        
        Returns:
            Adjusted threshold in hours
        """
        profile = self.get_monitoring_profile(season_phase)
        multiplier = profile.get('alert_threshold_multiplier', 1.0)
        
        adjusted = base_threshold_hours * multiplier
        logger.debug(f"Threshold adjusted: {base_threshold_hours}h -> {adjusted}h "
                    f"(phase: {season_phase}, multiplier: {multiplier})")
        
        return adjusted
    
    def is_special_date(self, check_date: Optional[date] = None) -> Dict:
        """
        Check if date is a special date (holiday, break, etc.).
        
        Args:
            check_date: Date to check (defaults to today)
        
        Returns:
            Dict with special date info, or empty dict if not special
        """
        if check_date is None:
            check_date = datetime.utcnow().date()
        
        date_str = check_date.strftime('%Y-%m-%d')
        
        # Check breaks
        for break_info in self.config.get('special_dates', {}).get('breaks', []):
            if break_info.get('date') == date_str:
                return {
                    'type': 'break',
                    'name': break_info.get('name'),
                    'note': break_info.get('note'),
                    'date': date_str
                }
        
        # Check important dates
        for important_info in self.config.get('special_dates', {}).get('important_dates', []):
            if important_info.get('date') == date_str:
                return {
                    'type': 'important',
                    'name': important_info.get('name'),
                    'note': important_info.get('note'),
                    'date': date_str
                }
        
        return {}
    
    def get_current_season_label(self) -> str:
        """Get current season label (e.g., '2024-25')."""
        return self.config.get('current_season', {}).get('label', 'Unknown')
    
    def get_season_info(self, season_phase: str) -> Dict:
        """
        Get detailed information about a season phase.
        
        Args:
            season_phase: Season phase name
        
        Returns:
            Dict with season phase details
        """
        current_season_label = self.get_current_season_label()
        season_config = self.config.get('seasons', {}).get(current_season_label, {})
        phase_config = season_config.get(season_phase, {})
        
        if not phase_config:
            return {
                'phase': season_phase,
                'description': f'Unknown phase: {season_phase}',
                'start_date': None,
                'end_date': None
            }
        
        return {
            'phase': season_phase,
            'description': phase_config.get('description', ''),
            'start_date': phase_config.get('start_date'),
            'end_date': phase_config.get('end_date'),
            'characteristics': phase_config.get('characteristics', [])
        }
    
    def is_in_maintenance_window(
        self,
        check_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if current time is in a maintenance window.
        
        Args:
            check_time: Time to check (defaults to now)
        
        Returns:
            True if in maintenance window, False otherwise
        """
        if check_time is None:
            check_time = datetime.utcnow()
        
        maintenance = self.config.get('maintenance_windows', {})
        
        # Check daily maintenance
        daily_windows = maintenance.get('daily', [])
        for window in daily_windows:
            if self._is_time_in_window(check_time, window):
                logger.info(f"In daily maintenance window: {window.get('reason')}")
                return True
        
        # Check weekly maintenance
        weekly_windows = maintenance.get('weekly', [])
        for window in weekly_windows:
            if self._is_time_in_window(check_time, window):
                logger.info(f"In weekly maintenance window: {window.get('reason')}")
                return True
        
        return False
    
    def _is_time_in_window(self, check_time: datetime, window: Dict) -> bool:
        """Check if time falls within maintenance window."""
        try:
            # Check day of week if specified
            if 'day' in window:
                expected_day = window['day']
                actual_day = check_time.strftime('%A')
                if expected_day != actual_day:
                    return False
            
            # Check time range
            start_time_str = window.get('start_time', '00:00')
            end_time_str = window.get('end_time', '23:59')
            
            start_hour, start_min = map(int, start_time_str.split(':'))
            end_hour, end_min = map(int, end_time_str.split(':'))
            
            check_hour = check_time.hour
            check_min = check_time.minute
            
            current_minutes = check_hour * 60 + check_min
            start_minutes = start_hour * 60 + start_min
            end_minutes = end_hour * 60 + end_min
            
            return start_minutes <= current_minutes <= end_minutes
        
        except Exception as e:
            logger.error(f"Error checking maintenance window: {e}")
            return False
    
    def get_summary(self, check_date: Optional[date] = None) -> Dict:
        """
        Get summary of current season state.
        
        Args:
            check_date: Date to check (defaults to today)
        
        Returns:
            Dict with season summary
        """
        if check_date is None:
            check_date = datetime.utcnow().date()
        
        phase = self.get_current_season_phase(check_date)
        profile = self.get_monitoring_profile(phase)
        special = self.is_special_date(check_date)
        season_info = self.get_season_info(phase)
        
        return {
            'season_label': self.get_current_season_label(),
            'current_phase': phase,
            'phase_description': season_info.get('description'),
            'check_date': check_date.isoformat(),
            'monitoring_profile': profile,
            'special_date': special if special else None,
            'in_maintenance_window': self.is_in_maintenance_window()
        }
