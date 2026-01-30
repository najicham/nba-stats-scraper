"""
Prediction Quality Tracker

Tracks data availability and quality for each prediction.
Provides visibility into what data was used and what was missing.

Usage:
    tracker = PredictionQualityTracker(bq_client, game_date)
    tracker.check_data_availability()

    for player in players:
        quality = tracker.get_player_quality(player_lookup, features)
        # Include quality in prediction record

Created: Session 39 (2026-01-30)
"""

import logging
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class QualityTier(Enum):
    """Data quality tiers for predictions."""
    GOLD = "gold"      # All critical data available
    SILVER = "silver"  # Some data missing but acceptable
    BRONZE = "bronze"  # Significant data missing


@dataclass
class DataSourceStatus:
    """Status of a data source."""
    source_name: str
    available: bool
    row_count: int = 0
    freshness_hours: float = 0.0
    games_covered: int = 0
    games_expected: int = 0


@dataclass
class PlayerQuality:
    """Quality assessment for a single player's prediction."""
    player_lookup: str
    quality_tier: QualityTier
    quality_score: float  # 0-100
    shot_zones_available: bool
    shot_zones_source: str  # 'bigdataball', 'nbac_fallback', 'unavailable'
    missing_features: List[str] = field(default_factory=list)
    quality_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'data_quality_tier': self.quality_tier.value,
            'quality_score': self.quality_score,
            'shot_zones_available': self.shot_zones_available,
            'shot_zones_source': self.shot_zones_source,
            'missing_features': self.missing_features,
            'quality_issues': self.quality_issues if self.quality_issues else None
        }


