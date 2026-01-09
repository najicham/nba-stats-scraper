#!/usr/bin/env python3
"""
Storage module for news articles.

Handles saving articles to BigQuery and checking for duplicates.
"""

import json
import logging
from typing import List, Optional, Set
from datetime import datetime, timezone

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from scrapers.news.rss_fetcher import NewsArticle

logger = logging.getLogger(__name__)

# BigQuery configuration
PROJECT_ID = "nba-props-platform"
DATASET_ID = "nba_raw"
TABLE_ID = "news_articles_raw"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

# Schema definition for news_articles_raw table
# Schema for news_insights table (extraction results)
NEWS_INSIGHTS_SCHEMA = [
    bigquery.SchemaField("article_id", "STRING", mode="REQUIRED",
                        description="FK to news_articles_raw"),
    bigquery.SchemaField("category", "STRING", mode="REQUIRED",
                        description="News category (injury, trade, lineup, etc.)"),
    bigquery.SchemaField("subcategory", "STRING", mode="NULLABLE",
                        description="Subcategory (out, questionable, rumor, etc.)"),
    bigquery.SchemaField("confidence", "FLOAT64", mode="REQUIRED",
                        description="Classification confidence 0-1"),
    bigquery.SchemaField("player_mentions", "JSON", mode="NULLABLE",
                        description="Array of player mentions with context"),
    bigquery.SchemaField("linked_players", "JSON", mode="NULLABLE",
                        description="Array of linked players from registry"),
    bigquery.SchemaField("teams_mentioned", "STRING", mode="REPEATED",
                        description="Team abbreviations mentioned"),
    bigquery.SchemaField("keywords_matched", "STRING", mode="REPEATED",
                        description="Keywords that matched"),
    bigquery.SchemaField("ai_summary", "STRING", mode="NULLABLE",
                        description="AI-generated summary of the article"),
    bigquery.SchemaField("headline", "STRING", mode="NULLABLE",
                        description="AI-generated short headline (max 50 chars)"),
    bigquery.SchemaField("ai_summary_generated_at", "TIMESTAMP", mode="NULLABLE",
                        description="When AI summary was generated"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED",
                        description="When extraction was performed"),
]

# Schema for player-article links (for website player pages)
NEWS_PLAYER_LINKS_SCHEMA = [
    bigquery.SchemaField("player_lookup", "STRING", mode="REQUIRED",
                        description="Player lookup from registry"),
    bigquery.SchemaField("article_id", "STRING", mode="REQUIRED",
                        description="FK to news_articles_raw"),
    bigquery.SchemaField("sport", "STRING", mode="REQUIRED",
                        description="nba or mlb"),
    bigquery.SchemaField("mention_role", "STRING", mode="NULLABLE",
                        description="primary, secondary, or mentioned"),
    bigquery.SchemaField("link_confidence", "FLOAT64", mode="REQUIRED",
                        description="Confidence of the player link 0-1"),
    bigquery.SchemaField("link_method", "STRING", mode="NULLABLE",
                        description="How linked: exact, search, ai"),
    bigquery.SchemaField("article_category", "STRING", mode="NULLABLE",
                        description="injury, trade, etc."),
    bigquery.SchemaField("article_published_at", "TIMESTAMP", mode="NULLABLE",
                        description="When article was published"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED",
                        description="When this link was created"),
]

