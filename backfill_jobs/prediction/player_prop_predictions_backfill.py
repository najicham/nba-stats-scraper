#!/usr/bin/env python3
"""
Player Prop Predictions Backfill Job (Phase 5)

Generates historical predictions using all 5 prediction systems.
This enables validation of prediction accuracy against actual outcomes.

Features:
- Day-by-day processing (game dates only)
- Bootstrap period skip (first 14 days of each season)
- Phase 4 dependency validation (requires ml_feature_store, player_daily_cache)
- Checkpoint support for resumable backfills
- Direct prediction system invocation (no Cloud Run/Pub/Sub needed)

Dependencies:
- player_daily_cache (Phase 4)
- player_shot_zone_analysis (Phase 4)
- team_defense_zone_analysis (Phase 4)
- player_composite_factors (Phase 4)

Usage:
    # Dry run to check data availability
    python player_prop_predictions_backfill.py --dry-run --start-date 2021-12-01 --end-date 2021-12-07

    # Process date range
    python player_prop_predictions_backfill.py --start-date 2021-11-15 --end-date 2021-12-31

    # Resume from checkpoint
    python player_prop_predictions_backfill.py --start-date 2021-11-15 --end-date 2021-12-31

    # Retry specific failed dates
    python player_prop_predictions_backfill.py --dates 2021-12-05,2021-12-12
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import time
import traceback

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.backfill import BackfillCheckpoint, get_game_dates_for_range
from google.cloud import bigquery

# Phase 5C: Scoring tier adjustments
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierAdjuster

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = 'nba-props-platform'
PREDICTIONS_TABLE = f'{PROJECT_ID}.nba_predictions.player_prop_predictions'


def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within bootstrap period (first 14 days of season)."""
    season_year = get_season_year_from_date(check_date)
    return is_early_season(check_date, season_year)


