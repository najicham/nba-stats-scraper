"""MLB Signal Best Bets Exporter — regressor-based pipeline.

Pipeline (v6 season-replay validated — Session 444):
  1. Load predictions for game_date
  1b. Overconfidence cap: edge > MAX_EDGE (2.0) blocked
  1c. Probability cap: p_over > MAX_PROB_OVER (0.85) blocked (relaxed for regressor)
  2. Apply direction filter (OVER + optional UNDER via env var)
  3. Apply negative filters (bullpen, il_return, pitch_count, insufficient_data,
     pitcher_blacklist, whole_line_over)
  4. Apply edge floor (DEFAULT_EDGE_FLOOR = 0.75 K) — with signal rescue
  5. Evaluate all active + shadow signals
  6. Gate: signal_count >= 2 (OVER) or >= 3 (UNDER, higher bar)
  7. Rank: OVER by pure edge (composite scoring fails cross-season validation)
  8. Ultra tier: tag picks meeting all 5 criteria (home + proj + half-line + edge 1.1+ + not-blacklisted)
  9. Ultra overlay: ultra picks outside top-3 still published at 2u
 10. Build pick angles (human-readable reasoning)
 11. Write to mlb_predictions.signal_best_bets_picks
 12. Write filter audit to mlb_predictions.best_bets_filter_audit

Session 443 changes (11-agent cross-season validation):
  - Pitcher blacklist expanded 10 → 18 (validated bad pitchers)
  - Whole-number line filter added (49% HR vs 58.6% half-lines, p<0.001)
  - bad_opponent/bad_venue demoted to observation (cross-season r=-0.29)
  - DOW filter removed (confirmed noise)
  - Pure edge ranking confirmed optimal (composite scoring fails cross-season)

Session 444 changes (full-season replay Apr-Sep 2025):
  - Pitcher blacklist expanded 18 → 23 (5 new 0% or <40% HR pitchers)
  - swstr_surge removed from rescue signals (54.9% HR, drags all combos to 51-55%)
  - 5 dead features removed from training (36 features, was 40)
  - Ultra tier: edge >= 1.1 + home + projection agrees + half-line (81.4% HR, N=70)
  - Replay validated: 63.4% BB HR, +170u, 13 retrains, zero losing months
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from ml.signals.mlb.registry import build_mlb_registry, MLBSignalRegistry
from ml.signals.mlb.base_signal import MLBSignalResult

logger = logging.getLogger(__name__)

# =============================================================================
# REGRESSOR CONFIGURATION (unified — no season phases)
# =============================================================================

# Default edge floor (env var override: MLB_EDGE_FLOOR)
# Regressor sweet spot at 0.75 K — walk-forward validated
DEFAULT_EDGE_FLOOR = float(os.environ.get('MLB_EDGE_FLOOR', '0.75'))

# UNDER direction control (env var override: MLB_UNDER_ENABLED)
# UNDER is unprofitable without signal filtering (47-49% HR walk-forward)
# Only surface UNDER with strong signal backing
UNDER_ENABLED = os.environ.get('MLB_UNDER_ENABLED', 'false').lower() == 'true'
UNDER_MIN_SIGNALS = 3  # Higher bar than OVER (which uses 2)

# Overconfidence cap — OVER picks with edge > MAX_EDGE are blocked
# Walk-forward (Session 438b): edge 2.0-2.5 = 58.7%, edge 3.0+ = 48.2% (losing)
MAX_EDGE = float(os.environ.get('MLB_MAX_EDGE', '2.0'))

# Probability cap — OVER picks with p_over > MAX_PROB are blocked
# Relaxed for regressor: p_over is derived (not native classifier output)
# Regressor p_over has different calibration — 0.85 keeps outliers only
MAX_PROB_OVER = float(os.environ.get('MLB_MAX_PROB_OVER', '0.85'))

# Daily pick limit — truncate ranked picks to this count
# Walk-forward (Session 438b): Top-3 at prob 0.60-0.70 = 63.1% HR, +20.4% ROI, zero losing months
MAX_PICKS_PER_DAY = int(os.environ.get('MLB_MAX_PICKS_PER_DAY', '3'))

# Minimum real signal count for best bets (OVER)
MIN_SIGNAL_COUNT = 2

# Base signals that inflate signal count with zero value
BASE_SIGNAL_TAGS = frozenset(['high_edge'])

# Signal rescue tags — picks can bypass edge floor if they have these signals
# Session 444: swstr_surge REMOVED (54.9% HR, drags all signal combos to 51-55%)
RESCUE_SIGNAL_TAGS = frozenset([
    'opponent_k_prone',
    'ballpark_k_boost',
])

# UNDER signal weights for quality-based ranking
UNDER_SIGNAL_WEIGHTS = {
    'velocity_drop_under': 2.0,
    'short_rest_under': 1.5,
    'high_variance_under': 1.5,
    'weather_cold_under': 1.0,
    'pitch_count_limit_under': 2.0,
}

# =============================================================================
# ULTRA TIER CONFIGURATION (Session 444 — season replay validated)
# Edge 1.0-1.1 was 63% HR (noise), edge 1.1+ = 81.4% HR (N=70)
# =============================================================================
ULTRA_MIN_EDGE = float(os.environ.get('MLB_ULTRA_MIN_EDGE', '1.1'))
ULTRA_REQUIRES_HOME = True
ULTRA_REQUIRES_PROJECTION_AGREES = True
ULTRA_REQUIRES_HALF_LINE = True


class MLBBestBetsExporter:
    """Generate MLB best bets from predictions + signals."""

    def __init__(self, bq_client=None, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.bq_client = bq_client
        self.registry = build_mlb_registry()
        self.filter_audit: List[Dict] = []

    def _get_bq_client(self):
        if self.bq_client is None:
            from shared.clients.bigquery_pool import get_bigquery_client
            self.bq_client = get_bigquery_client(project_id=self.project_id)
        return self.bq_client

    def export(
        self,
        predictions: List[Dict],
        game_date: str,
        features_by_pitcher: Optional[Dict[str, Dict]] = None,
        supplemental_by_pitcher: Optional[Dict[str, Dict]] = None,
        edge_floor: Optional[float] = None,
        min_signals: int = MIN_SIGNAL_COUNT,
        dry_run: bool = False,
    ) -> List[Dict]:
        """Run the full best bets pipeline.

        Args:
            predictions: List of prediction dicts from prediction systems
            game_date: Target game date (YYYY-MM-DD)
            features_by_pitcher: {pitcher_lookup: {feature_dict}}
            supplemental_by_pitcher: {pitcher_lookup: {supplemental_dict}}
            edge_floor: Override edge floor (None = use DEFAULT_EDGE_FLOOR)
            min_signals: Minimum real signal count for OVER (default 2)
            dry_run: If True, don't write to BQ

        Returns:
            List of best bet picks
        """
        features_by_pitcher = features_by_pitcher or {}
        supplemental_by_pitcher = supplemental_by_pitcher or {}
        self.filter_audit = []

        # Unified edge floor (no phase logic — regressor sweet spot)
        effective_edge_floor = edge_floor if edge_floor is not None else DEFAULT_EDGE_FLOOR
        under_enabled = UNDER_ENABLED

        logger.info(f"[MLB BB] Processing {len(predictions)} predictions for {game_date}")
        logger.info(f"[MLB BB] Edge floor: {effective_edge_floor}, UNDER enabled: {under_enabled}")

        # 1. Filter to actionable predictions (OVER/UNDER with line)
        allowed_directions = ['OVER']
        if under_enabled:
            allowed_directions.append('UNDER')

        actionable = []
        for p in predictions:
            rec = p.get('recommendation')
            if (rec in allowed_directions
                    and p.get('strikeouts_line') is not None
                    and p.get('predicted_strikeouts') is not None):
                actionable.append(p)
            elif rec == 'UNDER' and not under_enabled:
                # Record UNDER blocks in audit for tracking
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': p.get('pitcher_lookup', ''),
                    'system_id': p.get('system_id', 'unknown'),
                    'filter_name': 'direction_filter',
                    'filter_result': 'BLOCKED',
                    'filter_reason': 'UNDER disabled (walk-forward: 47-49% HR without signals)',
                    'recommendation': rec,
                    'edge': p.get('edge'),
                    'line_value': p.get('strikeouts_line'),
                })

        logger.info(f"[MLB BB] {len(actionable)} actionable predictions "
                    f"(directions: {allowed_directions})")

        # 1b. Overconfidence cap — block OVER picks with edge > MAX_EDGE
        capped = []
        for p in actionable:
            edge = abs(p.get('edge', 0))
            if p.get('recommendation') == 'OVER' and edge > MAX_EDGE:
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': p.get('pitcher_lookup', ''),
                    'system_id': p.get('system_id', 'unknown'),
                    'filter_name': 'overconfidence_cap',
                    'filter_result': 'BLOCKED',
                    'filter_reason': f'OVER edge {edge:.1f} > {MAX_EDGE} cap (overconfident)',
                    'recommendation': p.get('recommendation'),
                    'edge': p.get('edge'),
                    'line_value': p.get('strikeouts_line'),
                })
                logger.debug(f"[MLB BB] {p.get('pitcher_lookup', '')} BLOCKED by overconfidence_cap "
                             f"(edge={edge:.1f} > {MAX_EDGE})")
            else:
                capped.append(p)

        if len(actionable) - len(capped) > 0:
            logger.info(f"[MLB BB] {len(actionable) - len(capped)} blocked by overconfidence cap "
                        f"(edge > {MAX_EDGE})")
        actionable = capped

        # 1c. Probability cap — block OVER picks with p_over > MAX_PROB_OVER
        # Walk-forward: prob 0.60-0.70 = 64.4% HR, prob 0.70+ drops to 58.7%, 0.80+ = 48.2%
        prob_capped = []
        for p in actionable:
            p_over = p.get('p_over')
            if (p.get('recommendation') == 'OVER'
                    and p_over is not None
                    and p_over > MAX_PROB_OVER):
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': p.get('pitcher_lookup', ''),
                    'system_id': p.get('system_id', 'unknown'),
                    'filter_name': 'probability_cap',
                    'filter_result': 'BLOCKED',
                    'filter_reason': f'OVER p_over {p_over:.3f} > {MAX_PROB_OVER} cap '
                                     f'(walk-forward: prob>{MAX_PROB_OVER} = 56-48% HR)',
                    'recommendation': p.get('recommendation'),
                    'edge': p.get('edge'),
                    'line_value': p.get('strikeouts_line'),
                })
                logger.debug(f"[MLB BB] {p.get('pitcher_lookup', '')} BLOCKED by probability_cap "
                             f"(p_over={p_over:.3f} > {MAX_PROB_OVER})")
            else:
                prob_capped.append(p)

        if len(actionable) - len(prob_capped) > 0:
            logger.info(f"[MLB BB] {len(actionable) - len(prob_capped)} blocked by probability cap "
                        f"(p_over > {MAX_PROB_OVER})")
        actionable = prob_capped

        # 2. Apply negative filters
        passed_filters = []
        for pred in actionable:
            pitcher = pred.get('pitcher_lookup', '')
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})

            blocked = False
            for filt in self.registry.negative_filters():
                result = filt.evaluate(pred, features, supplemental)
                audit_entry = {
                    'game_date': game_date,
                    'pitcher_lookup': pitcher,
                    'system_id': pred.get('system_id', 'unknown'),
                    'filter_name': filt.tag,
                    'filter_result': 'BLOCKED' if result.qualifies else 'PASSED',
                    'filter_reason': result.metadata.get('reason') if result.qualifies else None,
                    'recommendation': pred.get('recommendation'),
                    'edge': pred.get('edge'),
                    'line_value': pred.get('strikeouts_line'),
                }
                self.filter_audit.append(audit_entry)

                if result.qualifies:
                    blocked = True
                    logger.debug(f"[MLB BB] {pitcher} BLOCKED by {filt.tag}: {result.metadata}")
                    break

            if not blocked:
                passed_filters.append(pred)

        logger.info(f"[MLB BB] {len(passed_filters)} passed negative filters "
                    f"({len(actionable) - len(passed_filters)} blocked)")

        # 3. Edge floor + signal rescue
        edge_eligible = []
        for pred in passed_filters:
            edge = abs(pred.get('edge', 0))
            pitcher = pred.get('pitcher_lookup', '')

            if edge >= effective_edge_floor:
                edge_eligible.append((pred, False))  # (pred, rescued)
                continue

            # Signal rescue: check if any rescue signals fire
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})
            rescued = False
            rescue_signal = None
            for tag in RESCUE_SIGNAL_TAGS:
                signal = self.registry.get(tag)
                result = signal.evaluate(pred, features, supplemental)
                if result.qualifies:
                    rescued = True
                    rescue_signal = tag
                    break

            if rescued:
                edge_eligible.append((pred, True))
                logger.debug(f"[MLB BB] {pitcher} RESCUED by {rescue_signal} (edge={edge:.1f})")
            else:
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': pitcher,
                    'system_id': pred.get('system_id', 'unknown'),
                    'filter_name': 'edge_floor',
                    'filter_result': 'BLOCKED',
                    'filter_reason': f'Edge {edge:.1f} < {effective_edge_floor}',
                    'recommendation': pred.get('recommendation'),
                    'edge': pred.get('edge'),
                    'line_value': pred.get('strikeouts_line'),
                })

        logger.info(f"[MLB BB] {len(edge_eligible)} passed edge floor")

        # 4. Evaluate all signals for eligible picks
        annotated_picks = []
        for pred, was_rescued in edge_eligible:
            pitcher = pred.get('pitcher_lookup', '')
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})

            signal_tags = []
            signal_count = 0
            real_signal_count = 0
            signal_results = {}

            for signal in self.registry.all():
                if signal.is_negative_filter:
                    continue
                result = signal.evaluate(pred, features, supplemental)
                if result.qualifies:
                    signal_tags.append(signal.tag)
                    signal_count += 1
                    signal_results[signal.tag] = result
                    if signal.tag not in BASE_SIGNAL_TAGS:
                        real_signal_count += 1

            annotated_picks.append({
                **pred,
                'signal_tags': signal_tags,
                'signal_count': signal_count,
                'real_signal_count': real_signal_count,
                'signal_results': signal_results,
                'signal_rescued': was_rescued,
                'rescue_signal': None,  # TODO: track which signal
            })

        # 5. Signal count gate (UNDER has higher bar)
        gated_picks = []
        for p in annotated_picks:
            if p['recommendation'] == 'UNDER':
                required = UNDER_MIN_SIGNALS
            else:
                required = min_signals
            if p['real_signal_count'] >= required:
                gated_picks.append(p)

        over_gated = sum(1 for p in gated_picks if p['recommendation'] == 'OVER')
        under_gated = sum(1 for p in gated_picks if p['recommendation'] == 'UNDER')
        logger.info(f"[MLB BB] {len(gated_picks)} passed signal count gate "
                    f"(OVER: {over_gated} >= {min_signals} signals, "
                    f"UNDER: {under_gated} >= {UNDER_MIN_SIGNALS} signals)")

        # 6. Rank picks
        over_picks = [p for p in gated_picks if p['recommendation'] == 'OVER']
        under_picks = [p for p in gated_picks if p['recommendation'] == 'UNDER']

        # OVER: rank by edge (higher = better)
        over_picks.sort(key=lambda p: abs(p.get('edge', 0)), reverse=True)

        # UNDER: rank by weighted signal quality (same lesson as NBA)
        for pick in under_picks:
            quality = 0.0
            for tag, result in pick.get('signal_results', {}).items():
                weight = UNDER_SIGNAL_WEIGHTS.get(tag, 1.0)
                quality += result.confidence * weight
            pick['under_signal_quality'] = round(quality, 4)
        under_picks.sort(key=lambda p: p.get('under_signal_quality', 0), reverse=True)

        # Combine and assign ranks
        ranked_picks = over_picks + under_picks

        # 6b. Daily pick limit — truncate to MAX_PICKS_PER_DAY
        top_picks = ranked_picks[:MAX_PICKS_PER_DAY]
        remaining_picks = ranked_picks[MAX_PICKS_PER_DAY:]

        if remaining_picks:
            logger.info(f"[MLB BB] Trimming {len(remaining_picks)} picks to daily limit "
                        f"of {MAX_PICKS_PER_DAY}")

        # 7. Ultra tier tagging (Session 444 — 81.4% HR, N=70)
        # Ultra picks in top-N get 2u stake. Ultra picks NOT in top-N still get published.
        ultra_overlay = []
        for pick in top_picks:
            is_ultra, criteria = self._check_ultra(pick, features_by_pitcher)
            pick['ultra_tier'] = is_ultra
            pick['ultra_criteria'] = criteria
            pick['staking_multiplier'] = 2 if is_ultra else 1

        # Check remaining picks for ultra overlay
        for pick in remaining_picks:
            is_ultra, criteria = self._check_ultra(pick, features_by_pitcher)
            if is_ultra:
                pick['ultra_tier'] = True
                pick['ultra_criteria'] = criteria
                pick['staking_multiplier'] = 2
                ultra_overlay.append(pick)

        # Final picks = top-N + ultra overlay
        ranked_picks = top_picks + ultra_overlay

        for i, pick in enumerate(ranked_picks, 1):
            pick['rank'] = i

        n_ultra = sum(1 for p in ranked_picks if p.get('ultra_tier'))
        n_overlay = len(ultra_overlay)
        if n_ultra > 0:
            logger.info(f"[MLB BB] Ultra tier: {n_ultra} picks ({n_overlay} via overlay)")

        # 8. Build pick angles + stamp algorithm version
        algo_version = 'mlb_v6_season_replay_validated'
        for pick in ranked_picks:
            pick['pick_angles'] = self._build_pick_angles(pick)
            pick['algorithm_version'] = algo_version

        # 9. Write to BigQuery
        if not dry_run and ranked_picks:
            self._write_best_bets(ranked_picks, game_date)
            self._write_filter_audit(game_date)

        logger.info(f"[MLB BB] Final best bets: {len(ranked_picks)} "
                    f"(OVER: {len(over_picks)}, UNDER: {len(under_picks)}, "
                    f"ultra: {n_ultra})")

        return ranked_picks

    def _check_ultra(self, pick: Dict, features_by_pitcher: Dict) -> Tuple[bool, List[str]]:
        """Check if a pick qualifies for Ultra tier.

        Ultra = OVER + half-line + not-blacklisted + edge >= 1.1 + home + projection agrees.
        Season replay: 81.4% HR (N=70), +88u at 2u staking.

        Returns:
            (is_ultra, criteria_list)
        """
        if pick.get('recommendation') != 'OVER':
            return False, []

        criteria = []

        # Must be half-line
        line = pick.get('strikeouts_line')
        if line is not None and line != int(line):
            criteria.append('half_line')
        elif ULTRA_REQUIRES_HALF_LINE:
            return False, []

        # Edge >= ULTRA_MIN_EDGE
        edge = abs(pick.get('edge', 0))
        if edge >= ULTRA_MIN_EDGE:
            criteria.append(f'edge_{edge:.1f}')
        else:
            return False, []

        # Home pitcher
        pitcher = pick.get('pitcher_lookup', '')
        features = features_by_pitcher.get(pitcher, {})
        is_home = (pick.get('is_home')
                   or features.get('is_home')
                   or 'home_pitcher_over' in pick.get('signal_tags', []))
        if is_home:
            criteria.append('is_home')
        elif ULTRA_REQUIRES_HOME:
            return False, []

        # Projection agrees
        signal_tags = pick.get('signal_tags', [])
        proj_agrees = ('projection_agrees_over' in signal_tags
                       or 'regressor_projection_agrees_over' in signal_tags)
        if proj_agrees:
            criteria.append('projection_agrees')
        elif ULTRA_REQUIRES_PROJECTION_AGREES:
            return False, []

        # Not blacklisted (already filtered by pipeline, but safety check)
        from ml.signals.mlb.signals import PitcherBlacklistFilter
        if pitcher in PitcherBlacklistFilter.BLACKLIST:
            return False, []

        return True, criteria

    def _build_pick_angles(self, pick: Dict) -> List[str]:
        """Build human-readable pick angles from signal results."""
        angles = []
        rec = pick.get('recommendation', '')
        pitcher = pick.get('pitcher_lookup', '').replace('_', ' ').title()
        edge = pick.get('edge', 0)
        line = pick.get('strikeouts_line')

        if rec == 'OVER':
            angles.append(f"Model projects {pick.get('predicted_strikeouts', '?')} K "
                         f"vs line {line} ({edge:+.1f} edge)")
        else:
            angles.append(f"Model projects {pick.get('predicted_strikeouts', '?')} K "
                         f"vs line {line} ({edge:+.1f} edge)")

        signal_results = pick.get('signal_results', {})

        if 'swstr_surge' in signal_results:
            meta = signal_results['swstr_surge'].metadata
            angles.append(f"SwStr% surge: +{meta.get('surge_pct', 0):.1%} above season avg")

        if 'velocity_drop_under' in signal_results:
            meta = signal_results['velocity_drop_under'].metadata
            angles.append(f"Velocity down {meta.get('velocity_drop_mph', 0):.1f} mph from season avg")

        if 'opponent_k_prone' in signal_results:
            meta = signal_results['opponent_k_prone'].metadata
            angles.append(f"Opponent K-rate {meta.get('opponent_k_rate', 0):.1%} (top 25%)")

        if 'short_rest_under' in signal_results:
            meta = signal_results['short_rest_under'].metadata
            angles.append(f"Short rest: {meta.get('days_rest', '?')} days")

        if 'high_variance_under' in signal_results:
            meta = signal_results['high_variance_under'].metadata
            angles.append(f"High K variance: {meta.get('k_std', 0):.1f} std dev last 10")

        if 'ballpark_k_boost' in signal_results:
            meta = signal_results['ballpark_k_boost'].metadata
            angles.append(f"K-friendly ballpark: {meta.get('ballpark_k_factor', 0):.3f} factor")

        if 'umpire_k_friendly' in signal_results:
            meta = signal_results['umpire_k_friendly'].metadata
            angles.append(f"K-friendly umpire: {meta.get('umpire_k_rate', 0):.1%} K rate")

        if 'ace_pitcher_over' in signal_results:
            meta = signal_results['ace_pitcher_over'].metadata
            angles.append(f"Elite K rate: {meta.get('k_per_9', 0):.1f} K/9")

        if 'projection_agrees_over' in signal_results:
            meta = signal_results['projection_agrees_over'].metadata
            angles.append(f"Projection confirms: +{meta.get('projection_diff', 0):.1f} K above line")

        if 'regressor_projection_agrees_over' in signal_results:
            meta = signal_results['regressor_projection_agrees_over'].metadata
            angles.append(f"Projection agrees: +{meta.get('projection_diff', 0):.1f} K above line")

        if 'k_trending_over' in signal_results:
            meta = signal_results['k_trending_over'].metadata
            angles.append(f"K trending up: {meta.get('k_last_3', 0):.1f} avg last 3 "
                         f"vs {meta.get('k_last_10', 0):.1f} last 10 (+{meta.get('trend', 0):.1f})")

        if 'recent_k_above_line' in signal_results:
            meta = signal_results['recent_k_above_line'].metadata
            angles.append(f"Recent K avg exceeds line by {meta.get('k_avg_vs_line', 0):.1f} K")

        if 'home_pitcher_over' in signal_results:
            angles.append("Home pitcher K advantage")

        if 'long_rest_over' in signal_results:
            meta = signal_results['long_rest_over'].metadata
            angles.append(f"Extended rest: {meta.get('days_rest', '?')} days (fresh arm)")

        if pick.get('ultra_tier'):
            criteria = pick.get('ultra_criteria', [])
            angles.append(f"ULTRA: {', '.join(criteria)} — 2u stake")

        return angles

    def _write_best_bets(self, picks: List[Dict], game_date: str):
        """Write best bets to signal_best_bets_picks table."""
        client = self._get_bq_client()
        table_id = f"{self.project_id}.mlb_predictions.signal_best_bets_picks"

        # Scoped delete: only delete for pitchers we're refreshing
        pitcher_lookups = [p['pitcher_lookup'] for p in picks]
        if pitcher_lookups:
            placeholders = ", ".join(f"'{pl}'" for pl in pitcher_lookups)
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date = '{game_date}'
              AND pitcher_lookup IN ({placeholders})
            """
            try:
                client.query(delete_query).result()
            except Exception as e:
                logger.warning(f"Delete before insert failed: {e}")

        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for pick in picks:
            rows.append({
                'pitcher_lookup': pick['pitcher_lookup'],
                'game_pk': pick.get('game_pk'),
                'game_date': game_date,
                'system_id': pick.get('system_id', 'unknown'),
                'pitcher_name': pick.get('pitcher_name'),
                'team_abbr': pick.get('team_abbr'),
                'opponent_team_abbr': pick.get('opponent_team_abbr'),
                'predicted_strikeouts': pick.get('predicted_strikeouts'),
                'line_value': pick.get('strikeouts_line'),
                'recommendation': pick.get('recommendation'),
                'edge': pick.get('edge'),
                'confidence_score': pick.get('confidence'),
                'signal_tags': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'real_signal_count': pick.get('real_signal_count', 0),
                'rank': pick.get('rank'),
                'pick_angles': pick.get('pick_angles', []),
                'algorithm_version': pick.get('algorithm_version', 'mlb_v2'),
                'signal_rescued': pick.get('signal_rescued', False),
                'rescue_signal': pick.get('rescue_signal'),
                'under_signal_quality': pick.get('under_signal_quality'),
                'ultra_tier': pick.get('ultra_tier', False),
                'ultra_criteria': pick.get('ultra_criteria', []),
                'staking_multiplier': pick.get('staking_multiplier', 1),
                'created_at': now,
            })

        if rows:
            try:
                errors = client.insert_rows_json(table_id, rows)
                if errors:
                    logger.error(f"Insert errors: {errors[:3]}")
                else:
                    logger.info(f"Wrote {len(rows)} best bets to {table_id}")
            except Exception as e:
                logger.error(f"Failed to write best bets: {e}")

    def _write_filter_audit(self, game_date: str):
        """Write filter audit records to best_bets_filter_audit table."""
        if not self.filter_audit:
            return

        client = self._get_bq_client()
        table_id = f"{self.project_id}.mlb_predictions.best_bets_filter_audit"

        now = datetime.now(timezone.utc).isoformat()
        rows = [{**entry, 'created_at': now} for entry in self.filter_audit]

        try:
            errors = client.insert_rows_json(table_id, rows)
            if errors:
                logger.error(f"Filter audit insert errors: {errors[:3]}")
            else:
                logger.info(f"Wrote {len(rows)} filter audit records")
        except Exception as e:
            logger.error(f"Failed to write filter audit: {e}")
