"""MLB Signal Best Bets Exporter — regressor-based pipeline.

Pipeline (V3 FINAL — Session 456, vig-adjusted cross-season validated):
  1. Load predictions for game_date
  1b. Overconfidence cap: edge > MAX_EDGE (2.0) blocked
  1c. Probability cap: p_over > MAX_PROB_OVER (0.85) blocked (relaxed for regressor)
  2. Apply direction filter (OVER + optional UNDER via env var)
  3. Apply negative filters (bullpen, il_return, pitch_count, insufficient_data,
     pitcher_blacklist, whole_line_over)
  4. Apply edge floor:
     - Home OVER: 0.75 K (with signal rescue)
     - Away OVER: 1.25 K (no rescue — 51% HR cross-season)
  5. Evaluate all active + shadow signals
     - long_rest_over, k_trending_over → tracking-only (excluded from real_signal_count)
  6. Gate: signal_count >= 2 (OVER) or >= 3 (UNDER, higher bar)
  7. Rank: OVER by pure edge (composite scoring fails cross-season validation)
  8. Ultra tier: home + proj agrees + edge >= 0.5 + not rescued
  9. Ultra overlay: ultra picks outside top-5 still published at 2u
 10. Build pick angles (human-readable reasoning)
 11. Write to mlb_predictions.signal_best_bets_picks
 12. Write filter audit to mlb_predictions.best_bets_filter_audit

V3 FINAL config (120d/14d retrain, 4-season cross-validation):
  61.5% HR, +377u, 10.2% ROI across 2022-2025 (vig-adjusted).

Session 455 changes (vig-adjusted P&L, away filters):
  - Away edge floor 1.25 K (home remains 0.75 K)
  - Away rescued picks blocked (51% HR cross-season)
  - MAX_PICKS_PER_DAY raised 3 → 5 (rank 5 still profitable: 58.4%/+32u)
  - long_rest_over → tracking-only (55.4% HR, -36u cross-season)
  - k_trending_over → tracking-only (55.6% HR, -18u cross-season)
  - Ultra redesigned: edge 0.5+ (was 1.1), no half-line req, rescued excluded
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

# Away pitcher edge floor — higher bar for away OVER pitchers
# Cross-season: away 54.1% HR vs home 64.2%. Edge 1.25+ needed for profitability.
AWAY_EDGE_FLOOR = float(os.environ.get('MLB_AWAY_EDGE_FLOOR', '1.25'))

# Block rescued picks for away pitchers (51% HR cross-season — coin flip)
BLOCK_AWAY_RESCUE = os.environ.get('MLB_BLOCK_AWAY_RESCUE', 'true').lower() == 'true'

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
# V3 FINAL: Rank 5 still profitable (58.4%/+32u cross-season)
MAX_PICKS_PER_DAY = int(os.environ.get('MLB_MAX_PICKS_PER_DAY', '5'))

# Minimum real signal count for best bets (OVER)
MIN_SIGNAL_COUNT = 2

# Base signals that inflate signal count with zero value
# Session 483: home_pitcher_over added — fires for every home OVER pick (~50% of candidates),
# providing zero discriminatory power while pushing picks past the MIN_SIGNAL_COUNT=2 gate.
# Walk-forward stat (64.9% home vs 59.7% away) measures general home advantage, not signal value.
# Still available for Ultra tier evaluation (line 573) and pick angle generation.
BASE_SIGNAL_TAGS = frozenset(['high_edge', 'home_pitcher_over'])

# Tracking-only signals — evaluated and tagged but excluded from real_signal_count
# long_rest_over: 55.4% HR, -36u P&L across 4 seasons — actively losing money
# k_trending_over: 55.6% HR, -18u P&L across 4 seasons — coin flip
TRACKING_ONLY_SIGNALS = frozenset([
    'long_rest_over', 'k_trending_over',
    # Session 464 shadow signals — evaluate but don't count
    'k_rate_reversion_under', 'k_rate_bounce_over', 'umpire_csw_combo_over',
    'rest_workload_stress_under', 'low_era_high_k_combo_over',
    # Session 464 round 2 shadow signals
    'chase_rate_over', 'contact_specialist_under', 'humidity_over',
    'fresh_opponent_over',
    # Session 465 combo shadow signals (2 remaining shadow)
    'day_game_elite_peripherals_combo_over',
    'high_csw_low_era_high_k_combo_over',
    # PROMOTED: xfip_elite_over, day_game_high_csw_combo_over (S465)
    # PROMOTED: pitcher_on_roll_over, day_game_shadow_over (S464)
])

# Signal rescue tags — picks can bypass edge floor if they have these signals
# Session 444: swstr_surge REMOVED (54.9% HR, drags all signal combos to 51-55%)
# Session 447: ballpark_k_boost REMOVED (41.2% solo rescue HR on 17 picks — net negative)
# V3 FINAL: Away pitchers blocked from rescue (BLOCK_AWAY_RESCUE)
RESCUE_SIGNAL_TAGS = frozenset([
    'opponent_k_prone',
])

# UNDER signal weights for quality-based ranking
UNDER_SIGNAL_WEIGHTS = {
    'velocity_drop_under': 2.0,
    'short_rest_under': 1.5,
    'high_variance_under': 1.5,
    'weather_cold_under': 1.0,
    'pitch_count_limit_under': 2.0,
}

# Tiebreaker signals — don't count toward RSC, but break ties in ranking
# Umpire signal: 64.2% HR but inflates RSC when active (Session 465: -1.7pp, -33u)
# Used as tiebreaker only: when two picks have similar edge (within 0.25 K),
# prefer the one with a favorable umpire assignment.
TIEBREAKER_SIGNALS = frozenset(['umpire_k_friendly'])

# =============================================================================
# ULTRA TIER CONFIGURATION (V3 FINAL — Session 455 cross-season redesign)
# Removed: half_line (vacuous — all K lines are x.5), edge 1.1 (hurt 2022-2023)
# Added: rescued picks excluded (lowest confidence shouldn't get 2u)
# =============================================================================
ULTRA_MIN_EDGE = float(os.environ.get('MLB_ULTRA_MIN_EDGE', '0.5'))
ULTRA_REQUIRES_HOME = True
ULTRA_REQUIRES_PROJECTION_AGREES = True
ULTRA_REQUIRES_HALF_LINE = False


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

    def _get_regime_context(self, game_date: str) -> dict:
        """Query yesterday's MLB macro data for market regime awareness.

        Session 483: Ports the NBA regime_context pattern to MLB.
        The mlb_predictions.league_macro_daily table exists (mlb_league_macro.py
        populates it) but was never read by the pipeline — same gap as NBA pre-Session 483.

        Returns dict with:
            vegas_mae_7d: float or None — book accuracy on K lines (7d rolling)
            mae_gap_7d: float or None — model_mae - vegas_mae (positive = model worse)
            market_regime: str or None — TIGHT/NORMAL/LOOSE
            over_edge_floor_delta: float — additional edge to add when TIGHT
            disable_rescue: bool — True when TIGHT (rescue is noise in efficient market)
            block_all_over: bool — True when mae_gap too large (model not competitive)

        Thresholds (K-specific, narrower than NBA points):
            TIGHT:        vegas_mae_7d < 1.7 K  → raise floor +0.5 K, disable rescue
            MAE gap:      mae_gap_7d > 0.3 K    → block all OVER (model losing to Vegas)
        """
        from datetime import date, timedelta
        result = {
            'vegas_mae_7d': None,
            'mae_gap_7d': None,
            'market_regime': None,
            'over_edge_floor_delta': 0.0,
            'disable_rescue': False,
            'block_all_over': False,
        }
        try:
            yesterday = (date.fromisoformat(game_date) - timedelta(days=1)).isoformat()
            bq = self._get_bq_client()
            query = f"""
                SELECT vegas_mae_7d, mae_gap_7d, market_regime
                FROM `{self.project_id}.mlb_predictions.league_macro_daily`
                WHERE game_date = '{yesterday}'
                LIMIT 1
            """
            rows = list(bq.query(query).result())
            if rows:
                row = rows[0]
                if row.vegas_mae_7d is not None:
                    result['vegas_mae_7d'] = float(row.vegas_mae_7d)
                if row.mae_gap_7d is not None:
                    result['mae_gap_7d'] = float(row.mae_gap_7d)
                result['market_regime'] = getattr(row, 'market_regime', None)

                vegas_mae = result['vegas_mae_7d']
                mae_gap = result['mae_gap_7d']

                if vegas_mae is not None and vegas_mae < 1.7:
                    result['over_edge_floor_delta'] = 0.5
                    result['disable_rescue'] = True
                    logger.warning(
                        f"[MLB BB] TIGHT market: vegas_mae={vegas_mae:.2f} < 1.7 K. "
                        f"Raising OVER floor +0.5 K and disabling rescue."
                    )
                if mae_gap is not None and mae_gap > 0.3:
                    result['block_all_over'] = True
                    logger.warning(
                        f"[MLB BB] MAE gap={mae_gap:.2f} > 0.3 K: model worse than Vegas. "
                        f"Blocking all OVER picks for today."
                    )
        except Exception as e:
            logger.warning(f"[MLB BB] Regime context query failed (non-fatal): {e}")
        return result

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
        self._blacklist_blocked = []  # Shadow tracking for blacklisted pitchers

        # Session 483: Query market regime before pipeline starts.
        # Same pattern as NBA regime_context.py — reads mlb_predictions.league_macro_daily.
        # The table existed but was never read by the exporter (same gap as NBA pre-Session 483).
        regime = self._get_regime_context(game_date)
        regime_delta = regime['over_edge_floor_delta']

        # Unified edge floor (no phase logic — regressor sweet spot)
        effective_edge_floor = (edge_floor if edge_floor is not None else DEFAULT_EDGE_FLOOR) + regime_delta
        effective_rescue_tags = frozenset() if regime['disable_rescue'] else RESCUE_SIGNAL_TAGS
        under_enabled = UNDER_ENABLED

        logger.info(f"[MLB BB] Processing {len(predictions)} predictions for {game_date}")
        logger.info(
            f"[MLB BB] Edge floor: {effective_edge_floor:.2f}K (base {DEFAULT_EDGE_FLOOR:.2f}K "
            f"+ regime_delta {regime_delta:.2f}K), away: {AWAY_EDGE_FLOOR}K, "
            f"regime: {regime['market_regime']}, rescue: {'disabled' if regime['disable_rescue'] else 'enabled'}, "
            f"UNDER: {under_enabled}, max picks: {MAX_PICKS_PER_DAY}"
        )

        # Block all OVER picks when model is badly losing to Vegas (mae_gap > 0.3 K)
        if regime['block_all_over']:
            logger.warning(
                f"[MLB BB] MAE gap gate: blocking all OVER picks for {game_date}. "
                f"mae_gap={regime['mae_gap_7d']:.2f} K — model not competitive with books."
            )
            return []

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
            blocked_by_blacklist = False
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
                    if filt.tag == 'pitcher_blacklist':
                        blocked_by_blacklist = True
                    logger.debug(f"[MLB BB] {pitcher} BLOCKED by {filt.tag}: {result.metadata}")
                    break

            if not blocked:
                passed_filters.append(pred)
            elif blocked_by_blacklist:
                # Save for shadow pick tracking — we'll evaluate signals later
                self._blacklist_blocked.append(pred)

        logger.info(f"[MLB BB] {len(passed_filters)} passed negative filters "
                    f"({len(actionable) - len(passed_filters)} blocked)")

        # 3. Edge floor + signal rescue (with away pitcher adjustments)
        edge_eligible = []
        away_blocked = 0
        for pred in passed_filters:
            edge = abs(pred.get('edge', 0))
            pitcher = pred.get('pitcher_lookup', '')
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})

            # Determine home/away for edge floor adjustment
            is_home = pred.get('is_home')
            if is_home is None:
                is_home = features.get('is_home')
            is_away = (is_home is not None and not bool(is_home))

            # Away OVER: higher edge floor (1.25 vs 0.75)
            if pred.get('recommendation') == 'OVER' and is_away:
                pick_edge_floor = AWAY_EDGE_FLOOR
            else:
                pick_edge_floor = effective_edge_floor

            if edge >= pick_edge_floor:
                edge_eligible.append((pred, False))  # (pred, rescued)
                continue

            # Away OVER below away edge floor: block (no rescue)
            if is_away and pred.get('recommendation') == 'OVER' and BLOCK_AWAY_RESCUE:
                away_blocked += 1
                filter_name = 'away_edge_floor'
                if edge >= effective_edge_floor:
                    # Would pass home floor but not away floor
                    filter_reason = (f'Away OVER edge {edge:.2f} < {AWAY_EDGE_FLOOR} '
                                     f'(no rescue for away)')
                else:
                    filter_reason = (f'Away OVER edge {edge:.2f} < {AWAY_EDGE_FLOOR} '
                                     f'(rescue blocked for away)')
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': pitcher,
                    'system_id': pred.get('system_id', 'unknown'),
                    'filter_name': filter_name,
                    'filter_result': 'BLOCKED',
                    'filter_reason': filter_reason,
                    'recommendation': pred.get('recommendation'),
                    'edge': pred.get('edge'),
                    'line_value': pred.get('strikeouts_line'),
                })
                continue

            # Home/unknown pitchers: signal rescue
            # Session 483: uses effective_rescue_tags (frozenset() when market is TIGHT)
            rescued = False
            rescue_signal = None
            for tag in effective_rescue_tags:
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
                    'filter_reason': f'Edge {edge:.1f} < {pick_edge_floor}',
                    'recommendation': pred.get('recommendation'),
                    'edge': pred.get('edge'),
                    'line_value': pred.get('strikeouts_line'),
                })

        if away_blocked:
            logger.info(f"[MLB BB] {away_blocked} away OVER picks blocked "
                        f"(edge < {AWAY_EDGE_FLOOR} or rescue blocked)")
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
                    # Shadow signals and tracking-only don't count toward gate
                    if (signal.tag not in BASE_SIGNAL_TAGS
                            and signal.tag not in TRACKING_ONLY_SIGNALS
                            and not signal.is_shadow):
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

        # OVER: rank by edge (higher = better), tiebreaker signals break ties
        # Tiebreaker: small bonus (0.01) for picks with favorable umpire assignment
        # This only affects picks within ~0.25 K of each other
        def _over_sort_key(p):
            edge = abs(p.get('edge', 0))
            tiebreaker = 0.01 if any(
                t in p.get('signal_tags', []) for t in TIEBREAKER_SIGNALS
            ) else 0.0
            return (edge + tiebreaker)
        over_picks.sort(key=_over_sort_key, reverse=True)

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
        algo_version = 'mlb_v8_s456_v3final_away_5picks'
        for pick in ranked_picks:
            pick['pick_angles'] = self._build_pick_angles(pick)
            pick['algorithm_version'] = algo_version

        # 8b. Evaluate shadow picks for blacklisted pitchers
        shadow_picks = self._evaluate_shadow_picks(
            game_date, ranked_picks, features_by_pitcher,
            supplemental_by_pitcher, effective_edge_floor, min_signals,
            effective_rescue_tags=effective_rescue_tags,
        )

        # 9. Write to BigQuery
        if not dry_run and ranked_picks:
            self._write_best_bets(ranked_picks, game_date)
            self._write_filter_audit(game_date)
        if not dry_run and shadow_picks:
            self._write_shadow_picks(shadow_picks, game_date)

        logger.info(f"[MLB BB] Final best bets: {len(ranked_picks)} "
                    f"(OVER: {len(over_picks)}, UNDER: {len(under_picks)}, "
                    f"ultra: {n_ultra})")

        return ranked_picks

    def _check_ultra(self, pick: Dict, features_by_pitcher: Dict) -> Tuple[bool, List[str]]:
        """Check if a pick qualifies for Ultra tier.

        V3 FINAL: OVER + home + projection agrees + edge >= 0.5 + not rescued.
        Removed: half_line (vacuous — all K lines are x.5), edge 1.1 (hurt 2022-2023).
        Cross-season validated across 2022-2025.

        Returns:
            (is_ultra, criteria_list)
        """
        if pick.get('recommendation') != 'OVER':
            return False, []

        # Rescued picks cannot be Ultra (lowest confidence shouldn't get 2u)
        if pick.get('signal_rescued'):
            return False, []

        criteria = []

        # Half-line check (optional — ULTRA_REQUIRES_HALF_LINE = False in V3)
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

        # Session 460 — new shadow signal angles
        if 'cold_weather_k_over' in signal_results:
            meta = signal_results['cold_weather_k_over'].metadata
            angles.append(f"Cold weather {meta.get('temperature', '?'):.0f}°F — harder to barrel")

        if 'lineup_k_spike_over' in signal_results:
            meta = signal_results['lineup_k_spike_over'].metadata
            angles.append(f"Lineup K-prone: {meta.get('lineup_k_vs_hand', 0):.1%} vs pitcher hand")

        if 'pitch_efficiency_depth_over' in signal_results:
            meta = signal_results['pitch_efficiency_depth_over'].metadata
            angles.append(f"Deep starter: {meta.get('ip_avg_last_5', '?')} IP avg")

        if 'high_csw_over' in signal_results:
            meta = signal_results['high_csw_over'].metadata
            angles.append(f"Elite pitch quality: {meta.get('season_csw_pct', 0):.1%} CSW%")

        if 'elite_peripherals_over' in signal_results:
            meta = signal_results['elite_peripherals_over'].metadata
            angles.append(f"Ace peripherals: {meta.get('fip', '?')} FIP, "
                         f"{meta.get('k_per_9', '?')} K/9")

        if 'game_total_low_over' in signal_results:
            meta = signal_results['game_total_low_over'].metadata
            angles.append(f"Low game total {meta.get('game_total_line', '?')} — deeper outings")

        if 'heavy_favorite_over' in signal_results:
            meta = signal_results['heavy_favorite_over'].metadata
            angles.append(f"Heavy favorite ML {meta.get('team_moneyline', '?')} — starter stays in")

        if 'bottom_up_agrees_over' in signal_results:
            meta = signal_results['bottom_up_agrees_over'].metadata
            angles.append(f"Bottom-up lineup K estimate: {meta.get('bottom_up_k_expected', '?')} "
                         f"(+{meta.get('diff', '?')} vs line)")

        if 'short_starter_under' in signal_results:
            meta = signal_results['short_starter_under'].metadata
            angles.append(f"Short starter: {meta.get('ip_avg_last_5', '?')} IP avg — K upside capped")

        if 'catcher_framing_poor_under' in signal_results:
            meta = signal_results['catcher_framing_poor_under'].metadata
            angles.append(f"Poor catcher framing: {meta.get('catcher_framing_runs', '?')} runs")

        # Session 464 — new shadow signal angles
        if 'k_rate_reversion_under' in signal_results:
            meta = signal_results['k_rate_reversion_under'].metadata
            angles.append(f"K hot streak reversion: {meta.get('k_avg_last_3', '?')} avg "
                         f"vs {meta.get('expected_k', '?')} expected (+{meta.get('k_excess', '?')})")

        if 'k_rate_bounce_over' in signal_results:
            meta = signal_results['k_rate_bounce_over'].metadata
            angles.append(f"K cold streak bounce: {meta.get('k_avg_last_3', '?')} avg "
                         f"vs {meta.get('expected_k', '?')} expected (-{meta.get('k_deficit', '?')})")

        if 'umpire_csw_combo_over' in signal_results:
            meta = signal_results['umpire_csw_combo_over'].metadata
            angles.append(f"K-friendly ump ({meta.get('umpire_k_rate', 0):.1%}) "
                         f"+ high CSW ({meta.get('season_csw_pct', 0):.1%})")

        if 'rest_workload_stress_under' in signal_results:
            meta = signal_results['rest_workload_stress_under'].metadata
            angles.append(f"Fatigue compound: {meta.get('days_rest', '?')}d rest "
                         f"+ {meta.get('games_last_30_days', '?')} games/30d")

        if 'low_era_high_k_combo_over' in signal_results:
            meta = signal_results['low_era_high_k_combo_over'].metadata
            angles.append(f"Dominant ace: {meta.get('season_era', '?')} ERA, "
                         f"{meta.get('k_per_9', '?')} K/9")

        if 'pitcher_on_roll_over' in signal_results:
            meta = signal_results['pitcher_on_roll_over'].metadata
            angles.append(f"On a roll: L3={meta.get('k_avg_last_3', '?')}, "
                         f"L5={meta.get('k_avg_last_5', '?')} > {meta.get('line', '?')} line")

        # Session 464 round 2 — research-backed shadow signal angles
        if 'chase_rate_over' in signal_results:
            meta = signal_results['chase_rate_over'].metadata
            angles.append(f"High chase rate: {meta.get('o_swing_pct', 0):.1%} O-Swing%")

        if 'contact_specialist_under' in signal_results:
            meta = signal_results['contact_specialist_under'].metadata
            angles.append(f"Contact-heavy lineup: {meta.get('z_contact_pct', 0):.1%} Z-Contact%")

        if 'humidity_over' in signal_results:
            meta = signal_results['humidity_over'].metadata
            angles.append(f"High humidity {meta.get('humidity_pct', '?')}% — reduced ball carry")

        if 'fresh_opponent_over' in signal_results:
            meta = signal_results['fresh_opponent_over'].metadata
            angles.append(f"Fresh opponent matchup ({meta.get('vs_opponent_games', '?')} prior games)")

        if pick.get('ultra_tier'):
            criteria = pick.get('ultra_criteria', [])
            angles.append(f"ULTRA: {', '.join(criteria)} — 2u stake")

        return angles

    def _evaluate_shadow_picks(
        self,
        game_date: str,
        ranked_picks: List[Dict],
        features_by_pitcher: Dict,
        supplemental_by_pitcher: Dict,
        edge_floor: float,
        min_signals: int,
        effective_rescue_tags: frozenset = RESCUE_SIGNAL_TAGS,
    ) -> List[Dict]:
        """Evaluate blacklist-blocked picks as shadow picks for counterfactual tracking.

        Runs the same signal evaluation and ranking logic as real picks, then
        computes where each shadow pick would have ranked if not blacklisted.
        """
        if not self._blacklist_blocked:
            return []

        shadow_picks = []
        for pred in self._blacklist_blocked:
            pitcher = pred.get('pitcher_lookup', '')
            edge = abs(pred.get('edge', 0))
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})

            # Apply edge floor with away adjustment (same as real picks)
            is_home = pred.get('is_home')
            if is_home is None:
                is_home = features.get('is_home')
            is_away = (is_home is not None and not bool(is_home))

            pick_edge_floor = edge_floor
            if pred.get('recommendation') == 'OVER' and is_away:
                pick_edge_floor = AWAY_EDGE_FLOOR

            if edge < pick_edge_floor:
                # Away OVER below away floor: no rescue
                if is_away and pred.get('recommendation') == 'OVER' and BLOCK_AWAY_RESCUE:
                    continue  # Would have been blocked by away edge floor

                # Check rescue signals (Session 483: effective_rescue_tags, empty when TIGHT)
                rescued = False
                for tag in effective_rescue_tags:
                    signal = self.registry.get(tag)
                    result = signal.evaluate(pred, features, supplemental)
                    if result.qualifies:
                        rescued = True
                        break
                if not rescued:
                    continue  # Would have been blocked by edge floor anyway

            # Evaluate all signals (same as step 4)
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
                    # Shadow signals and tracking-only don't count toward gate
                    if (signal.tag not in BASE_SIGNAL_TAGS
                            and signal.tag not in TRACKING_ONLY_SIGNALS
                            and not signal.is_shadow):
                        real_signal_count += 1

            # Apply signal count gate (same as step 5)
            rec = pred.get('recommendation', 'OVER')
            required = UNDER_MIN_SIGNALS if rec == 'UNDER' else min_signals
            if real_signal_count < required:
                continue  # Would have been blocked by signal gate

            # Compute rank position: where would this pick fall among real picks?
            # For OVER picks, rank by edge
            rank_position = 1
            for real_pick in ranked_picks:
                if abs(real_pick.get('edge', 0)) > edge:
                    rank_position += 1
            would_be_selected = rank_position <= MAX_PICKS_PER_DAY

            # Check ultra tier
            shadow_pred = {**pred, 'signal_tags': signal_tags}
            is_ultra, ultra_criteria = self._check_ultra(shadow_pred, features_by_pitcher)

            # Build pick angles
            annotated = {
                **pred,
                'signal_tags': signal_tags,
                'signal_results': signal_results,
                'ultra_tier': is_ultra,
            }
            pick_angles = self._build_pick_angles(annotated)

            shadow_picks.append({
                'game_date': game_date,
                'pitcher_lookup': pitcher,
                'game_pk': int(pred['game_id']) if pred.get('game_id') else None,
                'system_id': pred.get('system_id', 'unknown'),
                'pitcher_name': pred.get('pitcher_name'),
                'team_abbr': pred.get('team_abbr'),
                'opponent_team_abbr': pred.get('opponent_team_abbr'),
                'predicted_strikeouts': pred.get('predicted_strikeouts'),
                'line_value': pred.get('strikeouts_line'),
                'recommendation': rec,
                'edge': pred.get('edge'),
                'confidence_score': pred.get('confidence'),
                'signal_tags': ','.join(signal_tags),
                'signal_count': signal_count,
                'real_signal_count': real_signal_count,
                'rank_position': rank_position,
                'would_be_selected': would_be_selected,
                'ultra_tier': is_ultra,
                'pick_angles': ','.join(pick_angles),
            })

        if shadow_picks:
            logger.info(f"[MLB BB] {len(shadow_picks)} shadow picks from blacklist "
                        f"({sum(1 for s in shadow_picks if s['would_be_selected'])} would be selected)")

        return shadow_picks

    def _write_shadow_picks(self, shadow_picks: List[Dict], game_date: str):
        """Write shadow picks to blacklist_shadow_picks table for counterfactual tracking."""
        client = self._get_bq_client()
        table_id = f"{self.project_id}.mlb_predictions.blacklist_shadow_picks"

        now = datetime.now(timezone.utc).isoformat()
        rows = [{**pick, 'created_at': now} for pick in shadow_picks]

        try:
            errors = client.insert_rows_json(table_id, rows)
            if errors:
                logger.error(f"Shadow picks insert errors: {errors[:3]}")
            else:
                logger.info(f"Wrote {len(rows)} shadow picks to {table_id}")
        except Exception as e:
            logger.error(f"Failed to write shadow picks: {e}")

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
            # game_pk is REQUIRED (NOT NULL). Skip picks without it rather than
            # letting one bad row sink the entire batch insert.
            game_pk = int(pick['game_id']) if pick.get('game_id') else None
            if game_pk is None:
                logger.error(
                    f"[MLB BB] Skipping {pick.get('pitcher_lookup')} — no game_pk "
                    f"(game_id missing from prediction dict, schedule lookup failed)"
                )
                continue

            # Session 518: clamp confidence to BQ NUMERIC(4,3) bounds [-9.999, 9.999].
            # The regressor's confidence value can exceed 10 (observed 5-20+) but the
            # signal_best_bets_picks schema is more constrained than pitcher_strikeouts.
            raw_conf = pick.get('confidence')
            confidence_clamped = (
                max(-9.999, min(9.999, raw_conf))
                if raw_conf is not None
                else None
            )
            rows.append({
                'pitcher_lookup': pick['pitcher_lookup'],
                'game_pk': game_pk,
                'game_date': game_date,
                'system_id': pick.get('system_id', 'unknown'),
                'pitcher_name': pick.get('pitcher_name'),
                'team_abbr': pick.get('team_abbr'),
                'opponent_team_abbr': pick.get('opponent_team_abbr'),
                'predicted_strikeouts': pick.get('predicted_strikeouts'),
                'line_value': pick.get('strikeouts_line'),
                'recommendation': pick.get('recommendation'),
                'edge': pick.get('edge'),
                'confidence_score': confidence_clamped,
                'signal_tags': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'real_signal_count': pick.get('real_signal_count', 0),
                'rank': pick.get('rank'),
                # Explicitly set REPEATED fields that BQ requires non-null
                'warning_tags': [],
                'agreeing_model_ids': [],
                'pick_angles': pick.get('pick_angles', []),
                'algorithm_version': pick.get('algorithm_version', 'mlb_v2'),
                'source_model_id': pick.get('system_id'),
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
