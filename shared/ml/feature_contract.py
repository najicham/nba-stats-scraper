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

CURRENT_FEATURE_STORE_VERSION = "v2_60features"
FEATURE_STORE_FEATURE_COUNT = 60

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

    # 37: Star Teammates Out (V11 - Injury Context, replaces disabled breakout_risk_score)
    "star_teammates_out",

    # 38: Game Total Line (V11 - Game Environment, replaces disabled composite_breakout_signal)
    "game_total_line",

    # 39-53: V12 Features (Session 230 - Feature Store Extension)
    "days_rest",
    "minutes_load_last_7d",
    "spread_magnitude",
    "implied_team_total",
    "points_avg_last_3",
    "scoring_trend_slope",
    "deviation_from_avg_last3",
    "consecutive_games_below_avg",
    "teammate_usage_available",
    "usage_rate_last_5",
    "games_since_structural_change",
    "multi_book_line_std",
    "prop_over_streak",
    "prop_under_streak",
    "line_vs_season_avg",

    # 54: Prop Line Delta (Session 294 — market overreaction signal)
    "prop_line_delta",                # current_line - previous_game_line

    # 55-56: V16 Features — Prop Line History (Session 356)
    "over_rate_last_10",              # Fraction of last 10 games where actual > prop_line [0.0-1.0]
    "margin_vs_line_avg_last_5",      # Mean(actual - prop_line) over last 5 games

    # 57-59: V17 Features — Opportunity Risk (Session 360)
    "blowout_minutes_risk",           # Fraction of team's L10 games with 15+ margin [0.0-1.0]
    "minutes_volatility_last_10",     # Stdev of player minutes over L10 games
    "opponent_pace_mismatch",         # team_pace - opponent_pace (positive = faster team)
]

