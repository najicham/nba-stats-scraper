# predictions/mlb/prediction_systems/ensemble_v1.py
"""
MLB Ensemble V1 Predictor

Weighted ensemble combining V1 baseline and V1.6 rolling systems.
Uses weighted averaging with confidence boost when systems agree.

Weights:
- V1 Baseline: 30%
- V1.6 Rolling: 50%
- Total: 80% (allows for future systems to be added)

Agreement Bonus:
- When systems predict within 1.0 strikeouts: +10% confidence
- When systems disagree significantly (>2.0 K): -15% confidence

System ID: 'ensemble_v1'
"""

import logging
from typing import Dict, List, Optional
import numpy as np

from predictions.mlb.base_predictor import BaseMLBPredictor

logger = logging.getLogger(__name__)


class MLBEnsembleV1(BaseMLBPredictor):
    """
    Ensemble predictor combining V1 baseline and V1.6 rolling

    Generates predictions by:
    1. Running both V1 and V1.6 predictions
    2. Weighted averaging of predictions
    3. Confidence adjustment based on system agreement
    4. Using base class red flags and recommendation logic
    """

    def __init__(
        self,
        v1_predictor: BaseMLBPredictor,
        v1_6_predictor: BaseMLBPredictor,
        v1_weight: float = 0.3,
        v1_6_weight: float = 0.5,
        project_id: str = None
    ):
        """
        Initialize ensemble predictor

        Args:
            v1_predictor: V1 baseline predictor instance
            v1_6_predictor: V1.6 rolling predictor instance
            v1_weight: Weight for V1 predictions (default: 0.3)
            v1_6_weight: Weight for V1.6 predictions (default: 0.5)
            project_id: GCP project ID
        """
        super().__init__(system_id='ensemble_v1', project_id=project_id)

        self.v1_predictor = v1_predictor
        self.v1_6_predictor = v1_6_predictor
        self.v1_weight = v1_weight
        self.v1_6_weight = v1_6_weight

        # Validate weights
        total_weight = v1_weight + v1_6_weight
        if total_weight > 1.0:
            logger.warning(f"Total weight {total_weight} > 1.0, will normalize")
            self.v1_weight = v1_weight / total_weight
            self.v1_6_weight = v1_6_weight / total_weight

        logger.info(f"Ensemble initialized: V1={self.v1_weight:.1%}, V1.6={self.v1_6_weight:.1%}")

    def predict(
        self,
        pitcher_lookup: str,
        features: Dict,
        strikeouts_line: Optional[float] = None
    ) -> Dict:
        """
        Generate ensemble prediction by combining V1 and V1.6 predictions

        Args:
            pitcher_lookup: Pitcher identifier
            features: Feature dict from pitcher_game_summary
            strikeouts_line: Betting line (optional, for recommendation)

        Returns:
            dict: Ensemble prediction with metadata
        """
        # Get predictions from both systems
        try:
            v1_pred = self.v1_predictor.predict(pitcher_lookup, features, strikeouts_line)
            v1_6_pred = self.v1_6_predictor.predict(pitcher_lookup, features, strikeouts_line)
        except Exception as e:
            logger.error(f"[{self.system_id}] Failed to get component predictions: {e}")
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'error': f'Component prediction failed: {str(e)}'
            }

        # Check if either system returned an error or skip
        if v1_pred.get('recommendation') == 'ERROR' and v1_6_pred.get('recommendation') == 'ERROR':
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'error': 'Both systems failed'
            }

        # If one system skipped (red flag), use the other system's recommendation
        if v1_pred.get('recommendation') == 'SKIP' and v1_6_pred.get('recommendation') != 'SKIP':
            # Use V1.6 prediction but mark as ensemble with reduced confidence
            prediction = v1_6_pred.copy()
            prediction['system_id'] = self.system_id
            prediction['confidence'] = prediction.get('confidence', 0) * 0.8  # Reduce confidence
            prediction['ensemble_note'] = 'V1 skipped, using V1.6 only'
            return prediction

        if v1_6_pred.get('recommendation') == 'SKIP' and v1_pred.get('recommendation') != 'SKIP':
            # Use V1 prediction but mark as ensemble with reduced confidence
            prediction = v1_pred.copy()
            prediction['system_id'] = self.system_id
            prediction['confidence'] = prediction.get('confidence', 0) * 0.8  # Reduce confidence
            prediction['ensemble_note'] = 'V1.6 skipped, using V1 only'
            return prediction

        # If both skipped, return skip
        if v1_pred.get('recommendation') == 'SKIP' and v1_6_pred.get('recommendation') == 'SKIP':
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'SKIP',
                'system_id': self.system_id,
                'skip_reason': 'Both systems skipped',
                'red_flags': v1_pred.get('red_flags', []) + v1_6_pred.get('red_flags', [])
            }

        # Both systems produced predictions - calculate ensemble
        v1_strikeouts = v1_pred.get('predicted_strikeouts')
        v1_6_strikeouts = v1_6_pred.get('predicted_strikeouts')

        if v1_strikeouts is None or v1_6_strikeouts is None:
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'error': 'One or more systems returned null prediction'
            }

        # Weighted average
        ensemble_strikeouts = (
            v1_strikeouts * self.v1_weight +
            v1_6_strikeouts * self.v1_6_weight
        )

        # Calculate base confidence (average of component confidences)
        v1_conf = v1_pred.get('confidence', 0)
        v1_6_conf = v1_6_pred.get('confidence', 0)
        base_confidence = (v1_conf + v1_6_conf) / 2.0

        # Agreement adjustment
        agreement_diff = abs(v1_strikeouts - v1_6_strikeouts)
        confidence_multiplier = 1.0

        if agreement_diff < 1.0:
            # Strong agreement - boost confidence
            confidence_multiplier = 1.1
            agreement_note = f"Strong agreement (diff={agreement_diff:.2f})"
        elif agreement_diff < 2.0:
            # Moderate agreement - neutral
            confidence_multiplier = 1.0
            agreement_note = f"Moderate agreement (diff={agreement_diff:.2f})"
        else:
            # Disagreement - reduce confidence
            confidence_multiplier = 0.85
            agreement_note = f"Systems disagree (diff={agreement_diff:.2f})"

        ensemble_confidence = base_confidence * confidence_multiplier

        # Generate recommendation using base class logic
        recommendation = self._generate_recommendation(
            ensemble_strikeouts,
            strikeouts_line,
            ensemble_confidence
        )

        # Check red flags (use ensemble prediction and features)
        red_flag_result = self._check_red_flags(features, recommendation)

        # If hard skip, return SKIP recommendation
        if red_flag_result.skip_bet:
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': round(ensemble_strikeouts, 2),
                'confidence': 0.0,
                'recommendation': 'SKIP',
                'edge': None,
                'strikeouts_line': strikeouts_line,
                'system_id': self.system_id,
                'red_flags': red_flag_result.flags,
                'skip_reason': red_flag_result.skip_reason,
                'component_predictions': {
                    'v1_baseline': round(v1_strikeouts, 2),
                    'v1_6_rolling': round(v1_6_strikeouts, 2)
                }
            }

        # Apply red flag confidence multiplier
        final_confidence = ensemble_confidence * red_flag_result.confidence_multiplier

        # Re-generate recommendation with adjusted confidence
        final_recommendation = self._generate_recommendation(
            ensemble_strikeouts,
            strikeouts_line,
            final_confidence
        )

        # Calculate edge if line provided
        edge = None
        if strikeouts_line is not None:
            edge = ensemble_strikeouts - strikeouts_line

        return {
            'pitcher_lookup': pitcher_lookup,
            'predicted_strikeouts': round(ensemble_strikeouts, 2),
            'confidence': round(final_confidence, 2),
            'base_confidence': round(ensemble_confidence, 2),
            'recommendation': final_recommendation,
            'edge': round(edge, 2) if edge is not None else None,
            'strikeouts_line': strikeouts_line,
            'system_id': self.system_id,
            'model_version': f'ensemble_v1 (V1:{self.v1_weight:.0%}, V1.6:{self.v1_6_weight:.0%})',
            'red_flags': red_flag_result.flags if red_flag_result.flags else None,
            'confidence_multiplier': round(red_flag_result.confidence_multiplier, 2) if red_flag_result.confidence_multiplier < 1.0 else None,
            'agreement_note': agreement_note,
            'component_predictions': {
                'v1_baseline': round(v1_strikeouts, 2),
                'v1_6_rolling': round(v1_6_strikeouts, 2)
            },
            'component_confidences': {
                'v1_baseline': round(v1_conf, 2),
                'v1_6_rolling': round(v1_6_conf, 2)
            }
        }
