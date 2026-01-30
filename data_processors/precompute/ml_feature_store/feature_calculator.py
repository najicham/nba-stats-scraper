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

IMPORTANT: All ratio calculations must be rounded to 9 decimal places
for BigQuery NUMERIC type compatibility. Python float division can
produce 17+ decimal places which causes batch insert failures.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# Default values for missing data (league averages)
DEFAULT_FT_PERCENTAGE = 0.15  # ~15% of points from FT is league average
DEFAULT_WIN_PERCENTAGE = 0.500  # 50% win rate for unknown teams

# BigQuery NUMERIC type precision limit
NUMERIC_PRECISION = 9


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
        player_status = (phase3_data.get('player_status') or '').lower()
        
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

        # Split into windows (handle None values)
        first_3_points = [g.get('points') or 0 for g in last_5_games[0:3]]
        last_2_points = [g.get('points') or 0 for g in last_5_games[3:5]]

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
                minutes_recent = sum(g.get('minutes_played') or 0 for g in last_10_games) / len(last_10_games)
            else:
                minutes_recent = 0.0

        # Get season average (Phase 3)
        minutes_season = phase3_data.get('minutes_avg_season') or 0.0
        
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
            return DEFAULT_FT_PERCENTAGE
        
        # Sum free throws and points (handle None values)
        total_ft_makes = sum(g.get('ft_makes') or 0 for g in last_10_games)
        total_points = sum(g.get('points') or 0 for g in last_10_games)
        
        # Avoid division by zero
        if total_points == 0:
            logger.debug("No points scored in last 10 games, returning default")
            return DEFAULT_FT_PERCENTAGE

        # Calculate percentage
        # Each FT is worth 1 point
        ft_points = float(total_ft_makes)
        pct = ft_points / float(total_points)

        # Clamp to reasonable range [0, 0.5]
        # (It's impossible for >50% of points to be from FTs)
        pct = max(0.0, min(0.5, pct))

        # Round to 9 decimal places for BigQuery NUMERIC compatibility
        pct = round(pct, NUMERIC_PRECISION)

        logger.debug(f"FT percentage: ft_makes={total_ft_makes}, points={total_points}, pct={pct:.9f}")

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
            return DEFAULT_WIN_PERCENTAGE

        # Count wins (handle None values)
        wins = sum(1 for g in season_games if g.get('win_flag'))
        total_games = len(season_games)

        # Calculate percentage
        win_pct = float(wins) / float(total_games)

        # Round to 9 decimal places for BigQuery NUMERIC compatibility
        # This prevents repeating decimals like 0.6666666666666666 from 2/3 wins
        win_pct = round(win_pct, NUMERIC_PRECISION)

        logger.debug(f"Team win pct: wins={wins}, total={total_games}, pct={win_pct:.9f}")

        return win_pct

    # ========================================================================
    # FEATURE 33: DNP RATE
    # ========================================================================

    def calculate_dnp_rate(self, phase3_data: Dict) -> float:
        """
        Calculate DNP (Did Not Play) rate from recent games (v2.1).

        Uses gamebook-based DNP tracking from player_game_summary to identify
        players with patterns of coach decisions, injuries, or other DNPs that
        may not appear in pre-game injury reports.

        Based on analysis:
        - 35%+ of DNPs are not in pre-game injury report
        - Coach decisions, late scratches, G League assignments
        - Higher DNP rate = higher risk of not playing

        Args:
            phase3_data: Dict containing last_10_games with is_dnp field

        Returns:
            float: DNP rate [0.0, 1.0], default 0.0 if no data
        """
        last_10_games = phase3_data.get('last_10_games', [])

        # Need at least 3 games for meaningful calculation
        if len(last_10_games) < 3:
            logger.debug(f"Insufficient games for dnp_rate: {len(last_10_games)}/3")
            return 0.0

        # Count DNPs (handle None and False values)
        dnp_count = sum(1 for g in last_10_games if g.get('is_dnp') is True)
        total_games = len(last_10_games)

        # Calculate rate
        dnp_rate = float(dnp_count) / float(total_games)

        # Round to 9 decimal places for BigQuery NUMERIC compatibility
        dnp_rate = round(dnp_rate, NUMERIC_PRECISION)

        logger.debug(f"DNP rate: dnp_count={dnp_count}, total={total_games}, rate={dnp_rate:.9f}")

        return dnp_rate

    # ========================================================================
    # FEATURE 34: PTS SLOPE 10G (Player Trajectory - Session 28)
    # ========================================================================

    def calculate_pts_slope_10g(self, phase3_data: Dict) -> float:
        """
        Calculate linear regression slope of points over last 10 games.

        Positive slope = player trending upward (scoring more each game)
        Negative slope = player trending downward (scoring less each game)

        Uses least squares regression on game index vs points:
        slope = sum((x - x_mean)(y - y_mean)) / sum((x - x_mean)^2)

        Args:
            phase3_data: Dict containing last_10_games with points

        Returns:
            float: Points slope (expected points change per game), default 0.0
        """
        last_10_games = phase3_data.get('last_10_games', [])

        # Need at least 5 games for meaningful trend
        if len(last_10_games) < 5:
            logger.debug(f"Insufficient games for pts_slope: {len(last_10_games)}/5")
            return 0.0

        # Get points from each game (oldest to newest for slope direction)
        # Note: last_10_games[0] is most recent, so reverse for chronological order
        points_list = [(g.get('points') or 0) for g in reversed(last_10_games)]
        n = len(points_list)

        # Calculate linear regression slope using least squares
        # x = game index (0, 1, 2, ..., n-1), y = points
        x_mean = (n - 1) / 2.0
        y_mean = sum(points_list) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(points_list))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        slope = numerator / denominator

        # Round to 9 decimal places for BigQuery NUMERIC compatibility
        slope = round(slope, NUMERIC_PRECISION)

        logger.debug(f"Points slope: n={n}, slope={slope:.9f} pts/game")

        return slope

    # ========================================================================
    # FEATURE 35: PTS VS SEASON ZSCORE (Player Trajectory - Session 28)
    # ========================================================================

    def calculate_pts_vs_season_zscore(self, phase4_data: Dict, phase3_data: Dict) -> float:
        """
        Calculate z-score of recent performance vs season average.

        z-score = (L5_avg - season_avg) / season_std

        Positive z-score = performing above season average
        Negative z-score = performing below season average

        Uses existing features from player_daily_cache:
        - points_avg_last_5 (L5 avg)
        - points_avg_season (season avg)
        - points_std_last_10 (approximates season std)

        Args:
            phase4_data: Dict with Phase 4 data (preferred)
            phase3_data: Dict with Phase 3 data (fallback)

        Returns:
            float: Z-score clamped to [-3.0, 3.0], default 0.0
        """
        # Get L5 average (prefer Phase 4)
        l5_avg = phase4_data.get('points_avg_last_5')
        if l5_avg is None:
            l5_avg = phase3_data.get('points_avg_last_5')

        # Get season average (prefer Phase 4)
        season_avg = phase4_data.get('points_avg_season')
        if season_avg is None:
            season_avg = phase3_data.get('points_avg_season')

        # Get standard deviation (prefer Phase 4)
        std = phase4_data.get('points_std_last_10')
        if std is None:
            std = phase3_data.get('points_std_last_10')

        # Handle missing data
        if l5_avg is None or season_avg is None or std is None or std == 0:
            logger.debug("Missing data for pts_vs_season_zscore, returning 0.0")
            return 0.0

        # Calculate z-score
        z_score = (float(l5_avg) - float(season_avg)) / float(std)

        # Clamp to [-3, 3] (extreme outliers capped)
        z_score = max(-3.0, min(3.0, z_score))

        # Round to 9 decimal places for BigQuery NUMERIC compatibility
        z_score = round(z_score, NUMERIC_PRECISION)

        logger.debug(f"Z-score: L5={l5_avg:.1f}, season={season_avg:.1f}, std={std:.1f}, z={z_score:.9f}")

        return z_score

    # ========================================================================
    # FEATURE 36: BREAKOUT FLAG (Player Trajectory - Session 28)
    # ========================================================================

    def calculate_breakout_flag(self, phase4_data: Dict, phase3_data: Dict) -> float:
        """
        Calculate breakout flag for exceptional recent performance.

        A player is flagged as "breaking out" if their L5 average exceeds
        their season average by more than 1.5 standard deviations.

        breakout_flag = 1.0 if L5_avg > season_avg + 1.5 * std, else 0.0

        This captures:
        - Stars having exceptional stretches
        - Breakout games from role players
        - Usage increases from roster changes

        Args:
            phase4_data: Dict with Phase 4 data (preferred)
            phase3_data: Dict with Phase 3 data (fallback)

        Returns:
            float: 1.0 if breaking out, 0.0 otherwise
        """
        # Get L5 average (prefer Phase 4)
        l5_avg = phase4_data.get('points_avg_last_5')
        if l5_avg is None:
            l5_avg = phase3_data.get('points_avg_last_5')

        # Get season average (prefer Phase 4)
        season_avg = phase4_data.get('points_avg_season')
        if season_avg is None:
            season_avg = phase3_data.get('points_avg_season')

        # Get standard deviation (prefer Phase 4)
        std = phase4_data.get('points_std_last_10')
        if std is None:
            std = phase3_data.get('points_std_last_10')

        # Handle missing data
        if l5_avg is None or season_avg is None or std is None:
            logger.debug("Missing data for breakout_flag, returning 0.0")
            return 0.0

        # Calculate threshold (season_avg + 1.5 * std)
        threshold = float(season_avg) + 1.5 * float(std)

        # Check if breaking out
        is_breakout = float(l5_avg) > threshold

        logger.debug(f"Breakout: L5={l5_avg:.1f}, threshold={threshold:.1f} (season={season_avg:.1f} + 1.5*{std:.1f}), "
                    f"flag={1.0 if is_breakout else 0.0}")

        return 1.0 if is_breakout else 0.0
