#!/usr/bin/env python3
"""
RSS Feed Fetcher for sports news.

Fetches and parses RSS feeds from ESPN, CBS Sports, and other sources.
Designed for simplicity - no AI extraction, just raw article collection.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from email.utils import parsedate_to_datetime

import feedparser

logger = logging.getLogger(__name__)


@dataclass
class RSSFeedConfig:
    """Configuration for an RSS feed source."""
    name: str
    url: str
    sport: str  # 'nba' or 'mlb'
    source_type: str = 'rss'  # 'rss' or 'atom'
    enabled: bool = True


@dataclass
class NewsArticle:
    """Represents a single news article from an RSS feed."""
    article_id: str
    source: str
    source_url: str
    source_guid: str
    title: str
    summary: str
    published_at: datetime
    scraped_at: datetime
    sport: str
    author: Optional[str] = None
    content_hash: str = ''

    def __post_init__(self):
        """Generate content hash for deduplication."""
        if not self.content_hash:
            content = f"{self.title.lower().strip()}|{self.summary[:100].lower().strip()}"
            self.content_hash = hashlib.md5(content.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for BigQuery insertion."""
        return {
            'article_id': self.article_id,
            'source': self.source,
            'source_url': self.source_url,
            'source_guid': self.source_guid,
            'title': self.title,
            'summary': self.summary,
            'published_at': self.published_at.isoformat(),
            'scraped_at': self.scraped_at.isoformat(),
            'sport': self.sport,
            'author': self.author,
            'content_hash': self.content_hash,
            'ai_processed': False,
        }


# Pre-configured feed sources
DEFAULT_FEEDS = [
    # ESPN Feeds
    RSSFeedConfig(
        name='espn_nba',
        url='https://www.espn.com/espn/rss/nba/news',
        sport='nba',
    ),
    RSSFeedConfig(
        name='espn_mlb',
        url='https://www.espn.com/espn/rss/mlb/news',
        sport='mlb',
    ),
    # CBS Sports Feeds
    RSSFeedConfig(
        name='cbs_nba',
        url='https://www.cbssports.com/rss/headlines/nba/',
        sport='nba',
    ),
    RSSFeedConfig(
        name='cbs_mlb',
        url='https://www.cbssports.com/rss/headlines/mlb/',
        sport='mlb',
    ),
    # Yahoo Sports Feeds (can be enabled if needed)
    RSSFeedConfig(
        name='yahoo_nba',
        url='https://sports.yahoo.com/nba/rss.xml',
        sport='nba',
        enabled=False,  # Disabled by default - enable after testing
    ),
    RSSFeedConfig(
        name='yahoo_mlb',
        url='https://sports.yahoo.com/mlb/rss.xml',
        sport='mlb',
        enabled=False,
    ),
]


