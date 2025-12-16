"""
What Matters Most Exporter for Trends v2

Analyzes how different factors (rest, home/away, B2B) impact
different player archetypes (stars, scorers, rotation, role players).

Output: /v1/trends/what-matters.json
Refresh: Weekly (Monday 6 AM)
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class WhatMattersExporter(BaseExporter):
    """
    Export factor impact analysis by player archetype.

    JSON structure:
    {
        "generated_at": "...",
        "as_of_date": "2024-12-15",
        "archetypes": {
            "star": {
                "description": "22+ PPG players",
                "player_count": 35,
                "example_players": ["LeBron James", "Luka Doncic"],
                "factors": {
                    "rest": {...},
                    "home_away": {...},
                    "back_to_back": {...}
                }
            },
            ...
        },
        "key_insights": [
            "Stars hit 50.8% on back-to-backs vs 48.6% rested - lines adjust",
            "Role players significantly underperform (39.7% hit rate)",
            ...
        ]
    }
    """

    # Archetype definitions (PPG-based since usage_rate not available)
    ARCHETYPES = {
        'star': {'min_ppg': 22, 'description': '22+ PPG stars'},
        'scorer': {'min_ppg': 15, 'max_ppg': 22, 'description': '15-22 PPG scorers'},
        'rotation': {'min_ppg': 8, 'max_ppg': 15, 'description': '8-15 PPG rotation'},
        'role_player': {'max_ppg': 8, 'description': 'Under 8 PPG role players'}
    }

    def generate_json(self, as_of_date: str = None) -> Dict[str, Any]:
        """
        Generate what matters most JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary ready for JSON serialization
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Generating what matters most as of {as_of_date}")

        # Get archetype data with factor impacts
        archetypes = self._query_archetype_factors(as_of_date)

        # Generate key insights
        key_insights = self._generate_insights(archetypes)

        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'archetypes': archetypes,
            'key_insights': key_insights
        }

    def _query_archetype_factors(self, as_of_date: str) -> Dict[str, Dict]:
        """Query factor impacts for each archetype."""
        # Query totals
        totals_query = """
        WITH player_archetypes AS (
            SELECT
                player_lookup,
                CASE
                    WHEN AVG(points) >= 22 THEN 'star'
                    WHEN AVG(points) >= 15 THEN 'scorer'
                    WHEN AVG(points) >= 8 THEN 'rotation'
                    ELSE 'role_player'
                END as archetype
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 365 DAY)
              AND game_date <= @as_of_date
            GROUP BY player_lookup
            HAVING COUNT(*) >= 20
        ),
        games_with_archetype AS (
            SELECT
                g.player_lookup,
                pa.archetype,
                g.over_under_result
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            JOIN player_archetypes pa ON g.player_lookup = pa.player_lookup
            WHERE g.game_date >= DATE_SUB(@as_of_date, INTERVAL 365 DAY)
              AND g.game_date <= @as_of_date
              AND g.over_under_result IN ('OVER', 'UNDER')
        )
        SELECT
            archetype,
            COUNT(DISTINCT player_lookup) as player_count,
            COUNT(*) as total_games,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as overall_over_pct
        FROM games_with_archetype
        GROUP BY archetype
        """

        # Query rest impact
        rest_query = """
        WITH player_archetypes AS (
            SELECT
                player_lookup,
                CASE
                    WHEN AVG(points) >= 22 THEN 'star'
                    WHEN AVG(points) >= 15 THEN 'scorer'
                    WHEN AVG(points) >= 8 THEN 'rotation'
                    ELSE 'role_player'
                END as archetype
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 365 DAY)
              AND game_date <= @as_of_date
            GROUP BY player_lookup
            HAVING COUNT(*) >= 20
        ),
        games_with_rest AS (
            SELECT
                pa.archetype,
                g.over_under_result,
                DATE_DIFF(g.game_date, LAG(g.game_date) OVER (PARTITION BY g.player_lookup ORDER BY g.game_date), DAY) - 1 as rest_days
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            JOIN player_archetypes pa ON g.player_lookup = pa.player_lookup
            WHERE g.game_date >= DATE_SUB(@as_of_date, INTERVAL 365 DAY)
              AND g.game_date <= @as_of_date
              AND g.over_under_result IN ('OVER', 'UNDER')
        )
        SELECT
            archetype,
            CASE
                WHEN rest_days = 0 THEN 'b2b'
                WHEN rest_days = 1 THEN 'one_day'
                WHEN rest_days >= 2 THEN 'rested'
            END as rest_category,
            COUNT(*) as games,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct
        FROM games_with_rest
        WHERE rest_days IS NOT NULL
        GROUP BY archetype, rest_category
        HAVING COUNT(*) >= 20
        """

        # Query home/away impact
        home_away_query = """
        WITH player_archetypes AS (
            SELECT
                player_lookup,
                CASE
                    WHEN AVG(points) >= 22 THEN 'star'
                    WHEN AVG(points) >= 15 THEN 'scorer'
                    WHEN AVG(points) >= 8 THEN 'rotation'
                    ELSE 'role_player'
                END as archetype
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 365 DAY)
              AND game_date <= @as_of_date
            GROUP BY player_lookup
            HAVING COUNT(*) >= 20
        ),
        games_with_location AS (
            SELECT
                pa.archetype,
                g.over_under_result,
                t.home_game
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            JOIN player_archetypes pa ON g.player_lookup = pa.player_lookup
            JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
              ON g.game_date = t.game_date AND g.team_abbr = t.team_abbr
            WHERE g.game_date >= DATE_SUB(@as_of_date, INTERVAL 365 DAY)
              AND g.game_date <= @as_of_date
              AND g.over_under_result IN ('OVER', 'UNDER')
        )
        SELECT
            archetype,
            CASE WHEN home_game THEN 'home' ELSE 'away' END as location,
            COUNT(*) as games,
            ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct
        FROM games_with_location
        GROUP BY archetype, home_game
        HAVING COUNT(*) >= 50
        """

        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]

        # Execute queries
        totals_results = self.query_to_list(totals_query, params)
        rest_results = self.query_to_list(rest_query, params)
        home_away_results = self.query_to_list(home_away_query, params)

        # Get example players
        example_query = """
        WITH player_archetypes AS (
            SELECT
                player_lookup,
                AVG(points) as avg_ppg,
                CASE
                    WHEN AVG(points) >= 22 THEN 'star'
                    WHEN AVG(points) >= 15 THEN 'scorer'
                    WHEN AVG(points) >= 8 THEN 'rotation'
                    ELSE 'role_player'
                END as archetype
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND game_date <= @as_of_date
            GROUP BY player_lookup
            HAVING COUNT(*) >= 10
        )
        SELECT
            pa.archetype,
            pn.player_name,
            pa.avg_ppg
        FROM player_archetypes pa
        JOIN `nba-props-platform.nba_reference.nba_players_registry` pn
          ON pa.player_lookup = pn.player_lookup
        QUALIFY ROW_NUMBER() OVER (PARTITION BY pa.archetype, pn.player_lookup ORDER BY pa.avg_ppg DESC) = 1
        ORDER BY pa.archetype, pa.avg_ppg DESC
        """
        example_results = self.query_to_list(example_query, params)

        # Build examples dict
        examples_by_archetype = {}
        for r in example_results:
            arch = r['archetype']
            if arch not in examples_by_archetype:
                examples_by_archetype[arch] = []
            examples_by_archetype[arch].append(r['player_name'])

        # Build archetypes dict
        archetypes = {}
        for archetype_name, config in self.ARCHETYPES.items():
            archetypes[archetype_name] = {
                'description': config['description'],
                'player_count': 0,
                'example_players': examples_by_archetype.get(archetype_name, []),
                'overall_over_pct': None,
                'factors': {
                    'rest': {},
                    'home_away': {}
                }
            }

        # Populate totals
        for r in totals_results:
            arch = r['archetype']
            if arch in archetypes:
                archetypes[arch]['player_count'] = r['player_count']
                archetypes[arch]['overall_over_pct'] = self._safe_float(r['overall_over_pct'])

        # Populate rest factors
        for r in rest_results:
            arch = r['archetype']
            if arch in archetypes and r['rest_category']:
                archetypes[arch]['factors']['rest'][r['rest_category']] = {
                    'games': r['games'],
                    'over_pct': self._safe_float(r['over_pct'])
                }

        # Populate home/away factors
        for r in home_away_results:
            arch = r['archetype']
            if arch in archetypes:
                archetypes[arch]['factors']['home_away'][r['location']] = {
                    'games': r['games'],
                    'over_pct': self._safe_float(r['over_pct'])
                }

        return archetypes

    def _generate_insights(self, archetypes: Dict) -> List[str]:
        """Generate key insights from the data."""
        insights = []

        # Compare archetypes
        star_pct = archetypes.get('star', {}).get('overall_over_pct')
        role_pct = archetypes.get('role_player', {}).get('overall_over_pct')

        if star_pct and role_pct:
            diff = star_pct - role_pct
            if abs(diff) >= 5:
                if diff > 0:
                    insights.append(f"Stars significantly outperform role players ({star_pct}% vs {role_pct}% hit rate)")
                else:
                    insights.append(f"Role players surprisingly outperform stars ({role_pct}% vs {star_pct}% hit rate)")

        # B2B impact for stars
        star_factors = archetypes.get('star', {}).get('factors', {}).get('rest', {})
        b2b = star_factors.get('b2b', {})
        rested = star_factors.get('rested', {})

        if b2b.get('over_pct') and rested.get('over_pct'):
            b2b_pct = b2b['over_pct']
            rested_pct = rested['over_pct']
            diff = b2b_pct - rested_pct
            if abs(diff) >= 2:
                direction = "better" if diff > 0 else "worse"
                insights.append(f"Stars perform {direction} on B2Bs ({b2b_pct}% vs {rested_pct}% on 2+ rest)")

        # Home/away for any archetype with significant diff
        for arch_name, arch_data in archetypes.items():
            home_away = arch_data.get('factors', {}).get('home_away', {})
            home = home_away.get('home', {})
            away = home_away.get('away', {})

            if home.get('over_pct') and away.get('over_pct'):
                diff = home['over_pct'] - away['over_pct']
                if abs(diff) >= 3:
                    direction = "home" if diff > 0 else "road"
                    insights.append(f"{arch_name.replace('_', ' ').title()}s perform better at {direction} ({max(home['over_pct'], away['over_pct'])}% vs {min(home['over_pct'], away['over_pct'])}%)")

        # If no insights, add a generic one
        if not insights:
            insights.append("No significant factor differences detected in current sample")

        return insights[:5]  # Limit to 5 insights

    def _safe_float(self, value) -> Optional[float]:
        """Convert to float, handling None and special values."""
        if value is None:
            return None
        try:
            f = float(value)
            if f != f:  # NaN check
                return None
            return round(f, 1)
        except (TypeError, ValueError):
            return None

    def export(self, as_of_date: str = None) -> str:
        """
        Generate and upload what matters most JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting what matters most as of {as_of_date}")

        json_data = self.generate_json(as_of_date)

        path = 'trends/what-matters.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=43200')  # 12 hour cache

        logger.info(f"Exported what matters most to {gcs_path}")
        return gcs_path
