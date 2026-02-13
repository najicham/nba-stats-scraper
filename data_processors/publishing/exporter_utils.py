"""
Exporter Utilities for Phase 6 Publishing

Common utility functions shared across all exporters.
Eliminates duplication of ~60% across 30 exporter files.

Usage:
    from data_processors.publishing.exporter_utils import (
        safe_float, safe_int, format_float_dict, format_percentage
    )

    # In exporter code:
    value = safe_float(row.get('points'), default=0.0)
    pct = format_percentage(row.get('hit_rate'))
"""

from typing import Any, Optional, Dict, List, Union
from datetime import datetime, timezone


def safe_float(value: Any, default: Optional[float] = None, precision: int = 2) -> Optional[float]:
    """
    Safely convert value to float, handling None, NaN, and invalid values.

    Args:
        value: Value to convert (can be number, string, or None)
        default: Default value if conversion fails (default: None)
        precision: Decimal places to round to (default: 2)

    Returns:
        Float value rounded to precision, or default if conversion fails

    Examples:
        >>> safe_float(3.14159)
        3.14
        >>> safe_float("2.5")
        2.5
        >>> safe_float(None)
        None
        >>> safe_float(None, default=0.0)
        0.0
        >>> safe_float(float('nan'))
        None
    """
    if value is None:
        return default
    try:
        f = float(value)
        # NaN check (NaN != NaN is True)
        if f != f:
            return default
        return round(f, precision)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """
    Safely convert value to int, handling None and invalid values.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Integer value or default
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_odds(value: Any) -> Optional[int]:
    """
    Safely convert odds value to int, handling None and invalid values.

    Validates American odds format (must be outside [-100, 100] range).

    Args:
        value: Odds value to convert

    Returns:
        Integer odds value or None if invalid

    Examples:
        >>> safe_odds(-110)
        -110
        >>> safe_odds(150)
        150
        >>> safe_odds(0)
        None
        >>> safe_odds(-50)
        None
    """
    if value is None:
        return None
    try:
        odds_int = int(value)
        # American odds must be outside [-100, 100] range
        if -100 < odds_int < 100:
            return None
        return odds_int
    except (TypeError, ValueError):
        return None


def format_float_dict(data: Dict[str, Any], keys: List[str], precision: int = 2) -> Dict[str, Any]:
    """
    Format specific keys in a dictionary as floats.

    Args:
        data: Dictionary with values to format
        keys: List of keys to convert to floats
        precision: Decimal places for rounding

    Returns:
        New dictionary with specified keys as floats

    Example:
        >>> format_float_dict({'points': '25.123', 'name': 'LeBron'}, ['points'])
        {'points': 25.12, 'name': 'LeBron'}
    """
    result = data.copy()
    for key in keys:
        if key in result:
            result[key] = safe_float(result[key], precision=precision)
    return result


def format_percentage(
    value: Any,
    default: Optional[float] = None,
    as_decimal: bool = True
) -> Optional[float]:
    """
    Format value as percentage.

    Args:
        value: Value to format (0.75 or 75)
        default: Default if conversion fails
        as_decimal: If True, returns 0.75; if False, returns 75.0

    Returns:
        Percentage as decimal (0.75) or whole number (75.0)
    """
    f = safe_float(value)
    if f is None:
        return default

    # Detect if already in decimal form (< 1) or percentage form (> 1)
    if as_decimal:
        return f if f <= 1 else round(f / 100, 4)
    else:
        return round(f * 100, 2) if f <= 1 else round(f, 2)


def get_generated_at() -> str:
    """
    Get current UTC timestamp in ISO format.

    Returns:
        ISO format timestamp string
    """
    return datetime.now(timezone.utc).isoformat()


def create_empty_response(
    game_date: str,
    extra_fields: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a standard empty response for when no data is available.

    Args:
        game_date: Date string for the response
        extra_fields: Additional fields to include

    Returns:
        Standard empty response dictionary
    """
    response = {
        'game_date': game_date,
        'generated_at': get_generated_at(),
        'total_count': 0,
    }
    if extra_fields:
        response.update(extra_fields)
    return response


def truncate_string(s: str, max_length: int = 50, suffix: str = '...') -> str:
    """
    Truncate string at word boundary.

    Args:
        s: String to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated

    Returns:
        Truncated string
    """
    if not s or len(s) <= max_length:
        return s or ''

    truncated = s[:max_length - len(suffix)]
    last_space = truncated.rfind(' ')

    if last_space > max_length * 0.6:  # Only break at space if reasonable
        truncated = truncated[:last_space]

    return truncated + suffix


