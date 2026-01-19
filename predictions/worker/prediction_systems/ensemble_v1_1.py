# predictions/worker/prediction_systems/ensemble_v1_1.py

"""
Ensemble V1.1 Prediction System - Performance-Based Weighted Ensemble

System ID: ensemble_v1_1
System Name: Ensemble V1.1
Version: 1.1 (Performance-based weighted ensemble with CatBoost V8)

Algorithm:
1. Run all 5 base systems (Moving Average, Zone Matchup, Similarity, XGBoost, CatBoost V8)
2. Weight each prediction by FIXED performance-based weights (not confidence)
3. Calculate weighted average prediction
4. Analyze 5-way system agreement
5. Boost confidence when systems agree
6. Generate recommendation based on ensemble prediction and agreement

Weighting Logic (V1.1 - Fixed Performance-Based):
- CatBoost V8: 45% (best system, 4.81 MAE)
- Similarity: 25% (good complementarity, 5.45 MAE)
- Moving Average: 20% (momentum signal, 5.55 MAE)
- Zone Matchup: 10% (reduced weight, 6.50 MAE with extreme bias)
- XGBoost: 0% (skip for now, mock model)

Benefits over V1:
- Includes CatBoost V8 (the actual best system)
- Reduces Zone Matchup weight (was dragging down performance)
- Uses performance-based weights instead of confidence weights
- Expected MAE: 4.9-5.1 (6-9% improvement from 5.41)

System Agreement Analysis:
- High Agreement: All within 2 points (variance < 2.0)
- Good Agreement: All within 3 points (variance < 3.0)
- Moderate Agreement: All within 6 points (variance < 6.0)
- Low Agreement: Variance > 6.0
"""

from typing import Dict, Tuple, Optional, List
from datetime import date
import logging
import numpy as np

logger = logging.getLogger(__name__)


