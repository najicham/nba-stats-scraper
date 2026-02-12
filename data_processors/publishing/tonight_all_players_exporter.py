"""
Tonight All Players Exporter for Phase 6 Publishing

Exports all players in tonight's games with card-level data for the website homepage.
This is the primary initial page load endpoint (~150 KB).
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date
from collections import defaultdict

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float, safe_int, safe_odds

logger = logging.getLogger(__name__)


class TonightAllPlayersExporter(BaseExporter):
    """
    Export all players in tonight's games to JSON.

    Output files:
    - tonight/all-players.json - All players for tonight's games

    JSON structure:
    {
        "game_date": "2024-12-11",
        "generated_at": "2024-12-11T07:00:00Z",
        "total_players": 156,
        "total_with_lines": 98,
        "games": [
            {
                "game_id": "20241211_LAL_DEN",
                "home_team": "DEN",
                "away_team": "LAL",
                "game_time": "19:30",
                "game_status": "scheduled",
                "home_score": null,
                "away_score": null,
                "players": [...]
            }
        ]
    }
    """

    def generate_json(self, target_date: str) -> Dict[str, Any]:
        """
        Generate JSON for all players in tonight's games.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get games for the date
        games = self._query_games(target_date)

        if not games:
            logger.warning(f"No games found for {target_date}")
            return self._empty_response(target_date)

        # Get all player data for the date
        players = self._query_players(target_date)

        # Get last 10 results for players with predictions
        player_lookups = [p['player_lookup'] for p in players]
        last_10_map = self._query_last_10_results(player_lookups, target_date)

        # Group players by game
        games_data = self._build_games_data(games, players, last_10_map)

        # Count totals
        total_players = sum(len(g['players']) for g in games_data)
        total_with_lines = sum(
            1 for g in games_data
            for p in g['players']
            if p.get('has_line')
        )

        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'total_players': total_players,
            'total_with_lines': total_with_lines,
            'games': games_data
        }

    def _query_games(self, target_date: str) -> List[Dict]:
        """Query games scheduled for the date."""
        query = """
        SELECT DISTINCT
            -- Construct date-based game_id to match upcoming_player_game_context format
            CONCAT(
                FORMAT_DATE('%Y%m%d', game_date),
                '_',
                away_team_tricode,
                '_',
                home_team_tricode
            ) as game_id,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_status,
            -- Format game time as "7:30 PM ET" for frontend lock time calculation
            LTRIM(FORMAT_TIMESTAMP('%I:%M %p ET', game_date_est, 'America/New_York')) as game_time,
            game_date_est,
            -- Scores (only for final games)
            CASE WHEN game_status = 3 THEN home_team_score ELSE NULL END as home_team_score,
            CASE WHEN game_status = 3 THEN away_team_score ELSE NULL END as away_team_score
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
        ORDER BY game_date_est, game_id
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        return self.query_to_list(query, params)

    def _query_players(self, target_date: str) -> List[Dict]:
        """Query all players for tonight's games with predictions, fatigue, and injury data."""
        query = """
        WITH predictions AS (
            -- Get predictions for players (production CatBoost V9 system)
            -- Use ROW_NUMBER to deduplicate in case of multiple rows per player/game
            SELECT
                pp.player_lookup,
                pp.game_id,
                pp.game_date,
                pp.predicted_points,
                pp.confidence_score,
                pp.recommendation,
                pp.current_points_line
            FROM `nba-props-platform.nba_predictions.player_prop_predictions` pp
            WHERE pp.game_date = @target_date
              AND pp.system_id = 'catboost_v9'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY pp.player_lookup, pp.game_id
                ORDER BY pp.created_at DESC
            ) = 1
        ),
        player_names AS (
            -- Get player full names
            SELECT player_lookup, player_name
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY season DESC) = 1
        ),
        fatigue AS (
            -- Get fatigue scores
            SELECT
                player_lookup,
                game_date,
                fatigue_score
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @target_date
        ),
        injuries AS (
            -- Get injury status (most recent report for the date)
            SELECT
                player_lookup,
                injury_status,
                reason as injury_reason
            FROM `nba-props-platform.nba_raw.nbac_injury_report`
            WHERE report_date <= @target_date
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY report_date DESC, report_hour DESC) = 1
        ),
        season_stats AS (
            -- Get season averages (derive season year from target date)
            SELECT
                player_lookup,
                ROUND(AVG(points), 1) as season_ppg,
                ROUND(AVG(minutes_played), 1) as season_mpg,
                COUNT(*) as games_played
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE season_year = CASE
                WHEN EXTRACT(MONTH FROM @target_date) >= 10 THEN EXTRACT(YEAR FROM @target_date)
                ELSE EXTRACT(YEAR FROM @target_date) - 1
              END
              AND game_date < @target_date
            GROUP BY player_lookup
        ),
        last_5_stats AS (
            -- Get last 5 games averages (all recent games, not season-specific)
            SELECT
                player_lookup,
                ROUND(AVG(points), 1) as last_5_ppg
            FROM (
                SELECT player_lookup, points
                FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date < @target_date
                QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 5
            )
            GROUP BY player_lookup
        ),
        game_context AS (
            -- Get game context (team, opponent, rest days, etc.)
            SELECT
                player_lookup,
                game_id,
                team_abbr,
                opponent_team_abbr,
                home_game,
                days_rest
            FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
            WHERE game_date = @target_date
        ),
        best_odds AS (
            -- Get best over/under odds from BettingPros
            SELECT
                player_lookup,
                points_line,
                MAX(CASE WHEN bet_side = 'over' THEN odds_american END) as over_odds,
                MAX(CASE WHEN bet_side = 'under' THEN odds_american END) as under_odds
            FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
            WHERE game_date = @target_date
              AND is_best_line = TRUE
            GROUP BY player_lookup, points_line
        )
        SELECT
            gc.player_lookup,
            COALESCE(pn.player_name, gc.player_lookup) as player_full_name,
            gc.game_id,
            gc.team_abbr,
            gc.opponent_team_abbr,
            gc.home_game,

            -- Prediction data
            p.predicted_points,
            p.confidence_score,
            p.recommendation,
            p.current_points_line,
            CASE WHEN p.current_points_line IS NOT NULL THEN TRUE ELSE FALSE END as has_line,

            -- Fatigue and rest
            f.fatigue_score,
            CASE
                WHEN f.fatigue_score >= 95 THEN 'fresh'
                WHEN f.fatigue_score >= 75 THEN 'normal'
                WHEN f.fatigue_score IS NOT NULL THEN 'tired'
                ELSE 'normal'
            END as fatigue_level,
            gc.days_rest,

            -- Injury
            COALESCE(i.injury_status, 'available') as injury_status,
            i.injury_reason,

            -- Season stats
            ss.season_ppg,
            ss.season_mpg,
            ss.games_played,

            -- Recent form
            l5.last_5_ppg,

            -- Betting odds (for props array)
            bo.over_odds,
            bo.under_odds

        FROM game_context gc
        LEFT JOIN predictions p ON gc.player_lookup = p.player_lookup AND gc.game_id = p.game_id
        LEFT JOIN player_names pn ON gc.player_lookup = pn.player_lookup
        LEFT JOIN fatigue f ON gc.player_lookup = f.player_lookup
        LEFT JOIN injuries i ON gc.player_lookup = i.player_lookup
        LEFT JOIN season_stats ss ON gc.player_lookup = ss.player_lookup
        LEFT JOIN last_5_stats l5 ON gc.player_lookup = l5.player_lookup
        LEFT JOIN best_odds bo ON gc.player_lookup = bo.player_lookup
            AND ROUND(p.current_points_line, 1) = ROUND(bo.points_line, 1)
        ORDER BY gc.game_id, COALESCE(ss.season_ppg, 0) DESC
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)
        ]
        return self.query_to_list(query, params)

    def _query_last_10_results(self, player_lookups: List[str], before_date: str) -> Dict[str, List]:
        """Query last 10 over/under results for players."""
        if not player_lookups:
            return {}

        query = """
        WITH recent_games AS (
            SELECT
                player_lookup,
                game_date,
                over_under_result,
                points,
                is_dnp,
                points_line
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date < @before_date
              AND player_lookup IN UNNEST(@player_lookups)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 10
        )
        SELECT
            player_lookup,
            ARRAY_AGG(
                STRUCT(over_under_result, points, is_dnp, points_line)
                ORDER BY game_date DESC
            ) as last_10
        FROM recent_games
        GROUP BY player_lookup
        """
        params = [
            bigquery.ScalarQueryParameter('before_date', 'DATE', before_date),
            bigquery.ArrayQueryParameter('player_lookups', 'STRING', player_lookups)
        ]
        results = self.query_to_list(query, params)

        # Build lookup map
        last_10_map = {}
        for r in results:
            player = r['player_lookup']
            games = r.get('last_10', [])

            # Extract O/U results (DNP games marked as null/DNP for graph gaps)
            results_list = []
            points_list = []
            lines_list = []
            for g in games:
                if isinstance(g, dict):
                    ou = g.get('over_under_result')
                    pts = g.get('points')
                    dnp = g.get('is_dnp', False)
                    line = g.get('points_line')
                else:
                    ou = getattr(g, 'over_under_result', None)
                    pts = getattr(g, 'points', None)
                    dnp = getattr(g, 'is_dnp', False)
                    line = getattr(g, 'points_line', None)

                if dnp:
                    results_list.append('DNP')
                    points_list.append(None)
                    lines_list.append(None)
                elif ou == 'OVER':
                    results_list.append('O')
                    points_list.append(int(pts) if pts is not None else None)
                    lines_list.append(float(line) if line is not None else None)
                elif ou == 'UNDER':
                    results_list.append('U')
                    points_list.append(int(pts) if pts is not None else None)
                    lines_list.append(float(line) if line is not None else None)
                else:
                    results_list.append('-')
                    points_list.append(int(pts) if pts is not None else None)
                    lines_list.append(float(line) if line is not None else None)

            # Calculate record (only O/U count, not DNP or -)
            overs = results_list.count('O')
            unders = results_list.count('U')

            last_10_map[player] = {
                'results': results_list,
                'points': points_list,
                'lines': lines_list,
                'record': f"{overs}-{unders}" if (overs + unders) > 0 else None
            }

        return last_10_map

    def _build_games_data(
        self,
        games: List[Dict],
        players: List[Dict],
        last_10_map: Dict[str, Dict]
    ) -> List[Dict[str, Any]]:
        """Build the games array with nested players."""
        # Group players by game_id
        players_by_game = defaultdict(list)
        for p in players:
            players_by_game[p['game_id']].append(p)

        games_data = []
        for game in games:
            game_id = game['game_id']
            game_players = players_by_game.get(game_id, [])

            # Format players
            formatted_players = []
            for p in game_players:
                player_lookup = p['player_lookup']
                last_10 = last_10_map.get(player_lookup, {})

                games_played = p.get('games_played') or 0
                player_data = {
                    'player_lookup': player_lookup,
                    'name': p.get('player_full_name', player_lookup),  # Renamed for frontend
                    'team': p.get('team_abbr'),  # Renamed for frontend
                    'is_home': p.get('home_game'),
                    'has_line': p.get('has_line', False),

                    # Fatigue and rest
                    'fatigue_level': p.get('fatigue_level', 'normal'),
                    'fatigue_score': safe_float(p.get('fatigue_score')),
                    'days_rest': p.get('days_rest'),

                    # Injury
                    'injury_status': p.get('injury_status', 'available'),
                    'injury_reason': p.get('injury_reason'),

                    # Season stats
                    'season_ppg': safe_float(p.get('season_ppg')),
                    'season_mpg': safe_float(p.get('season_mpg')),
                    'minutes_avg': safe_float(p.get('season_mpg')),
                    'last_5_ppg': safe_float(p.get('last_5_ppg')),
                    'games_played': games_played,

                    # Edge case flags
                    'limited_data': games_played < 10,
                }

                # Calculate recent_form (Hot/Cold/Neutral based on last 5 vs season avg)
                last_5_ppg = p.get('last_5_ppg')
                season_ppg = p.get('season_ppg')
                if last_5_ppg and season_ppg:
                    diff = last_5_ppg - season_ppg
                    if diff >= 3:
                        player_data['recent_form'] = 'Hot'
                    elif diff <= -3:
                        player_data['recent_form'] = 'Cold'
                    else:
                        player_data['recent_form'] = 'Neutral'
                else:
                    player_data['recent_form'] = None

                # Add last_10_points for ALL players (null = DNP gap in sparkline)
                player_data['last_10_points'] = last_10.get('points', [])

                # Add last_10_lines for ALL players (null where line was missing)
                player_data['last_10_lines'] = last_10.get('lines', [])

                # Add last_10_results (vs line) for ALL players
                player_data['last_10_results'] = last_10.get('results', [])
                player_data['last_10_record'] = last_10.get('record')

                # Add last_10_vs_avg for ALL players (O/U vs season average)
                season_ppg = p.get('season_ppg')
                last_10_pts = last_10.get('points', [])
                last_10_res = last_10.get('results', [])
                if season_ppg and last_10_pts:
                    vs_avg = []
                    for i_game, pts in enumerate(last_10_pts):
                        # Preserve DNP markers from results
                        is_dnp = (i_game < len(last_10_res) and last_10_res[i_game] == 'DNP')
                        if is_dnp:
                            vs_avg.append('DNP')
                        elif pts is None:
                            vs_avg.append('-')
                        elif pts > season_ppg:
                            vs_avg.append('O')
                        elif pts < season_ppg:
                            vs_avg.append('U')
                        else:
                            vs_avg.append('P')
                    avg_overs = vs_avg.count('O')
                    avg_unders = vs_avg.count('U')
                    player_data['last_10_vs_avg'] = vs_avg
                    player_data['last_10_avg_record'] = f"{avg_overs}-{avg_unders}"

                if p.get('has_line'):
                    line_value = safe_float(p.get('current_points_line'))
                    player_data['props'] = [{
                        'stat_type': 'points',
                        'line': line_value,
                        'over_odds': safe_odds(p.get('over_odds')),
                        'under_odds': safe_odds(p.get('under_odds')),
                    }]
                    player_data['prediction'] = {
                        'predicted': safe_float(p.get('predicted_points')),
                        'confidence': safe_float(p.get('confidence_score')),
                        'recommendation': p.get('recommendation'),
                    }

                formatted_players.append(player_data)

            # Sort: players with lines first (by confidence), then without (by PPG)
            formatted_players.sort(
                key=lambda x: (
                    not x.get('has_line', False),  # has_line first
                    x.get('injury_status') == 'out',  # OUT players last
                    -(x.get('prediction', {}).get('confidence') or 0),  # high confidence first
                    -(x.get('season_ppg') or 0)  # high PPG first
                )
            )

            # Map game_status to string
            status_map = {1: 'scheduled', 2: 'in_progress', 3: 'final'}
            game_status = status_map.get(game.get('game_status'), 'scheduled')

            # Get scores with type safety
            home_score = safe_int(game.get('home_team_score'))
            away_score = safe_int(game.get('away_team_score'))

            # Warn on final games with missing scores (postponement or data anomaly)
            if game_status == 'final' and (home_score is None or away_score is None):
                logger.warning(
                    f"Final game {game_id} has NULL scores - possible postponement or data gap"
                )

            games_data.append({
                'game_id': game_id,
                'home_team': game.get('home_team_abbr'),
                'away_team': game.get('away_team_abbr'),
                'game_time': game.get('game_time'),
                'game_status': game_status,
                'home_score': home_score,
                'away_score': away_score,
                'player_count': len(formatted_players),
                'players': formatted_players
            })

        return games_data

    def _empty_response(self, target_date: str) -> Dict[str, Any]:
        """Return empty response for dates with no games."""
        return {
            'game_date': target_date,
            'generated_at': self.get_generated_at(),
            'total_players': 0,
            'total_with_lines': 0,
            'games': []
        }

    def export(self, target_date: str) -> str:
        """
        Generate and upload tonight's all players JSON.

        Args:
            target_date: Date string in YYYY-MM-DD format

        Returns:
            GCS path of the exported file
        """
        logger.info(f"Exporting tonight all players for {target_date}")

        json_data = self.generate_json(target_date)

        # Upload with short cache (lines can change)
        path = 'tonight/all-players.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=300')

        return gcs_path