# Validate feature store list length matches expected count
# >= because experiment features (55+) extend beyond BQ schema (55 columns)
assert len(FEATURE_STORE_NAMES) >= FEATURE_STORE_FEATURE_COUNT, (
    f"FEATURE_STORE_NAMES has {len(FEATURE_STORE_NAMES)} features, "
    f"expected at least {FEATURE_STORE_FEATURE_COUNT}"
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


# -----------------------------------------------------------------------------
# V11 Model Contract (39 features with star_teammates_out + game_total_line)
# Adds injury context and game environment features
# -----------------------------------------------------------------------------

V11_FEATURE_NAMES: List[str] = V10_FEATURE_NAMES + [
    # 37: Injury Context (V11)
    "star_teammates_out",

    # 38: Game Environment (V11)
    "game_total_line",
]

V11_CONTRACT = ModelFeatureContract(
    model_version="v11",
    feature_count=39,
    feature_names=V11_FEATURE_NAMES,
    description="CatBoost V11 - 39 features, adds star_teammates_out + game_total_line"
)


# -----------------------------------------------------------------------------
# V12 Model Contract (54 features - V2 architecture experiment)
# Adds fatigue, trend, team context, and market signals
# Experiment-only: does NOT change feature store schema
# -----------------------------------------------------------------------------

V12_FEATURE_NAMES: List[str] = V11_FEATURE_NAMES + [
    # 39: Fatigue / Rest
    "days_rest",                      # From UPCG.days_rest

    # 40: Workload
    "minutes_load_last_7d",           # From UPCG.minutes_in_last_7_days

    # 41-42: Game Environment (derived from spread/total)
    "spread_magnitude",               # abs(UPCG.game_spread)
    "implied_team_total",             # (game_total +/- spread) / 2

    # 43-46: Scoring Trends
    "points_avg_last_3",              # Ultra-short average
    "scoring_trend_slope",            # OLS slope last 7 games
    "deviation_from_avg_last3",       # Z-score: (avg_L3 - season_avg) / std
    "consecutive_games_below_avg",    # Cold streak counter

    # 47-48: Usage / Team Context
    "teammate_usage_available",       # SUM(usage_rate) for OUT teammates
    "usage_rate_last_5",              # Recent usage rate average

    # 49: Structural Change
    "games_since_structural_change",  # Games since trade/ASB/return

    # 50: Market Signal
    "multi_book_line_std",            # Std dev across sportsbooks

    # 51-53: Prop Line History
    "prop_over_streak",               # Consecutive games over prop line
    "prop_under_streak",              # Consecutive games under prop line
    "line_vs_season_avg",             # vegas_line - season_avg
]

V12_CONTRACT = ModelFeatureContract(
    model_version="v12",
    feature_count=54,
    feature_names=V12_FEATURE_NAMES,
    description="CatBoost V12 - 54 features, adds fatigue/trend/team/market signals for V2 architecture"
)


# -----------------------------------------------------------------------------
# V12 No-Vegas Contract (50 features - production deployment)
# V12 trained WITHOUT vegas features (indices 25-28 excluded)
# Used by CatBoostV12 prediction system in production
# -----------------------------------------------------------------------------

V12_NOVEG_FEATURE_NAMES: List[str] = [
    name for name in V12_FEATURE_NAMES if name not in (
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
    )
]

V12_NOVEG_CONTRACT = ModelFeatureContract(
    model_version="v12_noveg",
    feature_count=50,
    feature_names=V12_NOVEG_FEATURE_NAMES,
    description="CatBoost V12 No-Vegas - 50 features (54 minus 4 vegas), MAE loss, independent predictions"
)


# -----------------------------------------------------------------------------
# V13 Model Contract (60 features - V12 + shooting efficiency features)
# Adds FG% rolling averages, relative efficiency, and cold streak detection
# Experiment-only: does NOT change feature store schema
# -----------------------------------------------------------------------------

V13_FEATURE_NAMES: List[str] = V12_FEATURE_NAMES + [
    # 54-55: FG% Rolling Averages
    "fg_pct_last_3",                  # Mean FG% last 3 games (5+ FGA filter)
    "fg_pct_last_5",                  # Mean FG% last 5 games (5+ FGA filter)

    # 56: Relative Shooting Efficiency
    "fg_pct_vs_season_avg",           # FG% L3 minus season FG% (10+ games)

    # 57-58: 3PT Rolling Averages
    "three_pct_last_3",               # Mean 3PT% last 3 games (2+ 3PA filter)
    "three_pct_last_5",               # Mean 3PT% last 5 games (2+ 3PA filter)

    # 59: FG% Cold Streak Counter
    "fg_cold_streak",                 # Consecutive games < 40% FG% (5+ FGA)
]

V13_CONTRACT = ModelFeatureContract(
    model_version="v13",
    feature_count=60,
    feature_names=V13_FEATURE_NAMES,
    description="CatBoost V13 - 60 features, adds FG%/3PT% shooting efficiency signals"
)

V13_NOVEG_FEATURE_NAMES: List[str] = [
    name for name in V13_FEATURE_NAMES if name not in (
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
    )
]

V13_NOVEG_CONTRACT = ModelFeatureContract(
    model_version="v13_noveg",
    feature_count=56,
    feature_names=V13_NOVEG_FEATURE_NAMES,
    description="CatBoost V13 No-Vegas - 56 features (60 minus 4 vegas), with shooting efficiency"
)


# -----------------------------------------------------------------------------
# V14 Model Contract (65 features - V13 + engineered FG% features)
# Transforms raw FG% into CatBoost-usable signals: z-scores, interactions, acceleration
# Experiment-only: does NOT change feature store schema
# -----------------------------------------------------------------------------

V14_FEATURE_NAMES: List[str] = V13_FEATURE_NAMES + [
    # 60: Personalized FG% Z-Score (cold relative to THIS player's normal)
    "fg_cold_z_score",                # (fg_pct_L3 - season_fg_pct) / season_fg_std

    # 61: Volume-Adjusted Expected Points from shooting
    "expected_pts_from_shooting",     # fg_pct_L3 * fga_L3 * 2 + three_pct_L3 * tpa_L3

    # 62: FG% Acceleration (trend direction)
    "fg_pct_acceleration",            # fg_pct_L3 - fg_pct_L5

    # 63: Fatigue-Cold Interaction
    "fatigue_cold_signal",            # minutes_load_last_7d * (1 - fg_pct_L3)

    # 64: 3PT% Variance (shooting inconsistency)
    "three_pct_std_last_5",           # Std dev of 3PT% last 5 games
]

V14_CONTRACT = ModelFeatureContract(
    model_version="v14",
    feature_count=65,
    feature_names=V14_FEATURE_NAMES,
    description="CatBoost V14 - 65 features, adds engineered FG% signals (z-score, interactions, acceleration)"
)

V14_NOVEG_FEATURE_NAMES: List[str] = [
    name for name in V14_FEATURE_NAMES if name not in (
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
    )
]

V14_NOVEG_CONTRACT = ModelFeatureContract(
    model_version="v14_noveg",
    feature_count=61,
    feature_names=V14_NOVEG_FEATURE_NAMES,
    description="CatBoost V14 No-Vegas - 61 features (65 minus 4 vegas), with engineered FG% signals"
)


# -----------------------------------------------------------------------------
# V15 Model Contract (56 features - V12 + player profile features)
# Adds ft_rate_season and starter_rate_season from player_game_summary
# Based on V12 champion (not V13/V14 shooting efficiency chain)
# Experiment-only: does NOT change feature store schema
# -----------------------------------------------------------------------------

V15_FEATURE_NAMES: List[str] = V12_FEATURE_NAMES + [
    # 54: Player Profile - Free throw rate (FTA/FGA season-to-date)
    "ft_rate_season",

    # 55: Player Profile - Starter rate (% games started season-to-date)
    "starter_rate_season",
]

V15_CONTRACT = ModelFeatureContract(
    model_version="v15",
    feature_count=56,
    feature_names=V15_FEATURE_NAMES,
    description="CatBoost V15 - 56 features, V12 + ft_rate_season + starter_rate_season from player profiles"
)

V15_NOVEG_FEATURE_NAMES: List[str] = [
    name for name in V15_FEATURE_NAMES if name not in (
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
    )
]

V15_NOVEG_CONTRACT = ModelFeatureContract(
    model_version="v15_noveg",
    feature_count=52,
    feature_names=V15_NOVEG_FEATURE_NAMES,
    description="CatBoost V15 No-Vegas - 52 features (56 minus 4 vegas), with player profile features"
)


# -----------------------------------------------------------------------------
# V16 Model Contract (56 features - V12 + prop line history features)
# Adds over_rate_last_10 and margin_vs_line_avg_last_5 from prediction_accuracy
# Session 356: Best experiment result (75% HR edge 3+, OVER 88.9%, UNDER 63.6%)
# These ARE in the feature store schema (v2_57features)
# -----------------------------------------------------------------------------

V16_FEATURE_NAMES: List[str] = V12_FEATURE_NAMES + [
    # 54: Prop line over rate — fraction of last 10 games where actual > prop_line
    "over_rate_last_10",

    # 55: Margin vs line — mean(actual - prop_line) over last 5 games
    "margin_vs_line_avg_last_5",
]

V16_CONTRACT = ModelFeatureContract(
    model_version="v16",
    feature_count=56,
    feature_names=V16_FEATURE_NAMES,
    description="CatBoost V16 - 56 features, V12 + over_rate_last_10 + margin_vs_line_avg_last_5"
)

V16_NOVEG_FEATURE_NAMES: List[str] = [
    name for name in V16_FEATURE_NAMES if name not in (
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
    )
]

V16_NOVEG_CONTRACT = ModelFeatureContract(
    model_version="v16_noveg",
    feature_count=52,
    feature_names=V16_NOVEG_FEATURE_NAMES,
    description="CatBoost V16 No-Vegas - 52 features (56 minus 4 vegas), with prop line history features"
)


# -----------------------------------------------------------------------------
# V17 Model Contract (59 features - V16 + opportunity risk features)
# Adds blowout_minutes_risk, minutes_volatility_last_10, opponent_pace_mismatch
# Session 360: Captures risk of reduced opportunity — the gap the model can't express
# These ARE in the feature store schema (v2_60features)
# -----------------------------------------------------------------------------

V17_FEATURE_NAMES: List[str] = V16_FEATURE_NAMES + [
    # 56: Blowout risk — fraction of team's L10 games with 15+ margin
    "blowout_minutes_risk",

    # 57: Minutes volatility — stdev of player minutes over L10
    "minutes_volatility_last_10",

    # 58: Pace mismatch — team_pace minus opponent_pace
    "opponent_pace_mismatch",
]

V17_CONTRACT = ModelFeatureContract(
    model_version="v17",
    feature_count=59,
    feature_names=V17_FEATURE_NAMES,
    description="CatBoost V17 - 59 features, V16 + blowout_minutes_risk + minutes_volatility + pace_mismatch"
)

V17_NOVEG_FEATURE_NAMES: List[str] = [
    name for name in V17_FEATURE_NAMES if name not in (
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
    )
]

V17_NOVEG_CONTRACT = ModelFeatureContract(
    model_version="v17_noveg",
    feature_count=55,
    feature_names=V17_NOVEG_FEATURE_NAMES,
    description="CatBoost V17 No-Vegas - 55 features (59 minus 4 vegas), with opportunity risk features"
)


# =============================================================================
# CONTRACT REGISTRY
# =============================================================================

MODEL_CONTRACTS: Dict[str, ModelFeatureContract] = {
    "v8": V8_CONTRACT,
    "v9": V9_CONTRACT,
    "v10": V10_CONTRACT,
    "v11": V11_CONTRACT,
    "v12": V12_CONTRACT,
    "v12_noveg": V12_NOVEG_CONTRACT,
    "v13": V13_CONTRACT,
    "v13_noveg": V13_NOVEG_CONTRACT,
    "v14": V14_CONTRACT,
    "v14_noveg": V14_NOVEG_CONTRACT,
    "v15": V15_CONTRACT,
    "v15_noveg": V15_NOVEG_CONTRACT,
    "v16": V16_CONTRACT,
    "v16_noveg": V16_NOVEG_CONTRACT,
    "v17": V17_CONTRACT,
    "v17_noveg": V17_NOVEG_CONTRACT,
    "catboost_v8": V8_CONTRACT,
    "catboost_v9": V9_CONTRACT,
    "catboost_v10": V10_CONTRACT,
    "catboost_v11": V11_CONTRACT,
    "catboost_v12": V12_NOVEG_CONTRACT,
    "catboost_v13": V13_NOVEG_CONTRACT,
    "catboost_v14": V14_NOVEG_CONTRACT,
    "catboost_v15": V15_NOVEG_CONTRACT,
    "catboost_v16": V16_NOVEG_CONTRACT,
    "catboost_v17": V17_NOVEG_CONTRACT,
}


def get_contract(model_version: str) -> ModelFeatureContract:
    """Get the feature contract for a model version."""
    # Normalize version string
    version = model_version.lower().replace("catboost_", "")
    if version.startswith("v9_"):  # Handle v9_feb_02_retrain etc
        version = "v9"
    if version.startswith("v8_"):
        version = "v8"
    if version.startswith("v11_"):
        version = "v11"
    if version.startswith("v17_noveg"):
        version = "v17_noveg"
    elif version.startswith("v17_"):
        version = "v17"
    if version.startswith("v16_noveg"):
        version = "v16_noveg"
    elif version.startswith("v16_"):
        version = "v16"
    if version.startswith("v15_noveg"):
        version = "v15_noveg"
    elif version.startswith("v15_"):
        version = "v15"
    if version.startswith("v14_noveg"):
        version = "v14_noveg"
    elif version.startswith("v14_"):
        version = "v14"
    if version.startswith("v13_noveg"):
        version = "v13_noveg"
    elif version.startswith("v13_"):
        version = "v13"
    if version.startswith("v12_noveg"):
        version = "v12_noveg"
    elif version.startswith("v12_"):
        version = "v12"

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

# V11 features from Phase 3
FEATURES_FROM_PHASE3_V11 = [37, 38]

# Session 145: Optional features - not counted in zero-tolerance gating
# Vegas lines are unavailable for ~60% of players (bench players without published lines).
# game_total_line (38) depends on odds data availability.
# These features are still tracked as defaults for visibility, but don't block predictions.
# Scraper health monitoring separately alerts when star players are missing lines.
FEATURES_OPTIONAL = set(FEATURES_VEGAS) | {38, 41, 42, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59}

# Session 152: Vegas line source values
# Stored in ml_feature_store_v2.vegas_line_source and player_prop_predictions.vegas_line_source
# Tracks which scraper provided the ML features (25-28), distinct from line_source_api
# which tracks which source provided the prediction's betting line value.
VEGAS_SOURCE_ODDS_API = 'odds_api'
VEGAS_SOURCE_BETTINGPROS = 'bettingpros'
VEGAS_SOURCE_BOTH = 'both'
VEGAS_SOURCE_NONE = 'none'

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
for _idx in FEATURES_FROM_PHASE3_V11:
    FEATURE_SOURCE_MAP[_idx] = 'phase3'

# V12 feature source mappings (experiment-only)
FEATURES_FROM_UPCG_V12 = [39, 40, 51, 52]
FEATURES_COMPUTED_V12 = [41, 42, 43, 44, 45, 46, 48, 49, 53]
FEATURES_FROM_ODDS_V12 = [50]
FEATURES_FROM_INJURY_V12 = [47]

for _idx in FEATURES_FROM_UPCG_V12:
    FEATURE_SOURCE_MAP[_idx] = 'phase3'
for _idx in FEATURES_COMPUTED_V12:
    FEATURE_SOURCE_MAP[_idx] = 'calculated'
for _idx in FEATURES_FROM_ODDS_V12:
    FEATURE_SOURCE_MAP[_idx] = 'vegas'
for _idx in FEATURES_FROM_INJURY_V12:
    FEATURE_SOURCE_MAP[_idx] = 'injury_context'

# Feature 54: prop_line_delta (Session 294)
FEATURE_SOURCE_MAP[54] = 'vegas'

# Features 55-56: V16 prop line history (Session 356)
FEATURE_SOURCE_MAP[55] = 'calculated'
FEATURE_SOURCE_MAP[56] = 'calculated'

# Features 57-59: V17 opportunity risk (Session 360)
FEATURE_SOURCE_MAP[57] = 'calculated'
FEATURE_SOURCE_MAP[58] = 'calculated'
FEATURE_SOURCE_MAP[59] = 'calculated'


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

    # V11 features
    "star_teammates_out": 0.0,  # 0 = no stars out (common case, valid default)
    "game_total_line": 224.0,   # League average game total

    # V12 features (experiment-only)
    "days_rest": 1.0,
    "minutes_load_last_7d": 80.0,
    "spread_magnitude": 5.0,
    "implied_team_total": 112.0,
    "points_avg_last_3": 10.0,
    "scoring_trend_slope": 0.0,
    "deviation_from_avg_last3": 0.0,
    "consecutive_games_below_avg": 0.0,
    "teammate_usage_available": 0.0,
    "usage_rate_last_5": 20.0,
    "games_since_structural_change": 30.0,
    "multi_book_line_std": 0.5,
    "prop_over_streak": 0.0,
    "prop_under_streak": 0.0,
    "line_vs_season_avg": 0.0,

    # Feature 54 (Session 294)
    "prop_line_delta": 0.0,  # No change = neutral default

    # V13 features (experiment-only - shooting efficiency)
    "fg_pct_last_3": 0.45,       # League average FG%
    "fg_pct_last_5": 0.45,
    "fg_pct_vs_season_avg": 0.0,  # Neutral (no deviation)
    "three_pct_last_3": 0.36,    # League average 3PT%
    "three_pct_last_5": 0.36,
    "fg_cold_streak": 0.0,       # Not cold by default

    # V15 features (experiment-only - player profile)
    "ft_rate_season": 0.30,      # League average FTA/FGA ratio
    "starter_rate_season": 0.50, # Neutral (50% starter rate)

    # V16 features (Session 356 — prop line history)
    "over_rate_last_10": 0.5,    # Neutral (50% over rate)
    "margin_vs_line_avg_last_5": 0.0,  # Neutral (no margin)

    # V17 features (Session 360 — opportunity risk)
    "blowout_minutes_risk": 0.2,          # ~20% of games are blowouts league-wide
    "minutes_volatility_last_10": 4.0,    # Typical minutes stdev
    "opponent_pace_mismatch": 0.0,        # Neutral (no pace difference)
}


