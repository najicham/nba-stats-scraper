"""
News Exporter for Phase 6 Publishing

Exports player news articles to GCS as JSON for frontend consumption.
Follows the schema defined in docs/api/NEWS_API_REFERENCE.md and
frontend handoff in props-web/docs/08-projects/current/news-integration/BACKEND_HANDOFF.md

Output files:
- player-news/{player_lookup}.json - News for a specific player
- player-news/tonight-summary.json - Quick lookup for all tonight's players
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

from google.cloud import bigquery

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)

# Source display name mapping
SOURCE_DISPLAY_NAMES = {
    'espn_nba': 'ESPN',
    'espn_mlb': 'ESPN',
    'cbs_nba': 'CBS Sports',
    'cbs_mlb': 'CBS Sports',
    'yahoo_nba': 'Yahoo Sports',
    'yahoo_mlb': 'Yahoo Sports',
    # RotoWire disabled - RSS feeds discontinued Jan 2026
}

# Impact level mapping based on category
CATEGORY_IMPACT = {
    'injury': 'high',
    'trade': 'high',
    'suspension': 'high',
    'signing': 'medium',
    'lineup': 'medium',
    'performance': 'low',
    'preview': 'low',
    'recap': 'low',
    'analysis': 'low',
    'other': 'low',
}

# Categories considered critical for indicators
CRITICAL_CATEGORIES = {'injury', 'trade', 'suspension'}


class NewsExporter(BaseExporter):
    """
    Export player news to GCS JSON files.

    Generates:
    1. Individual player news files: player-news/{player_lookup}.json
    2. Tonight summary file: player-news/tonight-summary.json

    Cache settings:
    - Individual player files: 15 minutes
    - Tonight summary: 5 minutes
    """

    def __init__(self, sport: str = 'nba', **kwargs):
        super().__init__(**kwargs)
        self.sport = sport

    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """
        Default implementation - exports tonight summary.
        Use export_player() for individual players.
        """
        return self.generate_tonight_summary()

    def export(self, target_date: Optional[str] = None, **kwargs) -> str:
        """
        Export tonight summary to GCS.

        Args:
            target_date: Optional date string (YYYY-MM-DD), defaults to today

        Returns:
            GCS path of uploaded file
        """
        data = self.generate_tonight_summary()
        # Use sport-specific path to avoid NBA/MLB overwriting each other
        path = f'player-news/{self.sport}/tonight-summary.json'
        return self.upload_to_gcs(data, path, cache_control='public, max-age=300')

    def export_player(self, player_lookup: str) -> str:
        """
        Export news for a specific player to GCS.

        Args:
            player_lookup: Player lookup key (e.g., 'lebronjames')

        Returns:
            GCS path of uploaded file
        """
        data = self.generate_player_json(player_lookup)
        # Use sport-specific path
        path = f'player-news/{self.sport}/{player_lookup}.json'
        return self.upload_to_gcs(data, path, cache_control='public, max-age=900')

    def export_all_players(self, limit: int = 500) -> List[str]:
        """
        Export news for all players with news articles.

        Args:
            limit: Max number of players to export

        Returns:
            List of GCS paths
        """
        players = self._get_players_with_news(limit=limit)
        paths = []

        for i, player in enumerate(players):
            try:
                path = self.export_player(player['player_lookup'])
                paths.append(path)
                if (i + 1) % 50 == 0:
                    logger.info(f"Exported {i + 1}/{len(players)} players")
            except Exception as e:
                logger.error(f"Failed to export {player['player_lookup']}: {e}")

        logger.info(f"Exported news for {len(paths)} players")
        return paths

    def export_incremental(self, minutes_back: int = 20) -> List[str]:
        """
        Export news only for players with recent article links.

        This is more efficient than export_all_players when called frequently,
        as it only re-exports players who have new content.

        Args:
            minutes_back: Only export players with links created in the last N minutes

        Returns:
            List of GCS paths (always includes tonight-summary)
        """
        paths = []

        # Always export tonight summary (lightweight)
        try:
            path = self.export()
            paths.append(path)
            logger.info(f"Exported tonight-summary.json")
        except Exception as e:
            logger.error(f"Failed to export tonight summary: {e}")

        # Get players with recently created links
        players = self._get_players_with_recent_news(minutes_back=minutes_back)

        if not players:
            logger.info(f"No players with new links in last {minutes_back} minutes")
            return paths

        logger.info(f"Found {len(players)} players with recent news to export")

        for player in players:
            try:
                path = self.export_player(player['player_lookup'])
                paths.append(path)
            except Exception as e:
                logger.error(f"Failed to export {player['player_lookup']}: {e}")

        logger.info(f"Incremental export complete: {len(paths)} files")
        return paths

    def _get_players_with_recent_news(self, minutes_back: int = 20) -> List[Dict]:
        """Get players who have new article links in the last N minutes."""
        query = """
        SELECT DISTINCT player_lookup
        FROM `nba-props-platform.nba_analytics.news_player_links`
        WHERE sport = @sport
          AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @minutes MINUTE)
        ORDER BY player_lookup
        """

        params = [
            bigquery.ScalarQueryParameter('sport', 'STRING', self.sport),
            bigquery.ScalarQueryParameter('minutes', 'INT64', minutes_back),
        ]

        return self.query_to_list(query, params)

    def generate_player_json(self, player_lookup: str) -> Dict[str, Any]:
        """
        Generate JSON for a specific player's news.

        Schema matches frontend handoff specification.
        """
        articles = self._query_player_articles(player_lookup)

        # Get player info
        player_info = self._get_player_info(player_lookup)
        player_name = player_info.get('player_full_name', player_lookup)
        team_abbr = player_info.get('team_abbr', '')

        # Process articles
        formatted_articles = []
        has_critical_news = False
        critical_category = None

        for article in articles:
            category = article.get('category', 'other')
            impact = CATEGORY_IMPACT.get(category, 'low')

            # Check for critical news
            if category in CRITICAL_CATEGORIES and not has_critical_news:
                has_critical_news = True
                critical_category = category

            formatted_articles.append({
                'id': article['article_id'],
                'headline': article.get('headline') or self._create_headline(article['title']),
                'title': article['title'],
                'summary': article.get('ai_summary') or article.get('summary', ''),
                'category': category,
                'impact': impact,
                'source': SOURCE_DISPLAY_NAMES.get(article['source'], article['source']),
                'source_url': article.get('source_url', ''),
                'published_at': self._format_timestamp(article.get('published_at')),
                'is_primary_mention': article.get('mention_role') == 'primary',
            })

        return {
            'player_lookup': player_lookup,
            'player_name': player_name,
            'team_abbr': team_abbr,
            'sport': self.sport,
            'updated_at': self.get_generated_at(),
            'has_critical_news': has_critical_news,
            'critical_category': critical_category,
            'news_count': len(formatted_articles),
            'articles': formatted_articles,
        }

    def generate_tonight_summary(self) -> Dict[str, Any]:
        """
        Generate lightweight summary for all players with news.

        Used for quick checks without loading full article data.
        Returns just player_lookup and critical news status.
        """
        summaries = self._query_news_summaries()

        players = []
        for row in summaries:
            # Check if any category is critical
            categories = row.get('categories', [])
            has_critical = any(cat in CRITICAL_CATEGORIES for cat in categories)
            critical_cat = next((cat for cat in categories if cat in CRITICAL_CATEGORIES), None)

            players.append({
                'player_lookup': row['player_lookup'],
                'has_critical_news': has_critical,
                'critical_category': critical_cat,
                'news_count': row['article_count'],
                'latest_category': categories[0] if categories else None,
            })

        return {
            'updated_at': self.get_generated_at(),
            'sport': self.sport,
            'total_players': len(players),
            'players': players,
        }

    def _query_player_articles(self, player_lookup: str, limit: int = 20) -> List[Dict]:
        """Query articles for a specific player."""
        query = """
        SELECT
            l.article_id,
            a.title,
            a.summary,
            a.source,
            a.source_url,
            a.published_at,
            l.mention_role,
            i.category,
            i.ai_summary,
            i.headline,
            i.subcategory
        FROM `nba-props-platform.nba_analytics.news_player_links` l
        JOIN `nba-props-platform.nba_raw.news_articles_raw` a
            ON l.article_id = a.article_id
        LEFT JOIN `nba-props-platform.nba_analytics.news_insights` i
            ON l.article_id = i.article_id
        WHERE l.player_lookup = @player_lookup
            AND l.sport = @sport
        ORDER BY a.published_at DESC
        LIMIT @limit
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
            bigquery.ScalarQueryParameter('sport', 'STRING', self.sport),
            bigquery.ScalarQueryParameter('limit', 'INT64', limit),
        ]

        return self.query_to_list(query, params)

    def _query_news_summaries(self, hours_back: int = 72) -> List[Dict]:
        """Query summary of news per player for tonight-summary endpoint."""
        query = """
        SELECT
            l.player_lookup,
            COUNT(*) as article_count,
            ARRAY_AGG(DISTINCT i.category ORDER BY i.category) as categories
        FROM `nba-props-platform.nba_analytics.news_player_links` l
        LEFT JOIN `nba-props-platform.nba_analytics.news_insights` i
            ON l.article_id = i.article_id
        WHERE l.sport = @sport
            AND l.created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        GROUP BY l.player_lookup
        ORDER BY article_count DESC
        """

        params = [
            bigquery.ScalarQueryParameter('sport', 'STRING', self.sport),
            bigquery.ScalarQueryParameter('hours', 'INT64', hours_back),
        ]

        return self.query_to_list(query, params)

    def _get_players_with_news(self, limit: int = 500) -> List[Dict]:
        """Get list of players who have news articles."""
        query = """
        SELECT DISTINCT player_lookup
        FROM `nba-props-platform.nba_analytics.news_player_links`
        WHERE sport = @sport
        ORDER BY player_lookup
        LIMIT @limit
        """

        params = [
            bigquery.ScalarQueryParameter('sport', 'STRING', self.sport),
            bigquery.ScalarQueryParameter('limit', 'INT64', limit),
        ]

        return self.query_to_list(query, params)

    def _get_player_info(self, player_lookup: str) -> Dict:
        """Get player info from registry."""
        query = """
        SELECT
            player_lookup,
            player_name as player_full_name,
            team_abbr
        FROM `nba-props-platform.nba_reference.nba_players_registry`
        WHERE player_lookup = @player_lookup
        ORDER BY season DESC
        LIMIT 1
        """

        params = [
            bigquery.ScalarQueryParameter('player_lookup', 'STRING', player_lookup),
        ]

        results = self.query_to_list(query, params)
        return results[0] if results else {'player_lookup': player_lookup}

    def _create_headline(self, title: str) -> str:
        """Create short headline from title, max 50 chars."""
        if not title:
            return ''
        if len(title) <= 50:
            return title
        # Truncate at word boundary
        truncated = title[:47]
        last_space = truncated.rfind(' ')
        if last_space > 30:
            truncated = truncated[:last_space]
        return truncated + '...'

    def _format_timestamp(self, ts) -> Optional[str]:
        """Format timestamp to ISO string."""
        if ts is None:
            return None
        if hasattr(ts, 'isoformat'):
            return ts.isoformat()
        return str(ts)

    def _safe_float(self, val, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default


def test_news_exporter():
    """Test the news exporter locally."""
    logging.basicConfig(level=logging.INFO)

    exporter = NewsExporter(sport='nba')

    # Test tonight summary
    print("\n=== Tonight Summary ===")
    summary = exporter.generate_tonight_summary()
    print(f"Total players with news: {summary['total_players']}")
    for p in summary['players'][:5]:
        print(f"  {p['player_lookup']}: {p['news_count']} articles, critical={p['has_critical_news']}")

    # Test single player
    if summary['players']:
        player = summary['players'][0]['player_lookup']
        print(f"\n=== Player: {player} ===")
        player_data = exporter.generate_player_json(player)
        print(f"Name: {player_data['player_name']}")
        print(f"Team: {player_data['team_abbr']}")
        print(f"Has critical news: {player_data['has_critical_news']}")
        print(f"Articles: {len(player_data['articles'])}")
        for a in player_data['articles'][:3]:
            print(f"  [{a['category']}] {a['headline']}")


if __name__ == '__main__':
    test_news_exporter()
