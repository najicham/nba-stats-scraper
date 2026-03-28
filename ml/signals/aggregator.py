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
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ml.signals.base_signal import SignalResult
from ml.signals.combo_registry import ComboEntry, load_combo_registry, match_combo
from ml.signals.signal_health import MODEL_DEPENDENT_SIGNALS
from shared.config.calendar_regime import detect_regime
from shared.config.model_selection import get_min_confidence

logger = logging.getLogger(__name__)

# Bump whenever scoring formula, filters, or combo weights change.
# Session 452: Imported from pipeline_merger to ensure single source of truth.
# All picks (aggregator and merger) use the same version string.
from ml.signals.pipeline_merger import ALGORITHM_VERSION

# Session 441: Max picks per team per game.
# Prevents correlated exposure from same-game concentration.
# Mar 7: 3 UTA picks in same blowout all lost simultaneously.
MAX_PICKS_PER_TEAM = 2

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
    'day_of_week_over',   # Session 436: 40% BB HR (N=15), on ALL 5 Mar 7 losers — noise
    'predicted_pace_over',  # Session 436: 43% BB HR (N=21), fires on ~50% matchups — noise
    'low_line_over',        # Session 438: 20% BB HR (1-4), 50% model HR — confirmed anti-signal
    'prop_line_drop_over',  # Session 438: 57.9% BB HR (11-19) — below 60% graduation, inflating real_sc
})

# Session 436: Shadow signals fire and record to pick_signal_tags for validation
# tracking, but MUST NOT count toward real_sc. 4 brainstorming agents independently
# identified this as the #1 root cause of Mar 7 failure (1-5, all OVER).
# Shadow signals inflated real_sc on bad picks (losers avg 5.8 vs winner 3.0).
# Graduation: when a shadow signal reaches N >= 30 at BB level with HR >= 60%,
# remove from this set and add to VALIDATED signals.
SHADOW_SIGNALS = frozenset({
    'projection_consensus_over',   # 0% BB HR (0-5) — catastrophic
    'projection_consensus_under',  # Insufficient BB data
    'positive_clv_over',           # 0% BB HR (0-1)
    'positive_clv_under',          # Insufficient BB data
    'hot_form_over',               # 0% BB HR (0-2) — catastrophic
    'scoring_momentum_over',       # 0% BB HR (0-2) — catastrophic
    # usage_surge_over graduated Session 495: 68.8% HR (N=32) — meets graduation criteria (N>=30, HR>=60%)
    'career_matchup_over',         # 0% BB HR (0-1)
    'consistent_scorer_over',      # 71.4% HR (N=7) — promising but N too small
    'over_trend_over',             # Insufficient BB data
    'minutes_load_over',           # Insufficient BB data
    'bounce_back_over',            # Insufficient BB data
    'sharp_money_over',            # No data yet
    'sharp_money_under',           # No data yet
    'minutes_surge_over',          # Permanently blocked (no RotoWire minutes)
    'dvp_favorable_over',          # Insufficient BB data
    'day_of_week_under',           # 33.3% HR (N=9) — bad start
    'over_streak_reversion_under', # 51.6% HR 5-season — harmful, kept for tracking
    'star_favorite_under',         # +0.7pp = noise (Session 427)
    'starter_away_overtrend_under',  # Session 462: 48.2% HR 5-season — harmful, demoted from weights
    'mean_reversion_under',  # Session 451: decayed to 53% vs 54.3% baseline, removed from weights/rescue Session 429. Stop real_sc inflation.
    'sharp_book_lean_over',  # Session 462: 41.7% HR 5-season — harmful, demoted from weights/rescue
    'downtrend_under',       # Session 471: 16.7% HR 7d (N=6) — catastrophic, demoted from UNDER_SIGNAL_WEIGHTS
    # Session 462→466: hot_3pt_under, cold_3pt_over, line_drifted_down_under PROMOTED to active
    # (62.5%, 60.2%, 59.8% HR, 5-season cross-validated, pre-game clean)
    # Session 463: P0 simulator experiment validated signals
    'ft_anomaly_under',            # 63.3% HR (N=278) 5-season — FTA CV >= 0.5, FTA >= 5/game
    'slow_pace_under',             # 56.6% HR (N=777) 5-season — opponent pace <= 99
    'star_line_under',             # 57.6% HR (N=1,018) 5-season BUT 35.3% HR this season (N=17) — do NOT graduate
    'sharp_consensus_under',       # 69.3% HR (N=205) 5-season — line dropped + high book std
    # Session 469: Direction-specific book disagreement (shadow — accumulating BB data)
    # book_disagree_over: 79.6% HR (N=211) 5-season. Gets OVER_SIGNAL_WEIGHTS but excluded from real_sc until N>=30 BB
    # book_disagree_under: direction-specific validation. Gets UNDER_SIGNAL_WEIGHTS but excluded from real_sc
    'book_disagree_over',
    'book_disagree_under',
    'volatile_scoring_over',  # Session 487: 20% BB HR (1-4, N=5) — harmful, inflating real_sc
})

# Session 400: UNDER signal quality weights for signal-first ranking.
# UNDER edge is flat at 52-53% across all buckets — signals are the quality
# discriminator. Weights derived from backtest HR (higher HR = higher weight).
UNDER_SIGNAL_WEIGHTS: Dict[str, float] = {
    # sharp_book_lean_under removed Session 431: ZERO production fires in 2026. Market regime makes negative lean nonexistent. Was 3.0→1.0→removed.
    # mean_reversion_under removed Session 429: cross-season decay below 2026 baseline (53.0% vs 54.3%). Was 2.5→1.5→removed.
    'sharp_line_drop_under': 2.5,   # Session 422c: 87.5% HR (N=8) — already fires, now weighted
    'book_disagreement': 1.0,        # Session 434: reduced 2.5→1.0. 47.4% HR 7d (N=19), below breakeven
    'book_disagree_under': 1.5,      # Session 469: direction-specific version (shadow, accumulating data)
    'bench_under': 2.0,              # 76.9% HR
    'home_under': 1.0,           # Session 495: restored from BASE_SIGNALS. Structural signal
                                  # (UNDER + home + line>=15), no data deps, 63.9% backtest HR (N=1,386).
                                  # Session 483 demotion (48.1% 30d) was toxic Feb-March window artifact.
                                  # Current 7d HR: 69.2% (HOT). NOT in rescue_tags or RESCUE_SIGNAL_PRIORITY.
    # starter_away_overtrend_under removed Session 462: 48.2% HR 5-season cross-validated — harmful
    'extended_rest_under': 1.5,      # 61.8% HR
    'volatile_starter_under': 2.0,   # Session 427: promoted 1.5→2.0. Cross-season +11.1pp lift (best UNDER signal)
    # downtrend_under removed Session 471: 16.7% HR 7d (N=6) — catastrophic. Demoted to SHADOW_SIGNALS.
    # star_favorite_under removed Session 427: +0.7pp lift = noise, 73% HR from N=88 was single-season artifact
    # starter_under removed Session 419 (38.7% signal HR N=31, demoted to BASE_SIGNALS)
    # Session 466: Promoted from shadow — 5-season cross-validated, pre-game clean
    'hot_3pt_under': 2.5,            # 62.5% HR (N=670) — 3PT hot streak regresses, strongest structural signal
    'line_drifted_down_under': 2.0,  # 59.8% HR (N=336) — smart money nudging under
}
UNDER_EDGE_TIEBREAKER = 0.1  # Edge as minor tiebreaker for UNDER

