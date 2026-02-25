"""
Trends V3 Builder — Tier 1 Trend Detectors

Computes player performance trends from BigQuery game data for the
trends page feed. Returns trend items matching the V3 spec format.

Tier 1 detectors:
- scoring_streak: Consecutive games above a scoring threshold
- cold_snap: Below season avg in recent games
- breakout: Role player whose recent production is way above norm
- double_double_machine: Consistent double-double production
- shooting_hot: Shooting % significantly above season norm
- shooting_cold: Shooting % significantly below season norm

One trend per player max, sorted by intensity descending.
Target 20-30 trends with 70/30 tonight/other split.
"""

import logging
from typing import Dict, List, Any, Set

from google.cloud import bigquery

logger = logging.getLogger(__name__)

MAX_TRENDS = 30
MAX_PER_TYPE = 5
MIN_SEASON_GAMES = 15
TONIGHT_RATIO = 0.7


def build_trends(
    bq_client: bigquery.Client,
    game_date: str,
    tonight_teams: Set[str],
) -> List[Dict[str, Any]]:
    """
    Build the trends array for tonight.json.

    Args:
        bq_client: BigQuery client
        game_date: Target date (YYYY-MM-DD)
        tonight_teams: Set of team abbreviations playing tonight

    Returns:
        List of trend items matching the V3 spec
    """
    players = _query_player_data(bq_client, game_date)
    if not players:
        logger.warning(f"No player data found for trends on {game_date}")
        return []

    tonight_upper = {t.upper() for t in tonight_teams}
    logger.info(
        f"Building trends for {len(players)} players, "
        f"{len(tonight_upper)} teams playing tonight"
    )

    # Run all detectors
    all_candidates: List[Dict] = []
    detectors = [
        _detect_scoring_streaks,
        _detect_cold_snaps,
        _detect_breakouts,
        _detect_double_double_machines,
        _detect_shooting_hot,
        _detect_shooting_cold,
        _detect_bounce_backs,
    ]

    for detector in detectors:
        try:
            candidates = detector(players)
            all_candidates.extend(candidates)
        except Exception as e:
            logger.warning(f"Trend detector {detector.__name__} failed: {e}")

    logger.info(f"Found {len(all_candidates)} raw trend candidates")

    # Deduplicate: one per player, keep highest intensity
    deduped = _deduplicate(all_candidates)
    logger.info(f"After dedup: {len(deduped)} unique player trends")

    # Cap each type to MAX_PER_TYPE to prevent any single detector dominating
    capped = _cap_per_type(deduped)
    logger.info(f"After per-type cap ({MAX_PER_TYPE}): {len(capped)} trends")

    # Split tonight vs not-tonight, apply 70/30 ratio
    tonight = sorted(
        [t for t in capped if t['player']['team'] in tonight_upper],
        key=lambda x: x['intensity'],
        reverse=True,
    )
    other = sorted(
        [t for t in capped if t['player']['team'] not in tonight_upper],
        key=lambda x: x['intensity'],
        reverse=True,
    )

    tonight_slots = int(MAX_TRENDS * TONIGHT_RATIO)
    other_slots = MAX_TRENDS - min(len(tonight), tonight_slots)

    result = tonight[:tonight_slots] + other[:other_slots]
    result.sort(key=lambda x: x['intensity'], reverse=True)
    result = result[:MAX_TRENDS]

    # Interleave types so no two consecutive trends are the same type
    result = _interleave_types(result)

    # Validate before returning — strip any items with bad data
    result = _validate_trends(result)

    tonight_count = sum(1 for t in result if t['player']['team'] in tonight_upper)
    logger.info(
        f"Final trends: {len(result)} "
        f"({tonight_count} tonight, {len(result) - tonight_count} other)"
    )

    return result


# =============================================================================
# Data query
# =============================================================================

