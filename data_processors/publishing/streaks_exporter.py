"""
Streaks Exporter for Phase 6 Publishing

Exports players currently on OVER/UNDER/prediction streaks.
Useful for highlighting hot/cold players on the website.

Output: /v1/streaks/today.json
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter
from .exporter_utils import safe_float

logger = logging.getLogger(__name__)


class StreaksExporter(BaseExporter):
    """
    Export players on notable streaks.

    Streak types:
    - OVER streak: Consecutive games beating their points line
    - UNDER streak: Consecutive games falling short of their points line
    - Prediction streak: Consecutive correct predictions (OVER/UNDER calls)

    JSON structure:
    {
        "generated_at": "...",
        "as_of_date": "2024-12-11",
        "min_streak_length": 4,
        "streaks": {
            "over": [
                {
                    "player_lookup": "lebronjames",
                    "player_full_name": "LeBron James",
                    "team": "LAL",
                    "streak_length": 6,
                    "avg_margin": 4.5,
                    "games": [...]
                }
            ],
            "under": [...],
            "prediction_hits": [...]
        },
        "summary": {
            "total_over_streaks": 15,
            "total_under_streaks": 12,
            "longest_over": 8,
            "longest_under": 7
        }
    }
    """

    def __init__(self, min_streak_length: int = 4, **kwargs):
        """
        Initialize StreaksExporter.

        Args:
            min_streak_length: Minimum streak length to include (default: 4)
        """
        super().__init__(**kwargs)
        self.min_streak_length = min_streak_length

    def generate_json(self, as_of_date: str) -> Dict[str, Any]:
        """
        Generate streaks JSON.

        Args:
            as_of_date: Date to calculate streaks as of (YYYY-MM-DD)

        Returns:
            Dictionary ready for JSON serialization
        """
        # Get all streaks
        over_streaks = self._query_over_under_streaks(as_of_date, streak_type='OVER')
        under_streaks = self._query_over_under_streaks(as_of_date, streak_type='UNDER')
        prediction_streaks = self._query_prediction_streaks(as_of_date)

        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'min_streak_length': self.min_streak_length,
            'streaks': {
                'over': over_streaks,
                'under': under_streaks,
                'prediction_hits': prediction_streaks
            },
            'summary': {
                'total_over_streaks': len(over_streaks),
                'total_under_streaks': len(under_streaks),
                'total_prediction_streaks': len(prediction_streaks),
                'longest_over': max([s['streak_length'] for s in over_streaks], default=0),
                'longest_under': max([s['streak_length'] for s in under_streaks], default=0),
                'longest_prediction': max([s['streak_length'] for s in prediction_streaks], default=0)
            }
        }

    def _query_over_under_streaks(self, as_of_date: str, streak_type: str) -> List[Dict]:
        """
        Query players on OVER or UNDER streaks.

        Uses a window function to identify consecutive games with the same result.

        Args:
            as_of_date: Date to calculate streaks as of
            streak_type: 'OVER' or 'UNDER'

        Returns:
            List of players on streaks
        """
        query = """
        WITH recent_games AS (
            -- Get recent games for all players with lines
            SELECT
                g.player_lookup,
                g.game_date,
                g.points,
                g.points_line,
                g.over_under_result,
                g.opponent_team_abbr,
                g.team_abbr,
                ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as game_num
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            WHERE g.game_date <= @as_of_date
              AND g.over_under_result IS NOT NULL
              AND g.season_year = CASE
                WHEN EXTRACT(MONTH FROM @as_of_date) >= 10 THEN EXTRACT(YEAR FROM @as_of_date)
                ELSE EXTRACT(YEAR FROM @as_of_date) - 1
              END
        ),
        streak_calc AS (
            -- Identify where streaks break
            SELECT
                player_lookup,
                game_date,
                points,
                points_line,
                over_under_result,
                opponent_team_abbr,
                team_abbr,
                game_num,
                CASE WHEN over_under_result = @streak_type THEN 0 ELSE 1 END as streak_break
            FROM recent_games
            WHERE game_num <= 20  -- Only look at last 20 games
        ),
        current_streak AS (
            -- Get current streak length (games from most recent until first break)
            SELECT
                player_lookup,
                COUNT(*) as streak_length,
                ROUND(AVG(points - points_line), 1) as avg_margin,
                ARRAY_AGG(STRUCT(
                    game_date,
                    points,
                    points_line,
                    opponent_team_abbr
                ) ORDER BY game_date DESC) as games
            FROM streak_calc
            WHERE game_num <= (
                -- Find first break position
                SELECT COALESCE(MIN(game_num), 21) - 1
                FROM streak_calc s2
                WHERE s2.player_lookup = streak_calc.player_lookup
                  AND s2.streak_break = 1
            )
              AND streak_break = 0
            GROUP BY player_lookup
            HAVING COUNT(*) >= @min_streak
        ),
        player_info AS (
            SELECT DISTINCT player_lookup, player_name, team_abbr
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            WHERE season = CASE
                WHEN EXTRACT(MONTH FROM @as_of_date) >= 10
                THEN CONCAT(EXTRACT(YEAR FROM @as_of_date), '-', SUBSTR(CAST(EXTRACT(YEAR FROM @as_of_date) + 1 AS STRING), 3, 2))
                ELSE CONCAT(EXTRACT(YEAR FROM @as_of_date) - 1, '-', SUBSTR(CAST(EXTRACT(YEAR FROM @as_of_date) AS STRING), 3, 2))
              END
        )
        SELECT
            cs.player_lookup,
            COALESCE(pi.player_name, cs.player_lookup) as player_full_name,
            COALESCE(pi.team_abbr, '') as team,
            cs.streak_length,
            cs.avg_margin,
            cs.games
        FROM current_streak cs
        LEFT JOIN player_info pi ON cs.player_lookup = pi.player_lookup
        ORDER BY cs.streak_length DESC, cs.avg_margin DESC
        LIMIT 50
        """

        params = [
            bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date),
            bigquery.ScalarQueryParameter('streak_type', 'STRING', streak_type),
            bigquery.ScalarQueryParameter('min_streak', 'INT64', self.min_streak_length)
        ]

        results = self.query_to_list(query, params)

        # Format results
        formatted = []
        for r in results:
            games = r.get('games', [])
            formatted.append({
                'player_lookup': r['player_lookup'],
                'player_full_name': r['player_full_name'],
                'team': r['team'],
                'streak_length': r['streak_length'],
                'avg_margin': safe_float(r['avg_margin']),
                'games': [
                    {
                        'game_date': str(g['game_date']),
                        'points': g['points'],
                        'line': safe_float(g['points_line']),
                        'opponent': g['opponent_team_abbr']
                    }
                    for g in games[:5]  # Only include last 5 games in output
                ]
            })

        return formatted

    def _query_prediction_streaks(self, as_of_date: str) -> List[Dict]:
        """
        Query players where our predictions have been correct consecutively.

        A "prediction hit" means our recommendation (OVER/UNDER) matched the outcome.

        Args:
            as_of_date: Date to calculate streaks as of

        Returns:
            List of players with prediction streaks
        """
        query = """
        WITH recent_predictions AS (
            SELECT
                a.player_lookup,
                a.game_date,
                a.recommendation,
                a.actual_points,
                a.prediction_correct,
                ROW_NUMBER() OVER (PARTITION BY a.player_lookup ORDER BY a.game_date DESC) as pred_num
            FROM `nba-props-platform.nba_predictions.prediction_accuracy` a
            WHERE a.game_date <= @as_of_date
              AND a.system_id = 'catboost_v9'
              AND a.recommendation IN ('OVER', 'UNDER')  -- Only actionable predictions
        ),
        streak_calc AS (
            SELECT
                player_lookup,
                game_date,
                recommendation,
                actual_points,
                prediction_correct,
                pred_num,
                CASE WHEN prediction_correct = TRUE THEN 0 ELSE 1 END as streak_break
            FROM recent_predictions
            WHERE pred_num <= 20
        ),
        current_streak AS (
            SELECT
                player_lookup,
                COUNT(*) as streak_length
            FROM streak_calc
            WHERE pred_num <= (
                SELECT COALESCE(MIN(pred_num), 21) - 1
                FROM streak_calc s2
                WHERE s2.player_lookup = streak_calc.player_lookup
                  AND s2.streak_break = 1
            )
              AND streak_break = 0
            GROUP BY player_lookup
            HAVING COUNT(*) >= @min_streak
        ),
        player_info AS (
            SELECT DISTINCT player_lookup, player_name, team_abbr
            FROM `nba-props-platform.nba_reference.nba_players_registry`
            WHERE season = CASE
                WHEN EXTRACT(MONTH FROM @as_of_date) >= 10
                THEN CONCAT(EXTRACT(YEAR FROM @as_of_date), '-', SUBSTR(CAST(EXTRACT(YEAR FROM @as_of_date) + 1 AS STRING), 3, 2))
                ELSE CONCAT(EXTRACT(YEAR FROM @as_of_date) - 1, '-', SUBSTR(CAST(EXTRACT(YEAR FROM @as_of_date) AS STRING), 3, 2))
              END
        )
        SELECT
            cs.player_lookup,
            COALESCE(pi.player_name, cs.player_lookup) as player_full_name,
            COALESCE(pi.team_abbr, '') as team,
            cs.streak_length
        FROM current_streak cs
        LEFT JOIN player_info pi ON cs.player_lookup = pi.player_lookup
        ORDER BY cs.streak_length DESC
        LIMIT 30
        """

        params = [
            bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date),
            bigquery.ScalarQueryParameter('min_streak', 'INT64', self.min_streak_length)
        ]

        results = self.query_to_list(query, params)

        return [
            {
                'player_lookup': r['player_lookup'],
                'player_full_name': r['player_full_name'],
                'team': r['team'],
                'streak_length': r['streak_length'],
                'streak_type': 'prediction_hits'
            }
            for r in results
        ]

    def export(self, as_of_date: str = None) -> str:
        """
        Generate and upload streaks JSON.

        Args:
            as_of_date: Date to calculate streaks as of (default: today)

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting streaks as of {as_of_date}")

        json_data = self.generate_json(as_of_date)

        path = f'streaks/today.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=3600')

        return gcs_path