class EnsembleV1_1:
    """Ensemble V1.1 - Performance-based weighted ensemble with CatBoost V8"""

    def __init__(
        self,
        moving_average_system,
        zone_matchup_system,
        similarity_system,
        xgboost_system,
        catboost_system
    ):
        """
        Initialize Ensemble V1.1 system

        Args:
            moving_average_system: Instance of MovingAverageBaseline
            zone_matchup_system: Instance of ZoneMatchupV1
            similarity_system: Instance of SimilarityBalancedV1
            xgboost_system: Instance of XGBoostV1
            catboost_system: Instance of CatBoostV8
        """
        self.system_id = 'ensemble_v1_1'
        self.system_name = 'Ensemble V1.1'
        self.version = '1.1'

        # Component systems
        self.moving_average = moving_average_system
        self.zone_matchup = zone_matchup_system
        self.similarity = similarity_system
        self.xgboost = xgboost_system
        self.catboost = catboost_system

        # NEW: Performance-based fixed weights (based on historical MAE)
        self.system_weights = {
            'catboost': 0.45,       # Best system (4.81 MAE)
            'similarity': 0.25,     # Good complementarity (5.45 MAE)
            'moving_average': 0.20, # Momentum signal (5.55 MAE)
            'zone_matchup': 0.10,   # Reduced weight (6.50 MAE, extreme bias)
            'xgboost': 0.00         # Skip for now (mock model)
        }

        # Ensemble parameters (keep existing)
        self.high_agreement_threshold = 2.0  # Within 2 points
        self.good_agreement_threshold = 3.0  # Within 3 points (tighter threshold)
        self.moderate_agreement_threshold = 6.0  # Within 6 points

        # Confidence adjustments (keep existing)
        self.high_agreement_bonus = 10  # When variance < 2.0
        self.good_agreement_bonus = 5   # When variance < 4.0
        self.all_systems_bonus = 5      # When all 5 systems predict

        # Recommendation thresholds (keep existing)
        self.edge_threshold = 1.5  # Ensemble can be more aggressive
        self.confidence_threshold = 65.0  # Minimum confidence (out of 100)

        logger.info(f"Initialized {self.system_name} (v{self.version}) with 5 systems")
        logger.info(f"System weights: {self.system_weights}")
    
    def predict(
        self,
        features: Dict[str, float],
        player_lookup: str,
        game_date: date,
        prop_line: Optional[float] = None,
        historical_games: Optional[List[Dict]] = None
    ) -> Tuple[float, float, str, Dict[str, any]]:
        """
        Make ensemble prediction by combining all 5 systems

        Args:
            features: Dictionary with 33 features
            player_lookup: Player identifier
            game_date: Game date
            prop_line: Optional betting line for recommendation
            historical_games: Optional historical games for similarity system

        Returns:
            Tuple of (predicted_points, confidence, recommendation, metadata)
            - predicted_points: Ensemble prediction (weighted average)
            - confidence: Ensemble confidence (0-100)
            - recommendation: 'OVER' | 'UNDER' | 'PASS'
            - metadata: Dict with all component predictions and agreement info
        """
        # Collect predictions from all systems
        predictions = []
        
        # System 1: Moving Average
        try:
            ma_pred, ma_conf, ma_rec = self.moving_average.predict(
                features, player_lookup, game_date, prop_line
            )
            predictions.append({
                'system': 'moving_average',
                'prediction': ma_pred,
                'confidence': ma_conf * 100,  # Convert to 0-100
                'recommendation': ma_rec
            })
        except Exception as e:
            logger.warning(f"Moving Average failed: {e}")
            predictions.append(None)
        
        # System 2: Zone Matchup
        try:
            zm_pred, zm_conf, zm_rec = self.zone_matchup.predict(
                features, player_lookup, game_date, prop_line
            )
            predictions.append({
                'system': 'zone_matchup',
                'prediction': zm_pred,
                'confidence': zm_conf * 100,  # Convert to 0-100
                'recommendation': zm_rec
            })
        except Exception as e:
            logger.warning(f"Zone Matchup failed: {e}")
            predictions.append(None)
        
        # System 3: Similarity
        try:
            if historical_games is None:
                # If no historical games provided, skip similarity
                logger.debug("No historical games provided for similarity system")
                predictions.append(None)
            else:
                sim_result = self.similarity.predict(
                    player_lookup=player_lookup,
                    features=features,
                    historical_games=historical_games,
                    betting_line=prop_line
                )
                
                if sim_result['predicted_points'] is not None:
                    predictions.append({
                        'system': 'similarity',
                        'prediction': sim_result['predicted_points'],
                        'confidence': sim_result['confidence_score'],
                        'recommendation': sim_result['recommendation']
                    })
                else:
                    predictions.append(None)
        except Exception as e:
            logger.warning(f"Similarity failed: {e}")
            predictions.append(None)
        
        # System 4: XGBoost
        try:
            xgb_result = self.xgboost.predict(
                player_lookup=player_lookup,
                features=features,
                betting_line=prop_line
            )

            if xgb_result['predicted_points'] is not None:
                predictions.append({
                    'system': 'xgboost',
                    'prediction': xgb_result['predicted_points'],
                    'confidence': xgb_result['confidence_score'],
                    'recommendation': xgb_result['recommendation']
                })
            else:
                predictions.append(None)
        except Exception as e:
            logger.warning(f"XGBoost failed: {e}")
            predictions.append(None)

        # System 5: CatBoost V8 (NEW)
        try:
            cb_result = self.catboost.predict(
                player_lookup=player_lookup,
                features=features,
                betting_line=prop_line
            )

            if cb_result['predicted_points'] is not None:
                predictions.append({
                    'system': 'catboost',
                    'prediction': cb_result['predicted_points'],
                    'confidence': cb_result['confidence_score'],
                    'recommendation': cb_result['recommendation']
                })
            else:
                predictions.append(None)
        except Exception as e:
            logger.warning(f"CatBoost V8 failed: {e}")
            predictions.append(None)

        # Filter out None predictions
        valid_predictions = [p for p in predictions if p is not None]
        
        # Check if we have enough predictions
        if len(valid_predictions) < 2:
            logger.warning(f"Insufficient valid predictions ({len(valid_predictions)}/5)")
            return (0.0, 0.0, 'PASS', {
                'error': 'Insufficient valid predictions',
                'valid_systems': len(valid_predictions),
                'predictions': predictions
            })
        
        # Calculate weighted average prediction
        ensemble_pred = self._calculate_weighted_prediction(valid_predictions)
        
        # Ensure prediction is reasonable
        ensemble_pred = max(0.0, min(60.0, ensemble_pred))
        
        # Calculate ensemble confidence
        ensemble_conf = self._calculate_ensemble_confidence(valid_predictions)
        
        # Determine ensemble recommendation
        if prop_line is not None:
            ensemble_rec = self._determine_ensemble_recommendation(
                ensemble_pred,
                prop_line,
                ensemble_conf,
                valid_predictions
            )
        else:
            ensemble_rec = 'PASS'
        
        # Calculate agreement metrics
        agreement_metrics = self._calculate_agreement_metrics(valid_predictions)
        
        # Build metadata
        metadata = {
            'systems_used': len(valid_predictions),
            'predictions': predictions,
            'agreement': agreement_metrics,
            'weights_used': {  # NEW
                p['system']: self.system_weights.get(p['system'], 0.0)
                for p in valid_predictions
            },
            'ensemble': {
                'prediction': ensemble_pred,
                'confidence': ensemble_conf,
                'recommendation': ensemble_rec
            }
        }
        
        logger.debug(
            f"{player_lookup} ensemble: {ensemble_pred:.1f} "
            f"({len(valid_predictions)} systems, "
            f"agreement={agreement_metrics['type']}, "
            f"variance={agreement_metrics['variance']:.2f}, "
            f"conf={ensemble_conf:.1f})"
        )
        
        return (ensemble_pred, ensemble_conf / 100.0, ensemble_rec, metadata)
    
    def _calculate_weighted_prediction(self, predictions: List[Dict]) -> float:
        """
        Calculate weighted average using FIXED performance-based weights

        V1.1 Change: Uses fixed weights based on historical performance
        instead of confidence-weighted averaging

        Args:
            predictions: List of valid prediction dicts

        Returns:
            Weighted average prediction
        """
        weighted_sum = 0.0
        total_weight = 0.0

        for pred in predictions:
            system_name = pred['system']
            weight = self.system_weights.get(system_name, 0.0)

            if weight > 0:
                weighted_sum += pred['prediction'] * weight
                total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def _calculate_ensemble_confidence(self, predictions: List[Dict]) -> float:
        """
        Calculate ensemble confidence (0-100)

        Logic:
        1. Start with average of component confidences
        2. Add bonus for high agreement (low variance)
        3. Add bonus if all 5 systems predicted
        4. Clamp to [20, 95] range

        Args:
            predictions: List of valid prediction dicts

        Returns:
            Confidence score (0-100)
        """
        # Base confidence: average of components
        avg_confidence = np.mean([p['confidence'] for p in predictions])

        # Calculate prediction variance
        pred_values = [p['prediction'] for p in predictions]
        variance = np.std(pred_values) if len(pred_values) > 1 else 0.0

        # Start with average confidence
        confidence = avg_confidence

        # Agreement bonus/penalty based on variance
        if variance < self.high_agreement_threshold:
            # High agreement: all within 2 points
            confidence += self.high_agreement_bonus
        elif variance < self.good_agreement_threshold:
            # Good agreement: all within 3 points
            confidence += self.good_agreement_bonus
        elif variance < self.moderate_agreement_threshold:
            # Moderate disagreement: apply small penalty
            confidence -= 5.0
        else:
            # Low agreement: apply larger penalty
            confidence -= 10.0

        # Bonus if all 5 systems predicted
        if len(predictions) == 5:
            confidence += self.all_systems_bonus

        # Clamp to reasonable range
        return max(20.0, min(95.0, confidence))
    
    def _determine_ensemble_recommendation(
        self,
        ensemble_pred: float,
        prop_line: float,
        ensemble_conf: float,
        predictions: List[Dict]
    ) -> str:
        """
        Determine ensemble recommendation
        
        Logic:
        1. Check if we have sufficient confidence
        2. Calculate edge (prediction vs line)
        3. Check if edge meets threshold
        4. Consider system agreement on recommendations
        
        Args:
            ensemble_pred: Ensemble prediction
            prop_line: Betting line
            ensemble_conf: Ensemble confidence (0-100)
            predictions: List of valid predictions
        
        Returns:
            'OVER' | 'UNDER' | 'PASS'
        """
        # Check confidence threshold
        if ensemble_conf < self.confidence_threshold:
            return 'PASS'
        
        # Calculate edge
        edge = abs(ensemble_pred - prop_line)
        
        # Check edge threshold
        if edge < self.edge_threshold:
            return 'PASS'
        
        # Count system recommendations
        rec_counts = {'OVER': 0, 'UNDER': 0, 'PASS': 0}
        for pred in predictions:
            rec = pred.get('recommendation', 'PASS')
            rec_counts[rec] += 1
        
        # If majority agrees on direction, use it
        if rec_counts['OVER'] > len(predictions) / 2:
            return 'OVER'
        elif rec_counts['UNDER'] > len(predictions) / 2:
            return 'UNDER'
        
        # Otherwise, use ensemble prediction
        if ensemble_pred > prop_line:
            return 'OVER'
        else:
            return 'UNDER'
    
    def _calculate_agreement_metrics(self, predictions: List[Dict]) -> Dict:
        """
        Calculate agreement metrics across all systems
        
        Args:
            predictions: List of valid predictions
        
        Returns:
            Dict with agreement type, variance, range, etc.
        """
        pred_values = [p['prediction'] for p in predictions]
        
        # Calculate statistics
        mean_pred = np.mean(pred_values)
        variance = np.std(pred_values)
        pred_range = max(pred_values) - min(pred_values)
        
        # Determine agreement type
        if variance < self.high_agreement_threshold:
            agreement_type = 'high'
            agreement_pct = 95.0
        elif variance < self.good_agreement_threshold:
            agreement_type = 'good'
            agreement_pct = 85.0
        elif variance < self.moderate_agreement_threshold:
            agreement_type = 'moderate'
            agreement_pct = 70.0
        else:
            agreement_type = 'low'
            agreement_pct = max(50.0, 100.0 - (variance * 5))
        
        return {
            'type': agreement_type,
            'agreement_percentage': agreement_pct,
            'variance': variance,
            'range': pred_range,
            'mean': mean_pred,
            'min': min(pred_values),
            'max': max(pred_values)
        }
    
    def analyze_predictions(
        self,
        features: Dict[str, float],
        player_lookup: str,
        game_date: date,
        historical_games: Optional[List[Dict]] = None
    ) -> Dict[str, any]:
        """
        Analyze predictions from all systems without making recommendation
        
        Useful for understanding why systems agree or disagree
        
        Args:
            features: Feature dictionary
            player_lookup: Player identifier
            game_date: Game date
            historical_games: Optional historical games for similarity
        
        Returns:
            Dict with detailed analysis
        """
        _, _, _, metadata = self.predict(
            features,
            player_lookup,
            game_date,
            prop_line=None,
            historical_games=historical_games
        )
        
        # Extract key factors
        points_last_5 = features.get('points_avg_last_5', 0)
        points_season = features.get('points_avg_season', 0)
        zone_mismatch = features.get('shot_zone_mismatch_score', 0)
        fatigue = features.get('fatigue_score', 70)
        opponent_def = features.get('opponent_def_rating_last_15', 112)
        
        # Analyze key differences
        analysis = {
            'metadata': metadata,
            'key_factors': {
                'recent_form': 'Hot' if points_last_5 > points_season + 3 else 'Cold' if points_last_5 < points_season - 3 else 'Normal',
                'zone_matchup': 'Favorable' if zone_mismatch > 3 else 'Unfavorable' if zone_mismatch < -3 else 'Neutral',
                'fatigue_level': 'Fresh' if fatigue > 80 else 'Fatigued' if fatigue < 60 else 'Normal',
                'opponent_defense': 'Weak' if opponent_def > 115 else 'Elite' if opponent_def < 108 else 'Average'
            },
            'system_strengths': {
                'moving_average': 'Captures recent momentum and trends',
                'zone_matchup': 'Identifies style matchup advantages',
                'similarity': 'Finds historical patterns in similar contexts',
                'xgboost': 'Learns complex interactions from training data'
            }
        }
        
        return analysis
    
    def get_system_weights(self, predictions: List[Dict]) -> Dict[str, float]:
        """
        Get normalized weights for each system
        
        Args:
            predictions: List of valid predictions
        
        Returns:
            Dict mapping system name to normalized weight
        """
        total_conf = sum(p['confidence'] for p in predictions)
        
        weights = {}
        for pred in predictions:
            weights[pred['system']] = pred['confidence'] / total_conf
        
        return weights
    
    def __str__(self) -> str:
        return f"{self.system_name} (v{self.version}) - 5 Systems"

    def __repr__(self) -> str:
        return f"EnsembleV1_1(version='{self.version}', systems=5)"