# Session 437 P4: Rescue signal priority weights for rescue_cap sorting.
# When rescue_cap trims excess rescues, drop lowest-priority first.
# Priority based on validated BB HR — higher = more likely to keep.
# Old behavior: sorted by edge ascending (dropped HSE 100% HR while keeping
# combo_he_ms 40% HR because HSE had lower edge).
RESCUE_SIGNAL_PRIORITY: Dict[str, int] = {
    'high_scoring_environment_over': 3,  # 100% BB HR (3-0) — only OVER rescue
    'hot_3pt_under': 3,                  # Session 466: 62.5% HR 5-season
    'line_drifted_down_under': 2,        # Session 466: 59.8% HR 5-season
    # home_under removed Session 483: demoted to BASE_SIGNALS
    'combo_3way': 1,                     # UNDER only (COLD for OVER)
    'combo_he_ms': 1,                    # UNDER only
}

# Session 437 P5: Minimum 7d HR for a signal to qualify as rescue.
# Read from signal_health_daily at runtime. Signals below this threshold
# automatically lose rescue eligibility. Self-correcting — signals regain
# rescue when their HR recovers. Fail-open: if signal_health is empty,
# all signals pass (no blocking without data).
RESCUE_MIN_HR_7D = 60.0

# Session 437 P7: Validated OVER signal weights — mirrors UNDER_SIGNAL_WEIGHTS.
# OVER edge is the primary discriminator, but signal quality distinguishes
# between two OVER picks at similar edge. Weighted quality is added as a
# secondary component (edge remains dominant).
# Weights derived from validated BB/signal HR. Only validated signals get
# non-zero weight — shadow signals default to 0.0 (via SHADOW_SIGNALS check).
OVER_SIGNAL_WEIGHTS: Dict[str, float] = {
    'line_rising_over': 3.0,                # 96.6% signal HR
    'book_disagree_over': 3.0,              # Session 469: 79.6% HR (N=211, 5-season) — strongest directional signal
    'combo_3way': 2.5,                      # 95.5% season signal HR
    'fast_pace_over': 2.5,                  # 81.5% signal HR
    'high_scoring_environment_over': 2.0,   # 100% BB HR (3-0)
    'book_disagreement': 2.0,               # 93.0% signal HR (direction-neutral, kept for backward compat)
    'rest_advantage_2d': 2.0,               # Session 442: 74.0% BB HR (N=50), strongest unweighted signal
    'scoring_cold_streak_over': 1.5,        # Post-cold bounce signal
    'cold_3pt_over': 2.0,                   # Session 466: 60.2% HR (N=123) 5-season — cold from 3 bounces back
    # sharp_book_lean_over removed Session 462: 41.7% HR 5-season cross-validated — harmful
    'b2b_boost_over': 1.0,                  # Active signal
    'q4_scorer_over': 1.0,                  # Active signal
    'self_creation_over': 1.0,              # Active signal
    'sharp_line_move_over': 1.0,            # Active signal
    'combo_he_ms': 1.0,                     # 53.8% BB HR — low weight
    'usage_surge_over': 2.0,               # Session 495: graduated from shadow. 68.8% HR (N=32) — meets graduation criteria (N>=30, HR>=60%)
}
# OVER quality tiebreaker weight: how much signal quality affects ranking
# relative to edge. Edge is still dominant (1.0x), quality is secondary.
OVER_QUALITY_WEIGHT = 0.3

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

