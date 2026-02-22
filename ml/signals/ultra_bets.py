"""Ultra Bets — high-confidence pick classification layer.

Classifies best bets picks into an "Ultra" tier based on criteria
discovered in Session 326 backtesting. Ultra is a label ON TOP of
best bets (not a separate exporter). Each pick is checked against
hardcoded criteria; matches are returned with HR and sample size.

Criteria HRs are from Session 326 backtest (Jan 9 - Feb 21, 2026).
Update manually after retrains.

Created: 2026-02-22 (Session 326)
"""

from typing import Any, Dict, List


# Each criterion: id, description, hit_rate, sample_size, check function
ULTRA_CRITERIA = [
    {
        'id': 'v12_edge_6plus',
        'description': 'V12+vegas model, edge >= 6',
        'hit_rate': 100.0,
        'sample_size': 26,
    },
    {
        'id': 'v12_over_edge_5plus',
        'description': 'V12+vegas OVER, edge >= 5',
        'hit_rate': 100.0,
        'sample_size': 18,
    },
    {
        'id': 'consensus_3plus_edge_5plus',
        'description': '3+ models agree, edge >= 5',
        'hit_rate': 78.9,
        'sample_size': 18,
    },
    {
        'id': 'v12_edge_4_5plus',
        'description': 'V12+vegas model, edge >= 4.5',
        'hit_rate': 77.2,
        'sample_size': 57,
    },
]


def _check_criterion(criterion_id: str, pick: Dict[str, Any]) -> bool:
    """Check if a pick matches a specific ultra criterion."""
    source_family = pick.get('source_model_family', '')
    edge = abs(pick.get('edge') or 0)
    direction = pick.get('recommendation', '')
    model_agreement = pick.get('model_agreement_count', 0)

    if criterion_id == 'v12_edge_6plus':
        return source_family.startswith('v12') and edge >= 6.0

    if criterion_id == 'v12_over_edge_5plus':
        return source_family.startswith('v12') and direction == 'OVER' and edge >= 5.0

    if criterion_id == 'consensus_3plus_edge_5plus':
        return model_agreement >= 3 and edge >= 5.0

    if criterion_id == 'v12_edge_4_5plus':
        return source_family.startswith('v12') and edge >= 4.5

    return False


def classify_ultra_pick(pick: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Classify a pick against all ultra criteria.

    Args:
        pick: Pick dict from aggregator (needs source_model_family, edge,
              recommendation, model_agreement_count).

    Returns:
        List of matched criteria dicts with id, description, hit_rate,
        sample_size. Empty list if no criteria match.
    """
    matched = []
    for criterion in ULTRA_CRITERIA:
        if _check_criterion(criterion['id'], pick):
            matched.append({
                'id': criterion['id'],
                'description': criterion['description'],
                'hit_rate': criterion['hit_rate'],
                'sample_size': criterion['sample_size'],
            })
    return matched
