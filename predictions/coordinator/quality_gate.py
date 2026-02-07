# predictions/coordinator/quality_gate.py
"""
Quality Gate System for Predictions (Session 95, overhauled Session 139)

Implements "Predict Once, Never Replace" strategy:
- Only predict when feature quality is high enough
- Never replace existing predictions
- HARD FLOOR: Never predict with red alerts or matchup_quality < 50% (any mode)
- Self-heal via QualityHealer when processors are missing
- BACKFILL mode for next-day record-keeping predictions

Modes:
- FIRST: First attempt, require 85% quality
- RETRY: Hourly retries, require 85% quality
- FINAL_RETRY: Last quality-gated attempt, accept 80%
- LAST_CALL: 4 PM ET - accept 70% (was 0%, Session 139 overhaul)
- BACKFILL: Next-day record-keeping, accept 70%
"""

import logging
from datetime import date
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class PredictionMode(Enum):
    """Prediction run modes with quality thresholds."""
    FIRST = "FIRST"           # 8 AM ET - 85% threshold
    RETRY = "RETRY"           # 9-12 PM ET - 85% threshold
    FINAL_RETRY = "FINAL_RETRY"  # 1 PM ET - 80% threshold
    LAST_CALL = "LAST_CALL"   # 4 PM ET - 70% threshold (Session 139: was 0%)
    BACKFILL = "BACKFILL"     # Next-day record-keeping - 70% threshold


# Quality thresholds by mode
QUALITY_THRESHOLDS = {
    PredictionMode.FIRST: 85.0,
    PredictionMode.RETRY: 85.0,
    PredictionMode.FINAL_RETRY: 80.0,
    PredictionMode.LAST_CALL: 70.0,   # Session 139: was 0.0 (forced all)
    PredictionMode.BACKFILL: 70.0,     # Session 139: next-day record-keeping
}

# Session 139: Hard floor - NEVER predict regardless of mode
# These catch the Session 132 scenario (all matchup features defaulted)
HARD_FLOOR_MATCHUP_QUALITY = 50.0  # matchup_quality_pct minimum
HARD_FLOOR_ALERT_LEVELS = {'red'}  # quality_alert_level values that block
HARD_FLOOR_MAX_DEFAULTS = 0  # Session 141: Zero tolerance for default features


@dataclass
class QualityGateResult:
    """Result of quality gate check for a player."""
    player_lookup: str
    should_predict: bool
    reason: str
    feature_quality_score: Optional[float]
    has_existing_prediction: bool
    low_quality_flag: bool
    forced_prediction: bool
    prediction_attempt: str
    hard_floor_blocked: bool = False       # Session 139: blocked by absolute hard floor
    missing_processor: Optional[str] = None  # Session 139: which processor likely failed


@dataclass
class QualityGateSummary:
    """Summary of quality gate results for a batch."""
    total_players: int
    players_to_predict: int
    players_skipped_existing: int
    players_skipped_low_quality: int
    players_forced: int
    avg_quality_score: float
    quality_distribution: Dict[str, int]  # high/medium/low counts
    players_hard_blocked: int = 0          # Session 139: blocked by hard floor
    missing_processors: List[str] = field(default_factory=list)  # Session 139: diagnosed missing processors


