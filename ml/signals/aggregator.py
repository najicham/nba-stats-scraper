"""Best Bets Aggregator — selects top picks from multiple signal sources.

Session 259: Registry-based combo scoring, signal count floor, improved formula.
    - MIN_SIGNAL_COUNT = 2 (1-signal picks hit 43.8%, harmful)
    - Edge contribution capped at /7.0 (diminishing returns past 7 pts)
    - Signal count multiplier capped at 3 (4+ doesn't improve HR)
    - Combo bonuses/penalties driven by combo_registry instead of hardcoded

Session 260: Signal health weighting (LIVE).
    - HOT regime signals get 1.2x weight multiplier
    - COLD regime signals get 0.5x weight multiplier
    - NORMAL regime signals unchanged (1.0x)
    - Multiplier applied to each signal's contribution to signal_multiplier

Session 264: COLD model-dependent signals → 0.0x weight.
    - Model-dependent signals (high_edge, edge_spread_optimal, etc.) are
      downstream of model predictions — broken model means broken signals.
    - COLD behavioral signals (minutes_surge, cold_snap, etc.) keep 0.5x.

Session 279: Pick provenance — qualifying_subsets + algorithm_version.
    - Each scored pick now includes qualifying_subsets (which Level 1/2 subsets
      the player-game already appeared in) and qualifying_subset_count.
    - ALGORITHM_VERSION tag for scoring formula traceability.
    - Phase 1: observation only (store, don't score on subset membership).

Session 284: Player blacklist + avoid-familiar + remove rel_edge filter.
    - Players with <40% HR on 8+ graded edge-3+ picks are excluded.
    - Checked FIRST in aggregate loop (before signal evaluation, for efficiency).
    - Season replay proved +$10,450 P&L improvement.
    - Avoid-familiar: skip players with 6+ games vs opponent (+$1,780 P&L).
    - Removed rel_edge>=30% filter: was blocking 62.8% HR picks (above breakeven).
      Cross-season analysis showed it hurts 2025-26 profits (blocks 65.5% HR picks).
"""

import logging
from typing import Any, Dict, List, Optional, Set

from ml.signals.base_signal import SignalResult
from ml.signals.combo_registry import ComboEntry, load_combo_registry, match_combo
from ml.signals.signal_health import MODEL_DEPENDENT_SIGNALS
from shared.config.model_selection import get_min_confidence

logger = logging.getLogger(__name__)

# Bump whenever scoring formula, filters, or combo weights change
ALGORITHM_VERSION = 'v296_remove_consensus_signals'

# Signal health regime → weight multiplier
HEALTH_MULTIPLIERS = {
    'HOT': 1.2,
    'NORMAL': 1.0,
    'COLD': 0.5,
}


