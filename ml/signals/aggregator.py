"""Best Bets Aggregator — selects top picks from multiple signal sources."""

from typing import Dict, List
from ml.signals.base_signal import SignalResult


class BestBetsAggregator:
    """Aggregates signal results into a ranked best-bets list.

    Scoring:
        composite_score = edge_score * signal_multiplier
        edge_score = min(1.0, abs(edge) / 10.0)
        signal_multiplier = 1.0 + 0.25 * (num_signals - 1)
    """

    MAX_PICKS_PER_DAY = 5

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
                - rank: 1-based rank
        """
        scored = []
        for pred in predictions:
            key = f"{pred['player_lookup']}::{pred['game_id']}"
            results = signal_results.get(key, [])
            qualifying = [r for r in results if r.qualifies]

            if not qualifying:
                continue

            edge = abs(pred.get('edge') or 0)
            edge_score = min(1.0, edge / 10.0)
            signal_multiplier = 1.0 + 0.25 * (len(qualifying) - 1)
            composite_score = edge_score * signal_multiplier

            scored.append({
                **pred,
                'signal_tags': [r.source_tag for r in qualifying],
                'signal_count': len(qualifying),
                'composite_score': round(composite_score, 4),
            })

        # Sort descending by composite score
        scored.sort(key=lambda x: x['composite_score'], reverse=True)

        # Assign ranks and return top N
        for i, pick in enumerate(scored[:self.MAX_PICKS_PER_DAY]):
            pick['rank'] = i + 1

        return scored[:self.MAX_PICKS_PER_DAY]
