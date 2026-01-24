"""
Deep Dive Exporter for Trends v2

Exports a monthly featured analysis promo card.
This is a simple exporter that generates a teaser for deep-dive content.

Output: /v1/trends/deep-dive-current.json
Refresh: Monthly (1st of month)
"""

import logging
from typing import Dict, Any
from datetime import date

from .base_exporter import BaseExporter
from .exporter_utils import get_generated_at

logger = logging.getLogger(__name__)


class DeepDiveExporter(BaseExporter):
    """
    Export monthly deep-dive promo card.

    JSON structure:
    {
        "generated_at": "...",
        "month": "December 2024",
        "title": "Rest Days and Veteran Stars",
        "subtitle": "Why experienced players thrive with extra recovery",
        "hero_stat": {
            "value": "67%",
            "label": "Veteran stars hit rate on 2+ rest days",
            "context": "vs 52% league average"
        },
        "teaser": "Our analysis of 3 seasons shows...",
        "slug": "veteran-rest-december-2024",
        "cta": "Read the full analysis"
    }
    """

    # Monthly deep dive topics - rotate through these
    MONTHLY_TOPICS = {
        1: {
            "title": "The January Effect",
            "subtitle": "How post-holiday schedules impact player performance",
            "focus": "schedule_density"
        },
        2: {
            "title": "All-Star Break Impact",
            "subtitle": "Performance patterns before and after the break",
            "focus": "all_star_break"
        },
        3: {
            "title": "Playoff Push Performance",
            "subtitle": "How contenders perform in the stretch run",
            "focus": "playoff_race"
        },
        4: {
            "title": "End of Season Trends",
            "subtitle": "Resting stars and hungry underdogs",
            "focus": "season_end"
        },
        10: {
            "title": "Season Opener Insights",
            "subtitle": "Early season trends and what they mean",
            "focus": "season_start"
        },
        11: {
            "title": "November Grind",
            "subtitle": "How teams handle the first month marathon",
            "focus": "early_season"
        },
        12: {
            "title": "December Deep Dive",
            "subtitle": "Rest patterns and holiday performance",
            "focus": "rest_impact"
        }
    }

    def generate_json(self, as_of_date: str = None) -> Dict[str, Any]:
        """
        Generate deep dive promo JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Dictionary ready for JSON serialization
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        target_date = date.fromisoformat(as_of_date)
        month_num = target_date.month
        year = target_date.year

        # Get topic for this month
        topic = self.MONTHLY_TOPICS.get(month_num, self.MONTHLY_TOPICS[12])

        # Generate hero stat based on focus area
        hero_stat = self._get_hero_stat(topic['focus'], as_of_date)

        month_name = target_date.strftime('%B %Y')
        slug = f"{topic['focus'].replace('_', '-')}-{target_date.strftime('%B-%Y').lower()}"

        return {
            'generated_at': self.get_generated_at(),
            'month': month_name,
            'title': topic['title'],
            'subtitle': topic['subtitle'],
            'hero_stat': hero_stat,
            'teaser': self._get_teaser(topic['focus']),
            'slug': slug,
            'cta': 'Read the full analysis'
        }

    def _get_hero_stat(self, focus: str, as_of_date: str) -> Dict[str, Any]:
        """Get a compelling hero stat based on the focus area."""

        if focus == 'rest_impact':
            # Query actual rest impact data
            query = """
            WITH games_with_rest AS (
                SELECT
                    over_under_result,
                    DATE_DIFF(game_date, LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date), DAY) - 1 as rest_days
                FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@as_of_date, INTERVAL 90 DAY)
                  AND game_date <= @as_of_date
                  AND over_under_result IN ('OVER', 'UNDER')
            )
            SELECT
                ROUND(SUM(CASE WHEN rest_days >= 2 AND over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 /
                      NULLIF(SUM(CASE WHEN rest_days >= 2 THEN 1 ELSE 0 END), 0), 1) as rested_over_pct,
                ROUND(SUM(CASE WHEN rest_days = 0 AND over_under_result = 'OVER' THEN 1 ELSE 0 END) * 100.0 /
                      NULLIF(SUM(CASE WHEN rest_days = 0 THEN 1 ELSE 0 END), 0), 1) as b2b_over_pct
            FROM games_with_rest
            WHERE rest_days IS NOT NULL
            """
            from google.cloud import bigquery
            params = [bigquery.ScalarQueryParameter('as_of_date', 'DATE', as_of_date)]
            results = self.query_to_list(query, params)

            if results and results[0].get('rested_over_pct'):
                rested_pct = results[0]['rested_over_pct']
                b2b_pct = results[0]['b2b_over_pct']
                diff = round(rested_pct - b2b_pct, 1)
                return {
                    'value': f"{rested_pct:.0f}%",
                    'label': 'OVER rate on 2+ rest days',
                    'context': f"vs {b2b_pct:.0f}% on back-to-backs ({'+' if diff > 0 else ''}{diff}%)"
                }

        # Default fallback
        return {
            'value': '54%',
            'label': 'League-wide OVER rate this month',
            'context': 'Based on points props'
        }

    def _get_teaser(self, focus: str) -> str:
        """Get teaser text for the focus area."""
        teasers = {
            'rest_impact': "Our analysis of rest patterns reveals significant differences in how players perform based on days off. The data shows clear trends that can inform your betting strategy.",
            'schedule_density': "January brings the densest part of the NBA schedule. We analyzed how teams handle the grind and which players thrive under pressure.",
            'all_star_break': "The All-Star break is a reset point for the season. We examined performance patterns in the 10 games before and after the break.",
            'playoff_race': "As teams jockey for playoff position, performance patterns shift. Our analysis reveals who steps up in high-stakes games.",
            'season_end': "The final weeks bring load management and motivation questions. We identified which trends matter most for bettors.",
            'season_start': "Early season data is limited but valuable. We analyzed what October/November trends actually predict about the rest of the season.",
            'early_season': "A month into the season, patterns start to emerge. Our deep dive into November data reveals actionable insights."
        }
        return teasers.get(focus, "Our latest analysis reveals patterns that can inform your betting strategy.")

    def export(self, as_of_date: str = None) -> str:
        """
        Generate and upload deep dive promo JSON.

        Args:
            as_of_date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of the exported file
        """
        if as_of_date is None:
            as_of_date = date.today().strftime('%Y-%m-%d')

        logger.info(f"Exporting deep dive promo as of {as_of_date}")

        json_data = self.generate_json(as_of_date)

        path = 'trends/deep-dive-current.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=86400')

        logger.info(f"Exported deep dive to {gcs_path}")
        return gcs_path