def _query_player_data(
    bq_client: bigquery.Client, game_date: str
) -> List[Dict]:
    """
    Query recent games + season averages for all qualifying players.

    Returns a list of player dicts, each with a 'games' list ordered
    most-recent-first (game_num 1 = latest).
    """
    query = """
    WITH season_stats AS (
        SELECT
            player_lookup,
            player_full_name,
            team_abbr,
            COUNT(*) as season_games,
            AVG(points) as season_ppg,
            AVG(offensive_rebounds + defensive_rebounds) as season_rpg,
            AVG(assists) as season_apg,
            SAFE_DIVIDE(
                SUM(IF(fg_attempts IS NOT NULL, fg_makes, NULL)),
                NULLIF(SUM(fg_attempts), 0)
            ) as season_fg_pct,
            SAFE_DIVIDE(
                SUM(IF(three_pt_attempts IS NOT NULL, three_pt_makes, NULL)),
                NULLIF(SUM(three_pt_attempts), 0)
            ) as season_3pt_pct,
            AVG(minutes_played) as season_mpg
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date >= DATE_SUB(@game_date, INTERVAL 180 DAY)
          AND game_date < @game_date
          AND minutes_played >= 10
          AND is_active = TRUE
        GROUP BY player_lookup, player_full_name, team_abbr
        HAVING COUNT(*) >= 15
    ),
    recent_games AS (
        SELECT
            g.player_lookup,
            g.game_date,
            g.points,
            g.offensive_rebounds + g.defensive_rebounds as rebounds,
            g.assists,
            g.fg_makes,
            g.fg_attempts,
            g.three_pt_makes,
            g.three_pt_attempts,
            g.minutes_played,
            ROW_NUMBER() OVER (
                PARTITION BY g.player_lookup ORDER BY g.game_date DESC
            ) as game_num
        FROM `nba-props-platform.nba_analytics.player_game_summary` g
        INNER JOIN season_stats s ON g.player_lookup = s.player_lookup
        WHERE g.game_date >= DATE_SUB(@game_date, INTERVAL 120 DAY)
          AND g.game_date < @game_date
          AND g.minutes_played >= 10
          AND g.is_active = TRUE
    ),
    registry AS (
        SELECT player_lookup, position
        FROM `nba-props-platform.nba_reference.nba_players_registry`
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup ORDER BY season DESC
        ) = 1
    )
    SELECT
        s.player_lookup,
        s.player_full_name,
        s.team_abbr,
        s.season_games,
        s.season_ppg,
        s.season_rpg,
        s.season_apg,
        s.season_fg_pct,
        s.season_3pt_pct,
        s.season_mpg,
        r.game_date,
        r.points,
        r.rebounds,
        r.assists,
        r.fg_makes,
        r.fg_attempts,
        r.three_pt_makes,
        r.three_pt_attempts,
        r.minutes_played,
        r.game_num,
        reg.position
    FROM season_stats s
    JOIN recent_games r ON s.player_lookup = r.player_lookup
    LEFT JOIN registry reg ON s.player_lookup = reg.player_lookup
    WHERE r.game_num <= 30
    ORDER BY s.player_lookup, r.game_num
    """

    params = [bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)]
    job_config = bigquery.QueryJobConfig(query_parameters=params)

    try:
        rows = bq_client.query(query, job_config=job_config).result(timeout=90)
    except Exception as e:
        logger.error(f"Trends player data query failed: {e}")
        return []

    # Group rows by player
    players_map: Dict[str, Dict] = {}
    for row in rows:
        lookup = row['player_lookup']
        if lookup not in players_map:
            players_map[lookup] = {
                'player_lookup': lookup,
                'player_name': row['player_full_name'] or lookup,
                'team': row['team_abbr'],
                'position': row.get('position') or '',
                'season_games': int(row['season_games']),
                'season_ppg': float(row['season_ppg'] or 0),
                'season_rpg': float(row['season_rpg'] or 0),
                'season_apg': float(row['season_apg'] or 0),
                'season_fg_pct': float(row['season_fg_pct'] or 0),
                'season_3pt_pct': float(row['season_3pt_pct'] or 0),
                'season_mpg': float(row['season_mpg'] or 0),
                'games': [],
            }
        players_map[lookup]['games'].append({
            'points': int(row['points'] or 0),
            'rebounds': int(row['rebounds'] or 0),
            'assists': int(row['assists'] or 0),
            'fg_makes': int(row['fg_makes'] or 0),
            'fg_attempts': int(row['fg_attempts'] or 0),
            'three_pt_makes': int(row['three_pt_makes'] or 0),
            'three_pt_attempts': int(row['three_pt_attempts'] or 0),
            'minutes': float(row['minutes_played'] or 0),
            'game_num': int(row['game_num']),
        })

    return list(players_map.values())


