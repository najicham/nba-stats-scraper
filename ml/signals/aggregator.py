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
ALGORITHM_VERSION = 'v397_q4_scorer_under_block'

# Base signals that fire on nearly every edge 5+ pick. Picks with ONLY
# these signals hit 57.1% (N=42) vs 77.8% for picks with 4+ signals.
# Session 348 analysis: the additional signals (rest_advantage_2d,
# combo_he_ms, combo_3way, book_disagreement, etc.) are what separate
# profitable picks from marginal ones.
BASE_SIGNALS = frozenset({'model_health', 'high_edge', 'edge_spread_optimal'})

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
        - AWAY block: v12_noveg/v9 + AWAY game → skip (43-48% HR vs 57-59% HOME, Session 347/365)
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
            'signal_density': 0,
            'legacy_block': 0,
            'model_profile_would_block': 0,
            'toxic_starter_over_would_block': 0,
            'toxic_star_over_would_block': 0,
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
            # Session 355: Premium signals (combo_3way, combo_he_ms) with 95%+ HR
            # are exempt from the edge floor. We defer the edge floor reject for
            # below-floor picks, tagging them for rescue if premium signals are found.
            pred_edge = abs(pred.get('edge') or 0)
            below_edge_floor = pred_edge < self.MIN_EDGE
            if below_edge_floor:
                # Check if this pick has premium signals that warrant edge floor bypass
                key_for_signal_check = f"{pred['player_lookup']}::{pred['game_id']}"
                signal_check = signal_results.get(key_for_signal_check, [])
                premium_tags = {'combo_3way', 'combo_he_ms'}
                has_premium = any(
                    r.qualifies and r.source_tag in premium_tags
                    for r in signal_check
                )
                if not has_premium:
                    filter_counts['edge_floor'] += 1
                    # Don't track edge_floor — these are below edge 3, not actionable
                    continue
                # Premium signal found — bypass edge floor (95%+ HR signals)

            # Session 378: OVER edge 5+ floor — edge 3-5 OVER = 25% HR (1-3) in
            # best bets full season. Edge 5-7 OVER = 67.5%, edge 7+ = 77.8%.
            # UNDER is profitable at all edge levels (57.5-100%).
            if pred.get('recommendation') == 'OVER' and pred_edge < 5.0:
                filter_counts['over_edge_floor'] += 1
                _record_filtered(pred, 'over_edge_floor', pred_edge)
                continue

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

            # AWAY block (Session 347, expanded Session 365):
            # v12_noveg: 43.8% AWAY (N=105) vs 57.0% HOME — structural to no-vegas features
            # v9: 48.1% AWAY (N=449) vs 58.8% HOME — below breakeven at -110
            if not pred.get('is_home', False):
                from ml.signals.model_direction_affinity import get_affinity_group
                away_group = get_affinity_group(source_family)
                if away_group in ('v12_noveg', 'v9'):
                    filter_counts['away_noveg'] += 1
                    _record_filtered(pred, 'away_noveg', pred_edge)
                    continue

            # HOME OVER block REMOVED (Session 392): N=16 was contaminated by
            # disabled model picks. Combined with AWAY block, would block ALL OVER
            # picks from dominant model families. Revisit if clean data confirms.

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

            # Bench UNDER block (Session 278): line < 12 = 35.1% HR
            line_val = pred.get('line_value') or 0
            if pred.get('recommendation') == 'UNDER' and line_val > 0 and line_val < 12:
                filter_counts['bench_under'] += 1
                _record_filtered(pred, 'bench_under', pred_edge)
                continue

            # Star UNDER block (Session 354, relaxed Session 367):
            # season_avg >= 25 + UNDER was 51.3% HR (N=37) at time of creation.
            # Session 367 revalidation: 55.3% overall (above breakeven), but
            # 58.3% when star_teammates_out >= 1 vs 55.6% without.
            # Now injury-aware: allow when a star teammate is out (usage boost
            # shifts scoring distribution, making UNDER more viable).
            season_avg = pred.get('points_avg_season') or 0
            star_teammates_out = pred.get('star_teammates_out') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and season_avg >= 25
                    and star_teammates_out < 1):
                filter_counts['star_under'] += 1
                _record_filtered(pred, 'star_under', pred_edge)
                continue

            # UNDER Star AWAY block (Session 369): 38.5% HR (5W-8L, -$380) vs HOME 81.8% (9W-2L, +$680)
            # Star-line players (line >= 23) playing AWAY have structurally worse UNDER outcomes
            if (pred.get('recommendation') == 'UNDER'
                    and line_val >= 23
                    and not pred.get('is_home', False)):
                filter_counts['under_star_away'] += 1
                _record_filtered(pred, 'under_star_away', pred_edge)
                continue

            # Medium teammate usage UNDER block (Session 355): 32.0% HR (N=25)
            # Model has 0% importance on teammate_usage_available but production
            # data shows when moderate usage is available (15-30), UNDER = catastrophic.
            teammate_usage = pred.get('teammate_usage_available') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and 15 <= teammate_usage <= 30):
                filter_counts['med_usage_under'] += 1
                _record_filtered(pred, 'med_usage_under', pred_edge)
                continue

            # Starter V12 UNDER block (Session 355): 46.7% HR (N=30)
            # V12 UNDER specifically bad for 15-20 line range (starter tier).
            if (pred.get('recommendation') == 'UNDER'
                    and 15 <= season_avg < 20
                    and source_family.startswith('v12')):
                filter_counts['starter_v12_under'] += 1
                _record_filtered(pred, 'starter_v12_under', pred_edge)
                continue

            # Line jumped UNDER block (Session 294, lowered 306): 38.2% HR at 2.0 (N=272)
            prop_line_delta = pred.get('prop_line_delta')
            if (prop_line_delta is not None
                    and prop_line_delta >= 2.0
                    and pred.get('recommendation') == 'UNDER'):
                filter_counts['line_jumped_under'] += 1
                _record_filtered(pred, 'line_jumped_under', pred_edge)
                continue

            # Line dropped UNDER block (Session 294, lowered 306): 35.2% HR at 2.0 (N=108)
            if (prop_line_delta is not None
                    and prop_line_delta <= -2.0
                    and pred.get('recommendation') == 'UNDER'):
                filter_counts['line_dropped_under'] += 1
                _record_filtered(pred, 'line_dropped_under', pred_edge)
                continue

            # Line dropped OVER block (Session 374b): OVER + line dropped 2+ = 39.1% HR Feb (N=23).
            # Market correcting downward is bearish for OVER. OVER + line UP = 96.6% HR.
            if (prop_line_delta is not None
                    and prop_line_delta <= -2.0
                    and pred.get('recommendation') == 'OVER'):
                filter_counts['line_dropped_over'] += 1
                _record_filtered(pred, 'line_dropped_over', pred_edge)
                continue

            # Neg +/- streak UNDER block (Session 294): 13.1% HR
            neg_pm_streak = pred.get('neg_pm_streak') or 0
            if neg_pm_streak >= 3 and pred.get('recommendation') == 'UNDER':
                filter_counts['neg_pm_streak'] += 1
                _record_filtered(pred, 'neg_pm_streak', pred_edge)
                continue

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

            # High book std UNDER block (Session 377): UNDER + multi_book_line_std 1.0-1.5 = 14.8% HR (N=142).
            # When books disagree significantly on the line, UNDER predictions are unreliable.
            book_std = pred.get('multi_book_line_std') or 0
            if (pred.get('recommendation') == 'UNDER'
                    and 1.0 <= book_std <= 1.5):
                filter_counts['high_book_std_under'] += 1
                _record_filtered(pred, 'high_book_std_under', pred_edge)
                continue

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

            # Edge-tiered signal count (Session 388): SC >= 4 for edge < 7, SC >= 3 for edge 7+.
            # SC=3 at edge 5-7 = 51.3% HR (N=39). SC=4 at edge 5-7 = 70.6% (N=17).
            # SC=3 at edge 7+ = 85.7% (N=7) — preserved.
            # Subsumes SC=3 OVER edge gate (Session 374b) — all directions blocked at SC=3 edge<7.
            required_sc = self.MIN_SIGNAL_COUNT if pred_edge >= self.HIGH_EDGE_SC_THRESHOLD else self.MIN_SIGNAL_COUNT_LOW_EDGE
            sig_tags_early = [r.source_tag for r in qualifying]
            if len(qualifying) < required_sc:
                filter_counts['signal_count'] += 1
                _record_filtered(pred, 'signal_count', pred_edge, len(qualifying), sig_tags_early)
                continue

            # SC=3 OVER block (Session 394): SC=3 OVER is a net loser at 45.5% HR,
            # -1.6 units across Dec-Mar. SC=3 UNDER is profitable (57.9%, +4.4 units).
            # Block all OVER picks with exactly SC=3 regardless of edge.
            if (pred.get('recommendation') == 'OVER'
                    and len(qualifying) == 3):
                filter_counts['sc3_over_block'] += 1
                _record_filtered(pred, 'sc3_over_block', pred_edge, len(qualifying), sig_tags_early)
                continue

            # Starter OVER SC floor (Session 382c, relaxed Session 393):
            # Starter OVER collapsed 90% Jan → 33.3% Feb. SC >= 5 was too restrictive
            # for current signal pool (volatile_scoring_over disabled, rest_advantage_2d
            # expired, several signals need NULL supplemental data). Lowered to SC >= 4
            # during bootstrapping phase. Signal_density still blocks base-only picks.
            if (pred.get('recommendation') == 'OVER'
                    and 15 <= line_val < 25
                    and len(qualifying) < 4):
                filter_counts['starter_over_sc_floor'] += 1
                _record_filtered(pred, 'starter_over_sc_floor', pred_edge, len(qualifying), sig_tags_early)
                continue

            # Confidence floor: model-specific
            if self._min_confidence > 0:
                confidence = pred.get('confidence_score') or 0
                if confidence < self._min_confidence:
                    filter_counts['confidence'] += 1
                    continue

            tags = [r.source_tag for r in qualifying]
            warning_tags: List[str] = []

            # Combo matching (for annotation)
            matched = match_combo(tags, self._registry)

            # Block ANTI_PATTERN combos
            if matched and matched.classification == 'ANTI_PATTERN':
                filter_counts['anti_pattern'] += 1
                continue

            # Signal density filter (Session 348): picks with ONLY the base 3
            # signals (model_health, high_edge, edge_spread_optimal) hit 57.1%
            # (N=42). Picks with at least one additional signal hit 77.8% (N=63).
            # Block picks where every qualifying signal is in the base set.
            # Session 352: Bypass for edge ≥ 7 — at extreme edge the conviction
            # itself is informative (all-model edge 7+ = 52-56% HR). Max 1-2/day.
            tag_set = frozenset(tags)
            if tag_set and tag_set.issubset(BASE_SIGNALS) and pred_edge < 7.0:
                filter_counts['signal_density'] += 1
                _record_filtered(pred, 'signal_density', pred_edge, len(qualifying), tags)
                continue

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

            # Composite score = edge (primary ranking signal)
            # Signal/combo context is tracked but doesn't influence ranking
            composite_score = round(pred_edge, 4)

            # Qualifying subsets (Session 279)
            player_subsets = self._qualifying_subsets.get(key, [])
            subsets_for_storage = [
                {'subset_id': s['subset_id'], 'system_id': s['system_id']}
                for s in player_subsets
            ]

            scored.append({
                **pred,
                'signal_tags': tags,
                'signal_count': len(qualifying),
                'composite_score': composite_score,
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
        if filter_counts['over_edge_floor'] > 0:
            logger.info(f"OVER edge floor (5.0): skipped {filter_counts['over_edge_floor']} OVER picks with edge < 5.0")
        if filter_counts['under_edge_7plus'] > 0:
            logger.info(f"UNDER edge 7+ block: skipped {filter_counts['under_edge_7plus']} predictions")
        if filter_counts['model_direction_affinity'] > 0:
            logger.info(f"Model-direction affinity: skipped {filter_counts['model_direction_affinity']} predictions")
        if filter_counts['away_noveg'] > 0:
            logger.info(f"AWAY block (v12_noveg/v9): skipped {filter_counts['away_noveg']} predictions")
        if filter_counts['under_star_away'] > 0:
            logger.info(f"UNDER Star AWAY block (line≥23): skipped {filter_counts['under_star_away']} predictions")
        if filter_counts['med_usage_under'] > 0:
            logger.info(f"Medium teammate usage UNDER block: skipped {filter_counts['med_usage_under']} predictions")
        if filter_counts['starter_v12_under'] > 0:
            logger.info(f"Starter V12 UNDER block (15-20 line): skipped {filter_counts['starter_v12_under']} predictions")
        if filter_counts['starter_over_sc_floor'] > 0:
            logger.info(f"Starter OVER SC floor: skipped {filter_counts['starter_over_sc_floor']} OVER picks (line 15-25, SC < 4)")
        # sc3_edge_floor retained for schema continuity — subsumed by edge-tiered SC (Session 388)
        if filter_counts['sc3_over_block'] > 0:
            logger.info(f"SC=3 OVER block: skipped {filter_counts['sc3_over_block']} OVER picks with SC=3 (45.5% HR, net loser)")
        if filter_counts['line_dropped_over'] > 0:
            logger.info(f"Line dropped OVER block: skipped {filter_counts['line_dropped_over']} OVER picks with line drop >= 2")
        if filter_counts['opponent_depleted_under'] > 0:
            logger.info(f"Opponent depleted UNDER block: skipped {filter_counts['opponent_depleted_under']} UNDER picks with 3+ opponent stars out")
        if filter_counts['q4_scorer_under_block'] > 0:
            logger.info(f"Q4 scorer UNDER block: skipped {filter_counts['q4_scorer_under_block']} UNDER picks with Q4 ratio >= 0.35 (34.0% HR)")
        if filter_counts['signal_density'] > 0:
            logger.info(f"Signal density filter: skipped {filter_counts['signal_density']} base-only picks")
        if filter_counts['legacy_block'] > 0:
            logger.info(f"Legacy model blocklist: skipped {filter_counts['legacy_block']} predictions from {LEGACY_MODEL_BLOCKLIST}")
        if filter_counts['model_profile_would_block'] > 0:
            logger.info(
                f"Model profile (observation): WOULD block "
                f"{filter_counts['model_profile_would_block']} predictions"
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

        # --- Calendar regime observation (Session 396) ---
        # Detect regime once per aggregate() call. Log picks that WOULD be
        # blocked by calendar-aware filters without actually filtering.
        # Simulation showed: Star OVER already handled by filter stack (66.7%
        # HR in best bets during toxic, N=3). Starter OVER is the real problem
        # (40.0% HR, -2.6 units, N=10 during Jan 30 - Feb 25 toxic window).
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
                        # Starter OVER: 40.0% HR during toxic (N=10, -48.9pp vs normal)
                        if (pick_rec == 'OVER'
                                and 15 <= pick_line < 25):
                            filter_counts['toxic_starter_over_would_block'] += 1
                            logger.info(
                                f"Calendar WOULD block: Starter OVER "
                                f"{pick['player_lookup']} (line={pick_line}, "
                                f"edge={pick.get('composite_score', 0):.1f})"
                            )
                        # Star OVER: already handled by stack (66.7% HR, N=3)
                        # but tracking for completeness
                        if (pick_rec == 'OVER'
                                and pick_line >= 25):
                            filter_counts['toxic_star_over_would_block'] += 1
                            logger.info(
                                f"Calendar WOULD block: Star OVER "
                                f"{pick['player_lookup']} (line={pick_line}, "
                                f"edge={pick.get('composite_score', 0):.1f})"
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
