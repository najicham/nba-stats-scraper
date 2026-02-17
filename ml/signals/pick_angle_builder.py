"""Pick Angle Builder — generates human-readable reasoning for each pick.

Angles explain WHY a pick was selected: confidence context, player tier
patterns, cross-model consensus, subset membership, and signal-specific insights.

Session 278: Initial creation.
Session 279: Added subset membership angle (qualifying_subsets provenance).
Session 284: Added high-conviction edge>=5 angle (65.6% HR cross-season).
"""

import logging
from typing import Any, Dict, List

from shared.config.subset_public_names import SUBSET_PUBLIC_NAMES

logger = logging.getLogger(__name__)

MAX_ANGLES = 5

# Historical hit rates by confidence tier (from Session 277 analysis)
CONFIDENCE_HR_MAP = {
    95: 55.4, 92: 47.5, 90: 52.7, 89: 54.8,
    87: 50.9, 85: 51.2, 82: 49.8, 79: 48.1, 77: 46.5,
}

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
    'dual_agree': "V9 + V12 both say {direction}",
    'model_consensus_v9_v12': "V9 + V12 both say {direction}",
    'combo_he_ms': "High edge + minutes surge combo: 94.9% HR",
    'combo_3way': "Triple combo (ESO+HE+MS): 78.1% HR",
    'b2b_fatigue_under': "Back-to-back fatigue: 85.7% UNDER HR",
    'rest_advantage_2d': "2+ days rest advantage: 64.8% HR",
    'edge_spread_optimal': "Optimal edge spread: 67.2% HR",
    '3pt_bounce': "3pt bounce-back pattern: 74.9% HR",
    'high_ft_under': "High FT volume UNDER: 64.1% HR",
    'blowout_recovery': "Blowout recovery bounce: 56.9% HR",
    'minutes_surge': "Minutes surge detected",
    'self_creator_under': "Self-creator UNDER: 61.8% HR",
    'volatile_under': "Volatile player UNDER: 60.0% HR",
    'high_usage_under': "High usage UNDER: 58.7% HR",
    'cold_snap': "Cold snap bounce-back",
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


def _confidence_angle(pick: Dict) -> str | None:
    """Generate confidence context angle."""
    confidence = pick.get('confidence_score')
    if not confidence:
        return None

    # Find closest matching tier
    conf_pct = int(round(confidence * 100))
    closest_tier = min(CONFIDENCE_HR_MAP.keys(), key=lambda t: abs(t - conf_pct))
    hr = CONFIDENCE_HR_MAP[closest_tier]

    return f"Confidence {confidence:.2f} ({hr:.1f}% HR at this tier)"


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

    # Special warning for 0.92 confidence tier
    confidence = pick.get('confidence_score')
    if confidence and 0.915 <= confidence <= 0.925:
        angles.append("Warning: 0.92 confidence tier has 47.5% HR — worst tier")

    return angles


def _high_conviction_angle(pick: Dict) -> str | None:
    """Generate high-conviction angle for edge >= 5 picks (Session 284)."""
    edge = abs(pick.get('edge') or 0)
    if edge < 5.0:
        return None
    return f"High conviction: edge {edge:.1f} pts (65.6% HR at edge 5+)"


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
) -> List[str]:
    """Build human-readable angles explaining why a pick was selected.

    Args:
        pick: Pick dict from aggregator (includes signal_tags, warning_tags, etc.)
        signal_results: List of SignalResult objects for this pick.
        cross_model_factors: Cross-model consensus factors for this pick.

    Returns:
        List of up to MAX_ANGLES angle strings, ordered by importance.
    """
    angles: List[str] = []

    # 1. Confidence context (always first if available)
    conf_angle = _confidence_angle(pick)
    if conf_angle:
        angles.append(conf_angle)

    # 2. High conviction edge (Session 284 — 65.6% HR cross-season)
    hc_angle = _high_conviction_angle(pick)
    if hc_angle:
        angles.append(hc_angle)

    # 3. Subset membership (Session 279 — high-value provenance)
    subset_angle = _subset_membership_angle(pick)
    if subset_angle:
        angles.append(subset_angle)

    # 4. Direction + player tier
    tier_angle = _direction_tier_angle(pick)
    if tier_angle:
        angles.append(tier_angle)

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

    return angles[:MAX_ANGLES]
