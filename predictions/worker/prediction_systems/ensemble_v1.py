# predictions/worker/prediction_systems/ensemble_v1.py

"""
Ensemble V1 Prediction System

System ID: ensemble_v1
System Name: Ensemble V1
Version: 1.0

Algorithm:
1. Run both Moving Average and Zone Matchup systems
2. Weight each prediction by its confidence score
3. Calculate weighted average prediction
4. Use maximum confidence for final confidence
5. Determine recommendation based on ensemble prediction

Weighting Logic:
- Confidence-weighted average: (MA_pred * MA_conf + ZM_pred * ZM_conf) / (MA_conf + ZM_conf)
- Confidence: max(MA_conf, ZM_conf) * agreement_bonus
- Agreement bonus: +0.05 if both systems agree on direction

Benefits:
- Combines complementary strengths of both systems
- More robust than single system
- Higher confidence when systems agree
- Balanced view of recent form + matchup advantage

System Agreement Analysis:
- Strong Agreement: Both predict within 2 points
- Moderate Agreement: Both predict within 4 points
- Disagreement: Predictions differ by >4 points
"""

from typing import Dict, Tuple, Optional
from datetime import date
import logging

logger = logging.getLogger(__name__)


class EnsembleV1:
    """Ensemble V1 prediction system combining Moving Average and Zone Matchup"""
    
    def __init__(self, moving_average_system, zone_matchup_system):
        """
        Initialize Ensemble V1 system
        
        Args:
            moving_average_system: Instance of MovingAverageBaseline
            zone_matchup_system: Instance of ZoneMatchupV1
        """
        self.system_id = 'ensemble_v1'
        self.system_name = 'Ensemble V1'
        self.version = '1.0'
        
        # Component systems
        self.moving_average = moving_average_system
        self.zone_matchup = zone_matchup_system
        
        # Ensemble parameters
        self.agreement_bonus = 0.05  # Confidence bonus when systems agree
        self.strong_agreement_threshold = 2.0  # Within 2 points
        self.moderate_agreement_threshold = 4.0  # Within 4 points
        
        logger.info(f"Initialized {self.system_name} (v{self.version})")
    
    def predict(
        self,
        features: Dict[str, float],
        player_lookup: str,
        game_date: date,
        prop_line: Optional[float] = None
    ) -> Tuple[float, float, str, Dict[str, any]]:
        """
        Make ensemble prediction by combining both systems
        
        Args:
            features: Dictionary with 25 features
            player_lookup: Player identifier
            game_date: Game date
            prop_line: Optional betting line for recommendation
        
        Returns:
            Tuple of (predicted_points, confidence, recommendation, metadata)
            - predicted_points: Ensemble prediction (weighted average)
            - confidence: Ensemble confidence (max with agreement bonus)
            - recommendation: 'OVER' | 'UNDER' | 'PASS'
            - metadata: Dict with component predictions and agreement info
        """
        # Get predictions from both systems
        ma_pred, ma_conf, ma_rec = self.moving_average.predict(
            features, player_lookup, game_date, prop_line
        )
        
        zm_pred, zm_conf, zm_rec = self.zone_matchup.predict(
            features, player_lookup, game_date, prop_line
        )
        
        # Calculate weighted average prediction
        total_weight = ma_conf + zm_conf
        ensemble_pred = (ma_pred * ma_conf + zm_pred * zm_conf) / total_weight
        
        # Ensure prediction is reasonable
        ensemble_pred = max(0.0, min(60.0, ensemble_pred))
        
        # Calculate ensemble confidence
        ensemble_conf = self._calculate_ensemble_confidence(
            ma_pred, ma_conf, zm_pred, zm_conf
        )
        
        # Determine ensemble recommendation
        if prop_line is not None:
            ensemble_rec = self._determine_ensemble_recommendation(
                ensemble_pred, prop_line, ensemble_conf, ma_rec, zm_rec
            )
        else:
            ensemble_rec = 'PASS'
        
        # Calculate agreement metrics
        agreement_type = self._calculate_agreement_type(ma_pred, zm_pred)
        prediction_diff = abs(ma_pred - zm_pred)
        
        # Build metadata
        metadata = {
            'moving_average': {
                'prediction': ma_pred,
                'confidence': ma_conf,
                'recommendation': ma_rec
            },
            'zone_matchup': {
                'prediction': zm_pred,
                'confidence': zm_conf,
                'recommendation': zm_rec
            },
            'agreement_type': agreement_type,
            'prediction_difference': prediction_diff,
            'systems_agree': agreement_type in ['strong', 'moderate'],
            'recommendation_agreement': ma_rec == zm_rec
        }
        
        logger.debug(
            f"{player_lookup} ensemble: {ensemble_pred:.1f} "
            f"(MA={ma_pred:.1f}, ZM={zm_pred:.1f}, diff={prediction_diff:.1f}, "
            f"agreement={agreement_type}, conf={ensemble_conf:.2f})"
        )
        
        return (ensemble_pred, ensemble_conf, ensemble_rec, metadata)
    
    def _calculate_ensemble_confidence(
        self,
        ma_pred: float,
        ma_conf: float,
        zm_pred: float,
        zm_conf: float
    ) -> float:
        """
        Calculate ensemble confidence based on component confidences and agreement
        
        Logic:
        1. Start with max confidence from either system
        2. Add agreement bonus if predictions are close
        3. Clamp to [0.2, 0.8] range
        
        Args:
            ma_pred: Moving Average prediction
            ma_conf: Moving Average confidence
            zm_pred: Zone Matchup prediction
            zm_conf: Zone Matchup confidence
        
        Returns:
            Float confidence (0.2-0.8)
        """
        # Start with maximum confidence
        base_confidence = max(ma_conf, zm_conf)
        
        # Calculate agreement
        prediction_diff = abs(ma_pred - zm_pred)
        
        # Add bonus if systems agree
        if prediction_diff <= self.strong_agreement_threshold:
            # Strong agreement: both within 2 points
            confidence = base_confidence + self.agreement_bonus
        elif prediction_diff <= self.moderate_agreement_threshold:
            # Moderate agreement: both within 4 points
            confidence = base_confidence + (self.agreement_bonus * 0.5)
        else:
            # Disagreement: no bonus
            confidence = base_confidence
        
        # Clamp to valid range
        return max(0.2, min(0.8, confidence))
    
    def _determine_ensemble_recommendation(
        self,
        ensemble_pred: float,
        prop_line: float,
        ensemble_conf: float,
        ma_rec: str,
        zm_rec: str,
        edge_threshold: float = 2.0,
        confidence_threshold: float = 0.45
    ) -> str:
        """
        Determine ensemble recommendation
        
        Logic:
        1. Check if ensemble prediction has sufficient edge and confidence
        2. If both systems agree on recommendation, boost confidence in that
        3. If systems disagree, require higher edge/confidence
        
        Args:
            ensemble_pred: Ensemble prediction
            prop_line: Betting line
            ensemble_conf: Ensemble confidence
            ma_rec: Moving Average recommendation
            zm_rec: Zone Matchup recommendation
            edge_threshold: Minimum edge required
            confidence_threshold: Minimum confidence required
        
        Returns:
            'OVER' | 'UNDER' | 'PASS'
        """
        # Calculate edge
        edge = abs(ensemble_pred - prop_line)
        
        # Check if we have enough edge
        if edge <= edge_threshold:
            return 'PASS'
        
        # Check if we're confident enough
        if ensemble_conf <= confidence_threshold:
            return 'PASS'
        
        # If both systems agree on recommendation, use it
        if ma_rec == zm_rec and ma_rec != 'PASS':
            return ma_rec
        
        # Systems disagree or one PASSed - use ensemble prediction
        if ensemble_pred > prop_line:
            return 'OVER'
        else:
            return 'UNDER'
    
    def _calculate_agreement_type(self, ma_pred: float, zm_pred: float) -> str:
        """
        Calculate agreement type between systems
        
        Args:
            ma_pred: Moving Average prediction
            zm_pred: Zone Matchup prediction
        
        Returns:
            'strong' | 'moderate' | 'disagreement'
        """
        diff = abs(ma_pred - zm_pred)
        
        if diff <= self.strong_agreement_threshold:
            return 'strong'
        elif diff <= self.moderate_agreement_threshold:
            return 'moderate'
        else:
            return 'disagreement'
    
    def get_system_weights(
        self,
        ma_conf: float,
        zm_conf: float
    ) -> Tuple[float, float]:
        """
        Get normalized weights for each system
        
        Args:
            ma_conf: Moving Average confidence
            zm_conf: Zone Matchup confidence
        
        Returns:
            Tuple of (ma_weight, zm_weight) that sum to 1.0
        """
        total = ma_conf + zm_conf
        return (ma_conf / total, zm_conf / total)
    
    def analyze_disagreement(
        self,
        features: Dict[str, float],
        player_lookup: str,
        game_date: date
    ) -> Dict[str, any]:
        """
        Analyze why systems might disagree
        
        Useful for understanding prediction differences
        
        Args:
            features: Feature dictionary
            player_lookup: Player identifier
            game_date: Game date
        
        Returns:
            Dict with analysis of key factors
        """
        # Get predictions
        ma_pred, ma_conf, _ = self.moving_average.predict(
            features, player_lookup, game_date
        )
        zm_pred, zm_conf, _ = self.zone_matchup.predict(
            features, player_lookup, game_date
        )
        
        # Extract key factors
        points_last_5 = features.get('points_avg_last_5', 0)
        points_season = features.get('points_avg_season', 0)
        opponent_def = features.get('opponent_def_rating', 110)
        
        recent_vs_season = points_last_5 - points_season
        defense_vs_avg = opponent_def - 110.0
        
        analysis = {
            'moving_average_prediction': ma_pred,
            'zone_matchup_prediction': zm_pred,
            'difference': abs(ma_pred - zm_pred),
            'recent_form_vs_season': recent_vs_season,
            'recent_form_impact': 'Hot streak' if recent_vs_season > 2 else 'Cold streak' if recent_vs_season < -2 else 'Neutral',
            'defense_vs_average': defense_vs_avg,
            'defense_impact': 'Weak defense' if defense_vs_avg > 5 else 'Elite defense' if defense_vs_avg < -5 else 'Average defense',
            'likely_reason': self._identify_disagreement_reason(recent_vs_season, defense_vs_avg, ma_pred, zm_pred)
        }
        
        return analysis
    
    def _identify_disagreement_reason(
        self,
        recent_vs_season: float,
        defense_vs_avg: float,
        ma_pred: float,
        zm_pred: float
    ) -> str:
        """Identify likely reason for prediction disagreement"""
        if ma_pred > zm_pred and recent_vs_season > 2:
            return "Moving Average captures hot streak not reflected in matchup"
        elif zm_pred > ma_pred and defense_vs_avg > 5:
            return "Zone Matchup identifies favorable matchup despite recent form"
        elif ma_pred < zm_pred and recent_vs_season < -2:
            return "Moving Average penalizes cold streak, Zone Matchup focuses on matchup"
        elif zm_pred < ma_pred and defense_vs_avg < -5:
            return "Zone Matchup identifies tough matchup despite recent form"
        else:
            return "Mixed factors - no single dominant reason"
    
    def __str__(self) -> str:
        return f"{self.system_name} (v{self.version})"
    
    def __repr__(self) -> str:
        return f"EnsembleV1(version='{self.version}')"