NEWS_ARTICLES_SCHEMA = [
    bigquery.SchemaField("article_id", "STRING", mode="REQUIRED",
                        description="Unique identifier (hash of source:guid)"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
                        description="Source feed name (e.g., espn_nba, cbs_mlb)"),
    bigquery.SchemaField("source_url", "STRING", mode="NULLABLE",
                        description="URL to the original article"),
    bigquery.SchemaField("source_guid", "STRING", mode="NULLABLE",
                        description="Original RSS guid/id"),
    bigquery.SchemaField("title", "STRING", mode="REQUIRED",
                        description="Article title"),
    bigquery.SchemaField("summary", "STRING", mode="NULLABLE",
                        description="Article summary/description from RSS"),
    bigquery.SchemaField("published_at", "TIMESTAMP", mode="REQUIRED",
                        description="When the article was published"),
    bigquery.SchemaField("scraped_at", "TIMESTAMP", mode="REQUIRED",
                        description="When we scraped this article"),
    bigquery.SchemaField("sport", "STRING", mode="REQUIRED",
                        description="Sport: nba or mlb"),
    bigquery.SchemaField("author", "STRING", mode="NULLABLE",
                        description="Article author if available"),
    bigquery.SchemaField("content_hash", "STRING", mode="REQUIRED",
                        description="Hash of title+summary for deduplication"),
    bigquery.SchemaField("ai_processed", "BOOL", mode="REQUIRED",
                        description="Whether AI extraction has been run"),
    bigquery.SchemaField("ai_processed_at", "TIMESTAMP", mode="NULLABLE",
                        description="When AI extraction was run"),
]


class NewsStorage:
    """
    Handles storage of news articles to BigQuery.

    Usage:
        storage = NewsStorage()
        storage.ensure_table_exists()
        new_articles = storage.filter_new_articles(articles)
        storage.save_articles(new_articles)
    """

    def __init__(self, project_id: str = PROJECT_ID, dataset_id: str = DATASET_ID):
        """Initialize BigQuery client."""
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = f"{project_id}.{dataset_id}.{TABLE_ID}"
        self.client = bigquery.Client(project=project_id)
        logger.info(f"Initialized NewsStorage for {self.table_id}")

    def ensure_table_exists(self) -> bool:
        """
        Create the news_articles_raw table if it doesn't exist.

        Returns:
            True if table exists or was created successfully
        """
        try:
            self.client.get_table(self.table_id)
            logger.info(f"Table {self.table_id} already exists")
            return True
        except NotFound:
            logger.info(f"Creating table {self.table_id}")

        try:
            table = bigquery.Table(self.table_id, schema=NEWS_ARTICLES_SCHEMA)

            # Add table configuration
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="published_at",
            )
            table.clustering_fields = ["sport", "source"]
            table.description = "Raw news articles from RSS feeds (ESPN, CBS Sports, etc.)"

            self.client.create_table(table)
            logger.info(f"Created table {self.table_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create table: {e}")
            return False

    def get_existing_hashes(self, hours_lookback: int = 48) -> Set[str]:
        """
        Get content hashes of articles from the last N hours.

        Used for deduplication - we don't want to insert the same article twice.

        Args:
            hours_lookback: How many hours back to check for duplicates

        Returns:
            Set of content_hash values
        """
        query = f"""
        SELECT DISTINCT content_hash
        FROM `{self.table_id}`
        WHERE scraped_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours_lookback} HOUR)
        """

        try:
            result = self.client.query(query).result()
            hashes = {row.content_hash for row in result}
            logger.info(f"Found {len(hashes)} existing article hashes")
            return hashes
        except NotFound:
            logger.warning(f"Table {self.table_id} not found, returning empty set")
            return set()
        except Exception as e:
            logger.error(f"Failed to get existing hashes: {e}")
            return set()

    def filter_new_articles(
        self,
        articles: List[NewsArticle],
        hours_lookback: int = 48
    ) -> List[NewsArticle]:
        """
        Filter out articles that already exist in the database.

        Args:
            articles: List of articles to filter
            hours_lookback: How many hours back to check for duplicates

        Returns:
            List of articles that are not in the database
        """
        existing_hashes = self.get_existing_hashes(hours_lookback)

        new_articles = [
            article for article in articles
            if article.content_hash not in existing_hashes
        ]

        logger.info(f"Filtered {len(articles)} articles -> {len(new_articles)} new")
        return new_articles

    def save_articles(self, articles: List[NewsArticle]) -> int:
        """
        Save articles to BigQuery.

        Args:
            articles: List of NewsArticle objects to save

        Returns:
            Number of articles successfully saved
        """
        if not articles:
            logger.info("No articles to save")
            return 0

        # Convert articles to dicts for BigQuery
        rows = [article.to_dict() for article in articles]

        # Use streaming insert for low-latency writes
        errors = self.client.insert_rows_json(self.table_id, rows)

        if errors:
            logger.error(f"Errors inserting rows: {errors}")
            # Count successful inserts
            success_count = len(rows) - len(errors)
        else:
            success_count = len(rows)

        logger.info(f"Saved {success_count}/{len(rows)} articles to {self.table_id}")
        return success_count

    def get_recent_articles(
        self,
        sport: Optional[str] = None,
        limit: int = 50
    ) -> List[dict]:
        """
        Get recent articles from the database.

        Args:
            sport: Filter by sport ('nba' or 'mlb'), or None for all
            limit: Maximum number of articles to return

        Returns:
            List of article dictionaries
        """
        where_clause = f"WHERE sport = '{sport}'" if sport else ""

        query = f"""
        SELECT *
        FROM `{self.table_id}`
        {where_clause}
        ORDER BY published_at DESC
        LIMIT {limit}
        """

        try:
            result = self.client.query(query).result()
            articles = [dict(row) for row in result]
            logger.info(f"Retrieved {len(articles)} articles")
            return articles
        except Exception as e:
            logger.error(f"Failed to get recent articles: {e}")
            return []

    def get_unprocessed_articles(self, limit: int = 100) -> List[dict]:
        """
        Get articles that haven't been processed by AI yet.

        Returns:
            List of article dictionaries where ai_processed = False
        """
        query = f"""
        SELECT *
        FROM `{self.table_id}`
        WHERE ai_processed = FALSE
        ORDER BY published_at DESC
        LIMIT {limit}
        """

        try:
            result = self.client.query(query).result()
            articles = [dict(row) for row in result]
            logger.info(f"Found {len(articles)} unprocessed articles")
            return articles
        except Exception as e:
            logger.error(f"Failed to get unprocessed articles: {e}")
            return []