class RSSFetcher:
    """
    Fetches and parses RSS feeds from sports news sources.

    Usage:
        fetcher = RSSFetcher()
        articles = fetcher.fetch_all()  # Fetch from all enabled feeds
        articles = fetcher.fetch_feed('espn_nba')  # Fetch from specific feed
    """

    def __init__(self, feeds: Optional[List[RSSFeedConfig]] = None):
        """
        Initialize RSS fetcher.

        Args:
            feeds: Optional list of feed configurations. Uses DEFAULT_FEEDS if not provided.
        """
        self.feeds = {f.name: f for f in (feeds or DEFAULT_FEEDS)}
        logger.info(f"Initialized RSSFetcher with {len(self.feeds)} feeds")

    def fetch_feed(self, feed_name: str) -> List[NewsArticle]:
        """
        Fetch articles from a specific RSS feed.

        Args:
            feed_name: Name of the feed to fetch (e.g., 'espn_nba')

        Returns:
            List of NewsArticle objects
        """
        if feed_name not in self.feeds:
            raise ValueError(f"Unknown feed: {feed_name}. Available: {list(self.feeds.keys())}")

        config = self.feeds[feed_name]
        if not config.enabled:
            logger.info(f"Feed {feed_name} is disabled, skipping")
            return []

        logger.info(f"Fetching RSS feed: {feed_name} from {config.url}")

        try:
            feed = feedparser.parse(config.url)

            if feed.bozo:
                logger.warning(f"Feed {feed_name} had parsing issues: {feed.bozo_exception}")

            articles = []
            scraped_at = datetime.now(timezone.utc)

            for entry in feed.entries:
                try:
                    article = self._parse_entry(entry, config, scraped_at)
                    if article:
                        articles.append(article)
                except Exception as e:
                    logger.warning(f"Failed to parse entry in {feed_name}: {e}")
                    continue

            logger.info(f"Fetched {len(articles)} articles from {feed_name}")
            return articles

        except Exception as e:
            logger.error(f"Failed to fetch feed {feed_name}: {e}")
            return []

    def fetch_all(self, sports: Optional[List[str]] = None) -> List[NewsArticle]:
        """
        Fetch articles from all enabled feeds.

        Args:
            sports: Optional list of sports to filter by ('nba', 'mlb')

        Returns:
            List of NewsArticle objects from all feeds
        """
        all_articles = []

        for name, config in self.feeds.items():
            if not config.enabled:
                continue
            if sports and config.sport not in sports:
                continue

            articles = self.fetch_feed(name)
            all_articles.extend(articles)

        # Deduplicate by content_hash
        seen_hashes = set()
        unique_articles = []
        for article in all_articles:
            if article.content_hash not in seen_hashes:
                seen_hashes.add(article.content_hash)
                unique_articles.append(article)

        logger.info(f"Fetched {len(all_articles)} total, {len(unique_articles)} unique articles")
        return unique_articles

    def fetch_nba(self) -> List[NewsArticle]:
        """Fetch all NBA news articles."""
        return self.fetch_all(sports=['nba'])

    def fetch_mlb(self) -> List[NewsArticle]:
        """Fetch all MLB news articles."""
        return self.fetch_all(sports=['mlb'])

    def _parse_entry(
        self,
        entry: feedparser.FeedParserDict,
        config: RSSFeedConfig,
        scraped_at: datetime
    ) -> Optional[NewsArticle]:
        """Parse a single RSS entry into a NewsArticle."""

        # Extract required fields
        title = entry.get('title', '').strip()
        if not title:
            return None

        link = entry.get('link', '')
        summary = entry.get('summary', entry.get('description', '')).strip()

        # Parse published date
        published_at = self._parse_date(entry)

        # Generate article ID from link or guid
        guid = entry.get('id', entry.get('guid', link))
        article_id = hashlib.md5(f"{config.name}:{guid}".encode()).hexdigest()[:16]

        # Extract author
        author = entry.get('author', entry.get('dc_creator', None))

        return NewsArticle(
            article_id=article_id,
            source=config.name,
            source_url=link,
            source_guid=guid,
            title=title,
            summary=summary,
            published_at=published_at,
            scraped_at=scraped_at,
            sport=config.sport,
            author=author,
        )

    def _parse_date(self, entry: feedparser.FeedParserDict) -> datetime:
        """Parse date from RSS entry, with fallback to current time."""
        # Try published_parsed first (feedparser's parsed version)
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        # Try parsing published string
        if hasattr(entry, 'published') and entry.published:
            try:
                return parsedate_to_datetime(entry.published)
            except (TypeError, ValueError):
                pass

        # Fallback to current time
        return datetime.now(timezone.utc)

    def get_feed_names(self, enabled_only: bool = True) -> List[str]:
        """Get list of available feed names."""
        if enabled_only:
            return [name for name, config in self.feeds.items() if config.enabled]
        return list(self.feeds.keys())


# Quick test function
def test_fetcher():
    """Test the RSS fetcher with ESPN NBA feed."""
    logging.basicConfig(level=logging.INFO)

    fetcher = RSSFetcher()
    articles = fetcher.fetch_feed('espn_nba')

    print(f"\n=== Fetched {len(articles)} articles ===\n")

    for article in articles[:5]:
        print(f"Title: {article.title}")
        print(f"Source: {article.source}")
        print(f"Published: {article.published_at}")
        print(f"Summary: {article.summary[:100]}...")
        print(f"URL: {article.source_url}")
        print("-" * 50)


if __name__ == '__main__':
    test_fetcher()
