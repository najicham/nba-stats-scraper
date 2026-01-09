"""
News scrapers for sports news aggregation.

This module provides RSS feed scraping for NBA and MLB news from various sources.

Usage:
    from scrapers.news import RSSFetcher, NewsStorage

    # Fetch articles
    fetcher = RSSFetcher()
    articles = fetcher.fetch_nba()

    # Save to BigQuery
    storage = NewsStorage()
    storage.ensure_table_exists()
    storage.save_articles(articles)
"""

from scrapers.news.rss_fetcher import RSSFetcher, RSSFeedConfig, NewsArticle
from scrapers.news.storage import (
    NewsStorage,
    NewsInsightsStorage,
    NewsPlayerLinksStorage,
    NEWS_ARTICLES_SCHEMA,
    NEWS_INSIGHTS_SCHEMA,
    NEWS_PLAYER_LINKS_SCHEMA,
)
from scrapers.news.keyword_extractor import KeywordExtractor, ExtractionResult, NewsCategory
from scrapers.news.player_linker import PlayerLinker, LinkedPlayer
from scrapers.news.ai_summarizer import NewsSummarizer, SummaryResult

__all__ = [
    # Fetcher
    'RSSFetcher',
    'RSSFeedConfig',
    'NewsArticle',
    # Storage
    'NewsStorage',
    'NewsInsightsStorage',
    'NewsPlayerLinksStorage',
    'NEWS_ARTICLES_SCHEMA',
    'NEWS_INSIGHTS_SCHEMA',
    'NEWS_PLAYER_LINKS_SCHEMA',
    # Extraction
    'KeywordExtractor',
    'ExtractionResult',
    'NewsCategory',
    # Player Linking
    'PlayerLinker',
    'LinkedPlayer',
    # AI Summarization
    'NewsSummarizer',
    'SummaryResult',
]