# =============================================================================
# COLUMN-BASED UTILITIES
# =============================================================================

def build_feature_array_from_columns(row, num_features: int = FEATURE_STORE_FEATURE_COUNT) -> List[float]:
    """Reconstruct feature array from individual feature_N_value columns.

    Used by training/augmentation code that needs an ordered list of features
    when migrating off the features ARRAY column.

    Args:
        row: A BigQuery Row, pandas Series, or any object with attribute/key access
             for feature_N_value columns.
        num_features: Number of features to extract (default 54 for full feature store).

    Returns:
        List of floats with NaN for NULL/missing columns (CatBoost compatible).
    """
    import math
    result = []
    for i in range(num_features):
        col_name = f'feature_{i}_value'
        # Support both attribute access (BQ Row) and dict/Series access
        val = None
        if hasattr(row, col_name):
            val = getattr(row, col_name, None)
        elif hasattr(row, '__getitem__'):
            try:
                val = row[col_name]
            except (KeyError, IndexError):
                pass
        if val is None or (isinstance(val, float) and math.isnan(val)):
            result.append(float('nan'))
        else:
            result.append(float(val))
    return result


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

    # Validate V11 alignment with feature store (first 39 features)
    for i, (store_name, v11_name) in enumerate(zip(FEATURE_STORE_NAMES[:39], V11_FEATURE_NAMES)):
        if store_name != v11_name:
            raise ValueError(
                f"Feature store position {i} mismatch: "
                f"store has '{store_name}', V11 expects '{v11_name}'"
            )
    print(f"  ✓ Feature store aligned with V11 (first 39 features)")

    # Validate V12 alignment with feature store (all 54 features)
    for i, (store_name, v12_name) in enumerate(zip(FEATURE_STORE_NAMES, V12_FEATURE_NAMES)):
        if store_name != v12_name:
            raise ValueError(
                f"Feature store position {i} mismatch: "
                f"store has '{store_name}', V12 expects '{v12_name}'"
            )
    print(f"  ✓ Feature store aligned with V12 (all 54 features)")

    # Validate V12 extends V11 (first 39 features must match)
    for i, (v11_name, v12_name) in enumerate(zip(V11_FEATURE_NAMES, V12_FEATURE_NAMES[:39])):
        if v11_name != v12_name:
            raise ValueError(
                f"V12 position {i} mismatch: "
                f"V11 has '{v11_name}', V12 has '{v12_name}'"
            )
    print(f"  ✓ V12 extends V11 (first 39 features match, +{V12_CONTRACT.feature_count - 39} new)")

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
