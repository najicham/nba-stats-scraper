"""Best Bets Aggregator — edge-first selection with signal-based filtering.

Session 297: MAJOR ARCHITECTURE CHANGE — edge-first selection.
    Analysis showed the model's edge IS the signal:
      - green_light subset (edge 5+, signal day): 78.0% HR, +$69 units
      - ultra_high_edge (edge 7+): 80.2% HR, +$43 units
      - signal-scored best bets: 59.8% HR, +$17 units
    Signals were SELECTING low-edge picks via composite scoring, diluting
    the model's high-edge winners. Now:
      1. Edge 5+ is the primary filter (was no floor, then 3.0)
      2. UNDER edge 7+ blocked (40.7% HR — catastrophic)
      3. Picks ranked by edge (not composite score)
      4. Signals used for pick angles (explanations) only
      5. Negative filters (blacklist, familiar, quality) still applied
    Projected: 71% HR (up from 59.8%)

Session 298: Natural sizing — removed MAX_PICKS_PER_DAY=5 hard cap.
    Let edge floor + negative filters determine the natural pick count.
    Some days 2 picks, some days 8 — that's honest.

Session 314: Consolidated best bets systems — aggregate() now returns
    (picks, filter_summary) tuple tracking per-filter rejection counts.
    Removed ANTI_PATTERN combo entries that blocked all edge 5+ candidates.
    Both SignalBestBetsExporter (System 2) and SignalAnnotator bridge
    (System 3) now share the same filters via this aggregator.

Session 316: Refined UNDER 7+ block to allow star-level lines (25+).
    Session 318: Reverted star-level exception (N=7 too small, 37.5% HR in best bets).
    UNDER edge 7+ is now an unconditional block again.

Prior history (Sessions 259-298):
    Session 259: Registry-based combo scoring, MIN_SIGNAL_COUNT=2.
    Session 260: Signal health weighting (HOT/COLD multipliers).
    Session 264: COLD model-dependent signals → 0.0x weight.
    Session 279: Pick provenance (qualifying_subsets + algorithm_version).
    Session 284: Player blacklist, avoid-familiar, remove rel_edge filter.
    Session 294: UNDER line-jump/line-drop/neg-pm blocks.
    Session 297: Edge-first architecture, edge floor 5.0, UNDER 7+ block.
    Session 298: Natural sizing — removed MAX_PICKS_PER_DAY cap.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from ml.signals.base_signal import SignalResult
from ml.signals.combo_registry import ComboEntry, load_combo_registry, match_combo
from ml.signals.signal_health import MODEL_DEPENDENT_SIGNALS
from shared.config.calendar_regime import detect_regime
from shared.config.model_selection import get_min_confidence

logger = logging.getLogger(__name__)

# Bump whenever scoring formula, filters, or combo weights change
ALGORITHM_VERSION = 'v429_signal_weight_cleanup'

# Base signals that fire on nearly every edge 5+ pick. Picks with ONLY
# these signals hit 57.1% (N=42) vs 77.8% for picks with 4+ signals.
# Session 348 analysis: the additional signals (rest_advantage_2d,
# combo_he_ms, combo_3way, book_disagreement, etc.) are what separate
# profitable picks from marginal ones.
BASE_SIGNALS = frozenset({
    'model_health', 'high_edge', 'edge_spread_optimal',
    'blowout_recovery',   # Session 422: 20% BB HR (1-4), demoted — still fires for tracking
    'starter_under',      # Session 422: 38.7% signal HR (N=31), demoted
    'blowout_risk_under', # Session 422b: 16.7% HR (N=12), inflating SC on bad picks
})

# Session 400: UNDER signal quality weights for signal-first ranking.
# UNDER edge is flat at 52-53% across all buckets — signals are the quality
# discriminator. Weights derived from backtest HR (higher HR = higher weight).
UNDER_SIGNAL_WEIGHTS: Dict[str, float] = {
    'sharp_book_lean_under': 1.0,   # Session 423: demoted 3.0→1.0. 84.7% backtest but ZERO production fires — market regime makes negative lean nonexistent
    # mean_reversion_under removed Session 429: cross-season decay below 2026 baseline (53.0% vs 54.3%). Was 2.5→1.5→removed.
    'sharp_line_drop_under': 2.5,   # Session 422c: 87.5% HR (N=8) — already fires, now weighted
    'book_disagreement': 2.5,        # 93.0% HR (N=43)
    'bench_under': 2.0,              # 76.9% HR
    'home_under': 2.0,               # Session 422c: boosted from 1.5. 60.6% HR (N=4,253) model-level
    'starter_away_overtrend_under': 1.5,  # Session 423: 68.1% HR (N=213), monthly stable, shadow
    'extended_rest_under': 1.5,      # 61.8% HR
    'volatile_starter_under': 2.0,   # Session 427: promoted 1.5→2.0. Cross-season +11.1pp lift (best UNDER signal)
    'downtrend_under': 2.0,          # Session 427: promoted 1.5→2.0. Cross-season +8.1pp lift, increasing trend
    # star_favorite_under removed Session 427: +0.7pp lift = noise, 73% HR from N=88 was single-season artifact
    # starter_under removed Session 419 (38.7% signal HR N=31, demoted to BASE_SIGNALS)
}
UNDER_EDGE_TIEBREAKER = 0.1  # Edge as minor tiebreaker for UNDER

# Session 372: Teams with catastrophic UNDER HR (edge 3+, Dec 1+, N>=190).
# High-variance offenses where scoring exceeds expectations.
# Re-evaluate monthly as rosters change. Last validated: 2026-02-28.
# MIN 43.8% (N=219), MEM 46.7% (N=197), MIL 48.7% (N=193).
# Session 377: Added IND — 42.7% full-season HR (N=426), 18.9% Feb (N=185).
UNDER_TOXIC_OPPONENTS = frozenset({'MIN', 'MEM', 'MIL', 'IND'})

# Signal health regime → weight multiplier (used for pick angles context)
HEALTH_MULTIPLIERS = {
    'HOT': 1.2,
    'NORMAL': 1.0,
    'COLD': 0.5,
}

# Session 421: Player-tier edge caps (observation mode).
# Bench/role players at high edge = severe overconfidence during toxic windows.
# Bench edge 7+: 34.1% HR (N=91). Role edge 7+: 43.1% HR (N=72).
# For OVER ranking only. Caps effective edge used in composite_score.
TIER_EDGE_CAPS = {
    'bench': 5.0,     # line < 12: 34.1% HR at edge 7+ (N=91)
    'role': 6.0,      # line 12-17.5: 43.1% HR at edge 7+ (N=72)
    'starter': None,   # line 18-24.5: uncapped (63.2% HR)
    'star': None,      # line 25+: uncapped
}


class BestBetsAggregator:
    """Edge-first best bets selection with signal-based filtering.

    Selection (Session 297-298):
        1. Filter: edge >= 5.0 (edge <5 hits 57%, edge 5+ hits 71%)
        2. Filter: negative filters (blacklist, quality, UNDER blocks)
        3. Rank: by edge descending (model confidence = primary signal)
        4. Return: all qualifying picks (natural sizing, Session 298)
        5. Annotate: signal tags attached for pick angles (explanations)

    Negative Filters:
        - Player blacklist: <40% HR on 8+ picks → skip (Session 284)
        - Avoid familiar: 6+ games vs this opponent → skip (Session 284)
        - MIN_EDGE = 3.0: lowered from 5.0 — edge 3-4 is best V12 band during degradation (Session 352)
        - OVER edge 5+ floor: edge 3-5 OVER = 25% HR (1-3), edge 5+ OVER = 68-78% (Session 378)
        - UNDER edge 7+ block: V9 only (34.1% HR), V12/V16/V13/V15/LightGBM allowed (Session 297, narrowed 367)
        - Feature quality floor: quality < 85 → skip (24.0% HR)
        - Bench UNDER block: UNDER + line < 12 → skip (35.1% HR)
        - Line jumped UNDER block: UNDER + line jumped 2+ → skip (38.2% HR, Session 306)
        - Line dropped UNDER block: UNDER + line dropped 2+ → skip (35.2% HR, Session 306)
        - Neg +/- streak UNDER block: UNDER + 3+ neg games → skip (13.1% HR)
        - AWAY block: REMOVED Session 401 (root cause was model staleness, not structural)
        - Signal density: base-only signals → skip unless edge ≥ 7 (Session 352 bypass)
        - ANTI_PATTERN combos → skip

    Session 370: MIN_SIGNAL_COUNT raised from 2 to 3.
    Session 388: Edge-tiered signal count — SC >= 4 for edge < 7, SC >= 3 for edge 7+.
        SC=3 at edge 5-7 = 51.3% HR (N=39) — weakest link in filter stack.
        SC=4 at edge 5-7 = 70.6% HR (N=17). SC=3 at edge 7+ = 85.7% (N=7) — preserved.
        Subsumes SC=3 OVER edge gate (Session 374b) — ALL SC=3 at edge < 7 now blocked.
    """

    MIN_SIGNAL_COUNT = 3           # Base floor for edge 7+ (Session 370)
    # Session 393: Lowered from 4 → 3. SC=3 at edge 5-7 = 50% HR stat was from
    # now-disabled models (98% of graded picks). New fleet in bootstrapping phase
    # with ~0 graded data. Signal_density filter still blocks base-only SC=3 picks.
    MIN_SIGNAL_COUNT_LOW_EDGE = 3  # Edge < 7 (was 4, Session 388; relaxed Session 393)
    HIGH_EDGE_SC_THRESHOLD = 7.0   # Edge dividing SC tiers
    MIN_EDGE = 3.0                 # Lowered from 5.0 (Session 352): edge 3-4 is best V12 band during model degradation

    def __init__(
        self,
        combo_registry: Optional[Dict[str, ComboEntry]] = None,
        signal_health: Optional[Dict[str, Dict[str, Any]]] = None,
        model_id: Optional[str] = None,
        cross_model_factors: Optional[Dict[str, Dict[str, Any]]] = None,
        qualifying_subsets: Optional[Dict[str, List[Dict]]] = None,
        player_blacklist: Optional[Set[str]] = None,
        model_direction_blocks: Optional[Set[tuple]] = None,
        model_direction_affinity_stats: Optional[Dict] = None,
        model_profile_store: Optional[Any] = None,
        regime_context: Optional[Dict[str, Any]] = None,
    ):
        if combo_registry is not None:
            self._registry = combo_registry
        else:
            self._registry = load_combo_registry(bq_client=None)
        self._signal_health = signal_health or {}
        self._min_confidence = get_min_confidence(model_id or '')
        self._cross_model_factors = cross_model_factors or {}
        self._qualifying_subsets = qualifying_subsets or {}
        self._player_blacklist = player_blacklist or set()
        self._model_direction_blocks = model_direction_blocks or set()
        self._model_direction_affinity_stats = model_direction_affinity_stats
        self._model_profile_store = model_profile_store
        self._regime_context = regime_context or {}

    def aggregate(self, predictions: List[Dict],
                  signal_results: Dict[str, List[SignalResult]]) -> Tuple[List[Dict], Dict]:
        """Select top picks for a single game date.

        Edge-first: picks are ranked by edge (model confidence), not by
        signal composite score. Signals are attached for pick angles only.

        Session 393: Also collects filtered-out picks for counterfactual
        tracking. Access via filter_summary['filtered_picks'].

        Returns:
            Tuple of (picks, filter_summary) where filter_summary tracks
            how many candidates were rejected by each filter.
        """
        scored = []
        # Track all filter rejections
        filter_counts = {
            'blacklist': 0,
            'edge_floor': 0,
            'over_edge_floor': 0,
            'under_edge_7plus': 0,
            'familiar_matchup': 0,
            'quality_floor': 0,
            'bench_under': 0,
            'line_jumped_under': 0,
            'line_dropped_under': 0,
            'line_dropped_over': 0,
            'neg_pm_streak': 0,
            'signal_count': 0,
            'sc3_edge_floor': 0,  # Retained for schema continuity — subsumed by edge-tiered SC (Session 388)
            'sc3_over_block': 0,
            'opponent_depleted_under': 0,
            'high_book_std_under': 0,
            'confidence': 0,
            'anti_pattern': 0,
            'model_direction_affinity': 0,
            'away_noveg': 0,
            'star_under': 0,
            'under_star_away': 0,
            'med_usage_under': 0,
            'starter_v12_under': 0,
            'starter_over_sc_floor': 0,
            'opponent_under_block': 0,
            'q4_scorer_under_block': 0,
            'friday_over_block': 0,
            'high_skew_over_block': 0,
            'signal_density': 0,
            'legacy_block': 0,
            'model_profile_would_block': 0,
            'toxic_starter_over_would_block': 0,
            'toxic_star_over_would_block': 0,
            'regime_over_floor': 0,
            'regime_rescue_blocked': 0,
            'high_spread_over_would_block': 0,
            'flat_trend_under': 0,
            'under_after_streak': 0,
            'under_after_bad_miss': 0,
            'mid_line_over_obs': 0,
            'monday_over_obs': 0,
            'home_over_obs': 0,
            'signal_stack_2plus_obs': 0,
            'rescue_cap': 0,
            'unreliable_over_low_mins_obs': 0,
            'unreliable_under_flat_trend_obs': 0,
            'b2b_under_block': 0,
            'blowout_risk_under_block_obs': 0,
        }

        # Session 393: Counterfactual tracking — log filtered-out picks so we
        # can grade them post-hoc and validate each filter's value.
        filtered_picks: List[Dict] = []

        def _record_filtered(pred_dict: Dict, filter_name: str,
                             pred_edge_val: float = 0.0,
                             sig_count: int = 0,
                             sig_tags: Optional[List[str]] = None) -> None:
            """Record a filtered-out pick for counterfactual analysis."""
            filtered_picks.append({
                'player_lookup': pred_dict.get('player_lookup', ''),
                'game_id': pred_dict.get('game_id', ''),
                'game_date': pred_dict.get('game_date', ''),
                'system_id': pred_dict.get('system_id', ''),
                'team_abbr': pred_dict.get('team_abbr', ''),
                'opponent_team_abbr': pred_dict.get('opponent_team_abbr', ''),
                'recommendation': pred_dict.get('recommendation', ''),
                'predicted_points': pred_dict.get('predicted_points'),
                'line_value': pred_dict.get('line_value') or pred_dict.get('current_points_line'),
                'edge': round(pred_edge_val, 1),
                'signal_count': sig_count,
                'signal_tags': sig_tags or [],
                'filter_reason': filter_name,
            })

        # Session 378c: Model sanity guard — detect and block models whose
        # predictions are severely imbalanced (>90% one direction). A broken
        # model (e.g., XGBoost version mismatch producing all UNDER with
        # inflated edges) can dominate per-player selection and poison all
        # best bets picks. This catches the problem at the aggregator level.
        from collections import defaultdict
        model_direction_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {'OVER': 0, 'UNDER': 0})
        for pred in predictions:
            rec = pred.get('recommendation')
            if rec in ('OVER', 'UNDER'):
                model_direction_counts[pred.get('system_id', '')][rec] += 1
        blocked_models: Set[str] = set()
        for model_id, counts in model_direction_counts.items():
            total = counts['OVER'] + counts['UNDER']
            if total >= 20:  # Need enough predictions to judge
                over_pct = counts['OVER'] / total
                if over_pct > 0.95 or over_pct < 0.05:
                    blocked_models.add(model_id)
                    dominant = 'OVER' if over_pct > 0.5 else 'UNDER'
                    logger.warning(
                        f"Model sanity guard: blocking {model_id} — "
                        f"{max(over_pct, 1 - over_pct):.0%} {dominant} ({total} predictions). "
                        f"Extreme direction imbalance suggests miscalibration."
                    )

        # Session 382: Legacy model blocklist — hardcoded models not in registry
        # that bypass all registry controls. catboost_v12: 33.3% BB HR (6 picks),
        # catboost_v9: 37.5% BB HR (12 picks). These are loaded directly by
        # worker.py, not via the registry, so they cannot be disabled via enabled=FALSE.
        LEGACY_MODEL_BLOCKLIST = frozenset({'catboost_v12', 'catboost_v9'})
        legacy_blocked = LEGACY_MODEL_BLOCKLIST - blocked_models
        if legacy_blocked:
            blocked_models.update(legacy_blocked)
            logger.info(
                f"Legacy model blocklist: blocking {legacy_blocked} — "
                f"hardcoded models bypass registry controls"
            )

        for pred in predictions:
            # --- Negative filters (order: cheapest checks first) ---

            # Model sanity guard (Session 378c) + legacy blocklist (Session 382)
            pred_system_id = pred.get('system_id', '')
            if pred_system_id in blocked_models:
                if pred_system_id in LEGACY_MODEL_BLOCKLIST:
                    filter_counts['legacy_block'] += 1
                continue

            # Player blacklist (Session 284)
            pred_edge_early = abs(pred.get('edge') or 0)
            if pred['player_lookup'] in self._player_blacklist:
                filter_counts['blacklist'] += 1
                if pred_edge_early >= 3.0:
                    _record_filtered(pred, 'blacklist', pred_edge_early)
                continue

            # Edge floor: lowered to 3.0 (Session 352) — signal filters provide quality gate
            # Session 355: Premium signals with high HR are exempt from edge floors.
            # Session 398: Expanded from combo-only to include validated high-HR signals.
            # Signals measure contextual conditions (pace, line movement, home/away) that
            # are orthogonal to model edge. A pick with low edge but strong signal context
            # can still be profitable. Rescued picks are tracked via signal_rescued flag.
            pred_edge = abs(pred.get('edge') or 0)
            below_edge_floor = pred_edge < self.MIN_EDGE

            # Session 398: Signal rescue — check for qualifying high-HR signals
            # that can independently justify a pick regardless of model edge.
            # These signals have 65%+ HR at edge 0-3 on N>=5 (validated via BQ).
            signal_rescued = False
            rescue_signal = None
            if below_edge_floor or (pred.get('recommendation') == 'OVER' and pred_edge < 5.0):
                key_for_signal_check = f"{pred['player_lookup']}::{pred['game_id']}"
                signal_check = signal_results.get(key_for_signal_check, [])
                # Signals that can rescue picks from edge floor:
                # - combo_3way, combo_he_ms: 88%+ HR in best bets (original premium)
                # - book_disagreement: 72.0% HR at edge 0-3 (N=25)
                # - home_under: 75.0% HR at edge 0-3 (N=8)
                # - low_line_over: 66.7% HR at edge 0-3 (N=6)
                # - volatile_scoring_over: 66.7% HR at edge 0-3 (N=6)
                # - high_scoring_environment_over: 100% HR at edge 3-5 (N=7)
                # - sharp_book_lean_over: 70.3% HR (N=508, Session 399)
                # - sharp_book_lean_under: 84.7% HR (N=202, Session 399)
                # Session 415: Removed low_line_over (0% HR in rescued BB).
                # Session 420: Restored high_scoring_environment_over —
                # 71.4% HR (5-7) overall, 3-0 on Mar 5. Removal killed
                # OVER pipeline (0 OVER picks at edge 5+ on Mar 6).
                rescue_tags = {
                    'combo_3way', 'combo_he_ms',
                    'book_disagreement', 'home_under',
                    'volatile_scoring_over',
                    'high_scoring_environment_over',  # Session 420: restored (71.4% HR)
                    'sharp_book_lean_over', 'sharp_book_lean_under',
                    # mean_reversion_under removed Session 427: cross-season decay
                    # 75.7%(2024)→65.2%(2025)→53.0%(2026), below 2026 baseline
                }
                for r in signal_check:
                    if r.qualifies and r.source_tag in rescue_tags:
                        signal_rescued = True
                        rescue_signal = r.source_tag
                        break

                # Session 415: signal_stack_2plus demoted to observation-only.
                # 50% HR at N=6 in rescued BB — thinnest quality tier, all OVER.
                # Track counterfactual but do NOT rescue.
                if not signal_rescued:
                    qualifying_signals = [
                        r for r in signal_check
                        if r.qualifies and r.source_tag not in BASE_SIGNALS
                    ]
                    if len(qualifying_signals) >= 2:
                        filter_counts['signal_stack_2plus_obs'] += 1
                        _record_filtered(
                            pred, 'signal_stack_2plus_obs', pred_edge,
                            len(qualifying_signals),
                            [r.source_tag for r in qualifying_signals],
                        )

                # Session 412: Regime gating — during cautious regime (yesterday
                # BB HR < 50%), track what WOULD be blocked for counterfactual.
                # Session 413: Observation-only — regime on N=7 nuked 10/12 picks.
                # Next-day avg after bad day is still 53.9% (above breakeven).
                if (signal_rescued
                        and self._regime_context.get('disable_over_rescue')
                        and pred.get('recommendation') == 'OVER'):
                    filter_counts['regime_rescue_blocked'] += 1
                    _record_filtered(pred, 'regime_rescue_blocked', pred_edge)
                    # Observation mode — do NOT disable rescue

            if below_edge_floor:
                if not signal_rescued:
                    filter_counts['edge_floor'] += 1
                    continue
                # Signal rescue: bypass edge floor
                filter_counts.setdefault('signal_rescue', 0)
                filter_counts['signal_rescue'] += 1
                logger.debug(
                    f"Signal rescue: {pred['player_lookup']} edge={pred_edge:.1f} "
                    f"rescued by {rescue_signal}"
                )

            # Session 378→419: OVER edge floor. Originally 5.0 based on stale 25%
            # HR (1-3, pre-filter-stack). Post-ASB edge 3-5 OVER = 67.6% (N=105).
            # CF: 87.5% (7-1) blocked winners. Specific OVER filters (friday,
            # high_spread, mid_line, high_skew) already catch bad OVER categories.
            # Lowered to 3.0 (effectively MIN_EDGE) — the blanket floor is redundant.
            over_floor = 3.0  # Session 419: lowered from 5.0
            regime_delta = self._regime_context.get('over_edge_floor_delta', 0)
            if pred.get('recommendation') == 'OVER' and pred_edge < over_floor and not signal_rescued:
                filter_counts['over_edge_floor'] += 1
                _record_filtered(pred, 'over_edge_floor', pred_edge)
                continue
            # Observation: track what regime floor WOULD block
            if (regime_delta > 0
                    and pred.get('recommendation') == 'OVER'
                    and over_floor <= pred_edge < over_floor + regime_delta
                    and not signal_rescued):
                filter_counts['regime_over_floor'] += 1
                _record_filtered(pred, 'regime_over_floor', pred_edge)

            # UNDER at edge 7+ block (Session 297, narrowed Session 367):
            # V9 UNDER 7+: 34.1% HR (N=41) — catastrophic, keep blocked.
            # V12 models: already allowed (100% HR at 7+).
            # V16/V13/V15/LightGBM: no graded data yet but not V9's structural issue.
            # v9_low_vegas: separate affinity group (62.5% UNDER), exempt.
            # Session 318: Removed star-level exception (N=7 too small, 37.5% HR).
            source_family = pred.get('source_model_family', '')
            if (pred.get('recommendation') == 'UNDER'
                    and pred_edge >= 7.0
                    and source_family.startswith('v9')
                    and source_family != 'v9_low_vegas'):
                filter_counts['under_edge_7plus'] += 1
                _record_filtered(pred, 'under_edge_7plus', pred_edge)
                continue

            # Model-direction affinity block (Session 330): data-driven
            # block of model+direction+edge combos with proven poor HR.
            # Phase 1: observation mode (threshold=0.0, nothing blocked).
            if self._model_direction_blocks:
                from ml.signals.model_direction_affinity import check_model_direction_block
                block_reason = check_model_direction_block(
                    source_family, pred.get('recommendation', ''), pred_edge,
                    self._model_direction_blocks)
                if block_reason:
                    filter_counts['model_direction_affinity'] += 1
                    _record_filtered(pred, 'model_direction_affinity', pred_edge)
                    continue

            # AWAY block REMOVED (Session 401):
            # Original (Session 347/365): v12_noveg 43.8% AWAY, v9 48.1% AWAY
            # Root cause was model staleness (train_1102 vintage = 44.1% AWAY),
            # NOT structural. Newer models (Jan+ training) show zero HOME/AWAY gap:
            # 61.0% AWAY vs 63.3% HOME. March AWAY noveg = 60.0% (N=45).
            # Filter was #1 blocker (9 rejections in 2 days), blocking winning picks.

            # Avoid familiar matchups (Session 284)
            games_vs_opp = pred.get('games_vs_opponent') or 0
            if games_vs_opp >= 6:
                filter_counts['familiar_matchup'] += 1
                _record_filtered(pred, 'familiar_matchup', pred_edge)
                continue

            # Feature quality floor (Session 278): quality < 85 = 24.0% HR
            # Session 310: quality=0 (missing) must also be blocked, not passed through
            quality = pred.get('feature_quality_score') or 0
            if quality < 85:
                filter_counts['quality_floor'] += 1
                _record_filtered(pred, 'quality_floor', pred_edge)
                continue

            # Bench UNDER — DEMOTED to observation (Session 419).
            # Original 35.1% HR was pre-filter-stack. CF HR = 100% (2-0, blocking winners).
            # Other UNDER filters (flat_trend, opponent, med_usage) catch bad UNDER picks.
            line_val = pred.get('line_value') or 0
            if pred.get('recommendation') == 'UNDER' and line_val > 0 and line_val < 12:
                filter_counts['bench_under'] += 1
                _record_filtered(pred, 'bench_under_obs', pred_edge)
                # continue  # Session 419: observation mode — do NOT block

            # Star UNDER block — REMOVED Session 400.
            # Was 50.0% Feb (toxic window) but recovered to 72.1% Mar (N=61).
            # Signal-supported star UNDER: 71.4% Mar (N=7). Blanket block
            # was killing highest-edge multi-model picks (Maxey 8.5, SGA 6.6).
            # Research agent investigating seasonal activation pattern.
            # Filter counter retained for schema continuity.
            season_avg = pred.get('points_avg_season') or 0

            # UNDER Star AWAY observation (Session 369→415): Was 38.5% HR at creation
            # (toxic Feb) but recovered to 73.0% post-ASB. Demoted to observation
            # Session 415 — collect 2 weeks fresh data before re-evaluation.
            if (pred.get('recommendation') == 'UNDER'
                    and line_val >= 23
                    and not pred.get('is_home', False)):
                filter_counts['under_star_away'] += 1
                _record_filtered(pred, 'under_star_away', pred_edge)
                # Observation mode — do NOT continue/filter

            # Medium teammate usage UNDER block (Session 355): 32.0% HR (N=25)
            # Model has 0% importance on teammate_usage_available but production
            # data shows when moderate usage is available (15-30), UNDER = catastrophic.
            teammate_usage = pred.get('teammate_usage_available') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and 15 <= teammate_usage <= 30):
                filter_counts['med_usage_under'] += 1
                _record_filtered(pred, 'med_usage_under', pred_edge)
                continue

            # B2B UNDER block (Session 422c): 30.8% HR (N=52) — B2B players go OVER
            # at high rates. Market underprices fatigue or model overestimates it.
            rest_days = pred.get('rest_days') or 99
            if (pred.get('recommendation') == 'UNDER'
                    and rest_days <= 1):
                filter_counts['b2b_under_block'] += 1
                _record_filtered(pred, 'b2b_under_block', pred_edge)
                continue

            # starter_v12_under REMOVED (Session 422b): Dead filter — zero fires
            # across entire season. startswith('v12') missed lgbm/xgb models,
            # and season_avg vs line_value mismatch meant no picks matched.

            # Line jumped UNDER — DEMOTED to observation (Session 417)
            # Was 38.2% HR (N=272, Session 294), but recent: 5/5 winners blocked.
            # Now logs to filtered_picks for tracking but does NOT block.
            prop_line_delta = pred.get('prop_line_delta')
            if (prop_line_delta is not None
                    and prop_line_delta >= 2.0
                    and pred.get('recommendation') == 'UNDER'):
                filter_counts['line_jumped_under'] += 1
                _record_filtered(pred, 'line_jumped_under_obs', pred_edge)
                # continue  # Session 417: observation only — do not block

            # Line dropped UNDER block (Session 294, lowered 306): 35.2% HR at 2.0 (N=108)
            if (prop_line_delta is not None
                    and prop_line_delta <= -2.0
                    and pred.get('recommendation') == 'UNDER'):
                filter_counts['line_dropped_under'] += 1
                _record_filtered(pred, 'line_dropped_under', pred_edge)
                continue

            # Line dropped OVER — DEMOTED to observation (Session 428).
            # Original 39.1% HR was Feb toxic window (N=23). Full-season CF HR = 60.0%
            # (N=477) — blocking profitable picks. Market line drops may reflect injury
            # news that the model already incorporates.
            if (prop_line_delta is not None
                    and prop_line_delta <= -2.0
                    and pred.get('recommendation') == 'OVER'):
                filter_counts['line_dropped_over'] += 1
                _record_filtered(pred, 'line_dropped_over_obs', pred_edge)
                # continue  # Session 428: observation mode — do NOT block

            # Neg +/- streak UNDER — DEMOTED to observation (Session 428).
            # Original 13.1% HR was from early data. Full-season CF HR = 64.5%
            # (N=758) — highest CF HR of any filter. Blocking the most profitable picks.
            neg_pm_streak = pred.get('neg_pm_streak') or 0
            if neg_pm_streak >= 3 and pred.get('recommendation') == 'UNDER':
                filter_counts['neg_pm_streak'] += 1
                _record_filtered(pred, 'neg_pm_streak_obs', pred_edge)
                # continue  # Session 428: observation mode — do NOT block

            # Opponent team UNDER block (Session 372)
            # MIN 43.8%, MEM 46.7%, MIL 48.7% UNDER HR (edge 3+, N>=190)
            if (pred.get('recommendation') == 'UNDER'
                    and pred.get('opponent_team_abbr', '') in UNDER_TOXIC_OPPONENTS):
                filter_counts['opponent_under_block'] += 1
                _record_filtered(pred, 'opponent_under_block', pred_edge)
                continue

            # Opponent depleted UNDER block (Session 374b): UNDER + 3+ opponent stars out = 44.4% HR (N=207).
            # When opponent is depleted, game becomes less competitive, UNDER less predictable.
            opponent_stars_out = pred.get('opponent_stars_out') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and opponent_stars_out >= 3):
                filter_counts['opponent_depleted_under'] += 1
                _record_filtered(pred, 'opponent_depleted_under', pred_edge)
                continue

            # Q4 scorer UNDER block (Session 397): UNDER + q4_scoring_ratio >= 0.35 = 34.0% HR (N=359).
            # Players who score disproportionately in Q4 → model undershoots them.
            # Q4 scoring is not captured in season/rolling averages → false UNDER signals.
            q4_ratio = pred.get('q4_scoring_ratio') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and q4_ratio >= 0.35):
                filter_counts['q4_scorer_under_block'] += 1
                _record_filtered(pred, 'q4_scorer_under_block', pred_edge)
                continue

            # Friday OVER block (Session 398): OVER on Friday = 37.5% HR at best bets (N=8),
            # 53.0% raw (N=443). Worst OVER day by far. BQ-validated across Nov-Mar.
            game_date_str_raw = pred.get('game_date', '')
            if game_date_str_raw and pred.get('recommendation') == 'OVER':
                from datetime import datetime as _dt, date as _date
                try:
                    if isinstance(game_date_str_raw, str):
                        _gd = _dt.strptime(game_date_str_raw, '%Y-%m-%d').date()
                    elif isinstance(game_date_str_raw, _date):
                        _gd = game_date_str_raw
                    else:
                        _gd = None
                    if _gd and _gd.weekday() == 4:  # 4 = Friday
                        filter_counts['friday_over_block'] += 1
                        _record_filtered(pred, 'friday_over_block', pred_edge)
                        continue
                except (ValueError, TypeError):
                    pass

            # High skew OVER block (Session 399): OVER + mean_median_gap > 2.0 = 49.1% HR.
            # Right-skewed scoring distributions cause model to predict mean while books
            # set lines at median. When mean >> median, OVER is systematically over-predicted.
            mean_median_gap = pred.get('mean_median_gap') or 0
            if (pred.get('recommendation') == 'OVER'
                    and mean_median_gap > 2.0):
                filter_counts['high_skew_over_block'] += 1
                _record_filtered(pred, 'high_skew_over_block', pred_edge)
                continue

            # High book std UNDER block (Session 377): UNDER + multi_book_line_std 1.0-1.5 = 14.8% HR (N=142).
            # When books disagree significantly on the line, UNDER predictions are unreliable.
            book_std = pred.get('multi_book_line_std') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and 1.0 <= book_std <= 1.5):
                filter_counts['high_book_std_under'] += 1
                _record_filtered(pred, 'high_book_std_under', pred_edge)
                continue

            # Flat trend UNDER — DEMOTED to observation (Session 428).
            # Original 53% HR (N=2,720) was marginally above breakeven but full-season
            # CF HR = 59.2% (N=211) within BB pipeline — blocking profitable picks.
            # 68% directional consistency is moderate but not enough to justify blocking.
            trend_slope = pred.get('trend_slope') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and -0.5 <= trend_slope <= 0.5):
                filter_counts['flat_trend_under'] += 1
                _record_filtered(pred, 'flat_trend_under_obs', pred_edge)
                # continue  # Session 428: observation mode — do NOT block

            # UNDER after streak (Session 418): 3+ consecutive unders + model UNDER = 44.7% HR (N=515)
            # Model blind spot: it chases the downtrend, but bounce-back makes these UNDER calls lose.
            # Edge guard: only suppress low-mid edge; at edge 5+ the model's conviction may override.
            prop_under_streak = pred.get('prop_under_streak') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and prop_under_streak >= 3
                    and pred_edge < 5.0):
                filter_counts['under_after_streak'] += 1
                _record_filtered(pred, 'under_after_streak', pred_edge)
                continue

            # UNDER after bad miss + bad shooting + AWAY (Session 427):
            # Mirror image of bounce_back_over's strongest tier. Player shot badly
            # (<30% FG) AND missed line (<70%) — bounce-back is coming. UNDER in
            # this context is reliably toxic: 45.1%(2024), 51.9%(2025), 33.8%(2026).
            # Combined N=457. Only applies AWAY — HOME buffers the bounce (60%+ HR).
            prev_ratio = pred.get('prev_game_ratio') or 0
            prev_fg = pred.get('prev_game_fg_pct') or 0
            is_away = not pred.get('is_home', True)
            if (pred.get('recommendation') == 'UNDER'
                    and 0 < prev_ratio < 0.70
                    and 0 < prev_fg < 0.30
                    and is_away):
                filter_counts['under_after_bad_miss'] += 1
                _record_filtered(pred, 'under_after_bad_miss', pred_edge)
                continue

            # Blowout risk UNDER block observation (Session 423): blowout_risk >= 0.40 + UNDER
            # = 16.7% HR (N=12). High blowout benching risk → players get pulled → OVER.
            # Observation mode until N >= 20 at BB level.
            blowout_risk_val = pred.get('blowout_risk') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and blowout_risk_val >= 0.40
                    and line_val >= 15):
                filter_counts['blowout_risk_under_block_obs'] += 1
                _record_filtered(pred, 'blowout_risk_under_block_obs', pred_edge)
                # Observation mode — do NOT continue/filter

            # High spread OVER — DEMOTED to observation (Session 419).
            # Historical 44.3% (N=61) full season, but CF HR = 100% (2-0, blocking winners).
            # Monitor 2 weeks — if CF HR drops below 50% at N >= 5, re-activate.
            spread_mag = pred.get('spread_magnitude') or 0
            if (pred.get('recommendation') == 'OVER'
                    and spread_mag >= 7.0):
                filter_counts['high_spread_over_would_block'] += 1
                _record_filtered(pred, 'high_spread_over_would_block', pred_edge)
                # continue  # Session 419: observation mode — do NOT block

            # Mid-line OVER — DEMOTED to observation (Session 428).
            # Original 47.9% BB HR (N=213) was toxic-window-biased. Full-season
            # CF HR = 55.8% (N=926) — above breakeven. Weekly stddev 13.6pp on
            # mean 2.8pp lift = pure noise. Not a reliable filter.
            if (pred.get('recommendation') == 'OVER'
                    and 15 <= line_val <= 25):
                filter_counts['mid_line_over_obs'] += 1
                _record_filtered(pred, 'mid_line_over_obs', pred_edge)
                # continue  # Session 428: observation mode — do NOT block

            # Monday OVER observation (Session 414): OVER on Monday = 49.0% HR (N=251).
            # Complements active friday_over_block. Reuses date parsing from Friday filter.
            if pred.get('recommendation') == 'OVER':
                _gd_raw_obs = pred.get('game_date', '')
                if _gd_raw_obs:
                    from datetime import datetime as _dt_obs, date as _date_obs
                    try:
                        if isinstance(_gd_raw_obs, str):
                            _gd_obs = _dt_obs.strptime(_gd_raw_obs, '%Y-%m-%d').date()
                        elif isinstance(_gd_raw_obs, _date_obs):
                            _gd_obs = _gd_raw_obs
                        else:
                            _gd_obs = None
                        if _gd_obs and _gd_obs.weekday() == 0:  # 0 = Monday
                            filter_counts['monday_over_obs'] += 1
                            _record_filtered(pred, 'monday_over_obs', pred_edge)
                            # Observation mode — do NOT continue/filter
                    except (ValueError, TypeError):
                        pass

            # Home OVER observation (Session 414): OVER + is_home = 49.7% HR (N=4,278).
            # Large N, consistently below breakeven.
            if (pred.get('recommendation') == 'OVER'
                    and pred.get('is_home')):
                filter_counts['home_over_obs'] += 1
                _record_filtered(pred, 'home_over_obs', pred_edge)
                # Observation mode — do NOT continue/filter

            # Session 421: Feature-based unreliable high-edge observation.
            # Wrong OVER fingerprint: edge 5+ + low minutes_load (<45).
            # Wrong UNDER fingerprint: edge 5+ + high minutes_load (>58) + flat trend.
            if pred_edge >= 5.0:
                mins_load = pred.get('minutes_load_7d') or 0
                t_slope = pred.get('trend_slope') or 0

                if (pred.get('recommendation') == 'OVER'
                        and mins_load > 0 and mins_load < 45):
                    filter_counts['unreliable_over_low_mins_obs'] += 1
                    _record_filtered(pred, 'unreliable_over_low_mins_obs', pred_edge)
                    # Observation only — do NOT block

                elif (pred.get('recommendation') == 'UNDER'
                        and mins_load > 58
                        and -0.3 <= t_slope <= 0.3):
                    filter_counts['unreliable_under_flat_trend_obs'] += 1
                    _record_filtered(pred, 'unreliable_under_flat_trend_obs', pred_edge)
                    # Observation only — do NOT block

            # --- Model profile observation (Session 384) ---
            # Log what the per-model profile store WOULD block, without
            # actually filtering. Observation mode for Phase 1 validation.
            if self._model_profile_store and self._model_profile_store.loaded:
                _profile_dims = [
                    ('direction', pred.get('recommendation', '')),
                    ('home_away', 'HOME' if pred.get('is_home', False) else 'AWAY'),
                ]
                # Add tier dimension
                if line_val > 0:
                    if line_val < 12:
                        _profile_dims.append(('tier', 'bench'))
                    elif line_val < 15:
                        _profile_dims.append(('tier', 'role'))
                    elif line_val < 25:
                        _profile_dims.append(('tier', 'starter'))
                    else:
                        _profile_dims.append(('tier', 'star'))
                # Add edge band dimension
                if pred_edge >= 7.0:
                    _profile_dims.append(('edge_band', '7_plus'))
                elif pred_edge >= 5.0:
                    _profile_dims.append(('edge_band', '5_7'))
                elif pred_edge >= 3.0:
                    _profile_dims.append(('edge_band', '3_5'))

                for _dim, _val in _profile_dims:
                    if self._model_profile_store.is_blocked(pred_system_id, _dim, _val):
                        filter_counts['model_profile_would_block'] += 1
                        logger.debug(
                            f"Profile WOULD block: {pred_system_id} "
                            f"{_dim}={_val} for {pred['player_lookup']}"
                        )
                        break  # Count once per prediction

            # --- Signal evaluation (for annotations, not selection) ---

            key = f"{pred['player_lookup']}::{pred['game_id']}"
            results = signal_results.get(key, [])
            qualifying = [r for r in results if r.qualifies]

            tags = [r.source_tag for r in qualifying]
            # Session 397: real_sc = non-base signal count. Base signals
            # (model_health, high_edge, edge_spread_optimal) fire on ~100% of picks,
            # inflating SC to 3 with zero discriminative power. real_sc measures
            # actual signal support. SC=3 with only base signals = real_sc 0.
            real_sc = len([t for t in tags if t not in BASE_SIGNALS])

            # Signal count gate: need at least base signals firing (SC >= 3)
            required_sc = self.MIN_SIGNAL_COUNT if pred_edge >= self.HIGH_EDGE_SC_THRESHOLD else self.MIN_SIGNAL_COUNT_LOW_EDGE
            if len(qualifying) < required_sc:
                filter_counts['signal_count'] += 1
                _record_filtered(pred, 'signal_count', pred_edge, len(qualifying), tags)
                continue

            # Real signal gate (Session 397 refactor): combines SC=3 OVER block
            # + signal_density into unified real_sc check.
            # - OVER with no real signals = 45.5% HR (Session 394) → block
            # - UNDER with no real signals at edge < 7 = 57.1% HR (Session 348) → block
            # - UNDER with no real signals at edge 7+ = allowed (Session 352 bypass)
            if real_sc == 0:
                if pred.get('recommendation') == 'OVER':
                    filter_counts['sc3_over_block'] += 1
                    _record_filtered(pred, 'sc3_over_block', pred_edge, len(qualifying), tags)
                    continue
                elif pred_edge < 7.0:
                    filter_counts['signal_density'] += 1
                    _record_filtered(pred, 'signal_density', pred_edge, len(qualifying), tags)
                    continue

            # Starter OVER SC floor (Session 382c, relaxed Session 393):
            # Starter OVER collapsed 90% Jan → 33.3% Feb. Need at least 1 real
            # signal beyond base. real_sc >= 1 (equivalent to old SC >= 4).
            if (pred.get('recommendation') == 'OVER'
                    and 15 <= line_val < 25
                    and real_sc < 1):
                filter_counts['starter_over_sc_floor'] += 1
                _record_filtered(pred, 'starter_over_sc_floor', pred_edge, len(qualifying), tags)
                continue

            # Confidence floor: model-specific
            if self._min_confidence > 0:
                confidence = pred.get('confidence_score') or 0
                if confidence < self._min_confidence:
                    filter_counts['confidence'] += 1
                    continue

            warning_tags: List[str] = []

            # Combo matching (for annotation)
            matched = match_combo(tags, self._registry)

            # Warning: contradictory signals
            # minutes_surge + blowout_recovery check removed (Session 318: minutes_surge removed)

            # Cross-model factors (for annotation, not scoring)
            xm_factors = self._cross_model_factors.get(key, {})
            model_agreement = xm_factors.get('model_agreement_count', 0)
            feature_diversity = xm_factors.get('feature_set_diversity', 0)
            quantile_under = xm_factors.get('quantile_consensus_under', False)
            agreeing_model_ids = xm_factors.get('agreeing_model_ids', [])

            # Consensus bonus (kept for data tracking, but not used for ranking)
            consensus_bonus = 0.0
            if xm_factors and pred.get('recommendation') == xm_factors.get('majority_direction'):
                consensus_bonus = xm_factors.get('consensus_bonus', 0)

            # Session 400: Direction-aware composite scoring.
            # OVER: edge is the primary quality discriminator (higher edge = better).
            # UNDER: edge is flat at 52-53% across all buckets. Use weighted
            # signal quality score instead, with edge as minor tiebreaker.
            under_signal_quality = None
            if pred.get('recommendation') == 'UNDER':
                real_signal_tags = [t for t in tags if t not in BASE_SIGNALS]
                under_signal_quality = sum(
                    UNDER_SIGNAL_WEIGHTS.get(t, 1.0) for t in real_signal_tags
                )
                composite_score = round(under_signal_quality + pred_edge * UNDER_EDGE_TIEBREAKER, 4)
            else:
                composite_score = round(pred_edge, 4)

            # Session 421: Player-tier edge cap observation.
            # Classify tier by line, compute what composite_score WOULD be if capped.
            # Observation only — composite_score is NOT changed for ranking.
            tier = ('star' if line_val >= 25 else
                    'starter' if line_val >= 18 else
                    'role' if line_val >= 12 else 'bench')
            cap = TIER_EDGE_CAPS.get(tier)
            if cap and pred.get('recommendation') == 'OVER' and composite_score > cap:
                capped_composite = round(cap, 4)
                tier_cap_delta = round(composite_score - capped_composite, 2)
            else:
                capped_composite = composite_score
                tier_cap_delta = 0.0

            # Qualifying subsets (Session 279)
            player_subsets = self._qualifying_subsets.get(key, [])
            subsets_for_storage = [
                {'subset_id': s['subset_id'], 'system_id': s['system_id']}
                for s in player_subsets
            ]

            scored.append({
                **pred,
                'trend_slope': pred.get('trend_slope') or 0.0,
                'spread_magnitude': pred.get('spread_magnitude') or 0.0,
                'signal_tags': tags,
                'signal_count': len(qualifying),
                'real_signal_count': real_sc,
                'signal_rescued': signal_rescued,
                'rescue_signal': rescue_signal,
                'composite_score': composite_score,
                'under_signal_quality': under_signal_quality,
                'player_tier': tier,
                'tier_edge_cap_delta': tier_cap_delta,
                'capped_composite_score': capped_composite,
                'matched_combo_id': matched.combo_id if matched else None,
                'combo_classification': matched.classification if matched else None,
                'combo_hit_rate': matched.hit_rate if matched else None,
                'warning_tags': warning_tags,
                'model_agreement_count': model_agreement,
                'feature_set_diversity': feature_diversity,
                'consensus_bonus': consensus_bonus,
                'quantile_consensus_under': quantile_under,
                'agreeing_model_ids': agreeing_model_ids,
                'qualifying_subsets': subsets_for_storage,
                'qualifying_subset_count': len(subsets_for_storage),
                'algorithm_version': ALGORITHM_VERSION,
            })

        # Log significant filter rejections
        if filter_counts['blacklist'] > 0:
            logger.info(
                f"Player blacklist: skipped {filter_counts['blacklist']} predictions "
                f"({len(self._player_blacklist)} players on blacklist)"
            )
        if filter_counts['edge_floor'] > 0:
            logger.info(f"Edge floor ({self.MIN_EDGE}): skipped {filter_counts['edge_floor']} predictions")
        if filter_counts.get('signal_rescue', 0) > 0:
            logger.info(f"Signal rescue: rescued {filter_counts['signal_rescue']} picks below edge floor via high-HR signals")
        if filter_counts['over_edge_floor'] > 0:
            logger.info(f"OVER edge floor (3.0): skipped {filter_counts['over_edge_floor']} OVER picks with edge < 3.0")
        if filter_counts['under_edge_7plus'] > 0:
            logger.info(f"UNDER edge 7+ block: skipped {filter_counts['under_edge_7plus']} predictions")
        if filter_counts['model_direction_affinity'] > 0:
            logger.info(f"Model-direction affinity: skipped {filter_counts['model_direction_affinity']} predictions")
        # away_noveg filter REMOVED Session 401 — was model staleness, not structural
        if filter_counts['under_star_away'] > 0:
            logger.info(f"UNDER Star AWAY (observation): tagged {filter_counts['under_star_away']} picks (line≥23, away)")
        if filter_counts['med_usage_under'] > 0:
            logger.info(f"Medium teammate usage UNDER block: skipped {filter_counts['med_usage_under']} predictions")
        # starter_v12_under removed Session 422b (dead filter, zero fires)
        if filter_counts['starter_over_sc_floor'] > 0:
            logger.info(f"Starter OVER SC floor: skipped {filter_counts['starter_over_sc_floor']} OVER picks (line 15-25, SC < 4)")
        # sc3_edge_floor retained for schema continuity — subsumed by edge-tiered SC (Session 388)
        if filter_counts['sc3_over_block'] > 0:
            logger.info(f"SC=3 OVER block: skipped {filter_counts['sc3_over_block']} OVER picks with SC=3 (45.5% HR, net loser)")
        if filter_counts['line_dropped_over'] > 0:
            logger.info(f"Line dropped OVER (observation): tagged {filter_counts['line_dropped_over']} OVER picks with line drop >= 2")
        if filter_counts['opponent_depleted_under'] > 0:
            logger.info(f"Opponent depleted UNDER block: skipped {filter_counts['opponent_depleted_under']} UNDER picks with 3+ opponent stars out")
        if filter_counts['q4_scorer_under_block'] > 0:
            logger.info(f"Q4 scorer UNDER block: skipped {filter_counts['q4_scorer_under_block']} UNDER picks with Q4 ratio >= 0.35 (34.0% HR)")
        if filter_counts['friday_over_block'] > 0:
            logger.info(f"Friday OVER block: skipped {filter_counts['friday_over_block']} OVER picks on Friday (37.5% HR at best bets)")
        if filter_counts['high_skew_over_block'] > 0:
            logger.info(f"High skew OVER block: skipped {filter_counts['high_skew_over_block']} OVER picks with mean-median gap > 2.0 (49.1% HR)")
        if filter_counts['flat_trend_under'] > 0:
            logger.info(f"Flat trend UNDER (observation): tagged {filter_counts['flat_trend_under']} UNDER picks with trend slope -0.5 to 0.5")
        if filter_counts['under_after_streak'] > 0:
            logger.info(f"UNDER after streak: skipped {filter_counts['under_after_streak']} UNDER picks on players with 3+ consecutive unders (44.7% HR anti-signal)")
        if filter_counts['under_after_bad_miss'] > 0:
            logger.info(f"UNDER after bad miss: skipped {filter_counts['under_after_bad_miss']} UNDER picks on AWAY players after bad miss + bad shooting (33-45% HR)")
        if filter_counts['high_spread_over_would_block'] > 0:
            logger.info(
                f"High spread OVER block: skipped "
                f"{filter_counts['high_spread_over_would_block']} OVER picks with spread >= 7 (44.3% HR)"
            )
        if filter_counts['mid_line_over_obs'] > 0:
            logger.info(
                f"Mid-line OVER (observation): tagged "
                f"{filter_counts['mid_line_over_obs']} OVER picks with line 15-25"
            )
        if filter_counts['monday_over_obs'] > 0:
            logger.info(
                f"Monday OVER (observation): tagged "
                f"{filter_counts['monday_over_obs']} OVER picks on Monday (49.0% HR)"
            )
        if filter_counts['home_over_obs'] > 0:
            logger.info(
                f"Home OVER (observation): tagged "
                f"{filter_counts['home_over_obs']} home OVER picks (49.7% HR)"
            )
        if filter_counts['signal_density'] > 0:
            logger.info(f"Signal density filter: skipped {filter_counts['signal_density']} base-only picks")
        if filter_counts['legacy_block'] > 0:
            logger.info(f"Legacy model blocklist: skipped {filter_counts['legacy_block']} predictions from {LEGACY_MODEL_BLOCKLIST}")
        if filter_counts['model_profile_would_block'] > 0:
            logger.info(
                f"Model profile (observation): WOULD block "
                f"{filter_counts['model_profile_would_block']} predictions"
            )
        if filter_counts['regime_over_floor'] > 0:
            over_floor = 3.0 + self._regime_context.get('over_edge_floor_delta', 0)
            logger.info(
                f"Regime OVER floor ({over_floor}): skipped "
                f"{filter_counts['regime_over_floor']} OVER picks "
                f"(cautious regime, yesterday HR={self._regime_context.get('yesterday_bb_hr')}%)"
            )
        if filter_counts['regime_rescue_blocked'] > 0:
            logger.info(
                f"Regime rescue blocked: skipped "
                f"{filter_counts['regime_rescue_blocked']} OVER signal-rescue picks "
                f"(cautious regime)"
            )
        if filter_counts['toxic_starter_over_would_block'] > 0:
            logger.info(
                f"Calendar regime (observation): WOULD block "
                f"{filter_counts['toxic_starter_over_would_block']} Starter OVER picks (toxic window)"
            )
        if filter_counts['toxic_star_over_would_block'] > 0:
            logger.info(
                f"Calendar regime (observation): WOULD block "
                f"{filter_counts['toxic_star_over_would_block']} Star OVER picks (toxic window)"
            )
        if filter_counts['signal_stack_2plus_obs'] > 0:
            logger.info(
                f"Signal stack 2+ (observation): tagged "
                f"{filter_counts['signal_stack_2plus_obs']} picks that would have been rescued"
            )
        if filter_counts['rescue_cap'] > 0:
            logger.info(
                f"Rescue cap: dropped {filter_counts['rescue_cap']} lowest-edge rescued picks "
                f"to keep rescue ≤ 40% of slate"
            )
        if filter_counts['unreliable_over_low_mins_obs'] > 0:
            logger.info(
                f"Unreliable OVER low mins (observation): tagged "
                f"{filter_counts['unreliable_over_low_mins_obs']} edge 5+ OVER picks with minutes_load < 45"
            )
        if filter_counts['unreliable_under_flat_trend_obs'] > 0:
            logger.info(
                f"Unreliable UNDER flat trend (observation): tagged "
                f"{filter_counts['unreliable_under_flat_trend_obs']} edge 5+ UNDER picks with high mins + flat trend"
            )

        if filter_counts['blowout_risk_under_block_obs'] > 0:
            logger.info(
                f"Blowout risk UNDER block (observation): tagged "
                f"{filter_counts['blowout_risk_under_block_obs']} UNDER picks with "
                f"blowout_risk >= 0.40 (16.7% HR N=12)"
            )

        # Session 421: Tier edge cap observation summary
        capped_count = sum(1 for p in scored if p.get('tier_edge_cap_delta', 0) > 0)
        if capped_count:
            logger.info(f"Tier edge cap (observation): {capped_count} picks would be re-ranked")

        # Session 421: Market compression observation
        compression = self._regime_context.get('market_compression', {})
        compression_ratio = compression.get('compression_ratio')
        if compression_ratio is not None:
            if compression_ratio < 0.70:
                high_edge = [p for p in scored if p.get('composite_score', 0) >= 5.0]
                logger.info(f"Market compression RED ({compression_ratio}): {len(high_edge)} edge 5+ picks")
                for p in high_edge:
                    p['compression_ratio'] = compression_ratio
                    p['compression_scaled_edge'] = round(p.get('composite_score', 0) * compression_ratio, 2)
            else:
                # Store ratio on all picks for tracking even in GREEN/YELLOW
                for p in scored:
                    p['compression_ratio'] = compression_ratio

        # --- Calendar regime observation (Session 396) ---
        # Detect regime once per aggregate() call. Log picks that WOULD be
        # blocked by calendar-aware filters without actually filtering.
        # Session 412: Now also records to filtered_picks for counterfactual grading.
        if scored:
            from datetime import date as date_type
            game_date_str = scored[0].get('game_date', '')
            try:
                if isinstance(game_date_str, str):
                    game_date_val = date_type.fromisoformat(game_date_str)
                else:
                    game_date_val = game_date_str
                regime = detect_regime(game_date_val)
                if regime.is_toxic:
                    logger.info(
                        f"Calendar regime: {regime.label} (toxic=True, "
                        f"day {regime.days_into_regime})"
                    )
                    for pick in scored:
                        pick_line = pick.get('line_value') or 0
                        pick_rec = pick.get('recommendation', '')
                        pick_edge = pick.get('composite_score', 0)
                        # Starter OVER: 40.0% HR during toxic (N=10, -48.9pp vs normal)
                        if (pick_rec == 'OVER'
                                and 15 <= pick_line < 25):
                            filter_counts['toxic_starter_over_would_block'] += 1
                            _record_filtered(pick, 'toxic_starter_over_would_block', pick_edge)
                            logger.info(
                                f"Calendar WOULD block: Starter OVER "
                                f"{pick['player_lookup']} (line={pick_line}, "
                                f"edge={pick_edge:.1f})"
                            )
                        # Star OVER: already handled by stack (66.7% HR, N=3)
                        # but tracking for completeness
                        if (pick_rec == 'OVER'
                                and pick_line >= 25):
                            filter_counts['toxic_star_over_would_block'] += 1
                            _record_filtered(pick, 'toxic_star_over_would_block', pick_edge)
                            logger.info(
                                f"Calendar WOULD block: Star OVER "
                                f"{pick['player_lookup']} (line={pick_line}, "
                                f"edge={pick_edge:.1f})"
                            )
                else:
                    logger.debug(f"Calendar regime: {regime.label} (toxic=False)")
            except (ValueError, TypeError) as e:
                logger.debug(f"Calendar regime detection skipped: {e}")

        # Ultra Bets classification (Session 326)
        from ml.signals.ultra_bets import classify_ultra_pick
        for pick_entry in scored:
            ultra_criteria = classify_ultra_pick(pick_entry)
            pick_entry['ultra_tier'] = len(ultra_criteria) > 0
            pick_entry['ultra_criteria'] = ultra_criteria

        # Session 415: Rescue cap — if rescued picks > 40% of slate, drop
        # lowest-edge rescues to filtered_picks. Rescue was designed as an
        # exception mechanism but generates 67% of slate during edge compression.
        # Minimum 1 rescue always kept.
        rescued_picks = [p for p in scored if p.get('signal_rescued')]
        non_rescued = [p for p in scored if not p.get('signal_rescued')]
        if scored and len(rescued_picks) > 0:
            max_rescue = max(1, int(len(scored) * 0.4))
            if len(rescued_picks) > max_rescue:
                # Sort rescued by edge ascending (drop lowest first)
                rescued_picks.sort(key=lambda x: x.get('edge', 0))
                to_drop = rescued_picks[:len(rescued_picks) - max_rescue]
                to_keep = rescued_picks[len(rescued_picks) - max_rescue:]
                for drop_pick in to_drop:
                    filter_counts['rescue_cap'] += 1
                    _record_filtered(
                        drop_pick, 'rescue_cap',
                        drop_pick.get('edge', 0),
                    )
                    logger.info(
                        f"Rescue cap: dropping {drop_pick['player_lookup']} "
                        f"edge={drop_pick.get('edge', 0):.1f}"
                    )
                scored = non_rescued + to_keep

        # Rank by edge descending (model confidence = primary signal)
        scored.sort(key=lambda x: x['composite_score'], reverse=True)

        # Assign ranks — natural sizing (Session 298: no artificial cap)
        for i, pick in enumerate(scored):
            pick['rank'] = i + 1

        if scored:
            logger.info(
                f"Selected {len(scored)} picks (edge range: "
                f"{scored[-1]['composite_score']:.1f}-{scored[0]['composite_score']:.1f})"
            )

        filter_summary = {
            'total_candidates': len(predictions),
            'passed_filters': len(scored),
            'rejected': filter_counts,
            'filtered_picks': filtered_picks,  # Session 393: counterfactual tracking
            'regime_context': self._regime_context,  # Session 412: daily regime state
        }

        # Session 391: Sanity warning — detect when a single filter dominates rejections.
        # This catches configuration issues like unregistered models winning per-player
        # selection then being blocked downstream (legacy_block: 47/61 = 77%).
        total_candidates = len(predictions)
        if total_candidates > 0:
            for filter_name, count in filter_counts.items():
                if count > total_candidates * 0.5:
                    logger.warning(
                        f"FILTER DOMINANCE: '{filter_name}' rejected {count}/{total_candidates} "
                        f"candidates ({100 * count / total_candidates:.0f}%). "
                        f"Investigate upstream — this filter may be masking a data/config issue."
                    )

        return scored, filter_summary

    def _weighted_signal_count(self, tags: List[str]) -> float:
        """Compute health-weighted effective signal count, capped at 3.0.

        Used for pick angle context, not for ranking.
        """
        total = 0.0
        for tag in tags:
            mult = self._get_health_multiplier(tag)
            total += mult
        return min(total, 3.0)

    def _get_health_multiplier(self, signal_tag: str) -> float:
        """Get health-based weight multiplier for a signal."""
        health = self._signal_health.get(signal_tag)
        if not health:
            return 1.0
        regime = health.get('regime', 'NORMAL')

        if regime == 'COLD':
            is_model_dep = health.get('is_model_dependent')
            if is_model_dep is None:
                is_model_dep = signal_tag in MODEL_DEPENDENT_SIGNALS
            if is_model_dep:
                return 0.0

        return HEALTH_MULTIPLIERS.get(regime, 1.0)