# =============================================================================
# Helpers
# =============================================================================

def _last_name(full_name: str) -> str:
    """Extract last name for headlines. Handles suffixes like Jr."""
    if not full_name:
        return ""
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name
    suffixes = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv'}
    if parts[-1].lower().rstrip('.') in suffixes and len(parts) > 2:
        return parts[-2]
    return parts[-1]


def _make_trend(
    player: Dict,
    trend_type: str,
    category: str,
    headline: str,
    detail: str,
    primary_value: float,
    primary_label: str,
    secondary_value: float,
    secondary_label: str,
    intensity: float,
) -> Dict[str, Any]:
    """Create a trend item matching the V3 spec."""
    return {
        'id': f"{trend_type.replace('_', '-')}-{player['player_lookup']}",
        'type': trend_type,
        'category': category,
        'player': {
            'lookup': player['player_lookup'],
            'name': player['player_name'],
            'team': player['team'],
            'position': player['position'],
        },
        'headline': headline,
        'detail': detail,
        'stats': {
            'primary_value': primary_value,
            'primary_label': primary_label,
            'secondary_value': secondary_value,
            'secondary_label': secondary_label,
        },
        'intensity': round(min(max(intensity, 0), 10), 1),
    }


def _deduplicate(candidates: List[Dict]) -> List[Dict]:
    """Keep only the highest-intensity trend per player."""
    best: Dict[str, Dict] = {}
    for trend in candidates:
        lookup = trend['player']['lookup']
        if lookup not in best or trend['intensity'] > best[lookup]['intensity']:
            best[lookup] = trend
    return list(best.values())


def _cap_per_type(trends: List[Dict], max_per_type: int = MAX_PER_TYPE) -> List[Dict]:
    """Cap each trend type to max_per_type items, keeping highest intensity."""
    by_type: Dict[str, List[Dict]] = {}
    for t in trends:
        by_type.setdefault(t['type'], []).append(t)

    result = []
    for type_trends in by_type.values():
        type_trends.sort(key=lambda x: x['intensity'], reverse=True)
        result.extend(type_trends[:max_per_type])
    return result


def _interleave_types(trends: List[Dict]) -> List[Dict]:
    """Reorder using round-robin across types for maximum diversity.

    Groups trends by type, orders type groups by their top intensity,
    then round-robins one from each type. Ensures each type appears
    once before any type repeats.
    """
    if len(trends) <= 1:
        return trends

    # Group by type, each group sorted by intensity desc
    by_type: Dict[str, List[Dict]] = {}
    for t in trends:
        by_type.setdefault(t['type'], []).append(t)
    for group in by_type.values():
        group.sort(key=lambda x: x['intensity'], reverse=True)

    # Order type groups by their top intensity
    type_order = sorted(
        by_type.keys(),
        key=lambda k: by_type[k][0]['intensity'],
        reverse=True,
    )

    # Round-robin: take one from each type in order, repeat
    result = []
    while any(by_type[t] for t in type_order):
        for t in type_order:
            if by_type[t]:
                result.append(by_type[t].pop(0))

    return result


VALID_TYPES = {
    'scoring_streak', 'cold_snap', 'breakout',
    'double_double_machine', 'shooting_hot', 'shooting_cold',
    'bounce_back',
}
VALID_CATEGORIES = {'hot', 'cold', 'interesting'}


