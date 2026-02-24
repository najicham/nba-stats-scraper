"""Pick Angle Builder — generates human-readable reasoning for each pick.

Angles explain WHY a pick was selected: player tier patterns, cross-model
consensus, subset membership, and signal-specific insights.

Session 278: Initial creation.
Session 279: Added subset membership angle (qualifying_subsets provenance).
Session 284: Added high-conviction edge>=5 angle (65.6% HR cross-season).
Session 308: Removed confidence angle (Session 306 proved confidence doesn't
  separate good from bad for V9 — all tiers cluster 46-55% HR).
"""

import logging
from typing import Any, Dict, List, Optional

from shared.config.subset_public_names import SUBSET_PUBLIC_NAMES
from ml.signals.model_direction_affinity import get_affinity_group, _classify_edge_band

logger = logging.getLogger(__name__)

MAX_ANGLES = 5

# Historical hit rates by direction + player tier
DIRECTION_TIER_HR = {
    ('OVER', 'star'): 57.7, ('OVER', 'starter'): 53.2,
    ('OVER', 'role'): 55.1, ('OVER', 'bench'): 58.0,
    ('UNDER', 'star'): 65.9, ('UNDER', 'starter'): 52.1,
    ('UNDER', 'role'): 53.8, ('UNDER', 'bench'): 35.1,
}

# Signal tag → angle template
SIGNAL_ANGLE_MAP = {
    'high_edge': "High edge: model predicts {edge:.1f} pts from line",
    'bench_under': "Bench UNDER pattern: 76.6% historical rate",
    # dual_agree, model_consensus_v9_v12 REMOVED (Session 296)
    'combo_he_ms': "High edge + minutes surge combo: 94.9% HR",
    'combo_3way': "Triple combo (ESO+HE+MS): 78.1% HR",
    'b2b_fatigue_under': "Back-to-back fatigue: 85.7% UNDER HR",
    'rest_advantage_2d': "2+ days rest advantage: 64.8% HR",
    'edge_spread_optimal': "Optimal edge spread: 67.2% HR",
    '3pt_bounce': "3pt bounce-back pattern: 74.9% HR",
    # high_ft_under REMOVED — 33.3% HR on best bets (Session 326)
    'blowout_recovery': "Blowout recovery bounce: 56.9% HR",
    # minutes_surge REMOVED (Session 318)
    # self_creator_under REMOVED — 36.4% HR on best bets (Session 326)
    # volatile_under REMOVED — 33.3% HR on best bets (Session 326)
    # high_usage_under REMOVED — 40.0% HR on best bets (Session 326)
    # cold_snap REMOVED (Session 318)
    'book_disagreement': "Sportsbooks disagree on line: 93.0% edge 3+ HR (WATCH)",
    'ft_rate_bench_over': "Bench OVER + high FT rate: 72.5% HR historically (WATCH)",
}

# Warning tag → warning angle
WARNING_ANGLE_MAP = {
    'contradictory_signals': "Warning: contradictory signals detected",
}


def _classify_tier(line_value: float) -> str:
    """Classify player tier by line value."""
    if line_value >= 25:
        return 'star'
    elif line_value >= 18:
        return 'starter'
    elif line_value >= 12:
        return 'role'
    else:
        return 'bench'


def _direction_tier_angle(pick: Dict) -> str | None:
    """Generate direction + player tier angle."""
    direction = pick.get('recommendation')
    line_value = pick.get('line_value')
    if not direction or not line_value:
        return None

    tier = _classify_tier(float(line_value))
    key = (direction, tier)
    hr = DIRECTION_TIER_HR.get(key)
    if hr is None:
        return None

    tier_label = {'star': 'star (25+)', 'starter': 'starter (18-25)',
                  'role': 'role (12-18)', 'bench': 'bench (<12)'}
    return f"{direction} on {tier_label[tier]} line: {hr:.1f}% HR historically"


def _consensus_angle(pick: Dict, cross_model_factors: Dict) -> str | None:
    """Generate cross-model consensus angle."""
    n_agreeing = cross_model_factors.get('model_agreement_count', 0)
    if n_agreeing < 3:
        return None

    direction = cross_model_factors.get('majority_direction', '')
    avg_edge = cross_model_factors.get('avg_edge_agreeing', 0)

    return f"{n_agreeing} of 6 models agree {direction} (avg edge {avg_edge:.1f})"


def _signal_angles(pick: Dict, signal_results: List) -> List[str]:
    """Generate one angle per qualifying signal."""
    angles = []
    direction = pick.get('recommendation', '')
    edge = pick.get('edge') or 0

    qualifying_tags = pick.get('signal_tags', [])
    for tag in qualifying_tags:
        if tag == 'model_health':
            continue

        template = SIGNAL_ANGLE_MAP.get(tag)
        if template:
            try:
                angle = template.format(
                    edge=edge,
                    direction=direction,
                )
            except (KeyError, ValueError):
                angle = template
        else:
            angle = f"Signal: {tag}"

        angles.append(angle)

    return angles


def _warning_angles(pick: Dict) -> List[str]:
    """Generate warning angles from warning_tags."""
    angles = []
    for tag in pick.get('warning_tags', []):
        angle = WARNING_ANGLE_MAP.get(tag)
        if angle:
            angles.append(angle)

    return angles


def _high_conviction_angle(pick: Dict) -> str | None:
    """Generate high-conviction angle for edge >= 5 picks (Session 284)."""
    edge = abs(pick.get('edge') or 0)
    if edge < 5.0:
        return None
    return f"High conviction: edge {edge:.1f} pts (65.6% HR at edge 5+)"


