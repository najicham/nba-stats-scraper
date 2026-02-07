"""
Canonical Feature Contract for ML Models

THIS IS THE SINGLE SOURCE OF TRUTH for feature definitions.
All training scripts, prediction code, and feature store processors
MUST import from this file to ensure consistency.

DO NOT duplicate feature lists elsewhere. Import from here.

When adding new features:
1. Add to the appropriate version list below
2. Add to FEATURE_STORE_NAMES if it should be in the feature store
3. Update CURRENT_FEATURE_STORE_VERSION if feature store schema changes
4. Run validation: python -m shared.ml.feature_contract --validate
"""

from typing import List, Dict, Optional
from dataclasses import dataclass


# =============================================================================
# FEATURE STORE CONFIGURATION
# =============================================================================

CURRENT_FEATURE_STORE_VERSION = "v2_39features"
FEATURE_STORE_FEATURE_COUNT = 39

# Canonical feature names in the feature store, IN ORDER
# Position matters! New features must be APPENDED, never inserted.
FEATURE_STORE_NAMES: List[str] = [
    # 0-4: Recent Performance
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",

    # 5-8: Composite Factors
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",

    # 9-12: Derived Factors
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",

    # 13-17: Matchup Context
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",

    # 18-21: Shot Zones
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",

    # 22-24: Team Context
    "team_pace",
    "team_off_rating",
    "team_win_pct",

    # 25-28: Vegas Lines
    "vegas_points_line",
    "vegas_opening_line",
    "vegas_line_move",
    "has_vegas_line",

    # 29-30: Opponent History
    "avg_points_vs_opponent",
    "games_vs_opponent",

    # 31-32: Minutes/Efficiency
    "minutes_avg_last_10",
    "ppm_avg_last_10",

    # 33: DNP Risk (added Session 28)
    "dnp_rate",

    # 34-36: Player Trajectory (added Session 28)
    "pts_slope_10g",
    "pts_vs_season_zscore",
    "breakout_flag",

    # 37: Breakout Risk (added Session 126)
    "breakout_risk_score",

    # 38: Composite Breakout Signal (added Session 126)
    "composite_breakout_signal",
]

# Validate feature store list length matches expected count
assert len(FEATURE_STORE_NAMES) == FEATURE_STORE_FEATURE_COUNT, (
    f"FEATURE_STORE_NAMES has {len(FEATURE_STORE_NAMES)} features, "
    f"expected {FEATURE_STORE_FEATURE_COUNT}"
)


# =============================================================================
# MODEL VERSION FEATURE DEFINITIONS
# =============================================================================

@dataclass
class ModelFeatureContract:
    """Contract defining which features a model version uses."""
    model_version: str
    feature_count: int
    feature_names: List[str]
    description: str

    def validate(self) -> bool:
        """Validate contract consistency."""
        if len(self.feature_names) != self.feature_count:
            raise ValueError(
                f"{self.model_version}: feature_names has {len(self.feature_names)} items, "
                f"expected {self.feature_count}"
            )
        return True

    def get_feature_index(self, name: str) -> int:
        """Get the index of a feature by name."""
        try:
            return self.feature_names.index(name)
        except ValueError:
            raise ValueError(f"Feature '{name}' not found in {self.model_version}")

    def extract_from_dict(self, features_dict: Dict[str, float],
                          defaults: Optional[Dict[str, float]] = None) -> List[float]:
        """
        Extract features from a dictionary in the correct order.

        This is the SAFE way to build a feature vector - by name, not position.
        """
        defaults = defaults or {}
        result = []
        for name in self.feature_names:
            if name in features_dict and features_dict[name] is not None:
                result.append(float(features_dict[name]))
            elif name in defaults:
                result.append(float(defaults[name]))
            else:
                raise ValueError(f"Missing feature '{name}' with no default")
        return result

    def extract_from_arrays(self, feature_values: List[float],
                            feature_names: List[str]) -> Dict[str, float]:
        """
        Convert parallel arrays to a dictionary.

        Use this when reading from the feature store.
        """
        if len(feature_values) != len(feature_names):
            min_len = min(len(feature_values), len(feature_names))
            feature_values = feature_values[:min_len]
            feature_names = feature_names[:min_len]
        return dict(zip(feature_names, feature_values))


# -----------------------------------------------------------------------------
# V8 Model Contract (33 features)
# Historical model trained on 2021-2024 data
# -----------------------------------------------------------------------------

