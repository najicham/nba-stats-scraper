"""
Consolidated Trends Tonight Exporter

Produces a single /v1/trends/tonight.json endpoint that powers the redesigned
Trends page. Combines data from existing hot/cold and bounce-back exporters,
adds per-game matchup cards and dynamic insight generators.

Output: /v1/trends/tonight.json
Refresh: Daily (updated throughout day as games approach)
Cache: 1 hour

Sections:
- players.hot: Top 10 hot players playing tonight (reuses WhosHotColdExporter)
- players.cold: Top 10 cold players playing tonight (reuses WhosHotColdExporter)
- players.bounce_back: Top 5 bounce-back candidates tonight (reuses BounceBackExporter)
- matchups: One card per game tonight (new SQL)
- insights: Up to 12 dynamic insights from 10 generators
"""

import logging
import os
from typing import Dict, List, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float, safe_int
from .whos_hot_cold_exporter import WhosHotColdExporter
from .bounce_back_exporter import BounceBackExporter
from .trends_v3_builder import build_trends
from shared.utils.nba_team_mapper import get_nba_team_mapper

logger = logging.getLogger(__name__)

MAX_HOT_COLD = 10
MAX_BOUNCE_BACK = 5
MAX_INSIGHTS = 12


class TrendsTonightExporter(BaseExporter):
    """
    Consolidated exporter for the Trends Tonight page.

    Reuses WhosHotColdExporter and BounceBackExporter for player data,
    adds new matchup cards and dynamic insights.
    """

    def generate_json(self, game_date: str = None) -> Dict[str, Any]:
        """
        Generate consolidated trends tonight JSON.

        Args:
            game_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary ready for JSON serialization
        """
        if game_date is None:
            game_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Generating trends tonight for {game_date}")

        # Shared data: prop lines for enrichment
        prop_lines = self._query_prop_lines(game_date)

        # Build all sections
        players_section = self._build_players_section(game_date, prop_lines)
        matchups_section = self._build_matchups_section(game_date)
        insights_section = self._build_insights_section(
            game_date, players_section, matchups_section
        )

        # V3 trends array
        tonight_teams = self._extract_tonight_teams(matchups_section)
        trends_section = self._build_trends_section(game_date, tonight_teams)

        # Enrich trends with tonight's box score data
        team_game_map = self._build_team_game_map(matchups_section)
        tonight_boxscores = self._query_tonight_boxscores(game_date)
        game_statuses = self._query_game_statuses(game_date)
        self._enrich_trends_with_tonight(
            trends_section, team_game_map, tonight_boxscores, game_statuses
        )

        games_tonight = len(matchups_section)

        return {
            'metadata': {
                'generated_at': self.get_generated_at(),
                'game_date': game_date,
                'games_tonight': games_tonight,
                'version': '3',
                'build_commit': os.environ.get('BUILD_COMMIT', 'local'),
            },
            'players': players_section,
            'matchups': matchups_section,
            'insights': insights_section,
            'trends': trends_section,
        }

    def export(self, game_date: str = None, **kwargs) -> str:
        """
        Generate and upload trends tonight JSON to GCS.

        Args:
            game_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of the exported file
        """
        if game_date is None:
            game_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting trends tonight for {game_date}")

        json_data = self.generate_json(game_date)

        path = 'trends/tonight.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')

        logger.info(f"Exported trends tonight to {gcs_path}")
        return gcs_path

    # =========================================================================
    # Shared data queries
    # =========================================================================

    def _query_prop_lines(self, game_date: str) -> Dict[str, float]:
        """Query current prop lines for all players on game_date.

        Returns:
            Dict mapping player_lookup -> current_points_line
        """
        query = """
        SELECT player_lookup, current_points_line
        FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
        WHERE game_date = @game_date
          AND current_points_line IS NOT NULL
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]
        try:
            rows = self.query_to_list(query, params)
            return {
                r['player_lookup']: safe_float(r['current_points_line'], precision=1)
                for r in rows
                if r.get('player_lookup')
            }
        except Exception as e:
            logger.warning(f"Failed to query prop lines: {e}")
            return {}

    # =========================================================================
    # Section 1 & 2: Players (hot/cold/bounce_back)
    # =========================================================================

    def _build_players_section(
        self, game_date: str, prop_lines: Dict[str, float]
    ) -> Dict[str, List]:
        """Build players section by reusing existing exporters and filtering."""
        hot_players = []
        cold_players = []
        bounce_back = []

        # --- Hot/Cold from WhosHotColdExporter ---
        try:
            hc_exporter = WhosHotColdExporter(
                project_id=self.project_id, bucket_name=self.bucket_name
            )
            hc_data = hc_exporter.generate_json(as_of_date=game_date)

            # Filter to playing tonight and enrich with prop lines
            for p in hc_data.get('hot', []):
                if p.get('playing_tonight'):
                    p['prop_line'] = prop_lines.get(p.get('player_lookup'))
                    hot_players.append(p)

            for p in hc_data.get('cold', []):
                if p.get('playing_tonight'):
                    p['prop_line'] = prop_lines.get(p.get('player_lookup'))
                    cold_players.append(p)

        except Exception as e:
            logger.error(f"Failed to get hot/cold data: {e}")

        # Cap at MAX_HOT_COLD
        hot_players = hot_players[:MAX_HOT_COLD]
        cold_players = cold_players[:MAX_HOT_COLD]

        # --- Bounce-back from BounceBackExporter ---
        try:
            bb_exporter = BounceBackExporter(
                project_id=self.project_id, bucket_name=self.bucket_name
            )
            bb_data = bb_exporter.generate_json(as_of_date=game_date)

            for c in bb_data.get('bounce_back_candidates', []):
                if c.get('playing_tonight'):
                    c['prop_line'] = prop_lines.get(c.get('player_lookup'))
                    bounce_back.append(c)

        except Exception as e:
            logger.error(f"Failed to get bounce-back data: {e}")

        bounce_back = bounce_back[:MAX_BOUNCE_BACK]

        return {
            'hot': hot_players,
            'cold': cold_players,
            'bounce_back': bounce_back,
        }

    # =========================================================================
    # Tonight's box score enrichment
    # =========================================================================

    def _query_tonight_boxscores(self, game_date: str) -> Dict[str, Dict]:
        """Query tonight's box scores from player boxscores table.

        Returns:
            Dict mapping player_lookup → box score stats dict
        """
        query = """
        SELECT
            bs.player_lookup,
            bs.team_abbr,
            bs.minutes,
            bs.points,
            bs.total_rebounds,
            bs.assists,
            bs.steals,
            bs.blocks,
            bs.turnovers,
            bs.field_goals_made,
            bs.field_goals_attempted,
            bs.field_goal_percentage,
            bs.three_pointers_made,
            bs.three_pointers_attempted,
            bs.three_point_percentage,
            bs.free_throws_made,
            bs.free_throws_attempted,
            bs.plus_minus
        FROM `nba-props-platform.nba_raw.nbac_player_boxscores` bs
        WHERE bs.game_date = @game_date
          AND bs.minutes IS NOT NULL
          AND bs.minutes != '0:00'
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]
        try:
            rows = self.query_to_list(query, params)
            return {
                r['player_lookup']: r
                for r in rows
                if r.get('player_lookup')
            }
        except Exception as e:
            logger.warning(f"Failed to query tonight's boxscores: {e}")
            return {}

    def _query_game_statuses(self, game_date: str) -> Dict[str, Dict[str, Any]]:
        """Query game statuses and times per team for tonight's games.

        Returns:
            Dict mapping team_abbr → {'status': str, 'game_time': str|None}
        """
        query = """
        SELECT
            home_team_tricode as team_abbr,
            CASE game_status
                WHEN 1 THEN 'scheduled'
                WHEN 2 THEN 'in_progress'
                WHEN 3 THEN 'final'
                ELSE 'scheduled'
            END as status,
            FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%S%Ez', game_date_est, 'America/New_York') as game_time
        FROM `nba-props-platform.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = @game_date
        UNION ALL
        SELECT
            away_team_tricode,
            CASE game_status
                WHEN 1 THEN 'scheduled'
                WHEN 2 THEN 'in_progress'
                WHEN 3 THEN 'final'
                ELSE 'scheduled'
            END,
            FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%S%Ez', game_date_est, 'America/New_York')
        FROM `nba-props-platform.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = @game_date
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]
        try:
            rows = self.query_to_list(query, params)
            return {
                r['team_abbr']: {
                    'status': r['status'],
                    'game_time': r.get('game_time'),
                }
                for r in rows if r.get('team_abbr')
            }
        except Exception as e:
            logger.warning(f"Failed to query game statuses: {e}")
            return {}

    def _build_team_game_map(self, matchups: List[Dict]) -> Dict[str, Dict]:
        """Map team_abbr → {opponent, home} from matchups."""
        team_map = {}
        for m in matchups:
            away = m['away_team']['abbr']
            home = m['home_team']['abbr']
            team_map[away] = {'opponent': home, 'home': False}
            team_map[home] = {'opponent': away, 'home': True}
        return team_map

    @staticmethod
    def _parse_minutes(minutes_str) -> Optional[int]:
        """Parse minutes string like '36:12' to integer minutes (36)."""
        if not minutes_str:
            return None
        try:
            return int(str(minutes_str).split(':')[0])
        except (ValueError, IndexError):
            return None

    def _build_tonight_object(
        self,
        team_info: Dict,
        boxscore_row: Optional[Dict],
        game_status: str,
        game_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a tonight object for a trend item."""
        obj: Dict[str, Any] = {
            'status': game_status or 'scheduled',
            'opponent': team_info['opponent'],
            'home': team_info['home'],
            'game_time': game_time,
            'min': None, 'pts': None, 'reb': None, 'ast': None,
            'stl': None, 'blk': None, 'tov': None,
            'fg': None, 'fg_pct': None,
            'three_pt': None, 'three_pct': None,
            'ft': None, 'plus_minus': None,
        }
        if boxscore_row:
            obj['min'] = self._parse_minutes(boxscore_row.get('minutes'))
            obj['pts'] = safe_int(boxscore_row.get('points'))
            obj['reb'] = safe_int(boxscore_row.get('total_rebounds'))
            obj['ast'] = safe_int(boxscore_row.get('assists'))
            obj['stl'] = safe_int(boxscore_row.get('steals'))
            obj['blk'] = safe_int(boxscore_row.get('blocks'))
            obj['tov'] = safe_int(boxscore_row.get('turnovers'))

            fgm = safe_int(boxscore_row.get('field_goals_made'))
            fga = safe_int(boxscore_row.get('field_goals_attempted'))
            if fgm is not None and fga is not None:
                obj['fg'] = f"{fgm}-{fga}"
            obj['fg_pct'] = safe_float(
                boxscore_row.get('field_goal_percentage'), precision=3
            )

            tpm = safe_int(boxscore_row.get('three_pointers_made'))
            tpa = safe_int(boxscore_row.get('three_pointers_attempted'))
            if tpm is not None and tpa is not None:
                obj['three_pt'] = f"{tpm}-{tpa}"
            obj['three_pct'] = safe_float(
                boxscore_row.get('three_point_percentage'), precision=3
            )

            ftm = safe_int(boxscore_row.get('free_throws_made'))
            fta = safe_int(boxscore_row.get('free_throws_attempted'))
            if ftm is not None and fta is not None:
                obj['ft'] = f"{ftm}-{fta}"

            obj['plus_minus'] = safe_int(boxscore_row.get('plus_minus'))

        return obj

    def _enrich_trends_with_tonight(
        self,
        trends: List[Dict],
        team_map: Dict[str, Dict],
        boxscores: Dict[str, Dict],
        game_statuses: Dict[str, Dict[str, Any]],
    ) -> None:
        """Add tonight object to each trend item whose player is playing tonight.

        Modifies trends in place.
        """
        for trend in trends:
            player = trend.get('player', {})
            team = player.get('team', '')
            lookup = player.get('lookup', '')

            if team not in team_map:
                continue

            team_info = team_map[team]
            boxscore_row = boxscores.get(lookup)
            status_info = game_statuses.get(team, {})
            game_status = status_info.get('status', 'scheduled') if isinstance(status_info, dict) else status_info
            game_time = status_info.get('game_time') if isinstance(status_info, dict) else None

            trend['tonight'] = self._build_tonight_object(
                team_info, boxscore_row, game_status, game_time
            )

    # =========================================================================
    # Section: V3 Trends
    # =========================================================================

    def _extract_tonight_teams(self, matchups: List[Dict]) -> set:
        """Extract team abbreviations from matchup cards."""
        teams = set()
        for m in matchups:
            teams.add(m.get('away_team', {}).get('abbr', ''))
            teams.add(m.get('home_team', {}).get('abbr', ''))
        teams.discard('')
        return teams

    def _build_trends_section(
        self, game_date: str, tonight_teams: set
    ) -> List[Dict]:
        """Build V3 trends array using the trends builder."""
        try:
            return build_trends(self.bq_client, game_date, tonight_teams)
        except Exception as e:
            logger.error(f"Failed to build V3 trends: {e}")
            return []

    # =========================================================================
    # Section 3: Matchups
    # =========================================================================

    def _build_matchups_section(self, game_date: str) -> List[Dict]:
        """Build per-game matchup cards from team context tables."""
        query = """
        WITH team_ctx AS (
            SELECT
                tc.team_abbr,
                tc.game_id,
                tc.opponent_team_abbr,
                tc.home_game,
                tc.game_spread,
                tc.game_total,
                tc.team_days_rest,
                tc.is_back_to_back,
                tc.starters_out_count,
                tc.team_win_streak_entering,
                tc.travel_miles
            FROM `nba-props-platform.nba_analytics.upcoming_team_game_context` tc
            WHERE tc.game_date = @game_date
        ),
        defense AS (
            SELECT
                d.team_abbr,
                d.opponent_points_per_game,
                d.opponent_pace,
                d.weakest_zone
            FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` d
            WHERE d.analysis_date = (
                SELECT MAX(analysis_date)
                FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
                WHERE analysis_date <= @game_date
            )
        ),
        over_rates AS (
            SELECT
                team_abbr,
                COUNTIF(over_under_result = 'OVER') / COUNT(*) as over_rate_l15
            FROM (
                SELECT team_abbr, over_under_result,
                       ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY game_date DESC) as rn
                FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 25 DAY)
                  AND game_date < @game_date
                  AND over_under_result IN ('OVER', 'UNDER')
            )
            WHERE rn <= 15
            GROUP BY team_abbr
            HAVING COUNT(*) >= 5
        )
        SELECT
            tc.game_id,
            tc.team_abbr,
            tc.opponent_team_abbr,
            tc.home_game,
            tc.game_spread,
            tc.game_total,
            tc.team_days_rest,
            tc.is_back_to_back,
            tc.starters_out_count,
            tc.team_win_streak_entering,
            tc.travel_miles,
            d.opponent_points_per_game as opp_ppg,
            d.opponent_pace,
            d.weakest_zone,
            orates.over_rate_l15
        FROM team_ctx tc
        LEFT JOIN defense d ON tc.team_abbr = d.team_abbr
        LEFT JOIN over_rates orates ON tc.team_abbr = orates.team_abbr
        ORDER BY tc.game_id, tc.home_game DESC
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception as e:
            logger.error(f"Matchup query failed: {e}")
            return []

        if not rows:
            return []

        # Group rows into games (each game has 2 rows: home + away)
        games_map: Dict[str, Dict] = {}
        for row in rows:
            game_id = row['game_id']
            if game_id not in games_map:
                games_map[game_id] = {}

            side = 'home' if row.get('home_game') else 'away'
            games_map[game_id][side] = row

        mapper = get_nba_team_mapper()
        matchups = []

        for game_id, sides in games_map.items():
            home = sides.get('home', {})
            away = sides.get('away', {})

            if not home or not away:
                continue

            home_abbr = home.get('team_abbr', '')
            away_abbr = away.get('team_abbr', '')

            home_info = mapper.get_team_info(home_abbr)
            away_info = mapper.get_team_info(away_abbr)

            matchup = {
                'game_id': game_id,
                'away_team': {
                    'abbr': away_abbr,
                    'name': away_info.full_name if away_info else away_abbr,
                },
                'home_team': {
                    'abbr': home_abbr,
                    'name': home_info.full_name if home_info else home_abbr,
                },
                'spread': safe_float(home.get('game_spread'), precision=1),
                'total': safe_float(home.get('game_total'), precision=1),
                'defense': {
                    'away_opp_ppg': safe_float(away.get('opp_ppg'), precision=1),
                    'home_opp_ppg': safe_float(home.get('opp_ppg'), precision=1),
                },
                'rest': {
                    'away_days': safe_int(away.get('team_days_rest')),
                    'home_days': safe_int(home.get('team_days_rest')),
                    'away_b2b': bool(away.get('is_back_to_back')),
                    'home_b2b': bool(home.get('is_back_to_back')),
                },
                'injuries': {
                    'away_starters_out': safe_int(away.get('starters_out_count'), default=0),
                    'home_starters_out': safe_int(home.get('starters_out_count'), default=0),
                },
                'over_rate': {
                    'away_l15': safe_float(away.get('over_rate_l15')),
                    'home_l15': safe_float(home.get('over_rate_l15')),
                },
                'pace': {
                    'away': safe_float(away.get('opponent_pace'), precision=1),
                    'home': safe_float(home.get('opponent_pace'), precision=1),
                },
            }

            # Generate key insight for this game
            matchup['key_insight'] = self._generate_key_insight(
                away_abbr, home_abbr, away, home
            )

            matchups.append(matchup)

        return matchups

    def _generate_key_insight(
        self,
        away_abbr: str,
        home_abbr: str,
        away: Dict,
        home: Dict,
    ) -> str:
        """Generate a single-sentence key insight for a matchup, priority-ordered."""
        parts = []

        # 1. Rest mismatch (B2B vs 2+ days rest)
        away_b2b = bool(away.get('is_back_to_back'))
        home_b2b = bool(home.get('is_back_to_back'))
        away_rest = safe_int(away.get('team_days_rest')) or 1
        home_rest = safe_int(home.get('team_days_rest')) or 1

        if away_b2b and home_rest >= 2:
            parts.append(f"{away_abbr} on B2B; {home_abbr} rested ({home_rest} days)")
        elif home_b2b and away_rest >= 2:
            parts.append(f"{home_abbr} on B2B; {away_abbr} rested ({away_rest} days)")

        # 2. Injury impact
        away_out = safe_int(away.get('starters_out_count'), default=0)
        home_out = safe_int(home.get('starters_out_count'), default=0)
        if away_out >= 2:
            parts.append(f"{away_abbr} missing {away_out} starters")
        if home_out >= 2:
            parts.append(f"{home_abbr} missing {home_out} starters")

        # 3. Pace note via opponent_pace (which reflects pace of games allowed)
        away_pace = safe_float(away.get('opponent_pace'), precision=1)
        home_pace = safe_float(home.get('opponent_pace'), precision=1)
        if away_pace and home_pace:
            diff = abs(away_pace - home_pace)
            if diff > 4:
                fast_team = away_abbr if away_pace > home_pace else home_abbr
                slow_team = home_abbr if away_pace > home_pace else away_abbr
                parts.append(f"Pace clash: {fast_team} fast vs {slow_team} slow")

        if not parts:
            return f"{away_abbr} at {home_abbr}"

        return '; '.join(parts[:2])

    # =========================================================================
    # Section 4: Insights (10 generators)
    # =========================================================================

    def _build_insights_section(
        self,
        game_date: str,
        players: Dict[str, List],
        matchups: List[Dict],
    ) -> List[Dict]:
        """Run all insight generators, sort by relevance, cap at MAX_INSIGHTS."""
        insights: List[Dict] = []

        generators = [
            self._insight_b2b_tonight,
            self._insight_rest_advantage,
            self._insight_pace_clash,
            self._insight_defense_exploit,
            self._insight_hot_streakers_tonight,
            self._insight_bounce_back_alert,
            self._insight_day_of_week,
            self._insight_home_over_rate,
            self._insight_model_performance,
            self._insight_scoring_tier,
        ]

        for gen in generators:
            try:
                result = gen(game_date, players, matchups)
                if result:
                    insights.append(result)
            except Exception as e:
                logger.warning(f"Insight generator {gen.__name__} failed: {e}")

        # Sort: high confidence first, then medium, then low
        confidence_order = {'high': 0, 'medium': 1, 'low': 2}
        insights.sort(key=lambda x: confidence_order.get(x.get('confidence', 'low'), 2))

        return insights[:MAX_INSIGHTS]

    # --- Generators 1-6: Derived from matchup/player data (no extra SQL) ---

    def _insight_b2b_tonight(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Alert when any team is on a back-to-back tonight."""
        b2b_teams = []
        for m in matchups:
            rest = m.get('rest', {})
            if rest.get('away_b2b'):
                b2b_teams.append(m['away_team']['abbr'])
            if rest.get('home_b2b'):
                b2b_teams.append(m['home_team']['abbr'])

        if not b2b_teams:
            return None

        teams_str = ', '.join(b2b_teams)
        return {
            'id': f"ti-b2b-{b2b_teams[0].lower()}",
            'type': 'alert',
            'headline': f"B2B Alert: {teams_str} on second night",
            'description': (
                f"{len(b2b_teams)} team(s) playing a back-to-back tonight. "
                "Players on B2B teams historically score fewer points."
            ),
            'main_value': str(len(b2b_teams)),
            'is_positive': False,
            'confidence': 'high',
            'sample_size': len(b2b_teams),
            'tags': ['rest', 'b2b'] + [t.lower() for t in b2b_teams],
            'players': [],
        }

    def _insight_rest_advantage(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Highlight team with 3+ days rest."""
        rested_teams = []
        for m in matchups:
            rest = m.get('rest', {})
            for side in ['away', 'home']:
                days = rest.get(f'{side}_days')
                if days is not None and days >= 3:
                    abbr = m[f'{side}_team']['abbr']
                    rested_teams.append((abbr, days))

        if not rested_teams:
            return None

        best = max(rested_teams, key=lambda x: x[1])
        return {
            'id': f"ti-rest-{best[0].lower()}",
            'type': 'info',
            'headline': f"Rest Edge: {best[0]} with {best[1]} days off",
            'description': (
                f"{best[0]} has had {best[1]} days of rest. "
                "Well-rested teams tend to see higher scoring outputs."
            ),
            'main_value': f"+{best[1]}",
            'is_positive': True,
            'confidence': 'medium',
            'sample_size': best[1],
            'tags': ['rest', best[0].lower()],
            'players': [],
        }

    def _insight_pace_clash(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Identify games with big pace differential."""
        for m in matchups:
            pace = m.get('pace', {})
            away_pace = pace.get('away')
            home_pace = pace.get('home')
            if away_pace and home_pace:
                diff = abs(away_pace - home_pace)
                if diff > 4:
                    fast = m['away_team']['abbr'] if away_pace > home_pace else m['home_team']['abbr']
                    slow = m['home_team']['abbr'] if away_pace > home_pace else m['away_team']['abbr']
                    return {
                        'id': f"ti-pace-{fast.lower()}-{slow.lower()}",
                        'type': 'info',
                        'headline': f"Pace Clash: {fast} vs {slow}",
                        'description': (
                            f"Pace differential of {diff:.1f} between {fast} and {slow}. "
                            "Large pace mismatches can create over/under opportunities."
                        ),
                        'main_value': f"{diff:.1f}",
                        'is_positive': None,
                        'confidence': 'medium',
                        'sample_size': None,
                        'tags': ['pace', fast.lower(), slow.lower()],
                        'players': [],
                    }
        return None

    def _insight_defense_exploit(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Identify matchup where a weak defense faces a strong offense."""
        # Use opp_ppg from matchup data — high opp_ppg = weak defense
        worst_defense = None
        worst_opp_ppg = 0

        for m in matchups:
            defense = m.get('defense', {})
            for side, opp_side in [('away', 'home'), ('home', 'away')]:
                opp_ppg = defense.get(f'{side}_opp_ppg')
                if opp_ppg and opp_ppg > worst_opp_ppg:
                    worst_opp_ppg = opp_ppg
                    worst_defense = {
                        'weak_team': m[f'{side}_team']['abbr'],
                        'opponent': m[f'{opp_side}_team']['abbr'],
                        'opp_ppg': opp_ppg,
                    }

        if not worst_defense or worst_opp_ppg < 115:
            return None

        return {
            'id': f"ti-def-{worst_defense['weak_team'].lower()}",
            'type': 'alert',
            'headline': f"Defense Exploit: {worst_defense['opponent']} vs {worst_defense['weak_team']}",
            'description': (
                f"{worst_defense['weak_team']} allows {worst_opp_ppg:.1f} PPG to opponents. "
                f"{worst_defense['opponent']} players could benefit from the weak defense."
            ),
            'main_value': f"{worst_opp_ppg:.1f}",
            'is_positive': True,
            'confidence': 'medium',
            'sample_size': None,
            'tags': ['defense', worst_defense['weak_team'].lower(), worst_defense['opponent'].lower()],
            'players': [],
        }

    def _insight_hot_streakers_tonight(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Alert when 3+ hot players are on tonight's slate."""
        hot = players.get('hot', [])
        if len(hot) < 3:
            return None

        names = [p.get('player_full_name', p.get('player_lookup', '')) for p in hot[:5]]
        return {
            'id': 'ti-hot-streak',
            'type': 'positive',
            'headline': f"{len(hot)} Hot Players Tonight",
            'description': (
                f"Multiple players on hot streaks are playing tonight including "
                f"{', '.join(names[:3])}."
            ),
            'main_value': str(len(hot)),
            'is_positive': True,
            'confidence': 'medium',
            'sample_size': len(hot),
            'tags': ['hot', 'streak'],
            'players': [p.get('player_lookup') for p in hot[:5]],
        }

    def _insight_bounce_back_alert(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Alert when multiple bounce-back candidates are playing tonight."""
        bb = players.get('bounce_back', [])
        if len(bb) < 2:
            return None

        names = [c.get('player_full_name', c.get('player_lookup', '')) for c in bb[:3]]
        avg_rate = sum(c.get('bounce_back_rate', 0) for c in bb) / len(bb)

        return {
            'id': 'ti-bounce-back',
            'type': 'info',
            'headline': f"{len(bb)} Bounce-Back Candidates Tonight",
            'description': (
                f"{', '.join(names)} had bad recent games. "
                f"Average bounce-back rate: {avg_rate:.0%}."
            ),
            'main_value': f"{avg_rate:.0%}",
            'is_positive': True,
            'confidence': 'medium',
            'sample_size': len(bb),
            'tags': ['bounce-back'],
            'players': [c.get('player_lookup') for c in bb[:5]],
        }

    # --- Generators 7-10: Need their own queries ---

    def _insight_day_of_week(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Check if today's day-of-week OVER rate deviates 3%+ from average."""
        query = """
        WITH daily AS (
            SELECT
                EXTRACT(DAYOFWEEK FROM game_date) as dow,
                COUNTIF(over_under_result = 'OVER') / COUNT(*) as over_rate,
                COUNT(*) as games
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@game_date, INTERVAL 60 DAY)
              AND game_date < @game_date
              AND over_under_result IN ('OVER', 'UNDER')
            GROUP BY dow
        ),
        overall AS (
            SELECT AVG(over_rate) as avg_over_rate FROM daily
        )
        SELECT
            d.dow,
            d.over_rate,
            d.games,
            o.avg_over_rate,
            d.over_rate - o.avg_over_rate as deviation
        FROM daily d
        CROSS JOIN overall o
        WHERE d.dow = EXTRACT(DAYOFWEEK FROM @game_date)
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception:
            return None

        if not rows:
            return None

        row = rows[0]
        deviation = safe_float(row.get('deviation'))
        over_rate = safe_float(row.get('over_rate'))
        games = safe_int(row.get('games'))

        if deviation is None or abs(deviation) < 0.03:
            return None

        day_names = {1: 'Sunday', 2: 'Monday', 3: 'Tuesday', 4: 'Wednesday',
                     5: 'Thursday', 6: 'Friday', 7: 'Saturday'}
        dow = safe_int(row.get('dow'))
        day_name = day_names.get(dow, 'Today')

        direction = 'higher' if deviation > 0 else 'lower'
        return {
            'id': 'ti-dow',
            'type': 'info',
            'headline': f"{day_name} Games Lean {'Over' if deviation > 0 else 'Under'}",
            'description': (
                f"OVER rate on {day_name}s is {over_rate:.1%}, "
                f"{abs(deviation):.1%} {direction} than average ({games} games L60d)."
            ),
            'main_value': f"{over_rate:.0%}",
            'is_positive': deviation > 0,
            'confidence': 'low' if games and games < 50 else 'medium',
            'sample_size': games,
            'tags': ['day-of-week', day_name.lower()],
            'players': [],
        }

    def _insight_home_over_rate(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Check if 7-day home OVER rate differs significantly from away."""
        query = """
        WITH games AS (
            SELECT
                over_under_result,
                team_abbr = SPLIT(game_id, '_')[OFFSET(2)] as is_home
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@game_date, INTERVAL 7 DAY)
              AND game_date < @game_date
              AND over_under_result IN ('OVER', 'UNDER')
        )
        SELECT
            COUNTIF(is_home AND over_under_result = 'OVER') /
                NULLIF(COUNTIF(is_home AND over_under_result IN ('OVER', 'UNDER')), 0)
                as home_over_rate,
            COUNTIF(NOT is_home AND over_under_result = 'OVER') /
                NULLIF(COUNTIF(NOT is_home AND over_under_result IN ('OVER', 'UNDER')), 0)
                as away_over_rate,
            COUNTIF(is_home AND over_under_result IN ('OVER', 'UNDER')) as home_games,
            COUNTIF(NOT is_home AND over_under_result IN ('OVER', 'UNDER')) as away_games
        FROM games
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception:
            return None

        if not rows:
            return None

        row = rows[0]
        home_rate = safe_float(row.get('home_over_rate'))
        away_rate = safe_float(row.get('away_over_rate'))
        home_games = safe_int(row.get('home_games'))
        away_games = safe_int(row.get('away_games'))

        if home_rate is None or away_rate is None:
            return None
        if (home_games or 0) < 20 or (away_games or 0) < 20:
            return None

        diff = home_rate - away_rate
        if abs(diff) < 0.04:
            return None

        favored = 'Home' if diff > 0 else 'Away'
        return {
            'id': 'ti-home-away',
            'type': 'info',
            'headline': f"{favored} Players Hitting Overs More (L7d)",
            'description': (
                f"Home OVER rate {home_rate:.1%} vs away {away_rate:.1%} "
                f"over the last 7 days ({home_games}H / {away_games}A games)."
            ),
            'main_value': f"{abs(diff):.1%}",
            'is_positive': diff > 0,
            'confidence': 'low',
            'sample_size': (home_games or 0) + (away_games or 0),
            'tags': ['home-away', 'over-rate'],
            'players': [],
        }

    def _insight_model_performance(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Report edge 3+ hit rate over last 7 and 30 days."""
        query = """
        SELECT
            COUNTIF(game_date >= DATE_SUB(@game_date, INTERVAL 7 DAY) AND prediction_correct) as hits_7d,
            COUNTIF(game_date >= DATE_SUB(@game_date, INTERVAL 7 DAY)) as total_7d,
            COUNTIF(prediction_correct) as hits_30d,
            COUNT(*) as total_30d
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
          AND game_date < @game_date
          AND ABS(predicted_margin) >= 3
          AND system_id = 'catboost_v12'
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception:
            return None

        if not rows:
            return None

        row = rows[0]
        total_7d = safe_int(row.get('total_7d'), default=0)
        hits_7d = safe_int(row.get('hits_7d'), default=0)
        total_30d = safe_int(row.get('total_30d'), default=0)
        hits_30d = safe_int(row.get('hits_30d'), default=0)

        if total_30d < 10:
            return None

        rate_30d = hits_30d / total_30d if total_30d else 0
        rate_7d = hits_7d / total_7d if total_7d else None

        description_parts = [f"30-day: {rate_30d:.1%} ({hits_30d}/{total_30d})"]
        if rate_7d is not None and total_7d >= 5:
            description_parts.insert(0, f"7-day: {rate_7d:.1%} ({hits_7d}/{total_7d})")

        return {
            'id': 'ti-model',
            'type': 'info',
            'headline': f"Model Edge 3+ Hit Rate: {rate_30d:.0%}",
            'description': (
                f"High-edge (3+) pick performance — {'. '.join(description_parts)}."
            ),
            'main_value': f"{rate_30d:.0%}",
            'is_positive': rate_30d >= 0.55,
            'confidence': 'high' if total_30d >= 50 else 'medium',
            'sample_size': total_30d,
            'tags': ['model', 'performance'],
            'players': [],
        }

    def _insight_scoring_tier(
        self, game_date: str, players: Dict, matchups: List[Dict]
    ) -> Optional[Dict]:
        """Check if stars vs rotation OVER rate gap > 5%."""
        query = """
        WITH player_tiers AS (
            SELECT
                player_lookup,
                AVG(points) as avg_pts,
                over_under_result
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@game_date, INTERVAL 14 DAY)
              AND game_date < @game_date
              AND over_under_result IN ('OVER', 'UNDER')
            GROUP BY player_lookup, over_under_result, game_date
        ),
        tiered AS (
            SELECT
                CASE WHEN avg_pts >= 22 THEN 'star' ELSE 'rotation' END as tier,
                over_under_result
            FROM player_tiers
        )
        SELECT
            tier,
            COUNTIF(over_under_result = 'OVER') / COUNT(*) as over_rate,
            COUNT(*) as games
        FROM tiered
        GROUP BY tier
        """
        params = [
            bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
        ]

        try:
            rows = self.query_to_list(query, params)
        except Exception:
            return None

        tiers = {r['tier']: r for r in rows}
        star = tiers.get('star')
        rotation = tiers.get('rotation')

        if not star or not rotation:
            return None

        star_rate = safe_float(star.get('over_rate'))
        rot_rate = safe_float(rotation.get('over_rate'))
        star_games = safe_int(star.get('games'), default=0)
        rot_games = safe_int(rotation.get('games'), default=0)

        if star_rate is None or rot_rate is None:
            return None
        if star_games < 30 or rot_games < 30:
            return None

        gap = star_rate - rot_rate
        if abs(gap) < 0.05:
            return None

        favored = 'Stars' if gap > 0 else 'Rotation'
        return {
            'id': 'ti-tier',
            'type': 'info',
            'headline': f"{favored} Hitting Overs More (L14d)",
            'description': (
                f"Stars (22+ PPG avg) OVER rate: {star_rate:.1%} ({star_games} games) "
                f"vs rotation: {rot_rate:.1%} ({rot_games} games)."
            ),
            'main_value': f"{abs(gap):.1%}",
            'is_positive': gap > 0,
            'confidence': 'low',
            'sample_size': star_games + rot_games,
            'tags': ['scoring-tier', 'star', 'rotation'],
            'players': [],
        }
