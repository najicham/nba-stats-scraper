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
"""

import logging
from typing import Any, Dict, List, Optional

from ml.signals.base_signal import SignalResult
from ml.signals.combo_registry import ComboEntry, load_combo_registry, match_combo
from ml.signals.signal_health import MODEL_DEPENDENT_SIGNALS
from shared.config.model_selection import get_min_confidence

logger = logging.getLogger(__name__)

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
        - MIN_SIGNAL_COUNT = 2 (eliminates 1-signal picks)
        - Confidence floor: model-specific (V12: >= 0.90, excludes 41.7% HR tier)
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
        """
        if combo_registry is not None:
            self._registry = combo_registry
        else:
            self._registry = load_combo_registry(bq_client=None)
        self._signal_health = signal_health or {}
        self._min_confidence = get_min_confidence(model_id or '')
        self._cross_model_factors = cross_model_factors or {}

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
        for pred in predictions:
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

            composite_score = round(base_score + combo_adjustment + consensus_bonus, 4)

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
            })

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