def _model_direction_angle(
    pick: Dict,
    model_direction_affinities: Optional[Dict] = None,
) -> str | None:
    """Generate model-direction context angle (Session 330).

    Shows whether the pick's model is in its strong or weak direction
    based on historical affinity data.
    """
    if not model_direction_affinities:
        return None

    source_family = pick.get('source_model_family', '')
    group = get_affinity_group(source_family)
    if not group:
        return None

    direction = pick.get('recommendation', '')
    if direction not in ('OVER', 'UNDER'):
        return None

    edge = abs(pick.get('edge') or 0)
    band = _classify_edge_band(edge)
    if not band:
        return None

    # Look up the affinity data for this combo
    group_data = model_direction_affinities.get(group, {})
    direction_data = group_data.get(direction, {})
    band_data = direction_data.get(band)

    if not band_data:
        return None

    hr = band_data.get('hit_rate')
    n = band_data.get('total_picks', 0)
    if hr is None or n < 10:
        return None

    # Group display names
    group_names = {
        'v9': 'V9',
        'v12_noveg': 'V12-noveg',
        'v12_vegas': 'V12+vegas',
    }
    group_label = group_names.get(group, group)

    band_labels = {
        '3_5': '3-5',
        '5_7': '5-7',
        '7_plus': '7+',
    }
    band_label = band_labels.get(band, band)

    if hr >= 60.0:
        return f"Model-direction match: {group_label} {direction} edge {band_label}: {hr:.1f}% HR ({n})"
    elif hr < 45.0:
        return f"Model-direction caution: {group_label} {direction} edge {band_label}: {hr:.1f}% HR ({n})"

    return None


def _subset_membership_angle(pick: Dict) -> str | None:
    """Generate angle from qualifying subset membership (Session 279)."""
    subsets = pick.get('qualifying_subsets', [])
    if len(subsets) < 2:
        return None

    # Use public names where available, fall back to subset_id
    names = []
    for s in subsets:
        sid = s.get('subset_id', '')
        public = SUBSET_PUBLIC_NAMES.get(sid)
        if public:
            names.append(public['name'])
        else:
            names.append(sid)

    return f"Appears in {len(subsets)} subsets: {', '.join(names)}"


def build_pick_angles(
    pick: Dict[str, Any],
    signal_results: List,
    cross_model_factors: Dict[str, Any],
    direction_health: Dict[str, Any] | None = None,
    model_direction_affinities: Optional[Dict] = None,
) -> List[str]:
    """Build human-readable angles explaining why a pick was selected.

    Args:
        pick: Pick dict from aggregator (includes signal_tags, warning_tags, etc.)
        signal_results: List of SignalResult objects for this pick.
        cross_model_factors: Cross-model consensus factors for this pick.
        direction_health: Optional dict with over_hr_14d, under_hr_14d rolling HRs.
        model_direction_affinities: Optional nested dict from compute_model_direction_affinities.

    Returns:
        List of up to MAX_ANGLES angle strings, ordered by importance.
    """
    angles: List[str] = []

    # 0. Ultra Bets angle — highest priority (Session 326, updated 327)
    ultra_criteria = pick.get('ultra_criteria', [])
    if ultra_criteria:
        # Use highest-HR criterion for the angle text
        best = max(ultra_criteria, key=lambda c: c.get('backtest_hr', 0))
        if best.get('live_hr') is not None and best.get('live_n', 0) > 0:
            angles.append(
                f"ULTRA BET: {best['description']} — "
                f"backtest {best['backtest_hr']:.1f}% ({best['backtest_n']}), "
                f"live {best['live_hr']:.1f}% ({best['live_n']})"
            )
        else:
            angles.append(
                f"ULTRA BET: {best['description']} — "
                f"{best['backtest_hr']:.1f}% HR ({best['backtest_n']} picks)"
            )

    # 1. High conviction edge (Session 284 — 65.6% HR cross-season)
    hc_angle = _high_conviction_angle(pick)
    if hc_angle:
        angles.append(hc_angle)

    # 2. Subset membership (Session 279 — high-value provenance)
    subset_angle = _subset_membership_angle(pick)
    if subset_angle:
        angles.append(subset_angle)

    # 3. Direction + player tier
    tier_angle = _direction_tier_angle(pick)
    if tier_angle:
        angles.append(tier_angle)

    # 4. Model-direction affinity (Session 330)
    mda_angle = _model_direction_angle(pick, model_direction_affinities)
    if mda_angle:
        angles.append(mda_angle)

    # 5. Cross-model consensus
    consensus = _consensus_angle(pick, cross_model_factors)
    if consensus:
        angles.append(consensus)

    # 6. Signal-specific angles
    sig_angles = _signal_angles(pick, signal_results)
    angles.extend(sig_angles)

    # 7. Warning angles (always last)
    warn_angles = _warning_angles(pick)
    angles.extend(warn_angles)

    # 8. Direction health warning (Session 284)
    if direction_health:
        direction = pick.get('recommendation')
        if direction == 'OVER' and direction_health.get('over_hr_14d') is not None:
            hr = direction_health['over_hr_14d']
            if hr < 50.0:
                angles.append(
                    f"Warning: OVER direction at {hr:.0f}% HR last 14d — below breakeven"
                )
        elif direction == 'UNDER' and direction_health.get('under_hr_14d') is not None:
            hr = direction_health['under_hr_14d']
            if hr < 50.0:
                angles.append(
                    f"Warning: UNDER direction at {hr:.0f}% HR last 14d — below breakeven"
                )

    return angles[:MAX_ANGLES]
