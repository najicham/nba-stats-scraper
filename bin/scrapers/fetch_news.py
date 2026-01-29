#!/usr/bin/env python3
"""
CLI for fetching sports news from RSS feeds.

Usage:
    # Fetch and display articles (dry run - no save)
    python bin/scrapers/fetch_news.py --dry-run

    # Fetch NBA articles only
    python bin/scrapers/fetch_news.py --sport nba --dry-run

    # Fetch and save to BigQuery
    python bin/scrapers/fetch_news.py --save

    # Fetch, filter duplicates, and save
    python bin/scrapers/fetch_news.py --save --dedupe

    # Show recent articles from database
    python bin/scrapers/fetch_news.py --show-recent --sport nba
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# Add project root to path using relative path from this file
_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_current_dir, '..', '..'))

from scrapers.news.rss_fetcher import RSSFetcher
from scrapers.news.storage import NewsStorage


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def fetch_articles(args):
    """Fetch articles from RSS feeds."""
    fetcher = RSSFetcher()

    # Determine which sports to fetch
    sports = None
    if args.sport:
        sports = [args.sport]

    print(f"\n{'='*60}")
    print(f"  News Fetcher - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # Fetch articles
    if sports:
        print(f"Fetching {sports[0].upper()} articles...")
        if sports[0] == 'nba':
            articles = fetcher.fetch_nba()
        else:
            articles = fetcher.fetch_mlb()
    else:
        print("Fetching all articles (NBA + MLB)...")
        articles = fetcher.fetch_all()

    print(f"Fetched {len(articles)} articles\n")

    # Display articles
    if args.dry_run or args.verbose:
        print("-" * 60)
        for i, article in enumerate(articles[:args.limit], 1):
            print(f"\n[{i}] {article.title}")
            print(f"    Source: {article.source}")
            print(f"    Sport: {article.sport.upper()}")
            print(f"    Published: {article.published_at}")
            if article.author:
                print(f"    Author: {article.author}")
            print(f"    Summary: {article.summary[:100]}...")
            if args.verbose:
                print(f"    URL: {article.source_url}")
                print(f"    Hash: {article.content_hash}")
        print("-" * 60)

    # Save to BigQuery if requested
    if args.save:
        storage = NewsStorage()

        # Ensure table exists
        if not storage.ensure_table_exists():
            print("ERROR: Failed to create/verify table")
            return 1

        # Filter duplicates if requested
        if args.dedupe:
            print(f"\nFiltering duplicates (last {args.dedupe_hours} hours)...")
            articles = storage.filter_new_articles(articles, args.dedupe_hours)
            print(f"{len(articles)} new articles to save")

        # Save articles
        if articles:
            print(f"\nSaving {len(articles)} articles to BigQuery...")
            saved = storage.save_articles(articles)
            print(f"Successfully saved {saved} articles")
        else:
            print("\nNo new articles to save")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"{'='*60}")
    print(f"  Total fetched: {len(articles)}")

    # Count by source
    source_counts = {}
    for article in articles:
        source_counts[article.source] = source_counts.get(article.source, 0) + 1

    print(f"\n  By source:")
    for source, count in sorted(source_counts.items()):
        print(f"    {source}: {count}")

    # Count by sport
    sport_counts = {}
    for article in articles:
        sport_counts[article.sport] = sport_counts.get(article.sport, 0) + 1

    print(f"\n  By sport:")
    for sport, count in sorted(sport_counts.items()):
        print(f"    {sport.upper()}: {count}")

    print()
    return 0


def show_recent(args):
    """Show recent articles from database."""
    storage = NewsStorage()

    sport = args.sport if args.sport else None
    articles = storage.get_recent_articles(sport=sport, limit=args.limit)

    print(f"\n{'='*60}")
    print(f"  Recent Articles from Database")
    print(f"{'='*60}\n")

    if not articles:
        print("No articles found in database")
        return 0

    for i, article in enumerate(articles, 1):
        print(f"[{i}] {article['title']}")
        print(f"    Source: {article['source']} | Sport: {article['sport'].upper()}")
        print(f"    Published: {article['published_at']}")
        print(f"    AI Processed: {article['ai_processed']}")
        print()

    print(f"Total: {len(articles)} articles")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Fetch sports news from RSS feeds',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Mode arguments
    parser.add_argument('--dry-run', action='store_true',
                       help='Fetch and display articles without saving')
    parser.add_argument('--save', action='store_true',
                       help='Save articles to BigQuery')
    parser.add_argument('--show-recent', action='store_true',
                       help='Show recent articles from database')

    # Filter arguments
    parser.add_argument('--sport', choices=['nba', 'mlb'],
                       help='Filter by sport')
    parser.add_argument('--limit', type=int, default=20,
                       help='Maximum articles to display (default: 20)')

    # Deduplication
    parser.add_argument('--dedupe', action='store_true',
                       help='Filter out duplicate articles before saving')
    parser.add_argument('--dedupe-hours', type=int, default=48,
                       help='Hours to look back for duplicates (default: 48)')

    # Output arguments
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show verbose output')

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Default to dry-run if no mode specified
    if not (args.save or args.show_recent):
        args.dry_run = True

    # Execute appropriate function
    if args.show_recent:
        return show_recent(args)
    else:
        return fetch_articles(args)


if __name__ == '__main__':
    sys.exit(main())