V8_FEATURE_NAMES: List[str] = [
    # 0-4: Recent Performance
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",

    # 5-8: Composite Factors
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",

    # 9-12: Derived Factors
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",

    # 13-17: Matchup Context
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",

    # 18-21: Shot Zones
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",

    # 22-24: Team Context
    "team_pace",
    "team_off_rating",
    "team_win_pct",

    # 25-28: Vegas Lines
    "vegas_points_line",
    "vegas_opening_line",
    "vegas_line_move",
    "has_vegas_line",

    # 29-30: Opponent History
    "avg_points_vs_opponent",
    "games_vs_opponent",

    # 31-32: Minutes/Efficiency
    "minutes_avg_last_10",
    "ppm_avg_last_10",
]

V8_CONTRACT = ModelFeatureContract(
    model_version="v8",
    feature_count=33,
    feature_names=V8_FEATURE_NAMES,
    description="CatBoost V8 - 33 features, trained on 2021-2024 historical data"
)


# -----------------------------------------------------------------------------
# V9 Model Contract (33 features)
# Current production model trained on Nov 2025+ data
# Same features as V8, different training data
# -----------------------------------------------------------------------------

V9_FEATURE_NAMES: List[str] = V8_FEATURE_NAMES.copy()  # Same as V8

V9_CONTRACT = ModelFeatureContract(
    model_version="v9",
    feature_count=33,
    feature_names=V9_FEATURE_NAMES,
    description="CatBoost V9 - 33 features, trained on Nov 2025+ current season data"
)


# -----------------------------------------------------------------------------
# V10 Model Contract (FUTURE - 37+ features with tier information)
# -----------------------------------------------------------------------------

V10_FEATURE_NAMES: List[str] = V9_FEATURE_NAMES + [
    # 33: DNP Risk
    "dnp_rate",

    # 34-36: Player Trajectory
    "pts_slope_10g",
    "pts_vs_season_zscore",
    "breakout_flag",
]

V10_CONTRACT = ModelFeatureContract(
    model_version="v10",
    feature_count=37,
    feature_names=V10_FEATURE_NAMES,
    description="CatBoost V10 - 37 features, includes trajectory features"
)


# =============================================================================
# CONTRACT REGISTRY
# =============================================================================

MODEL_CONTRACTS: Dict[str, ModelFeatureContract] = {
    "v8": V8_CONTRACT,
    "v9": V9_CONTRACT,
    "v10": V10_CONTRACT,
    "catboost_v8": V8_CONTRACT,
    "catboost_v9": V9_CONTRACT,
    "catboost_v10": V10_CONTRACT,
}


def get_contract(model_version: str) -> ModelFeatureContract:
    """Get the feature contract for a model version."""
    # Normalize version string
    version = model_version.lower().replace("catboost_", "")
    if version.startswith("v9_"):  # Handle v9_feb_02_retrain etc
        version = "v9"
    if version.startswith("v8_"):
        version = "v8"

    if version not in MODEL_CONTRACTS:
        raise ValueError(f"Unknown model version: {model_version}")
    return MODEL_CONTRACTS[version]


# =============================================================================
# FEATURE SOURCE CLASSIFICATION (Session 142)
# =============================================================================
# All 33 V9 features are REQUIRED for prediction (zero tolerance, Session 141).
# If any feature has source='default', prediction is blocked.
# These constants map feature indices to their upstream pipeline source,
# helping diagnose which pipeline component to fix when coverage drops.

# Features populated by Phase 4 precompute processors
FEATURES_FROM_PHASE4 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 13, 14, 22, 23, 29, 31, 32]

# Features populated by Phase 3 analytics
FEATURES_FROM_PHASE3 = [15, 16, 17]

# Features calculated on-the-fly during feature store generation
FEATURES_CALCULATED = [9, 10, 11, 12, 21, 24, 28, 30, 33, 34, 35, 36]

# Features from vegas/odds data
FEATURES_VEGAS = [25, 26, 27]

# Features from shot zone analysis
FEATURES_SHOT_ZONE = [18, 19, 20]

# Session 145: Optional features - not counted in zero-tolerance gating
# Vegas lines are unavailable for ~60% of players (bench players without published lines).
# These features are still tracked as defaults for visibility, but don't block predictions.
# Scraper health monitoring separately alerts when star players are missing lines.
FEATURES_OPTIONAL = set(FEATURES_VEGAS)  # {25, 26, 27}

