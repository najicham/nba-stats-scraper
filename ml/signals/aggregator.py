"""Best Bets Aggregator — selects top picks from multiple signal sources.

Session 259: Registry-based combo scoring, signal count floor, improved formula.
    - MIN_SIGNAL_COUNT = 2 (1-signal picks hit 43.8%, harmful)
    - Edge contribution capped at /7.0 (diminishing returns past 7 pts)
    - Signal count multiplier capped at 3 (4+ doesn't improve HR)
    - Combo bonuses/penalties driven by combo_registry instead of hardcoded
"""

import logging
from typing import Dict, List, Optional

from ml.signals.base_signal import SignalResult
from ml.signals.combo_registry import ComboEntry, load_combo_registry, match_combo

logger = logging.getLogger(__name__)


class BestBetsAggregator:
    """Aggregates signal results into a ranked best-bets list.

    Scoring (Session 259):
        edge_score = min(1.0, abs(edge) / 7.0)       # capped at 7 pts
        effective_signals = min(signal_count, 3)       # capped at 3
        signal_multiplier = 1.0 + 0.3 * (effective_signals - 1)  # max 1.6x
        base_score = edge_score * signal_multiplier
        composite_score = base_score + combo_registry_weight

    Filters:
        - MIN_SIGNAL_COUNT = 2 (eliminates 1-signal picks)
        - ANTI_PATTERN combos are blocked entirely
    """

    MAX_PICKS_PER_DAY = 5
    MIN_SIGNAL_COUNT = 2

    def __init__(self, combo_registry: Optional[Dict[str, ComboEntry]] = None):
        """Initialize aggregator.

        Args:
            combo_registry: Pre-loaded combo registry. If None, loads fallback.
        """
        if combo_registry is not None:
            self._registry = combo_registry
        else:
            self._registry = load_combo_registry(bq_client=None)

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

            effective_signals = min(len(qualifying), 3)  # Cap at 3
            signal_multiplier = 1.0 + 0.3 * (effective_signals - 1)  # Max 1.6x

            base_score = edge_score * signal_multiplier

            # Registry-driven combo adjustment
            combo_adjustment = 0.0
            if matched and matched.classification == 'SYNERGISTIC':
                combo_adjustment = matched.score_weight

            # Legacy warning: contradictory signals
            if 'minutes_surge' in tags and 'blowout_recovery' in tags:
                warning_tags.append('contradictory_signals')

            composite_score = round(base_score + combo_adjustment, 4)

            scored.append({
                **pred,
                'signal_tags': tags,
                'signal_count': len(qualifying),
                'composite_score': composite_score,
                'matched_combo_id': matched.combo_id if matched else None,
                'combo_classification': matched.classification if matched else None,
                'combo_hit_rate': matched.hit_rate if matched else None,
                'warning_tags': warning_tags,
            })

        # Sort descending by composite score
        scored.sort(key=lambda x: x['composite_score'], reverse=True)

        # Assign ranks and return top N
        for i, pick in enumerate(scored[:self.MAX_PICKS_PER_DAY]):
            pick['rank'] = i + 1

        return scored[:self.MAX_PICKS_PER_DAY]
