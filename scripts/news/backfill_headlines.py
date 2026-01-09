#!/usr/bin/env python3
"""
Backfill AI Headlines for Existing News Articles

This script adds the headline column to news_insights if needed,
then regenerates AI headlines for articles that don't have them.

Usage:
    # Dry run (show what would be updated)
    python scripts/news/backfill_headlines.py --dry-run

    # Run the backfill
    python scripts/news/backfill_headlines.py

    # Limit to N articles
    python scripts/news/backfill_headlines.py --limit 50
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


def ensure_headline_column():
    """Add headline column to news_insights if it doesn't exist."""
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.nba_analytics.news_insights"

    try:
        table = client.get_table(table_id)
        existing_columns = {field.name for field in table.schema}

        if 'headline' in existing_columns:
            logger.info("headline column already exists")
            return True

        # Add the headline column
        logger.info("Adding headline column to news_insights...")
        new_schema = list(table.schema)
        new_schema.append(
            bigquery.SchemaField("headline", "STRING", mode="NULLABLE",
                               description="AI-generated short headline (max 50 chars)")
        )

        table.schema = new_schema
        client.update_table(table, ["schema"])
        logger.info("Successfully added headline column")
        return True

    except Exception as e:
        logger.error(f"Failed to update schema: {e}")
        return False


def get_articles_without_headlines(limit: int = 100) -> list:
    """Get articles that have ai_summary but no headline."""
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    SELECT
        i.article_id,
        a.title,
        a.summary,
        a.sport,
        i.ai_summary
    FROM `nba-props-platform.nba_analytics.news_insights` i
    JOIN `nba-props-platform.nba_raw.news_articles_raw` a
        ON i.article_id = a.article_id
    WHERE i.ai_summary IS NOT NULL
      AND (i.headline IS NULL OR i.headline = '')
    ORDER BY a.published_at DESC
    LIMIT @limit
    """

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ])

    results = client.query(query, job_config=job_config).result()
    articles = [dict(row) for row in results]
    logger.info(f"Found {len(articles)} articles without headlines")
    return articles


def regenerate_headlines(articles: list, dry_run: bool = False) -> dict:
    """Regenerate headlines for the given articles using AI."""
    if not articles:
        logger.info("No articles to process")
        return {'processed': 0, 'cost': 0.0}

    from scrapers.news.ai_summarizer import NewsSummarizer

    summarizer = NewsSummarizer()
    client = bigquery.Client(project=PROJECT_ID)

    processed = 0
    errors = 0

    for i, article in enumerate(articles):
        if i > 0 and i % 10 == 0:
            stats = summarizer.get_usage_stats()
            logger.info(f"Progress: {i}/{len(articles)}, cost so far: ${stats['total_cost_usd']:.4f}")

        try:
            # Generate new summary with headline
            result = summarizer.summarize(
                article_id=article['article_id'],
                title=article['title'],
                content=article.get('summary', ''),
                sport=article.get('sport', 'NBA').upper()
            )

            if dry_run:
                logger.info(f"[DRY RUN] Would update {article['article_id']}: {result.headline}")
                processed += 1
                continue

            # Update the headline in BigQuery
            query = """
            UPDATE `nba-props-platform.nba_analytics.news_insights`
            SET headline = @headline,
                ai_summary_generated_at = CURRENT_TIMESTAMP()
            WHERE article_id = @article_id
            """
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("headline", "STRING", result.headline),
                bigquery.ScalarQueryParameter("article_id", "STRING", article['article_id']),
            ])
            client.query(query, job_config=job_config).result()

            processed += 1
            logger.debug(f"Updated headline for {article['article_id']}: {result.headline}")

        except Exception as e:
            logger.error(f"Failed to process {article['article_id']}: {e}")
            errors += 1

    stats = summarizer.get_usage_stats()
    logger.info(f"Completed: {processed} headlines generated, {errors} errors")
    logger.info(f"Total cost: ${stats['total_cost_usd']:.4f}")

    return {
        'processed': processed,
        'errors': errors,
        'cost': stats['total_cost_usd']
    }


def main():
    parser = argparse.ArgumentParser(description='Backfill AI headlines for news articles')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    parser.add_argument('--limit', type=int, default=100, help='Max articles to process (default: 100)')
    parser.add_argument('--skip-schema', action='store_true', help='Skip adding headline column')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  News Headlines Backfill Script")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - no changes will be made")

    # Step 1: Ensure headline column exists
    if not args.skip_schema and not args.dry_run:
        if not ensure_headline_column():
            logger.error("Failed to ensure headline column exists")
            return 1

    # Step 2: Get articles without headlines
    articles = get_articles_without_headlines(limit=args.limit)

    if not articles:
        logger.info("All articles already have headlines!")
        return 0

    # Estimate cost
    from scrapers.news.ai_summarizer import NewsSummarizer
    summarizer = NewsSummarizer.__new__(NewsSummarizer)
    summarizer.model = 'claude-3-haiku-20240307'
    estimate = {
        'num_articles': len(articles),
        'estimated_cost_usd': len(articles) * 0.00018  # ~$0.00018 per article
    }
    logger.info(f"Estimated cost: ${estimate['estimated_cost_usd']:.4f} for {len(articles)} articles")

    # Step 3: Regenerate headlines
    result = regenerate_headlines(articles, dry_run=args.dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("  Summary")
    logger.info("=" * 60)
    logger.info(f"  Articles processed: {result['processed']}")
    logger.info(f"  Errors: {result.get('errors', 0)}")
    logger.info(f"  Actual cost: ${result['cost']:.4f}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
