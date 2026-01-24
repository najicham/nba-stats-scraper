"""
Player Season Exporter for Player Modal

Exports season-level aggregates and patterns for a specific player.
Used for the season view in the Player Modal.

Endpoint: GET /v1/player/{player_lookup}/season/{season}
Refresh: Daily or on-demand

Frontend fields (SeasonDataResponse):
- player_profile: position, shot_profile, archetype
- averages: ppg, rpg, apg, shooting splits
- current_form: heat_score, temperature, streak
- key_patterns: rest_sensitive, home_performer, etc.
- prop_hit_rates: points, rebounds, assists
- game_log: full season with results
- splits: home/away, rest, by month
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float

logger = logging.getLogger(__name__)


# Player tier thresholds (consistent with results_exporter)
PLAYER_TIER_THRESHOLDS = {
    'elite': 25.0,      # 25+ PPG
    'starter': 15.0,    # 15-25 PPG
}


def get_player_tier(ppg: Optional[float]) -> str:
    """Classify player tier based on PPG."""
    if ppg is None:
        return 'role_player'
    if ppg >= PLAYER_TIER_THRESHOLDS['elite']:
        return 'elite'
    elif ppg >= PLAYER_TIER_THRESHOLDS['starter']:
        return 'starter'
    return 'role_player'


class PlayerSeasonExporter(BaseExporter):
    """
    Export season-level stats and patterns for Player Modal.

    JSON structure:
    {
        "player_lookup": "stephencurry",
        "player_full_name": "Stephen Curry",
        "season": "2024-25",
        "generated_at": "...",
        "player_profile": {
            "position": "PG",
            "team_abbr": "GSW",
            "player_tier": "elite",
            "shot_profile": "perimeter"
        },
        "averages": {
            "ppg": 26.5,
            "rpg": 4.8,
            "apg": 6.2,
            "fg_pct": 0.472,
            "three_pct": 0.412,
            "ft_pct": 0.925,
            "minutes": 32.1
        },
        "current_form": {
            "heat_score": 7.8,
            "temperature": "warm",
            "current_streak": 3,
            "streak_direction": "over",
            "l5_avg": 28.2,
            "l10_avg": 27.1
        },
        "key_patterns": [
            {"pattern": "rest_sensitive", "description": "+4.2 PPG on 2+ days rest", "strength": "strong"},
            {"pattern": "home_performer", "description": "+2.8 PPG at home", "strength": "moderate"}
        ],
        "prop_hit_rates": {
            "points": {"games": 45, "overs": 28, "rate": 0.622},
            "total_recommendations": 42,
            "win_rate": 0.714
        },
        "game_log": [...],
        "splits": {
            "home": {"games": 22, "ppg": 28.1, "over_rate": 0.68},
            "away": {"games": 23, "ppg": 25.0, "over_rate": 0.56},
            "rested": {"games": 15, "ppg": 29.2, "over_rate": 0.73},
            "back_to_back": {"games": 8, "ppg": 23.5, "over_rate": 0.50}
        },
        "monthly": [
            {"month": "Oct", "games": 8, "ppg": 24.5},
            {"month": "Nov", "games": 15, "ppg": 26.8}
        ]
    }
    """

    def generate_json(self, player_lookup: str, season: str = None) -> Dict[str, Any]:
        """
        Generate season data JSON for a specific player.

        Args:
            player_lookup: Player identifier (e.g., 'stephencurry')
            season: Season string (e.g., '2024-25'), defaults to current

        Returns:
            Dictionary ready for JSON serialization
        """
        # Determine season year
        if season is None:
            today = date.today()
            season_year = today.year if today.month >= 10 else today.year - 1
            season = f"{season_year}-{str(season_year + 1)[-2:]}"
        else:
            season_year = int(season.split('-')[0])

        logger.info(f"Generating season data for {player_lookup} season {season}")

        # Get player profile
        profile = self._query_player_profile(player_lookup, season_year)
        if not profile:
            return self._empty_response(player_lookup, season, "Player not found")

        # Get season averages
        averages = self._query_season_averages(player_lookup, season_year)

        # Get current form (heat score, streak)
        current_form = self._query_current_form(player_lookup, season_year)

        # Get key patterns
        patterns = self._query_key_patterns(player_lookup, season_year)

        # Get prop hit rates
        hit_rates = self._query_prop_hit_rates(player_lookup, season_year)

        # Get full game log
        game_log = self._query_game_log(player_lookup, season_year)

        # Get splits
        splits = self._query_splits(player_lookup, season_year)

        # Get monthly breakdown
        monthly = self._query_monthly(player_lookup, season_year)

        # Add player tier based on PPG
        player_tier = get_player_tier(averages.get('ppg'))

        return {
            'player_lookup': player_lookup,
            'player_full_name': profile.get('player_name', player_lookup),
            'season': season,
            'generated_at': self.get_generated_at(),
            'player_profile': {
                'position': profile.get('position'),
                'team_abbr': profile.get('team_abbr'),
                'player_tier': player_tier,
                'shot_profile': profile.get('shot_profile', 'balanced'),
            },
            'averages': averages,
            'current_form': current_form,
            'key_patterns': patterns,
            'prop_hit_rates': hit_rates,
            'game_log': game_log,
            'splits': splits,
            'monthly': monthly,
        }

    def _query_player_profile(self, player_lookup: str, season_year: int) -> Optional[Dict]:
        """Query player profile info."""
        query = """
        WITH player_info AS (
            SELECT
                player_lookup,
                player_name,
                position,
                team_abbr
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            WHERE player_lookup = @player_lookup
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        shot_zones AS (
            SELECT
                player_lookup,
                paint_rate_last_10 as pct_paint,
                mid_range_rate_last_10 as pct_mid_range,
                three_pt_rate_last_10 as pct_three
            FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
            WHERE player_lookup = @player_lookup
            ORDER BY analysis_date DESC
            LIMIT 1
        )
        SELECT
            pi.*,
            sz.pct_paint,
            sz.pct_mid_range,
            sz.pct_three
        FROM player_info pi
        LEFT JOIN shot_zones sz ON pi.player_lookup = sz.player_lookup
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
        ]

        results = self.query_to_list(query, params)
        if not results:
            return None

        r = results[0]

        # Classify shot profile
        shot_profile = 'balanced'
        paint = safe_float(r.get('pct_paint'))
        three = safe_float(r.get('pct_three'))
        mid = safe_float(r.get('pct_mid_range'))

        if paint and paint >= 0.50:
            shot_profile = 'interior'
        elif three and three >= 0.50:
            shot_profile = 'perimeter'
        elif mid and mid >= 0.30:
            shot_profile = 'mid_range'

        return {
            'player_name': r['player_name'],
            'position': r.get('position'),
            'team_abbr': r.get('team_abbr'),
            'shot_profile': shot_profile,
        }

    def _query_season_averages(self, player_lookup: str, season_year: int) -> Dict[str, Any]:
        """Query season averages."""
        query = """
        SELECT
            COUNT(*) as games,
            ROUND(AVG(pgs.points), 1) as ppg,
            ROUND(AVG(pgs.offensive_rebounds + pgs.defensive_rebounds), 1) as rpg,
            ROUND(AVG(pgs.assists), 1) as apg,
            ROUND(AVG(pgs.steals), 1) as spg,
            ROUND(AVG(pgs.blocks), 1) as bpg,
            ROUND(AVG(pgs.turnovers), 1) as topg,
            ROUND(SUM(pgs.fg_makes) / NULLIF(SUM(pgs.fg_attempts), 0), 3) as fg_pct,
            ROUND(SUM(pgs.three_pt_makes) / NULLIF(SUM(pgs.three_pt_attempts), 0), 3) as three_pct,
            ROUND(SUM(pgs.ft_makes) / NULLIF(SUM(pgs.ft_attempts), 0), 3) as ft_pct,
            ROUND(AVG(COALESCE(pgs.minutes_played, gps.minutes_decimal)), 1) as minutes
        FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
        LEFT JOIN `nba-props-platform.nba_raw.nbac_gamebook_player_stats` gps
            ON pgs.player_lookup = gps.player_lookup AND pgs.game_id = gps.game_id
        WHERE pgs.player_lookup = @player_lookup
          AND pgs.season_year = @season_year
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)
        if not results or results[0]['games'] == 0:
            return {}

        r = results[0]
        return {
            'games': r['games'],
            'ppg': safe_float(r.get('ppg')),
            'rpg': safe_float(r.get('rpg')),
            'apg': safe_float(r.get('apg')),
            'spg': safe_float(r.get('spg')),
            'bpg': safe_float(r.get('bpg')),
            'topg': safe_float(r.get('topg')),
            'fg_pct': safe_float(r.get('fg_pct')),
            'three_pct': safe_float(r.get('three_pct')),
            'ft_pct': safe_float(r.get('ft_pct')),
            'minutes': safe_float(r.get('minutes')),
        }

    def _query_current_form(self, player_lookup: str, season_year: int) -> Dict[str, Any]:
        """Query current form (heat score, streak, L5/L10)."""
        query = """
        WITH recent_games AS (
            SELECT
                game_date,
                points,
                points_line,
                over_under_result,
                ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_num
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND season_year = @season_year
        ),
        first_result AS (
            SELECT over_under_result as first_result FROM recent_games WHERE game_num = 1
        ),
        streak_break AS (
            SELECT MIN(game_num) as break_at
            FROM recent_games r, first_result f
            WHERE r.over_under_result != f.first_result
        ),
        stats AS (
            SELECT
                AVG(CASE WHEN game_num <= 5 THEN points END) as l5_avg,
                AVG(CASE WHEN game_num <= 10 THEN points END) as l10_avg,
                AVG(points) as season_avg,
                SUM(CASE WHEN game_num <= 10 AND over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs_l10,
                COUNT(CASE WHEN game_num <= 10 THEN 1 END) as games_l10
            FROM recent_games
        )
        SELECT
            s.l5_avg,
            s.l10_avg,
            s.season_avg,
            s.overs_l10,
            s.games_l10,
            f.first_result,
            COALESCE(sb.break_at - 1, s.games_l10) as streak_length
        FROM stats s, first_result f
        LEFT JOIN streak_break sb ON TRUE
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)
        if not results:
            return {}

        r = results[0]

        # Calculate heat score (0-10)
        # 50% hit rate + 25% streak + 25% margin
        hit_rate = r['overs_l10'] / r['games_l10'] if r.get('games_l10', 0) > 0 else 0.5
        streak_factor = min(r.get('streak_length', 0) / 10, 1.0)
        l5 = safe_float(r.get('l5_avg')) or 0
        season = safe_float(r.get('season_avg')) or 1
        margin_factor = min(max((l5 - season + 10) / 20, 0), 1) if season > 0 else 0.5

        heat_score = round(10 * (0.5 * hit_rate + 0.25 * streak_factor + 0.25 * margin_factor), 1)

        # Determine temperature
        if heat_score >= 8.0:
            temperature = 'hot'
        elif heat_score >= 6.5:
            temperature = 'warm'
        elif heat_score >= 4.5:
            temperature = 'neutral'
        elif heat_score >= 3.0:
            temperature = 'cool'
        else:
            temperature = 'cold'

        return {
            'heat_score': heat_score,
            'temperature': temperature,
            'current_streak': r.get('streak_length', 0),
            'streak_direction': r.get('first_result', '').lower() if r.get('first_result') else None,
            'l5_avg': safe_float(r.get('l5_avg')),
            'l10_avg': safe_float(r.get('l10_avg')),
            'hit_rate_l10': round(hit_rate, 2) if r.get('games_l10', 0) > 0 else None,
        }

    def _query_key_patterns(self, player_lookup: str, season_year: int) -> List[Dict]:
        """Query key patterns (rest sensitive, home performer, etc.)."""
        query = """
        WITH games AS (
            SELECT
                g.points,
                CASE WHEN g.team_abbr = SUBSTR(g.game_id, 14, 3) THEN TRUE ELSE FALSE END as is_home,
                LAG(g.game_date) OVER (ORDER BY g.game_date) as prev_game_date,
                DATE_DIFF(g.game_date, LAG(g.game_date) OVER (ORDER BY g.game_date), DAY) as days_rest
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.player_lookup = @player_lookup
              AND g.season_year = @season_year
        ),
        splits AS (
            SELECT
                AVG(points) as overall_avg,
                AVG(CASE WHEN is_home THEN points END) as home_avg,
                AVG(CASE WHEN NOT is_home THEN points END) as away_avg,
                AVG(CASE WHEN days_rest >= 2 THEN points END) as rested_avg,
                AVG(CASE WHEN days_rest = 1 THEN points END) as b2b_avg,
                COUNT(CASE WHEN is_home THEN 1 END) as home_games,
                COUNT(CASE WHEN NOT is_home THEN 1 END) as away_games,
                COUNT(CASE WHEN days_rest >= 2 THEN 1 END) as rested_games,
                COUNT(CASE WHEN days_rest = 1 THEN 1 END) as b2b_games
            FROM games
        )
        SELECT * FROM splits
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)
        if not results:
            return []

        r = results[0]
        patterns = []
        overall = safe_float(r.get('overall_avg')) or 0

        # Rest sensitivity (threshold: 2.5+ PPG diff, strong if 4+)
        rested = safe_float(r.get('rested_avg'))
        b2b = safe_float(r.get('b2b_avg'))
        if rested and b2b and overall > 0:
            rest_diff = rested - b2b
            if rest_diff >= 2.5:
                patterns.append({
                    'pattern': 'rest_sensitive',
                    'description': f"+{rest_diff:.1f} PPG on 2+ days rest",
                    'strength': 'strong' if rest_diff >= 4 else 'moderate'
                })
            elif rest_diff <= -2.5:
                # Reverse rest sensitivity - plays better on B2B
                patterns.append({
                    'pattern': 'b2b_performer',
                    'description': f"+{-rest_diff:.1f} PPG on back-to-backs",
                    'strength': 'strong' if rest_diff <= -4 else 'moderate'
                })

        # Home performer (threshold: 2.5+ PPG diff, strong if 4+)
        home = safe_float(r.get('home_avg'))
        away = safe_float(r.get('away_avg'))
        if home and away and overall > 0:
            home_diff = home - away
            if home_diff >= 2.5:
                patterns.append({
                    'pattern': 'home_performer',
                    'description': f"+{home_diff:.1f} PPG at home",
                    'strength': 'strong' if home_diff >= 4 else 'moderate'
                })
            elif home_diff <= -2.5:
                patterns.append({
                    'pattern': 'road_warrior',
                    'description': f"+{-home_diff:.1f} PPG on road",
                    'strength': 'strong' if home_diff <= -4 else 'moderate'
                })

        return patterns[:4]  # Max 4 patterns

    def _query_prop_hit_rates(self, player_lookup: str, season_year: int) -> Dict[str, Any]:
        """Query prop hit rates from predictions."""
        query = """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN recommendation IN ('OVER', 'UNDER') THEN 1 ELSE 0 END) as recommendations,
            SUM(CASE WHEN prediction_correct = TRUE THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END) as overs,
            SUM(CASE WHEN actual_points < line_value THEN 1 ELSE 0 END) as unders
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE player_lookup = @player_lookup
          AND system_id = 'catboost_v8'
          AND EXTRACT(YEAR FROM game_date) >= @season_year
          AND (EXTRACT(MONTH FROM game_date) >= 10 OR EXTRACT(YEAR FROM game_date) > @season_year)
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)
        if not results or results[0]['total'] == 0:
            return {}

        r = results[0]
        total_games = r['overs'] + r['unders']
        return {
            'points': {
                'games': total_games,
                'overs': r['overs'],
                'unders': r['unders'],
                'over_rate': round(r['overs'] / total_games, 3) if total_games > 0 else None,
            },
            'total_recommendations': r['recommendations'],
            'correct': r['correct'],
            'win_rate': round(r['correct'] / r['recommendations'], 3) if r['recommendations'] > 0 else None,
        }

    def _query_game_log(self, player_lookup: str, season_year: int) -> List[Dict]:
        """Query full game log for the season."""
        query = """
        SELECT
            pgs.game_date,
            pgs.opponent_team_abbr as opponent,
            CASE WHEN pgs.team_abbr = SUBSTR(pgs.game_id, 14, 3) THEN TRUE ELSE FALSE END as is_home,
            pgs.points,
            pgs.offensive_rebounds + pgs.defensive_rebounds as rebounds,
            pgs.assists,
            COALESCE(pgs.minutes_played, gps.minutes_decimal) as minutes_played,
            pgs.points_line as line,
            pgs.over_under_result as result,
            pgs.win_flag as team_won
        FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
        LEFT JOIN `nba-props-platform.nba_raw.nbac_gamebook_player_stats` gps
            ON pgs.player_lookup = gps.player_lookup AND pgs.game_id = gps.game_id
        WHERE pgs.player_lookup = @player_lookup
          AND pgs.season_year = @season_year
        ORDER BY pgs.game_date DESC
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)
        return [
            {
                'date': str(r['game_date']),
                'opponent': r['opponent'],
                'is_home': r['is_home'],
                'points': r['points'],
                'rebounds': r['rebounds'],
                'assists': r['assists'],
                'minutes': safe_float(r.get('minutes_played')),
                'line': safe_float(r.get('line')),
                'result': r.get('result'),
                'team_won': r.get('team_won'),
            }
            for r in results
        ]

    def _query_splits(self, player_lookup: str, season_year: int) -> Dict[str, Any]:
        """Query performance splits."""
        query = """
        WITH games AS (
            SELECT
                g.points,
                g.over_under_result,
                CASE WHEN g.team_abbr = SUBSTR(g.game_id, 14, 3) THEN TRUE ELSE FALSE END as is_home,
                DATE_DIFF(g.game_date, LAG(g.game_date) OVER (ORDER BY g.game_date), DAY) as days_rest
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.player_lookup = @player_lookup
              AND g.season_year = @season_year
        )
        SELECT
            'home' as split_type,
            COUNT(*) as games,
            ROUND(AVG(points), 1) as ppg,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 1.0 /
                  NULLIF(SUM(CASE WHEN over_under_result IN ('OVER', 'UNDER') THEN 1 ELSE 0 END), 0), 2) as over_rate
        FROM games WHERE is_home
        UNION ALL
        SELECT
            'away' as split_type,
            COUNT(*) as games,
            ROUND(AVG(points), 1) as ppg,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 1.0 /
                  NULLIF(SUM(CASE WHEN over_under_result IN ('OVER', 'UNDER') THEN 1 ELSE 0 END), 0), 2) as over_rate
        FROM games WHERE NOT is_home
        UNION ALL
        SELECT
            'rested' as split_type,
            COUNT(*) as games,
            ROUND(AVG(points), 1) as ppg,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 1.0 /
                  NULLIF(SUM(CASE WHEN over_under_result IN ('OVER', 'UNDER') THEN 1 ELSE 0 END), 0), 2) as over_rate
        FROM games WHERE days_rest >= 2
        UNION ALL
        SELECT
            'back_to_back' as split_type,
            COUNT(*) as games,
            ROUND(AVG(points), 1) as ppg,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 1.0 /
                  NULLIF(SUM(CASE WHEN over_under_result IN ('OVER', 'UNDER') THEN 1 ELSE 0 END), 0), 2) as over_rate
        FROM games WHERE days_rest = 1
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)

        splits = {}
        for r in results:
            splits[r['split_type']] = {
                'games': r['games'],
                'ppg': safe_float(r.get('ppg')),
                'over_rate': safe_float(r.get('over_rate')),
            }

        return splits

    def _query_monthly(self, player_lookup: str, season_year: int) -> List[Dict]:
        """Query monthly breakdown."""
        query = """
        SELECT
            FORMAT_DATE('%b', game_date) as month,
            EXTRACT(MONTH FROM game_date) as month_num,
            COUNT(*) as games,
            ROUND(AVG(points), 1) as ppg,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 1.0 /
                  NULLIF(SUM(CASE WHEN over_under_result IN ('OVER', 'UNDER') THEN 1 ELSE 0 END), 0), 2) as over_rate
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND season_year = @season_year
        GROUP BY month, month_num
        ORDER BY
            CASE WHEN month_num >= 10 THEN month_num - 10 ELSE month_num + 2 END
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('season_year', 'INT64', season_year),
        ]

        results = self.query_to_list(query, params)
        return [
            {
                'month': r['month'],
                'games': r['games'],
                'ppg': safe_float(r.get('ppg')),
                'over_rate': safe_float(r.get('over_rate')),
            }
            for r in results
        ]

    def _empty_response(self, player_lookup: str, season: str, reason: str) -> Dict[str, Any]:
        """Return empty response when no data available."""
        return {
            'player_lookup': player_lookup,
            'season': season,
            'generated_at': self.get_generated_at(),
            'error': reason,
            'player_profile': None,
            'averages': {},
            'current_form': {},
            'key_patterns': [],
            'prop_hit_rates': {},
            'game_log': [],
            'splits': {},
            'monthly': [],
        }

    def export(self, player_lookup: str, season: str = None) -> str:
        """
        Generate and upload season data JSON.

        Args:
            player_lookup: Player identifier
            season: Season string (e.g., '2024-25'), defaults to current

        Returns:
            GCS path of the exported file
        """
        # Determine season string
        if season is None:
            today = date.today()
            season_year = today.year if today.month >= 10 else today.year - 1
            season = f"{season_year}-{str(season_year + 1)[-2:]}"

        logger.info(f"Exporting season data for {player_lookup} season {season}")

        json_data = self.generate_json(player_lookup, season)

        # Upload to GCS
        path = f'players/{player_lookup}/season/{season}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')  # 1 hour cache

        logger.info(f"Exported season data to {gcs_path}")
        return gcs_path