class QualityGate:
    """
    Quality gate for prediction requests.

    Implements the "Predict Once, Never Replace" strategy.
    """

    def __init__(self, project_id: str, dataset_prefix: str = ''):
        """
        Initialize quality gate.

        Args:
            project_id: GCP project ID
            dataset_prefix: Optional dataset prefix for test isolation
        """
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        self._bq_client = None

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            from shared.clients import get_bigquery_client
            self._bq_client = get_bigquery_client(self.project_id)
        return self._bq_client

    def get_existing_predictions(self, game_date: date, player_lookups: List[str]) -> Dict[str, bool]:
        """
        Check which players already have predictions for the given date.

        Args:
            game_date: Date to check predictions for
            player_lookups: List of player lookups to check

        Returns:
            Dict mapping player_lookup to bool (True if prediction exists)
        """
        if not player_lookups:
            return {}

        dataset = f"{self.dataset_prefix}nba_predictions" if self.dataset_prefix else "nba_predictions"

        query = f"""
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.{dataset}.player_prop_predictions`
            WHERE game_date = @game_date
              AND player_lookup IN UNNEST(@player_lookups)
              AND is_active = TRUE
              AND system_id = 'catboost_v9'
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            existing = {row.player_lookup: True for row in result}
            logger.info(f"Found {len(existing)} existing predictions for {game_date}")
            return existing
        except Exception as e:
            logger.error(f"Error checking existing predictions: {e}")
            return {}

    def get_feature_quality_scores(self, game_date: date, player_lookups: List[str]) -> Dict[str, float]:
        """
        Get feature quality scores for players from ml_feature_store_v2.

        Session 139: Also fetches is_quality_ready, quality_alert_level, matchup_quality_pct
        for richer quality gating. Returns dict of scores for backward compatibility,
        but also populates self._quality_details for enhanced gating.

        Args:
            game_date: Date to get features for
            player_lookups: List of player lookups

        Returns:
            Dict mapping player_lookup to quality score (float)
        """
        if not player_lookups:
            self._quality_details = {}
            return {}

        dataset = f"{self.dataset_prefix}nba_predictions" if self.dataset_prefix else "nba_predictions"

        query = f"""
            SELECT
                player_lookup,
                feature_quality_score,
                is_quality_ready,
                quality_alert_level,
                matchup_quality_pct,
                default_feature_count,
                required_default_count
            FROM `{self.project_id}.{dataset}.ml_feature_store_v2`
            WHERE game_date = @game_date
              AND player_lookup IN UNNEST(@player_lookups)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            scores = {}
            self._quality_details = {}
            for row in result:
                scores[row.player_lookup] = float(row.feature_quality_score or 0)
                self._quality_details[row.player_lookup] = {
                    'is_quality_ready': row.is_quality_ready or False,
                    'quality_alert_level': row.quality_alert_level,
                    'matchup_quality_pct': float(row.matchup_quality_pct or 0),
                    'default_feature_count': int(row.default_feature_count or 0),
                    'required_default_count': int(row.required_default_count or row.default_feature_count or 0),
                }
            logger.info(f"Got quality scores for {len(scores)} players for {game_date}")
            return scores
        except Exception as e:
            logger.error(f"Error getting feature quality scores: {e}")
            self._quality_details = {}
            return {}

    def apply_quality_gate(
        self,
        game_date: date,
        player_lookups: List[str],
        mode: PredictionMode
    ) -> Tuple[List[QualityGateResult], QualityGateSummary]:
        """
        Apply quality gate to a batch of players.

        Session 139 overhaul:
        - Hard floor: NEVER predict with red alerts or matchup_quality < 50% (any mode)
        - LAST_CALL no longer forces at 0% threshold (now 70%)
        - Diagnoses missing processors for self-healing
        - No more forced_no_features or forced_last_call escape hatches

        Args:
            game_date: Date to make predictions for
            player_lookups: List of player lookups
            mode: Prediction mode (determines threshold)

        Returns:
            Tuple of (list of QualityGateResult, QualityGateSummary)
        """
        threshold = QUALITY_THRESHOLDS.get(mode, 85.0)

        logger.info(f"Applying quality gate: mode={mode.value}, threshold={threshold}%, players={len(player_lookups)}")

        # Get existing predictions and quality scores
        existing_predictions = self.get_existing_predictions(game_date, player_lookups)
        quality_scores = self.get_feature_quality_scores(game_date, player_lookups)

        results = []
        stats = {
            'total': len(player_lookups),
            'to_predict': 0,
            'skipped_existing': 0,
            'skipped_low_quality': 0,
            'forced': 0,
            'hard_blocked': 0,
            'quality_sum': 0.0,
            'quality_count': 0,
            'high': 0,
            'medium': 0,
            'low': 0,
        }
        diagnosed_processors = set()

        for player_lookup in player_lookups:
            has_existing = existing_predictions.get(player_lookup, False)
            quality_score = quality_scores.get(player_lookup)
            details = getattr(self, '_quality_details', {}).get(player_lookup, {})
            alert_level = details.get('quality_alert_level')
            matchup_q = details.get('matchup_quality_pct', 100)  # Default 100 for backward compat

            # Track quality distribution
            if quality_score is not None:
                stats['quality_sum'] += quality_score
                stats['quality_count'] += 1
                if quality_score >= 85:
                    stats['high'] += 1
                elif quality_score >= 80:
                    stats['medium'] += 1
                else:
                    stats['low'] += 1

            # Rule 1: Never replace existing predictions
            if has_existing:
                results.append(QualityGateResult(
                    player_lookup=player_lookup,
                    should_predict=False,
                    reason="already_has_prediction",
                    feature_quality_score=quality_score,
                    has_existing_prediction=True,
                    low_quality_flag=False,
                    forced_prediction=False,
                    prediction_attempt=mode.value
                ))
                stats['skipped_existing'] += 1
                continue

            # Rule 2 (Session 139 HARD FLOOR): Block red alerts and low matchup quality
            # This applies to ALL modes including LAST_CALL and BACKFILL
            if alert_level in HARD_FLOOR_ALERT_LEVELS:
                missing = _diagnose_missing_processor(details)
                if missing:
                    diagnosed_processors.add(missing)
                logger.warning(
                    f"HARD_FLOOR: Blocking {player_lookup} - quality_alert_level={alert_level}, "
                    f"matchup_q={matchup_q:.0f}%, missing_processor={missing}"
                )
                results.append(QualityGateResult(
                    player_lookup=player_lookup,
                    should_predict=False,
                    reason=f"hard_floor_red_alert",
                    feature_quality_score=quality_score,
                    has_existing_prediction=False,
                    low_quality_flag=True,
                    forced_prediction=False,
                    prediction_attempt=mode.value,
                    hard_floor_blocked=True,
                    missing_processor=missing,
                ))
                stats['hard_blocked'] += 1
                stats['skipped_low_quality'] += 1
                continue

            if quality_score is not None and matchup_q < HARD_FLOOR_MATCHUP_QUALITY:
                missing = _diagnose_missing_processor(details)
                if missing:
                    diagnosed_processors.add(missing)
                logger.warning(
                    f"HARD_FLOOR: Blocking {player_lookup} - matchup_quality={matchup_q:.0f}% "
                    f"< {HARD_FLOOR_MATCHUP_QUALITY}%, missing_processor={missing}"
                )
                results.append(QualityGateResult(
                    player_lookup=player_lookup,
                    should_predict=False,
                    reason=f"hard_floor_matchup_{matchup_q:.0f}",
                    feature_quality_score=quality_score,
                    has_existing_prediction=False,
                    low_quality_flag=True,
                    forced_prediction=False,
                    prediction_attempt=mode.value,
                    hard_floor_blocked=True,
                    missing_processor=missing,
                ))
                stats['hard_blocked'] += 1
                stats['skipped_low_quality'] += 1
                continue

            # Rule 2b (Session 141 Zero Tolerance): Block any defaulted REQUIRED features
            # Session 145: Use required_default_count (excludes optional vegas features)
            # Vegas lines unavailable for ~60% of players (bench) - normal, not a blocker
            # This applies to ALL modes including LAST_CALL and BACKFILL
            default_count = details.get('required_default_count', details.get('default_feature_count', 0))
            if quality_score is not None and default_count > HARD_FLOOR_MAX_DEFAULTS:
                logger.warning(
                    f"HARD_FLOOR: Blocking {player_lookup} - required_default_count={default_count} "
                    f"> {HARD_FLOOR_MAX_DEFAULTS} (zero tolerance, excludes optional vegas)"
                )
                results.append(QualityGateResult(
                    player_lookup=player_lookup,
                    should_predict=False,
                    reason=f"zero_tolerance_defaults_{default_count}",
                    feature_quality_score=quality_score,
                    has_existing_prediction=False,
                    low_quality_flag=True,
                    forced_prediction=False,
                    prediction_attempt=mode.value,
                    hard_floor_blocked=True,
                ))
                stats['hard_blocked'] += 1
                stats['skipped_low_quality'] += 1
                continue

            # Rule 3: No feature data at all - skip (no more LAST_CALL forcing)
            if quality_score is None:
                results.append(QualityGateResult(
                    player_lookup=player_lookup,
                    should_predict=False,
                    reason="no_features_available",
                    feature_quality_score=None,
                    has_existing_prediction=False,
                    low_quality_flag=True,
                    forced_prediction=False,
                    prediction_attempt=mode.value,
                    hard_floor_blocked=True,
                ))
                stats['hard_blocked'] += 1
                stats['skipped_low_quality'] += 1
                continue

            # Rule 4: Quality meets threshold - predict
            if quality_score >= threshold:
                low_quality = quality_score < 85
                results.append(QualityGateResult(
                    player_lookup=player_lookup,
                    should_predict=True,
                    reason="quality_sufficient",
                    feature_quality_score=quality_score,
                    has_existing_prediction=False,
                    low_quality_flag=low_quality,
                    forced_prediction=False,
                    prediction_attempt=mode.value
                ))
                stats['to_predict'] += 1
                continue

            # Rule 5: Below threshold - skip
            results.append(QualityGateResult(
                player_lookup=player_lookup,
                should_predict=False,
                reason=f"quality_below_threshold_{threshold}",
                feature_quality_score=quality_score,
                has_existing_prediction=False,
                low_quality_flag=True,
                forced_prediction=False,
                prediction_attempt=mode.value
            ))
            stats['skipped_low_quality'] += 1

        # Build summary
        avg_quality = stats['quality_sum'] / stats['quality_count'] if stats['quality_count'] > 0 else 0.0

        summary = QualityGateSummary(
            total_players=stats['total'],
            players_to_predict=stats['to_predict'],
            players_skipped_existing=stats['skipped_existing'],
            players_skipped_low_quality=stats['skipped_low_quality'],
            players_forced=stats['forced'],
            avg_quality_score=avg_quality,
            quality_distribution={
                'high_85plus': stats['high'],
                'medium_80_85': stats['medium'],
                'low_below_80': stats['low'],
            },
            players_hard_blocked=stats['hard_blocked'],
            missing_processors=sorted(diagnosed_processors),
        )

        # Log summary
        logger.info(
            f"QUALITY_GATE_SUMMARY: mode={mode.value}, "
            f"to_predict={stats['to_predict']}/{stats['total']}, "
            f"skipped_existing={stats['skipped_existing']}, "
            f"skipped_low_quality={stats['skipped_low_quality']}, "
            f"hard_blocked={stats['hard_blocked']}, "
            f"avg_quality={avg_quality:.1f}%"
        )
        if diagnosed_processors:
            logger.warning(
                f"QUALITY_GATE: Missing processors diagnosed: {sorted(diagnosed_processors)}"
            )

        return results, summary