# =============================================================================
# OBSERVATION FILTER AUDIT — 2026-03-27
# =============================================================================
# ~20 observation-mode filter instances currently in this file.
# (Was 30. Removed 5: familiar_matchup_obs, b2b_under_block_obs, ft_variance_under_obs,
#  neg_pm_streak_obs, line_dropped_over_obs. Promoted 1 to active block: monday_over_obs.
#  Promoted 1 from obs to active block: hot_shooting_reversion_obs.
#  REVERTED to observation: home_over_obs (2026-03-27, BB-level CF HR = 70%, N=10 — blocking winners).)
# Promotion requires: N >= 30 BB-level picks at CF HR >= 55% for 7 consecutive days.
# Demotion/removal threshold: CF HR >= 55% (blocking too many winners).
#
# Categorized by readiness:
#
# (A) CLEARLY TOO-NEW / LOW-N — keep observing:
#   - signal_stack_2plus_obs: 50% HR at N=6 — needs data
#   - bias_regime_over_obs: accumulating data
#   - blowout_risk_under_block_obs: 16.7% HR at N=12 — low N
#   - tanking_risk_obs: new, accumulating data (season end)
#   - over_low_rsc_obs: 45.5% at N=11 — promote when N>=30
#   - hot_streak_under_obs: 44.4% at N=18 — below threshold, needs more data
#   - unreliable_over_low_mins_obs: no HR data in comments
#   - unreliable_under_flat_trend_obs: no HR data in comments
#   - model_profile_would_block: Phase 1 validation ongoing
#   - solo_game_pick_obs: 52.2% HR (N=69) — below 55% CF HR threshold for blocking
#   - thin_slate_obs: 51.2% HR — accumulating data
#   - depleted_stars_over_obs: BB 0% (N=4) — too low N for reliable signal
#   - mae_gap_obs: partially promoted for OVER (mae_gap>0.5), UNDER still obs
#
# (B) HAS ENOUGH DATA — FLAG FOR PROMOTION REVIEW (CF HR suggests can block):
#   - monday_over_obs: PROMOTED to active block 2026-03-26 (49.0% HR, N=251)
#   - home_over_obs: REVERTED to observation 2026-03-27 (BB CF HR 70%, N=10 — blocking winners)
#   - hot_shooting_reversion_obs: PROMOTED to active block 2026-03-26 (OVER CF HR ~40.8%, N=250 pred-level)
#   - player_under_suppression_obs: check date (Mar 24) passed — review BQ data
#   - under_star_away: 73.0% post-ASB HR — demoted during toxic Feb, review
#
# (C) CLEARLY HARMFUL DIRECTION — DATA SHOWS BLOCKING WINNERS, CONSIDER REMOVAL:
#   - familiar_matchup_obs: REMOVED 2026-03-26 (CF HR 54.4%, 5-season confirmed)
#   - b2b_under_block_obs: REMOVED 2026-03-26 (CF HR 54.0%, 5-season confirmed)
#   - ft_variance_under_obs: REMOVED 2026-03-26 (CF HR 56.0%, 5-season confirmed)
#   - line_dropped_over_obs: REMOVED 2026-03-26 (CF HR 60.0%, N=477)
#   - neg_pm_streak_obs: REMOVED 2026-03-26 (CF HR 64.5%, N=758 — highest of any filter)
#   - line_jumped_under_obs: CF HR 100% (5/5 winners blocked) — strong anti-signal
#   - flat_trend_under_obs: CF HR 59.2% (N=211) — blocking winners
#   - high_skew_over_block_obs: CF HR 75% (N=4) — blocking winners, low N
#   - bench_under_obs: CF HR 100% (N=2) — blocking winners, very low N
#   - opponent_under_block: CF HR 52.4% (N=21) — coin flip, demoted Session 488
#   - opponent_depleted_under: CF HR 83.3% (N=6) — blocking winners, low N
#
# NOTE: Do NOT promote/demote based on this code analysis alone.
# Run BQ CF HR queries against filter_counterfactual_daily for current N and HR.
# =============================================================================


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
        player_under_suppression: Optional[Set[str]] = None,
        model_direction_blocks: Optional[Set[tuple]] = None,
        model_direction_affinity_stats: Optional[Dict] = None,
        model_profile_store: Optional[Any] = None,
        regime_context: Optional[Dict[str, Any]] = None,
        runtime_demoted_filters: Optional[Set[str]] = None,
        mode: str = 'production',
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
        self._player_under_suppression = player_under_suppression or set()
        self._model_direction_blocks = model_direction_blocks or set()
        self._model_direction_affinity_stats = model_direction_affinity_stats
        self._model_profile_store = model_profile_store
        self._regime_context = regime_context or {}
        # Session 432: Runtime filter overrides from filter_overrides table.
        # Filters in this set still record to filtered_picks but don't block.
        self._runtime_demoted = runtime_demoted_filters or set()
        self._mode = mode

    def _health_multiplier(self, signal_tag: str) -> float:
        """Get health-aware weight multiplier for a signal.

        Session 469: COLD signals get reduced weight in composite scoring.
        Model-dependent COLD signals → 0.0x (already existed for pick angles).
        Behavioral COLD signals → 0.5x (new — prevents cold signals from
        boosting bad picks during temporary downturns).
        HOT → 1.2x, NORMAL → 1.0x.

        Fail-open: if no health data, returns 1.0 (full weight).
        """
        if not self._signal_health:
            return 1.0
        health = self._signal_health.get(signal_tag)
        if not health:
            return 1.0
        regime = health.get('regime', 'NORMAL')
        is_model_dep = health.get('is_model_dependent', False)
        if regime == 'COLD':
            return 0.0 if is_model_dep else 0.5
        elif regime == 'HOT':
            return 1.2
        return 1.0

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

        # Session 432: Log runtime-demoted filters
        if self._runtime_demoted:
            logger.info(f"Runtime-demoted filters (auto-obs): {sorted(self._runtime_demoted)}")

        # Track all filter rejections
        filter_counts = defaultdict(int)

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

        # Session 437 P8: Bias-regime detection for OVER volume gating.
        # When >70% of predictions are UNDER, the model is signaling low OVER
        # confidence. Track what WOULD be blocked (observation mode).
        # Active mode would limit OVER to edge 5+ non-rescued only.
        total_preds = len(predictions)
        under_count = sum(1 for p in predictions if p.get('recommendation') == 'UNDER')
        under_pct = under_count / total_preds if total_preds > 0 else 0.0
        bias_regime_under = under_pct > 0.70
        if bias_regime_under:
            logger.info(
                f"Bias regime: UNDER-heavy ({under_pct:.0%} UNDER, "
                f"{total_preds - under_count} OVER out of {total_preds})"
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

            # Session 451: Player UNDER suppression (observation mode).
            # Players with UNDER HR < 35% at N >= 20 across enabled models are
            # tracked. KAT 28% (N=32), Herro 12.5% (N=8). Start as observation
            # to measure impact before promoting to active filter.
            if (pred.get('recommendation') == 'UNDER'
                    and pred['player_lookup'] in self._player_under_suppression):
                filter_counts['player_under_suppression_obs'] += 1
                _record_filtered(pred, 'player_under_suppression_obs', pred_edge_early)
                # Observation mode — do NOT continue/filter

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
                # Session 466: OVER rescue restricted to HSE only.
                # March 2026: 18 rescued OVER at avg edge 3.9, combo_he_ms 40% HR,
                # signal_stack 33% HR, volatile_scoring 0% HR. Only HSE works (3-0).
                # Session 494: Removed combo_3way/combo_he_ms from UNDER rescue_tags.
                # Both signals have OVER-only gates (combo_3way.py:46, combo_he_ms.py:39)
                # — they return no-qualify for UNDER predictions, so they were dead code
                # here. No UNDER picks were ever rescued by them.
                if pred.get('recommendation') == 'OVER':
                    rescue_tags = {
                        'high_scoring_environment_over',  # 100% BB HR (3-0), only validated OVER rescue
                    }
                else:
                    rescue_tags = {
                        # home_under removed Session 483: demoted to BASE_SIGNALS (48.1% HR 30d)
                        'hot_3pt_under',          # Session 466: 62.5% HR 5-season, promoted
                        'line_drifted_down_under', # Session 466: 59.8% HR 5-season, promoted
                    }

                # Session 437 P5: Dynamic rescue health gate.
                # Signals with 7d HR < RESCUE_MIN_HR_7D lose rescue eligibility.
                # Self-correcting — no manual intervention during cold/hot streaks.
                if self._signal_health:
                    unhealthy_rescue = set()
                    for rtag in list(rescue_tags):
                        health = self._signal_health.get(rtag, {})
                        hr_7d = health.get('hr_7d')
                        if hr_7d is not None and hr_7d < RESCUE_MIN_HR_7D:
                            unhealthy_rescue.add(rtag)
                            logger.debug(
                                f"Rescue health gate: {rtag} blocked "
                                f"(7d HR={hr_7d:.1f}% < {RESCUE_MIN_HR_7D}%)"
                            )
                    if unhealthy_rescue:
                        rescue_tags -= unhealthy_rescue
                        filter_counts.setdefault('rescue_health_gate', 0)
                        filter_counts['rescue_health_gate'] += len(unhealthy_rescue)

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
                # BB HR < 50%) or TIGHT market (vegas_mae < 4.5), disable OVER rescue.
                # Session 483: PROMOTED TO ACTIVE. Observation mode let March 8 happen:
                # 3 rescued OVER picks at edge 3.1-3.2 all lost in a TIGHT market.
                # Rescue is only valid when the market is soft enough to exploit.
                if (signal_rescued
                        and self._regime_context.get('disable_over_rescue')
                        and pred.get('recommendation') == 'OVER'):
                    filter_counts['regime_rescue_blocked'] += 1
                    _record_filtered(pred, 'regime_rescue_blocked', pred_edge)
                    continue

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

            # Session 435: BB OVER edge 3-4 = 33.3% HR (4-12). 4.0+ = 68.3%.
            # Session 436: Apply floor to rescued OVER too — rescued OVER = 50% HR
            # vs non-rescued 66.7%. combo_he_ms rescue at edge <4 = 40% HR (2-3).
            # Exempt HSE rescue (3-0, 100% HR) — HSE identifies genuine scoring env.
            # Session 468: Raised from 4.0 to 5.0. 5-season discovery analysis (79K
            # predictions) shows OVER at edge 3-5 is net-negative in 4/5 seasons:
            #   2021-22: 43%, 2022-23: 45%, 2023-24: 49%, 2024-25: 50%.
            # Only 2025-26 (58%) was profitable at edge 3-5 — single-season artifact.
            # UNDER at edge 3-5 is 56.7% consistently. OVER needs edge 5+ to be viable.
            # Session 475: Raised from 5.0 to 6.0 based on Mar 7+ collapse (28.6% HR).
            # Session 476: Lowered back to 5.0. 9-agent analysis (Mar 21 2026) found:
            #   - The Mar 7+ collapse was N=3 per bucket (statistically meaningless)
            #   - Season-long edge 5-6 HR: 63.0% (N=27) — viable tier
            #   - The 6.0 floor was blocking everything since enabled fleet avg_abs_diff
            #     peaked at 1.53 (LGBM), producing zero edge-6+ OVER candidates
            #   - v9_low_vegas (enabled Session 476) produces edge 5-6 OVER picks
            # Session 483: regime_delta now ACTIVELY raises the floor.
            # Previously observation-only — it tracked WOULD-block but never blocked.
            # delta is +1.0 when cautious (yesterday HR < 50%) or TIGHT market
            # (vegas_mae_7d < 4.5). Result: floor rises 5.0 → 6.0 in those regimes.
            over_floor = 5.0 + self._regime_context.get('over_edge_floor_delta', 0)
            hse_rescued = signal_rescued and rescue_signal == 'high_scoring_environment_over'
            if (pred.get('recommendation') == 'OVER'
                    and pred_edge < over_floor
                    and not hse_rescued):
                if over_floor > 5.0:
                    filter_counts['regime_over_floor'] += 1
                    _record_filtered(pred, 'regime_over_floor', pred_edge)
                else:
                    filter_counts['over_edge_floor'] += 1
                    _record_filtered(pred, 'over_edge_floor', pred_edge)
                continue

            # Session 437 P8: Bias-regime OVER volume gate (observation mode).
            # When >70% of predictions are UNDER and this is a rescued OVER
            # with edge < 5.0, track what would be blocked. Active mode would
            # limit OVER to edge 5+ non-rescued only during UNDER-heavy regimes.
            if (bias_regime_under
                    and pred.get('recommendation') == 'OVER'
                    and (signal_rescued or pred_edge < 5.0)):
                filter_counts['bias_regime_over_obs'] += 1
                _record_filtered(pred, 'bias_regime_over_obs', pred_edge)

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
                    if 'model_direction_affinity' not in self._runtime_demoted:
                        continue

            # AWAY block REMOVED (Session 401):
            # Original (Session 347/365): v12_noveg 43.8% AWAY, v9 48.1% AWAY
            # Root cause was model staleness (train_1102 vintage = 44.1% AWAY),
            # NOT structural. Newer models (Jan+ training) show zero HOME/AWAY gap:
            # 61.0% AWAY vs 63.3% HOME. March AWAY noveg = 60.0% (N=45).
            # Filter was #1 blocker (9 rejections in 2 days), blocking winning picks.

            # familiar_matchup_obs REMOVED 2026-03-26: 5-season CF HR = 54.4% (N=large),
            # confirmed blocking winners across all seasons. Filter is conceptually wrong.

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

            # Medium teammate usage UNDER — ACTIVE filter (Session 488 demote REVERTED).
            # CF HR = 45.9% (N=37) — blocking losers (54% of blocked picks lose).
            # Session 488 misread CF HR: 45.9% < 55% threshold means filter is doing its job.
            # Session 355 finding (32.0% HR, N=25) validates direction — medium teammates
            # available means line-setter already priced in volume for supporting cast.
            teammate_usage = pred.get('teammate_usage_available') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and 15 <= teammate_usage <= 30):
                filter_counts['med_usage_under'] += 1
                _record_filtered(pred, 'med_usage_under', pred_edge)
                if 'med_usage_under' not in self._runtime_demoted:
                    continue

            # b2b_under_block_obs REMOVED 2026-03-26: 5-season CF HR = 54.0% — blocking winners.
            # Filter is conceptually wrong; B2B fatigue doesn't hurt UNDER picks.

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

            # Line dropped UNDER — ACTIVE filter (Session 488 demote REVERTED).
            # CF HR = 37.5% (N=8) — blocking losers (62.5% of blocked picks lose).
            # Session 488 misread CF HR: 37.5% is well below 55% threshold — filter correct.
            # Line drops on UNDER picks suggest market moved away from UNDER thesis.
            if (prop_line_delta is not None
                    and prop_line_delta <= -2.0
                    and pred.get('recommendation') == 'UNDER'):
                filter_counts['line_dropped_under'] += 1
                _record_filtered(pred, 'line_dropped_under', pred_edge)
                if 'line_dropped_under' not in self._runtime_demoted:
                    continue

            # line_dropped_over_obs REMOVED 2026-03-26: CF HR = 60.0% (N=477) — blocking winners.
            # Market line drops already incorporated by model; filter direction was wrong.

            # Session 451: Line anomaly extreme drop — ACTIVE filter.
            # When a player's line drops >= 40% OR >= 6 points from their previous
            # game line, the edge is manufactured from information asymmetry (injury,
            # restriction, etc.) that the model doesn't see. Mar 8: Derrick White
            # line 16.5 → 8.5 (51% drop) created artificial ULTRA edge 7.4 — lost.
            # Safety net filter — rare trigger, clear mechanism.
            if (prop_line_delta is not None
                    and line_val > 0
                    and pred.get('recommendation') == 'OVER'):
                prev_line = line_val - prop_line_delta  # prop_line_delta = current - prev
                if prev_line > 0:
                    drop_pct = (prev_line - line_val) / prev_line
                    drop_abs = prev_line - line_val
                    if drop_pct >= 0.40 or drop_abs >= 6.0:
                        filter_counts['line_anomaly_extreme_drop'] += 1
                        _record_filtered(pred, 'line_anomaly_extreme_drop', pred_edge)
                        continue

            # neg_pm_streak_obs REMOVED 2026-03-26: CF HR = 64.5% (N=758) — highest CF HR of
            # any filter. Blocking the most profitable UNDER picks. Filter is clearly harmful.

            # Opponent team UNDER — DEMOTED to observation (Session 488).
            # CF HR = 52.4% (N=21) — coin flip. Session 372 baseline (MIN/MEM/MIL/IND
            # at 43-49% UNDER HR) was N>=190 from 2023-24; rosters have changed.
            # 2025-26 data shows 52.4% CF HR — not sufficient to block picks.
            if (pred.get('recommendation') == 'UNDER'
                    and pred.get('opponent_team_abbr', '') in UNDER_TOXIC_OPPONENTS):
                filter_counts['opponent_under_block'] += 1
                _record_filtered(pred, 'opponent_under_block', pred_edge)
                # Observation mode — do NOT block

            # Opponent depleted UNDER block (Session 374b): UNDER + 3+ opponent stars out = 44.4% HR (N=207).
            # When opponent is depleted, game becomes less competitive, UNDER less predictable.
            # Session 476: Demoted to observation. 9-agent analysis found CF HR = 83.3% (N=6)
            # — blocking winners in recent data. Original 44.4% HR (N=207) may not hold in
            # late-season tight market where depleted rosters create scoring variance.
            opponent_stars_out = pred.get('opponent_stars_out') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and opponent_stars_out >= 3):
                filter_counts['opponent_depleted_under'] += 1
                _record_filtered(pred, 'opponent_depleted_under', pred_edge)
                # continue  # Session 476: observation mode — CF HR 83.3% (N=6) blocking winners

            # Q4 scorer UNDER block (Session 397): UNDER + q4_scoring_ratio >= 0.35 = 34.0% HR (N=359).
            # Players who score disproportionately in Q4 → model undershoots them.
            # Q4 scoring is not captured in season/rolling averages → false UNDER signals.
            q4_ratio = pred.get('q4_scoring_ratio') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and q4_ratio >= 0.35):
                filter_counts['q4_scorer_under_block'] += 1
                _record_filtered(pred, 'q4_scorer_under_block', pred_edge)
                if 'q4_scorer_under_block' not in self._runtime_demoted:
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
                        if 'friday_over_block' not in self._runtime_demoted:
                            continue
                except (ValueError, TypeError):
                    pass

            # High skew OVER block — DEMOTED to observation (Session 470).
            # Original thesis (Session 399): OVER + mean_median_gap > 2.0 = 49.1% HR.
            # In-season CF HR: 75% (3/4 graded) — blocking winners. Thesis too thin
            # (49.1% vs 50%) to justify active blocking. Track counterfactual only.
            mean_median_gap = pred.get('mean_median_gap') or 0
            if (pred.get('recommendation') == 'OVER'
                    and mean_median_gap > 2.0):
                filter_counts['high_skew_over_block'] += 1
                _record_filtered(pred, 'high_skew_over_block_obs', pred_edge)

            # High book std UNDER block (Session 377): UNDER + multi_book_line_std 1.0-1.5 = 14.8% HR (N=142).
            # When books disagree significantly on the line, UNDER predictions are unreliable.
            book_std = pred.get('multi_book_line_std') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and 1.0 <= book_std <= 1.5):
                filter_counts['high_book_std_under'] += 1
                _record_filtered(pred, 'high_book_std_under', pred_edge)
                if 'high_book_std_under' not in self._runtime_demoted:
                    continue

            # flat_trend_under_obs: REMOVED 2026-03-26 Session 494.
            # CF HR 59.2% (N=211) — was blocking profitable UNDER picks. Removed.

            # UNDER after streak — ACTIVE filter (Session 488 demote REVERTED).
            # CF HR = 45.5% (N=11) — blocking losers (54.5% of blocked picks lose).
            # Session 418 N=515 prediction-level finding (44.7% HR) validates direction.
            # Session 488 misread CF HR: 45.5% < 55% threshold = filter correctly blocking.
            prop_under_streak = pred.get('prop_under_streak') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and prop_under_streak >= 3
                    and pred_edge < 5.0):
                filter_counts['under_after_streak'] += 1
                _record_filtered(pred, 'under_after_streak', pred_edge)
                if 'under_after_streak' not in self._runtime_demoted:
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
                if 'under_after_bad_miss' not in self._runtime_demoted:
                    continue

            # Blowout risk UNDER block (Session 423→434→436): blowout_risk >= 0.40 + UNDER
            # Session 434: Promoted to active. Session 436: Demoted back to observation.
            # Raw prediction HR = 57.9% (N=216) — filter blocks profitable UNDER picks.
            # Threshold 0.40 too broad (captures ~70% of players). Need more data.
            blowout_risk_val = pred.get('blowout_risk') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and blowout_risk_val >= 0.40
                    and line_val >= 15):
                filter_counts['blowout_risk_under_block_obs'] += 1
                _record_filtered(pred, 'blowout_risk_under_block_obs', pred_edge)

            # High spread OVER — DEMOTED to observation (Session 419).
            # Session 436: Promoted back to active blocking.
            # Spread >= 7 OVER = 47% HR (N=32) vs 77% in competitive games.
            # 30pp differential validated over full season. Flagged 4 of 5 Mar 7 losses.
            spread_mag = pred.get('spread_magnitude') or 0
            if (pred.get('recommendation') == 'OVER'
                    and spread_mag >= 7.0):
                filter_counts['high_spread_over_would_block'] += 1
                _record_filtered(pred, 'high_spread_over_would_block', pred_edge)
                if 'high_spread_over_would_block' not in self._runtime_demoted:
                    continue

            # Tanking risk observation (Session 474): season-end games where a team tanks
            # for draft position. Heavy spreads (>= 10) create blowout conditions where the
            # losing team's stars play full minutes (coach plays them regardless) while
            # winners may sit starters early → UNDER picks in lopsided UNDER contexts fail.
            # Using spread_magnitude >= 10 as proxy (top ~15% most lopsided games).
            # Observation only — accumulating data through season end to validate direction.
            if (spread_mag >= 10.0
                    and pred.get('recommendation') == 'UNDER'):
                filter_counts['tanking_risk_obs'] += 1
                _record_filtered(pred, 'tanking_risk_obs', pred_edge)
                # continue  # Session 474: observation only — no blocking until validated

            # Mid-line OVER — DEMOTED to observation (Session 428).
            # Original 47.9% BB HR (N=213) was toxic-window-biased. Full-season
            # CF HR = 55.8% (N=926) — above breakeven. Weekly stddev 13.6pp on
            # mean 2.8pp lift = pure noise. Not a reliable filter.
            if (pred.get('recommendation') == 'OVER'
                    and 15 <= line_val <= 25):
                filter_counts['mid_line_over_obs'] += 1
                _record_filtered(pred, 'mid_line_over_obs', pred_edge)
                # continue  # Session 428: observation mode — do NOT block

            # Monday OVER block — PROMOTED to active 2026-03-26: 49.0% HR (N=251), large N,
            # consistently below breakeven across 4+ seasons. Mirrors friday_over_block.
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
                            if 'monday_over_obs' not in self._runtime_demoted:
                                continue
                    except (ValueError, TypeError):
                        pass

            # Home OVER — REVERTED to observation 2026-03-27.
            # Raw prediction CF HR was 49.7% (N=4,278) — below breakeven.
            # But BB-level CF HR = 70% (N=10) — blocking winners at the BB-qualified level.
            # The raw-prediction dataset includes many bad picks; BB pipeline already filters
            # to high-quality. Applying a raw-prediction filter on BB-qualified picks is too broad.
            # Keep observing until BB-level N >= 30 with CF HR consistently <= 45%.
            if (pred.get('recommendation') == 'OVER'
                    and pred.get('is_home')):
                filter_counts['home_over_obs'] += 1
                _record_filtered(pred, 'home_over_obs', pred_edge)
                # continue  # OBSERVATION MODE — do not block

            # Session 438 P10 → Session 440: Prediction sanity check (ACTIVE).
            # Block predictions where predicted_points > 2x season avg on
            # bench/role players (line < 18). Model-level HR = 40.9% (N=88)
            # for pred > 2x avg — strongly below breakeven. Catches model
            # artifacts from sparse training data on low-volume players.
            # Mar 7: would have blocked Konchar (2.77x avg, LOSS).
            predicted_pts = pred.get('predicted_points') or 0
            if (predicted_pts > 0
                    and season_avg > 0
                    and line_val < 18
                    and predicted_pts > 2 * season_avg):
                filter_counts['prediction_sanity'] += 1
                _record_filtered(pred, 'prediction_sanity', pred_edge)
                continue

            # Session 439: Depleted roster OVER observation.
            # When 3+ star teammates are OUT, BB OVER = 0% HR (N=4), model-level = 48.2% (N=137).
            # Depleted rosters have worse overall offense — volume boost doesn't materialize
            # for remaining players. Bench/role players on skeleton crews score well below line.
            # At stars_out=2: BB OVER = 50% (N=12), model = 49.2% (N=708) — borderline.
            # Starting in observation to accumulate data before promoting.
            own_stars_out = pred.get('star_teammates_out') or 0
            if (pred.get('recommendation') == 'OVER'
                    and own_stars_out >= 3):
                filter_counts['depleted_stars_over_obs'] += 1
                _record_filtered(pred, 'depleted_stars_over_obs', pred_edge)
                # Observation mode — do NOT continue/filter

            # Session 441→494: Hot shooting reversion OVER block — PROMOTED to active.
            # After 70%+ FG games (with real minutes), OVER HR = 40.8% (CF HR, N=250 pred-level).
            # Efficiency mean-reverts at the extreme — 60-69% shows NO signal.
            # Uses prev_game_fg_pct + prev_game_minutes as proxy for FGA >= 12.
            # Promoted Session 494: prediction-level N=250, CF HR ~40% well below 55% threshold.
            prev_fg_pct = pred.get('prev_game_fg_pct') or 0
            prev_mins = pred.get('prev_game_minutes') or 0
            if (pred.get('recommendation') == 'OVER'
                    and prev_fg_pct >= 0.70
                    and prev_mins >= 20):
                filter_counts['hot_shooting_reversion_obs'] += 1
                _record_filtered(pred, 'hot_shooting_reversion_obs', pred_edge)
                if 'hot_shooting_reversion_obs' not in self._runtime_demoted:
                    continue

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
            # Session 397: real_sc = non-base, non-shadow signal count.
            # Base signals fire on ~100% of picks, inflating SC with zero value.
            # Session 436: Shadow signals are unvalidated and inflate real_sc on
            # bad picks (Mar 7: losers avg 5.8 vs winner 3.0). Exclude both.
            real_sc = len([t for t in tags
                          if t not in BASE_SIGNALS and t not in SHADOW_SIGNALS])

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
            #   BUT Session 475 fix: bypass requires predicted_points >= 55% of line.
            #   Root cause: line-update re-runs cause model to over-anchor to the new
            #   line value (e.g., line 17.5 → predicted 8.8, edge 8.7). These are model
            #   artifacts — no real signals, prediction < 55% of line = impossible without
            #   injury context. This filter is named zero_signal_extreme_underprediction.
            if real_sc == 0:
                if pred.get('recommendation') == 'OVER':
                    if pred_edge >= 7.0:
                        # Session 483: Edge 7+ OVER bypass — mirrors existing UNDER bypass.
                        # Edge 7+ OVER = 78.8% HR (N=33 this season). High conviction
                        # without explicit signal context is still profitable at this edge.
                        # UNDER already had this bypass (Session 352); OVER had no reason
                        # to be asymmetrically blocked.
                        pass
                    else:
                        filter_counts['sc3_over_block'] += 1
                        _record_filtered(pred, 'sc3_over_block', pred_edge, len(qualifying), tags)
                        continue
                elif pred_edge < 7.0:
                    filter_counts['signal_density'] += 1
                    _record_filtered(pred, 'signal_density', pred_edge, len(qualifying), tags)
                    # ACTIVE filter (Session 488 demote REVERTED): CF HR = 40.0% (N=35) —
                    # blocking losers (60% of blocked picks lose). Well below 55% threshold.
                    # UNDER with real_sc=0 at edge 3-7 lacks signal support and is correctly blocked.
                    continue
                else:
                    # Session 352 bypass: UNDER + edge >= 7 + real_sc=0 is allowed,
                    # but only if the model's prediction is >= 55% of the line.
                    # A predicted/line ratio < 0.55 with zero real signals indicates
                    # a model artifact from mid-day line movement, not genuine conviction.
                    predicted_pts = float(pred.get('predicted_points') or 0)
                    if line_val > 0 and predicted_pts > 0 and (predicted_pts / line_val) < 0.55:
                        filter_counts['zero_signal_extreme_underprediction'] += 1
                        _record_filtered(pred, 'zero_signal_extreme_underprediction',
                                         pred_edge, len(qualifying), tags)
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

            # Session 400/437: Direction-aware composite scoring.
            # UNDER: edge is flat at 52-53% across all buckets. Use weighted
            # signal quality score instead, with edge as minor tiebreaker.
            # OVER: edge is the primary discriminator, but signal quality (P7)
            # helps distinguish picks at similar edge — prevents high-edge picks
            # with only shadow/base signals from outranking signal-rich picks.
            under_signal_quality = None
            over_signal_quality = None
            if pred.get('recommendation') == 'UNDER':
                real_signal_tags = [t for t in tags if t not in BASE_SIGNALS]
                # Session 469: Health-aware signal weighting. COLD signals get
                # reduced weight (0.5x behavioral, 0.0x model-dependent) so that
                # temporarily struggling signals don't boost bad UNDER picks.
                under_signal_quality = sum(
                    UNDER_SIGNAL_WEIGHTS.get(t, 1.0) * self._health_multiplier(t)
                    for t in real_signal_tags
                )
                composite_score = round(under_signal_quality + pred_edge * UNDER_EDGE_TIEBREAKER, 4)
            else:
                # Session 437 P7: Weighted OVER quality scoring.
                # Only validated (non-base, non-shadow) signals contribute.
                # Shadow signals default to 0.0 weight (excluded from real tags).
                over_real_tags = [t for t in tags
                                 if t not in BASE_SIGNALS and t not in SHADOW_SIGNALS]
                # Session 469: Health-aware OVER signal weighting.
                over_signal_quality = sum(
                    OVER_SIGNAL_WEIGHTS.get(t, 0.5) * self._health_multiplier(t)
                    for t in over_real_tags
                )
                composite_score = round(
                    pred_edge + over_signal_quality * OVER_QUALITY_WEIGHT, 4
                )

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

            # Session 438 P9: Volatility-adjusted edge z-score (observation).
            # Normalizes edge by player scoring variance. A 4-point edge
            # on a volatile player (std=8, z=0.5) is less meaningful than
            # on a consistent player (std=3, z=1.33).
            pts_std = pred.get('points_std_last_10') or 0
            edge_zscore = round(pred_edge / max(pts_std, 1.0), 4)

            # Qualifying subsets (Session 279)
            player_subsets = self._qualifying_subsets.get(key, [])
            subsets_for_storage = [
                {'subset_id': s['subset_id'], 'system_id': s['system_id']}
                for s in player_subsets
            ]

            # Session 442 O1: OVER low real_signal_count observation.
            # OVER at rsc=3 = 45.5% HR (N=11) vs rsc=4 = 65.4% (N=26).
            # Observation mode — accumulate BB-level data, promote at N >= 30.
            if (pred.get('recommendation') == 'OVER'
                    and real_sc < 4
                    and real_sc > 0):  # rsc=0 already blocked by sc3_over_block
                filter_counts['over_low_rsc_obs'] += 1
                _record_filtered(pred, 'over_low_rsc_obs', pred_edge, len(qualifying), tags)
                # Observation only — does NOT block

            # Session 442 O2 → Session 483: MAE gap filter — PARTIALLY PROMOTED TO ACTIVE.
            # When model MAE exceeds Vegas MAE, BB HR craters to 40-50%.
            # When model beats Vegas (negative gap), HR is 80-100%.
            # Session 483: When gap > 0.5 (model badly losing to books), block OVER picks.
            # UNDER stays observation-only — UNDER is stable at 57-58% regardless of regime.
            mae_gap = self._regime_context.get('mae_gap_7d')
            if mae_gap is not None and mae_gap > 0.15:
                filter_counts['mae_gap_obs'] += 1
                _record_filtered(pred, 'mae_gap_obs', pred_edge, len(qualifying), tags)
                if mae_gap > 0.5 and pred.get('recommendation') == 'OVER':
                    filter_counts['mae_gap_over_block'] += 1
                    _record_filtered(pred, 'mae_gap_over_block', pred_edge, len(qualifying), tags)
                    continue

            # Session 442 O3: Thin slate observation.
            # 4-6 game slates = 51.2% HR with 76.7% OVER-heavy mix.
            # 7-9 game slates = 72.0% HR. Small slates force OVER-heavy picks.
            num_games = self._regime_context.get('num_games_on_slate')
            if num_games is not None and 4 <= num_games <= 6:
                filter_counts['thin_slate_obs'] += 1
                _record_filtered(pred, 'thin_slate_obs', pred_edge, len(qualifying), tags)
                # Observation only — does NOT block

            # Session 442 O4: Hot streak UNDER observation.
            # UNDER when player went over in 4+ of last 5 = 44.4% HR (N=18).
            # UNDER when player went over in 0-2 of last 5 = 81-87% HR.
            # Uses feature 55 (over_rate_last_10, 0-1 scale). >= 0.7 = hot streak.
            if (pred.get('recommendation') == 'UNDER'
                    and (pred.get('over_rate_last_10') or 0) >= 0.7):
                filter_counts['hot_streak_under_obs'] += 1
                _record_filtered(pred, 'hot_streak_under_obs', pred_edge, len(qualifying), tags)
                # Observation only — does NOT block

            # Session 452: UNDER low real_sc — PROMOTED to active filter.
            # Mar 8: 6/7 UNDER losses had real_sc 1-2. Base signals inflate
            # raw signal_count to pass SC >= 3 gate, but real_sc == 1 means
            # minimal signal quality. Blocks UNDER picks with real_sc < 2
            # at edge < 7 (high-edge UNDER bypasses).
            if (pred.get('recommendation') == 'UNDER'
                    and real_sc < 2
                    and real_sc > 0
                    and pred_edge < 7.0):
                filter_counts['under_low_rsc'] += 1
                _record_filtered(pred, 'under_low_rsc', pred_edge, len(qualifying), tags)
                if 'under_low_rsc' not in self._runtime_demoted:
                    continue

            # ft_variance_under_obs REMOVED 2026-03-26: 5-season CF HR = 56.0% — blocking winners.
            # Original Session 452 promotion based on single-season data; 5-season confirms wrong direction.

            # Session 462→463: Cold FG UNDER — ACTIVE filter. Block UNDER when
            # FG% last_3 is 10%+ below season avg. Cold shooter bounces back.
            # 5-season cross-validated: blocked picks = 38.5% HR (N=457).
            _fg_last_3 = pred.get('fg_pct_last_3')
            _fg_season = pred.get('fg_pct_season')
            if (pred.get('recommendation') == 'UNDER'
                    and _fg_last_3 is not None and _fg_season is not None
                    and _fg_season - _fg_last_3 >= 0.10):
                filter_counts['cold_fg_under'] += 1
                _record_filtered(pred, 'cold_fg_under', pred_edge, len(qualifying), tags)
                if 'cold_fg_under' not in self._runtime_demoted:
                    continue

            # Session 462→463: Cold 3PT UNDER — ACTIVE filter. Block UNDER when
            # 3PT% last_3 is 10%+ below season avg. Same bounce-back mechanism.
            # 5-season cross-validated: blocked picks = 45.6% HR (N=735).
            _tpt_last_3 = pred.get('three_pct_last_3')
            _tpt_season = pred.get('three_pct_season')
            if (pred.get('recommendation') == 'UNDER'
                    and _tpt_last_3 is not None and _tpt_season is not None
                    and _tpt_season - _tpt_last_3 >= 0.10):
                filter_counts['cold_3pt_under'] += 1
                _record_filtered(pred, 'cold_3pt_under', pred_edge, len(qualifying), tags)
                if 'cold_3pt_under' not in self._runtime_demoted:
                    continue

            # Session 462→469: OVER + line rose heavy — PROMOTED to active.
            # BettingPros line rose >= 1.0. Fighting the market = losing.
            # 5-season cross-validated: blocked picks = 38.9% HR (N=54).
            # Was observation since Session 462. Promoted after 5-season confirmation.
            bp_move = pred.get('bp_line_movement')
            if (pred.get('recommendation') == 'OVER'
                    and bp_move is not None
                    and bp_move >= 1.0):
                filter_counts['over_line_rose_heavy'] += 1
                _record_filtered(pred, 'over_line_rose_heavy', pred_edge, len(qualifying), tags)
                if 'over_line_rose_heavy' not in self._runtime_demoted:
                    continue

            # Session 463: FTA anomaly OVER block — ACTIVE filter. Block OVER when
            # FTA is volatile (CV >= 0.5) and player averages 5+ FTA/game.
            # High FTA variance means scoring was inflated by unsustainable FT volume.
            # 5-season cross-validated: blocked picks = 37.5% HR (N=56) at CV>=0.6.
            fta_avg = pred.get('fta_avg_last_10', 0) or 0
            fta_cv = pred.get('fta_cv_last_10', 0) or 0
            if (pred.get('recommendation') == 'OVER'
                    and fta_avg >= 5.0
                    and fta_cv >= 0.6):
                filter_counts['ft_anomaly_over_block'] += 1
                _record_filtered(pred, 'ft_anomaly_over_block', pred_edge, len(qualifying), tags)
                if 'ft_anomaly_over_block' not in self._runtime_demoted:
                    continue

            # Session 468: Hot shooting OVER block — ACTIVE filter. Block OVER when
            # FG% or 3PT% last_3 is significantly above season average. Hot shooting
            # is mean-reverting — player regresses, making OVER a loser.
            # 5-season discovery analysis (79K predictions):
            #   FG% hot (diff >= 10%): 24.1% OVER HR (N=58)
            #   3PT% hot (diff >= 15%): 28.6% OVER HR (N=56)
            # Combined check: FG diff >= 10% OR 3PT diff >= 15%.
            if pred.get('recommendation') == 'OVER':
                _fg_hot = (
                    _fg_last_3 is not None
                    and _fg_season is not None
                    and _fg_last_3 - _fg_season >= 0.10
                )
                _tpt_hot = (
                    _tpt_last_3 is not None
                    and _tpt_season is not None
                    and _tpt_last_3 - _tpt_season >= 0.15
                )
                if _fg_hot or _tpt_hot:
                    filter_counts['hot_shooting_over_block'] += 1
                    _record_filtered(pred, 'hot_shooting_over_block', pred_edge, len(qualifying), tags)
                    if 'hot_shooting_over_block' not in self._runtime_demoted:
                        continue

            # Session 463: Counter-market UNDER block — ACTIVE filter. Block UNDER when
            # line rose >= 0.5 AND cross-book std >= 1.0. Model fights both market
            # direction and smart money — consistently loses.
            # 5-season cross-validated: blocked picks = 43.2% HR (N=447).
            _book_std = pred.get('multi_book_line_std') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and bp_move is not None
                    and bp_move >= 0.5
                    and _book_std >= 1.0):
                filter_counts['counter_market_under'] += 1
                _record_filtered(pred, 'counter_market_under', pred_edge, len(qualifying), tags)
                if 'counter_market_under' not in self._runtime_demoted:
                    continue

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
                'over_signal_quality': over_signal_quality,
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
                'edge_zscore': edge_zscore,
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
            logger.info(f"OVER edge floor (5.0 base, regime-adaptive): skipped {filter_counts['over_edge_floor']} OVER picks below OVER edge floor")
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
        if filter_counts['line_dropped_under'] > 0:
            logger.info(f"Line dropped UNDER block: skipped {filter_counts['line_dropped_under']} UNDER picks with line drop >= 2 (37.5% CF HR)")
        if filter_counts['opponent_depleted_under'] > 0:
            logger.info(f"Opponent depleted UNDER block: skipped {filter_counts['opponent_depleted_under']} UNDER picks with 3+ opponent stars out")
        if filter_counts['q4_scorer_under_block'] > 0:
            logger.info(f"Q4 scorer UNDER block: skipped {filter_counts['q4_scorer_under_block']} UNDER picks with Q4 ratio >= 0.35 (34.0% HR)")
        if filter_counts['friday_over_block'] > 0:
            logger.info(f"Friday OVER block: skipped {filter_counts['friday_over_block']} OVER picks on Friday (37.5% HR at best bets)")
        if filter_counts['high_skew_over_block'] > 0:
            logger.info(f"High skew OVER (observation): tagged {filter_counts['high_skew_over_block']} OVER picks with mean-median gap > 2.0")
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
                f"Monday OVER block (ACTIVE 2026-03-26): blocked "
                f"{filter_counts['monday_over_obs']} OVER picks on Monday (49.0% HR, N=251)"
            )
        if filter_counts['home_over_obs'] > 0:
            logger.info(
                f"Home OVER (OBS 2026-03-27): logged "
                f"{filter_counts['home_over_obs']} home OVER picks (BB CF HR 70% — observation only)"
            )
        if filter_counts['signal_density'] > 0:
            logger.info(f"Signal density filter: skipped {filter_counts['signal_density']} base-only picks")
        if filter_counts['zero_signal_extreme_underprediction'] > 0:
            logger.warning(
                f"Zero-signal extreme underprediction: blocked "
                f"{filter_counts['zero_signal_extreme_underprediction']} picks where "
                f"predicted_pts < 55% of line with real_sc=0 — likely model artifact from line movement"
            )
        if filter_counts['legacy_block'] > 0:
            logger.info(f"Legacy model blocklist: skipped {filter_counts['legacy_block']} predictions from {LEGACY_MODEL_BLOCKLIST}")
        if filter_counts['model_profile_would_block'] > 0:
            logger.info(
                f"Model profile (observation): WOULD block "
                f"{filter_counts['model_profile_would_block']} predictions"
            )
        if filter_counts['regime_over_floor'] > 0:
            over_floor = 4.0 + self._regime_context.get('over_edge_floor_delta', 0)
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
                f"Rescue cap: dropped {filter_counts['rescue_cap']} lowest-priority rescued picks "
                f"to keep rescue ≤ 40% of slate"
            )
        if filter_counts['rescue_health_gate'] > 0:
            logger.info(
                f"Rescue health gate: {filter_counts['rescue_health_gate']} signal(s) "
                f"lost rescue eligibility (7d HR < {RESCUE_MIN_HR_7D}%)"
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

        if filter_counts['depleted_stars_over_obs'] > 0:
            logger.info(
                f"Depleted stars OVER (observation): tagged "
                f"{filter_counts['depleted_stars_over_obs']} OVER picks with 3+ star teammates OUT "
                f"(BB 0% N=4, model 48.2% N=137)"
            )

        if filter_counts['hot_shooting_reversion_obs'] > 0:
            logger.info(
                f"Hot shooting reversion OVER block (ACTIVE 2026-03-26): blocked "
                f"{filter_counts['hot_shooting_reversion_obs']} OVER picks after "
                f"70%+ FG game (~40.8% CF HR, N=250 pred-level)"
            )
        if filter_counts['over_low_rsc_obs'] > 0:
            logger.info(
                f"OVER low rsc (observation): tagged "
                f"{filter_counts['over_low_rsc_obs']} OVER picks with real_sc < 4 "
                f"(45.5% HR at rsc=3, N=11)"
            )
        if filter_counts['mae_gap_obs'] > 0:
            logger.info(
                f"MAE gap (observation): tagged "
                f"{filter_counts['mae_gap_obs']} picks with model MAE > Vegas MAE by 0.15+ "
                f"(40-50% BB HR in this regime)"
            )
        if filter_counts.get('mae_gap_over_block', 0) > 0:
            mae_gap = self._regime_context.get('mae_gap_7d', 0)
            logger.info(
                f"MAE gap OVER block: blocked {filter_counts['mae_gap_over_block']} OVER picks "
                f"(mae_gap={mae_gap:.2f} > 0.5 — model badly losing to Vegas)"
            )
        if filter_counts['thin_slate_obs'] > 0:
            logger.info(
                f"Thin slate (observation): tagged "
                f"{filter_counts['thin_slate_obs']} picks on 4-6 game slates "
                f"(51.2% HR, 76.7% OVER-heavy)"
            )
        if filter_counts['hot_streak_under_obs'] > 0:
            logger.info(
                f"Hot streak UNDER (observation): tagged "
                f"{filter_counts['hot_streak_under_obs']} UNDER picks with "
                f"over_rate_last_10 >= 0.7 (44.4% HR when player hot)"
            )
        if filter_counts['solo_game_pick_obs'] > 0:
            logger.info(
                f"Solo game pick (observation): tagged "
                f"{filter_counts['solo_game_pick_obs']} picks from games with only 1 BB pick "
                f"(52.2% HR solo vs 75.3% multi)"
            )
        if filter_counts['line_anomaly_extreme_drop'] > 0:
            logger.info(
                f"Line anomaly extreme drop: blocked "
                f"{filter_counts['line_anomaly_extreme_drop']} OVER picks with line drop >= 40% or >= 6 pts "
                f"(manufactured edge from info asymmetry)"
            )
        if filter_counts['player_under_suppression_obs'] > 0:
            logger.info(
                f"Player UNDER suppression (observation): tagged "
                f"{filter_counts['player_under_suppression_obs']} UNDER picks on players with "
                f"< 35% UNDER HR at N >= 20"
            )
        if filter_counts['under_low_rsc'] > 0:
            logger.info(
                f"UNDER low rsc (ACTIVE): blocked "
                f"{filter_counts['under_low_rsc']} UNDER picks with real_sc < 2 "
                f"(Mar 8: 6/7 UNDER losses had rsc 1-2)"
            )
        if filter_counts['ft_anomaly_over_block'] > 0:
            logger.info(
                f"FTA anomaly OVER block: blocked "
                f"{filter_counts['ft_anomaly_over_block']} OVER picks with high FTA CV "
                f"(fta_avg>=5, cv>=0.6, backtest 37.5% HR)"
            )
        if filter_counts['counter_market_under'] > 0:
            logger.info(
                f"Counter-market UNDER block: blocked "
                f"{filter_counts['counter_market_under']} UNDER picks fighting market direction "
                f"(line rose 0.5+ with book std 1.0+, backtest 43.2% HR)"
            )
        if filter_counts['over_line_rose_heavy'] > 0:
            logger.info(
                f"OVER line rose heavy block: blocked "
                f"{filter_counts['over_line_rose_heavy']} OVER picks where BettingPros "
                f"line rose >= 1.0 (38.9% HR, fighting the market)"
            )
        if filter_counts['tanking_risk_obs'] > 0:
            logger.info(
                f"Tanking risk (observation): tagged "
                f"{filter_counts['tanking_risk_obs']} UNDER picks with spread >= 10 "
                f"(season-end lopsided games, accumulating data)"
            )

        if filter_counts['team_cap'] > 0:
            logger.info(
                f"Team cap ({MAX_PICKS_PER_TEAM}/team): dropped "
                f"{filter_counts['team_cap']} excess same-team picks"
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
        # Skipped in per_model mode — caps are production-only.
        if self._mode != 'per_model':
            rescued_picks = [p for p in scored if p.get('signal_rescued')]
            non_rescued = [p for p in scored if not p.get('signal_rescued')]
            if scored and len(rescued_picks) > 0:
                max_rescue = max(1, int(len(scored) * 0.4))
                if len(rescued_picks) > max_rescue:
                    # Session 437 P4: Sort by (priority, edge) ascending — drop
                    # lowest-priority rescues first. Old sort was edge-only, which
                    # dropped HSE (100% HR, 3-0) in favor of combo_he_ms (40% HR).
                    rescued_picks.sort(key=lambda x: (
                        RESCUE_SIGNAL_PRIORITY.get(x.get('rescue_signal', ''), 0),
                        x.get('edge', 0),
                    ))
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
                            f"edge={drop_pick.get('edge', 0):.1f} "
                            f"rescue={drop_pick.get('rescue_signal', '?')} "
                            f"priority={RESCUE_SIGNAL_PRIORITY.get(drop_pick.get('rescue_signal', ''), 0)}"
                        )
                    scored = non_rescued + to_keep

        # Session 441: Per-team cap — prevent correlated exposure.
        # Mar 7: 3 UTA OVER picks in same blowout all lost simultaneously.
        # Keep highest-edge picks per team, drop excess to filtered_picks.
        # Sort by composite_score desc first so we keep the best picks.
        # Skipped in per_model mode — caps are production-only.
        if self._mode != 'per_model':
            scored.sort(key=lambda x: x['composite_score'], reverse=True)
            team_counts: Dict[str, int] = {}
            team_kept: List[Dict] = []
            for pick in scored:
                team = pick.get('team_abbr', '')
                team_counts[team] = team_counts.get(team, 0) + 1
                if team_counts[team] > MAX_PICKS_PER_TEAM:
                    filter_counts['team_cap'] += 1
                    _record_filtered(pick, 'team_cap', pick.get('composite_score', 0))
                    logger.info(
                        f"Team cap: dropping {pick['player_lookup']} "
                        f"({team}, #{team_counts[team]} pick) "
                        f"edge={pick.get('composite_score', 0):.1f}"
                    )
                else:
                    team_kept.append(pick)
            scored = team_kept

        # Assign ranks — natural sizing (Session 298: no artificial cap)
        for i, pick in enumerate(scored):
            pick['rank'] = i + 1

        if scored:
            logger.info(
                f"Selected {len(scored)} picks (edge range: "
                f"{scored[-1]['composite_score']:.1f}-{scored[0]['composite_score']:.1f})"
            )

        # Session 442 O5: Solo game pick observation.
        # Picks from games with only 1 BB pick = 52.2% HR (N=69) vs
        # multi-pick games = 75.3% (N=73). 23pp gap across both directions.
        # Mechanism: solo games had poor model coverage overall.
        # Observation mode — tags picks for counterfactual tracking.
        # Skipped in per_model mode — observation counts are meaningless per-model.
        if self._mode != 'per_model' and scored:
            game_pick_counts: Dict[str, int] = {}
            for pick in scored:
                gid = pick.get('game_id', '')
                game_pick_counts[gid] = game_pick_counts.get(gid, 0) + 1
            for pick in scored:
                gid = pick.get('game_id', '')
                pick['picks_in_game'] = game_pick_counts.get(gid, 1)
                if game_pick_counts.get(gid, 1) == 1:
                    filter_counts['solo_game_pick_obs'] += 1
                    _record_filtered(pick, 'solo_game_pick_obs',
                                     pick.get('composite_score', 0),
                                     pick.get('signal_count', 0),
                                     pick.get('signal_tags', []))
                    # Observation only — does NOT block

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