class NewsInsightsStorage:
    """
    Handles storage of extraction results to BigQuery.

    Usage:
        storage = NewsInsightsStorage()
        storage.ensure_table_exists()
        storage.save_insights(extraction_results)
    """

    TABLE_NAME = "news_insights"

    def __init__(self, project_id: str = PROJECT_ID, dataset_id: str = "nba_analytics"):
        """Initialize BigQuery client."""
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = f"{project_id}.{dataset_id}.{self.TABLE_NAME}"
        self.client = bigquery.Client(project=project_id)
        logger.info(f"Initialized NewsInsightsStorage for {self.table_id}")

    def ensure_table_exists(self) -> bool:
        """Create the news_insights table if it doesn't exist."""
        try:
            self.client.get_table(self.table_id)
            logger.info(f"Table {self.table_id} already exists")
            return True
        except NotFound:
            logger.info(f"Creating table {self.table_id}")

        try:
            table = bigquery.Table(self.table_id, schema=NEWS_INSIGHTS_SCHEMA)
            table.description = "Extracted insights from news articles"
            self.client.create_table(table)
            logger.info(f"Created table {self.table_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create table: {e}")
            return False

    def save_insights(self, results: List[dict], summaries: Optional[dict] = None) -> int:
        """
        Save extraction results to BigQuery.

        Args:
            results: List of ExtractionResult.to_dict() outputs
            summaries: Optional dict mapping article_id -> {summary, headline} from AI

        Returns:
            Number of rows saved

        Note:
            AI summaries are included in the initial insert to avoid BigQuery
            streaming buffer issues. See docs/05-development/guides/bigquery-best-practices.md
        """
        if not results:
            return 0

        summaries = summaries or {}

        # Add timestamp
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for result in results:
            article_id = result['article_id']
            summary_data = summaries.get(article_id, {})

            row = {
                'article_id': article_id,
                'category': result['category'],
                'subcategory': result.get('subcategory'),
                'confidence': result['confidence'],
                'player_mentions': json.dumps(result.get('player_mentions', [])),
                'teams_mentioned': result.get('teams_mentioned', []),
                'keywords_matched': result.get('keywords_matched', []),
                'extracted_at': now,
                # Include AI summary fields in initial insert (avoids streaming buffer UPDATE issues)
                'ai_summary': summary_data.get('summary'),
                'headline': summary_data.get('headline'),
                'ai_summary_generated_at': summary_data.get('generated_at'),
            }
            rows.append(row)

        errors = self.client.insert_rows_json(self.table_id, rows)

        if errors:
            logger.error(f"Errors inserting insights: {errors}")
            return len(rows) - len(errors)

        logger.info(f"Saved {len(rows)} insights to {self.table_id}")
        return len(rows)

    def get_insights_by_category(
        self,
        category: str,
        limit: int = 50
    ) -> List[dict]:
        """Get insights by category."""
        query = f"""
        SELECT i.*, a.title, a.source, a.sport
        FROM `{self.table_id}` i
        JOIN `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` a ON i.article_id = a.article_id
        WHERE i.category = @category
        ORDER BY i.extracted_at DESC
        LIMIT {limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("category", "STRING", category),
        ])

        try:
            result = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Failed to get insights: {e}")
            return []

    def get_player_news(self, player_name: str, limit: int = 20) -> List[dict]:
        """
        Get news articles mentioning a specific player.

        Uses JSON search on player_mentions field.
        """
        query = f"""
        SELECT i.*, a.title, a.summary, a.source, a.sport, a.published_at
        FROM `{self.table_id}` i
        JOIN `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` a ON i.article_id = a.article_id
        WHERE LOWER(i.player_mentions) LIKE LOWER(@player_pattern)
        ORDER BY a.published_at DESC
        LIMIT {limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_pattern", "STRING", f"%{player_name}%"),
        ])

        try:
            result = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Failed to get player news: {e}")
            return []