class PredictionBackfill:
    """
    Backfill processor for player prop predictions (Phase 5).

    Reads from:
    - nba_precompute.player_daily_cache (Phase 4)
    - nba_precompute.player_shot_zone_analysis (Phase 4)
    - nba_precompute.team_defense_zone_analysis (Phase 4)
    - nba_analytics.player_game_summary (Phase 3)

    Writes to: nba_predictions.player_prop_predictions
    """

    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self._prediction_systems = None
        self._data_loader = None
        # Phase 5C: Scoring tier adjuster for bias correction
        self._tier_adjuster = None

    def _init_tier_adjuster(self):
        """Lazy-load tier adjuster."""
        if self._tier_adjuster is None:
            self._tier_adjuster = ScoringTierAdjuster()
        return self._tier_adjuster

    def _init_prediction_systems(self):
        """Lazy-load prediction systems."""
        if self._prediction_systems is not None:
            return

        logger.info("Initializing prediction systems...")

        # Add predictions directory to path
        predictions_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'predictions', 'worker'
        )
        sys.path.insert(0, predictions_dir)

        from prediction_systems.moving_average_baseline import MovingAverageBaseline
        from prediction_systems.zone_matchup_v1 import ZoneMatchupV1
        from prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
        from prediction_systems.xgboost_v1 import XGBoostV1
        from prediction_systems.ensemble_v1 import EnsembleV1
        from data_loaders import PredictionDataLoader

        self._moving_average = MovingAverageBaseline()
        self._zone_matchup = ZoneMatchupV1()
        self._similarity = SimilarityBalancedV1()
        self._xgboost = XGBoostV1()
        self._ensemble = EnsembleV1(
            moving_average_system=self._moving_average,
            zone_matchup_system=self._zone_matchup,
            similarity_system=self._similarity,
            xgboost_system=self._xgboost
        )
        self._data_loader = PredictionDataLoader(PROJECT_ID)
        self._prediction_systems = True
        logger.info("Prediction systems initialized")

    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False
        if end_date > date.today():
            logger.error("End date cannot be in the future")
            return False
        return True

    def check_mlfs_completeness(self, game_date: date, min_coverage_pct: float = 90.0) -> Dict:
        """
        Check if ML Feature Store data is complete for the date.

        Compares MLFS player count against expected players from player_game_summary.
        This prevents predictions from running on incomplete/stale MLFS data.

        Args:
            game_date: Date to check
            min_coverage_pct: Minimum coverage percentage required (default 90%)

        Returns:
            Dict with 'complete', 'mlfs_count', 'expected_count', 'coverage_pct'
        """
        try:
            query = f"""
            WITH mlfs AS (
                SELECT COUNT(DISTINCT player_lookup) as count
                FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
                WHERE game_date = '{game_date}'
            ),
            expected AS (
                SELECT COUNT(DISTINCT player_lookup) as count
                FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
                WHERE game_date = '{game_date}'
            )
            SELECT
                mlfs.count as mlfs_count,
                expected.count as expected_count
            FROM mlfs, expected
            """
            result = self.bq_client.query(query).to_dataframe()

            if result.empty:
                return {
                    'complete': False,
                    'mlfs_count': 0,
                    'expected_count': 0,
                    'coverage_pct': 0.0,
                    'error': 'No data returned'
                }

            mlfs_count = int(result['mlfs_count'].iloc[0])
            expected_count = int(result['expected_count'].iloc[0])

            if expected_count == 0:
                return {
                    'complete': False,
                    'mlfs_count': mlfs_count,
                    'expected_count': 0,
                    'coverage_pct': 0.0,
                    'error': 'No expected players (no games on this date?)'
                }

            coverage_pct = (mlfs_count / expected_count) * 100.0
            is_complete = coverage_pct >= min_coverage_pct

            return {
                'complete': is_complete,
                'mlfs_count': mlfs_count,
                'expected_count': expected_count,
                'coverage_pct': round(coverage_pct, 1)
            }

        except Exception as e:
            logger.error(f"Error checking MLFS completeness: {e}")
            return {
                'complete': False,
                'mlfs_count': 0,
                'expected_count': 0,
                'coverage_pct': 0.0,
                'error': str(e)
            }

    def check_phase4_dependencies(self, game_date: date) -> Dict:
        """Check if Phase 4 dependencies exist for the date."""
        try:
            queries = {
                'player_daily_cache': f"""
                    SELECT COUNT(*) as count
                    FROM `{PROJECT_ID}.nba_precompute.player_daily_cache`
                    WHERE cache_date = '{game_date}'
                """,
                'player_shot_zone_analysis': f"""
                    SELECT COUNT(*) as count
                    FROM `{PROJECT_ID}.nba_precompute.player_shot_zone_analysis`
                    WHERE analysis_date = '{game_date}'
                """,
                'team_defense_zone_analysis': f"""
                    SELECT COUNT(*) as count
                    FROM `{PROJECT_ID}.nba_precompute.team_defense_zone_analysis`
                    WHERE analysis_date = '{game_date}'
                """
            }

            counts = {}
            for name, query in queries.items():
                result = self.bq_client.query(query).to_dataframe()
                counts[name] = int(result['count'].iloc[0]) if not result.empty else 0

            # Need at least some data for each dependency
            # Lowered PDC threshold to 30 since early season has sparse coverage
            min_counts = {
                'player_daily_cache': 30,  # At least 30 player records (lowered for early season)
                'player_shot_zone_analysis': 50,  # At least 50 player records
                'team_defense_zone_analysis': 15  # 15+ teams
            }

            all_available = all(
                counts.get(name, 0) >= min_count
                for name, min_count in min_counts.items()
            )

            return {
                'available': all_available,
                **counts
            }

        except Exception as e:
            logger.error(f"Error checking dependencies: {e}")
            return {'available': False, 'error': str(e)}

    def get_players_for_date(self, game_date: date) -> List[Dict]:
        """Get players who played on a specific date."""
        query = f"""
        SELECT DISTINCT
            player_lookup,
            team_abbr,
            opponent_team_abbr as opponent_abbr,
            game_id
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date = '{game_date}'
          AND (minutes_played > 0 OR minutes_played IS NULL)
        ORDER BY player_lookup
        """
        try:
            result = self.bq_client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error fetching players for {game_date}: {e}")
            return []

    def generate_predictions_for_player(
        self,
        player_lookup: str,
        game_date: date,
        team_abbr: str,
        opponent_abbr: str,
        betting_line: float = 20.0  # Default line
    ) -> Optional[Dict]:
        """Generate predictions for a single player."""
        try:
            self._init_prediction_systems()

            # Load features from ml_feature_store_v2
            features = self._data_loader.load_features(
                player_lookup=player_lookup,
                game_date=game_date
            )

            if not features:
                logger.debug(f"No features for {player_lookup} on {game_date}")
                return None

            # Load historical games for similarity system
            historical_games = self._data_loader.load_historical_games(
                player_lookup=player_lookup,
                game_date=game_date
            )

            # Run all prediction systems
            predictions = {}

            # 1. Moving Average Baseline
            try:
                pred_pts, conf, rec = self._moving_average.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=betting_line
                )
                predictions['moving_average'] = {
                    'predicted_value': pred_pts,
                    'confidence': conf,
                    'recommendation': rec
                }
            except Exception as e:
                logger.debug(f"Moving average failed for {player_lookup}: {e}")

            # 2. Zone Matchup
            try:
                pred_pts, conf, rec = self._zone_matchup.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=betting_line
                )
                predictions['zone_matchup'] = {
                    'predicted_value': pred_pts,
                    'confidence': conf,
                    'recommendation': rec
                }
            except Exception as e:
                logger.debug(f"Zone matchup failed for {player_lookup}: {e}")

            # 3. Similarity Balanced
            try:
                sim_result = self._similarity.predict(
                    player_lookup=player_lookup,
                    features=features,
                    historical_games=historical_games or [],
                    betting_line=betting_line
                )
                if sim_result:
                    predictions['similarity'] = {
                        'predicted_value': sim_result.get('predicted_points'),
                        'confidence': sim_result.get('confidence_score', 0) / 100.0,  # Normalize to 0-1
                        'recommendation': sim_result.get('recommendation')
                    }
            except Exception as e:
                logger.debug(f"Similarity failed for {player_lookup}: {e}")

            # 4. XGBoost
            try:
                xgb_result = self._xgboost.predict(
                    player_lookup=player_lookup,
                    features=features,
                    betting_line=betting_line
                )
                if xgb_result and 'error' not in xgb_result:
                    predictions['xgboost'] = {
                        'predicted_value': xgb_result.get('predicted_points'),
                        'confidence': xgb_result.get('confidence_score', 0) / 100.0,  # Normalize to 0-1
                        'recommendation': xgb_result.get('recommendation')
                    }
            except Exception as e:
                logger.debug(f"XGBoost failed for {player_lookup}: {e}")

            # 5. Ensemble (combines all systems)
            try:
                ens_pred, ens_conf, ens_rec, ens_meta = self._ensemble.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=betting_line,
                    historical_games=historical_games
                )
                predictions['ensemble'] = {
                    'predicted_value': ens_pred,
                    'confidence': ens_conf,
                    'recommendation': ens_rec,
                    'metadata': ens_meta
                }
            except Exception as e:
                logger.debug(f"Ensemble failed for {player_lookup}: {e}")

            return predictions if predictions else None

        except Exception as e:
            logger.error(f"Error generating predictions for {player_lookup}: {e}")
            return None

    def write_predictions_to_bq(
        self,
        predictions: List[Dict],
        game_date: date
    ) -> int:
        """Write predictions to BigQuery with idempotency.

        The table schema expects ONE row per prediction system per player:
        - system_id: identifies the prediction system (moving_average, zone_matchup, etc.)
        - predicted_points: the predicted value
        - confidence_score: confidence level (0-1)
        - recommendation: OVER/UNDER/HOLD

        Idempotency: Deletes existing predictions for this date before inserting,
        allowing safe re-runs without creating duplicates.
        """
        if not predictions:
            return 0

        try:
            from datetime import timezone

            # IDEMPOTENCY: Delete existing predictions for this date first
            delete_query = f"""
            DELETE FROM `{PREDICTIONS_TABLE}`
            WHERE game_date = '{game_date.isoformat()}'
            """
            delete_job = self.bq_client.query(delete_query)
            delete_job.result()  # Wait for completion
            deleted_count = delete_job.num_dml_affected_rows or 0
            if deleted_count > 0:
                logger.info(f"  Deleted {deleted_count} existing predictions for {game_date} (idempotency)")

            # Prepare rows for BigQuery - one row per system per player
            rows = []
            timestamp = datetime.now(timezone.utc).isoformat()

            # Map our system names to system_id values
            system_id_map = {
                'moving_average': 'moving_average_baseline_v1',
                'zone_matchup': 'zone_matchup_v1',
                'similarity': 'similarity_balanced_v1',
                'xgboost': 'xgboost_v1',
                'ensemble': 'ensemble_v1'
            }

            for pred in predictions:
                player_lookup = pred['player_lookup']
                betting_line = pred.get('betting_line', 20.0)
                game_id = pred.get('game_id')  # Now included from get_players_for_date
                season_avg = pred.get('season_avg')  # Session 121: For tier classification

                # Create one row per prediction system
                for system_name, system_data in pred.get('predictions', {}).items():
                    if system_data is None:
                        continue

                    predicted_value = system_data.get('predicted_value')
                    if predicted_value is None:
                        continue

                    # Generate unique prediction_id
                    prediction_id = f"{game_date.isoformat()}_{player_lookup}_{system_name}"

                    row = {
                        'prediction_id': prediction_id,
                        'system_id': system_id_map.get(system_name, system_name),
                        'player_lookup': player_lookup,
                        'game_id': game_id,  # Now populated at write time
                        'game_date': game_date.isoformat(),
                        'predicted_points': float(predicted_value),
                        'confidence_score': float(system_data.get('confidence', 0.5)),
                        'recommendation': system_data.get('recommendation', 'HOLD'),
                        'current_points_line': float(betting_line),
                        'line_margin': float(predicted_value) - float(betting_line),
                        'is_active': True,
                        'created_at': timestamp,
                        'backfill_bootstrap_mode': True,
                        'model_version': '1.0',
                        'prediction_version': 1
                    }

                    # Phase 5C: Apply tier adjustment for ensemble predictions
                    # Session 121 FIX: Use season_avg (historical average) for tier classification
                    # instead of predicted_points - this ensures adjustments match actual player type
                    if system_name == 'ensemble':
                        try:
                            adjuster = self._init_tier_adjuster()
                            # Use season average for tier, fall back to predicted value if unavailable
                            tier_basis = float(season_avg) if season_avg else float(predicted_value)
                            tier = adjuster.classify_tier_by_season_avg(tier_basis)
                            adjustment = adjuster.get_adjustment_for_tier(
                                tier,
                                as_of_date=game_date.isoformat()
                            )
                            row['scoring_tier'] = tier
                            row['tier_adjustment'] = float(adjustment) if adjustment else None
                            row['adjusted_points'] = float(predicted_value) + float(adjustment) if adjustment else None
                        except Exception as e:
                            logger.debug(f"Tier adjustment failed for {player_lookup}: {e}")
                            row['scoring_tier'] = None
                            row['tier_adjustment'] = None
                            row['adjusted_points'] = None

                    rows.append(row)

            if not rows:
                return 0

            # Write to BigQuery using BATCH LOADING (not streaming inserts)
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            table_ref = self.bq_client.get_table(PREDICTIONS_TABLE)

            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                rows,
                PREDICTIONS_TABLE,
                job_config=job_config
            )
            load_job.result()  # Wait for completion

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
                return load_job.output_rows or 0

            return load_job.output_rows or len(rows)

        except Exception as e:
            logger.error(f"Error writing predictions to BigQuery: {e}")
            return 0

    def run_predictions_for_date(
        self,
        game_date: date,
        dry_run: bool = False,
        require_complete_mlfs: bool = True,
        min_mlfs_coverage_pct: float = 90.0
    ) -> Dict:
        """Run predictions for all players on a specific date.

        Uses batch loading optimization (10-40x speedup):
        - Loads all features in ONE query instead of N queries
        - Loads all historical games in ONE query instead of N queries

        Args:
            game_date: Date to process
            dry_run: If True, only check dependencies without processing
            require_complete_mlfs: If True, skip dates with incomplete MLFS (default True)
            min_mlfs_coverage_pct: Minimum MLFS coverage required (default 90%)
        """
        if is_bootstrap_date(game_date):
            return {
                'status': 'skipped_bootstrap',
                'date': game_date.isoformat()
            }

        # Check Phase 4 dependencies
        deps = self.check_phase4_dependencies(game_date)
        if not deps['available']:
            return {
                'status': 'missing_dependencies',
                'date': game_date.isoformat(),
                'dependencies': deps
            }

        # Check MLFS completeness (prevents running on stale/incomplete data)
        mlfs_check = self.check_mlfs_completeness(game_date, min_mlfs_coverage_pct)
        if require_complete_mlfs and not mlfs_check['complete']:
            logger.warning(
                f"MLFS incomplete for {game_date}: {mlfs_check['mlfs_count']}/{mlfs_check['expected_count']} "
                f"({mlfs_check['coverage_pct']}% < {min_mlfs_coverage_pct}% required). "
                f"Skipping to prevent predictions on stale data. "
                f"Use --skip-mlfs-check to override."
            )
            return {
                'status': 'incomplete_mlfs',
                'date': game_date.isoformat(),
                'mlfs_count': mlfs_check['mlfs_count'],
                'expected_count': mlfs_check['expected_count'],
                'coverage_pct': mlfs_check['coverage_pct']
            }

        if dry_run:
            return {
                'status': 'dry_run_complete',
                'date': game_date.isoformat(),
                'dependencies_available': True,
                'dependency_counts': deps
            }

        # Get players who played
        players = self.get_players_for_date(game_date)
        if not players:
            return {
                'status': 'no_players',
                'date': game_date.isoformat()
            }

        # Initialize prediction systems (lazy load)
        self._init_prediction_systems()

        # BATCH LOADING OPTIMIZATION: Load all data upfront with 2 queries instead of 300
        player_lookups = [p['player_lookup'] for p in players]

        # Batch load features for ALL players (1 query instead of N)
        all_features = self._data_loader.load_features_batch_for_date(
            player_lookups=player_lookups,
            game_date=game_date
        )

        # Batch load historical games for ALL players (1 query instead of N)
        all_historical = self._data_loader.load_historical_games_batch(
            player_lookups=player_lookups,
            game_date=game_date
        )

        # Generate predictions for each player using pre-loaded data
        all_predictions = []
        successful = 0
        failed = 0

        for player in players:
            player_lookup = player['player_lookup']
            try:
                # Use pre-loaded data instead of individual queries
                features = all_features.get(player_lookup)
                historical_games = all_historical.get(player_lookup, [])

                preds = self._generate_predictions_with_data(
                    player_lookup=player_lookup,
                    game_date=game_date,
                    features=features,
                    historical_games=historical_games
                )

                if preds:
                    # Extract season average for tier classification (Session 121 fix)
                    season_avg = features.get('points_avg_season') if features else None
                    all_predictions.append({
                        'player_lookup': player_lookup,
                        'team_abbr': player['team_abbr'],
                        'opponent_abbr': player['opponent_abbr'],
                        'game_id': player.get('game_id'),
                        'predictions': preds,
                        'season_avg': season_avg  # For tier classification
                    })
                    successful += 1
                else:
                    failed += 1

            except Exception as e:
                logger.debug(f"Player {player_lookup} failed: {e}")
                failed += 1

        # Write to BigQuery
        written = self.write_predictions_to_bq(all_predictions, game_date)

        return {
            'status': 'success' if successful > 0 else 'failed',
            'date': game_date.isoformat(),
            'players_found': len(players),
            'predictions_generated': successful,
            'failed': failed,
            'written_to_bq': written
        }

    def _generate_predictions_with_data(
        self,
        player_lookup: str,
        game_date: date,
        features: Optional[Dict],
        historical_games: List[Dict],
        betting_line: float = 20.0
    ) -> Optional[Dict]:
        """Generate predictions using pre-loaded data (batch optimization).

        This avoids the per-player BigQuery queries that were the main bottleneck.
        """
        if not features:
            logger.debug(f"No features for {player_lookup} on {game_date}")
            return None

        # Run all prediction systems
        predictions = {}

        # 1. Moving Average Baseline
        try:
            pred_pts, conf, rec = self._moving_average.predict(
                features=features,
                player_lookup=player_lookup,
                game_date=game_date,
                prop_line=betting_line
            )
            predictions['moving_average'] = {
                'predicted_value': pred_pts,
                'confidence': conf,
                'recommendation': rec
            }
        except Exception as e:
            logger.debug(f"Moving average failed for {player_lookup}: {e}")

        # 2. Zone Matchup
        try:
            pred_pts, conf, rec = self._zone_matchup.predict(
                features=features,
                player_lookup=player_lookup,
                game_date=game_date,
                prop_line=betting_line
            )
            predictions['zone_matchup'] = {
                'predicted_value': pred_pts,
                'confidence': conf,
                'recommendation': rec
            }
        except Exception as e:
            logger.debug(f"Zone matchup failed for {player_lookup}: {e}")

        # 3. Similarity Balanced
        try:
            sim_result = self._similarity.predict(
                player_lookup=player_lookup,
                features=features,
                historical_games=historical_games or [],
                betting_line=betting_line
            )
            if sim_result:
                predictions['similarity'] = {
                    'predicted_value': sim_result.get('predicted_points'),
                    'confidence': sim_result.get('confidence_score', 0) / 100.0,
                    'recommendation': sim_result.get('recommendation')
                }
        except Exception as e:
            logger.debug(f"Similarity failed for {player_lookup}: {e}")

        # 4. XGBoost
        try:
            xgb_result = self._xgboost.predict(
                player_lookup=player_lookup,
                features=features,
                betting_line=betting_line
            )
            if xgb_result and 'error' not in xgb_result:
                predictions['xgboost'] = {
                    'predicted_value': xgb_result.get('predicted_points'),
                    'confidence': xgb_result.get('confidence_score', 0) / 100.0,
                    'recommendation': xgb_result.get('recommendation')
                }
        except Exception as e:
            logger.debug(f"XGBoost failed for {player_lookup}: {e}")

        # 5. Ensemble (combines all systems)
        try:
            ens_pred, ens_conf, ens_rec, ens_meta = self._ensemble.predict(
                features=features,
                player_lookup=player_lookup,
                game_date=game_date,
                prop_line=betting_line,
                historical_games=historical_games
            )
            predictions['ensemble'] = {
                'predicted_value': ens_pred,
                'confidence': ens_conf,
                'recommendation': ens_rec,
                'metadata': ens_meta
            }
        except Exception as e:
            logger.debug(f"Ensemble failed for {player_lookup}: {e}")

        return predictions if predictions else None

    def run_backfill(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
        checkpoint: BackfillCheckpoint = None,
        require_complete_mlfs: bool = True,
        min_mlfs_coverage_pct: float = 90.0
    ):
        """Run backfill processing day-by-day with checkpoint support.

        Args:
            require_complete_mlfs: If True, skip dates with incomplete MLFS data
            min_mlfs_coverage_pct: Minimum MLFS coverage required (default 90%)
        """
        logger.info(f"Starting Phase 5 prediction backfill from {start_date} to {end_date}")

        if not self.validate_date_range(start_date, end_date):
            return

        # Get game dates (skip days with no games)
        logger.info("Fetching NBA schedule to find game dates...")
        game_dates = get_game_dates_for_range(start_date, end_date)

        if not game_dates:
            logger.warning("No game dates found in the specified range!")
            return

        # Handle checkpoint resume
        actual_start_idx = 0
        if checkpoint and not dry_run:
            resume_date = checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                for i, gd in enumerate(game_dates):
                    if gd >= resume_date:
                        actual_start_idx = i
                        break
                logger.info(f"RESUMING from checkpoint: {game_dates[actual_start_idx]}")
                checkpoint.print_status()

        dates_to_process = game_dates[actual_start_idx:]
        total_game_dates = len(game_dates)
        remaining_dates = len(dates_to_process)

        # Statistics
        processed_days = 0
        successful_days = 0
        skipped_days = 0
        failed_days = []
        total_predictions = 0

        logger.info(f"Processing {remaining_dates} game dates (of {total_game_dates} total)")

        for current_date in dates_to_process:
            day_number = actual_start_idx + processed_days + 1
            logger.info(f"Processing game date {day_number}/{total_game_dates}: {current_date}")

            start_time = time.time()
            result = self.run_predictions_for_date(
                current_date,
                dry_run=dry_run,
                require_complete_mlfs=require_complete_mlfs,
                min_mlfs_coverage_pct=min_mlfs_coverage_pct
            )
            elapsed = time.time() - start_time

            if result['status'] == 'incomplete_mlfs':
                # MLFS data incomplete - skip to prevent bad predictions
                coverage = result.get('coverage_pct', 0)
                logger.warning(f"  ⚠ Skipped: MLFS incomplete ({coverage}% coverage)")
                skipped_days += 1
                failed_days.append(current_date)  # Track for retry
                if checkpoint:
                    checkpoint.mark_date_failed(current_date, error=f"MLFS incomplete: {coverage}%")
            elif result['status'] == 'success':
                successful_days += 1
                preds = result.get('predictions_generated', 0)
                total_predictions += preds
                logger.info(f"  ✓ Success: {preds} predictions in {elapsed:.1f}s")
                if checkpoint:
                    checkpoint.mark_date_complete(current_date)

            elif result['status'] == 'skipped_bootstrap':
                skipped_days += 1
                logger.info(f"  ⏭ Skipped: bootstrap period")
                if checkpoint:
                    checkpoint.mark_date_skipped(current_date)

            elif result['status'] == 'missing_dependencies':
                failed_days.append(current_date)
                logger.warning(f"  ⚠ Missing dependencies: {result.get('dependencies', {})}")
                if checkpoint:
                    checkpoint.mark_date_failed(current_date, error='missing_dependencies')

            elif result['status'] == 'dry_run_complete':
                deps = result.get('dependencies_available', False)
                logger.info(f"  ✓ Dry run: deps {'OK' if deps else 'MISSING'}")

            else:
                failed_days.append(current_date)
                logger.error(f"  ✗ Failed: {result.get('status', 'unknown')}")
                if checkpoint:
                    checkpoint.mark_date_failed(current_date, error=result.get('status'))

            processed_days += 1
            if processed_days % 10 == 0 and not dry_run:
                logger.info(f"Progress: {processed_days}/{remaining_dates} game dates")

        # Summary
        logger.info("=" * 80)
        logger.info("PHASE 5 PREDICTION BACKFILL SUMMARY:")
        logger.info(f"  Game dates processed: {processed_days}")
        logger.info(f"  Successful: {successful_days}, Skipped: {skipped_days}, Failed: {len(failed_days)}")
        if not dry_run and total_predictions > 0:
            logger.info(f"  Total predictions generated: {total_predictions}")
        if failed_days:
            logger.info(f"  Failed dates: {failed_days[:10]}")
        logger.info("=" * 80)

    def process_specific_dates(self, dates: List[date], dry_run: bool = False):
        """Process specific dates (for retrying failed dates)."""
        for single_date in dates:
            result = self.run_predictions_for_date(single_date, dry_run)
            logger.info(f"{single_date}: {result['status']}")