def format_timestamp(ts: Any) -> Optional[str]:
    """
    Format timestamp to ISO string.

    Args:
        ts: Timestamp (datetime, date, or string)

    Returns:
        ISO format string or None
    """
    if ts is None:
        return None
    if hasattr(ts, 'isoformat'):
        return ts.isoformat()
    return str(ts)


def compute_display_confidence(
    predicted: Any,
    line: Any,
    model_confidence: Any,
    recommendation: Optional[str] = None
) -> Optional[float]:
    """
    Compute a meaningful 0-100 confidence score for frontend display.

    The model's internal confidence (75 + quality + consistency = 79-95) has only
    4 unique values and doesn't incorporate edge size. This function produces a
    wider range that reflects both model quality and prediction edge.

    Components:
    - Edge size (0-50): Primary driver. Larger edge = higher confidence.
    - Model quality (0-30): Data quality and player consistency from model.
    - Base (15): Minimum for having a valid prediction.

    PASS picks are capped at 40 to avoid contradicting the recommendation.

    Args:
        predicted: Predicted points value
        line: Betting line value
        model_confidence: Model's internal confidence score (79-95 range)
        recommendation: OVER, UNDER, PASS, or NO_LINE

    Returns:
        Display confidence 5-98, or None if inputs are invalid
    """
    pred_f = safe_float(predicted)
    line_f = safe_float(line)
    conf_f = safe_float(model_confidence)

    if pred_f is None or line_f is None:
        # No line available - return low confidence from model quality alone
        if conf_f is not None:
            quality = max(0, min(30, (conf_f - 75) * 1.5))
            return max(5, min(50, round(15 + quality)))
        return None

    edge = abs(pred_f - line_f)

    # Edge component: primary driver (0-50 range)
    # 0 edge → 0, 2 edge → 14, 3 edge → 21, 5 edge → 35, 7+ edge → 50
    edge_component = min(50, edge * 7)

    # Model quality component (0-30 range)
    # Normalize model's 79-95 range to 0-30
    quality_component = 0
    if conf_f is not None:
        quality_component = max(0, min(30, (conf_f - 75) * 1.5))

    confidence = 15 + edge_component + quality_component

    # PASS picks: cap at 40 so they don't contradict the recommendation
    if recommendation == 'PASS':
        confidence = min(confidence, 40)

    return max(5, min(98, round(confidence)))


def calculate_edge(predicted: Any, line: Any) -> Optional[float]:
    """
    Calculate prediction edge (predicted - line).

    Args:
        predicted: Predicted value
        line: Line value

    Returns:
        Edge value rounded to 1 decimal, or None
    """
    pred_f = safe_float(predicted)
    line_f = safe_float(line)
    if pred_f is not None and line_f is not None:
        return round(pred_f - line_f, 1)
    return None


def compute_win_rate(wins: int, total: int, min_sample: int = 1) -> Optional[float]:
    """
    Compute win rate as decimal with minimum sample check.

    Args:
        wins: Number of wins
        total: Total attempts
        min_sample: Minimum sample size required

    Returns:
        Win rate as decimal (0.0 to 1.0) or None
    """
    if total < min_sample:
        return None
    return round(wins / total, 4)


def group_by_key(items: List[Dict], key: str) -> Dict[str, List[Dict]]:
    """
    Group a list of dictionaries by a key.

    Args:
        items: List of dictionaries
        key: Key to group by

    Returns:
        Dictionary mapping key values to lists of items
    """
    from collections import defaultdict
    result = defaultdict(list)
    for item in items:
        result[item.get(key)].append(item)
    return dict(result)


# Export categories and impact levels (shared constants)
CATEGORY_IMPACT = {
    'injury': 'high',
    'trade': 'high',
    'suspension': 'high',
    'signing': 'medium',
    'lineup': 'medium',
    'performance': 'low',
    'preview': 'low',
    'recap': 'low',
    'analysis': 'low',
    'other': 'low',
}

CRITICAL_CATEGORIES = {'injury', 'trade', 'suspension'}

# Common cache control settings
CACHE_SHORT = 'public, max-age=60'      # 1 minute - live data
CACHE_MEDIUM = 'public, max-age=300'    # 5 minutes - frequently updated
CACHE_LONG = 'public, max-age=3600'     # 1 hour - stable data
CACHE_STATIC = 'public, max-age=86400'  # 24 hours - historical data
