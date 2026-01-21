# predictions/worker/prediction_systems/xgboost_v1.py

"""
XGBoost V1 Prediction System

Machine learning prediction system using gradient boosted trees.
Learns optimal feature weights from historical training data.

Algorithm:
1. Prepare feature vector (25 features in exact order)
2. Load trained XGBoost model
3. Run model.predict()
4. Calculate confidence from model uncertainty
5. Generate recommendation

Version: 1.0
"""

from typing import Dict, Optional
import numpy as np


class XGBoostV1:
    """
    XGBoost-based prediction system
    
    Uses machine learning to learn optimal patterns from historical data.
    Can capture non-linear interactions that rule-based systems miss.
    """
    
    def __init__(self, model=None, model_path: Optional[str] = None):
        """
        Initialize XGBoost V1 system
        
        Args:
            model: Pre-loaded model (for testing with mock model)
            model_path: Path to trained model in GCS (for production)
        """
        self.system_id = 'xgboost_v1'
        self.model_version = 'v1'
        
        # Load model
        if model is not None:
            self.model = model
        elif model_path is not None:
            self.model = self._load_model_from_gcs(model_path)
        else:
            # For testing: use mock model
            from predictions.shared.mock_xgboost_model import load_mock_model
            self.model = load_mock_model(seed=42)
    
    def predict(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float] = None
    ) -> Dict:
        """
        Generate prediction using XGBoost model
        
        Args:
            player_lookup: Player identifier
            features: Current game features (25 features)
            betting_line: Current over/under line (optional)
        
        Returns:
            dict: Prediction with metadata
        """
        # Step 1: Prepare feature vector
        feature_vector = self._prepare_feature_vector(features)
        
        # Step 2: Validate feature vector
        if feature_vector is None:
            return {
                'system_id': self.system_id,
                'model_version': self.model_version,
                'predicted_points': None,
                'confidence_score': 0.0,
                'recommendation': 'PASS',
                'error': 'Invalid feature vector'
            }
        
        # Step 3: Make prediction
        try:
            predicted_points = float(self.model.predict(feature_vector)[0])
        except Exception as e:
            return {
                'system_id': self.system_id,
                'model_version': self.model_version,
                'predicted_points': None,
                'confidence_score': 0.0,
                'recommendation': 'PASS',
                'error': f'Model prediction failed: {str(e)}'
            }
        
        # Clamp to reasonable range
        predicted_points = max(0, min(60, predicted_points))
        
        # Step 4: Calculate confidence
        confidence = self._calculate_confidence(features, feature_vector)
        
        # Step 5: Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_points,
            betting_line,
            confidence
        )
        
        return {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'model_type': self._get_model_type()
        }
    
    # ========================================================================
    # FEATURE PREPARATION
    # ========================================================================
    
    def _prepare_feature_vector(self, features: Dict) -> Optional[np.ndarray]:
        """
        Prepare feature vector in exact order required by model
        
        CRITICAL: Features must be in this exact order or predictions will be wrong!
        
        Order:
        0. points_avg_last_5
        1. points_avg_last_10
        2. points_avg_season
        3. points_std_last_10
        4. minutes_avg_last_10
        5. fatigue_score
        6. shot_zone_mismatch_score
        7. pace_score
        8. usage_spike_score
        9. referee_favorability_score (0 for now)
        10. look_ahead_pressure_score (0 for now)
        11. matchup_history_score (0 for now)
        12. momentum_score (0 for now)
        13. opponent_def_rating_last_15
        14. opponent_pace_last_15
        15. is_home
        16. days_rest
        17. back_to_back
        18. paint_rate_last_10
        19. mid_range_rate_last_10
        20. three_pt_rate_last_10
        21. assisted_rate_last_10
        22. team_pace_last_10
        23. team_off_rating_last_10
        24. usage_rate_last_10
        
        Args:
            features: Dictionary with feature names and values
        
        Returns:
            np.ndarray: Feature vector (shape: 1, 25) or None if invalid
        """
        try:
            feature_vector = np.array([
                features.get('points_avg_last_5', 0),
                features.get('points_avg_last_10', 0),
                features.get('points_avg_season', 0),
                features.get('points_std_last_10', 0),
                features.get('minutes_avg_last_10', 0),
                features.get('fatigue_score', 70),
                features.get('shot_zone_mismatch_score', 0),
                features.get('pace_score', 0),
                features.get('usage_spike_score', 0),
                features.get('referee_favorability_score', 0),
                features.get('look_ahead_pressure_score', 0),
                features.get('matchup_history_score', 0),
                features.get('momentum_score', 0),
                features.get('opponent_def_rating_last_15', 112),
                features.get('opponent_pace_last_15', 100),
                features.get('is_home', 0),
                features.get('days_rest', 1),
                features.get('back_to_back', 0),
                features.get('paint_rate_last_10', 30),
                features.get('mid_range_rate_last_10', 20),
                features.get('three_pt_rate_last_10', 30),
                features.get('assisted_rate_last_10', 60),
                features.get('team_pace_last_10', 100),
                features.get('team_off_rating_last_10', 112),
                features.get('usage_rate_last_10', 25)
            ]).reshape(1, -1)
            
            # Validate no NaN or Inf values
            if np.any(np.isnan(feature_vector)) or np.any(np.isinf(feature_vector)):
                return None
            
            return feature_vector
            
        except Exception as e:
            logger.error(f"Error preparing feature vector: {e}", exc_info=True)
            return None
    
    # ========================================================================
    # MODEL LOADING
    # ========================================================================
    
    def _load_model_from_gcs(self, model_path: str):
        """
        Load trained XGBoost model from Google Cloud Storage
        
        Args:
            model_path: Path to model in GCS (e.g., 'models/xgboost_v1.json')
        
        Returns:
            Loaded XGBoost model
        """
        # This would be used in production
        # For now, falls back to mock model
        
        try:
            import xgboost as xgb
            from google.cloud import storage
            
            # Parse GCS path
            if model_path.startswith('gs://'):
                parts = model_path.replace('gs://', '').split('/', 1)
                bucket_name = parts[0]
                blob_path = parts[1]
            else:
                raise ValueError(f"Invalid GCS path: {model_path}")
            
            # Download from GCS
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            # Save to local temp file
            local_path = '/tmp/xgboost_model.json'
            blob.download_to_filename(local_path)
            
            # Load model
            model = xgb.Booster()
            model.load_model(local_path)
            
            return model
            
        except Exception as e:
            logger.warning(f"Could not load model from GCS: {e}")
            logger.info("Falling back to mock model for testing")
            
            from predictions.shared.mock_xgboost_model import load_mock_model
            return load_mock_model(seed=42)
    
    # ========================================================================
    # CONFIDENCE CALCULATION
    # ========================================================================
    
    def _calculate_confidence(
        self,
        features: Dict,
        feature_vector: np.ndarray
    ) -> float:
        """
        Calculate confidence score
        
        For ML models, confidence is harder to estimate than rule-based systems.
        We use several heuristics:
        
        1. Base ML confidence (70% - higher than rules due to training)
        2. Data quality adjustment (±10 points)
        3. Feature consistency adjustment (±10 points)
        4. Model uncertainty (if available) (±10 points)
        
        Args:
            features: Feature dictionary
            feature_vector: Prepared feature vector
        
        Returns:
            float: Confidence score (0-100)
        """
        confidence = 70.0  # ML models start with higher base confidence
        
        # Data quality adjustment (±10 points)
        quality = features.get('feature_quality_score', 80)
        if quality >= 90:
            confidence += 10
        elif quality >= 80:
            confidence += 7
        elif quality >= 70:
            confidence += 5
        elif quality >= 60:
            confidence += 2
        else:
            confidence += 0
        
        # Consistency adjustment (±10 points)
        # Lower variance = more predictable = higher confidence
        std_dev = features.get('points_std_last_10', 5)
        if std_dev < 4:
            confidence += 10
        elif std_dev < 6:
            confidence += 7
        elif std_dev < 8:
            confidence += 5
        else:
            confidence += 2
        
        # Model uncertainty (if available)
        # Real XGBoost can estimate uncertainty via prediction intervals
        # For mock model, we skip this
        
        return max(0, min(100, confidence))
    
    # ========================================================================
    # RECOMMENDATION LOGIC
    # ========================================================================
    
    def _generate_recommendation(
        self,
        predicted_points: float,
        betting_line: Optional[float],
        confidence: float
    ) -> str:
        """
        Generate betting recommendation
        
        XGBoost can be more aggressive with edge threshold since
        it learns from historical data.
        
        Args:
            predicted_points: Model's prediction
            betting_line: Current betting line
            confidence: Confidence score
        
        Returns:
            str: 'OVER', 'UNDER', or 'PASS'
        """
        # Need betting line
        if betting_line is None:
            return 'PASS'
        
        # Minimum confidence threshold
        if confidence < 60:
            return 'PASS'
        
        # Calculate edge
        edge = predicted_points - betting_line
        
        # ML can use lower threshold (1.5 vs 2.0 for rules)
        min_edge = 1.5
        
        if edge >= min_edge:
            return 'OVER'
        elif edge <= -min_edge:
            return 'UNDER'
        else:
            return 'PASS'
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _get_model_type(self) -> str:
        """Get model type (mock or real)"""
        if hasattr(self.model, 'get_model_metadata'):
            metadata = self.model.get_model_metadata()
            return 'mock' if metadata.get('is_mock', False) else 'xgboost'
        return 'xgboost'
    
    def get_feature_importance(self) -> Dict:
        """
        Get feature importance from model
        
        Returns:
            dict: Feature importance scores
        """
        if hasattr(self.model, 'get_feature_importance'):
            return self.model.get_feature_importance()
        return {}
    
    def get_model_info(self) -> Dict:
        """
        Get model information
        
        Returns:
            dict: Model metadata
        """
        info = {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'model_type': self._get_model_type()
        }
        
        if hasattr(self.model, 'get_model_metadata'):
            metadata = self.model.get_model_metadata()
            # Add metadata but don't overwrite model_type
            for key, value in metadata.items():
                if key not in ['model_type', 'system_id', 'model_version']:
                    info[key] = value
        
        return info


# ============================================================================
# PRODUCTION MODEL LOADING (for future use)
# ============================================================================

def load_production_model(model_path: str) -> XGBoostV1:
    """
    Load production XGBoost model from GCS
    
    Args:
        model_path: GCS path to model (e.g., 'gs://bucket/models/xgboost_v1.json')
    
    Returns:
        XGBoostV1: System with loaded model
    """
    return XGBoostV1(model_path=model_path)


def load_mock_system() -> XGBoostV1:
    """
    Load system with mock model for testing
    
    Returns:
        XGBoostV1: System with mock model
    """
    from predictions.shared.mock_xgboost_model import load_mock_model
    mock_model = load_mock_model(seed=42)
    return XGBoostV1(model=mock_model)