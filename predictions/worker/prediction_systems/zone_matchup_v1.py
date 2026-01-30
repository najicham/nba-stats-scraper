# predictions/worker/prediction_systems/zone_matchup_v1.py

"""
Zone Matchup V1 Prediction System

System ID: zone_matchup
System Name: Zone Matchup V1
Version: 1.0

Algorithm:
1. Base prediction = season average (starting point)

2. Calculate zone-by-zone matchup scores:
   - Paint zone: player's paint% vs opponent's paint defense
   - Mid-range: player's mid% vs opponent's mid defense
   - Three-point: player's 3pt% vs opponent's perimeter defense
   - Free throw: player's FT rate vs opponent's foul tendency

3. Weight matchup scores by player's usage in each zone:
   - More weight to zones player uses frequently
   - Less weight to zones player rarely uses

4. Apply context adjustments:
   - Pace: Faster game = more opportunities
   - Home/Away: Venue advantage
   - Fatigue: High fatigue reduces effectiveness

5. Calculate confidence based on:
   - Opponent defense data quality
   - Player zone consistency
   - Recent games

Features Used (indices):
- 2: points_avg_season (base prediction)
- 3: points_std_last_10 (volatility for confidence)
- 4: games_played_last_7_days
- 5: fatigue_score
- 7: pace_score
- 13: opponent_def_rating (overall defense)
- 14: opponent_pace
- 15: home_away
- 18-21: pct_paint, pct_mid_range, pct_three, pct_free_throw

Zone Scoring Logic:
- Favorable matchup: +1.0 to +3.0 points per zone
- Neutral matchup: 0.0 points
- Unfavorable matchup: -1.0 to -3.0 points per zone

Weighted by usage:
- High usage zone (>40%): Full weight
- Medium usage zone (20-40%): 0.7x weight
- Low usage zone (<20%): 0.4x weight
"""

from typing import Dict, Tuple, Optional
from datetime import date
import logging

logger = logging.getLogger(__name__)