@dataclass
class AnalyticsQualityResult:
    """Result of analytics quality check for a game date."""
    game_date: date
    game_count: int
    active_players: int
    usage_rate_coverage_pct: float
    minutes_coverage_pct: float
    passes_threshold: bool
    issues: List[str]


class AnalyticsQualityGate:
    """
    Analytics quality gate for prediction requests (Session 96).

    Checks analytics data quality BEFORE predictions run.
    Optionally blocks predictions if quality is too low.

    Thresholds:
    - usage_rate_coverage: >= 50% to proceed (warning at < 80%)
    - minutes_coverage: >= 80% to proceed
    """

    # Minimum thresholds to allow predictions
    MIN_USAGE_RATE_COVERAGE = 50.0
    MIN_MINUTES_COVERAGE = 80.0

    # Warning thresholds (log but don't block)
    WARN_USAGE_RATE_COVERAGE = 80.0

    def __init__(self, project_id: str, dataset_prefix: str = ''):
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        self._bq_client = None

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            from shared.clients import get_bigquery_client
            self._bq_client = get_bigquery_client(self.project_id)
        return self._bq_client

    def check_analytics_quality(self, game_date: date) -> AnalyticsQualityResult:
        """
        Check analytics data quality for a game date.

        Args:
            game_date: Date to check analytics for (usually yesterday for grading)

        Returns:
            AnalyticsQualityResult with quality metrics and pass/fail
        """
        analytics_dataset = f"{self.dataset_prefix}nba_analytics" if self.dataset_prefix else "nba_analytics"

        query = f"""
        SELECT
            COUNT(DISTINCT game_id) as game_count,
            COUNTIF(is_dnp = FALSE) as active_players,
            COUNTIF(is_dnp = FALSE AND minutes_played > 0) as has_minutes,
            COUNTIF(is_dnp = FALSE AND usage_rate > 0) as has_usage_rate
        FROM `{self.project_id}.{analytics_dataset}.player_game_summary`
        WHERE game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            row = next(result)

            game_count = row.game_count or 0
            active_players = row.active_players or 0
            has_minutes = row.has_minutes or 0
            has_usage_rate = row.has_usage_rate or 0

            # Calculate coverage percentages
            usage_rate_pct = 100.0 * has_usage_rate / active_players if active_players > 0 else 0.0
            minutes_pct = 100.0 * has_minutes / active_players if active_players > 0 else 0.0

            # Check for issues
            issues = []
            passes = True

            if game_count == 0:
                issues.append("No games found for date")
                passes = False
            elif active_players == 0:
                issues.append("No active players found")
                passes = False
            else:
                if usage_rate_pct < self.MIN_USAGE_RATE_COVERAGE:
                    issues.append(f"usage_rate coverage {usage_rate_pct:.1f}% below minimum {self.MIN_USAGE_RATE_COVERAGE}%")
                    passes = False
                elif usage_rate_pct < self.WARN_USAGE_RATE_COVERAGE:
                    issues.append(f"WARNING: usage_rate coverage {usage_rate_pct:.1f}% below recommended {self.WARN_USAGE_RATE_COVERAGE}%")
                    # Don't fail, just warn

                if minutes_pct < self.MIN_MINUTES_COVERAGE:
                    issues.append(f"minutes coverage {minutes_pct:.1f}% below minimum {self.MIN_MINUTES_COVERAGE}%")
                    passes = False

            result = AnalyticsQualityResult(
                game_date=game_date,
                game_count=game_count,
                active_players=active_players,
                usage_rate_coverage_pct=round(usage_rate_pct, 1),
                minutes_coverage_pct=round(minutes_pct, 1),
                passes_threshold=passes,
                issues=issues,
            )

            # Log result
            if issues:
                logger.warning(
                    f"ANALYTICS_QUALITY_CHECK: date={game_date}, passes={passes}, "
                    f"usage_rate={usage_rate_pct:.1f}%, minutes={minutes_pct:.1f}%, "
                    f"issues={issues}"
                )
            else:
                logger.info(
                    f"ANALYTICS_QUALITY_CHECK: date={game_date}, passes=True, "
                    f"usage_rate={usage_rate_pct:.1f}%, minutes={minutes_pct:.1f}%"
                )

            return result

        except Exception as e:
            logger.error(f"Error checking analytics quality: {e}")
            return AnalyticsQualityResult(
                game_date=game_date,
                game_count=0,
                active_players=0,
                usage_rate_coverage_pct=0.0,
                minutes_coverage_pct=0.0,
                passes_threshold=False,
                issues=[f"Error checking analytics: {str(e)}"],
            )


def _diagnose_missing_processor(quality_details: Dict) -> Optional[str]:
    """
    Diagnose which Phase 4 processor likely failed based on quality details.

    Uses matchup_quality_pct and quality_alert_level to infer which processor
    didn't run. This enables targeted self-healing.

    Args:
        quality_details: Dict with is_quality_ready, quality_alert_level, matchup_quality_pct

    Returns:
        Processor name string or None if can't diagnose
    """
    matchup_q = quality_details.get('matchup_quality_pct', 100)
    alert_level = quality_details.get('quality_alert_level')

    # matchup_quality < 50% strongly indicates PlayerCompositeFactorsProcessor
    # or its dependencies (TeamDefenseZoneAnalysis, PlayerShotZoneAnalysis) failed
    if matchup_q < 50:
        # matchup_q = 0 means ALL matchup features defaulted -> composite factors processor
        if matchup_q == 0:
            return 'PlayerCompositeFactorsProcessor'
        # Partial matchup data -> likely a dependency processor
        return 'PlayerCompositeFactorsProcessor'

    # Red alert with decent matchup -> likely MLFeatureStoreProcessor issue
    if alert_level == 'red':
        return 'MLFeatureStoreProcessor'

    return None


def parse_prediction_mode(mode_str: str) -> PredictionMode:
    """
    Parse prediction mode string to enum.

    Maps legacy modes to new modes:
    - EARLY -> FIRST
    - OVERNIGHT -> RETRY (treated as retry)
    - SAME_DAY -> RETRY
    - MORNING -> RETRY

    Args:
        mode_str: Mode string from request

    Returns:
        PredictionMode enum
    """
    mode_map = {
        'FIRST': PredictionMode.FIRST,
        'RETRY': PredictionMode.RETRY,
        'FINAL_RETRY': PredictionMode.FINAL_RETRY,
        'LAST_CALL': PredictionMode.LAST_CALL,
        'BACKFILL': PredictionMode.BACKFILL,
        # Legacy mappings
        'EARLY': PredictionMode.FIRST,
        'OVERNIGHT': PredictionMode.RETRY,
        'SAME_DAY': PredictionMode.RETRY,
        'MORNING': PredictionMode.RETRY,
    }
    return mode_map.get(mode_str.upper(), PredictionMode.RETRY)
