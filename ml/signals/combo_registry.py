"""Combo Registry — loads validated signal combinations from BigQuery.

Provides combo-aware scoring to the aggregator by replacing hardcoded
bonuses with registry-driven lookups. The registry stores classification
(SYNERGISTIC, ANTI_PATTERN, NEUTRAL), score weights, and historical
hit rates for each validated combo.

Matching logic:
    1. Build canonical key from sorted signal tags: "a+b+c"
    2. Try longest (highest cardinality) match first
    3. Return classification, score_weight, hit_rate, or None

Created: 2026-02-15 (Session 259)
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.nba_predictions.signal_combo_registry'


@dataclass
class ComboEntry:
    """A single combo registry entry."""
    combo_id: str
    display_name: str
    signals: List[str]
    cardinality: int
    classification: str  # SYNERGISTIC | ANTI_PATTERN | NEUTRAL
    status: str          # PRODUCTION | CONDITIONAL | WATCH | BLOCKED
    direction_filter: Optional[str]
    hit_rate: Optional[float]
    roi: Optional[float]
    sample_size: Optional[int]
    score_weight: float
    notes: Optional[str]


# Hardcoded fallback registry — used when BQ is unavailable (e.g., tests, offline)
_FALLBACK_REGISTRY: Dict[str, ComboEntry] = {
    'edge_spread_optimal+high_edge+minutes_surge': ComboEntry(
        combo_id='edge_spread_optimal+high_edge+minutes_surge',
        display_name='Edge Spread + High Edge + Minutes Surge (3-Way)',
        signals=['edge_spread_optimal', 'high_edge', 'minutes_surge'],
        cardinality=3, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=95.5, roi=None, sample_size=22,
        score_weight=2.5, notes='Session 295: OVER_ONLY (UNDER=20.0% N=5). Updated HR from full-season audit.',
    ),
    'high_edge+minutes_surge': ComboEntry(
        combo_id='high_edge+minutes_surge',
        display_name='High Edge + Minutes Surge',
        signals=['high_edge', 'minutes_surge'],
        cardinality=2, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=79.4, roi=58.8, sample_size=34,
        score_weight=2.0, notes=None,
    ),
    'cold_snap': ComboEntry(
        combo_id='cold_snap',
        display_name='Cold Snap (Home Only)',
        signals=['cold_snap'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='OVER_ONLY', hit_rate=93.3, roi=None, sample_size=15,
        score_weight=1.5, notes=None,
    ),
    '3pt_bounce': ComboEntry(
        combo_id='3pt_bounce',
        display_name='3PT Bounce (Guards + Home)',
        signals=['3pt_bounce'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='OVER_ONLY', hit_rate=74.9, roi=None, sample_size=28,
        score_weight=1.0, notes='Session 275: Updated stats from 3-window backtest',
    ),
    'blowout_recovery': ComboEntry(
        combo_id='blowout_recovery',
        display_name='Blowout Recovery (No C, No B2B)',
        signals=['blowout_recovery'],
        cardinality=1, classification='SYNERGISTIC', status='WATCH',
        direction_filter='OVER_ONLY', hit_rate=56.9, roi=None, sample_size=112,
        score_weight=0.5, notes='Session 275: Updated stats from 3-window backtest',
    ),
    'edge_spread_optimal+high_edge': ComboEntry(
        combo_id='edge_spread_optimal+high_edge',
        display_name='Edge Spread + High Edge (Redundancy Trap)',
        signals=['edge_spread_optimal', 'high_edge'],
        cardinality=2, classification='ANTI_PATTERN', status='BLOCKED',
        direction_filter='BOTH', hit_rate=31.3, roi=None, sample_size=16,
        score_weight=-2.0, notes=None,
    ),
    'high_edge': ComboEntry(
        combo_id='high_edge',
        display_name='High Edge (Standalone)',
        signals=['high_edge'],
        cardinality=1, classification='ANTI_PATTERN', status='BLOCKED',
        direction_filter='BOTH', hit_rate=43.8, roi=None, sample_size=16,
        score_weight=-1.0, notes=None,
    ),
    # Market-pattern UNDER signals (Session 275)
    'bench_under': ComboEntry(
        combo_id='bench_under',
        display_name='Bench Player Under',
        signals=['bench_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=76.9, roi=46.7, sample_size=156,
        score_weight=1.5, notes='Session 275: 76.9% AVG HR across 3 eval windows',
    ),
    'high_ft_under': ComboEntry(
        combo_id='high_ft_under',
        display_name='High FT Volume Under',
        signals=['high_ft_under'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='UNDER_ONLY', hit_rate=64.1, roi=22.3, sample_size=74,
        score_weight=0.5, notes='Session 275: 64.1% AVG HR, FTA >= 7',
    ),
    'b2b_fatigue_under': ComboEntry(
        combo_id='b2b_fatigue_under',
        display_name='B2B Fatigue Under',
        signals=['b2b_fatigue_under'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='UNDER_ONLY', hit_rate=85.7, roi=63.6, sample_size=14,
        score_weight=1.0, notes='Session 275: 85.7% AVG HR, small sample (N=14)',
    ),
    # Session 295: Added performing UNDER signals from full-season audit
    'volatile_under': ComboEntry(
        combo_id='volatile_under',
        display_name='Volatile Scorer Under',
        signals=['volatile_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=73.1, roi=37.3, sample_size=26,
        score_weight=1.0, notes='Session 295: 73.1% HR (N=26) full-season audit',
    ),
    'high_usage_under': ComboEntry(
        combo_id='high_usage_under',
        display_name='High Usage Under',
        signals=['high_usage_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=68.1, roi=26.4, sample_size=47,
        score_weight=0.5, notes='Session 295: 68.1% HR (N=47) full-season audit',
    ),
    'prop_line_drop_over': ComboEntry(
        combo_id='prop_line_drop_over',
        display_name='Prop Line Drop Over',
        signals=['prop_line_drop_over'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=71.6, roi=35.0, sample_size=109,
        score_weight=1.0, notes='Session 305: Threshold 3.0→2.0. 71.6% HR (N=109, edge 3+). Was 0 production firings at 3.0.',
    ),
}


def load_combo_registry(bq_client: Optional[bigquery.Client] = None) -> Dict[str, ComboEntry]:
    """Load combo registry from BigQuery, falling back to hardcoded entries.

    Args:
        bq_client: BigQuery client. If None, uses fallback registry.

    Returns:
        Dict keyed by combo_id mapping to ComboEntry.
    """
    if bq_client is None:
        logger.info("No BQ client provided, using fallback combo registry")
        return dict(_FALLBACK_REGISTRY)

    try:
        query = f"""
        SELECT
          combo_id, display_name, signals, cardinality,
          classification, status, direction_filter,
          hit_rate, roi, sample_size, score_weight, notes
        FROM `{TABLE_ID}`
        """
        rows = bq_client.query(query).result(timeout=30)

        registry: Dict[str, ComboEntry] = {}
        for row in rows:
            entry = ComboEntry(
                combo_id=row.combo_id,
                display_name=row.display_name or '',
                signals=list(row.signals) if row.signals else [],
                cardinality=row.cardinality or 0,
                classification=row.classification,
                status=row.status,
                direction_filter=row.direction_filter,
                hit_rate=row.hit_rate,
                roi=row.roi,
                sample_size=row.sample_size,
                score_weight=row.score_weight or 0.0,
                notes=row.notes,
            )
            registry[entry.combo_id] = entry

        if registry:
            logger.info(f"Loaded {len(registry)} combo entries from BQ registry")
            return registry

        logger.warning("BQ combo registry empty, using fallback")
        return dict(_FALLBACK_REGISTRY)

    except Exception as e:
        logger.warning(f"Failed to load combo registry from BQ: {e}, using fallback")
        return dict(_FALLBACK_REGISTRY)


def match_combo(
    signal_tags: List[str],
    registry: Dict[str, ComboEntry],
) -> Optional[ComboEntry]:
    """Find the best matching combo for a set of qualifying signal tags.

    Matching strategy:
        1. Generate all possible subset keys from signal_tags
        2. Match longest (highest cardinality) combo first
        3. Return the matched ComboEntry or None

    Args:
        signal_tags: List of qualifying signal tags for a pick.
        registry: Combo registry dict from load_combo_registry().

    Returns:
        Best matching ComboEntry, or None if no match.
    """
    if not signal_tags or not registry:
        return None

    # Build canonical key for the full tag set
    sorted_tags = sorted(signal_tags)

    # Try exact match on full set first
    full_key = '+'.join(sorted_tags)
    if full_key in registry:
        return registry[full_key]

    # Try subsets by decreasing cardinality
    best_match: Optional[ComboEntry] = None
    best_cardinality = 0

    for combo_id, entry in registry.items():
        # Check if all signals in the combo are present in the tags
        if all(s in signal_tags for s in entry.signals):
            if entry.cardinality > best_cardinality:
                best_match = entry
                best_cardinality = entry.cardinality

    return best_match
