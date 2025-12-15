"""
Quick Hits Exporter for Trends v2

Exports 8 rotating quick stats/factoids about betting trends.
Each stat is a simple, digestible insight with supporting data.

Output: /v1/trends/quick-hits.json
Refresh: Weekly (Wednesday 8 AM)
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import date
import random

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class QuickHitsExporter(BaseExporter):
    """
    Export quick stats and betting insights.

    JSON structure:
    {
        "generated_at": "...",
        "as_of_date": "2024-12-15",
        "stats": [
            {
                "id": "sunday_overs",
                "category": "day_of_week",
                "headline": "Sunday Special",
                "stat": "54.2%",
                "description": "OVER hit rate on Sundays this season",
                "sample_size": 342,
                "trend": "positive",  # positive, negative, neutral
                "context": "vs 49.8% on other days"
            },
            ...
        ],
        "refresh_note": "Stats refresh every Wednesday"
    }
    """

    # Number of stats to include in output
    NUM_STATS = 8

    def generate_json(self, as_of_date: str = None) -> Dict[str, Any]:
        """
        Generate quick hits JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary ready for JSON serialization
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Generating quick hits as of {as_of_date}")

        # Generate all possible stats
        all_stats = []

        # Day of week stats
        all_stats.extend(self._query_day_of_week_stats(as_of_date))

        # Situational stats (B2B, rest, etc)
        all_stats.extend(self._query_situational_stats(as_of_date))

        # Home/away stats
        all_stats.extend(self._query_home_away_stats(as_of_date))

        # Scoring range stats
        all_stats.extend(self._query_scoring_range_stats(as_of_date))

        # Filter to stats with sufficient sample size and interesting findings
        valid_stats = [s for s in all_stats if s.get('sample_size', 0) >= 50]

        # Sort by "interestingness" (deviation from 50%)
        valid_stats.sort(key=lambda x: abs(float(x['stat'].rstrip('%')) - 50), reverse=True)

        # Take top N stats
        selected_stats = valid_stats[:self.NUM_STATS]

        return {
            'generated_at': self.get_generated_at(),
            'as_of_date': as_of_date,
            'stats': selected_stats,
            'total_available': len(valid_stats),
            'refresh_note': 'Stats refresh every Wednesday'
        }

    def _query_day_of_week_stats(self, as_of_date: str) -> List[Dict]:
        """Query OVER rate by day of week."""
        query = """
        WITH daily_stats AS (
            SELECT
                FORMAT_DATE('%A', game_date) as day_name,
                EXTRACT(DAYOFWEEK FROM game_date) as day_num,
                COUNT(*) as games,
                SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs,
                ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND game_date <= @as_of_date
              AND over_under_result IN ('OVER', 'UNDER')
            GROUP BY 1, 2
        ),
        overall AS (
            SELECT ROUND(AVG(over_pct), 1) as league_avg FROM daily_stats
        )
        SELECT d.*, o.league_avg
        FROM daily_stats d, overall o
        ORDER BY d.over_pct DESC
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        stats = []
        for r in results:
            pct = r['over_pct']
            league_avg = r['league_avg']
            diff = pct - league_avg

            if abs(diff) >= 2:  # Only include if meaningfully different
                trend = 'positive' if pct > 52 else 'negative' if pct < 48 else 'neutral'
                stats.append({
                    'id': f"{r['day_name'].lower()}_overs",
                    'category': 'day_of_week',
                    'headline': f"{r['day_name']} {'Surge' if diff > 0 else 'Slump'}",
                    'stat': f"{pct}%",
                    'description': f"OVER hit rate on {r['day_name']}s",
                    'sample_size': r['games'],
                    'trend': trend,
                    'context': f"vs {league_avg}% overall ({'+' if diff > 0 else ''}{diff:.1f}%)"
                })

        return stats

    def _query_situational_stats(self, as_of_date: str) -> List[Dict]:
        """Query situational stats (B2B, rest days, etc)."""
        query = """
        WITH games_with_rest AS (
            SELECT
                over_under_result,
                DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) - 1 as rest_days
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND game_date <= @as_of_date
              AND over_under_result IN ('OVER', 'UNDER')
        ),
        rest_stats AS (
            SELECT
                CASE
                    WHEN rest_days = 0 THEN 'b2b'
                    WHEN rest_days = 1 THEN 'one_day'
                    WHEN rest_days >= 2 THEN 'rested'
                END as rest_category,
                COUNT(*) as games,
                ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct
            FROM games_with_rest
            WHERE rest_days IS NOT NULL
            GROUP BY 1
        ),
        overall AS (
            SELECT ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as league_avg
            FROM games_with_rest WHERE rest_days IS NOT NULL
        )
        SELECT r.*, o.league_avg
        FROM rest_stats r, overall o
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        stats = []
        labels = {
            'b2b': ('Back-to-Back Blues', 'on back-to-back games'),
            'one_day': ('Standard Rest', 'with 1 day rest'),
            'rested': ('Fresh Legs', 'with 2+ days rest')
        }

        for r in results:
            if r['rest_category'] not in labels:
                continue

            pct = r['over_pct']
            league_avg = r['league_avg']
            diff = pct - league_avg
            headline, desc_suffix = labels[r['rest_category']]

            if abs(diff) >= 1.5:
                trend = 'positive' if pct > 52 else 'negative' if pct < 48 else 'neutral'
                stats.append({
                    'id': f"{r['rest_category']}_overs",
                    'category': 'situational',
                    'headline': headline,
                    'stat': f"{pct}%",
                    'description': f"OVER hit rate {desc_suffix}",
                    'sample_size': r['games'],
                    'trend': trend,
                    'context': f"vs {league_avg}% overall ({'+' if diff > 0 else ''}{diff:.1f}%)"
                })

        return stats

    def _query_home_away_stats(self, as_of_date: str) -> List[Dict]:
        """Query home vs away OVER rates by joining with team_offense_game_summary."""
        query = """
        WITH home_away AS (
            SELECT
                CASE WHEN t.home_game THEN 'home' ELSE 'away' END as location,
                COUNT(*) as games,
                ROUND(SUM(CASE WHEN p.over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct
            FROM `nba-props-platform.nba_analytics.player_game_summary` p
            JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
              ON p.game_date = t.game_date AND p.team_abbr = t.team_abbr
            WHERE p.game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND p.game_date <= @as_of_date
              AND p.over_under_result IN ('OVER', 'UNDER')
            GROUP BY 1
        )
        SELECT * FROM home_away
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        stats = []
        home_pct = None
        away_pct = None

        for r in results:
            if r['location'] == 'home':
                home_pct = r['over_pct']
            else:
                away_pct = r['over_pct']

        if home_pct and away_pct:
            diff = home_pct - away_pct
            if abs(diff) >= 2:
                better_loc = 'home' if diff > 0 else 'away'
                worse_loc = 'away' if diff > 0 else 'home'
                better_pct = home_pct if diff > 0 else away_pct

                stats.append({
                    'id': 'home_away_split',
                    'category': 'situational',
                    'headline': 'Home Court Advantage' if diff > 0 else 'Road Warriors',
                    'stat': f"{better_pct}%",
                    'description': f"OVER hit rate for {better_loc} players",
                    'sample_size': sum(r['games'] for r in results),
                    'trend': 'positive' if better_pct > 52 else 'neutral',
                    'context': f"vs {home_pct if diff < 0 else away_pct}% {worse_loc} ({abs(diff):.1f}% gap)"
                })

        return stats

    def _query_scoring_range_stats(self, as_of_date: str) -> List[Dict]:
        """Query OVER rates by player scoring tier."""
        query = """
        WITH player_tiers AS (
            SELECT
                player_lookup,
                AVG(points) as avg_ppg
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND game_date <= @as_of_date
            GROUP BY player_lookup
        ),
        games_with_tier AS (
            SELECT
                g.over_under_result,
                CASE
                    WHEN t.avg_ppg >= 22 THEN 'stars'
                    WHEN t.avg_ppg >= 15 THEN 'scorers'
                    WHEN t.avg_ppg >= 8 THEN 'rotation'
                    ELSE 'bench'
                END as tier
            FROM `nba-props-platform.nba_analytics.player_game_summary` g
            JOIN player_tiers t ON g.player_lookup = t.player_lookup
            WHERE g.game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
              AND g.game_date <= @as_of_date
              AND g.over_under_result IN ('OVER', 'UNDER')
        ),
        tier_stats AS (
            SELECT
                tier,
                COUNT(*) as games,
                ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as over_pct
            FROM games_with_tier
            GROUP BY tier
        ),
        overall AS (
            SELECT ROUND(SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as league_avg
            FROM games_with_tier
        )
        SELECT t.*, o.league_avg
        FROM tier_stats t, overall o
        """
        params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
        results = self.query_to_list(query, params)

        stats = []
        labels = {
            'stars': ('Star Power', '22+ PPG stars'),
            'scorers': ('Secondary Scorers', '15-22 PPG players'),
            'rotation': ('Rotation Players', '8-15 PPG players'),
            'bench': ('Bench Mob', 'under 8 PPG players')
        }

        for r in results:
            if r['tier'] not in labels:
                continue

            pct = r['over_pct']
            league_avg = r['league_avg']
            diff = pct - league_avg
            headline, desc = labels[r['tier']]

            if abs(diff) >= 2:
                trend = 'positive' if pct > 52 else 'negative' if pct < 48 else 'neutral'
                stats.append({
                    'id': f"{r['tier']}_overs",
                    'category': 'player_type',
                    'headline': headline,
                    'stat': f"{pct}%",
                    'description': f"OVER hit rate for {desc}",
                    'sample_size': r['games'],
                    'trend': trend,
                    'context': f"vs {league_avg}% overall ({'+' if diff > 0 else ''}{diff:.1f}%)"
                })

        return stats

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
        Generate and upload quick hits JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting quick hits as of {as_of_date}")

        json_data = self.generate_json(as_of_date)

        path = 'trends/quick-hits.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=43200')  # 12 hour cache

        logger.info(f"Exported quick hits to {gcs_path}")
        return gcs_path