def main():
    parser = argparse.ArgumentParser(
        description='Phase 5 Prediction Backfill - Generate historical predictions',
        epilog="NOTE: Requires Phase 4 precompute data to be complete"
    )
    parser.add_argument('--start-date', type=str,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str,
                        help='Specific dates to process (comma-separated)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Check dependencies without generating predictions')
    parser.add_argument('--no-resume', action='store_true',
                        help='Ignore checkpoint and start fresh')
    parser.add_argument('--status', action='store_true',
                        help='Show checkpoint status and exit')
    parser.add_argument('--skip-preflight', action='store_true',
                        help='Skip Phase 4 pre-flight check (not recommended)')
    parser.add_argument('--skip-mlfs-check', action='store_true',
                        help='Skip MLFS completeness check (allows running on incomplete MLFS data)')
    parser.add_argument('--min-mlfs-coverage', type=float, default=90.0,
                        help='Minimum MLFS coverage percentage required (default: 90)')

    args = parser.parse_args()
    backfiller = PredictionBackfill()

    # Handle specific dates
    if args.dates:
        date_list = [
            datetime.strptime(d.strip(), '%Y-%m-%d').date()
            for d in args.dates.split(',')
        ]
        backfiller.process_specific_dates(date_list, dry_run=args.dry_run)
        return

    # Parse date range
    start_date = (
        datetime.strptime(args.start_date, '%Y-%m-%d').date()
        if args.start_date
        else date.today() - timedelta(days=7)
    )
    end_date = (
        datetime.strptime(args.end_date, '%Y-%m-%d').date()
        if args.end_date
        else date.today() - timedelta(days=1)
    )

    # Initialize checkpoint
    checkpoint = BackfillCheckpoint('prediction_backfill', start_date, end_date)

    if args.status:
        if checkpoint.exists():
            checkpoint.print_status()
        else:
            print(f"No checkpoint found. Would be at: {checkpoint.checkpoint_path}")
        return

    if args.no_resume and checkpoint.exists():
        checkpoint.clear()

    # Pre-flight check
    if not args.skip_preflight and not args.dry_run:
        logger.info("=" * 70)
        logger.info("PHASE 4 PRE-FLIGHT CHECK")
        logger.info("=" * 70)

        # Check a sample date in the middle of the range
        sample_date = start_date + (end_date - start_date) // 2
        deps = backfiller.check_phase4_dependencies(sample_date)

        if not deps['available']:
            logger.error("=" * 70)
            logger.error("❌ PRE-FLIGHT CHECK FAILED: Phase 4 data is incomplete!")
            logger.error("=" * 70)
            logger.error(f"Checked date: {sample_date}")
            logger.error(f"Dependencies: {deps}")
            logger.error("")
            logger.error("Options:")
            logger.error("  1. Run Phase 4 backfill first")
            logger.error("  2. Use --skip-preflight to bypass (NOT RECOMMENDED)")
            sys.exit(1)
        else:
            logger.info(f"✅ Pre-flight check passed for sample date {sample_date}")
            logger.info(f"   Counts: {deps}")

    logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
    backfiller.run_backfill(
        start_date,
        end_date,
        dry_run=args.dry_run,
        checkpoint=checkpoint if not args.dry_run else None,
        require_complete_mlfs=not args.skip_mlfs_check,
        min_mlfs_coverage_pct=args.min_mlfs_coverage
    )


if __name__ == "__main__":
    main()