class BestBetsAggregator:
    """Aggregates signal results into a ranked best-bets list.

    Scoring (Session 259, updated Session 260):
        edge_score = min(1.0, abs(edge) / 7.0)       # capped at 7 pts
        effective_signals = sum of health-weighted qualifying signals (capped at 3.0)
        signal_multiplier = 1.0 + 0.3 * (effective_signals - 1)  # max 1.6x
        base_score = edge_score * signal_multiplier
        composite_score = base_score + combo_registry_weight

    Filters:
        - Player blacklist: <40% HR on 8+ picks → skip (Session 284)
        - Avoid familiar: 6+ games vs this opponent → skip (Session 284)
        - MIN_SIGNAL_COUNT = 2 (eliminates 1-signal picks)
        - Confidence floor: model-specific (V12: >= 0.90, excludes 41.7% HR tier)
        - Feature quality floor: quality < 85 → skip (24.0% HR)
        - Bench UNDER block: UNDER + line < 12 → skip (35.1% HR)
        - Line jumped UNDER block: UNDER + line jumped 3+ → skip (47.4% HR, Session 294)
        - Line dropped UNDER block: UNDER + line dropped 3+ → skip (41.0% HR, Session 294)
        - Neg +/- streak UNDER block: UNDER + 3+ neg +/- games → skip (13.1% HR, Session 294)
        - ANTI_PATTERN combos are blocked entirely
    """

    MAX_PICKS_PER_DAY = 5
    MIN_SIGNAL_COUNT = 2

    def __init__(
        self,
        combo_registry: Optional[Dict[str, ComboEntry]] = None,
        signal_health: Optional[Dict[str, Dict[str, Any]]] = None,
        model_id: Optional[str] = None,
        cross_model_factors: Optional[Dict[str, Dict[str, Any]]] = None,
        qualifying_subsets: Optional[Dict[str, List[Dict]]] = None,
        player_blacklist: Optional[Set[str]] = None,
    ):
        """Initialize aggregator.

        Args:
            combo_registry: Pre-loaded combo registry. If None, loads fallback.
            signal_health: Dict keyed by signal_tag with 'regime' field.
                Example: {'high_edge': {'regime': 'HOT', 'hr_7d': 75.0, ...}}
            model_id: Model ID for model-specific config (e.g. confidence floor).
            cross_model_factors: Dict keyed by 'player_lookup::game_id' with
                consensus factors from CrossModelScorer. If None, no consensus
                bonus is applied.
            qualifying_subsets: Dict keyed by 'player_lookup::game_id' with
                list of Level 1/2 subsets the player already appears in.
                From subset_membership_lookup. Phase 1: observation only.
            player_blacklist: Set of player_lookup strings to exclude.
                Players with <40% HR on 8+ picks. Session 284.
        """
        if combo_registry is not None:
            self._registry = combo_registry
        else:
            self._registry = load_combo_registry(bq_client=None)
        self._signal_health = signal_health or {}
        self._min_confidence = get_min_confidence(model_id or '')
        self._cross_model_factors = cross_model_factors or {}
        self._qualifying_subsets = qualifying_subsets or {}
        self._player_blacklist = player_blacklist or set()

    def aggregate(self, predictions: List[Dict],
                  signal_results: Dict[str, List[SignalResult]]) -> List[Dict]:
        """Select top picks for a single game date.

        Args:
            predictions: List of prediction dicts (one per player-game).
            signal_results: Mapping from prediction key
                (player_lookup::game_id) to list of qualifying SignalResults.

        Returns:
            Ranked list of up to MAX_PICKS_PER_DAY picks, each with:
                - All original prediction fields
                - signal_tags: list of qualifying signal tags
                - signal_count: number of qualifying signals
                - composite_score: ranking score
                - matched_combo_id: best matching combo from registry
                - combo_classification: SYNERGISTIC | ANTI_PATTERN | NEUTRAL
                - combo_hit_rate: historical hit rate of matched combo
                - warning_tags: list of warning labels
                - rank: 1-based rank
        """
        scored = []
        blacklist_skip_count = 0
        for pred in predictions:
            # Player blacklist: FIRST filter (Session 284)
            # Blocks chronically losing players before any signal evaluation
            if pred['player_lookup'] in self._player_blacklist:
                blacklist_skip_count += 1
                continue

            key = f"{pred['player_lookup']}::{pred['game_id']}"
            results = signal_results.get(key, [])
            qualifying = [r for r in results if r.qualifies]

            if not qualifying:
                continue

            # Signal count floor: skip 1-signal picks (43.8% HR)
            if len(qualifying) < self.MIN_SIGNAL_COUNT:
                continue

            # Confidence floor: model-specific (V12: 0.87 tier has 41.7% HR)
            if self._min_confidence > 0:
                confidence = pred.get('confidence_score') or 0
                if confidence < self._min_confidence:
                    continue

            # Smart filter: Feature quality floor (Session 278)
            # Picks with quality < 85 have 24.0% HR — worse than random
            quality = pred.get('feature_quality_score') or 0
            if quality > 0 and quality < 85:
                continue

            # Smart filter: Bench UNDER block (Session 278)
            # Bench UNDER (line < 12) = 35.1% HR — catastrophic
            line_val = pred.get('line_value') or 0
            if pred.get('recommendation') == 'UNDER' and line_val > 0 and line_val < 12:
                continue

            # Rel_edge>=30% filter REMOVED (Session 284)
            # Was blocking picks with 62.8% combined HR (above breakeven).
            # In 2025-26, blocked 65.5% HR picks — our best tier.

            # Smart filter: Avoid familiar matchups (Session 284)
            # Players with 6+ games vs this opponent regress to noise
            # Season replay: +$1,780 P&L when stacked with other filters
            games_vs_opp = pred.get('games_vs_opponent') or 0
            if games_vs_opp >= 6:
                continue

            # Smart filter: Block UNDER when line jumped 3+ (Session 294)
            # UNDER + line jumped 3+ = 47.4% HR (N=627) — below breakeven
            # Market raised the line after a big game, our UNDER calls lose edge
            # Note: OVER + line jumped is fine (56.8-64.9% HR) — do NOT block
            prop_line_delta = pred.get('prop_line_delta')
            if (prop_line_delta is not None
                    and prop_line_delta >= 3.0
                    and pred.get('recommendation') == 'UNDER'):
                continue

            # Smart filter: Block UNDER when line dropped 3+ (Session 294)
            # UNDER + line dropped 3+ = 41.0% HR (N=188) — market already priced the decline
            if (prop_line_delta is not None
                    and prop_line_delta <= -3.0
                    and pred.get('recommendation') == 'UNDER'):
                continue

            # Smart filter: Block UNDER when neg +/- streak 3+ games (Session 294)
            # 13.1% HR (N=84) — players in losing lineups bounce back, UNDER is a trap
            neg_pm_streak = pred.get('neg_pm_streak') or 0
            if neg_pm_streak >= 3 and pred.get('recommendation') == 'UNDER':
                continue

            tags = [r.source_tag for r in qualifying]
            warning_tags: List[str] = []

            # Match combo from registry
            matched = match_combo(tags, self._registry)

            # Block ANTI_PATTERN combos entirely
            if matched and matched.classification == 'ANTI_PATTERN':
                continue

            # Compute composite score with improved formula
            edge = abs(pred.get('edge') or 0)
            edge_score = min(1.0, edge / 7.0)  # Cap at 7 pts (was /10.0)

            # Health-weighted effective signal count (Session 260)
            effective_signals = self._weighted_signal_count(tags)
            signal_multiplier = 1.0 + 0.3 * (effective_signals - 1)  # Max 1.6x

            base_score = edge_score * signal_multiplier

            # Registry-driven combo adjustment
            combo_adjustment = 0.0
            if matched and matched.classification == 'SYNERGISTIC':
                combo_adjustment = matched.score_weight

            # Legacy warning: contradictory signals
            if 'minutes_surge' in tags and 'blowout_recovery' in tags:
                warning_tags.append('contradictory_signals')

            # Cross-model consensus bonus (Session 277)
            consensus_bonus = 0.0
            xm_factors = self._cross_model_factors.get(key, {})
            model_agreement = xm_factors.get('model_agreement_count', 0)
            feature_diversity = xm_factors.get('feature_set_diversity', 0)
            quantile_under = xm_factors.get('quantile_consensus_under', False)

            if xm_factors and pred.get('recommendation') == xm_factors.get('majority_direction'):
                consensus_bonus = xm_factors.get('consensus_bonus', 0)

            agreeing_model_ids = xm_factors.get('agreeing_model_ids', [])

            composite_score = round(base_score + combo_adjustment + consensus_bonus, 4)

            # Qualifying subsets from Level 1/2 (Session 279)
            player_subsets = self._qualifying_subsets.get(key, [])
            # Strip rank_in_subset for JSON storage (keep subset_id + system_id)
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

        if blacklist_skip_count > 0:
            logger.info(
                f"Player blacklist: skipped {blacklist_skip_count} predictions "
                f"({len(self._player_blacklist)} players on blacklist)"
            )

        # Sort descending by composite score
        scored.sort(key=lambda x: x['composite_score'], reverse=True)

        # Assign ranks and return top N
        for i, pick in enumerate(scored[:self.MAX_PICKS_PER_DAY]):
            pick['rank'] = i + 1

        return scored[:self.MAX_PICKS_PER_DAY]

    def _weighted_signal_count(self, tags: List[str]) -> float:
        """Compute health-weighted effective signal count, capped at 3.0.

        Each signal contributes its health multiplier (HOT=1.2, NORMAL=1.0,
        COLD=0.5) instead of a flat 1.0. Result is capped at 3.0 to match
        the existing diminishing-returns cap.
        """
        total = 0.0
        for tag in tags:
            mult = self._get_health_multiplier(tag)
            total += mult
        return min(total, 3.0)

    def _get_health_multiplier(self, signal_tag: str) -> float:
        """Get health-based weight multiplier for a signal.

        Returns:
            1.2 for HOT, 1.0 for NORMAL/unknown, 0.5 for COLD behavioral,
            0.0 for COLD model-dependent (Session 264).
        """
        health = self._signal_health.get(signal_tag)
        if not health:
            return 1.0
        regime = health.get('regime', 'NORMAL')

        if regime == 'COLD':
            # Model-dependent signals are downstream of predictions —
            # broken model means broken signal. Zero them out.
            is_model_dep = health.get('is_model_dependent')
            if is_model_dep is None:
                # Fallback: use static set if BQ field missing
                is_model_dep = signal_tag in MODEL_DEPENDENT_SIGNALS
            if is_model_dep:
                logger.debug(
                    f"Signal '{signal_tag}' zeroed: COLD + model-dependent"
                )
                return 0.0

        mult = HEALTH_MULTIPLIERS.get(regime, 1.0)
        if mult != 1.0:
            logger.debug(
                f"Signal '{signal_tag}' health multiplier: {mult}x ({regime})"
            )
        return mult
