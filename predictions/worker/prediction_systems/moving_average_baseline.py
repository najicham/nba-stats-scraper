# predictions/worker/prediction_systems/moving_average_baseline.py

"""
Moving Average Baseline Prediction System

System ID: moving_average
System Name: Moving Average Baseline
Version: 1.0

Algorithm:
1. Base prediction = weighted average of recent performance
   - Last 5 games: 50% weight (most important)
   - Last 10 games: 30% weight
   - Season average: 20% weight

2. Apply adjustments:
   - Fatigue: -2.5 (high), -1.0 (medium), 0.0 (low)
   - Matchup: shot_zone_mismatch * 0.3
   - Rest: -1.5 (back-to-back) or rest_advantage * 0.5
   - Pace: pace_score * 0.3
   - Venue: +0.5 (home) or -0.5 (away)
   - Usage: usage_spike_score * 0.4

3. Calculate confidence based on volatility and recent games
4. Determine recommendation (OVER/UNDER/PASS)

Features Used (indices):
- 0: points_avg_last_5
- 1: points_avg_last_10
- 2: points_avg_season
- 3: points_std_last_10 (volatility)
- 4: games_played_last_7_days
- 5: fatigue_score
- 6: shot_zone_mismatch_score
- 7: pace_score
- 8: usage_spike_score
- 15: home_away (1=home, 0=away)
- 16: back_to_back (1=yes, 0=no)
"""

from typing import Dict, Tuple, Optional
from datetime import date
import logging

logger = logging.getLogger(__name__)