def _validate_trends(trends: List[Dict]) -> List[Dict]:
    """Validate trend items and strip any with bad data.

    Catches data quality issues (impossible percentages, missing fields,
    out-of-range values) before they reach the frontend.
    """
    valid = []

    for t in trends:
        trend_id = t.get('id', '?')
        player_name = t.get('player', {}).get('name', '?')
        errors = []

        # Required fields
        if not t.get('type') or not t.get('headline') or not t.get('player', {}).get('lookup'):
            errors.append('missing required fields')

        # Type and category
        if t.get('type') not in VALID_TYPES:
            errors.append(f"invalid type: {t.get('type')}")
        if t.get('category') not in VALID_CATEGORIES:
            errors.append(f"invalid category: {t.get('category')}")

        # Intensity range
        intensity = t.get('intensity', 0)
        if not (0 <= intensity <= 10):
            errors.append(f"intensity {intensity} outside 0-10")

        # Shooting percentage sanity (stats.secondary_value is season %)
        stats = t.get('stats', {})
        if t.get('type') in ('shooting_hot', 'shooting_cold'):
            for key in ('primary_value', 'secondary_value'):
                val = stats.get(key)
                if val is not None and not (0 <= val <= 100):
                    errors.append(f"stats.{key}={val} outside 0-100%")

        # Headline length (mobile card limit)
        headline = t.get('headline', '')
        if len(headline) > 80:
            errors.append(f"headline too long ({len(headline)} chars)")

        if errors:
            logger.warning(
                f"Trend validation failed for {trend_id} ({player_name}): "
                f"{'; '.join(errors)} — stripping from output"
            )
        else:
            valid.append(t)

    stripped = len(trends) - len(valid)
    if stripped:
        logger.warning(f"Stripped {stripped} invalid trend(s) from output")

    return valid


# =============================================================================
# Tier 1 Detectors
# =============================================================================

def _detect_scoring_streaks(players: List[Dict]) -> List[Dict]:
    """
    Find players scoring above a threshold in consecutive games.

    Checks fixed thresholds (35, 30, 25, 20) first, then above-season-avg.
    Minimum streak: 4 games for fixed, 5 for above-avg.
    """
    trends = []
    thresholds = [(35, 8.0), (30, 6.5), (25, 5.0), (20, 3.5)]

    for p in players:
        games = p['games']
        if len(games) < 4:
            continue

        trend = None

        # Check fixed thresholds (highest first)
        # Skip thresholds trivially below the player's average
        for threshold, base_intensity in thresholds:
            if threshold < p['season_ppg'] - 5:
                continue

            streak = 0
            for g in games:
                if g['points'] >= threshold:
                    streak += 1
                else:
                    break

            if streak >= 4:
                avg = sum(g['points'] for g in games[:streak]) / streak
                intensity = base_intensity + (streak - 4) * 0.5
                trend = _make_trend(
                    player=p,
                    trend_type='scoring_streak',
                    category='hot',
                    headline=f"Scored {threshold}+ in {streak} straight",
                    detail=(
                        f"Averaging {avg:.1f} PPG in the streak, "
                        f"{p['season_ppg']:.1f} season avg"
                    ),
                    primary_value=streak,
                    primary_label='straight games',
                    secondary_value=round(avg, 1),
                    secondary_label='PPG in streak',
                    intensity=intensity,
                )
                break  # Use highest threshold met

        # Above season avg streak (fallback for notable players)
        if trend is None and p['season_ppg'] >= 15:
            streak = 0
            for g in games:
                if g['points'] > p['season_ppg']:
                    streak += 1
                else:
                    break

            if streak >= 5:
                avg = sum(g['points'] for g in games[:streak]) / streak
                pct_above = (avg - p['season_ppg']) / p['season_ppg']
                intensity = 3.0 + (streak - 5) * 0.4 + pct_above * 5
                trend = _make_trend(
                    player=p,
                    trend_type='scoring_streak',
                    category='hot',
                    headline=f"Scored above average in {streak} straight",
                    detail=(
                        f"Averaging {avg:.1f} PPG in the streak, "
                        f"{p['season_ppg']:.1f} season avg"
                    ),
                    primary_value=streak,
                    primary_label='straight games',
                    secondary_value=round(avg, 1),
                    secondary_label='PPG in streak',
                    intensity=intensity,
                )

        if trend:
            trends.append(trend)

    return trends


