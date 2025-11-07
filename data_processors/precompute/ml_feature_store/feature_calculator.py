# File: data_processors/precompute/ml_feature_store/feature_calculator.py
"""
Feature Calculator - Calculate Derived Features

Calculates 6 features that don't exist in any table:
- Feature 9: rest_advantage
- Feature 10: injury_risk
- Feature 11: recent_trend
- Feature 12: minutes_change
- Feature 21: pct_free_throw
- Feature 24: team_win_pct
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class FeatureCalculator:
    """Calculate derived features from Phase 3/4 data."""
    
    def __init__(self):
        """Initialize feature calculator."""
        pass
    
    # ========================================================================
    # FEATURE 9: REST ADVANTAGE
    # ========================================================================
    
    def calculate_rest_advantage(self, phase3_data: Dict) -> float:
        """
        Calculate rest advantage: player rest minus opponent rest.
        
        Positive = player more rested (advantage)
        Negative = opponent more rested (disadvantage)
        
        Args:
            phase3_data: Dict containing player and opponent rest days
            
        Returns:
            float: Rest advantage clamped to [-2.0, 2.0]
        """
        player_rest = phase3_data.get('days_rest')
        opponent_rest = phase3_data.get('opponent_days_rest')
        
        # Handle missing data
        if player_rest is None or opponent_rest is None:
            logger.debug("Missing rest data, returning 0.0")
            return 0.0
        
        # Calculate differential
        rest_diff = int(player_rest) - int(opponent_rest)
        
        # Clamp to [-2, 2]
        rest_advantage = max(-2.0, min(2.0, float(rest_diff)))
        
        logger.debug(f"Rest advantage: player={player_rest}, opp={opponent_rest}, advantage={rest_advantage}")
        
        return rest_advantage
    
    # ========================================================================
    # FEATURE 10: INJURY RISK
    # ========================================================================
    
    def calculate_injury_risk(self, phase3_data: Dict) -> float:
        """
        Calculate injury risk from player status.
        
        Maps injury report status to numeric risk score:
        - available: 0.0 (no risk)
        - probable: 1.0 (low risk)
        - questionable: 2.0 (moderate risk)
        - doubtful: 3.0 (high risk)
        - out: 3.0 (confirmed out)
        
        Args:
            phase3_data: Dict containing player_status
            
        Returns:
            float: Injury risk score [0.0, 3.0]
        """
        player_status = phase3_data.get('player_status', '').lower()
        
        # Status to risk mapping
        status_map = {
            'available': 0.0,
            'probable': 1.0,
            'questionable': 2.0,
            'doubtful': 3.0,
            'out': 3.0,
            '': 0.0  # No status = assume available
        }
        
        risk_score = status_map.get(player_status, 0.0)
        
        logger.debug(f"Injury risk: status='{player_status}', risk={risk_score}")
        
        return risk_score
    
    # ========================================================================
    # FEATURE 11: RECENT TREND
    # ========================================================================
    
    def calculate_recent_trend(self, phase3_data: Dict) -> float:
        """
        Calculate performance trend by comparing recent games.
        
        Compares first 3 games vs last 2 games in 5-game window:
        - Positive trend: Player improving (last 2 > first 3)
        - Negative trend: Player declining (last 2 < first 3)
        - Stable: No significant change
        
        Args:
            phase3_data: Dict containing list of last 5 games with points
            
        Returns:
            float: Trend score [-2.0, 2.0]
        """
        last_10_games = phase3_data.get('last_10_games', [])
        
        # Need at least 5 games for trend
        if len(last_10_games) < 5:
            logger.debug(f"Insufficient games for trend: {len(last_10_games)}/5")
            return 0.0
        
        # Take first 5 games (most recent)
        last_5_games = last_10_games[:5]
        
        # Split into windows
        first_3_points = [g['points'] for g in last_5_games[0:3]]
        last_2_points = [g['points'] for g in last_5_games[3:5]]
        
        # Calculate averages
        avg_first_3 = sum(first_3_points) / 3.0
        avg_last_2 = sum(last_2_points) / 2.0
        
        # Calculate difference
        diff = avg_last_2 - avg_first_3
        
        # Map to trend score
        if diff >= 5.0:
            trend = 2.0  # Strong upward
        elif diff >= 2.0:
            trend = 1.0  # Slight upward
        elif diff <= -5.0:
            trend = -2.0  # Strong downward
        elif diff <= -2.0:
            trend = -1.0  # Slight downward
        else:
            trend = 0.0  # Stable
        
        logger.debug(f"Trend: first_3={avg_first_3:.1f}, last_2={avg_last_2:.1f}, diff={diff:.1f}, trend={trend}")
        
        return trend
    
    # ========================================================================
    # FEATURE 12: MINUTES CHANGE
    # ========================================================================
    
    def calculate_minutes_change(self, phase4_data: Dict, phase3_data: Dict) -> float:
        """
        Calculate minutes change: recent vs season average.
        
        Positive change = player getting more minutes (opportunity increase)
        Negative change = player getting fewer minutes (opportunity decrease)
        
        Args:
            phase4_data: Dict with minutes_avg_last_10
            phase3_data: Dict with season_avg_minutes
            
        Returns:
            float: Minutes change score [-2.0, 2.0]
        """
        # Get recent minutes (Phase 4 preferred)
        minutes_recent = phase4_data.get('minutes_avg_last_10')
        if minutes_recent is None:
            # Fallback: calculate from Phase 3
            last_10_games = phase3_data.get('last_10_games', [])
            if last_10_games:
                minutes_recent = sum(g.get('minutes_played', 0) for g in last_10_games) / len(last_10_games)
            else:
                minutes_recent = 0.0
        
        # Get season average (Phase 3)
        minutes_season = phase3_data.get('minutes_avg_season', 0.0)
        
        # Handle edge cases
        if minutes_season == 0 or minutes_recent == 0:
            logger.debug("Missing minutes data, returning 0.0")
            return 0.0
        
        # Calculate percentage change
        pct_change = (float(minutes_recent) - float(minutes_season)) / float(minutes_season)
        
        # Map to change score
        if pct_change >= 0.20:
            change = 2.0  # +20% or more
        elif pct_change >= 0.10:
            change = 1.0  # +10% to +20%
        elif pct_change <= -0.20:
            change = -2.0  # -20% or more
        elif pct_change <= -0.10:
            change = -1.0  # -10% to -20%
        else:
            change = 0.0  # No significant change
        
        logger.debug(f"Minutes change: recent={minutes_recent:.1f}, season={minutes_season:.1f}, "
                    f"pct_change={pct_change:.2%}, score={change}")
        
        return change
    
    # ========================================================================
    # FEATURE 21: PCT FREE THROW
    # ========================================================================
    
    def calculate_pct_free_throw(self, phase3_data: Dict) -> float:
        """
        Calculate percentage of points from free throws.
        
        Based on last 10 games:
        pct_free_throw = (sum of FT makes) / (sum of points)
        
        Args:
            phase3_data: Dict containing last 10 games with ft_makes and points
            
        Returns:
            float: Free throw percentage [0.0, 1.0]
        """
        last_10_games = phase3_data.get('last_10_games', [])
        
        # Need at least 5 games for reasonable calculation
        if len(last_10_games) < 5:
            logger.debug(f"Insufficient games for pct_free_throw: {len(last_10_games)}/5")
            return 0.15  # League average
        
        # Sum free throws and points
        total_ft_makes = sum(g.get('ft_makes', 0) for g in last_10_games)
        total_points = sum(g.get('points', 0) for g in last_10_games)
        
        # Avoid division by zero
        if total_points == 0:
            logger.debug("No points scored in last 10 games, returning default")
            return 0.15
        
        # Calculate percentage
        # Each FT is worth 1 point
        ft_points = float(total_ft_makes)
        pct = ft_points / float(total_points)
        
        # Clamp to reasonable range [0, 0.5]
        # (It's impossible for >50% of points to be from FTs)
        pct = max(0.0, min(0.5, pct))
        
        logger.debug(f"FT percentage: ft_makes={total_ft_makes}, points={total_points}, pct={pct:.3f}")
        
        return pct
    
    # ========================================================================
    # FEATURE 24: TEAM WIN PCT
    # ========================================================================
    
    def calculate_team_win_pct(self, phase3_data: Dict) -> float:
        """
        Calculate team's win percentage for the season.
        
        Based on all games played this season before game_date:
        win_pct = wins / total_games
        
        Args:
            phase3_data: Dict containing season games with win_flag
            
        Returns:
            float: Win percentage [0.0, 1.0]
        """
        season_games = phase3_data.get('team_season_games', [])
        
        # Need at least 5 games for meaningful percentage
        if len(season_games) < 5:
            logger.debug(f"Insufficient games for win_pct: {len(season_games)}/5")
            return 0.500  # Default to 50%
        
        # Count wins
        wins = sum(1 for g in season_games if g.get('win_flag', False))
        total_games = len(season_games)
        
        # Calculate percentage
        win_pct = float(wins) / float(total_games)
        
        logger.debug(f"Team win pct: wins={wins}, total={total_games}, pct={win_pct:.3f}")
        
        return win_pct