class MovingAverageBaseline:
    """Moving Average Baseline prediction system"""
    
    def __init__(self):
        """Initialize Moving Average Baseline system"""
        self.system_id = 'moving_average'
        self.system_name = 'Moving Average Baseline'
        self.version = '1.0'
        
        # Weights for base prediction
        self.weight_last_5 = 0.50
        self.weight_last_10 = 0.30
        self.weight_season = 0.20
        
        # Adjustment multipliers
        self.matchup_multiplier = 0.3
        self.pace_multiplier = 0.3
        self.usage_multiplier = 0.4
        
        # Fixed adjustments
        self.home_advantage = 0.5
        self.away_penalty = -0.5
        self.back_to_back_penalty = -1.5
        
        logger.info(f"Initialized {self.system_name} (v{self.version})")
    
    def predict(
        self,
        features: Dict[str, float],
        player_lookup: str,
        game_date: date,
        prop_line: Optional[float] = None
    ) -> Tuple[float, float, str]:
        """
        Make a prediction using moving average approach
        
        Args:
            features: Dictionary with 25 features
            player_lookup: Player identifier
            game_date: Game date
            prop_line: Optional betting line for recommendation
        
        Returns:
            (predicted_points, confidence, recommendation)
        """
        # Validate features
        if not self.validate_features(features):
            raise ValueError(f"Invalid features for player {player_lookup}")
        
        # Extract required features
        points_last_5 = self.extract_feature(features, 'points_avg_last_5')
        points_last_10 = self.extract_feature(features, 'points_avg_last_10')
        points_season = self.extract_feature(features, 'points_avg_season')
        volatility = self.extract_feature(features, 'points_std_last_10')
        recent_games = int(self.extract_feature(features, 'games_played_last_7_days'))
        
        # Calculate base prediction (weighted average)
        base_prediction = (
            points_last_5 * self.weight_last_5 +
            points_last_10 * self.weight_last_10 +
            points_season * self.weight_season
        )
        
        # Calculate all adjustments
        fatigue_adj = self._calculate_fatigue_adjustment(features)
        matchup_adj = self._calculate_matchup_adjustment(features)
        rest_adj = self._calculate_rest_adjustment(features)
        pace_adj = self._calculate_pace_adjustment(features)
        venue_adj = self._calculate_venue_adjustment(features)
        usage_adj = self._calculate_usage_adjustment(features)
        
        # Combine all adjustments
        total_adjustment = (
            fatigue_adj +
            matchup_adj +
            rest_adj +
            pace_adj +
            venue_adj +
            usage_adj
        )
        
        # Final prediction
        predicted_points = base_prediction + total_adjustment
        
        # Ensure prediction is reasonable (NBA players rarely score < 0 or > 60)
        predicted_points = max(0.0, min(60.0, predicted_points))
        
        # Calculate confidence
        data_quality = 0.8 if features.get('data_source', 'unknown') == 'mock' else 1.0
        confidence = self.calculate_confidence(volatility, recent_games, data_quality)
        
        # Determine recommendation
        if prop_line is not None:
            recommendation = self.determine_recommendation(
                predicted_points, prop_line, confidence
            )
        else:
            recommendation = 'PASS'  # No line provided
        
        logger.debug(
            f"{player_lookup} prediction: {predicted_points:.1f} "
            f"(base={base_prediction:.1f}, adj={total_adjustment:.1f}, "
            f"confidence={confidence:.2f})"
        )
        
        return (predicted_points, confidence, recommendation)
    
    def _calculate_fatigue_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate fatigue adjustment
        
        Logic:
        - High fatigue (>70): -2.5 points
        - Medium fatigue (50-70): -1.0 points
        - Low fatigue (<50): 0.0 points
        """
        fatigue_score = self.extract_feature(features, 'fatigue_score')
        
        if fatigue_score > 70:
            return -2.5
        elif fatigue_score > 50:
            return -1.0
        else:
            return 0.0
    
    def _calculate_matchup_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate matchup adjustment based on shot zone mismatch
        
        Positive score = favorable matchup (weak opponent defense in player's zones)
        Negative score = unfavorable matchup (strong opponent defense)
        """
        shot_zone_mismatch = self.extract_feature(features, 'shot_zone_mismatch_score')
        return shot_zone_mismatch * self.matchup_multiplier
    
    def _calculate_rest_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate rest adjustment
        
        Logic:
        - Back-to-back game: -1.5 points (fixed penalty)
        - Normal rest: rest_advantage * 0.5
        """
        back_to_back = self.extract_feature(features, 'back_to_back')
        
        if back_to_back == 1:
            return self.back_to_back_penalty
        else:
            # rest_advantage is in features but not in our 25 feature spec
            # For now, assume 0.0 (can enhance later)
            return 0.0
    
    def _calculate_pace_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate pace adjustment
        
        Positive pace_score = faster game (more possessions)
        Negative pace_score = slower game (fewer possessions)
        """
        pace_score = self.extract_feature(features, 'pace_score')
        return pace_score * self.pace_multiplier
    
    def _calculate_venue_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate venue adjustment (home court advantage)
        
        Logic:
        - Home game: +0.5 points
        - Away game: -0.5 points
        """
        home_away = self.extract_feature(features, 'home_away')
        
        if home_away == 1:  # Home game
            return self.home_advantage
        else:  # Away game
            return self.away_penalty
    
    def _calculate_usage_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate usage adjustment
        
        Positive usage_spike = player taking more shots than usual
        Negative usage_spike = player taking fewer shots
        """
        usage_spike = self.extract_feature(features, 'usage_spike_score')
        return usage_spike * self.usage_multiplier
    
    def calculate_confidence(
        self,
        volatility: float,
        recent_games: int,
        data_quality: float = 1.0
    ) -> float:
        """
        Calculate prediction confidence score
        
        Formula:
        - Base confidence: 0.5
        - Volatility penalty: -0.15 (high), -0.08 (medium), 0 (low)
        - Recent games bonus: +0.10 (3+), +0.05 (2), -0.10 (<2)
        - Data quality adjustment: multiply by data_quality
        - Final range: clamped to [0.2, 0.8]
        """
        confidence = 0.5
        
        # Volatility penalty
        if volatility > 6.0:
            confidence -= 0.15
        elif volatility > 4.0:
            confidence -= 0.08
        
        # Recent games bonus/penalty
        if recent_games >= 3:
            confidence += 0.10
        elif recent_games >= 2:
            confidence += 0.05
        else:
            confidence -= 0.10
        
        # Adjust for data quality
        confidence *= data_quality
        
        # Clamp to range
        return max(0.2, min(0.8, confidence))
    
    def determine_recommendation(
        self,
        predicted_points: float,
        prop_line: float,
        confidence: float,
        edge_threshold: float = 2.0,
        confidence_threshold: float = 0.45
    ) -> str:
        """
        Determine betting recommendation
        
        Logic:
        - Must have >2.0 point edge
        - Must have >0.45 confidence
        - Otherwise: PASS
        """
        edge = abs(predicted_points - prop_line)
        
        if edge <= edge_threshold:
            return 'PASS'
        
        if confidence <= confidence_threshold:
            return 'PASS'
        
        if predicted_points > prop_line:
            return 'OVER'
        else:
            return 'UNDER'
    
    def validate_features(self, features: Dict[str, float]) -> bool:
        """Validate feature dictionary"""
        # Metadata fields are optional - use defaults if not present
        feature_count = features.get('feature_count', 25)
        feature_version = features.get('feature_version', 'v1_baseline_25')
        data_source = features.get('data_source', 'unknown')
        features_array = features.get('features_array', [])
        
        # Validate feature count if provided (accepts 25 or 33 features)
        if feature_count not in (25, 33):
            logger.error(f"Invalid feature count: {feature_count}")
            return False

        # Only validate array length if array exists and is non-empty
        if features_array and len(features_array) not in (25, 33):
            logger.error(f"Invalid array length: {len(features_array)}")
            return False
        
        return True
    
    def extract_feature(self, features: Dict[str, float], feature_name: str) -> float:
        """Extract named feature from features dict with alias support"""
        # Define field aliases for compatibility
        aliases = {
            'home_away': 'is_home',  # home_away (1=home) can be is_home (1=home, 0=away)
            'games_played_last_7_days': None,  # Optional field, default to 3 if missing
        }
        
        # Try primary field name first
        if feature_name in features:
            return features[feature_name]
        
        # Try alias if available
        if feature_name in aliases:
            alias = aliases[feature_name]
            if alias is None:
                # Optional field with default
                if feature_name == 'games_played_last_7_days':
                    return 3  # Default to 3 games
            elif alias in features:
                return features[alias]
        
        raise KeyError(f"Feature '{feature_name}' not found")
    
    def __str__(self) -> str:
        return f"{self.system_name} (v{self.version})"
    
    def __repr__(self) -> str:
        return f"MovingAverageBaseline(version='{self.version}')"