def _detect_cold_snaps(players: List[Dict]) -> List[Dict]:
    """
    Find players scoring below season average in recent games.

    Requires: below season avg in 5+ of last 7, with 15%+ drop.
    """
    trends = []

    for p in players:
        games = p['games']
        if len(games) < 7 or p['season_ppg'] < 12:
            continue

        last_7 = games[:7]
        below_count = sum(1 for g in last_7 if g['points'] < p['season_ppg'])

        if below_count < 5:
            continue

        recent_avg = sum(g['points'] for g in last_7) / 7
        drop_pct = (p['season_ppg'] - recent_avg) / p['season_ppg']

        if drop_pct < 0.15:
            continue

        # Use last-5 framing if those are consistently bad
        last_5 = games[:5]
        below_in_5 = sum(1 for g in last_5 if g['points'] < p['season_ppg'])

        if below_in_5 >= 4:
            stretch_avg = sum(g['points'] for g in last_5) / 5
            drop = p['season_ppg'] - stretch_avg
            headline = f"Averaging only {stretch_avg:.1f} PPG over last 5"
            detail = (
                f"Down {drop:.1f} pts per game, "
                f"{p['season_ppg']:.1f} season avg"
            )
            pv = round(stretch_avg, 1)
            pl = 'PPG last 5'
        else:
            drop = p['season_ppg'] - recent_avg
            headline = f"Averaging only {recent_avg:.1f} PPG over last 7"
            detail = (
                f"Down {drop:.1f} pts per game, "
                f"{p['season_ppg']:.1f} season avg"
            )
            pv = round(recent_avg, 1)
            pl = 'PPG last 7'

        intensity = 3.0 + drop_pct * 8 + (below_count - 5) * 0.5

        trends.append(_make_trend(
            player=p,
            trend_type='cold_snap',
            category='cold',
            headline=headline,
            detail=detail,
            primary_value=pv,
            primary_label=pl,
            secondary_value=round(p['season_ppg'], 1),
            secondary_label='season avg',
            intensity=intensity,
        ))

    return trends


def _detect_breakouts(players: List[Dict]) -> List[Dict]:
    """
    Find role players whose recent production is way above their norm.

    Requires: season avg < 20 PPG, last-7 avg 40%+ above season avg,
    minimum 12 PPG in the stretch.
    """
    trends = []

    for p in players:
        games = p['games']
        if len(games) < 7 or p['season_ppg'] >= 20 or p['season_ppg'] <= 0:
            continue

        last_7 = games[:7]
        recent_avg = sum(g['points'] for g in last_7) / 7

        if recent_avg < 12:
            continue

        increase_pct = (recent_avg - p['season_ppg']) / p['season_ppg']
        if increase_pct < 0.4:
            continue

        intensity = min(increase_pct * 10, 9.5)
        if recent_avg >= 20:
            intensity = min(intensity + 1, 10)

        trends.append(_make_trend(
            player=p,
            trend_type='breakout',
            category='hot',
            headline=f"Averaging {recent_avg:.1f} PPG over last 7",
            detail=(
                f"A {increase_pct:.0%} jump from his "
                f"{p['season_ppg']:.1f} season avg"
            ),
            primary_value=round(recent_avg, 1),
            primary_label='PPG last 7',
            secondary_value=round(p['season_ppg'], 1),
            secondary_label='season avg',
            intensity=intensity,
        ))

    return trends


def _detect_double_double_machines(players: List[Dict]) -> List[Dict]:
    """
    Find players hitting double-doubles consistently.

    Requires: 5+ DDs in last 7, or 7+ in last 10. Also checks DD streak.
    """
    trends = []

    for p in players:
        games = p['games']
        if len(games) < 7:
            continue

        def is_dd(g):
            cats = [g['points'], g['rebounds'], g['assists']]
            return sum(1 for c in cats if c >= 10) >= 2

        window = min(len(games), 10)
        recent = games[:window]
        dd_count = sum(1 for g in recent if is_dd(g))

        dd_in_7 = sum(1 for g in games[:7] if is_dd(g))

        if dd_in_7 < 5 and dd_count < 7:
            continue

        # Check consecutive DD streak
        dd_streak = 0
        for g in games:
            if is_dd(g):
                dd_streak += 1
            else:
                break

        if dd_streak >= 4:
            headline = f"Double-double in {dd_streak} straight"
            pv = dd_streak
            pl = 'straight double-doubles'
        else:
            headline = f"Double-double in {dd_count} of last {window}"
            pv = dd_count
            pl = f'of last {window}'

        pts_avg = sum(g['points'] for g in recent) / window
        reb_avg = sum(g['rebounds'] for g in recent) / window
        ast_avg = sum(g['assists'] for g in recent) / window

        intensity = 4.0 + (dd_count / window) * 4
        if dd_streak >= 4:
            intensity += dd_streak * 0.3

        trends.append(_make_trend(
            player=p,
            trend_type='double_double_machine',
            category='hot',
            headline=headline,
            detail=(
                f"Averaging {pts_avg:.1f} pts, {reb_avg:.1f} reb, "
                f"{ast_avg:.1f} ast over last {window}"
            ),
            primary_value=pv,
            primary_label=pl,
            secondary_value=round(pts_avg, 1),
            secondary_label=f'PPG last {window}',
            intensity=intensity,
        ))

    return trends


