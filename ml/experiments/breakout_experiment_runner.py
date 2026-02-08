#!/usr/bin/env python3
"""
Enhanced Breakout Classifier Experiment Runner

Flexible experimentation framework for breakout classifier development.
Supports JSON config files or command-line parameters for rapid iteration.

MODES:
- SHARED (default): Use ml/features/breakout_features.py for production consistency
  - Ensures training uses same features as evaluation/inference
  - Uses the 10 production features from BREAKOUT_FEATURE_ORDER
  - Recommended for all production model training
- EXPERIMENTAL: Use custom feature sets for research
  - Flexible query building with Session 126 features
  - For testing new features before promoting to shared module

Key Features:
- Production-ready shared feature module integration
- Configurable feature sets (experimental mode)
- Tunable hyperparameters (depth, iterations, learning_rate, l2_reg)
- Adjustable target definitions (min_ppg, max_ppg, breakout_multiplier)
- Structured JSON output for comparison across experiments
- Both config file and inline parameter support

Usage:
    # SHARED MODE (recommended for production training)
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \\
        --name "PROD_V1" \\
        --mode shared

    # EXPERIMENTAL MODE (for feature research)
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \\
        --name "EXP_CV_RATIO" \\
        --mode experimental \\
        --features "cv_ratio,cold_streak_indicator,pts_vs_season_zscore" \\
        --depth 6 --iterations 300

    # List available features
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py --list-features

Session 127 - Breakout Classifier Experimentation Framework
Session 135 - Refactored to use shared feature module as default
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from google.cloud import bigquery
from sklearn.metrics import (
    roc_auc_score, precision_recall_curve, average_precision_score,
    classification_report, confusion_matrix
)
from sklearn.model_selection import train_test_split
import catboost as cb

# Import shared feature module for production consistency
from ml.features.breakout_features import (
    get_training_data_query as get_shared_training_query,
    prepare_feature_vector as prepare_shared_feature_vector,
    validate_feature_distributions,
    BreakoutFeatureConfig,
    BREAKOUT_FEATURE_ORDER,
    FEATURE_DEFAULTS,
)

from shared.ml.training_data_loader import get_quality_where_clause, get_quality_join_clause

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
RESULTS_OUTPUT_DIR = Path("experiments/results")


def _get_quality_clause(alias='mf'):
    """Session 157: Shared quality clause for WHERE conditions."""
    return get_quality_where_clause(alias)


# =============================================================================
# FEATURE REGISTRY
# =============================================================================

@dataclass
class FeatureDefinition:
    """Definition of a feature for the breakout classifier."""
    name: str
    source: str  # 'query', 'feature_store', or 'computed'
    description: str
    default: float
    feature_store_name: Optional[str] = None  # Name in feature store if different


# All available features for breakout classification
AVAILABLE_FEATURES: Dict[str, FeatureDefinition] = {
    # === Original features from train_breakout_classifier.py ===
    "pts_vs_season_zscore": FeatureDefinition(
        name="pts_vs_season_zscore",
        source="feature_store",
        description="Z-score of recent performance vs season avg (hot streak indicator)",
        default=0.0,
        feature_store_name="pts_vs_season_zscore"
    ),
    "points_std_last_10": FeatureDefinition(
        name="points_std_last_10",
        source="query",
        description="Standard deviation of points in last 10 games",
        default=5.0
    ),
    "explosion_ratio": FeatureDefinition(
        name="explosion_ratio",
        source="computed",
        description="max(L5 points) / season_avg - explosive scoring potential",
        default=1.0
    ),
    "days_since_breakout": FeatureDefinition(
        name="days_since_breakout",
        source="computed",
        description="Days since player's last breakout game",
        default=30.0
    ),
    "opponent_def_rating": FeatureDefinition(
        name="opponent_def_rating",
        source="feature_store",
        description="Opponent defensive rating (lower = better defense)",
        default=112.0,
        feature_store_name="opponent_def_rating"
    ),
    "home_away": FeatureDefinition(
        name="home_away",
        source="feature_store",
        description="1 = home, 0 = away",
        default=0.5,
        feature_store_name="home_away"
    ),
    "back_to_back": FeatureDefinition(
        name="back_to_back",
        source="feature_store",
        description="1 = second game of back-to-back, 0 = normal rest",
        default=0.0,
        feature_store_name="back_to_back"
    ),
    "points_avg_last_5": FeatureDefinition(
        name="points_avg_last_5",
        source="query",
        description="Average points in last 5 games",
        default=10.0
    ),
    "points_avg_season": FeatureDefinition(
        name="points_avg_season",
        source="query",
        description="Season average points",
        default=12.0
    ),
    "minutes_avg_last_10": FeatureDefinition(
        name="minutes_avg_last_10",
        source="query",
        description="Average minutes in last 10 games",
        default=25.0
    ),

    # === NEW Session 126 features ===
    "cv_ratio": FeatureDefinition(
        name="cv_ratio",
        source="computed",
        description="Coefficient of variation (std/avg) - STRONGEST predictor (+0.198 correlation)",
        default=0.4
    ),
    "cold_streak_indicator": FeatureDefinition(
        name="cold_streak_indicator",
        source="computed",
        description="1 if L5 avg < L10 avg * 0.8 (mean reversion signal - 27.1% breakout rate)",
        default=0.0
    ),
    "usage_rate_trend": FeatureDefinition(
        name="usage_rate_trend",
        source="computed",
        description="Recent usage rate (L10) - season usage rate (rising = +7% breakout)",
        default=0.0
    ),
    "minutes_trend": FeatureDefinition(
        name="minutes_trend",
        source="computed",
        description="Recent minutes (L10) - season minutes (increasing minutes = opportunity)",
        default=0.0
    ),
    "games_since_dnp": FeatureDefinition(
        name="games_since_dnp",
        source="computed",
        description="Games since player last had a DNP (0 minutes)",
        default=10.0
    ),

    # === Additional contextual features ===
    "points_avg_last_10": FeatureDefinition(
        name="points_avg_last_10",
        source="query",
        description="Average points in last 10 games",
        default=10.0
    ),
    "minutes_avg_season": FeatureDefinition(
        name="minutes_avg_season",
        source="feature_store",
        description="Season average minutes",
        default=25.0,
        feature_store_name="minutes_avg_last_10"  # Use L10 as proxy
    ),
    "games_in_last_7_days": FeatureDefinition(
        name="games_in_last_7_days",
        source="feature_store",
        description="Number of games played in last 7 days (fatigue indicator)",
        default=3.0,
        feature_store_name="games_in_last_7_days"
    ),
    "breakout_risk_score": FeatureDefinition(
        name="breakout_risk_score",
        source="feature_store",
        description="Composite breakout risk 0-100 (Session 126)",
        default=50.0,
        feature_store_name="breakout_risk_score"
    ),
    "composite_breakout_signal": FeatureDefinition(
        name="composite_breakout_signal",
        source="feature_store",
        description="0-5 factor count (37% breakout at 4+)",
        default=2.0,
        feature_store_name="composite_breakout_signal"
    ),
    "team_pace": FeatureDefinition(
        name="team_pace",
        source="feature_store",
        description="Team pace (possessions per 48 min)",
        default=100.0,
        feature_store_name="team_pace"
    ),
    "opponent_pace": FeatureDefinition(
        name="opponent_pace",
        source="feature_store",
        description="Opponent pace",
        default=100.0,
        feature_store_name="opponent_pace"
    ),
}

# Default feature set (matches original train_breakout_classifier.py)
DEFAULT_FEATURES = [
    "pts_vs_season_zscore",
    "points_std_last_10",
    "explosion_ratio",
    "days_since_breakout",
    "opponent_def_rating",
    "home_away",
    "back_to_back",
    "points_avg_last_5",
    "points_avg_season",
    "minutes_avg_last_10",
]

# Enhanced feature set with Session 126 discoveries
ENHANCED_FEATURES = DEFAULT_FEATURES + [
    "cv_ratio",
    "cold_streak_indicator",
    "usage_rate_trend",
    "minutes_trend",
]


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ExperimentConfig:
    """Configuration for a breakout classifier experiment."""
    # Experiment metadata
    name: str
    hypothesis: str = ""
    tags: List[str] = None

    # Mode configuration
    mode: str = "shared"  # "shared" or "experimental"

    # Feature configuration (experimental mode only)
    feature_set: List[str] = None

    # Hyperparameters
    depth: int = 5
    iterations: int = 500
    learning_rate: float = 0.05
    l2_reg: float = 3.0
    early_stopping_rounds: int = 30

    # Target definition
    min_ppg: float = 8.0
    max_ppg: float = 16.0
    breakout_multiplier: float = 1.5

    # Date ranges
    train_start: str = None
    train_end: str = None
    eval_start: str = None
    eval_end: str = None
    train_days: int = 60
    eval_days: int = 7

    # Options
    target_precision: float = 0.60
    skip_register: bool = False
    dry_run: bool = False

    def __post_init__(self):
        if self.tags is None:
            self.tags = ["breakout", "classifier", "experiment"]
        # Default feature set based on mode
        if self.mode == "shared":
            # Shared mode: always use production features
            self.feature_set = BREAKOUT_FEATURE_ORDER.copy()
        elif self.feature_set is None:
            # Experimental mode: default to original features if not specified
            self.feature_set = DEFAULT_FEATURES.copy()

    @classmethod
    def from_json(cls, json_path: str) -> "ExperimentConfig":
        """Load config from JSON file."""
        with open(json_path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_args(cls, args) -> "ExperimentConfig":
        """Create config from command-line arguments."""
        features = args.features.split(',') if args.features else None

        return cls(
            name=args.name,
            hypothesis=args.hypothesis,
            tags=[t.strip() for t in args.tags.split(',') if t.strip()],
            mode=args.mode,
            feature_set=features,
            depth=args.depth,
            iterations=args.iterations,
            learning_rate=args.learning_rate,
            l2_reg=args.l2_reg,
            early_stopping_rounds=args.early_stopping,
            min_ppg=args.min_ppg,
            max_ppg=args.max_ppg,
            breakout_multiplier=args.breakout_multiplier,
            train_start=args.train_start,
            train_end=args.train_end,
            eval_start=args.eval_start,
            eval_end=args.eval_end,
            train_days=args.train_days,
            eval_days=args.eval_days,
            target_precision=args.target_precision,
            skip_register=args.skip_register,
            dry_run=args.dry_run,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def validate(self) -> List[str]:
        """Validate configuration. Returns list of errors."""
        errors = []

        # Validate mode
        if self.mode not in ["shared", "experimental"]:
            errors.append(f"mode must be 'shared' or 'experimental', got: {self.mode}")

        # In shared mode, warn if features specified (they'll be ignored)
        if self.mode == "shared" and self.feature_set != BREAKOUT_FEATURE_ORDER:
            # This is a warning, not error - features will be overridden
            pass

        # In experimental mode, validate features
        if self.mode == "experimental":
            for f in self.feature_set:
                if f not in AVAILABLE_FEATURES:
                    errors.append(f"Unknown feature: {f}")

        # Validate PPG range
        if self.min_ppg >= self.max_ppg:
            errors.append(f"min_ppg ({self.min_ppg}) must be < max_ppg ({self.max_ppg})")

        # Validate multiplier
        if self.breakout_multiplier <= 1.0:
            errors.append(f"breakout_multiplier ({self.breakout_multiplier}) must be > 1.0")

        # Validate hyperparameters
        if self.depth < 1 or self.depth > 16:
            errors.append(f"depth ({self.depth}) should be between 1 and 16")
        if self.learning_rate <= 0 or self.learning_rate > 1:
            errors.append(f"learning_rate ({self.learning_rate}) should be between 0 and 1")

        return errors


# =============================================================================
# RESULTS STRUCTURE
# =============================================================================

@dataclass
class ExperimentResults:
    """Structured results from an experiment."""
    # Metadata
    experiment_id: str
    experiment_name: str
    timestamp: str
    config: Dict[str, Any]

    # Dataset info
    train_samples: int
    eval_samples: int
    train_breakout_rate: float
    eval_breakout_rate: float
    train_period: Dict[str, str]
    eval_period: Dict[str, str]

    # Core metrics
    auc_roc: float
    average_precision: float

    # Optimal threshold metrics
    optimal_threshold: float
    precision_at_optimal: float
    recall_at_optimal: float
    f1_at_optimal: float

    # Threshold analysis
    threshold_analysis: Dict[str, Dict[str, float]]

    # Feature importance
    feature_importance: Dict[str, float]

    # Model path
    model_path: str
    config_path: str

    # Recommendation
    recommendation: str
    ready_for_shadow: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def save(self, output_dir: Path = RESULTS_OUTPUT_DIR) -> str:
        """Save results to JSON file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{self.experiment_name}_{self.experiment_id}.json"
        with open(output_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        return str(output_path)


# =============================================================================
# DATA LOADING (SHARED MODE - uses shared feature module)
# =============================================================================

def load_breakout_training_data_shared(
    client: bigquery.Client,
    start: str,
    end: str,
    min_ppg: float,
    max_ppg: float,
    breakout_mult: float,
) -> pd.DataFrame:
    """
    Load training data using the shared feature module.

    This ensures consistency with production evaluation and inference.
    Uses the same query and feature computation as backfill_breakout_shadow.py
    """
    config = BreakoutFeatureConfig(
        min_ppg=min_ppg,
        max_ppg=max_ppg,
        breakout_multiplier=breakout_mult,
    )

    query = get_shared_training_query(start, end, config)
    return client.query(query).to_dataframe()


def prepare_features_shared(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Prepare features using the shared feature module.

    This ensures consistency with production evaluation and inference.
    """
    rows = []
    for _, row in df.iterrows():
        try:
            _, feature_dict = prepare_shared_feature_vector(row, validate=True)
            rows.append(feature_dict)
        except Exception as e:
            # Skip rows with invalid features
            print(f"Warning: Skipping row due to feature error: {e}")
            continue

    X = pd.DataFrame(rows, columns=BREAKOUT_FEATURE_ORDER)

    # Get corresponding labels for rows we kept
    valid_indices = [i for i, _ in enumerate(df.iterrows()) if i < len(rows)]
    y = df.iloc[:len(rows)]['is_breakout'].astype(int).reset_index(drop=True)

    return X, y


# =============================================================================
# DATA LOADING (EXPERIMENTAL MODE - flexible feature sets)
# =============================================================================

def load_breakout_training_data_experimental(
    client: bigquery.Client,
    start: str,
    end: str,
    min_ppg: float,
    max_ppg: float,
    breakout_mult: float,
    features: List[str]
) -> pd.DataFrame:
    """
    Load training data for breakout classifier with flexible feature set.

    This query:
    1. Filters to role players (season avg between min_ppg and max_ppg)
    2. Computes is_breakout label (actual >= season_avg * breakout_mult)
    3. Computes derived features as needed
    4. Joins with feature store for additional features
    """
    # Determine if we need usage/minutes trend features
    needs_usage_trend = "usage_rate_trend" in features
    needs_games_since_dnp = "games_since_dnp" in features

    # Build optional CTEs
    optional_ctes = ""
    if needs_usage_trend:
        optional_ctes += f"""
    usage_data AS (
      -- Get usage rate data for trend calculation
      SELECT
        player_lookup,
        cache_date as game_date,
        usage_rate_last_10,
        player_usage_rate_season
      FROM `{PROJECT_ID}.nba_precompute.player_daily_cache`
      WHERE cache_date BETWEEN '{start}' AND '{end}'
    ),"""

    if needs_games_since_dnp:
        optional_ctes += f"""
    dnp_data AS (
      -- Find last DNP for each player-game
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        MAX(pgs2.game_date) as last_dnp_date
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      LEFT JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs2
        ON pgs.player_lookup = pgs2.player_lookup
        AND pgs2.game_date < pgs.game_date
        AND pgs2.minutes_played = 0
      WHERE pgs.game_date BETWEEN '{start}' AND '{end}'
      GROUP BY 1, 2
    ),"""

    # Build usage trend select
    usage_trend_select = "ud.usage_rate_last_10 - ud.player_usage_rate_season as usage_rate_trend," if needs_usage_trend else "0.0 as usage_rate_trend,"

    # Build games since DNP select
    games_since_dnp_select = "COALESCE(DATE_DIFF(wbh.game_date, dd.last_dnp_date, DAY), 30) as games_since_dnp," if needs_games_since_dnp else "30.0 as games_since_dnp,"

    # Build optional joins
    optional_joins = ""
    if needs_usage_trend:
        optional_joins += "\n      LEFT JOIN usage_data ud ON wbh.player_lookup = ud.player_lookup AND wbh.game_date = ud.game_date"
    if needs_games_since_dnp:
        optional_joins += "\n      LEFT JOIN dnp_data dd ON wbh.player_lookup = dd.player_lookup AND wbh.game_date = dd.game_date"

    query = f"""
    WITH player_history AS (
      -- Get all games for players in the date range to compute derived features
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.points,
        pgs.minutes_played,
        dc.points_avg_season,
        dc.points_std_last_10,
        dc.points_avg_last_5,
        dc.points_avg_last_10,
        dc.minutes_avg_last_10,
        -- Get max points in last 5 games for explosion_ratio
        MAX(pgs2.points) OVER (
          PARTITION BY pgs.player_lookup
          ORDER BY pgs.game_date
          ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) as max_points_last_5,
        -- Mark if this game was a breakout
        CASE WHEN pgs.points >= dc.points_avg_season * {breakout_mult} THEN 1 ELSE 0 END as is_breakout_game
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      JOIN `{PROJECT_ID}.nba_precompute.player_daily_cache` dc
        ON pgs.player_lookup = dc.player_lookup AND pgs.game_date = dc.cache_date
      LEFT JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs2
        ON pgs.player_lookup = pgs2.player_lookup
        AND pgs2.game_date >= DATE_SUB(pgs.game_date, INTERVAL 30 DAY)
        AND pgs2.game_date < pgs.game_date
      WHERE pgs.game_date >= DATE_SUB(DATE('{start}'), INTERVAL 60 DAY)  -- Need history
        AND pgs.game_date <= '{end}'
        AND dc.points_avg_season BETWEEN {min_ppg} AND {max_ppg}
        AND pgs.minutes_played > 0
        AND pgs.points IS NOT NULL
    ),
    with_breakout_history AS (
      -- Compute days since last breakout for each game
      SELECT
        ph.*,
        LAG(game_date) OVER (
          PARTITION BY player_lookup, is_breakout_game
          ORDER BY game_date
        ) as last_breakout_date
      FROM player_history ph
    ),{optional_ctes}
    final_features AS (
      SELECT
        wbh.player_lookup,
        wbh.game_date,
        wbh.points as actual_points,
        wbh.points_avg_season,
        wbh.points_avg_last_10,
        wbh.minutes_played,
        wbh.minutes_avg_last_10,

        -- Target variable
        CASE WHEN wbh.points >= wbh.points_avg_season * {breakout_mult} THEN 1 ELSE 0 END as is_breakout,

        -- From daily cache
        wbh.points_std_last_10,
        wbh.points_avg_last_5,

        -- Computed features
        SAFE_DIVIDE(wbh.max_points_last_5, wbh.points_avg_season) as explosion_ratio,
        COALESCE(
          DATE_DIFF(wbh.game_date, wbh.last_breakout_date, DAY),
          30  -- Default if no prior breakout
        ) as days_since_breakout,

        -- CV ratio (Session 126 - strongest predictor)
        SAFE_DIVIDE(wbh.points_std_last_10, wbh.points_avg_season) as cv_ratio,

        -- Cold streak indicator (L5 < L10 * 0.8)
        CASE WHEN wbh.points_avg_last_5 < wbh.points_avg_last_10 * 0.8 THEN 1.0 ELSE 0.0 END as cold_streak_indicator,

        -- Usage rate trend
        {usage_trend_select}

        -- Minutes trend (L10 vs season proxy using avg)
        COALESCE(wbh.minutes_avg_last_10, 25.0) - 25.0 as minutes_trend,

        -- Games since DNP
        {games_since_dnp_select}

        -- From feature store (will join)
        mf.features,
        mf.feature_names

      FROM with_breakout_history wbh
      JOIN `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        ON wbh.player_lookup = mf.player_lookup AND wbh.game_date = mf.game_date{optional_joins}
      WHERE wbh.game_date BETWEEN '{start}' AND '{end}'
        AND mf.feature_count >= 33
        AND wbh.is_breakout_game IS NOT NULL
        -- Session 157: Uses shared.ml.training_data_loader quality clause
        AND {_get_quality_clause()}
    )
    SELECT DISTINCT
      player_lookup,
      game_date,
      actual_points,
      points_avg_season,
      points_avg_last_10,
      minutes_played,
      minutes_avg_last_10,
      is_breakout,
      points_std_last_10,
      points_avg_last_5,
      explosion_ratio,
      days_since_breakout,
      cv_ratio,
      cold_streak_indicator,
      usage_rate_trend,
      minutes_trend,
      games_since_dnp,
      features,
      feature_names
    FROM final_features
    WHERE explosion_ratio IS NOT NULL  -- Must have L5 history
    ORDER BY game_date, player_lookup
    """
    return client.query(query).to_dataframe()


def extract_feature_from_store(
    features: List[float],
    feature_names: List[str],
    target_name: str,
    default: float = None
) -> float:
    """Extract a single feature from the feature store arrays."""
    if target_name in feature_names:
        idx = feature_names.index(target_name)
        if idx < len(features) and features[idx] is not None:
            return float(features[idx])
    return default


def prepare_features_experimental(
    df: pd.DataFrame,
    feature_list: List[str]
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Prepare feature matrix for breakout classifier (EXPERIMENTAL MODE).

    Combines:
    - Computed features from query
    - Features extracted from feature store

    For production, use prepare_features_shared() instead.
    """
    rows = []
    for _, row in df.iterrows():
        feature_values = row['features']
        feature_names = list(row['feature_names'])

        feature_dict = {}
        for feat_name in feature_list:
            feat_def = AVAILABLE_FEATURES[feat_name]

            if feat_def.source == "query" or feat_def.source == "computed":
                # Get from query results
                if feat_name in row.index and row[feat_name] is not None:
                    feature_dict[feat_name] = float(row[feat_name])
                else:
                    feature_dict[feat_name] = feat_def.default

            elif feat_def.source == "feature_store":
                # Extract from feature store
                store_name = feat_def.feature_store_name or feat_name
                value = extract_feature_from_store(
                    feature_values, feature_names, store_name, feat_def.default
                )
                feature_dict[feat_name] = value if value is not None else feat_def.default

        rows.append(feature_dict)

    X = pd.DataFrame(rows, columns=feature_list)

    # Handle missing values
    X = X.fillna(X.median())

    # Replace any inf values
    X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())

    y = df['is_breakout'].astype(int)

    return X, y


# =============================================================================
# MODEL TRAINING
# =============================================================================

def compute_class_weight(y: pd.Series) -> float:
    """Compute scale_pos_weight for imbalanced classes."""
    n_neg = (y == 0).sum()
    n_pos = (y == 1).sum()
    if n_pos == 0:
        return 1.0
    return n_neg / n_pos


def find_optimal_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    target_precision: float = 0.60
) -> Dict[str, float]:
    """
    Find optimal probability threshold for deployment.

    For betting, we want high precision (fewer false positives) at acceptable recall.
    Returns threshold that achieves target precision, or best available.
    """
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_prob)

    # Find threshold achieving target precision
    for i, (p, r, t) in enumerate(zip(precisions, recalls, thresholds)):
        if p >= target_precision:
            return {
                'threshold': float(t),
                'precision': float(p),
                'recall': float(r),
                'f1': 2 * p * r / (p + r) if (p + r) > 0 else 0
            }

    # Fallback: return threshold with best F1
    f1_scores = 2 * precisions * recalls / (precisions + recalls + 1e-10)
    best_idx = np.argmax(f1_scores[:-1])  # Exclude last (precision=1, recall=0)
    return {
        'threshold': float(thresholds[best_idx]),
        'precision': float(precisions[best_idx]),
        'recall': float(recalls[best_idx]),
        'f1': float(f1_scores[best_idx])
    }


def analyze_thresholds(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    thresholds: List[float] = None
) -> Dict[str, Dict[str, float]]:
    """Analyze model performance at different thresholds."""
    if thresholds is None:
        thresholds = [0.3, 0.4, 0.5, 0.6, 0.7]

    results = {}
    for thresh in thresholds:
        preds = (y_prob >= thresh).astype(int)
        tp = ((preds == 1) & (y_true == 1)).sum()
        fp = ((preds == 1) & (y_true == 0)).sum()
        fn = ((preds == 0) & (y_true == 1)).sum()
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        n_flagged = preds.sum()

        results[f"thresh_{thresh}"] = {
            'threshold': thresh,
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'f1': round(f1, 4),
            'n_flagged': int(n_flagged),
            'pct_flagged': round(n_flagged / len(y_true) * 100, 2)
        }

    return results


# =============================================================================
# MAIN EXPERIMENT RUNNER
# =============================================================================

def run_experiment(config: ExperimentConfig) -> Optional[ExperimentResults]:
    """Run a breakout classifier experiment with given configuration."""
    exp_id = str(uuid.uuid4())[:8]

    # Compute date ranges
    if config.train_start and config.train_end and config.eval_start and config.eval_end:
        dates = {
            'train_start': config.train_start,
            'train_end': config.train_end,
            'eval_start': config.eval_start,
            'eval_end': config.eval_end,
        }
    else:
        yesterday = date.today() - timedelta(days=1)
        eval_end = yesterday
        eval_start = eval_end - timedelta(days=config.eval_days - 1)
        train_end = eval_start - timedelta(days=1)
        train_start = train_end - timedelta(days=config.train_days - 1)

        dates = {
            'train_start': train_start.strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'eval_start': eval_start.strftime('%Y-%m-%d'),
            'eval_end': eval_end.strftime('%Y-%m-%d'),
        }

    # Calculate actual day counts
    train_start_dt = datetime.strptime(dates['train_start'], '%Y-%m-%d').date()
    train_end_dt = datetime.strptime(dates['train_end'], '%Y-%m-%d').date()
    eval_start_dt = datetime.strptime(dates['eval_start'], '%Y-%m-%d').date()
    eval_end_dt = datetime.strptime(dates['eval_end'], '%Y-%m-%d').date()
    train_days_actual = (train_end_dt - train_start_dt).days + 1
    eval_days_actual = (eval_end_dt - eval_start_dt).days + 1

    print("=" * 70)
    print(f" BREAKOUT EXPERIMENT: {config.name}")
    print("=" * 70)
    print(f"Experiment ID: {exp_id}")
    print(f"Mode: {config.mode.upper()}")
    if config.mode == "shared":
        print("  Using ml/features/breakout_features.py (production consistency)")
    else:
        print("  Using experimental feature pipeline (research mode)")
    print(f"Training:   {dates['train_start']} to {dates['train_end']} ({train_days_actual} days)")
    print(f"Evaluation: {dates['eval_start']} to {dates['eval_end']} ({eval_days_actual} days)")
    print()
    print(f"Target: Role players ({config.min_ppg}-{config.max_ppg} PPG season avg)")
    print(f"Breakout: >= {config.breakout_multiplier}x season average")
    print()
    print(f"Features ({len(config.feature_set)}):")
    for f in config.feature_set:
        if config.mode == "shared":
            # In shared mode, show defaults from shared module
            default = FEATURE_DEFAULTS.get(f, "N/A")
            print(f"  - {f} (default: {default})")
        else:
            # In experimental mode, show from registry
            feat_def = AVAILABLE_FEATURES.get(f)
            if feat_def:
                print(f"  - {f}: {feat_def.description}")
            else:
                print(f"  - {f}: (UNKNOWN)")
    print()
    print(f"Hyperparameters:")
    print(f"  depth={config.depth}, iterations={config.iterations}, "
          f"lr={config.learning_rate}, l2={config.l2_reg}")
    print()

    if config.dry_run:
        print("DRY RUN - would train breakout classifier with above configuration")
        return None

    # Validate config
    errors = config.validate()
    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        return None

    client = bigquery.Client(project=PROJECT_ID)

    # Load training data based on mode
    print("Loading training data...")
    if config.mode == "shared":
        df_train = load_breakout_training_data_shared(
            client, dates['train_start'], dates['train_end'],
            config.min_ppg, config.max_ppg, config.breakout_multiplier
        )
    else:
        df_train = load_breakout_training_data_experimental(
            client, dates['train_start'], dates['train_end'],
            config.min_ppg, config.max_ppg, config.breakout_multiplier,
            config.feature_set
        )
    print(f"  {len(df_train):,} samples")

    # Load evaluation data based on mode
    print("Loading evaluation data...")
    if config.mode == "shared":
        df_eval = load_breakout_training_data_shared(
            client, dates['eval_start'], dates['eval_end'],
            config.min_ppg, config.max_ppg, config.breakout_multiplier
        )
    else:
        df_eval = load_breakout_training_data_experimental(
            client, dates['eval_start'], dates['eval_end'],
            config.min_ppg, config.max_ppg, config.breakout_multiplier,
            config.feature_set
        )
    print(f"  {len(df_eval):,} samples")

    if len(df_train) < 500:
        print("ERROR: Not enough training data (need 500+)")
        return None

    if len(df_eval) < 50:
        print("WARNING: Limited evaluation data (have {}, recommend 100+)".format(len(df_eval)))

    # Check class distribution
    train_breakout_rate = df_train['is_breakout'].mean()
    eval_breakout_rate = df_eval['is_breakout'].mean() if len(df_eval) > 0 else 0

    print(f"\nClass distribution:")
    print(f"  Training: {train_breakout_rate*100:.1f}% breakouts ({df_train['is_breakout'].sum()} of {len(df_train)})")
    print(f"  Eval:     {eval_breakout_rate*100:.1f}% breakouts ({df_eval['is_breakout'].sum()} of {len(df_eval)})")

    # Prepare features based on mode
    if config.mode == "shared":
        print("\nPreparing features using shared module...")
        X_train_full, y_train_full = prepare_features_shared(df_train)
        X_eval, y_eval = prepare_features_shared(df_eval)
    else:
        print("\nPreparing features using experimental pipeline...")
        X_train_full, y_train_full = prepare_features_experimental(df_train, config.feature_set)
        X_eval, y_eval = prepare_features_experimental(df_eval, config.feature_set)

    # Split training into train/validation
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_full, y_train_full, test_size=0.15, random_state=42, stratify=y_train_full
    )

    print(f"\nDataset sizes:")
    print(f"  Train: {len(X_train):,} | Val: {len(X_val):,} | Eval: {len(X_eval):,}")

    # Compute class weight for imbalance
    class_weight = compute_class_weight(y_train)
    print(f"  Class weight (scale_pos_weight): {class_weight:.2f}")

    # Train CatBoost classifier
    print("\nTraining CatBoost classifier...")
    model = cb.CatBoostClassifier(
        iterations=config.iterations,
        learning_rate=config.learning_rate,
        depth=config.depth,
        l2_leaf_reg=config.l2_reg,
        scale_pos_weight=class_weight,
        random_seed=42,
        verbose=100,
        early_stopping_rounds=config.early_stopping_rounds,
        eval_metric='AUC',
    )

    model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        verbose=100
    )

    # Evaluate
    print("\n" + "=" * 70)
    print(" EVALUATION RESULTS")
    print("=" * 70)

    # Predictions
    eval_probs = model.predict_proba(X_eval)[:, 1]

    # Core metrics
    eval_auc = roc_auc_score(y_eval, eval_probs) if y_eval.sum() > 0 else 0
    eval_ap = average_precision_score(y_eval, eval_probs) if y_eval.sum() > 0 else 0

    print(f"\nCore Metrics:")
    print(f"  AUC-ROC: {eval_auc:.4f}")
    print(f"  Average Precision: {eval_ap:.4f}")

    # Find optimal threshold
    optimal = find_optimal_threshold(y_eval, eval_probs, config.target_precision)
    print(f"\nOptimal Threshold (target {config.target_precision*100:.0f}% precision):")
    print(f"  Threshold: {optimal['threshold']:.3f}")
    print(f"  Precision: {optimal['precision']*100:.1f}%")
    print(f"  Recall: {optimal['recall']*100:.1f}%")
    print(f"  F1: {optimal['f1']:.3f}")

    # Threshold analysis
    threshold_analysis = analyze_thresholds(y_eval.values, eval_probs)
    print(f"\nThreshold Analysis:")
    for key, metrics in threshold_analysis.items():
        print(f"  {metrics['threshold']:.1f}: Precision={metrics['precision']*100:.1f}%, "
              f"Recall={metrics['recall']*100:.1f}%, Flagged={metrics['n_flagged']}")

    # Feature importance
    importance = dict(zip(config.feature_set, model.feature_importances_))
    print(f"\nFeature Importance:")
    for feat, imp in sorted(importance.items(), key=lambda x: -x[1]):
        print(f"  {feat}: {imp:.4f}")

    # Classification report at optimal threshold
    eval_preds = (eval_probs >= optimal['threshold']).astype(int)
    print(f"\nClassification Report (threshold={optimal['threshold']:.3f}):")
    print(classification_report(y_eval, eval_preds, target_names=['No Breakout', 'Breakout']))

    # Save model
    MODEL_OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_path = MODEL_OUTPUT_DIR / f"breakout_exp_{config.name}_{ts}.cbm"
    model.save_model(str(model_path))

    # Save config
    config_path = MODEL_OUTPUT_DIR / f"breakout_exp_{config.name}_{ts}_config.json"
    with open(config_path, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)

    print(f"\nModel saved: {model_path}")
    print(f"Config saved: {config_path}")

    # Recommendation
    print("\n" + "-" * 40)
    print("RECOMMENDATION")
    print("-" * 40)

    ready_for_shadow = False
    if eval_auc >= 0.65 and optimal['precision'] >= 0.55:
        recommendation = "READY FOR SHADOW MODE"
        ready_for_shadow = True
        print(f"  - Use threshold {optimal['threshold']:.3f} for {optimal['precision']*100:.1f}% precision")
        print(f"  - Will flag ~{(eval_probs >= optimal['threshold']).mean()*100:.1f}% of role player games")
    elif eval_auc >= 0.60:
        recommendation = "MARGINAL PERFORMANCE"
        print(f"  - AUC ({eval_auc:.3f}) is acceptable but not strong")
        print("  - Consider more training data or feature engineering")
    else:
        recommendation = "NEEDS IMPROVEMENT"
        print(f"  - AUC ({eval_auc:.3f}) below 0.60 threshold")
        print("  - Try different features or larger training window")

    # Build results
    results = ExperimentResults(
        experiment_id=exp_id,
        experiment_name=config.name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        config=config.to_dict(),
        train_samples=len(df_train),
        eval_samples=len(df_eval),
        train_breakout_rate=round(train_breakout_rate, 4),
        eval_breakout_rate=round(eval_breakout_rate, 4),
        train_period={'start': dates['train_start'], 'end': dates['train_end']},
        eval_period={'start': dates['eval_start'], 'end': dates['eval_end']},
        auc_roc=round(eval_auc, 4),
        average_precision=round(eval_ap, 4),
        optimal_threshold=round(optimal['threshold'], 3),
        precision_at_optimal=round(optimal['precision'], 4),
        recall_at_optimal=round(optimal['recall'], 4),
        f1_at_optimal=round(optimal['f1'], 4),
        threshold_analysis=threshold_analysis,
        feature_importance={k: round(v, 4) for k, v in importance.items()},
        model_path=str(model_path),
        config_path=str(config_path),
        recommendation=recommendation,
        ready_for_shadow=ready_for_shadow,
    )

    # Save results
    results_path = results.save()
    print(f"\nResults saved: {results_path}")

    # Register experiment
    if not config.skip_register:
        try:
            row = {
                'experiment_id': exp_id,
                'experiment_name': config.name,
                'experiment_type': 'breakout_classifier_experiment',
                'hypothesis': config.hypothesis or f'Breakout classifier with {len(config.feature_set)} features',
                'config_json': json.dumps(config.to_dict()),
                'train_period': {
                    'start_date': dates['train_start'],
                    'end_date': dates['train_end'],
                    'samples': len(df_train)
                },
                'eval_period': {
                    'start_date': dates['eval_start'],
                    'end_date': dates['eval_end'],
                    'samples': len(df_eval)
                },
                'results_json': json.dumps({
                    'auc': round(eval_auc, 4),
                    'average_precision': round(eval_ap, 4),
                    'optimal_threshold': round(optimal['threshold'], 3),
                    'precision_at_optimal': round(optimal['precision'], 4),
                    'recall_at_optimal': round(optimal['recall'], 4),
                    'train_breakout_rate': round(train_breakout_rate, 4),
                    'eval_breakout_rate': round(eval_breakout_rate, 4),
                    'feature_importance': {k: round(v, 4) for k, v in importance.items()},
                    'ready_for_shadow': ready_for_shadow,
                }),
                'model_path': str(model_path),
                'status': 'completed',
                'tags': config.tags,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }
            errors = client.insert_rows_json(f"{PROJECT_ID}.nba_predictions.ml_experiments", [row])
            if not errors:
                print(f"\nRegistered in ml_experiments (ID: {exp_id})")
        except Exception as e:
            print(f"Warning: Could not register: {e}")

    return results


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='Run breakout classifier experiments',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # SHARED MODE (recommended for production models)
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \\
        --name "PROD_V2" --mode shared

    # EXPERIMENTAL MODE (for feature research)
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \\
        --name "EXP_CV_RATIO" --mode experimental \\
        --features "cv_ratio,cold_streak_indicator,pts_vs_season_zscore" \\
        --depth 6 --iterations 300

    # With config file
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py --config config.json

    # List available features
    PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py --list-features
        """
    )

    # Config file option
    parser.add_argument('--config', help='Path to JSON config file')

    # List features option
    parser.add_argument('--list-features', action='store_true',
                        help='List all available features and exit')

    # Experiment metadata
    parser.add_argument('--name', help='Experiment name (required without --config)')
    parser.add_argument('--hypothesis', default='', help='What we are testing')
    parser.add_argument('--tags', default='breakout,classifier,experiment',
                        help='Comma-separated tags')

    # Mode configuration
    parser.add_argument('--mode', default='shared', choices=['shared', 'experimental'],
                        help='Mode: "shared" (production features, default) or "experimental" (custom features)')

    # Feature configuration (experimental mode only)
    parser.add_argument('--features', help='Comma-separated feature list (experimental mode only, ignored in shared mode)')

    # Hyperparameters
    parser.add_argument('--depth', type=int, default=5, help='Tree depth (default: 5)')
    parser.add_argument('--iterations', type=int, default=500, help='Max iterations (default: 500)')
    parser.add_argument('--learning-rate', type=float, default=0.05, help='Learning rate (default: 0.05)')
    parser.add_argument('--l2-reg', type=float, default=3.0, help='L2 regularization (default: 3.0)')
    parser.add_argument('--early-stopping', type=int, default=30, help='Early stopping rounds (default: 30)')

    # Target definition
    parser.add_argument('--min-ppg', type=float, default=8.0,
                        help='Min season PPG for role player (default: 8)')
    parser.add_argument('--max-ppg', type=float, default=16.0,
                        help='Max season PPG for role player (default: 16)')
    parser.add_argument('--breakout-multiplier', type=float, default=1.5,
                        help='Breakout threshold multiplier (default: 1.5x season avg)')
    parser.add_argument('--target-precision', type=float, default=0.60,
                        help='Target precision for optimal threshold (default: 0.60)')

    # Date ranges
    parser.add_argument('--train-start', help='Training start (YYYY-MM-DD)')
    parser.add_argument('--train-end', help='Training end (YYYY-MM-DD)')
    parser.add_argument('--eval-start', help='Eval start (YYYY-MM-DD)')
    parser.add_argument('--eval-end', help='Eval end (YYYY-MM-DD)')
    parser.add_argument('--train-days', type=int, default=60, help='Days of training (default: 60)')
    parser.add_argument('--eval-days', type=int, default=7, help='Days of eval (default: 7)')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Show plan only')
    parser.add_argument('--skip-register', action='store_true', help='Skip ml_experiments registration')

    return parser.parse_args()


def list_features():
    """Print all available features with descriptions."""
    print("=" * 70)
    print(" AVAILABLE FEATURES FOR BREAKOUT CLASSIFIER")
    print("=" * 70)
    print()

    # Group by source
    by_source = {}
    for name, feat in AVAILABLE_FEATURES.items():
        if feat.source not in by_source:
            by_source[feat.source] = []
        by_source[feat.source].append((name, feat))

    for source in ['query', 'computed', 'feature_store']:
        if source in by_source:
            print(f"Source: {source.upper()}")
            print("-" * 40)
            for name, feat in sorted(by_source[source]):
                print(f"  {name}")
                print(f"    {feat.description}")
                print(f"    Default: {feat.default}")
                print()
            print()

    print("=" * 70)
    print(" PRESET FEATURE SETS")
    print("=" * 70)
    print()
    print("DEFAULT_FEATURES (original train_breakout_classifier.py):")
    for f in DEFAULT_FEATURES:
        print(f"  - {f}")
    print()
    print("ENHANCED_FEATURES (with Session 126 discoveries):")
    for f in ENHANCED_FEATURES:
        marker = " (NEW)" if f not in DEFAULT_FEATURES else ""
        print(f"  - {f}{marker}")


def main():
    args = parse_args()

    # Handle --list-features
    if args.list_features:
        list_features()
        return

    # Load config from file or args
    if args.config:
        config = ExperimentConfig.from_json(args.config)
        # Allow command-line flags to override config file
        if args.dry_run:
            config.dry_run = True
        if args.skip_register:
            config.skip_register = True
    elif args.name:
        config = ExperimentConfig.from_args(args)
    else:
        print("ERROR: Either --config or --name is required")
        print("Run with --help for usage information")
        return

    # Run experiment
    results = run_experiment(config)

    if results:
        print("\n" + "=" * 70)
        print(" EXPERIMENT COMPLETE")
        print("=" * 70)
        print(f"ID: {results.experiment_id}")
        print(f"AUC: {results.auc_roc}")
        print(f"Precision: {results.precision_at_optimal*100:.1f}%")
        print(f"Recommendation: {results.recommendation}")


if __name__ == "__main__":
    main()
