"""
Signal Best Bets Exporter for Phase 6 Publishing (System 2)

Runs the Signal Discovery Framework against today's predictions and exports
edge-first best bets to GCS. Natural sizing — all picks passing edge 5+ floor
and negative filters are included. Also writes picks to
the `signal_best_bets_picks` BigQuery table for grading.

Session 307: Multi-source candidate generation — queries ALL CatBoost families
    (not just champion V9), picks highest-edge prediction per player.
Session 314: Consolidated with SignalAnnotator (System 3). Both now share:
    - Same BestBetsAggregator with same negative filters
    - Same player_blacklist (from compute_player_blacklist)
    - Same games_vs_opponent (from shared query_games_vs_opponent in supplemental_data)
    Legacy BestBetsExporter (System 1) removed from daily_export.py.
    Added filter_summary + edge_distribution to JSON output.

Pipeline: Phase 5 → Phase 6 Export → signal-best-bets
Output: v1/signal-best-bets/{date}.json

Created: 2026-02-14 (Session 254)
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry
from ml.signals.model_health import BREAKEVEN_HR
from ml.signals.signal_health import get_signal_health_summary
from ml.signals.cross_model_scorer import CrossModelScorer
from ml.signals.pick_angle_builder import build_pick_angles
from ml.signals.player_blacklist import compute_player_blacklist
from ml.signals.model_direction_affinity import compute_model_direction_affinities
from ml.signals.subset_membership_lookup import lookup_qualifying_subsets
from ml.signals.aggregator import ALGORITHM_VERSION
from ml.signals.ultra_bets import compute_ultra_live_hrs, check_ultra_over_gate
from data_processors.publishing.signal_subset_materializer import SignalSubsetMaterializer
from ml.signals.supplemental_data import (
    query_model_health,
    query_predictions_with_supplements,
    query_games_vs_opponent,
)
from shared.config.model_selection import get_best_bets_model_id

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class SignalBestBetsExporter(BaseExporter):
    """
    Export signal-curated best bets to GCS and BigQuery.

    Steps:
    1. Query model health (rolling 7d HR) — informational, does not block
    2. Query today's predictions + supplemental data
    3. Run all signals via registry
    4. Aggregate picks (edge-first, natural sizing, 10+ negative filters)
    5. Write to BigQuery `signal_best_bets_picks`
    6. Export to GCS `v1/signal-best-bets/{date}.json`
    """

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Generate signal best bets JSON for a specific date."""
        # Step 1: Query model health
        model_health = self._query_model_health()
        hr_7d = model_health.get('hit_rate_7d_edge3')

        health_status = 'unknown'
        if hr_7d is not None:
            if hr_7d < BREAKEVEN_HR:
                health_status = 'blocked'
            elif hr_7d < 58.0:
                health_status = 'watch'
            else:
                health_status = 'healthy'

        # Session 347: Health gate REMOVED. The gate blocked ALL picks when the
        # champion model's raw edge 3+ HR dropped below 52.4%, but the actual
        # signal best bets (after 10+ negative filters) were hitting 62.8%
        # (27-16 since Jan 28). The gate measured single-model raw HR to block
        # multi-model filtered output — a category error. The filter pipeline
        # (player blacklist, model-direction affinity, bench-under block, etc.)
        # is the correct quality control mechanism, not a blunt system shutdown.
        # Health status is still computed and included in JSON for transparency.
        if health_status == 'blocked':
            logger.info(
                f"Model health below breakeven for {target_date} — "
                f"HR 7d = {hr_7d:.1f}% < {BREAKEVEN_HR}% "
                f"(informational only, picks NOT blocked)"
            )

        # Step 1b: Query prediction-independent metadata (needed for both
        # 0-prediction early return and full path)
        signal_health = {}
        try:
            signal_health = get_signal_health_summary(self.bq_client, target_date)
        except Exception as e:
            logger.warning(f"Signal health query failed (non-fatal): {e}")

        direction_health = {'over_hr_14d': None, 'under_hr_14d': None,
                            'over_n': 0, 'under_n': 0}
        try:
            direction_health = self._query_direction_health(target_date)
        except Exception as e:
            logger.warning(f"Direction health query failed (non-fatal): {e}")

        player_blacklist = set()
        blacklist_stats = {'evaluated': 0, 'blacklisted': 0, 'players': []}
        try:
            player_blacklist, blacklist_stats = compute_player_blacklist(
                self.bq_client, target_date
            )
        except Exception as e:
            logger.warning(f"Player blacklist computation failed (non-fatal): {e}")

        # Model-direction affinity (Session 330): compute which model+direction
        # +edge combos have proven poor hit rates
        model_dir_affinities = {}
        model_dir_blocks = set()
        model_dir_stats = {'combos_evaluated': 0, 'combos_blocked': 0,
                           'blocked_list': [], 'observation_mode': True}
        try:
            model_dir_affinities, model_dir_blocks, model_dir_stats = \
                compute_model_direction_affinities(
                    self.bq_client, target_date, PROJECT_ID
                )
        except Exception as e:
            logger.warning(f"Model-direction affinity computation failed (non-fatal): {e}")

        record = self._get_best_bets_record(target_date)

        # Cap player list in output to top 10 worst (avoid bloating JSON)
        blacklist_players_capped = [
            p['player_lookup'] for p in blacklist_stats.get('players', [])[:10]
        ]

        # Step 2: Query predictions and supplemental data
        predictions, supplemental_map = self._query_predictions_and_supplements(
            target_date
        )

        # Step 2b: Filter out predictions for games already started (Session 370)
        # Hourly re-exports were adding picks for in-progress/finished games
        predictions, started_game_ids = self._filter_started_games(
            target_date, predictions
        )

        if not predictions:
            logger.info(f"No predictions found for {target_date}")
            target_0 = (
                date.fromisoformat(target_date) if isinstance(target_date, str)
                else target_date
            )
            season_start_year_0 = target_0.year if target_0.month >= 10 else target_0.year - 1
            season_label_0 = f"{season_start_year_0}-{str(season_start_year_0 + 1)[-2:]}"
            return {
                'date': target_date,
                'season': season_label_0,
                'generated_at': self.get_generated_at(),
                'min_signal_count': BestBetsAggregator.MIN_SIGNAL_COUNT,
                'record': record,
                'model_health': {
                    'status': health_status,
                    'hit_rate_7d': hr_7d,
                    'graded_count': model_health.get('graded_count', 0),
                },
                'signal_health': signal_health,
                'player_blacklist': {
                    'count': blacklist_stats.get('blacklisted', 0),
                    'evaluated': blacklist_stats.get('evaluated', 0),
                    'hr_threshold': 40.0,
                    'min_picks': 8,
                    'players': blacklist_players_capped,
                },
                'direction_health': direction_health,
                'model_direction_affinity': {
                    'observation_mode': model_dir_stats.get('observation_mode', True),
                    'combos_evaluated': model_dir_stats.get('combos_evaluated', 0),
                    'combos_blocked': model_dir_stats.get('combos_blocked', 0),
                    'blocked_list': model_dir_stats.get('blocked_list', []),
                    'would_block_at_45': model_dir_stats.get('would_block_at_45', []),
                    'affinities': model_dir_affinities,
                },
                'filter_summary': {
                    'total_candidates': 0,
                    'passed_filters': 0,
                    'rejected': {},
                },
                'edge_distribution': {
                    'total_predictions': 0,
                    'edge_3_plus': 0,
                    'edge_5_plus': 0,
                    'edge_7_plus': 0,
                    'max_edge': None,
                },
                'started_games_filtered': sorted(started_game_ids) if started_game_ids else [],
                'picks': [],
                'total_picks': 0,
                'signals_evaluated': [],
            }

        # Step 4: Evaluate all signals
        registry = build_default_registry()
        signal_results = {}

        for pred in predictions:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            supplements = supplemental_map.get(pred['player_lookup'], {})
            # Inject model health into supplemental for the gate signal
            supplements['model_health'] = {
                'hit_rate_7d_edge3': hr_7d,
            }

            results_for_pred = []
            for signal in registry.all():
                result = signal.evaluate(pred, features=None, supplemental=supplements)
                results_for_pred.append(result)
            signal_results[key] = results_for_pred

        # Step 4b: Materialize signal subsets (Session 311)
        # Writes signal-based subset picks to current_subset_picks for grading
        version_id = kwargs.get('version_id')
        try:
            signal_mat = SignalSubsetMaterializer()
            signal_mat_result = signal_mat.materialize(
                game_date=target_date,
                version_id=version_id or f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                predictions=predictions,
                signal_results=signal_results,
            )
            logger.info(
                f"Signal subsets: {signal_mat_result.get('total_picks', 0)} picks "
                f"across {len([v for v in signal_mat_result.get('subsets', {}).values() if v > 0])} subsets"
            )
        except Exception as e:
            logger.warning(f"Signal subset materialization failed (non-fatal): {e}", exc_info=True)

        # Step 5: Compute cross-model consensus factors (Session 277)
        cross_model_factors = {}
        try:
            scorer = CrossModelScorer()
            cross_model_factors = scorer.compute_factors(
                self.bq_client, target_date, PROJECT_ID
            )
        except Exception as e:
            logger.warning(f"Cross-model scoring failed (non-fatal): {e}")

        # Step 5b: Look up qualifying subsets (Session 279 — pick provenance)
        qual_subsets = {}
        if version_id:
            try:
                qual_subsets = lookup_qualifying_subsets(
                    self.bq_client, target_date, version_id, PROJECT_ID
                )
            except Exception as e:
                logger.warning(f"Qualifying subsets lookup failed (non-fatal): {e}")

        # Step 5c: Enrich predictions with games_vs_opponent (Session 284)
        # Avoid-familiar filter: players with 6+ games vs opponent regress
        try:
            gvo_map = query_games_vs_opponent(self.bq_client, target_date)
            for pred in predictions:
                opp = pred.get('opponent_team_abbr', '')
                pred['games_vs_opponent'] = gvo_map.get(
                    (pred['player_lookup'], opp), 0
                )
        except Exception as e:
            logger.warning(f"Games vs opponent enrichment failed (non-fatal): {e}")

        # Step 5d: Compute edge distribution before filtering
        edges = [abs(p.get('edge') or 0) for p in predictions]
        edge_distribution = {
            'total_predictions': len(predictions),
            'edge_3_plus': sum(1 for e in edges if e >= 3.0),
            'edge_5_plus': sum(1 for e in edges if e >= 5.0),
            'edge_7_plus': sum(1 for e in edges if e >= 7.0),
            'max_edge': round(max(edges), 1) if edges else None,
        }

        # Step 6: Aggregate to top picks (with combo registry + signal health weighting + consensus)
        combo_registry = load_combo_registry(bq_client=self.bq_client)
        aggregator = BestBetsAggregator(
            combo_registry=combo_registry,
            signal_health=signal_health,
            cross_model_factors=cross_model_factors,
            qualifying_subsets=qual_subsets,
            player_blacklist=player_blacklist,
            model_direction_blocks=model_dir_blocks,
            model_direction_affinity_stats=model_dir_stats,
        )
        top_picks, filter_summary = aggregator.aggregate(predictions, signal_results)

        # Step 6b: Build pick angles (Session 278, 284: direction health, 330: model-direction)
        for pick in top_picks:
            key = f"{pick['player_lookup']}::{pick['game_id']}"
            pick['pick_angles'] = build_pick_angles(
                pick, signal_results.get(key, []), cross_model_factors.get(key, {}),
                direction_health=direction_health,
                model_direction_affinities=model_dir_affinities,
            )

        # Step 6c: Enrich ultra criteria with live HRs (Session 327)
        # Live HRs are written to BQ for internal monitoring but stripped
        # from the public JSON export.
        try:
            ultra_live = compute_ultra_live_hrs(self.bq_client, PROJECT_ID)
            for pick in top_picks:
                for crit in pick.get('ultra_criteria', []):
                    live = ultra_live.get(crit['id'], {})
                    crit['live_hr'] = live.get('live_hr')
                    crit['live_n'] = live.get('live_n', 0)
        except Exception as e:
            logger.warning(f"Ultra live HR enrichment failed (non-fatal): {e}")

        # Step 6d: Check ultra OVER gate for public exposure (Session 328)
        ultra_over_gate = {'gate_met': False, 'n': 0, 'hr': None}
        try:
            ultra_over_gate = check_ultra_over_gate(self.bq_client, PROJECT_ID)
        except Exception as e:
            logger.warning(f"Ultra OVER gate check failed (non-fatal): {e}")

        # Step 6e: Look up game times from schedule (Session 328)
        game_times = self._query_game_times(target_date, top_picks)

        # Step 6f: 1-pick day low conviction annotation (Session 369)
        # 1-pick days = 50.0% HR (7W-7L) vs multi-pick days = 69.8% (67W-29L)
        daily_pick_count = len(top_picks)
        if daily_pick_count == 1:
            top_picks[0].setdefault('warning_tags', []).append('low_conviction_day')
            top_picks[0].setdefault('pick_angles', []).append(
                'Only 1 pick today — lower conviction environment'
            )
            logger.info("1-pick day: added low_conviction_day warning")

        # Step 7: Format for JSON
        # ultra_tier included on OVER picks ONLY when the gate is met.
        # ultra_criteria always excluded from public JSON.
        picks_json = []
        for pick in top_picks:
            game_id = pick.get('game_id', '')

            # Ultra tier: expose on OVER picks only when gate is met
            show_ultra = (
                ultra_over_gate['gate_met']
                and pick.get('ultra_tier')
                and pick.get('recommendation') == 'OVER'
            )

            pick_dict = {
                'rank': pick['rank'],
                'player': pick.get('player_name', ''),
                'player_lookup': pick['player_lookup'],
                'game_id': game_id,
                'team': pick.get('team_abbr', ''),
                'opponent': pick.get('opponent_team_abbr', ''),
                'prediction': pick.get('predicted_points'),
                'line': pick.get('line_value'),
                'direction': pick.get('recommendation', ''),
                'stat': 'PTS',
                'edge': pick.get('edge'),
                'confidence': pick.get('confidence_score'),
                'signals': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'composite_score': pick.get('composite_score'),
                'matched_combo_id': pick.get('matched_combo_id'),
                'combo_classification': pick.get('combo_classification'),
                'combo_hit_rate': pick.get('combo_hit_rate'),
                'warnings': pick.get('warning_tags', []),
                'angles': pick.get('pick_angles', []),
                'model_agreement': pick.get('model_agreement_count', 0),
                'agreeing_models': pick.get('agreeing_model_ids', []),
                'feature_diversity': pick.get('feature_set_diversity', 0),
                'consensus_bonus': pick.get('consensus_bonus', 0),
                'quantile_under_consensus': pick.get('quantile_consensus_under', False),
                'qualifying_subsets': pick.get('qualifying_subsets', []),
                'qualifying_subset_count': pick.get('qualifying_subset_count', 0),
                'algorithm_version': pick.get('algorithm_version', ALGORITHM_VERSION),
                'system_id': pick.get('system_id'),
                # Multi-source attribution (Session 307)
                'source_model': pick.get('source_model_id'),
                'source_model_family': pick.get('source_model_family'),
                'n_models_eligible': pick.get('n_models_eligible', 0),
                'champion_edge': pick.get('champion_edge'),
                'direction_conflict': pick.get('direction_conflict', False),
                'actual': None,
                'result': None,
            }

            # Game time from schedule (Session 328)
            gt = game_times.get(game_id)
            pick_dict['game_time'] = gt if gt else None

            # Ultra tier: only OVER picks when gate met (Session 328)
            if show_ultra:
                pick_dict['ultra_tier'] = True

            picks_json.append(pick_dict)

        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        season_start_year = target.year if target.month >= 10 else target.year - 1
        season_label = f"{season_start_year}-{str(season_start_year + 1)[-2:]}"

        return {
            'date': target_date,
            'season': season_label,
            'generated_at': self.get_generated_at(),
            'min_signal_count': BestBetsAggregator.MIN_SIGNAL_COUNT,
            'record': record,
            'model_health': {
                'status': health_status,
                'hit_rate_7d': hr_7d,
                'graded_count': model_health.get('graded_count', 0),
            },
            'signal_health': signal_health,
            'player_blacklist': {
                'count': blacklist_stats.get('blacklisted', 0),
                'evaluated': blacklist_stats.get('evaluated', 0),
                'hr_threshold': 40.0,
                'min_picks': 8,
                'players': blacklist_players_capped,
            },
            'direction_health': direction_health,
            'model_direction_affinity': {
                'observation_mode': model_dir_stats.get('observation_mode', True),
                'combos_evaluated': model_dir_stats.get('combos_evaluated', 0),
                'combos_blocked': model_dir_stats.get('combos_blocked', 0),
                'blocked_list': model_dir_stats.get('blocked_list', []),
                'would_block_at_45': model_dir_stats.get('would_block_at_45', []),
                'affinities': model_dir_affinities,
            },
            'health_gate_active': False,
            'filter_summary': filter_summary,
            'edge_distribution': edge_distribution,
            'started_games_filtered': sorted(started_game_ids) if started_game_ids else [],
            'daily_pick_count': daily_pick_count,
            'low_conviction_day': daily_pick_count == 1,
            # ultra_bets removed from JSON (Session 327 — internal-only, in BQ)
            'picks': picks_json,
            'total_picks': len(picks_json),
            'signals_evaluated': [
                s.tag for s in registry.all() if s.tag != 'model_health'
            ],
        }

    def export(self, target_date: str, version_id: str = None) -> str:
        """
        Generate signal best bets, write to BigQuery, and upload to GCS.

        Args:
            target_date: Date string in YYYY-MM-DD format
            version_id: Optional version_id for qualifying subset lookup.

        Returns:
            GCS path where file was uploaded
        """
        json_data = self.generate_json(target_date, version_id=version_id)

        # Write picks to BigQuery for grading tracking
        if json_data['picks']:
            self._write_to_bigquery(
                target_date, json_data['picks'],
                filter_summary=json_data.get('filter_summary'),
            )

        # Upload to GCS (date-specific)
        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path=f'signal-best-bets/{target_date}.json',
            cache_control='public, max-age=300',
        )

        # Also write latest.json for stable frontend URL
        try:
            self.upload_to_gcs(
                json_data=json_data,
                path='signal-best-bets/latest.json',
                cache_control='public, max-age=60',
            )
            logger.info("Wrote signal-best-bets/latest.json")
        except Exception as e:
            logger.warning(f"Failed to write latest.json (non-fatal): {e}")

        # Also write best-bets/latest.json for backward compatibility
        # (legacy BestBetsExporter was decommissioned; this maintains the endpoint)
        try:
            self.upload_to_gcs(
                json_data=json_data,
                path='best-bets/latest.json',
                cache_control='public, max-age=60',
            )
            logger.info("Wrote best-bets/latest.json (backward compat)")
        except Exception as e:
            logger.warning(f"Failed to write best-bets/latest.json (non-fatal): {e}")

        logger.info(
            f"Exported {json_data['total_picks']} signal best bets for {target_date} "
            f"(health={json_data['model_health']['status']}) to {gcs_path}"
        )

        return gcs_path

    # ── Private helpers ──────────────────────────────────────────────────

    def _query_model_health(self) -> Dict[str, Any]:
        """Query rolling 7-day hit rate for edge 3+ picks."""
        return query_model_health(self.bq_client)

    def _query_predictions_and_supplements(self, target_date: str) -> tuple:
        """Query today's active predictions with supplemental signal data.

        Uses multi_model=True to query all CatBoost families and pick the
        highest-edge prediction per player (Session 307 Phase A).
        """
        return query_predictions_with_supplements(
            self.bq_client, target_date, multi_model=True,
        )

    def _write_to_bigquery(
        self,
        target_date: str,
        picks: List[Dict],
        filter_summary: Optional[Dict] = None,
    ) -> None:
        """Write signal best bets to BigQuery using batch load (not streaming).

        Deletes existing rows for the target date first to prevent duplicate
        accumulation on re-runs (Session 297: fixed triple-write bug).

        Uses load_table_from_json with WRITE_APPEND to avoid 90-min streaming
        buffer that blocks DML operations (codebase best practice).
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks'

        # Delete existing rows for this date to prevent duplicates on re-runs
        try:
            delete_query = f"""
            DELETE FROM `{table_ref}`
            WHERE game_date = @target_date
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        'target_date', 'DATE', target_date
                    ),
                ]
            )
            delete_job = self.bq_client.query(delete_query, job_config=job_config)
            result = delete_job.result(timeout=30)
            deleted = delete_job.num_dml_affected_rows or 0
            if deleted > 0:
                logger.info(
                    f"Deleted {deleted} existing rows for {target_date} "
                    f"from {table_ref}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to delete existing rows for {target_date} "
                f"(will append anyway): {e}"
            )

        rows_to_insert = []
        for pick in picks:
            rows_to_insert.append({
                'player_lookup': pick['player_lookup'],
                'game_id': pick.get('game_id', ''),
                'game_date': target_date,
                'system_id': pick.get('system_id') or pick.get('source_model') or 'catboost_v9',
                'player_name': pick.get('player', ''),
                'team_abbr': pick.get('team', ''),
                'opponent_team_abbr': pick.get('opponent', ''),
                'predicted_points': pick.get('prediction'),
                'line_value': pick.get('line'),
                'recommendation': pick.get('direction', ''),
                'edge': round(float(pick.get('edge') or 0), 1),
                'confidence_score': round(min(float(pick.get('confidence') or 0), 9.999), 3),
                'signal_tags': pick.get('signals', []),
                'signal_count': pick.get('signal_count', 0),
                'composite_score': pick.get('composite_score'),
                'matched_combo_id': pick.get('matched_combo_id'),
                'combo_classification': pick.get('combo_classification'),
                'combo_hit_rate': pick.get('combo_hit_rate'),
                'warning_tags': pick.get('warnings', []),
                'rank': pick.get('rank'),
                'model_agreement_count': pick.get('model_agreement', 0),
                'agreeing_model_ids': pick.get('agreeing_models', []),
                'feature_set_diversity': pick.get('feature_diversity', 0),
                'consensus_bonus': pick.get('consensus_bonus', 0),
                'quantile_consensus_under': pick.get('quantile_under_consensus', False),
                'pick_angles': pick.get('angles', []),
                'qualifying_subsets': json.dumps(pick.get('qualifying_subsets', []), default=str),
                'qualifying_subset_count': pick.get('qualifying_subset_count', 0),
                'algorithm_version': pick.get('algorithm_version', ALGORITHM_VERSION),
                # Multi-source attribution (Session 307)
                'source_model_id': pick.get('source_model'),
                'source_model_family': pick.get('source_model_family'),
                'n_models_eligible': pick.get('n_models_eligible'),
                'champion_edge': (
                    round(float(pick['champion_edge']), 1)
                    if pick.get('champion_edge') is not None else None
                ),
                'direction_conflict': pick.get('direction_conflict'),
                'filter_summary': json.dumps(filter_summary, default=str) if filter_summary else None,
                # Ultra Bets (Session 326)
                'ultra_tier': pick.get('ultra_tier', False),
                'ultra_criteria': json.dumps(pick.get('ultra_criteria', []), default=str),
                'created_at': datetime.now(timezone.utc).isoformat(),
            })

        if not rows_to_insert:
            return

        try:
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(
                rows_to_insert, table_ref, job_config=job_config
            )
            load_job.result(timeout=60)
            logger.info(
                f"Batch-loaded {len(rows_to_insert)} rows into {table_ref} "
                f"for {target_date}"
            )
        except Exception as e:
            logger.error(
                f"Failed to write signal best bets to BigQuery: {e}",
                exc_info=True,
            )

    def _query_direction_health(self, target_date: str) -> Dict[str, Any]:
        """Query 14-day rolling hit rate by direction (OVER vs UNDER).

        Returns dict with over_hr_14d, under_hr_14d, over_n, under_n.
        Observation-only (Session 284): monitors direction stability.
        """
        model_id = get_best_bets_model_id()

        query = f"""
        SELECT
            recommendation,
            COUNT(*) AS n,
            ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) AS hr
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
          AND game_date < @target_date
          AND system_id = @model_id
          AND ABS(predicted_points - line_value) >= 3
          AND is_voided = FALSE
          AND recommendation IN ('OVER', 'UNDER')
        GROUP BY recommendation
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
                bigquery.ScalarQueryParameter('model_id', 'STRING', model_id),
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result(timeout=30)

        health = {'over_hr_14d': None, 'under_hr_14d': None,
                  'over_n': 0, 'under_n': 0}
        for row in result:
            if row.recommendation == 'OVER':
                health['over_hr_14d'] = float(row.hr) if row.hr else None
                health['over_n'] = row.n
            elif row.recommendation == 'UNDER':
                health['under_hr_14d'] = float(row.hr) if row.hr else None
                health['under_n'] = row.n

        logger.info(
            f"Direction health 14d: OVER={health['over_hr_14d']}% "
            f"(N={health['over_n']}), UNDER={health['under_hr_14d']}% "
            f"(N={health['under_n']})"
        )
        return health

    def _query_game_times(
        self, target_date: str, picks: List[Dict]
    ) -> Dict[str, str]:
        """Look up game start times from schedule for today's picks.

        Joins via team tricode pairs since predictions use game_id format
        'YYYYMMDD_AWAY_HOME' while schedule uses numeric game_id.

        Returns:
            Dict mapping prediction game_id → ISO 8601 datetime string.
        """
        if not picks:
            return {}

        query = f"""
        SELECT
          away_team_tricode,
          home_team_tricode,
          game_date_est
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result(timeout=30)

            # Build lookup: "AWAY_HOME" → ISO timestamp
            schedule_times = {}
            for row in rows:
                away = row.away_team_tricode
                home = row.home_team_tricode
                if row.game_date_est:
                    # Format as ISO 8601 with ET offset
                    ts = row.game_date_est
                    if hasattr(ts, 'isoformat'):
                        schedule_times[f"{away}_{home}"] = ts.isoformat()

            # Map prediction game_ids to times
            # game_id format: "YYYYMMDD_AWAY_HOME"
            result = {}
            for pick in picks:
                gid = pick.get('game_id', '')
                parts = gid.split('_', 1)
                if len(parts) == 2:
                    team_key = parts[1]  # "AWAY_HOME"
                    if team_key in schedule_times:
                        result[gid] = schedule_times[team_key]

            return result
        except Exception as e:
            logger.warning(f"Game times lookup failed (non-fatal): {e}")
            return {}

    def _filter_started_games(
        self, target_date: str, predictions: List[Dict]
    ) -> tuple:
        """Remove predictions for games already in progress or finished.

        Queries nba_raw.nbac_schedule for game_status and filters out any
        predictions where game_status >= 2 (In Progress or Final).

        Also writes removed predictions to the late_picks_audit table for
        persistent tracking (Session 371).

        Returns:
            Tuple of (filtered_predictions, set of started game_ids that were removed).
        """
        if not predictions:
            return predictions, set()

        query = f"""
        SELECT
          away_team_tricode,
          home_team_tricode,
          game_status
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
          AND game_status >= 2
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result(timeout=30)

            # Build map of started game team pairs: "AWAY_HOME" → game_status
            started_games = {}
            for row in rows:
                key = f"{row.away_team_tricode}_{row.home_team_tricode}"
                started_games[key] = row.game_status

            if not started_games:
                return predictions, set()

            # Filter predictions — game_id format: "YYYYMMDD_AWAY_HOME"
            filtered = []
            removed_preds = []
            removed_game_ids = set()
            for pred in predictions:
                gid = pred.get('game_id', '')
                parts = gid.split('_', 1)
                if len(parts) == 2 and parts[1] in started_games:
                    pred['_game_status'] = started_games[parts[1]]
                    removed_preds.append(pred)
                    removed_game_ids.add(gid)
                else:
                    filtered.append(pred)

            if removed_preds:
                logger.warning(
                    f"Filtered {len(removed_preds)} predictions for {len(removed_game_ids)} "
                    f"started/finished games: {sorted(removed_game_ids)}"
                )
                self._write_late_picks_audit(target_date, removed_preds)

            return filtered, removed_game_ids

        except Exception as e:
            logger.warning(f"Started game filter failed (non-fatal): {e}")
            return predictions, set()

    def _write_late_picks_audit(
        self, target_date: str, removed_preds: List[Dict]
    ) -> None:
        """Write filtered-out predictions to late_picks_audit for tracking.

        Non-fatal — audit failure does not block the export pipeline.
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.late_picks_audit'
        now_utc = datetime.now(timezone.utc).isoformat()

        rows = []
        for pred in removed_preds:
            rows.append({
                'audit_date': target_date,
                'game_id': pred.get('game_id', ''),
                'game_date': target_date,
                'player_lookup': pred.get('player_lookup', ''),
                'source_model_id': pred.get('source_model_id'),
                'recommendation': pred.get('recommendation'),
                'edge': round(float(pred.get('edge') or 0), 1),
                'signal_count': pred.get('signal_count', 0),
                'game_status': pred.get('_game_status'),
                'prediction_created_at': pred.get('prediction_created_at'),
                'export_attempted_at': now_utc,
                'filter_action': 'BLOCKED_STARTED_GAME',
                'algorithm_version': pred.get('algorithm_version'),
            })

        try:
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(
                rows, table_ref, job_config=job_config
            )
            load_job.result(timeout=30)
            logger.info(
                f"Wrote {len(rows)} late picks to {table_ref} for {target_date}"
            )
        except Exception as e:
            logger.warning(f"Late picks audit write failed (non-fatal): {e}")

    def _get_best_bets_record(self, target_date: str) -> Dict[str, Any]:
        """Query W-L record for the best_bets subset across season/month/week.

        Uses the same v_dynamic_subset_performance view as AllSubsetsPicksExporter
        but filtered to subset_id='best_bets' only.

        Returns:
            Dict with season/month/week windows, each having wins/losses/pct.
        """
        empty_window = {'wins': 0, 'losses': 0, 'pct': 0.0}
        empty_record = {
            'season': empty_window.copy(),
            'month': empty_window.copy(),
            'week': empty_window.copy(),
        }

        target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date

        # Calendar-aligned windows (same logic as AllSubsetsPicksExporter)
        season_start_year = target.year if target.month >= 11 else target.year - 1
        season_start = date(season_start_year, 11, 1)
        month_start = target.replace(day=1)
        week_start = target - timedelta(days=target.weekday())

        query = """
        WITH base AS (
          SELECT game_date, wins, graded_picks
          FROM `nba_predictions.v_dynamic_subset_performance`
          WHERE subset_id = 'best_bets'
            AND game_date >= @season_start
            AND game_date < @end_date
        )
        SELECT
          SUM(wins) as season_wins,
          SUM(graded_picks - wins) as season_losses,
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as season_pct,
          SUM(CASE WHEN game_date >= @month_start THEN wins ELSE 0 END) as month_wins,
          SUM(CASE WHEN game_date >= @month_start THEN graded_picks - wins ELSE 0 END) as month_losses,
          ROUND(100.0 *
            SUM(CASE WHEN game_date >= @month_start THEN wins ELSE 0 END) /
            NULLIF(SUM(CASE WHEN game_date >= @month_start THEN graded_picks ELSE 0 END), 0),
          1) as month_pct,
          SUM(CASE WHEN game_date >= @week_start THEN wins ELSE 0 END) as week_wins,
          SUM(CASE WHEN game_date >= @week_start THEN graded_picks - wins ELSE 0 END) as week_losses,
          ROUND(100.0 *
            SUM(CASE WHEN game_date >= @week_start THEN wins ELSE 0 END) /
            NULLIF(SUM(CASE WHEN game_date >= @week_start THEN graded_picks ELSE 0 END), 0),
          1) as week_pct
        FROM base
        """

        params = [
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start.isoformat()),
            bigquery.ScalarQueryParameter('month_start', 'DATE', month_start.isoformat()),
            bigquery.ScalarQueryParameter('week_start', 'DATE', week_start.isoformat()),
            bigquery.ScalarQueryParameter('end_date', 'DATE', target_date),
        ]

        try:
            results = self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query best_bets record: {e}")
            return empty_record

        if not results or results[0].get('season_wins') is None:
            return empty_record

        r = results[0]
        return {
            'season': {
                'wins': int(r.get('season_wins') or 0),
                'losses': int(r.get('season_losses') or 0),
                'pct': float(r.get('season_pct') or 0),
            },
            'month': {
                'wins': int(r.get('month_wins') or 0),
                'losses': int(r.get('month_losses') or 0),
                'pct': float(r.get('month_pct') or 0),
            },
            'week': {
                'wins': int(r.get('week_wins') or 0),
                'losses': int(r.get('week_losses') or 0),
                'pct': float(r.get('week_pct') or 0),
            },
        }