def _detect_shooting_hot(players: List[Dict]) -> List[Dict]:
    """
    Find players shooting significantly above their season norm.

    Requires: 10+ percentage point increase in 3PT% (min 20 attempts),
    or 8+ percentage point increase in FG% (min 40 attempts).
    """
    trends = []

    for p in players:
        games = p['games']
        if len(games) < 5 or p['season_mpg'] < 20:
            continue

        window = min(len(games), 7)
        recent = games[:window]

        total_3pm = sum(g['three_pt_makes'] for g in recent)
        total_3pa = sum(g['three_pt_attempts'] for g in recent)
        total_fgm = sum(g['fg_makes'] for g in recent)
        total_fga = sum(g['fg_attempts'] for g in recent)

        best_trend = None
        best_intensity = 0

        # 3PT% hot — need real volume (4+ attempts/game)
        if total_3pa >= 28 and p['season_3pt_pct'] > 0:
            recent_pct = total_3pm / total_3pa
            diff = recent_pct - p['season_3pt_pct']

            if diff >= 0.12:
                intensity = min(4.0 + diff * 20, 8.5)
                if intensity > best_intensity:
                    best_intensity = intensity
                    best_trend = _make_trend(
                        player=p,
                        trend_type='shooting_hot',
                        category='hot',
                        headline=(
                            f"Shooting {recent_pct:.0%} from 3 "
                            f"over last {window}"
                        ),
                        detail=f"Season avg is {p['season_3pt_pct']:.0%} from 3",
                        primary_value=round(recent_pct * 100, 1),
                        primary_label=f'3PT% last {window}',
                        secondary_value=round(p['season_3pt_pct'] * 100, 1),
                        secondary_label='season 3PT%',
                        intensity=intensity,
                    )

        # FG% hot
        if total_fga >= 50 and p['season_fg_pct'] > 0:
            recent_pct = total_fgm / total_fga
            diff = recent_pct - p['season_fg_pct']

            if diff >= 0.08:
                intensity = min(3.5 + diff * 20, 8.0)
                if intensity > best_intensity:
                    best_trend = _make_trend(
                        player=p,
                        trend_type='shooting_hot',
                        category='hot',
                        headline=(
                            f"Shooting {recent_pct:.0%} from the field "
                            f"over last {window}"
                        ),
                        detail=f"Season avg is {p['season_fg_pct']:.0%} from the field",
                        primary_value=round(recent_pct * 100, 1),
                        primary_label=f'FG% last {window}',
                        secondary_value=round(p['season_fg_pct'] * 100, 1),
                        secondary_label='season FG%',
                        intensity=intensity,
                    )

        if best_trend:
            trends.append(best_trend)

    return trends


