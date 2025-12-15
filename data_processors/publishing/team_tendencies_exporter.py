"""
Team Tendencies Exporter for Trends v2

Exports team-level tendencies that affect player prop outcomes:
- Pace (fastest/slowest teams)
- Defense by shot zone (paint, perimeter, mid-range)
- Home/away performance splits
- Back-to-back vulnerability

Output: /v1/trends/team-tendencies.json
Refresh: Bi-weekly (Monday 6 AM)
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class TeamTendenciesExporter(BaseExporter):
    """
    Export team tendencies affecting player props.

    JSON structure:
    {
        "generated_at": "...",
        "as_of_date": "2024-12-15",
        "pace": {
            "kings": [...],  # Top 5 fastest
            "grinders": [...]  # Top 5 slowest
        },
        "defense_by_zone": {
            "paint": {"best": [...], "worst": [...]},
            "perimeter": {"best": [...], "worst": [...]}
        },
        "home_away": {
            "home_dominant": [...],
            "road_warriors": [...]
        },
        "back_to_back": {
            "vulnerable": [...],  # Teams that struggle on B2B
            "resilient": [...]    # Teams that handle B2B well
        }
    }
    """

    def generate_json(self, as_of_date: str = None) -> Dict[str, Any]:
        """
        Generate team tendencies JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary ready for JSON serialization
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Generating team tendencies as of {as_of_date}")

        # Get all tendency data
        pace_data = self._query_pace_tendencies(as_of_date)
        defense_data = self._query_defense_by_zone(as_of_date)
        home_away_data = self._query_home_away_splits(as_of_date)
        b2b_data = self._query_b2b_impact(as_of_date)

        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'pace': pace_data,
            'defense_by_zone': defense_data,
            'home_away': home_away_data,
            'back_to_back': b2b_data
        }

    def _query_pace_tendencies(self, as_of_date: str) -> Dict[str, List[Dict]]:
        """Query pace kings and grinders."""
        query = """
        WITH team_pace AS (
            SELECT
                team_abbr,
                ROUND(AVG(pace), 2) as avg_pace,
                COUNT(*) as games,
                ROUND(AVG(points_scored), 1) as avg_points
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 30 DAY)
              AND game_date <= @as_of_date
            GROUP BY team_abbr
            HAVING COUNT(*) >= 5
        ),
        league_avg AS (
            SELECT AVG(avg_pace) as league_pace FROM team_pace
        )
        SELECT
            tp.team_abbr,
            tp.avg_pace,
            tp.games,
            tp.avg_points,
            ROUND(tp.avg_pace - la.league_pace, 2) as vs_league
        FROM team_pace tp, league_avg la
        ORDER BY tp.avg_pace DESC
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        if not results:
            return {'kings': [], 'grinders': []}

        # Top 5 fastest and slowest
        kings = [self._format_pace_team(r, 'fast') for r in results[:5]]
        grinders = [self._format_pace_team(r, 'slow') for r in results[-5:][::-1]]

        return {
            'kings': kings,
            'grinders': grinders,
            'league_average': round(sum(r['avg_pace'] for r in results) / len(results), 2) if results else None
        }

    def _format_pace_team(self, row: Dict, pace_type: str) -> Dict:
        """Format pace team entry."""
        return {
            'team': row['team_abbr'],
            'pace': self._safe_float(row['avg_pace']),
            'games': row['games'],
            'avg_points': self._safe_float(row['avg_points']),
            'vs_league': self._safe_float(row['vs_league']),
            'insight': f"{'High-scoring environment' if pace_type == 'fast' else 'Slower, grind-it-out games'}"
        }

    def _query_defense_by_zone(self, as_of_date: str) -> Dict[str, Dict[str, List]]:
        """Query defense effectiveness by shot zone."""
        query = """
        WITH defense_stats AS (
            SELECT
                team_abbr,
                ROUND(AVG(paint_pct_allowed_last_15), 3) as paint_dfg,
                ROUND(AVG(three_pt_pct_allowed_last_15), 3) as three_dfg,
                ROUND(AVG(mid_range_pct_allowed_last_15), 3) as mid_dfg,
                ROUND(AVG(opponent_points_per_game), 1) as opp_ppg,
                COUNT(*) as games
            FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date >= DATE_SUB(@as_of_date, INTERVAL 30 DAY)
              AND analysis_date <= @as_of_date
            GROUP BY team_abbr
            HAVING COUNT(*) >= 5
        )
        SELECT * FROM defense_stats
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        if not results:
            return {
                'paint': {'best': [], 'worst': []},
                'perimeter': {'best': [], 'worst': []}
            }

        # Sort by paint defense (lower is better)
        paint_sorted = sorted(results, key=lambda x: x['paint_dfg'] or 1.0)
        paint_best = [self._format_defense_team(r, 'paint', 'best') for r in paint_sorted[:5]]
        paint_worst = [self._format_defense_team(r, 'paint', 'worst') for r in paint_sorted[-5:][::-1]]

        # Sort by perimeter defense (lower is better)
        three_sorted = sorted(results, key=lambda x: x['three_dfg'] or 1.0)
        three_best = [self._format_defense_team(r, 'perimeter', 'best') for r in three_sorted[:5]]
        three_worst = [self._format_defense_team(r, 'perimeter', 'worst') for r in three_sorted[-5:][::-1]]

        return {
            'paint': {'best': paint_best, 'worst': paint_worst},
            'perimeter': {'best': three_best, 'worst': three_worst}
        }

    def _format_defense_team(self, row: Dict, zone: str, quality: str) -> Dict:
        """Format defense team entry."""
        dfg_key = 'paint_dfg' if zone == 'paint' else 'three_dfg'
        dfg_pct = row.get(dfg_key, 0) or 0

        if zone == 'paint':
            insight = f"{'Tough interior D - avoid paint scorers' if quality == 'best' else 'Weak interior D - target paint scorers'}"
        else:
            insight = f"{'Tough perimeter D - avoid shooters' if quality == 'best' else 'Weak perimeter D - target shooters'}"

        return {
            'team': row['team_abbr'],
            'dfg_pct': round(dfg_pct * 100, 1) if dfg_pct else None,
            'opp_ppg': self._safe_float(row['opp_ppg']),
            'games': row['games'],
            'insight': insight
        }

    def _query_home_away_splits(self, as_of_date: str) -> Dict[str, List[Dict]]:
        """Query home/away performance splits."""
        query = """
        WITH team_splits AS (
            SELECT
                team_abbr,
                AVG(CASE WHEN home_game THEN points_scored END) as home_ppg,
                AVG(CASE WHEN NOT home_game THEN points_scored END) as away_ppg,
                SUM(CASE WHEN home_game THEN 1 ELSE 0 END) as home_games,
                SUM(CASE WHEN NOT home_game THEN 1 ELSE 0 END) as away_games
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 60 DAY)
              AND game_date <= @as_of_date
            GROUP BY team_abbr
            HAVING SUM(CASE WHEN home_game THEN 1 ELSE 0 END) >= 5
               AND SUM(CASE WHEN NOT home_game THEN 1 ELSE 0 END) >= 5
        )
        SELECT
            team_abbr,
            ROUND(home_ppg, 1) as home_ppg,
            ROUND(away_ppg, 1) as away_ppg,
            ROUND(home_ppg - away_ppg, 1) as home_diff,
            home_games,
            away_games
        FROM team_splits
        ORDER BY home_ppg - away_ppg DESC
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        if not results:
            return {'home_dominant': [], 'road_warriors': []}

        # Teams with biggest home advantage
        home_dominant = [
            {
                'team': r['team_abbr'],
                'home_ppg': self._safe_float(r['home_ppg']),
                'away_ppg': self._safe_float(r['away_ppg']),
                'differential': self._safe_float(r['home_diff']),
                'insight': 'Much better at home - boost home player props'
            }
            for r in results[:5]
        ]

        # Teams that play well on the road (smallest or negative differential)
        road_warriors = [
            {
                'team': r['team_abbr'],
                'home_ppg': self._safe_float(r['home_ppg']),
                'away_ppg': self._safe_float(r['away_ppg']),
                'differential': self._safe_float(r['home_diff']),
                'insight': 'Consistent on the road - props less venue-dependent'
            }
            for r in results[-5:][::-1]
        ]

        return {
            'home_dominant': home_dominant,
            'road_warriors': road_warriors
        }

    def _query_b2b_impact(self, as_of_date: str) -> Dict[str, List[Dict]]:
        """Query back-to-back game impact by team."""
        query = """
        WITH games_with_rest AS (
            SELECT
                team_abbr,
                game_date,
                points_scored,
                DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY team_abbr ORDER BY game_date), DAY) as days_since_last
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND game_date <= @as_of_date
        ),
        team_b2b_stats AS (
            SELECT
                team_abbr,
                AVG(CASE WHEN days_since_last = 1 THEN points_scored END) as b2b_ppg,
                AVG(CASE WHEN days_since_last > 1 THEN points_scored END) as rested_ppg,
                COUNT(CASE WHEN days_since_last = 1 THEN 1 END) as b2b_games,
                COUNT(CASE WHEN days_since_last > 1 THEN 1 END) as rested_games
            FROM games_with_rest
            WHERE days_since_last IS NOT NULL
            GROUP BY team_abbr
            HAVING COUNT(CASE WHEN days_since_last = 1 THEN 1 END) >= 3
               AND COUNT(CASE WHEN days_since_last > 1 THEN 1 END) >= 5
        )
        SELECT
            team_abbr,
            ROUND(b2b_ppg, 1) as b2b_ppg,
            ROUND(rested_ppg, 1) as rested_ppg,
            ROUND(b2b_ppg - rested_ppg, 1) as b2b_impact,
            b2b_games,
            rested_games
        FROM team_b2b_stats
        ORDER BY b2b_ppg - rested_ppg ASC
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        if not results:
            return {'vulnerable': [], 'resilient': []}

        # Teams that struggle most on B2B (biggest negative impact)
        vulnerable = [
            {
                'team': r['team_abbr'],
                'b2b_ppg': self._safe_float(r['b2b_ppg']),
                'rested_ppg': self._safe_float(r['rested_ppg']),
                'impact': self._safe_float(r['b2b_impact']),
                'b2b_games': r['b2b_games'],
                'insight': 'Struggles on back-to-backs - fade player props'
            }
            for r in results[:5]
        ]

        # Teams that handle B2B well
        resilient = [
            {
                'team': r['team_abbr'],
                'b2b_ppg': self._safe_float(r['b2b_ppg']),
                'rested_ppg': self._safe_float(r['rested_ppg']),
                'impact': self._safe_float(r['b2b_impact']),
                'b2b_games': r['b2b_games'],
                'insight': 'Handles B2B well - props less affected by schedule'
            }
            for r in results[-5:][::-1]
        ]

        return {
            'vulnerable': vulnerable,
            'resilient': resilient
        }

    def _safe_float(self, value) -> Optional[float]:
        """Convert to float, handling None and special values."""
        if value is None:
            return None
        try:
            f = float(value)
            if f != f:  # NaN check
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    def export(self, as_of_date: str = None) -> str:
        """
        Generate and upload team tendencies JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting team tendencies as of {as_of_date}")

        json_data = self.generate_json(as_of_date)

        path = 'trends/team-tendencies.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=43200')  # 12 hour cache

        logger.info(f"Exported team tendencies to {gcs_path}")
        return gcs_path
