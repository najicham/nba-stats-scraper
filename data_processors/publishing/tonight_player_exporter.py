"""
Tonight Player Exporter for Phase 6 Publishing

Exports detailed tonight data for a specific player.
Used for the "Tonight" tab in the player detail panel (~3-5 KB per player).
"""

import json
import logging
from typing import Dict, List, Any, Optional
from datetime import date, datetime

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float, compute_display_confidence

logger = logging.getLogger(__name__)


class TonightPlayerExporter(BaseExporter):
    """
    Export tonight's detailed data for a specific player.

    Output files:
    - tonight/player/{lookup}.json - Tonight tab detail for a player

    JSON structure:
    {
        "player_lookup": "lebronjames",
        "player_full_name": "LeBron James",
        "game_date": "2024-12-11",
        "generated_at": "...",
        "game_context": {...},
        "quick_numbers": {...},
        "fatigue": {...},
        "current_streak": {...},
        "tonights_factors": [...],
        "recent_form": [...],
        "prediction": {...}
    }
    """

    def generate_json(self, player_lookup: str, target_date: str) -> Dict[str, Any]:
        """
        Generate tonight's detail JSON for a specific player.

        Args:
            player_lookup: Player identifier
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get player's game context for tonight
        context = self._query_game_context(player_lookup, target_date)

        if not context:
            logger.warning(f"No game found for {player_lookup} on {target_date}")
            return self._empty_response(player_lookup, target_date)

        # Get prediction
        prediction = self._query_prediction(player_lookup, target_date)

        # Get fatigue details
        fatigue = self._query_fatigue(player_lookup, target_date)

        # Get recent form (last 10 games)
        recent_form = self._query_recent_form(player_lookup, target_date)

        # Get splits for tonight's factors
        splits = self._query_relevant_splits(player_lookup, context, target_date)

        # Get current streak
        streak = self._compute_streak(recent_form)

        # Get quick numbers
        quick_numbers = self._query_quick_numbers(player_lookup, target_date)

        # Get opponent defense tier
        opponent_abbr = context.get('opponent_team_abbr')
        defense_tier = self._query_defense_tier(opponent_abbr, target_date) if opponent_abbr else None

        # Compute days_rest fallback from recent_form if UPCG didn't have it
        if context.get('days_rest') is None and recent_form:
            last_game_str = recent_form[0].get('game_date')
            if last_game_str:
                try:
                    last_game_date = datetime.strptime(last_game_str, '%Y-%m-%d').date()
                    target = datetime.strptime(target_date, '%Y-%m-%d').date()
                    context['days_rest'] = (target - last_game_date).days
                except (ValueError, TypeError):
                    pass

        # Fallback to fatigue context for days_rest
        if context.get('days_rest') is None and fatigue and isinstance(fatigue.get('context'), dict):
            context['days_rest'] = fatigue['context'].get('days_rest')

        # Build tonight's factors (ranked candidate angles, top 4)
        tonights_factors = self._build_candidate_angles(
            context, fatigue, splits, defense_tier,
            recent_form, quick_numbers, prediction, streak
        )

        # Enrich recent_form with vs_avg (O/U vs season average)
        season_ppg = quick_numbers.get('season_ppg')
        if season_ppg and recent_form:
            for game in recent_form:
                if game.get('is_dnp'):
                    game['vs_avg'] = 'DNP'
                else:
                    pts = game.get('points')
                    if pts is not None:
                        if pts > season_ppg:
                            game['vs_avg'] = 'O'
                        elif pts < season_ppg:
                            game['vs_avg'] = 'U'
                        else:
                            game['vs_avg'] = 'P'

        games_played = quick_numbers.get('games_played') or 0
        return {
            'player_lookup': player_lookup,
            'player_full_name': context.get('player_full_name', player_lookup),
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'games_played': games_played,
            'limited_data': games_played < 10,
            'game_context': {
                'game_id': context.get('game_id'),
                'opponent': context.get('opponent_team_abbr'),
                'home_game': context.get('home_game'),
                'team_abbr': context.get('team_abbr'),
                'line': safe_float(prediction.get('current_points_line') if prediction else None),
                'days_rest': context.get('days_rest'),
                'is_back_to_back': context.get('back_to_back'),
                'injury_status': context.get('injury_status', 'available'),
                'injury_reason': context.get('injury_reason'),
            },
            'quick_numbers': quick_numbers,
            'opponent_defense': self._format_opponent_defense(defense_tier),
            'line_movement': self._format_line_movement(context, prediction),
            'fatigue': fatigue,
            'current_streak': streak,
            'tonights_factors': tonights_factors,
            'recent_form': recent_form,
            'prediction': self._format_prediction(prediction) if prediction else None
        }

    def _query_game_context(self, player_lookup: str, target_date: str) -> Optional[Dict]:
        """Query game context for the player tonight."""
        query = """
        WITH context AS (
            SELECT
                gc.player_lookup,
                gc.game_id,
                gc.team_abbr,
                gc.opponent_team_abbr,
                gc.home_game,
                gc.days_rest,
                gc.back_to_back,
                gc.opening_points_line,
                gc.current_points_line,
                gc.line_movement
            FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` gc
            WHERE gc.player_lookup = @player_lookup
              AND gc.game_date = @target_date
        ),
        player_name AS (
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            WHERE player_lookup = @player_lookup
            QUALIFY ROW_NUMBER() OVER (ORDER BY season DESC) = 1
        ),
        injury AS (
            SELECT
                player_lookup,
                injury_status,
                reason as injury_reason
            FROM `nba-props-platform.nba_raw.nbac_injury_report`
            WHERE player_lookup = @player_lookup
              AND report_date <= @target_date
            QUALIFY ROW_NUMBER() OVER (ORDER BY report_date DESC, report_hour DESC) = 1
        )
        SELECT
            c.*,
            COALESCE(pn.player_name, c.player_lookup) as player_full_name,
            i.injury_status,
            i.injury_reason
        FROM context c
        LEFT JOIN player_name pn ON c.player_lookup = pn.player_lookup
        LEFT JOIN injury i ON c.player_lookup = i.player_lookup
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _query_prediction(self, player_lookup: str, target_date: str) -> Optional[Dict]:
        """Query prediction for the player tonight."""
        query = """
        SELECT
            predicted_points,
            confidence_score,
            recommendation,
            current_points_line,
            line_margin,
            pace_adjustment,
            similar_games_count
        FROM `nba-props-platform.nba_predictions.player_prop_predictions`
        WHERE player_lookup = @player_lookup
          AND game_date = @target_date
          AND system_id = 'catboost_v9'
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        results = self.query_to_list(query, params)
        return results[0] if results else None

    def _query_fatigue(self, player_lookup: str, target_date: str) -> Dict[str, Any]:
        """Query fatigue details for the player."""
        query = """
        SELECT
            fatigue_score,
            fatigue_context_json
        FROM `nba-props-platform.nba_precompute.player_composite_factors`
        WHERE player_lookup = @player_lookup
          AND game_date = @target_date
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        results = self.query_to_list(query, params)

        if results:
            r = results[0]
            score = r.get('fatigue_score')
            if score is not None:
                if score >= 95:
                    level = 'fresh'
                elif score >= 75:
                    level = 'normal'
                else:
                    level = 'tired'
            else:
                level = 'normal'
                score = None

            # Parse fatigue_context_json if it's a string
            ctx = r.get('fatigue_context_json')
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except (json.JSONDecodeError, TypeError):
                    pass
            # Handle double-serialization (json.dumps applied twice in pipeline)
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except (json.JSONDecodeError, TypeError):
                    pass

            return {
                'score': safe_float(score),
                'level': level,
                'context': ctx
            }

        return {'score': None, 'level': 'normal', 'context': None}

    def _query_recent_form(self, player_lookup: str, before_date: str) -> List[Dict]:
        """Query last 10 games for the player."""
        query = """
        SELECT
            game_date,
            game_id,
            opponent_team_abbr,
            team_abbr,
            points,
            minutes_played,
            fg_makes,
            fg_attempts,
            three_pt_makes,
            three_pt_attempts,
            ft_makes,
            ft_attempts,
            over_under_result,
            points_line,
            is_dnp
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date < @before_date
        ORDER BY game_date DESC
        LIMIT 10
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('before_date', 'DATE', before_date)
        ]
        results = self.query_to_list(query, params)

        formatted = []
        for r in results:
            # Derive home_game from game_id (format: YYYYMMDD_AWAY_HOME)
            game_id = r.get('game_id', '')
            team_abbr = r.get('team_abbr', '')
            is_home = game_id.endswith(f'_{team_abbr}') if game_id and team_abbr else None
            is_dnp = r.get('is_dnp', False)

            if is_dnp:
                # DNP games: null stats, visible marker for graph gaps
                formatted.append({
                    'game_date': str(r['game_date']),
                    'opponent': r['opponent_team_abbr'],
                    'home_game': is_home,
                    'is_dnp': True,
                    'points': None,
                    'minutes': None,
                    'fg': None,
                    'three': None,
                    'ft': None,
                    'over_under': 'DNP',
                    'line': safe_float(r['points_line']),
                    'margin': None
                })
            else:
                formatted.append({
                    'game_date': str(r['game_date']),
                    'opponent': r['opponent_team_abbr'],
                    'home_game': is_home,
                    'is_dnp': False,
                    'points': r['points'],
                    'minutes': safe_float(r['minutes_played']),
                    'fg': f"{r['fg_makes']}/{r['fg_attempts']}" if r['fg_attempts'] else None,
                    'three': f"{r['three_pt_makes']}/{r['three_pt_attempts']}" if r['three_pt_attempts'] else None,
                    'ft': f"{r['ft_makes']}/{r['ft_attempts']}" if r['ft_attempts'] else None,
                    'over_under': r['over_under_result'],
                    'line': safe_float(r['points_line']),
                    'margin': int(r['points'] - r['points_line']) if (r['points'] is not None and r['points_line']) else None
                })

        return formatted

    def _query_quick_numbers(self, player_lookup: str, target_date: str) -> Dict[str, Any]:
        """Query quick stat numbers for the player."""
        query = """
        WITH season AS (
            SELECT
                ROUND(AVG(points), 1) as season_ppg,
                ROUND(AVG(minutes_played), 1) as season_mpg,
                COUNT(*) as games_played
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND season_year = CASE
                WHEN EXTRACT(MONTH FROM @target_date) >= 10 THEN EXTRACT(YEAR FROM @target_date)
                ELSE EXTRACT(YEAR FROM @target_date) - 1
              END
              AND game_date < @target_date
        ),
        last_10 AS (
            SELECT
                ROUND(AVG(points), 1) as last_10_ppg,
                ROUND(AVG(minutes_played), 1) as last_10_mpg
            FROM (
                SELECT points, minutes_played
                FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE player_lookup = @player_lookup
                  AND game_date < @target_date
                ORDER BY game_date DESC
                LIMIT 10
            )
        ),
        last_5 AS (
            SELECT
                ROUND(AVG(points), 1) as last_5_ppg,
                ROUND(AVG(minutes_played), 1) as last_5_mpg
            FROM (
                SELECT points, minutes_played
                FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE player_lookup = @player_lookup
                  AND game_date < @target_date
                ORDER BY game_date DESC
                LIMIT 5
            )
        )
        SELECT
            s.season_ppg,
            s.season_mpg,
            s.games_played,
            l10.last_10_ppg,
            l10.last_10_mpg,
            l5.last_5_ppg,
            l5.last_5_mpg
        FROM season s, last_10 l10, last_5 l5
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        results = self.query_to_list(query, params)

        if results:
            r = results[0]
            return {
                'season_ppg': safe_float(r.get('season_ppg')),
                'season_mpg': safe_float(r.get('season_mpg')),
                'games_played': r.get('games_played'),
                'last_10_ppg': safe_float(r.get('last_10_ppg')),
                'last_10_mpg': safe_float(r.get('last_10_mpg')),
                'last_5_ppg': safe_float(r.get('last_5_ppg')),
                'last_5_mpg': safe_float(r.get('last_5_mpg')),
            }

        return {}

    def _query_relevant_splits(
        self,
        player_lookup: str,
        context: Dict,
        target_date: str
    ) -> Dict[str, Any]:
        """Query splits relevant to tonight's game."""
        query = """
        WITH games AS (
            SELECT
                g.game_date,
                g.points,
                g.points_line,
                g.over_under_result,
                g.game_id,
                g.team_abbr,
                g.opponent_team_abbr,
                -- Derive home_game from game_id (format: YYYYMMDD_AWAY_HOME)
                ENDS_WITH(g.game_id, CONCAT('_', g.team_abbr)) as home_game,
                -- Calculate days_rest from previous game
                DATE_DIFF(g.game_date, LAG(g.game_date) OVER (ORDER BY g.game_date), DAY) as days_rest
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.player_lookup = @player_lookup
              AND g.game_date < @target_date
              AND g.season_year = CASE
                WHEN EXTRACT(MONTH FROM @target_date) >= 10 THEN EXTRACT(YEAR FROM @target_date)
                ELSE EXTRACT(YEAR FROM @target_date) - 1
              END
        )
        SELECT
            -- Home/Away split
            ROUND(AVG(CASE WHEN home_game THEN points END), 1) as home_ppg,
            COUNT(CASE WHEN home_game THEN 1 END) as home_games,
            ROUND(SAFE_DIVIDE(COUNTIF(home_game AND over_under_result = 'OVER'), COUNTIF(home_game AND over_under_result IS NOT NULL)), 3) as home_vs_line_pct,
            ROUND(AVG(CASE WHEN NOT home_game THEN points END), 1) as away_ppg,
            COUNT(CASE WHEN NOT home_game THEN 1 END) as away_games,
            ROUND(SAFE_DIVIDE(COUNTIF(NOT home_game AND over_under_result = 'OVER'), COUNTIF(NOT home_game AND over_under_result IS NOT NULL)), 3) as away_vs_line_pct,

            -- B2B split (days_rest = 1)
            ROUND(AVG(CASE WHEN days_rest = 1 THEN points END), 1) as b2b_ppg,
            COUNT(CASE WHEN days_rest = 1 THEN 1 END) as b2b_games,
            ROUND(SAFE_DIVIDE(COUNTIF(days_rest = 1 AND over_under_result = 'OVER'), COUNTIF(days_rest = 1 AND over_under_result IS NOT NULL)), 3) as b2b_vs_line_pct,
            ROUND(AVG(CASE WHEN days_rest > 1 OR days_rest IS NULL THEN points END), 1) as non_b2b_ppg,

            -- Rest split
            ROUND(AVG(CASE WHEN days_rest >= 2 THEN points END), 1) as rested_ppg,
            COUNT(CASE WHEN days_rest >= 2 THEN 1 END) as rested_games,
            ROUND(SAFE_DIVIDE(COUNTIF(days_rest >= 2 AND over_under_result = 'OVER'), COUNTIF(days_rest >= 2 AND over_under_result IS NOT NULL)), 3) as rested_vs_line_pct,

            -- vs Tonight's opponent
            ROUND(AVG(CASE WHEN opponent_team_abbr = @opponent THEN points END), 1) as vs_opponent_ppg,
            COUNT(CASE WHEN opponent_team_abbr = @opponent THEN 1 END) as vs_opponent_games,
            ROUND(SAFE_DIVIDE(COUNTIF(opponent_team_abbr = @opponent AND over_under_result = 'OVER'), COUNTIF(opponent_team_abbr = @opponent AND over_under_result IS NOT NULL)), 3) as vs_opponent_vs_line_pct

        FROM games
        """
        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('opponent', 'STRING', context.get('opponent_team_abbr', ''))
        ]
        results = self.query_to_list(query, params)
        return results[0] if results else {}

    def _compute_streak(self, recent_form: List[Dict]) -> Dict[str, Any]:
        """Compute current over/under streak from recent form."""
        if not recent_form:
            return {'type': None, 'length': 0}

        streak_type = None
        streak_length = 0

        for game in recent_form:
            ou = game.get('over_under')
            if ou in ('OVER', 'UNDER'):
                if streak_type is None:
                    streak_type = ou
                    streak_length = 1
                elif ou == streak_type:
                    streak_length += 1
                else:
                    break
            else:
                # No line for this game, break streak
                if streak_type:
                    break

        return {
            'type': streak_type.lower() if streak_type else None,
            'length': streak_length
        }

    def _query_defense_tier(self, opponent_abbr: str, target_date: str) -> Optional[Dict]:
        """
        Query opponent's defense tier ranking.

        Returns a tier (1-30, where 1 = best defense) based on opponent_points_per_game.

        Args:
            opponent_abbr: Opponent team abbreviation
            target_date: Date to check defense as of

        Returns:
            Dict with tier, rank, ppg_allowed, or None if no data
        """
        query = """
        WITH latest_defense AS (
            -- Get most recent defense data for each team
            SELECT
                team_abbr,
                opponent_points_per_game,
                defensive_rating_last_15,
                analysis_date
            FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date <= @target_date
            QUALIFY ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY analysis_date DESC) = 1
        ),
        ranked_defense AS (
            -- Rank teams by PPG allowed (lower = better defense)
            SELECT
                team_abbr,
                opponent_points_per_game,
                defensive_rating_last_15,
                RANK() OVER (ORDER BY opponent_points_per_game ASC) as rank_ppg
            FROM latest_defense
        )
        SELECT
            team_abbr,
            opponent_points_per_game,
            defensive_rating_last_15,
            rank_ppg,
            CASE
                WHEN rank_ppg <= 5 THEN 'elite'
                WHEN rank_ppg <= 10 THEN 'good'
                WHEN rank_ppg <= 20 THEN 'average'
                ELSE 'weak'
            END as tier_label
        FROM ranked_defense
        WHERE team_abbr = @opponent_abbr
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('opponent_abbr', 'STRING', opponent_abbr)
        ]

        results = self.query_to_list(query, params)

        if results:
            r = results[0]
            return {
                'rank': r.get('rank_ppg'),
                'tier_label': r.get('tier_label'),
                'ppg_allowed': safe_float(r.get('opponent_points_per_game')),
                'def_rating': safe_float(r.get('defensive_rating_last_15'))
            }

        return None

    def _format_opponent_defense(self, defense_tier: Optional[Dict]) -> Optional[Dict]:
        """Format opponent defense data for the response."""
        if not defense_tier:
            return None

        return {
            'rating': defense_tier.get('ppg_allowed'),
            'rank': defense_tier.get('rank'),
            'position_ppg_allowed': None,  # Not yet tracked at position level
            'position_ppg_rank': None,
        }

    def _format_line_movement(
        self,
        context: Dict,
        prediction: Optional[Dict]
    ) -> Optional[Dict]:
        """Format line movement data for the response.

        Returns null when opening line data isn't available (common for
        older dates or low-volume players). Frontend hides the card.
        """
        opened = context.get('opening_points_line')
        current = context.get('current_points_line')

        if opened is None or current is None:
            return None

        movement = safe_float(context.get('line_movement')) or round(current - opened, 1)

        # Determine if movement is favorable relative to our recommendation
        rec = prediction.get('recommendation') if prediction else None
        favorable = None
        if rec and movement != 0:
            # Line dropped + we say OVER = favorable (market coming our way)
            # Line rose + we say UNDER = favorable
            favorable = (movement < 0 and rec == 'OVER') or (movement > 0 and rec == 'UNDER')

        return {
            'opened': safe_float(opened),
            'current': safe_float(current),
            'movement': movement,
            'favorable': favorable,
        }

    @staticmethod
    def _parse_fg(fg_str: Optional[str]):
        """Parse 'makes/attempts' string into (makes, attempts) or None."""
        if not fg_str or '/' not in fg_str:
            return None
        try:
            makes, attempts = fg_str.split('/')
            return int(makes), int(attempts)
        except (ValueError, TypeError):
            return None

    def _build_candidate_angles(
        self,
        context: Dict,
        fatigue: Dict,
        splits: Dict,
        defense_tier: Optional[Dict],
        recent_form: List[Dict],
        quick_numbers: Dict,
        prediction: Optional[Dict],
        streak: Dict
    ) -> List[Dict]:
        """Build ranked candidate angles for tonight's game.

        Computes ~11 candidate angles from existing data, scores each by
        magnitude (0-1), and returns the top 4 most interesting ones.
        """
        candidates = []
        season_ppg = quick_numbers.get('season_ppg')
        season_mpg = quick_numbers.get('season_mpg')

        # 1. Back-to-back
        if context.get('back_to_back'):
            b2b_ppg = splits.get('b2b_ppg')
            non_b2b_ppg = splits.get('non_b2b_ppg')
            b2b_games = splits.get('b2b_games', 0)
            if b2b_ppg is not None and non_b2b_ppg is not None:
                impact = round(b2b_ppg - non_b2b_ppg, 1)
                mag = min(abs(impact) / 8, 1.0)
                if b2b_games < 3:
                    mag *= 0.7
                direction = 'negative' if impact < 0 else 'positive'
                desc = f"Averages {b2b_ppg} on back-to-backs vs {non_b2b_ppg} normally ({impact:+.1f})"
                candidates.append({
                    'id': 'b2b',
                    'factor': 'Back-to-Back',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 2. Location (home/away)
        is_home = context.get('home_game')
        if is_home is not None:
            if is_home:
                loc_ppg = splits.get('home_ppg')
                loc_games = splits.get('home_games', 0)
                other_ppg = splits.get('away_ppg')
                label = 'at home'
            else:
                loc_ppg = splits.get('away_ppg')
                loc_games = splits.get('away_games', 0)
                other_ppg = splits.get('home_ppg')
                label = 'on the road'

            if loc_ppg is not None and other_ppg is not None and loc_games >= 3:
                diff = round(loc_ppg - other_ppg, 1)
                mag = min(abs(diff) / 5, 1.0)
                direction = 'positive' if diff > 0 else ('negative' if diff < 0 else 'neutral')
                desc = f"Scores {loc_ppg} {label} vs {other_ppg} {'on the road' if is_home else 'at home'}"
                candidates.append({
                    'id': 'location',
                    'factor': 'Home' if is_home else 'Away',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 3. vs Opponent
        vs_opp_ppg = splits.get('vs_opponent_ppg')
        vs_opp_games = splits.get('vs_opponent_games', 0)
        opponent = context.get('opponent_team_abbr')
        if vs_opp_ppg is not None and vs_opp_games >= 1 and season_ppg:
            diff = round(vs_opp_ppg - season_ppg, 1)
            mag = min(abs(diff) / 6, 1.0)
            if vs_opp_games == 1:
                mag *= 0.6
            direction = 'positive' if diff > 0 else ('negative' if diff < 0 else 'neutral')
            game_word = 'game' if vs_opp_games == 1 else 'games'
            desc = f"Averages {vs_opp_ppg} vs {opponent} ({vs_opp_games} {game_word}), season avg {season_ppg}"
            candidates.append({
                'id': 'vs_opponent',
                'factor': f'vs {opponent}',
                'direction': direction,
                'magnitude': round(mag, 2),
                'description': desc
            })

        # 4. Rest advantage
        days_rest = context.get('days_rest')
        if days_rest is not None and days_rest >= 3:
            rested_ppg = splits.get('rested_ppg')
            if rested_ppg is not None and season_ppg:
                diff = round(rested_ppg - season_ppg, 1)
                mag = min(abs(diff) / 5 * 0.8, 1.0)
                direction = 'positive' if diff > 0 else ('negative' if diff < 0 else 'neutral')
                desc = f"{days_rest} days rest — averages {rested_ppg} when rested vs {season_ppg} season"
                candidates.append({
                    'id': 'rest',
                    'factor': 'Extra Rest',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 5. Fatigue
        fatigue_level = fatigue.get('level')
        fatigue_score = fatigue.get('score')
        if fatigue_level == 'tired' and fatigue_score is not None:
            mag = min((100 - fatigue_score) / 100 * 0.7, 1.0)
            desc = f"Elevated fatigue (score {fatigue_score}) — heavier recent workload"
            candidates.append({
                'id': 'fatigue',
                'factor': 'Fatigue',
                'direction': 'negative',
                'magnitude': round(mag, 2),
                'description': desc
            })
        elif fatigue_level == 'fresh':
            mag = 0.3
            desc = f"Well-rested (fatigue score {fatigue_score}) — light recent workload"
            candidates.append({
                'id': 'fatigue',
                'factor': 'Fresh Legs',
                'direction': 'positive',
                'magnitude': mag,
                'description': desc
            })

        # 6. Opponent defense
        if defense_tier:
            rank = defense_tier.get('rank')
            tier_label = defense_tier.get('tier_label')
            ppg_allowed = defense_tier.get('ppg_allowed')

            if tier_label in ('elite', 'good') or tier_label == 'weak':
                if tier_label == 'elite':
                    mag = min((30 - (rank or 15)) / 30, 1.0) * 0.9
                elif tier_label == 'good':
                    mag = min((30 - (rank or 15)) / 30, 1.0) * 0.7
                else:  # weak
                    mag = min(((rank or 15) - 1) / 30, 1.0) * 0.7

                direction = 'negative' if tier_label in ('elite', 'good') else 'positive'
                desc = f"vs {opponent} #{rank} defense ({tier_label}, allows {ppg_allowed} PPG)"
                candidates.append({
                    'id': 'opponent_defense',
                    'factor': 'Opponent Defense',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 7. Scoring trend (last 5 vs season)
        last_5_ppg = quick_numbers.get('last_5_ppg')
        if last_5_ppg is not None and season_ppg is not None:
            diff = round(last_5_ppg - season_ppg, 1)
            if abs(diff) >= 2:
                mag = min(abs(diff) / 6, 1.0)
                direction = 'positive' if diff > 0 else 'negative'
                trend_word = 'up' if diff > 0 else 'down'
                desc = f"Averaging {last_5_ppg} over last 5, {trend_word} {abs(diff)} from his {season_ppg} season mark"
                candidates.append({
                    'id': 'scoring_trend',
                    'factor': 'Scoring Surge' if diff > 0 else 'Scoring Dip',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 8. Line vs recent average
        line = prediction.get('current_points_line') if prediction else None
        last_10_ppg = quick_numbers.get('last_10_ppg')
        if line is not None and last_10_ppg is not None:
            diff = round(line - last_10_ppg, 1)
            if abs(diff) >= 2:
                mag = min(abs(diff) / 5 * 0.9, 1.0)
                direction = 'positive' if diff < 0 else 'negative'  # low line vs avg = positive (easier over)
                relation = 'below' if diff < 0 else 'above'
                desc = f"Line of {line} is {abs(diff)} {relation} his last 10 average of {last_10_ppg}"
                candidates.append({
                    'id': 'line_vs_avg',
                    'factor': 'Line Gap',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 9. Minutes trend
        last_5_mpg = quick_numbers.get('last_5_mpg')
        if last_5_mpg is not None and season_mpg is not None:
            diff = round(last_5_mpg - season_mpg, 1)
            if abs(diff) >= 3:
                mag = min(abs(diff) / 6 * 0.7, 1.0)
                direction = 'positive' if diff > 0 else 'negative'
                trend_word = 'up' if diff > 0 else 'down'
                desc = f"Playing {last_5_mpg} MPG over last 5, {trend_word} {abs(diff)} from {season_mpg} season"
                candidates.append({
                    'id': 'minutes_trend',
                    'factor': 'Minutes Up' if diff > 0 else 'Minutes Down',
                    'direction': direction,
                    'magnitude': round(mag, 2),
                    'description': desc
                })

        # 10. Streak
        streak_type = streak.get('type')
        streak_length = streak.get('length', 0)
        if streak_type and streak_length >= 3:
            mag = min(streak_length / 6 * 0.8, 1.0)
            direction = 'positive' if streak_type == 'over' else 'negative'
            # Compute over rate from recent_form
            played_games = [g for g in recent_form if not g.get('is_dnp') and g.get('over_under') in ('OVER', 'UNDER')]
            over_count = sum(1 for g in played_games if g.get('over_under') == 'OVER')
            total_ou = len(played_games)
            over_str = f", {over_count}-of-{total_ou} over rate in last {len(recent_form)}" if total_ou > 0 else ''
            desc = f"{streak_length} straight {streak_type.upper()}s{over_str}"
            candidates.append({
                'id': 'streak',
                'factor': f'{streak_type.upper()} Streak',
                'direction': direction,
                'magnitude': round(mag, 2),
                'description': desc
            })

        # 11. FG efficiency trend (last 5 vs last 10)
        played_games = [g for g in recent_form if not g.get('is_dnp')]
        if len(played_games) >= 5:
            last_5_games = played_games[:5]
            last_5_makes = 0
            last_5_att = 0
            for g in last_5_games:
                parsed = self._parse_fg(g.get('fg'))
                if parsed:
                    last_5_makes += parsed[0]
                    last_5_att += parsed[1]

            all_makes = 0
            all_att = 0
            for g in played_games:
                parsed = self._parse_fg(g.get('fg'))
                if parsed:
                    all_makes += parsed[0]
                    all_att += parsed[1]

            if last_5_att >= 20 and all_att >= 20:
                last_5_pct = round(last_5_makes / last_5_att * 100, 1)
                all_pct = round(all_makes / all_att * 100, 1)
                diff = round(last_5_pct - all_pct, 1)
                if abs(diff) >= 3:
                    mag = min(abs(diff) / 8 * 0.6, 1.0)
                    direction = 'positive' if diff > 0 else 'negative'
                    trend_word = 'up' if diff > 0 else 'down'
                    desc = f"Shooting {last_5_pct}% over last 5, {trend_word} from {all_pct}% over last {len(played_games)}"
                    candidates.append({
                        'id': 'fg_efficiency',
                        'factor': 'Shooting Hot' if diff > 0 else 'Shooting Cold',
                        'direction': direction,
                        'magnitude': round(mag, 2),
                        'description': desc
                    })

        # Sort by magnitude descending, return top 4
        candidates.sort(key=lambda c: c['magnitude'], reverse=True)
        return candidates[:4]

    def _format_prediction(self, prediction: Dict) -> Dict[str, Any]:
        """Format prediction data for output."""
        return {
            'predicted_points': safe_float(prediction.get('predicted_points')),
            'confidence_score': compute_display_confidence(
                prediction.get('predicted_points'),
                prediction.get('current_points_line'),
                prediction.get('confidence_score'),
                prediction.get('recommendation')
            ),
            'recommendation': prediction.get('recommendation'),
            'line': safe_float(prediction.get('current_points_line')),
            'edge': safe_float(prediction.get('line_margin')),
            'pace_adjustment': safe_float(prediction.get('pace_adjustment')),
            'similar_games': prediction.get('similar_games_count')
        }

    def _empty_response(self, player_lookup: str, target_date: str) -> Dict[str, Any]:
        """Return empty response when player has no game."""
        return {
            'player_lookup': player_lookup,
            'player_full_name': player_lookup,
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'game_context': None,
            'quick_numbers': {},
            'fatigue': {'score': None, 'level': 'normal', 'context': None},
            'current_streak': {'type': None, 'length': 0},
            'tonights_factors': [],
            'recent_form': [],
            'prediction': None
        }

    def export(self, player_lookup: str, target_date: str) -> str:
        """
        Generate and upload tonight's player detail JSON.

        Args:
            player_lookup: Player identifier
            target_date: Date string in YYYY-MM-DD format

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting tonight detail for {player_lookup} on {target_date}")

        json_data = self.generate_json(player_lookup, target_date)

        path = f'tonight/player/{player_lookup}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=300')

        return gcs_path

    def export_all_for_date(self, target_date: str) -> List[str]:
        """
        Export tonight details for all players with games on the date.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            List of GCS paths
        """
        logger.info(f"Exporting tonight details for all players on {target_date}")

        # Get all players with games
        query = """
        SELECT DISTINCT player_lookup
        FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
        WHERE game_date = @target_date
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        players = self.query_to_list(query, params)

        paths = []
        failures = []
        for i, p in enumerate(players):
            player_lookup = p['player_lookup']
            try:
                logger.info(f"[{i+1}/{len(players)}] Exporting {player_lookup}")
                path = self.export(player_lookup, target_date)
                paths.append(path)
            except Exception as e:
                logger.error(
                    f"[{i+1}/{len(players)}] Failed to export {player_lookup}: {e}",
                    exc_info=True
                )
                failures.append({'player': player_lookup, 'error': str(e)})

        # Log summary
        total = len(players)
        success_count = len(paths)
        failure_count = len(failures)
        logger.info(
            f"Tonight players export complete: "
            f"{success_count}/{total} succeeded, {failure_count} failed"
        )

        # Log individual failures for debugging
        if failures:
            logger.warning(
                f"Failed players ({failure_count}): "
                f"{', '.join(f['player'] for f in failures[:10])}"
                f"{'...' if failure_count > 10 else ''}"
            )

        # Raise if catastrophic failure (>20% of players failed)
        failure_pct = (failure_count / total * 100) if total > 0 else 0
        if failure_pct > 20:
            raise RuntimeError(
                f"Tonight players export catastrophic failure: "
                f"{failure_count}/{total} ({failure_pct:.1f}%) players failed. "
                f"First errors: {failures[:3]}"
            )

        return paths
