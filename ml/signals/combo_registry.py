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
    # edge_spread_optimal+high_edge+minutes_surge REMOVED — minutes_surge standalone removed (Session 318)
    # high_edge+minutes_surge REMOVED — minutes_surge standalone removed (Session 318)
    # cold_snap REMOVED — N=0 in all backtest windows (Session 318)
    # NOTE: combo_he_ms and combo_3way signals still fire independently (check supplemental data directly)
    '3pt_bounce': ComboEntry(
        combo_id='3pt_bounce',
        display_name='3PT Bounce (Guards + Home)',
        signals=['3pt_bounce'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='OVER_ONLY', hit_rate=74.9, roi=None, sample_size=28,
        score_weight=1.0, notes='Session 275: Updated stats from 3-window backtest',
    ),
    'bench_under': ComboEntry(
        combo_id='bench_under',
        display_name='Bench Player Under',
        signals=['bench_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=76.9, roi=46.7, sample_size=156,
        score_weight=1.5, notes='Session 275: 76.9% AVG HR across 3 eval windows',
    ),
    # Session 371+ signals
    'home_under': ComboEntry(
        combo_id='home_under',
        display_name='Home Under',
        signals=['home_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=63.9, roi=None, sample_size=1386,
        score_weight=1.0, notes='Session 371: 63.9% HR (N=1,386), Feb-resilient 63.4%',
    ),
    'scoring_cold_streak_over': ComboEntry(
        combo_id='scoring_cold_streak_over',
        display_name='Scoring Cold Streak Over',
        signals=['scoring_cold_streak_over'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='OVER_ONLY', hit_rate=65.1, roi=None, sample_size=304,
        score_weight=1.0, notes='Session 371: 65.1% HR (N=304)',
    ),
    'extended_rest_under': ComboEntry(
        combo_id='extended_rest_under',
        display_name='Extended Rest Under',
        signals=['extended_rest_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=61.8, roi=None, sample_size=76,
        score_weight=1.0, notes='Session 372: 61.8% HR (N=76), rest_days >= 4 + line >= 15',
    ),
    'starter_under': ComboEntry(
        combo_id='starter_under',
        display_name='Starter Under',
        signals=['starter_under'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='UNDER_ONLY', hit_rate=68.1, roi=None, sample_size=None,
        score_weight=1.0, notes='Session 372: Dec 68.1%, Feb 54.8%',
    ),
    'high_scoring_environment_over': ComboEntry(
        combo_id='high_scoring_environment_over',
        display_name='High Scoring Environment Over',
        signals=['high_scoring_environment_over'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='OVER_ONLY', hit_rate=70.2, roi=None, sample_size=329,
        score_weight=1.0, notes='Session 373: 70.2% HR (N=329), Feb-resilient 64.3%',
    ),
    'fast_pace_over': ComboEntry(
        combo_id='fast_pace_over',
        display_name='Fast Pace Over',
        signals=['fast_pace_over'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=81.5, roi=None, sample_size=None,
        score_weight=1.0, notes='Session 374: 81.5% HR',
    ),
    'volatile_scoring_over': ComboEntry(
        combo_id='volatile_scoring_over',
        display_name='Volatile Scoring Over',
        signals=['volatile_scoring_over'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=81.5, roi=None, sample_size=None,
        score_weight=1.0, notes='Session 374: 81.5% HR',
    ),
    'low_line_over': ComboEntry(
        combo_id='low_line_over',
        display_name='Low Line Over',
        signals=['low_line_over'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=78.1, roi=None, sample_size=None,
        score_weight=1.0, notes='Session 374: 78.1% HR',
    ),
    'line_rising_over': ComboEntry(
        combo_id='line_rising_over',
        display_name='Line Rising Over',
        signals=['line_rising_over'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=96.6, roi=None, sample_size=None,
        score_weight=1.5, notes='Session 374b: 96.6% HR, replaced prop_line_drop_over',
    ),
    'self_creation_over': ComboEntry(
        combo_id='self_creation_over',
        display_name='Self Creation Over',
        signals=['self_creation_over'],
        cardinality=1, classification='SYNERGISTIC', status='CONDITIONAL',
        direction_filter='OVER_ONLY', hit_rate=59.0, roi=None, sample_size=None,
        score_weight=1.0, notes='Session 380: 59% overall, 37% Feb — conservative',
    ),
    'sharp_line_move_over': ComboEntry(
        combo_id='sharp_line_move_over',
        display_name='Sharp Line Move Over',
        signals=['sharp_line_move_over'],
        cardinality=1, classification='SYNERGISTIC', status='PRODUCTION',
        direction_filter='OVER_ONLY', hit_rate=67.8, roi=None, sample_size=577,
        score_weight=1.0, notes='Session 380: 67.8% HR (N=577), Feb-resilient 69%',
    ),
    # high_ft_under REMOVED — 33.3% HR on best bets (Session 326)
    # volatile_under REMOVED — 33.3% HR on best bets (Session 326)
    # high_usage_under REMOVED — 40.0% HR on best bets (Session 326)
    # blowout_recovery DISABLED — 50% HR (7-7), 25% in Feb (Session 349)
    # b2b_fatigue_under DISABLED — 39.5% Feb HR (Session 373)
    # prop_line_drop_over DISABLED — conceptually backward, 39.1% Feb HR (Session 374b)
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
