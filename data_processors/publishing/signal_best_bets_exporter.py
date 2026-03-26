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
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.model_health import BREAKEVEN_HR
from ml.signals.pick_angle_builder import build_pick_angles
from ml.signals.ultra_bets import compute_ultra_live_hrs, check_ultra_over_gate
from data_processors.publishing.signal_subset_materializer import SignalSubsetMaterializer
from ml.signals.per_model_pipeline import run_all_model_pipelines
from ml.signals.pipeline_merger import merge_model_pipelines, ALGORITHM_VERSION
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
        """Generate signal best bets JSON for a specific date.

        Session 443: Uses per-model pipelines + merger instead of single-pipeline.
        Each model runs the full signal/filter stack independently, then a merge
        layer pools candidates and applies team cap, rescue cap, volume cap.
        """
        # ── Step 1: Run all per-model pipelines (builds shared context internally) ──
        # This replaces the old steps 1-6 (model health, signal health, blacklist,
        # affinity, predictions, signals, cross-model scorer, aggregator).
        # One big query per date + satellite queries, then pure Python per model.
        pipeline_results, shared_ctx = run_all_model_pipelines(
            self.bq_client, target_date
        )

        # Extract metadata from shared context for JSON output
        hr_7d = shared_ctx.default_model_health_hr
        health_status = 'unknown'
        if hr_7d is not None:
            if hr_7d < BREAKEVEN_HR:
                health_status = 'blocked'
            elif hr_7d < 58.0:
                health_status = 'watch'
            else:
                health_status = 'healthy'

        if health_status == 'blocked':
            logger.info(
                f"Model health below breakeven for {target_date} — "
                f"HR 7d = {hr_7d:.1f}% < {BREAKEVEN_HR}% "
                f"(informational only, picks NOT blocked)"
            )

        signal_health = shared_ctx.signal_health
        direction_health = shared_ctx.direction_health
        blacklist_stats = shared_ctx.blacklist_stats
        model_dir_stats = shared_ctx.model_direction_affinity_stats
        regime_ctx = shared_ctx.regime_context

        record = self._get_best_bets_record(target_date)

        # Cap player list in output to top 10 worst (avoid bloating JSON)
        blacklist_players_capped = [
            p['player_lookup'] for p in blacklist_stats.get('players', [])[:10]
        ]

        # ── Step 1b: Early return if no predictions found ──
        all_predictions_flat = [
            pred
            for preds in shared_ctx.all_predictions.values()
            for pred in preds
        ]

        if not all_predictions_flat:
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
                    'graded_count': 0,
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
                    'affinities': {},
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
                'started_games_filtered': [],
                'picks': [],
                'total_picks': 0,
                'signals_evaluated': [],
            }

        # ── Step 2: Merge model pipelines ──
        # Collect candidates from each model's pipeline result
        # Tag source_pipeline BEFORE merge (merger uses it for agreement counting)
        model_candidates = {}
        for system_id, result in pipeline_results.items():
            for cand in result.candidates:
                cand['source_pipeline'] = system_id
            model_candidates[system_id] = result.candidates
        top_picks, merge_summary = merge_model_pipelines(model_candidates)

        # ── Step 2b: Filter started games on merged picks ──
        top_picks, started_game_ids = self._filter_started_games(
            target_date, top_picks
        )

        # ── Step 2c: Compute edge distribution from all predictions (pre-filter) ──
        edges = [abs(p.get('edge') or 0) for p in all_predictions_flat]
        edge_distribution = {
            'total_predictions': len(all_predictions_flat),
            'edge_3_plus': sum(1 for e in edges if e >= 3.0),
            'edge_5_plus': sum(1 for e in edges if e >= 5.0),
            'edge_7_plus': sum(1 for e in edges if e >= 7.0),
            'max_edge': round(max(edges), 1) if edges else None,
        }

        # ── Step 2d: Build aggregate filter_summary from all per-model runs ──
        # Merge per-model filter summaries into a unified view for the JSON output
        # and for the filter_audit / filtered_picks writes in export().
        total_candidates_all = 0
        total_passed_all = 0
        merged_rejected: Dict[str, int] = {}
        merged_filtered_picks: List[Dict] = []
        for result in pipeline_results.values():
            fs = result.filter_summary
            total_candidates_all += fs.get('total_candidates', 0)
            total_passed_all += fs.get('passed_filters', 0)
            for filter_name, count in fs.get('rejected', {}).items():
                merged_rejected[filter_name] = merged_rejected.get(filter_name, 0) + count
            merged_filtered_picks.extend(fs.get('filtered_picks', []))

        filter_summary = {
            'total_candidates': total_candidates_all,
            'passed_filters': total_passed_all,
            'rejected': merged_rejected,
            'filtered_picks': merged_filtered_picks,
            'regime_context': regime_ctx,
            'merge_summary': merge_summary,
        }

        # ── Step 2e: Materialize signal subsets (Session 311) ──
        # Uses combined signal_results and a representative prediction list
        # (first model's predictions that have signal results)
        version_id = kwargs.get('version_id')
        combined_signal_results: Dict[str, List] = {}
        for result in pipeline_results.values():
            for key, sigs in result.signal_results.items():
                if key not in combined_signal_results:
                    combined_signal_results[key] = sigs

        # Use all_predictions_flat deduplicated by player_lookup for subset materialization
        seen_players_for_mat: set = set()
        deduped_predictions_for_mat: List[Dict] = []
        for pred in all_predictions_flat:
            pl = pred.get('player_lookup', '')
            if pl not in seen_players_for_mat:
                seen_players_for_mat.add(pl)
                deduped_predictions_for_mat.append(pred)

        try:
            signal_mat = SignalSubsetMaterializer()
            signal_mat_result = signal_mat.materialize(
                game_date=target_date,
                version_id=version_id or f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                predictions=deduped_predictions_for_mat,
                signal_results=combined_signal_results,
            )
            logger.info(
                f"Signal subsets: {signal_mat_result.get('total_picks', 0)} picks "
                f"across {len([v for v in signal_mat_result.get('subsets', {}).values() if v > 0])} subsets"
            )
        except Exception as e:
            logger.warning(f"Signal subset materialization failed (non-fatal): {e}", exc_info=True)

        # ── Step 3: Post-merge enrichment (pick angles, ultra bets, game times) ──

        # Build pick angles — cross_model_factors replaced by pipeline agreement.
        # build_pick_angles expects a dict with model_agreement_count, majority_direction,
        # avg_edge_agreeing. Build compatibility dicts from merger's pipeline_agreement data.
        for pick in top_picks:
            key = f"{pick['player_lookup']}::{pick['game_id']}"
            # Build compatibility cross_model_factors from pipeline agreement metadata
            agreement_count = pick.get('pipeline_agreement_count', 0)
            agreement_models = pick.get('pipeline_agreement_models', [])
            compat_factors = {
                'model_agreement_count': agreement_count,
                'majority_direction': pick.get('recommendation', ''),
                'avg_edge_agreeing': abs(pick.get('edge') or 0),
            }
            # Also set the pick-level fields that pick_angles/JSON formatting reads
            pick['model_agreement_count'] = agreement_count
            pick['agreeing_model_ids'] = agreement_models
            pick['feature_set_diversity'] = 0  # Not applicable in per-model pipeline
            pick['consensus_bonus'] = pick.get('consensus_bonus', 0)

            pick['pick_angles'] = build_pick_angles(
                pick,
                combined_signal_results.get(key, []),
                compat_factors,
                direction_health=direction_health,
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

        # Step 3b: Enrich ultra criteria with live HRs (Session 327)
        try:
            ultra_live = compute_ultra_live_hrs(self.bq_client, PROJECT_ID)
            for pick in top_picks:
                for crit in pick.get('ultra_criteria', []):
                    live = ultra_live.get(crit['id'], {})
                    crit['live_hr'] = live.get('live_hr')
                    crit['live_n'] = live.get('live_n', 0)
        except Exception as e:
            logger.warning(f"Ultra live HR enrichment failed (non-fatal): {e}")

        # Step 3c: Check ultra OVER gate for public exposure (Session 328)
        ultra_over_gate = {'gate_met': False, 'n': 0, 'hr': None}
        try:
            ultra_over_gate = check_ultra_over_gate(self.bq_client, PROJECT_ID)
        except Exception as e:
            logger.warning(f"Ultra OVER gate check failed (non-fatal): {e}")

        # Step 3d: Look up game times from schedule (Session 328)
        game_times = self._query_game_times(target_date, top_picks)

        # Step 3e: 1-pick day low conviction annotation (Session 369)
        daily_pick_count = len(top_picks)
        if daily_pick_count == 1:
            top_picks[0].setdefault('warning_tags', []).append('low_conviction_day')
            top_picks[0].setdefault('pick_angles', []).append(
                'Only 1 pick today — lower conviction environment'
            )
            logger.info("1-pick day: added low_conviction_day warning")

        # ── Step 4: Format for JSON ──
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
                'rank': pick.get('rank') or pick.get('merge_rank'),
                'player': pick.get('player_name', ''),
                'player_lookup': pick['player_lookup'],
                'game_id': game_id,
                'team': pick.get('team_abbr', ''),
                'opponent': pick.get('opponent_team_abbr', ''),
                'prediction': pick.get('predicted_points'),
                'line': pick.get('line_value'),
                'direction': pick.get('recommendation', ''),
                'stat': 'PTS',
                'edge': abs(pick.get('edge') or 0),
                'confidence': pick.get('confidence_score'),
                'signals': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'real_signal_count': pick.get('real_signal_count', 0),
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
                # Signal rescue (Session 398)
                'signal_rescued': pick.get('signal_rescued', False),
                'rescue_signal': pick.get('rescue_signal'),
                # Multi-source attribution (Session 307 / 443 per-model pipeline)
                'source_model': pick.get('source_model_id') or pick.get('source_pipeline'),
                'source_model_family': pick.get('source_model_family'),
                'n_models_eligible': pick.get('n_models_eligible', 0),
                'champion_edge': pick.get('champion_edge'),
                'direction_conflict': pick.get('direction_conflict', False),
                # Session 443: Per-model pipeline provenance
                'pipeline_agreement': pick.get('pipeline_agreement_count', 0),
                'pipeline_agreement_models': pick.get('pipeline_agreement_models', []),
                'source_pipeline': pick.get('source_pipeline'),
                # Session 422b: Fields that were in BQ write but missing from pick_dict
                'under_signal_quality': pick.get('under_signal_quality'),
                'model_hr_weight': pick.get('model_hr_weight'),
                'trend_slope': pick.get('trend_slope'),
                'spread_magnitude': pick.get('spread_magnitude'),
                'player_tier': pick.get('player_tier'),
                'tier_edge_cap_delta': pick.get('tier_edge_cap_delta'),
                'capped_composite_score': pick.get('capped_composite_score'),
                'compression_ratio': pick.get('compression_ratio'),
                'compression_scaled_edge': pick.get('compression_scaled_edge'),
                'actual': None,
                'result': None,
            }

            # Game time from schedule (Session 328)
            gt = game_times.get(game_id)
            pick_dict['game_time'] = gt if gt else None

            # Ultra data: always include for BQ write.
            # Public JSON visibility gated by show_ultra (stripped in export()).
            # Session 452: Derive ultra_tier from ultra_criteria presence to prevent
            # stale ultra_tier=True with empty criteria (76% of ultra picks were hollow).
            ultra_criteria = pick.get('ultra_criteria', [])
            pick_dict['ultra_tier'] = bool(ultra_criteria)
            pick_dict['ultra_criteria'] = ultra_criteria
            pick_dict['_show_ultra_public'] = show_ultra

            picks_json.append(pick_dict)

        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        season_start_year = target.year if target.month >= 10 else target.year - 1
        season_label = f"{season_start_year}-{str(season_start_year + 1)[-2:]}"

        # Build signals_evaluated from the signal registry used in pipelines
        from ml.signals.registry import build_default_registry
        _signal_registry = build_default_registry()
        signals_evaluated = [
            s.tag for s in _signal_registry.all() if s.tag != 'model_health'
        ]

        return {
            'date': target_date,
            'season': season_label,
            'generated_at': self.get_generated_at(),
            'min_signal_count': BestBetsAggregator.MIN_SIGNAL_COUNT,
            'record': record,
            'model_health': {
                'status': health_status,
                'hit_rate_7d': hr_7d,
                'graded_count': 0,
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
                'affinities': {},
            },
            'health_gate_active': False,
            'filter_summary': filter_summary,
            'edge_distribution': edge_distribution,
            'merge_summary': merge_summary,
            'started_games_filtered': sorted(started_game_ids) if started_game_ids else [],
            'daily_pick_count': daily_pick_count,
            'low_conviction_day': daily_pick_count == 1,
            'picks': picks_json,
            'total_picks': len(picks_json),
            'signals_evaluated': signals_evaluated,
            # Session 443: Store all model candidates for BQ write in export()
            '_model_bb_candidates': self._collect_all_model_candidates(
                pipeline_results, target_date
            ),
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

        # Session 403: Filter disabled model picks BEFORE any writes (BQ + GCS).
        # Previously this filter was inside _write_to_bigquery only, which meant
        # GCS got unfiltered picks while BQ got filtered — consistency gap.
        disabled_models = self._query_disabled_model_ids()
        if disabled_models and json_data['picks']:
            original_count = len(json_data['picks'])
            json_data['picks'] = [
                p for p in json_data['picks']
                if (p.get('system_id') or p.get('source_model') or '') not in disabled_models
            ]
            filtered = original_count - len(json_data['picks'])
            if filtered > 0:
                json_data['total_picks'] = len(json_data['picks'])
                logger.warning(
                    f"Filtered {filtered} picks from disabled models "
                    f"before export (BQ + GCS consistent)"
                )

        # Safety guard: don't overwrite existing JSON with 0 picks on re-export
        # of past dates (all games finished → all predictions filtered out).
        if not json_data['picks'] and json_data.get('started_games_filtered'):
            logger.warning(
                f"Re-export safety: {target_date} has 0 picks after filtering "
                f"{len(json_data['started_games_filtered'])} started games. "
                f"Skipping GCS upload to preserve existing data."
            )
            return f'signal-best-bets/{target_date}.json (skipped — all games started)'

        # Session 412: True pick locking — log lock behavior before BQ write.
        # Existing picks not in current signal output are preserved in BQ.
        existing_lookups = self._query_existing_pick_lookups(target_date)
        new_lookups = {p['player_lookup'] for p in json_data['picks']}
        preserved_lookups = existing_lookups - new_lookups
        truly_new_lookups = new_lookups - existing_lookups
        if preserved_lookups:
            logger.info(
                f"Pick locking: preserving {len(preserved_lookups)} locked picks "
                f"not in current signal output "
                f"({len(truly_new_lookups)} truly new, "
                f"{len(new_lookups & existing_lookups)} refreshed)"
            )

        # Write picks to BigQuery for grading tracking (includes full ultra data)
        if json_data['picks']:
            self._write_to_bigquery(
                target_date, json_data['picks'],
                filter_summary=json_data.get('filter_summary'),
            )

        # Session 443: Write ALL model candidates to model_bb_candidates BQ table
        # for historical analysis and pipeline-level HR computation.
        model_bb_candidates = json_data.pop('_model_bb_candidates', [])
        if model_bb_candidates:
            self._write_model_bb_candidates(target_date, model_bb_candidates)

        # Session 391: Write filter summary audit trail for historical analysis.
        # Persists rejection counts so we can retroactively detect patterns like
        # "legacy_block dominated 77% of candidates for 3 days before being caught."
        filter_summary = json_data.get('filter_summary')
        if filter_summary:
            self._write_filter_audit(target_date, json_data, filter_summary)

        # Session 393: Write filtered-out picks for counterfactual tracking.
        # Enables post-hoc grading: "would this pick have won if we didn't filter it?"
        filtered_picks = filter_summary.get('filtered_picks', []) if filter_summary else []
        if filtered_picks:
            self._write_filtered_picks(target_date, filtered_picks)

        # Strip internal-only fields from public JSON.
        # BQ write above gets full ultra_tier + ultra_criteria.
        # Public JSON shows ultra_tier (bool) but not ultra_criteria (internal detail).
        for pick in json_data.get('picks', []):
            pick.pop('_show_ultra_public', None)
            pick.pop('ultra_criteria', None)

        # Upload to GCS (date-specific) with degradation backup (Session 378c)
        gcs_path = self.compare_and_upload(
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

    def _query_disabled_model_ids(self) -> set:
        """Return set of model_ids that are disabled/blocked in model_registry.

        Session 386: Defense-in-depth — prevents poisoned picks from entering
        signal_best_bets_picks even if the aggregator doesn't catch them.
        """
        try:
            query = f"""
            SELECT model_id
            FROM `{PROJECT_ID}.nba_predictions.model_registry`
            WHERE enabled = FALSE OR status = 'blocked'
            """
            rows = self.bq_client.query(query).result(timeout=15)
            return {row.model_id for row in rows}
        except Exception as e:
            logger.warning(f"Disabled model query failed (non-fatal): {e}")
            return set()

    def _write_to_bigquery(
        self,
        target_date: str,
        picks: List[Dict],
        filter_summary: Optional[Dict] = None,
    ) -> None:
        """Write signal best bets to BigQuery using batch load (not streaming).

        Session 412: True pick locking — only deletes rows for players being
        refreshed. Picks from prior runs that signal no longer produces are
        PRESERVED in the table for grading. This prevents the scenario where
        a valid pick (e.g., KAT UNDER 17.5) gets deleted by a re-export.

        Uses load_table_from_json with WRITE_APPEND to avoid 90-min streaming
        buffer that blocks DML operations (codebase best practice).
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks'

        # True pick locking (Session 412): Only delete rows for players we're
        # about to re-insert. Picks from prior runs that are no longer in the
        # signal output are PRESERVED — they stay in the table for grading.
        # This prevents the "KAT UNDER 17.5" scenario where a valid pick gets
        # deleted by a re-export with different algorithm settings.
        #
        # Session 371: Also preserves picks for started/finished games.
        new_player_lookups = list({p['player_lookup'] for p in picks})
        if not new_player_lookups:
            return

        delete_succeeded = False
        try:
            delete_query = f"""
            DELETE FROM `{table_ref}`
            WHERE game_date = @target_date
              AND player_lookup IN UNNEST(@player_lookups)
              AND game_id NOT IN (
                SELECT CONCAT(
                  REPLACE(CAST(game_date AS STRING), '-', ''), '_',
                  away_team_tricode, '_', home_team_tricode
                )
                FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
                WHERE game_date = @target_date
                  AND game_status >= 2
              )
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        'target_date', 'DATE', target_date
                    ),
                    bigquery.ArrayQueryParameter(
                        'player_lookups', 'STRING', new_player_lookups
                    ),
                ]
            )
            delete_job = self.bq_client.query(delete_query, job_config=job_config)
            delete_job.result(timeout=30)
            deleted = delete_job.num_dml_affected_rows or 0
            if deleted > 0:
                logger.info(
                    f"Deleted {deleted} rows for {len(new_player_lookups)} "
                    f"refreshed players on {target_date} from {table_ref}"
                )
            delete_succeeded = True
        except Exception as e:
            logger.error(
                f"Failed to delete existing rows for {target_date} — "
                f"aborting APPEND to prevent duplicate picks: {e}",
                exc_info=True,
            )

        if not delete_succeeded:
            logger.error(
                f"Skipping APPEND for {target_date}: DELETE did not complete successfully. "
                f"Re-run the export to retry."
            )
            return

        # Session 386/403: Disabled model filtering now happens in export() before
        # both BQ and GCS writes for consistency. Kept as comment for history.

        rows_to_insert = []
        for pick in picks:
            rows_to_insert.append({
                'player_lookup': pick['player_lookup'],
                'game_id': pick.get('game_id', ''),
                'game_date': target_date,
                'system_id': pick.get('system_id') or pick.get('source_model') or get_best_bets_model_id(),
                'player_name': pick.get('player', ''),
                'team_abbr': pick.get('team', ''),
                'opponent_team_abbr': pick.get('opponent', ''),
                'predicted_points': pick.get('prediction'),
                'line_value': pick.get('line'),
                'recommendation': pick.get('direction', ''),
                'edge': round(abs(float(pick.get('edge') or 0)), 1),
                'confidence_score': round(min(float(pick.get('confidence') or 0) / 100.0, 9.999), 3),
                'signal_tags': pick.get('signals', []),
                'signal_count': pick.get('signal_count', 0),
                'real_signal_count': pick.get('real_signal_count', 0),
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
                # Signal rescue (Session 398)
                'signal_rescued': pick.get('signal_rescued', False),
                'rescue_signal': pick.get('rescue_signal'),
                # Ultra Bets (Session 326, Session 452: derive from criteria)
                'ultra_tier': bool(pick.get('ultra_criteria')),
                'ultra_criteria': json.dumps(pick.get('ultra_criteria', []), default=str),
                # Session 414/422b: Additional pick context for analysis
                'under_signal_quality': pick.get('under_signal_quality'),
                'model_hr_weight': pick.get('model_hr_weight'),
                'trend_slope': pick.get('trend_slope'),
                'spread_magnitude': pick.get('spread_magnitude'),
                'player_tier': pick.get('player_tier'),
                'tier_edge_cap_delta': pick.get('tier_edge_cap_delta'),
                'capped_composite_score': pick.get('capped_composite_score'),
                'compression_ratio': pick.get('compression_ratio'),
                'compression_scaled_edge': pick.get('compression_scaled_edge'),
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

    def _query_existing_pick_lookups(self, target_date: str) -> set:
        """Return set of player_lookups already in signal_best_bets_picks for this date.

        Session 412: Used to detect truly new picks vs refreshes, and to
        log how many picks are being preserved by true pick locking.
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks'
        query = f"""
        SELECT DISTINCT player_lookup
        FROM `{table_ref}`
        WHERE game_date = @target_date
        """
        try:
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
                ]
            )
            rows = self.bq_client.query(query, job_config=job_config).result(timeout=15)
            return {row.player_lookup for row in rows}
        except Exception as e:
            logger.warning(f"Failed to query existing pick lookups (non-fatal): {e}")
            return set()

    def _write_filter_audit(
        self,
        target_date: str,
        json_data: Dict,
        filter_summary: Dict,
    ) -> None:
        """Session 391: Write filter summary to audit table for historical analysis.

        Enables queries like "show days where a single filter rejected > 50%"
        to catch configuration issues retroactively.
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.best_bets_filter_audit'
        total_candidates = filter_summary.get('total_candidates', 0)
        passed = filter_summary.get('passed_filters', 0)
        rejected = filter_summary.get('rejected', {})

        row = {
            'game_date': target_date,
            'total_candidates': total_candidates,
            'passed_filters': passed,
            'rejected_json': json.dumps(rejected, default=str),
            'algorithm_version': json_data.get('algorithm_version', ALGORITHM_VERSION),
            'computed_at': datetime.now(timezone.utc).isoformat(),
        }

        try:
            # MERGE to handle re-exports — only keep latest run per game_date
            merge_query = f"""
            MERGE `{table_ref}` T
            USING (SELECT @game_date AS game_date) S
            ON T.game_date = S.game_date
            WHEN MATCHED THEN UPDATE SET
                total_candidates = @total_candidates,
                passed_filters = @passed_filters,
                rejected_json = @rejected_json,
                algorithm_version = @algorithm_version,
                computed_at = @computed_at
            WHEN NOT MATCHED THEN INSERT
                (game_date, total_candidates, passed_filters, rejected_json, algorithm_version, computed_at)
            VALUES (@game_date, @total_candidates, @passed_filters, @rejected_json, @algorithm_version, @computed_at)
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('game_date', 'DATE', target_date),
                    bigquery.ScalarQueryParameter('total_candidates', 'INT64', total_candidates),
                    bigquery.ScalarQueryParameter('passed_filters', 'INT64', passed),
                    bigquery.ScalarQueryParameter('rejected_json', 'STRING', json.dumps(rejected, default=str)),
                    bigquery.ScalarQueryParameter('algorithm_version', 'STRING', json_data.get('algorithm_version', ALGORITHM_VERSION)),
                    bigquery.ScalarQueryParameter('computed_at', 'TIMESTAMP', datetime.now(timezone.utc).isoformat()),
                ]
            )
            self.bq_client.query(merge_query, job_config=job_config).result(timeout=30)
            logger.info(f"Filter audit written for {target_date}: {total_candidates} candidates, {passed} passed")
        except Exception as e:
            # Non-fatal — don't fail export if audit write fails
            logger.warning(f"Failed to write filter audit for {target_date}: {e}")

    def _write_filtered_picks(self, target_date: str, filtered_picks: list) -> None:
        """Session 393: Write filtered-out picks for counterfactual grading.

        Enables post-hoc validation: query actual_points after games complete
        to see if filtered picks would have won. Validates each filter's value.

        Uses DELETE + load_table_from_json(WRITE_TRUNCATE on partition) for
        atomicity. If DELETE fails the APPEND is aborted to prevent duplicates.
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.best_bets_filtered_picks'
        now = datetime.now(timezone.utc).isoformat()

        # Step 1: DELETE existing rows for this partition (re-export safe).
        # Gate the APPEND on DELETE success to prevent duplicates.
        delete_succeeded = False
        try:
            delete_query = f"DELETE FROM `{table_ref}` WHERE game_date = @game_date"
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('game_date', 'DATE', target_date),
                ]
            )
            self.bq_client.query(delete_query, job_config=job_config).result(timeout=30)
            delete_succeeded = True
        except Exception as e:
            logger.error(
                f"Failed to delete existing filtered picks for {target_date} — "
                f"aborting APPEND to prevent duplicate rows: {e}",
                exc_info=True,
            )

        if not delete_succeeded:
            logger.error(
                f"Skipping filtered picks APPEND for {target_date}: DELETE did not "
                f"complete successfully. Re-run the export to retry."
            )
            return

        # Step 2: Build rows and load atomically via load_table_from_json
        # (WRITE_TRUNCATE on the partition avoids streaming-buffer DML conflicts).
        rows = []
        for pick in filtered_picks:
            rows.append({
                'game_date': target_date,
                'player_lookup': pick.get('player_lookup', ''),
                'game_id': pick.get('game_id', ''),
                'system_id': pick.get('system_id', ''),
                'team_abbr': pick.get('team_abbr', ''),
                'opponent_team_abbr': pick.get('opponent_team_abbr', ''),
                'recommendation': pick.get('recommendation', ''),
                'predicted_points': pick.get('predicted_points'),
                'line_value': pick.get('line_value'),
                'edge': pick.get('edge'),
                'signal_count': pick.get('signal_count', 0),
                'signal_tags': pick.get('signal_tags', []),
                'filter_reason': pick.get('filter_reason', ''),
                'actual_points': None,  # Filled by grading
                'prediction_correct': None,  # Filled by grading
                'created_at': now,
            })

        if not rows:
            return

        try:
            load_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(
                rows,
                f'{table_ref}${target_date.replace("-", "")}',
                job_config=load_config,
            )
            load_job.result(timeout=60)
            logger.info(
                f"Filtered picks written for {target_date}: {len(rows)} picks "
                f"({len(set(p['filter_reason'] for p in filtered_picks))} distinct filters)"
            )
        except Exception as e:
            # Non-fatal — don't fail export if counterfactual write fails
            logger.warning(f"Failed to write filtered picks for {target_date}: {e}")

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

        Two-layer filter (Session 371):
          1. Time-based: game_date_est <= NOW() means tipoff has passed.
             Self-contained — no dependency on schedule scraper updating game_status.
          2. Status-based: game_status >= 2 as secondary catch.

        Also writes removed predictions to the late_picks_audit table for
        persistent tracking.

        Returns:
            Tuple of (filtered_predictions, set of started game_ids that were removed).
        """
        if not predictions:
            return predictions, set()

        query = f"""
        SELECT
          away_team_tricode,
          home_team_tricode,
          game_status,
          game_date_est
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
          AND (game_status >= 2
               OR game_date_est <= TIMESTAMP(DATETIME(CURRENT_TIMESTAMP(), 'America/New_York')))
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

    def _collect_all_model_candidates(
        self,
        pipeline_results: Dict,
        target_date: str,
    ) -> List[Dict]:
        """Collect all candidates from all model pipelines for BQ write.

        Session 443: Every candidate from every model pipeline is recorded
        with full provenance — whether it was selected by the merger or not.
        The merger has already tagged each candidate with was_selected,
        selection_reason, merge_rank, pipeline_agreement_count, etc.

        Returns:
            Flat list of candidate dicts ready for BQ batch write.
        """
        all_candidates = []
        for system_id, result in pipeline_results.items():
            for candidate in result.candidates:
                all_candidates.append({
                    'game_date': target_date,
                    'player_lookup': candidate.get('player_lookup', ''),
                    'game_id': candidate.get('game_id', ''),
                    'system_id': candidate.get('system_id', system_id),
                    'source_pipeline': candidate.get('source_pipeline', system_id),
                    'source_model_family': candidate.get('source_model_family', ''),
                    'player_name': candidate.get('player_name', ''),
                    'team_abbr': candidate.get('team_abbr', ''),
                    'opponent_team_abbr': candidate.get('opponent_team_abbr', ''),
                    'predicted_points': candidate.get('predicted_points'),
                    'line_value': candidate.get('line_value'),
                    'recommendation': candidate.get('recommendation', ''),
                    'edge': round(abs(float(candidate.get('edge') or 0)), 1),
                    'confidence_score': candidate.get('confidence_score'),
                    'composite_score': candidate.get('composite_score'),
                    'signal_count': candidate.get('signal_count', 0),
                    'real_signal_count': candidate.get('real_signal_count', 0),
                    'signal_tags': candidate.get('signal_tags', []),
                    'signal_rescued': candidate.get('signal_rescued', False),
                    'rescue_signal': candidate.get('rescue_signal'),
                    'model_hr_weight': candidate.get('model_hr_weight'),
                    # Merge metadata (set by pipeline_merger._tag_candidate)
                    'was_selected': candidate.get('was_selected', False),
                    'selection_reason': candidate.get('selection_reason', ''),
                    'merge_rank': candidate.get('merge_rank'),
                    'pipeline_agreement_count': candidate.get('pipeline_agreement_count', 0),
                    'pipeline_agreement_models': candidate.get('pipeline_agreement_models', []),
                    'direction_conflict_count': candidate.get('direction_conflict_count', 0),
                    'algorithm_version': candidate.get('algorithm_version', ALGORITHM_VERSION),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                })
        return all_candidates

    def _write_model_bb_candidates(
        self,
        target_date: str,
        candidates: List[Dict],
    ) -> None:
        """Write all model pipeline candidates to BQ for historical analysis.

        Session 443: Records EVERY candidate from EVERY model pipeline —
        whether selected or not. Enables post-hoc analysis of why picks were
        made, which models contributed, and merge decisions.

        Uses DELETE+APPEND pattern for re-export safety.
        """
        table_ref = f'{PROJECT_ID}.nba_predictions.model_bb_candidates'

        if not candidates:
            return

        try:
            # Delete existing rows for this game_date (re-export safe)
            delete_query = f"""
            DELETE FROM `{table_ref}`
            WHERE game_date = @target_date
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
                ]
            )
            self.bq_client.query(delete_query, job_config=job_config).result(timeout=30)
        except Exception as e:
            logger.warning(
                f"Failed to delete existing model_bb_candidates for {target_date} "
                f"(will append anyway): {e}"
            )

        try:
            # Convert pipeline_agreement_models list to JSON string for BQ
            rows_to_insert = []
            for c in candidates:
                row = dict(c)
                if isinstance(row.get('pipeline_agreement_models'), list):
                    row['pipeline_agreement_models'] = json.dumps(
                        row['pipeline_agreement_models']
                    )
                if isinstance(row.get('signal_tags'), list):
                    row['signal_tags'] = row['signal_tags']  # BQ REPEATED field
                rows_to_insert.append(row)

            load_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            )
            load_job = self.bq_client.load_table_from_json(
                rows_to_insert, table_ref, job_config=load_config
            )
            load_job.result(timeout=60)
            logger.info(
                f"Batch-loaded {len(rows_to_insert)} model_bb_candidates "
                f"for {target_date} into {table_ref}"
            )
        except Exception as e:
            # Non-fatal — don't fail export if candidates write fails
            logger.warning(
                f"Failed to write model_bb_candidates for {target_date}: {e}",
                exc_info=True,
            )

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