# Reverse mapping: feature index -> source pipeline component
FEATURE_SOURCE_MAP = {}
for _idx in FEATURES_FROM_PHASE4:
    FEATURE_SOURCE_MAP[_idx] = 'phase4'
for _idx in FEATURES_FROM_PHASE3:
    FEATURE_SOURCE_MAP[_idx] = 'phase3'
for _idx in FEATURES_CALCULATED:
    FEATURE_SOURCE_MAP[_idx] = 'calculated'
for _idx in FEATURES_VEGAS:
    FEATURE_SOURCE_MAP[_idx] = 'vegas'
for _idx in FEATURES_SHOT_ZONE:
    FEATURE_SOURCE_MAP[_idx] = 'shot_zone'


# =============================================================================
# DEFAULT VALUES FOR MISSING FEATURES
# =============================================================================

FEATURE_DEFAULTS: Dict[str, float] = {
    # Recent Performance - use low defaults (conservative)
    "points_avg_last_5": 10.0,
    "points_avg_last_10": 10.0,
    "points_avg_season": 10.0,
    "points_std_last_10": 5.0,
    "games_in_last_7_days": 3.0,

    # Composite Factors - use neutral defaults
    "fatigue_score": 50.0,
    "shot_zone_mismatch_score": 0.0,
    "pace_score": 0.0,
    "usage_spike_score": 0.0,

    # Derived Factors - use neutral defaults
    "rest_advantage": 0.0,
    "injury_risk": 0.0,
    "recent_trend": 0.0,
    "minutes_change": 0.0,

    # Matchup Context - use league averages
    "opponent_def_rating": 112.0,
    "opponent_pace": 100.0,
    "home_away": 0.5,  # Neutral
    "back_to_back": 0.0,
    "playoff_game": 0.0,

    # Shot Zones - use league averages
    "pct_paint": 0.35,
    "pct_mid_range": 0.15,
    "pct_three": 0.35,
    "pct_free_throw": 0.15,

    # Team Context - use league averages
    "team_pace": 100.0,
    "team_off_rating": 112.0,
    "team_win_pct": 0.5,

    # Vegas Lines - use None indicator
    "vegas_points_line": None,  # Will be handled specially
    "vegas_opening_line": None,
    "vegas_line_move": 0.0,
    "has_vegas_line": 0.0,

    # Opponent History - use season average fallback
    "avg_points_vs_opponent": None,  # Will use season_avg
    "games_vs_opponent": 0.0,

    # Minutes/Efficiency - use role player defaults
    "minutes_avg_last_10": 25.0,
    "ppm_avg_last_10": 0.4,

    # Trajectory features
    "dnp_rate": 0.0,
    "pts_slope_10g": 0.0,
    "pts_vs_season_zscore": 0.0,
    "breakout_flag": 0.0,
}


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def validate_all_contracts() -> bool:
    """Validate all model contracts."""
    print("Validating feature contracts...")

    for name, contract in MODEL_CONTRACTS.items():
        contract.validate()
        print(f"  ✓ {name}: {contract.feature_count} features")

    # Validate feature store alignment
    for i, (store_name, v9_name) in enumerate(zip(FEATURE_STORE_NAMES[:33], V9_FEATURE_NAMES)):
        if store_name != v9_name:
            raise ValueError(
                f"Feature store position {i} mismatch: "
                f"store has '{store_name}', V9 expects '{v9_name}'"
            )
    print(f"  ✓ Feature store aligned with V9 (first 33 features)")

    print("All contracts valid!")
    return True


def validate_feature_vector(vector: List[float], contract: ModelFeatureContract) -> bool:
    """Validate a feature vector matches a contract."""
    if len(vector) != contract.feature_count:
        raise ValueError(
            f"Feature vector has {len(vector)} values, "
            f"{contract.model_version} expects {contract.feature_count}"
        )
    return True


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--validate":
        try:
            validate_all_contracts()
            sys.exit(0)
        except Exception as e:
            print(f"Validation failed: {e}")
            sys.exit(1)
    else:
        print("Feature Contract Summary")
        print("=" * 50)
        print(f"Feature Store: {CURRENT_FEATURE_STORE_VERSION} ({FEATURE_STORE_FEATURE_COUNT} features)")
        print()
        for name, contract in MODEL_CONTRACTS.items():
            if not name.startswith("catboost_"):  # Skip aliases
                print(f"{contract.model_version}: {contract.feature_count} features")
                print(f"  {contract.description}")
        print()
        print("Run with --validate to check consistency")
