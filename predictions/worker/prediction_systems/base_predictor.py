# predictions/worker/prediction_systems/base_predictor.py

"""
Base Predictor Abstract Class

All prediction systems inherit from this base class, which provides:
1. Common interface (predict method)
2. Shared confidence calculation logic
3. Shared recommendation logic (OVER/UNDER/PASS)
4. Consistent return format

Design Principles:
- Abstract methods must be implemented by subclasses
- Shared methods use proven formulas (from algorithm specs)
- All systems return: (predicted_points, confidence, recommendation)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional
from datetime import date
import logging

logger = logging.getLogger(__name__)


class BasePredictor(ABC):
    """Abstract base class for all NBA player points prediction systems"""
    
    def __init__(self, system_id: str, system_name: str, version: str = "1.0"):
        """
        Initialize base predictor
        
        Args:
            system_id: Unique identifier (e.g., 'moving_average', 'zone_matchup')
            system_name: Display name (e.g., 'Moving Average Baseline')
            version: System version for tracking
        """
        self.system_id = system_id
        self.system_name = system_name
        self.version = version
        
        logger.info(f"Initialized {system_name} (v{version})")
    
    @abstractmethod
    def predict(
        self, 
        features: Dict[str, float], 
        player_lookup: str, 
        game_date: date,
        prop_line: Optional[float] = None
    ) -> Tuple[float, float, str]:
        """
        Make a prediction for player points
        
        Args:
            features: Dictionary of 25 features (from mock or Phase 4)
            player_lookup: Player identifier (e.g., 'lebron-james')
            game_date: Date of the game
            prop_line: Optional betting line for recommendation logic
        
        Returns:
            Tuple of (predicted_points, confidence_score, recommendation)
            - predicted_points: Float (0-60+ range)
            - confidence_score: Float (0.0-1.0, typically 0.2-0.8)
            - recommendation: 'OVER' | 'UNDER' | 'PASS'
        
        Raises:
            ValueError: If features are invalid or missing required fields
        """
        pass
    
    def calculate_confidence(
        self, 
        volatility: float, 
        recent_games: int,
        data_quality: float = 1.0
    ) -> float:
        """
        Calculate prediction confidence score
        
        Formula (from algorithm specs):
        - Base confidence: 0.5
        - Volatility penalty: -0.15 (high), -0.08 (medium), 0 (low)
        - Recent games bonus: +0.10 (3+), +0.05 (2), -0.10 (<2)
        - Data quality adjustment: multiply by data_quality (0.0-1.0)
        - Final range: clamped to [0.2, 0.8]
        
        Args:
            volatility: Standard deviation of recent points (0-10+ range)
            recent_games: Number of games played in last 7 days
            data_quality: Data completeness multiplier (0.0-1.0)
        
        Returns:
            Float confidence score (0.2-0.8)
        """
        # Start with base confidence
        confidence = 0.5
        
        # Volatility penalty (high volatility = less confident)
        if volatility > 6.0:
            confidence -= 0.15  # Very inconsistent
        elif volatility > 4.0:
            confidence -= 0.08  # Moderately inconsistent
        # else: no penalty (consistent player)
        
        # Recent games bonus/penalty (more data = more confident)
        if recent_games >= 3:
            confidence += 0.10  # Good recent data
        elif recent_games >= 2:
            confidence += 0.05  # Adequate recent data
        else:
            confidence -= 0.10  # Limited recent data
        
        # Adjust for data quality (e.g., mock data = 0.8)
        confidence *= data_quality
        
        # Clamp to reasonable range [0.2, 0.8]
        confidence = max(0.2, min(0.8, confidence))
        
        return confidence
    
    def determine_recommendation(
        self, 
        predicted_points: float, 
        prop_line: float, 
        confidence: float,
        edge_threshold: float = 2.0,
        confidence_threshold: float = 0.45
    ) -> str:
        """
        Determine betting recommendation (OVER/UNDER/PASS)
        
        Logic:
        1. Calculate edge: |predicted - line|
        2. If edge < threshold: PASS (not enough edge)
        3. If confidence < threshold: PASS (not confident enough)
        4. Otherwise: OVER if predicted > line, UNDER if predicted < line
        
        Args:
            predicted_points: Our prediction
            prop_line: Betting line (e.g., 25.5)
            confidence: Our confidence score (0.0-1.0)
            edge_threshold: Minimum points edge required (default 2.0)
            confidence_threshold: Minimum confidence required (default 0.45)
        
        Returns:
            'OVER' | 'UNDER' | 'PASS'
        """
        # Calculate edge (absolute difference)
        edge = abs(predicted_points - prop_line)
        
        # Check if we have enough edge (must exceed threshold)
        if edge <= edge_threshold:
            return 'PASS'  # Not enough edge to bet
        
        # Check if we're confident enough (must exceed threshold)
        if confidence <= confidence_threshold:
            return 'PASS'  # Not confident enough to bet
        
        # We have edge and confidence - make recommendation
        if predicted_points > prop_line:
            return 'OVER'
        else:
            return 'UNDER'
    
    def validate_features(self, features: Dict[str, float]) -> bool:
        """
        Validate feature dictionary has required fields
        
        Args:
            features: Feature dictionary to validate
        
        Returns:
            True if valid, False otherwise
        
        Note:
            Subclasses can override to add system-specific validation
        """
        required_fields = [
            'feature_count',      # Should be 25
            'feature_version',    # Should be 'v1_baseline_25'
            'data_source',        # 'mock' or 'phase4'
            'features_array'      # Array of 25 floats
        ]
        
        # Check all required fields present
        for field in required_fields:
            if field not in features:
                logger.error(f"Missing required field: {field}")
                return False
        
        # Validate feature count (accepts 25 or 33 features)
        if features['feature_count'] not in (25, 33):
            logger.error(f"Invalid feature count: {features['feature_count']}, expected 25 or 33")
            return False

        # Validate array length (accepts 25 or 33 features)
        if len(features['features_array']) not in (25, 33):
            logger.error(f"Invalid array length: {len(features['features_array'])}, expected 25 or 33")
            return False
        
        return True
    
    def extract_feature(self, features: Dict[str, float], feature_name: str) -> float:
        """
        Extract a named feature from features dictionary
        
        Args:
            features: Feature dictionary with 'features_array' and named fields
            feature_name: Name of feature to extract (e.g., 'points_avg_last_5')
        
        Returns:
            Feature value as float
        
        Raises:
            KeyError: If feature not found
        """
        if feature_name not in features:
            raise KeyError(f"Feature '{feature_name}' not found in features dict")
        
        return features[feature_name]
    
    def __str__(self) -> str:
        """String representation"""
        return f"{self.system_name} (v{self.version})"
    
    def __repr__(self) -> str:
        """Developer representation"""
        return f"BasePredictor(system_id='{self.system_id}', system_name='{self.system_name}', version='{self.version}')"