def _detect_shooting_cold(players: List[Dict]) -> List[Dict]:
    """
    Find players shooting significantly below their season norm.

    Requires: 10+ percentage point drop in 3PT% (min 20 attempts, season > 25%),
    or 8+ percentage point drop in FG% (min 40 attempts, season > 35%).
    """
    trends = []

    for p in players:
        games = p['games']
        if len(games) < 5 or p['season_mpg'] < 20:
            continue

        window = min(len(games), 7)
        recent = games[:window]

        total_3pm = sum(g['three_pt_makes'] for g in recent)
        total_3pa = sum(g['three_pt_attempts'] for g in recent)
        total_fgm = sum(g['fg_makes'] for g in recent)
        total_fga = sum(g['fg_attempts'] for g in recent)

        best_trend = None
        best_intensity = 0

        # 3PT% cold — need real volume (4+ attempts/game)
        if total_3pa >= 28 and p['season_3pt_pct'] > 0.30:
            recent_pct = total_3pm / total_3pa
            diff = p['season_3pt_pct'] - recent_pct

            if diff >= 0.12:
                intensity = min(4.0 + diff * 20, 8.5)
                if intensity > best_intensity:
                    best_intensity = intensity
                    best_trend = _make_trend(
                        player=p,
                        trend_type='shooting_cold',
                        category='cold',
                        headline=(
                            f"Shooting only {recent_pct:.0%} from 3 "
                            f"over last {window}"
                        ),
                        detail=f"Season avg is {p['season_3pt_pct']:.0%} from 3",
                        primary_value=round(recent_pct * 100, 1),
                        primary_label=f'3PT% last {window}',
                        secondary_value=round(p['season_3pt_pct'] * 100, 1),
                        secondary_label='season 3PT%',
                        intensity=intensity,
                    )

        # FG% cold
        if total_fga >= 50 and p['season_fg_pct'] > 0.40:
            recent_pct = total_fgm / total_fga
            diff = p['season_fg_pct'] - recent_pct

            if diff >= 0.08:
                intensity = min(3.5 + diff * 20, 8.0)
                if intensity > best_intensity:
                    best_trend = _make_trend(
                        player=p,
                        trend_type='shooting_cold',
                        category='cold',
                        headline=(
                            f"Shooting only {recent_pct:.0%} from the field "
                            f"over last {window}"
                        ),
                        detail=f"Season avg is {p['season_fg_pct']:.0%} from the field",
                        primary_value=round(recent_pct * 100, 1),
                        primary_label=f'FG% last {window}',
                        secondary_value=round(p['season_fg_pct'] * 100, 1),
                        secondary_label='season FG%',
                        intensity=intensity,
                    )

        if best_trend:
            trends.append(best_trend)

    return trends


def _detect_bounce_backs(players: List[Dict]) -> List[Dict]:
    """
    Find players who had a bad last game and historically bounce back.

    Requires: last game 10+ points below season avg, 20+ minutes played
    (low-minute games from injury/foul trouble aren't real cold games).
    Computes bounce-back rate from the player's other recent games.
    """
    SHORTFALL_THRESHOLD = 10
    MIN_SAMPLE = 3

    trends = []

    for p in players:
        games = p['games']
        if len(games) < 5 or p['season_ppg'] < 12:
            continue

        last_game = games[0]

        # Filter: must have played real minutes
        if last_game['minutes'] < 20:
            continue

        shortfall = p['season_ppg'] - last_game['points']
        if shortfall < SHORTFALL_THRESHOLD:
            continue

        # Compute bounce-back rate from remaining games
        bad_followed = 0
        bounced = 0
        for i in range(1, len(games) - 1):
            prev = games[i]
            if prev['minutes'] < 20:
                continue
            if p['season_ppg'] - prev['points'] >= SHORTFALL_THRESHOLD:
                bad_followed += 1
                # Next game after this bad one is games[i-1] (more recent)
                if games[i - 1]['points'] >= p['season_ppg']:
                    bounced += 1

        if bad_followed < MIN_SAMPLE:
            continue

        bb_rate = bounced / bad_followed

        pts = last_game['points']
        fgm = last_game['fg_makes']
        fga = last_game['fg_attempts']
        mins = int(last_game['minutes'])

        headline = f"Scored {pts} on {fgm}-{fga} shooting last game"
        detail = (
            f"Played {mins} min, bounces back {bb_rate:.0%}, "
            f"{p['season_ppg']:.1f} season avg"
        )

        intensity = 3.0 + bb_rate * 4 + min(shortfall / 10, 2.0)
        if bb_rate >= 0.75 and bad_followed >= 8:
            intensity += 1.0

        trends.append(_make_trend(
            player=p,
            trend_type='bounce_back',
            category='interesting',
            headline=headline,
            detail=detail,
            primary_value=round(bb_rate * 100),
            primary_label='bounce-back %',
            secondary_value=round(shortfall, 1),
            secondary_label='pts below avg',
            intensity=intensity,
        ))

    return trends
