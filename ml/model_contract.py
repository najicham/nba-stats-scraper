"""
Model Contract - Defines expected feature names, ranges, and validation rules

This module provides a contract system for ML models to ensure:
1. Feature names and order match between training and production
2. Feature values fall within expected ranges (based on training data statistics)
3. Model files can be verified via hash
4. Feature drift can be detected

Usage:
    # During training:
    contract = ModelContract.from_training(
        model_id="catboost_v8_20260108",
        model_version="v8",
        feature_names=feature_list,
        X=training_features,  # DataFrame
        model_path="models/catboost_v8.cbm"
    )
    contract.save("models/catboost_v8_contract.json")

    # During inference:
    contract = ModelContract.load("models/catboost_v8_contract.json")
    issues = contract.validate_features(features_dict)
    if issues:
        logger.warning(f"Feature validation issues: {issues}")
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import json
import hashlib
from pathlib import Path


@dataclass
class FeatureStats:
    """Statistics for a single feature from training data"""
    name: str
    index: int
    mean: float
    std: float
    min_val: float
    max_val: float
    p5: float
    p25: float
    p50: float  # median
    p75: float
    p95: float
    missing_rate: float
    is_nullable: bool = False  # Whether NaN is allowed (e.g., shot zones, Vegas lines)

    def validate(self, value: Any) -> List[str]:
        """Validate a single feature value against training statistics"""
        issues = []

        # Check for None/NaN
        if value is None or (isinstance(value, float) and value != value):  # NaN check
            if not self.is_nullable:
                issues.append(f"MISSING: Feature {self.index} ({self.name}) is null but not nullable")
            return issues  # Skip range checks for null values

        # Convert to float for comparison
        try:
            val = float(value)
        except (ValueError, TypeError):
            issues.append(f"INVALID: Feature {self.index} ({self.name}) cannot convert to float: {value}")
            return issues

        # Check if outside expected range (p5 to p95)
        if val < self.p5:
            issues.append(f"LOW: Feature {self.index} ({self.name}) = {val:.2f} < p5 ({self.p5:.2f})")
        if val > self.p95:
            issues.append(f"HIGH: Feature {self.index} ({self.name}) = {val:.2f} > p95 ({self.p95:.2f})")

        # Check if extreme outlier (> 3 sigma from mean)
        if self.std > 0:
            z_score = abs(val - self.mean) / self.std
            if z_score > 4:
                issues.append(f"OUTLIER: Feature {self.index} ({self.name}) z={z_score:.1f} (> 4 sigma)")

        return issues


@dataclass
class ModelContract:
    """Contract defining expected model inputs and validation rules"""

    # Model identification
    model_id: str
    model_version: str
    model_type: str  # 'catboost', 'xgboost', 'ensemble'

    # Feature specification
    feature_names: List[str]
    feature_count: int
    feature_stats: Dict[str, Dict]  # Serialized FeatureStats
    nullable_features: List[int] = field(default_factory=list)  # Indices of nullable features

    # Training metadata
    training_date_range: Tuple[str, str] = ("", "")
    training_samples: int = 0
    training_mae: Optional[float] = None

    # Model file verification
    model_file_hash: str = ""
    model_file_path: str = ""

    # Lifecycle
    created_at: str = ""
    created_by: str = "training_script"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def get_feature_stats(self, name: str) -> Optional[FeatureStats]:
        """Get FeatureStats object for a feature by name"""
        if name not in self.feature_stats:
            return None
        stats = self.feature_stats[name]
        return FeatureStats(
            name=stats['name'],
            index=stats['index'],
            mean=stats['mean'],
            std=stats['std'],
            min_val=stats['min_val'],
            max_val=stats['max_val'],
            p5=stats['p5'],
            p25=stats['p25'],
            p50=stats['p50'],
            p75=stats['p75'],
            p95=stats['p95'],
            missing_rate=stats['missing_rate'],
            is_nullable=stats.get('is_nullable', False),
        )

    def validate_features(self, features: Dict[str, Any]) -> List[str]:
        """
        Validate feature values against training statistics

        Args:
            features: Dictionary of feature_name -> value

        Returns:
            List of validation issues (empty if all valid)
        """
        issues = []

        # Check for missing features
        for name in self.feature_names:
            if name not in features and name not in [self.feature_names[i] for i in self.nullable_features]:
                issues.append(f"MISSING: Feature '{name}' not provided")

        # Validate each feature value
        for name, value in features.items():
            if name not in self.feature_stats:
                continue  # Skip unknown features

            stats = self.get_feature_stats(name)
            if stats:
                issues.extend(stats.validate(value))

        return issues

    def validate_feature_vector(self, vector: List[float]) -> List[str]:
        """
        Validate a feature vector (in order) against training statistics

        Args:
            vector: List of feature values in expected order

        Returns:
            List of validation issues
        """
        issues = []

        if len(vector) != self.feature_count:
            issues.append(f"COUNT: Expected {self.feature_count} features, got {len(vector)}")
            return issues

        for i, (name, value) in enumerate(zip(self.feature_names, vector)):
            stats = self.get_feature_stats(name)
            if stats:
                issues.extend(stats.validate(value))

        return issues

    def verify_model_hash(self, model_path: str) -> bool:
        """Verify model file hasn't changed since contract was created"""
        current_hash = get_model_hash(model_path)
        return current_hash == self.model_file_hash

    @classmethod
    def from_training(
        cls,
        model_id: str,
        model_version: str,
        model_type: str,
        feature_names: List[str],
        X,  # pandas DataFrame
        model_path: str,
        training_date_range: Tuple[str, str] = ("", ""),
        training_mae: Optional[float] = None,
        nullable_features: Optional[List[int]] = None,
    ) -> 'ModelContract':
        """
        Create a contract from training data

        Args:
            model_id: Unique model identifier
            model_version: Version string (e.g., 'v8')
            model_type: Model type ('catboost', 'xgboost', 'ensemble')
            feature_names: List of feature names in order
            X: Training feature DataFrame
            model_path: Path to saved model file
            training_date_range: (start_date, end_date) of training data
            training_mae: Model's MAE on training/validation set
            nullable_features: List of feature indices that can be null/NaN
        """
        import pandas as pd
        import numpy as np

        feature_stats = {}
        nullable_indices = nullable_features or []

        for i, col in enumerate(feature_names):
            if col in X.columns:
                series = X[col]
                stats = FeatureStats(
                    name=col,
                    index=i,
                    mean=float(series.mean()) if not pd.isna(series.mean()) else 0.0,
                    std=float(series.std()) if not pd.isna(series.std()) else 0.0,
                    min_val=float(series.min()) if not pd.isna(series.min()) else 0.0,
                    max_val=float(series.max()) if not pd.isna(series.max()) else 0.0,
                    p5=float(series.quantile(0.05)) if not pd.isna(series.quantile(0.05)) else 0.0,
                    p25=float(series.quantile(0.25)) if not pd.isna(series.quantile(0.25)) else 0.0,
                    p50=float(series.quantile(0.50)) if not pd.isna(series.quantile(0.50)) else 0.0,
                    p75=float(series.quantile(0.75)) if not pd.isna(series.quantile(0.75)) else 0.0,
                    p95=float(series.quantile(0.95)) if not pd.isna(series.quantile(0.95)) else 0.0,
                    missing_rate=float(series.isna().mean()),
                    is_nullable=i in nullable_indices,
                )
                feature_stats[col] = asdict(stats)
            else:
                # Feature not in training data, create placeholder
                feature_stats[col] = asdict(FeatureStats(
                    name=col,
                    index=i,
                    mean=0.0, std=0.0, min_val=0.0, max_val=0.0,
                    p5=0.0, p25=0.0, p50=0.0, p75=0.0, p95=0.0,
                    missing_rate=1.0,
                    is_nullable=i in nullable_indices,
                ))

        return cls(
            model_id=model_id,
            model_version=model_version,
            model_type=model_type,
            feature_names=feature_names,
            feature_count=len(feature_names),
            feature_stats=feature_stats,
            nullable_features=nullable_indices,
            training_date_range=training_date_range,
            training_samples=len(X),
            training_mae=training_mae,
            model_file_hash=get_model_hash(model_path) if model_path and Path(model_path).exists() else "",
            model_file_path=str(model_path),
        )

    def save(self, path: str):
        """Save contract to JSON file"""
        data = asdict(self)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'ModelContract':
        """Load contract from JSON file"""
        with open(path) as f:
            data = json.load(f)

        # Handle tuple conversion for training_date_range
        if isinstance(data.get('training_date_range'), list):
            data['training_date_range'] = tuple(data['training_date_range'])

        return cls(**data)


def get_model_hash(model_path: str) -> str:
    """Calculate SHA256 hash of model file for verification"""
    sha256_hash = hashlib.sha256()
    try:
        with open(model_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return ""


# V8 Model Feature Names (for reference)
V8_FEATURE_NAMES = [
    # Base features (0-24)
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_played_last_10",
    "injury_adjustment",
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",
    "team_pace",
    "team_off_rating",
    "team_win_pct",
    # V8 features (25-32)
    "vegas_points_line",
    "vegas_opening_line",
    "vegas_line_move",
    "has_vegas_line",
    "avg_points_vs_opponent",
    "games_vs_opponent",
    "minutes_avg_last_10",
    "ppm_avg_last_10",
    # V8.1 feature (33)
    "has_shot_zone_data",
]

# V8 Nullable Features (can have NaN values)
V8_NULLABLE_FEATURES = [
    18, 19, 20,  # Shot zone features: pct_paint, pct_mid_range, pct_three
    25, 26, 27,  # Vegas features: vegas_points_line, vegas_opening_line, vegas_line_move
]