class ZoneMatchupV1:
    """Zone Matchup V1 prediction system"""
    
    def __init__(self):
        """Initialize Zone Matchup V1 system"""
        self.system_id = 'zone_matchup'
        self.system_name = 'Zone Matchup V1'
        self.version = '1.0'
        
        # Zone weights for usage
        self.high_usage_threshold = 0.40  # >40% = full weight
        self.medium_usage_threshold = 0.20  # 20-40% = 0.7x weight
        self.medium_usage_multiplier = 0.7
        self.low_usage_multiplier = 0.4
        
        # Matchup score multipliers
        self.zone_impact_multiplier = 2.0  # Max points per zone
        
        # Context adjustments
        self.pace_multiplier = 0.4
        self.home_advantage = 0.8
        self.away_penalty = -0.8
        
        # Defense rating thresholds (NBA average ~110)
        self.elite_defense = 105  # Top defense
        self.weak_defense = 115   # Weak defense
        
        logger.info(f"Initialized {self.system_name} (v{self.version})")
    
    def predict(
        self,
        features: Dict[str, float],
        player_lookup: str,
        game_date: date,
        prop_line: Optional[float] = None
    ) -> Tuple[float, float, str]:
        """
        Make a prediction using zone matchup approach
        
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
        
        # Extract base features
        points_season = self.extract_feature(features, 'points_avg_season')
        volatility = self.extract_feature(features, 'points_std_last_10')
        recent_games = int(self.extract_feature(features, 'games_played_last_7_days'))
        
        # Start with season average as base
        base_prediction = points_season
        
        # Calculate zone matchup adjustment
        zone_adjustment = self._calculate_zone_matchup_adjustment(features)
        
        # Calculate context adjustments
        pace_adj = self._calculate_pace_adjustment(features)
        venue_adj = self._calculate_venue_adjustment(features)
        fatigue_adj = self._calculate_fatigue_adjustment(features)
        
        # Combine all adjustments
        total_adjustment = zone_adjustment + pace_adj + venue_adj + fatigue_adj
        
        # Final prediction
        predicted_points = base_prediction + total_adjustment
        
        # Ensure prediction is reasonable
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
            recommendation = 'PASS'
        
        logger.debug(
            f"{player_lookup} zone prediction: {predicted_points:.1f} "
            f"(base={base_prediction:.1f}, zone={zone_adjustment:.1f}, "
            f"context={pace_adj + venue_adj + fatigue_adj:.1f}, "
            f"confidence={confidence:.2f})"
        )
        
        return (predicted_points, confidence, recommendation)
    
    def _calculate_zone_matchup_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate zone-by-zone matchup adjustment
        
        Logic:
        1. For each zone (paint, mid, three, FT):
           - Get player's usage % in that zone
           - Get opponent's defensive strength in that zone
           - Calculate matchup score (player strength vs opponent weakness)
           - Weight by player's usage
        2. Sum weighted matchup scores
        
        Returns:
            Float adjustment (-10.0 to +10.0 range typically)
        """
        # Extract player zone usage
        pct_paint = self.extract_feature(features, 'pct_paint')
        pct_mid_range = self.extract_feature(features, 'pct_mid_range')
        pct_three = self.extract_feature(features, 'pct_three')
        pct_free_throw = self.extract_feature(features, 'pct_free_throw')
        
        # Extract opponent defense rating (overall)
        opponent_def = self.extract_feature(features, 'opponent_def_rating')
        
        # Calculate zone-specific matchup scores
        # In production, we'd have opponent defense by zone
        # For now, use overall defense rating as proxy
        
        # Paint zone matchup
        paint_matchup = self._calculate_zone_score(
            player_usage=pct_paint,
            opponent_defense=opponent_def,
            zone_type='paint'
        )
        
        # Mid-range zone matchup
        mid_matchup = self._calculate_zone_score(
            player_usage=pct_mid_range,
            opponent_defense=opponent_def,
            zone_type='mid_range'
        )
        
        # Three-point zone matchup
        three_matchup = self._calculate_zone_score(
            player_usage=pct_three,
            opponent_defense=opponent_def,
            zone_type='three'
        )
        
        # Free throw zone matchup
        ft_matchup = self._calculate_zone_score(
            player_usage=pct_free_throw,
            opponent_defense=opponent_def,
            zone_type='free_throw'
        )
        
        # Weight each zone by player's usage
        paint_weighted = paint_matchup * self._get_usage_weight(pct_paint)
        mid_weighted = mid_matchup * self._get_usage_weight(pct_mid_range)
        three_weighted = three_matchup * self._get_usage_weight(pct_three)
        ft_weighted = ft_matchup * self._get_usage_weight(pct_free_throw)
        
        # Total zone adjustment
        total_zone_adjustment = (
            paint_weighted + 
            mid_weighted + 
            three_weighted + 
            ft_weighted
        )
        
        return total_zone_adjustment
    
    def _calculate_zone_score(
        self,
        player_usage: float,
        opponent_defense: float,
        zone_type: str
    ) -> float:
        """
        Calculate matchup score for a single zone

        Logic:
        - Elite defense (105): Harder to score (-1.5 to -3.0)
        - Average defense (110): Neutral (0.0)
        - Weak defense (115+): Easier to score (+1.5 to +3.0)

        Adjusted by zone type (paint defense matters more than perimeter)

        Args:
            player_usage: Player's usage % in this zone (0.0-1.0)
            opponent_defense: Opponent's defensive rating (100-120 range)
            zone_type: 'paint', 'mid_range', 'three', 'free_throw'

        Returns:
            Float score (-3.0 to +3.0)
        """
        # Calculate how much opponent defense deviates from average (110)
        # FIXED (Jan 2026): Was 110.0 - opponent_defense (inverted logic)
        defense_diff = opponent_defense - 110.0

        # Convert to matchup score
        # Positive = weak defense (easier to score)
        # Negative = strong defense (harder to score)
        base_score = defense_diff * 0.3  # Scale to reasonable range
        
        # Adjust by zone type (some zones matter more)
        zone_multipliers = {
            'paint': 1.2,      # Paint defense most important
            'mid_range': 1.0,  # Mid-range standard
            'three': 1.1,      # Perimeter defense important
            'free_throw': 0.8  # FT less affected by defense
        }
        
        multiplier = zone_multipliers.get(zone_type, 1.0)
        adjusted_score = base_score * multiplier
        
        # Clamp to reasonable range
        return max(-3.0, min(3.0, adjusted_score))
    
    def _get_usage_weight(self, usage_pct: float) -> float:
        """
        Get weight multiplier based on player's usage in zone
        
        Logic:
        - High usage (>40%): 1.0x (full weight)
        - Medium usage (20-40%): 0.7x
        - Low usage (<20%): 0.4x
        
        Args:
            usage_pct: Player's usage % in zone (0.0-1.0)
        
        Returns:
            Float weight multiplier
        """
        if usage_pct >= self.high_usage_threshold:
            return 1.0
        elif usage_pct >= self.medium_usage_threshold:
            return self.medium_usage_multiplier
        else:
            return self.low_usage_multiplier
    
    def _calculate_pace_adjustment(self, features: Dict[str, float]) -> float:
        """Calculate pace adjustment (faster game = more opportunities)"""
        pace_score = self.extract_feature(features, 'pace_score')
        return pace_score * self.pace_multiplier
    
    def _calculate_venue_adjustment(self, features: Dict[str, float]) -> float:
        """Calculate venue adjustment (home court advantage)"""
        home_away = self.extract_feature(features, 'home_away')
        
        if home_away == 1:  # Home game
            return self.home_advantage
        else:  # Away game
            return self.away_penalty
    
    def _calculate_fatigue_adjustment(self, features: Dict[str, float]) -> float:
        """
        Calculate fatigue adjustment
        
        Logic:
        - High fatigue (>70): -1.5 points
        - Medium fatigue (50-70): -0.8 points
        - Low fatigue (<50): 0.0 points
        """
        fatigue_score = self.extract_feature(features, 'fatigue_score')
        
        if fatigue_score > 70:
            return -1.5
        elif fatigue_score > 50:
            return -0.8
        else:
            return 0.0
    
    def calculate_confidence(
        self,
        volatility: float,
        recent_games: int,
        data_quality: float = 1.0
    ) -> float:
        """
        Calculate prediction confidence score
        
        Similar to base predictor but adjusted for zone analysis
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
        """Determine betting recommendation"""
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
        feature_version = features.get('feature_version', 'v2_33features')
        data_source = features.get('data_source', 'unknown')
        features_array = features.get('features_array', [])
        
        # Validate feature count if provided (accepts 25, 33, or 37 features)
        if feature_count not in (25, 33, 37):
            logger.error(f"Invalid feature count: {feature_count}", exc_info=True)
            return False

        # Only validate array length if array exists and is non-empty
        if features_array and len(features_array) not in (25, 33, 37):
            logger.error(f"Invalid array length: {len(features_array)}", exc_info=True)
            return False
        
        return True
    
    def extract_feature(self, features: Dict[str, float], feature_name: str) -> float:
        """Extract named feature from features dict with alias support"""
        # Define field aliases for compatibility
        aliases = {
            'home_away': 'is_home',  # home_away (1=home) can be is_home (1=home, 0=away)
            'games_played_last_7_days': None,  # Optional field, default to 3 if missing
            'opponent_def_rating': 'opponent_def_rating_last_15',  # Can use _last_15 variant
            'pct_paint': 'paint_rate_last_10',  # Shot zone percentages
            'pct_mid_range': 'mid_range_rate_last_10',
            'pct_three': 'three_pt_rate_last_10',
            'pct_free_throw': None,  # Optional field, default to 12% if missing
        }
        
        # Try primary field name first
        if feature_name in features:
            return features[feature_name]
        
        # Try alias if available
        if feature_name in aliases:
            alias = aliases[feature_name]
            if alias is None:
                # Optional fields with defaults
                if feature_name == 'games_played_last_7_days':
                    return 3  # Default to 3 games
                elif feature_name == 'pct_free_throw':
                    return 12.0  # Default FT% contribution (reasonable NBA average)
            elif alias in features:
                return features[alias]
        
        raise KeyError(f"Feature '{feature_name}' not found")
    
    def __str__(self) -> str:
        return f"{self.system_name} (v{self.version})"
    
    def __repr__(self) -> str:
        return f"ZoneMatchupV1(version='{self.version}')"