class NewsPlayerLinksStorage:
    """
    Storage for player-article links.

    This table enables fast lookups of news articles for a specific player,
    useful for player pages on the website.

    Usage:
        storage = NewsPlayerLinksStorage()
        storage.ensure_table_exists()
        storage.save_links(player_links)

        # Get news for a player
        articles = storage.get_player_articles("lebronjames", limit=10)
    """

    TABLE_NAME = "news_player_links"

    def __init__(self, project_id: str = PROJECT_ID, dataset_id: str = "nba_analytics"):
        """Initialize BigQuery client."""
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = f"{project_id}.{dataset_id}.{self.TABLE_NAME}"
        self.client = bigquery.Client(project=project_id)
        logger.info(f"Initialized NewsPlayerLinksStorage for {self.table_id}")

    def ensure_table_exists(self) -> bool:
        """Create the news_player_links table if it doesn't exist."""
        try:
            self.client.get_table(self.table_id)
            logger.info(f"Table {self.table_id} already exists")
            return True
        except NotFound:
            logger.info(f"Creating table {self.table_id}")

        try:
            table = bigquery.Table(self.table_id, schema=NEWS_PLAYER_LINKS_SCHEMA)
            table.clustering_fields = ["player_lookup", "sport"]
            table.description = "Links between news articles and players (for website)"
            self.client.create_table(table)
            logger.info(f"Created table {self.table_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create table: {e}")
            return False

    def save_links(self, links: List[dict]) -> int:
        """
        Save player-article links.

        Args:
            links: List of link dictionaries with player_lookup, article_id, etc.

        Returns:
            Number of links saved
        """
        if not links:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for link in links:
            row = {
                'player_lookup': link['player_lookup'],
                'article_id': link['article_id'],
                'sport': link.get('sport', 'nba'),
                'mention_role': link.get('mention_role'),
                'link_confidence': link.get('link_confidence', 0.8),
                'link_method': link.get('link_method', 'search'),
                'article_category': link.get('article_category'),
                'article_published_at': link.get('article_published_at'),
                'created_at': now,
            }
            rows.append(row)

        errors = self.client.insert_rows_json(self.table_id, rows)

        if errors:
            logger.error(f"Errors inserting links: {errors}")
            return len(rows) - len(errors)

        logger.info(f"Saved {len(rows)} player links to {self.table_id}")
        return len(rows)

    def get_player_articles(
        self,
        player_lookup: str,
        sport: str = 'nba',
        limit: int = 20,
        category: Optional[str] = None
    ) -> List[dict]:
        """
        Get news articles for a specific player.

        This is the main query for player pages on the website.

        Args:
            player_lookup: Player lookup from registry (e.g., "lebronjames")
            sport: 'nba' or 'mlb'
            limit: Maximum articles to return
            category: Optional filter by category (injury, trade, etc.)

        Returns:
            List of article dictionaries with full article data
        """
        category_filter = ""
        if category:
            category_filter = f"AND l.article_category = '{category}'"

        query = f"""
        SELECT
            a.article_id,
            a.title,
            a.summary,
            a.source,
            a.source_url,
            a.published_at,
            a.author,
            l.mention_role,
            l.article_category,
            l.link_confidence,
            i.ai_summary
        FROM `{self.table_id}` l
        JOIN `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` a ON l.article_id = a.article_id
        LEFT JOIN `{PROJECT_ID}.nba_analytics.news_insights` i ON l.article_id = i.article_id
        WHERE l.player_lookup = @player_lookup
          AND l.sport = @sport
          {category_filter}
        ORDER BY a.published_at DESC
        LIMIT {limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("sport", "STRING", sport),
        ])

        try:
            result = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Failed to get player articles: {e}")
            return []

    def update_ai_summary(
        self,
        article_id: str,
        ai_summary: str
    ) -> bool:
        """
        Update the AI summary for an article in news_insights.

        Args:
            article_id: Article to update
            ai_summary: AI-generated summary

        Returns:
            True if updated successfully
        """
        query = f"""
        UPDATE `{self.project_id}.nba_analytics.news_insights`
        SET ai_summary = @summary,
            ai_summary_generated_at = CURRENT_TIMESTAMP()
        WHERE article_id = @article_id
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("summary", "STRING", ai_summary),
            bigquery.ScalarQueryParameter("article_id", "STRING", article_id),
        ])

        try:
            self.client.query(query, job_config=job_config).result()
            logger.info(f"Updated AI summary for article {article_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update AI summary: {e}")
            return False

    def get_recent_injury_news(
        self,
        sport: str = 'nba',
        hours: int = 24,
        limit: int = 50
    ) -> List[dict]:
        """
        Get recent injury news with linked players.

        Useful for injury report pages.
        """
        query = f"""
        SELECT
            l.player_lookup,
            a.title,
            a.summary,
            a.source,
            a.source_url,
            a.published_at,
            i.subcategory as injury_status,
            i.ai_summary
        FROM `{self.table_id}` l
        JOIN `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` a ON l.article_id = a.article_id
        LEFT JOIN `{PROJECT_ID}.nba_analytics.news_insights` i ON l.article_id = i.article_id
        WHERE l.sport = @sport
          AND l.article_category = 'injury'
          AND a.published_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        ORDER BY a.published_at DESC
        LIMIT {limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("sport", "STRING", sport),
        ])

        try:
            result = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Failed to get injury news: {e}")
            return []


def test_storage():
    """Test storage module (requires BigQuery access)."""
    logging.basicConfig(level=logging.INFO)

    storage = NewsStorage()

    # Create table if needed
    storage.ensure_table_exists()

    # Check for existing articles
    existing = storage.get_existing_hashes(hours_lookback=24)
    print(f"Found {len(existing)} existing article hashes in last 24 hours")


if __name__ == '__main__':
    test_storage()