class PredictionQualityTracker:
    """
    Tracks data quality for predictions.

    Checks availability of all data sources and assesses quality
    for each player's prediction.
    """

    # Critical features that significantly impact prediction quality
    CRITICAL_FEATURES = [
        'paint_rate', 'mid_range_rate', 'three_pt_rate',
        'rolling_avg_points', 'usage_rate', 'minutes_played'
    ]

    # Shot zone features (most critical for model)
    SHOT_ZONE_FEATURES = ['paint_rate', 'mid_range_rate', 'three_pt_rate']

    def __init__(self, bq_client: bigquery.Client, game_date: date):
        self.client = bq_client
        self.project_id = bq_client.project
        self.game_date = game_date

        # Data source status
        self.sources: Dict[str, DataSourceStatus] = {}

        # Player-level quality cache
        self._player_quality_cache: Dict[str, PlayerQuality] = {}

        # Games being processed
        self.games_expected: List[str] = []
        self.games_with_bdb: List[str] = []

    def check_data_availability(self) -> Dict[str, DataSourceStatus]:
        """
        Check availability of all data sources for the game date.

        Returns dict of source name -> status.
        """
        logger.info(f"Checking data availability for {self.game_date}")

        # Check BigDataBall PBP
        self._check_bdb_availability()

        # Check NBAC PBP (fallback)
        self._check_nbac_pbp_availability()

        # Check gamebook/box scores
        self._check_gamebook_availability()

        # Check betting data
        self._check_betting_availability()

        # Check ML feature store
        self._check_feature_store_availability()

        # Log summary
        available_count = sum(1 for s in self.sources.values() if s.available)
        logger.info(
            f"Data availability: {available_count}/{len(self.sources)} sources available"
        )

        for name, status in self.sources.items():
            if not status.available:
                logger.warning(f"  ⚠️ {name}: UNAVAILABLE")
            else:
                logger.info(f"  ✓ {name}: {status.row_count} rows")

        return self.sources

    def _check_bdb_availability(self) -> None:
        """Check BigDataBall play-by-play availability."""
        query = f"""
        SELECT
            COUNT(*) as total_events,
            COUNT(DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0')) as games_with_bdb,
            COUNTIF(event_type = 'shot' AND shot_distance IS NOT NULL) as shots_with_distance
        FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
        WHERE game_date = '{self.game_date}'
          AND bdb_game_id IS NOT NULL
        """

        try:
            result = list(self.client.query(query).result())[0]

            # Get expected games count
            games_query = f"""
            SELECT COUNT(*) as cnt
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = '{self.game_date}'
              AND game_status = 3
            """
            games_result = list(self.client.query(games_query).result())[0]
            expected_games = games_result.cnt

            available = result.shots_with_distance > 50  # At least one game worth

            self.sources['bigdataball_pbp'] = DataSourceStatus(
                source_name='bigdataball_pbp',
                available=available,
                row_count=result.total_events,
                games_covered=result.games_with_bdb,
                games_expected=expected_games
            )

            self.games_with_bdb = []
            if available:
                # Get list of games with BDB data
                games_q = f"""
                SELECT DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0') as game_id
                FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
                WHERE game_date = '{self.game_date}'
                  AND bdb_game_id IS NOT NULL
                """
                self.games_with_bdb = [
                    r.game_id for r in self.client.query(games_q).result()
                ]

        except Exception as e:
            logger.error(f"Error checking BDB availability: {e}")
            self.sources['bigdataball_pbp'] = DataSourceStatus(
                source_name='bigdataball_pbp',
                available=False,
                row_count=0
            )

    def _check_nbac_pbp_availability(self) -> None:
        """Check NBAC play-by-play availability (fallback source)."""
        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_raw.nbac_play_by_play`
        WHERE game_date = '{self.game_date}'
        """

        try:
            result = list(self.client.query(query).result())[0]
            self.sources['nbac_pbp'] = DataSourceStatus(
                source_name='nbac_pbp',
                available=result.cnt > 0,
                row_count=result.cnt
            )
        except Exception as e:
            logger.warning(f"Error checking NBAC PBP: {e}")
            self.sources['nbac_pbp'] = DataSourceStatus(
                source_name='nbac_pbp',
                available=False,
                row_count=0
            )

    def _check_gamebook_availability(self) -> None:
        """Check gamebook/box score availability."""
        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = '{self.game_date}'
        """

        try:
            result = list(self.client.query(query).result())[0]
            self.sources['gamebook'] = DataSourceStatus(
                source_name='gamebook',
                available=result.cnt > 0,
                row_count=result.cnt
            )
        except Exception as e:
            logger.warning(f"Error checking gamebook: {e}")
            self.sources['gamebook'] = DataSourceStatus(
                source_name='gamebook',
                available=False,
                row_count=0
            )

    def _check_betting_availability(self) -> None:
        """Check betting/odds data availability."""
        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
        WHERE game_date = '{self.game_date}'
        """

        try:
            result = list(self.client.query(query).result())[0]
            self.sources['betting'] = DataSourceStatus(
                source_name='betting',
                available=result.cnt > 0,
                row_count=result.cnt
            )
        except Exception as e:
            logger.warning(f"Error checking betting data: {e}")
            self.sources['betting'] = DataSourceStatus(
                source_name='betting',
                available=False,
                row_count=0
            )

    def _check_feature_store_availability(self) -> None:
        """Check ML feature store availability."""
        query = f"""
        SELECT
            COUNT(*) as cnt,
            COUNTIF(features[SAFE_OFFSET(18)] IS NOT NULL) as with_paint
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{self.game_date}'
        """

        try:
            result = list(self.client.query(query).result())[0]
            self.sources['feature_store'] = DataSourceStatus(
                source_name='feature_store',
                available=result.cnt > 0,
                row_count=result.cnt
            )
        except Exception as e:
            logger.warning(f"Error checking feature store: {e}")
            self.sources['feature_store'] = DataSourceStatus(
                source_name='feature_store',
                available=False,
                row_count=0
            )

    def get_player_quality(
        self,
        player_lookup: str,
        features: Dict,
        game_id: Optional[str] = None
    ) -> PlayerQuality:
        """
        Assess prediction quality for a specific player.

        Args:
            player_lookup: Player identifier
            features: Feature dict being used for prediction
            game_id: Optional game ID to check BDB availability

        Returns:
            PlayerQuality with tier, score, and issues
        """
        # Check cache
        cache_key = f"{player_lookup}:{game_id or 'unknown'}"
        if cache_key in self._player_quality_cache:
            return self._player_quality_cache[cache_key]

        missing_features = []
        quality_issues = []

        # Check shot zone features (most critical)
        shot_zones_available = True
        shot_zones_source = 'unavailable'

        for feat in self.SHOT_ZONE_FEATURES:
            if features.get(feat) is None:
                missing_features.append(feat)
                shot_zones_available = False

        # Determine shot zone source
        bdb_status = self.sources.get('bigdataball_pbp')
        if bdb_status and bdb_status.available:
            if game_id and game_id in self.games_with_bdb:
                shot_zones_source = 'bigdataball'
            elif shot_zones_available:
                shot_zones_source = 'nbac_fallback'
        elif shot_zones_available:
            shot_zones_source = 'nbac_fallback'

        # Check other critical features
        for feat in self.CRITICAL_FEATURES:
            if feat not in self.SHOT_ZONE_FEATURES:
                if features.get(feat) is None:
                    missing_features.append(feat)

        # Calculate quality score (0-100)
        total_critical = len(self.CRITICAL_FEATURES)
        available_critical = total_critical - len([
            f for f in missing_features if f in self.CRITICAL_FEATURES
        ])
        quality_score = (available_critical / total_critical) * 100

        # Determine tier
        if not shot_zones_available:
            quality_tier = QualityTier.BRONZE
            quality_issues.append("Shot zone features unavailable")
        elif shot_zones_source == 'nbac_fallback':
            quality_tier = QualityTier.SILVER
            quality_issues.append("Using NBAC fallback for shot zones (BDB unavailable)")
        elif len(missing_features) > 2:
            quality_tier = QualityTier.SILVER
            quality_issues.append(f"Missing {len(missing_features)} features")
        else:
            quality_tier = QualityTier.GOLD

        quality = PlayerQuality(
            player_lookup=player_lookup,
            quality_tier=quality_tier,
            quality_score=quality_score,
            shot_zones_available=shot_zones_available,
            shot_zones_source=shot_zones_source,
            missing_features=missing_features,
            quality_issues=quality_issues
        )

        # Cache result
        self._player_quality_cache[cache_key] = quality

        return quality

    def get_overall_quality_summary(self) -> Dict:
        """Get summary of quality across all tracked predictions."""
        if not self._player_quality_cache:
            return {'error': 'No predictions tracked yet'}

        total = len(self._player_quality_cache)
        gold = sum(1 for q in self._player_quality_cache.values()
                   if q.quality_tier == QualityTier.GOLD)
        silver = sum(1 for q in self._player_quality_cache.values()
                     if q.quality_tier == QualityTier.SILVER)
        bronze = sum(1 for q in self._player_quality_cache.values()
                     if q.quality_tier == QualityTier.BRONZE)

        return {
            'total_predictions': total,
            'gold_count': gold,
            'gold_pct': round(100 * gold / total, 1) if total > 0 else 0,
            'silver_count': silver,
            'silver_pct': round(100 * silver / total, 1) if total > 0 else 0,
            'bronze_count': bronze,
            'bronze_pct': round(100 * bronze / total, 1) if total > 0 else 0,
            'bdb_available': self.sources.get('bigdataball_pbp', DataSourceStatus('bdb', False)).available,
            'bdb_games_covered': len(self.games_with_bdb),
            'bdb_games_expected': self.sources.get('bigdataball_pbp', DataSourceStatus('bdb', False)).games_expected
        }

    def generate_audit_id(self) -> str:
        """Generate unique audit ID."""
        return str(uuid.uuid4())[:16]

    def create_audit_record(
        self,
        player_lookup: str,
        game_id: str,
        prediction_value: float,
        confidence: float,
        line_value: float,
        model_version: str,
        features: Dict,
        game_start_time: Optional[datetime] = None
    ) -> Dict:
        """
        Create a complete audit record for a prediction.

        Args:
            player_lookup: Player identifier
            game_id: Game ID
            prediction_value: Model prediction
            confidence: Confidence score
            line_value: Betting line
            model_version: Model version string
            features: Features used
            game_start_time: When game starts (for re-run decisions)

        Returns:
            Dict ready to insert into audit log
        """
        quality = self.get_player_quality(player_lookup, features, game_id)

        # Calculate hours until game
        hours_until_game = None
        rerun_allowed = True
        if game_start_time:
            now = datetime.now(timezone.utc)
            if game_start_time.tzinfo is None:
                game_start_time = game_start_time.replace(tzinfo=timezone.utc)
            delta = game_start_time - now
            hours_until_game = delta.total_seconds() / 3600
            rerun_allowed = hours_until_game > 2  # 2 hour cutoff

        bdb_status = self.sources.get('bigdataball_pbp', DataSourceStatus('bdb', False))

        return {
            'audit_id': self.generate_audit_id(),
            'player_lookup': player_lookup,
            'game_date': self.game_date.isoformat(),
            'game_id': game_id,
            'processed_at': datetime.now(timezone.utc).isoformat(),
            'model_version': model_version,

            # Data availability
            'bdb_pbp_available': bdb_status.available,
            'bdb_pbp_game_count': bdb_status.games_covered,

            # Feature completeness
            'total_features_expected': len(self.CRITICAL_FEATURES),
            'total_features_available': len(self.CRITICAL_FEATURES) - len(quality.missing_features),
            'feature_completeness_pct': quality.quality_score,
            'missing_features': quality.missing_features or None,

            # Shot zones
            'shot_zones_source': quality.shot_zones_source,
            'paint_rate_available': 'paint_rate' not in quality.missing_features,
            'three_pt_rate_available': 'three_pt_rate' not in quality.missing_features,
            'mid_range_rate_available': 'mid_range_rate' not in quality.missing_features,

            # Quality
            'data_quality_tier': quality.quality_tier.value,
            'quality_issues': quality.quality_issues or None,
            'quality_score': quality.quality_score,

            # Prediction
            'prediction_value': prediction_value,
            'prediction_direction': 'over' if prediction_value > line_value else 'under',
            'confidence_score': confidence,
            'line_value': line_value,

            # Re-run tracking
            'is_rerun': False,
            'game_start_time': game_start_time.isoformat() if game_start_time else None,
            'hours_until_game': hours_until_game,
            'rerun_allowed': rerun_allowed
        }
