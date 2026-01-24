# predictions/mlb/base_predictor.py
"""
Base MLB Predictor Abstract Class

Abstract base class for all MLB prediction systems. Provides shared logic
for confidence calculation, red flags, recommendations, and feature preparation.

Each prediction system (V1, V1.6, ensemble, etc.) inherits from this class
and implements the abstract predict() method with its own model logic.

Usage:
    class MyPredictor(BaseMLBPredictor):
        def __init__(self, model_path: str, **kwargs):
            super().__init__(system_id='my_system', **kwargs)
            self.model_path = model_path

        def predict(self, pitcher_lookup: str, features: Dict, strikeouts_line: Optional[float] = None) -> Dict:
            # Custom prediction logic
            ...
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime, timedelta
import numpy as np

from predictions.mlb.config import get_config

logger = logging.getLogger(__name__)


class RedFlagResult:
    """Result of red flag evaluation"""
    def __init__(
        self,
        skip_bet: bool = False,
        confidence_multiplier: float = 1.0,
        flags: list = None,
        skip_reason: str = None
    ):
        self.skip_bet = skip_bet
        self.confidence_multiplier = confidence_multiplier
        self.flags = flags or []
        self.skip_reason = skip_reason


class BaseMLBPredictor(ABC):
    """
    Abstract base class for MLB pitcher strikeout predictors.

    Provides shared logic for:
    - Confidence calculation based on data quality
    - Red flag checking (IL status, first start, low IP, etc.)
    - Recommendation generation (OVER/UNDER/PASS)
    - BigQuery client management

    Subclasses must implement:
    - predict(): Generate prediction for a pitcher
    """

    # Class-level cache for IL status (shared across all predictor instances)
    _il_cache = None
    _il_cache_timestamp = None

    def __init__(
        self,
        system_id: str,
        project_id: str = None
    ):
        """
        Initialize base predictor

        Args:
            system_id: Unique identifier for this prediction system (e.g., 'v1_baseline', 'v1_6_rolling')
            project_id: GCP project ID
        """
        self.system_id = system_id
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self._bq_client = None

    def _get_bq_client(self):
        """Lazy-load BigQuery client"""
        if self._bq_client is None:
            from google.cloud import bigquery
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    def _get_current_il_pitchers(self) -> set:
        """
        Get set of pitcher_lookup values currently on IL.

        Caches result based on config TTL to avoid repeated queries.
        Uses retry logic with exponential backoff for BigQuery failures.

        Safety: On BigQuery failure after retries, returns empty set (no skips)
        rather than stale cache to avoid missing recently recovered pitchers.

        Returns:
            set: pitcher_lookup values on IL
        """
        config = get_config()
        cache_ttl_hours = config.cache.il_cache_ttl_hours
        now = datetime.now()

        # Return cached if within TTL
        if (BaseMLBPredictor._il_cache is not None and
            BaseMLBPredictor._il_cache_timestamp is not None):
            cache_age = now - BaseMLBPredictor._il_cache_timestamp
            if cache_age < timedelta(hours=cache_ttl_hours):
                logger.debug(f"IL cache hit (age: {cache_age})")
                return BaseMLBPredictor._il_cache

        # Query with retry logic (3 attempts with exponential backoff)
        client = self._get_bq_client()
        query = """
        SELECT DISTINCT REPLACE(player_lookup, '_', '') as player_lookup
        FROM `nba-props-platform.mlb_raw.bdl_injuries`
        WHERE snapshot_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND is_pitcher = TRUE
          AND injury_status IN ('10-Day-IL', '15-Day-IL', '60-Day-IL', 'Out')
        """

        max_retries = 3
        base_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                result = client.query(query).result()
                il_pitchers = {row.player_lookup for row in result}

                # Cache result with timestamp
                BaseMLBPredictor._il_cache = il_pitchers
                BaseMLBPredictor._il_cache_timestamp = now

                logger.info(f"Loaded {len(il_pitchers)} pitchers on IL (cache refreshed)")
                return il_pitchers

            except Exception as e:
                if attempt < max_retries - 1:
                    # Exponential backoff
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"IL query failed (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {e}")
                    import time
                    time.sleep(delay)
                else:
                    # Final attempt failed
                    cache_age_hours = ((now - BaseMLBPredictor._il_cache_timestamp).total_seconds() / 3600
                                      if BaseMLBPredictor._il_cache_timestamp else None)

                    logger.error(
                        f"IL query failed after {max_retries} attempts: {e}",
                        extra={
                            "error_type": type(e).__name__,
                            "cache_age_hours": cache_age_hours,
                            "fallback_action": "return_empty_set"
                        },
                        exc_info=True
                    )

                    # FAIL SAFE: Return empty set (no IL skips) rather than stale cache
                    # This is safer - we'd rather NOT skip a pitcher than skip them
                    # based on outdated IL status
                    return set()

    def _calculate_confidence(self, features: Dict, feature_vector: np.ndarray = None) -> float:
        """
        Calculate confidence score based on data quality

        Args:
            features: Raw feature dict
            feature_vector: Prepared feature vector (optional)

        Returns:
            float: Confidence score (0-100)
        """
        confidence = 70.0  # Base ML confidence

        # Data completeness adjustment
        completeness = features.get('data_completeness_score', 80)
        if completeness >= 90:
            confidence += 15
        elif completeness >= 80:
            confidence += 10
        elif completeness >= 70:
            confidence += 5
        elif completeness >= 50:
            confidence += 0
        else:
            confidence -= 10

        # Rolling stats games adjustment
        rolling_games = features.get('rolling_stats_games', 0)
        if rolling_games >= 10:
            confidence += 10
        elif rolling_games >= 5:
            confidence += 5
        elif rolling_games >= 3:
            confidence += 0
        else:
            confidence -= 10

        # Consistency adjustment (lower K std = more predictable)
        k_std = features.get('k_std_last_10', 3.0)
        if k_std < 2:
            confidence += 5
        elif k_std < 3:
            confidence += 2
        elif k_std > 4:
            confidence -= 5

        return max(0, min(100, confidence))

    def _calculate_feature_coverage(self, features: Dict, required_features: list) -> tuple:
        """
        Calculate feature coverage percentage for a prediction.

        Feature coverage measures what percentage of expected features are present
        (non-null). This helps detect low-data scenarios where predictions may be
        unreliable due to missing features.

        Args:
            features: Feature dict from pitcher_game_summary
            required_features: List of feature names expected by the model

        Returns:
            tuple: (coverage_pct, missing_features)
                - coverage_pct: Percentage of features with non-null values (0-100)
                - missing_features: List of feature names that are null/missing
        """
        if not required_features:
            # If no required features list, can't calculate coverage
            return 100.0, []

        total_features = len(required_features)
        present_features = 0
        missing_features = []

        for feature in required_features:
            value = features.get(feature)
            # Check if value is present and not null/None
            if value is not None and not (isinstance(value, float) and np.isnan(value)):
                present_features += 1
            else:
                missing_features.append(feature)

        coverage_pct = (present_features / total_features) * 100 if total_features > 0 else 100.0

        return coverage_pct, missing_features

    def _adjust_confidence_for_coverage(self, confidence: float, coverage_pct: float) -> float:
        """
        Adjust confidence score based on feature coverage.

        Low feature coverage indicates missing data, which reduces prediction reliability.
        This method applies graduated confidence penalties based on coverage level.

        Coverage thresholds and penalties:
        - >= 90%: No reduction (full confidence)
        - 80-89%: -5 confidence points
        - 70-79%: -10 confidence points
        - 60-69%: -15 confidence points
        - < 60%: -25 confidence points (severe data gaps)

        Args:
            confidence: Base confidence score (0-100)
            coverage_pct: Feature coverage percentage (0-100)

        Returns:
            float: Adjusted confidence score (0-100)
        """
        if coverage_pct >= 90:
            # Excellent coverage - no reduction
            penalty = 0
        elif coverage_pct >= 80:
            # Good coverage - minor reduction
            penalty = 5
        elif coverage_pct >= 70:
            # Acceptable coverage - moderate reduction
            penalty = 10
        elif coverage_pct >= 60:
            # Poor coverage - significant reduction
            penalty = 15
        else:
            # Very poor coverage - severe reduction
            penalty = 25

        adjusted_confidence = confidence - penalty
        return max(0, min(100, adjusted_confidence))

    def _generate_recommendation(
        self,
        predicted_strikeouts: float,
        strikeouts_line: Optional[float],
        confidence: float
    ) -> str:
        """
        Generate betting recommendation

        Args:
            predicted_strikeouts: Model prediction
            strikeouts_line: Betting line
            confidence: Confidence score

        Returns:
            str: 'OVER', 'UNDER', 'PASS', or 'NO_LINE'
        """
        if strikeouts_line is None:
            return 'NO_LINE'

        config = get_config().prediction

        if confidence < config.min_confidence:
            return 'PASS'

        edge = predicted_strikeouts - strikeouts_line

        if edge >= config.min_edge:
            return 'OVER'
        elif edge <= -config.min_edge:
            return 'UNDER'
        else:
            return 'PASS'

    def _check_red_flags(
        self,
        features: Dict,
        recommendation: str = None
    ) -> RedFlagResult:
        """
        Check for red flags that should skip or reduce confidence in a bet.

        RED FLAG SYSTEM v1.0
        ====================

        HARD SKIP (do not bet):
        - Currently on IL: Pitcher shouldn't have props but check anyway
        - First start of season: No historical data, unpredictable
        - Very low IP avg (<4.0): Likely bullpen game or opener
        - MLB debut (career starts < 3): Too little data

        SOFT REDUCE (reduce confidence):
        - Early season (starts < 3): Limited recent data → 0.7x
        - Very inconsistent (k_std > 4): High variance → varies by direction
        - Short rest (<4 days): Fatigue risk for OVER → 0.7x on OVER
        - High recent workload (>6 games/30d): Fatigue → 0.85x on OVER
        - SwStr% signals: Elite/low levels affect OVER/UNDER differently
        - SwStr% trend: Hot/cold streaks affect direction

        Args:
            features: Feature dict from pitcher_game_summary
            recommendation: 'OVER' or 'UNDER' (affects some rules)

        Returns:
            RedFlagResult with skip_bet, confidence_multiplier, flags
        """
        flags = []
        skip_bet = False
        skip_reason = None
        confidence_multiplier = 1.0

        # =============================================================
        # HARD SKIP RULES
        # =============================================================

        # 0. Currently on IL - shouldn't have props but check anyway
        pitcher_lookup = features.get('player_lookup', '')
        # Normalize name format (remove underscores for matching)
        pitcher_normalized = pitcher_lookup.replace('_', '').lower()
        il_pitchers = self._get_current_il_pitchers()
        if pitcher_normalized in il_pitchers:
            skip_bet = True
            skip_reason = "Pitcher currently on IL"
            flags.append("SKIP: Currently on IL")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # Load red flag configuration
        rf = get_config().red_flags

        # 1. First start of season - no data to predict with
        is_first_start = features.get('is_first_start', False)
        season_games = features.get('season_games_started', 0)

        if is_first_start or season_games == 0:
            skip_bet = True
            skip_reason = "First start of season - no historical data"
            flags.append("SKIP: First start of season")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # 2. Very low IP average - likely bullpen/opener
        ip_avg = features.get('ip_avg_last_5', 5.5)
        if ip_avg is not None and ip_avg < rf.min_ip_avg:
            skip_bet = True
            skip_reason = f"Low IP avg ({ip_avg:.1f}) - likely bullpen/opener"
            flags.append(f"SKIP: Low IP avg ({ip_avg:.1f})")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # 3. MLB debut / very few career starts
        rolling_games = features.get('rolling_stats_games', 0)
        if rolling_games is not None and rolling_games < rf.min_career_starts:
            skip_bet = True
            skip_reason = f"Only {rolling_games} career starts - too little data"
            flags.append(f"SKIP: Only {rolling_games} career starts")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # =============================================================
        # SOFT REDUCE RULES (cumulative)
        # =============================================================

        # 4. Early season (limited starts)
        if season_games < rf.early_season_starts:
            confidence_multiplier *= rf.early_season_multiplier
            flags.append(f"REDUCE: Early season ({season_games} starts)")

        # 5. Very inconsistent pitcher (high K std dev)
        # BACKTEST FINDING: k_std > 4 → 34.4% OVER hit rate vs 62.5% UNDER!
        k_std = features.get('k_std_last_10', 2.0)
        if k_std is not None:
            if k_std > rf.high_variance_k_std:
                if recommendation == 'OVER':
                    confidence_multiplier *= rf.high_variance_over_multiplier
                    flags.append(f"REDUCE: High variance ({k_std:.1f}) strongly favors UNDER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= rf.high_variance_under_multiplier
                    flags.append(f"BOOST: High variance ({k_std:.1f}) favors UNDER")

        # 6. Short rest (affects OVER bets more)
        days_rest = features.get('days_rest', 5)
        if days_rest is not None and days_rest < rf.short_rest_days and recommendation == 'OVER':
            confidence_multiplier *= rf.short_rest_over_multiplier
            flags.append(f"REDUCE: Short rest ({days_rest}d) for OVER bet")

        # 7. High recent workload (affects OVER bets)
        games_30d = features.get('games_last_30_days', 5)
        if games_30d is not None and games_30d > rf.high_workload_games and recommendation == 'OVER':
            confidence_multiplier *= rf.high_workload_over_multiplier
            flags.append(f"REDUCE: High workload ({games_30d} games in 30d)")

        # 8. SwStr% directional signal (BACKTEST VALIDATED)
        # high_swstr (>12%): 55.8% OVER vs 41.1% UNDER → Lean OVER
        # low_swstr (<8%): 47.5% OVER vs 49.7% UNDER → Lean UNDER
        swstr = features.get('season_swstr_pct')
        if swstr is not None:
            if swstr > rf.elite_swstr_pct:
                # Elite stuff - favors OVER
                if recommendation == 'OVER':
                    confidence_multiplier *= rf.elite_swstr_over_multiplier
                    flags.append(f"BOOST: Elite SwStr% ({swstr:.1%}) favors OVER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= rf.elite_swstr_under_multiplier
                    flags.append(f"REDUCE: Elite SwStr% ({swstr:.1%}) - avoid UNDER")
            elif swstr < rf.low_swstr_pct:
                # Weak stuff - favors UNDER
                if recommendation == 'OVER':
                    confidence_multiplier *= rf.low_swstr_over_multiplier
                    flags.append(f"REDUCE: Low SwStr% ({swstr:.1%}) - lean UNDER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= rf.low_swstr_under_multiplier
                    flags.append(f"SLIGHT BOOST: Low SwStr% ({swstr:.1%})")

        # 9. SwStr% Trend Signal (BACKTEST VALIDATED - Session 57)
        # Hot streak (+3%): 54.6% OVER hit rate (381 games) → Lean OVER
        # Cold streak (-3%): 49.8% UNDER hit rate (315 games) → Lean UNDER
        swstr_trend = features.get('swstr_trend')  # recent_swstr - season_swstr
        if swstr_trend is not None:
            if swstr_trend > rf.hot_streak_trend:
                # Hot streak - recent SwStr% above season baseline
                if recommendation == 'OVER':
                    confidence_multiplier *= rf.hot_streak_over_multiplier
                    flags.append(f"BOOST: Hot streak (SwStr% +{swstr_trend:.1%}) favors OVER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= rf.hot_streak_under_multiplier
                    flags.append(f"REDUCE: Hot streak (SwStr% +{swstr_trend:.1%}) - avoid UNDER")
            elif swstr_trend < rf.cold_streak_trend:
                # Cold streak - recent SwStr% below season baseline
                if recommendation == 'OVER':
                    confidence_multiplier *= rf.cold_streak_over_multiplier
                    flags.append(f"REDUCE: Cold streak (SwStr% {swstr_trend:.1%}) - lean UNDER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= rf.cold_streak_under_multiplier
                    flags.append(f"SLIGHT BOOST: Cold streak (SwStr% {swstr_trend:.1%})")

        # Minimum multiplier
        confidence_multiplier = max(rf.min_confidence_multiplier, confidence_multiplier)

        return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

    @abstractmethod
    def predict(
        self,
        pitcher_lookup: str,
        features: Dict,
        strikeouts_line: Optional[float] = None
    ) -> Dict:
        """
        Generate strikeout prediction for a pitcher.

        Each prediction system implements its own prediction logic here.

        Args:
            pitcher_lookup: Pitcher identifier
            features: Feature dict from pitcher_game_summary
            strikeouts_line: Betting line (optional, for recommendation)

        Returns:
            dict: Prediction with metadata including:
                - pitcher_lookup: str
                - predicted_strikeouts: float
                - confidence: float
                - recommendation: str ('OVER', 'UNDER', 'PASS', 'SKIP', 'NO_LINE', 'ERROR')
                - edge: float (optional, if line provided)
                - strikeouts_line: float (optional)
                - model_version: str
                - system_id: str
                - red_flags: list (optional)
                - error: str (optional)
        """
        pass
