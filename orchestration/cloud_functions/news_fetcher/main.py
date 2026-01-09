"""
News Fetcher Cloud Function

Fetches sports news from RSS feeds, extracts keywords, links players,
and generates AI summaries.

Trigger: Cloud Scheduler via HTTP (every 15 minutes)

Pipeline:
1. Fetch RSS feeds (ESPN, CBS Sports)
2. Deduplicate against existing articles
3. Save new articles to BigQuery
4. Extract keywords and categorize
5. Link player mentions to registry
6. Generate AI summaries (Claude Haiku)
7. Export to GCS for frontend consumption

Version: 1.0
Created: 2026-01-08
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import functions_framework
from flask import jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


def run_news_fetch(sports: list = None, generate_summaries: bool = True, max_articles: int = 50, export_to_gcs: bool = True) -> dict:
    """
    Run the complete news fetching pipeline.

    Args:
        sports: List of sports to fetch ('nba', 'mlb'). Defaults to both.
        generate_summaries: Whether to generate AI summaries for new articles
        max_articles: Max articles to process AI summaries for (cost control)
        export_to_gcs: Whether to export news to GCS for frontend (default: True)

    Returns:
        Result dictionary with counts and status
    """
    # Import here to avoid cold start overhead
    sys.path.insert(0, '/workspace')

    from scrapers.news import (
        RSSFetcher,
        NewsStorage,
        NewsInsightsStorage,
        NewsPlayerLinksStorage,
        KeywordExtractor,
        PlayerLinker,
    )

    if sports is None:
        sports = ['nba', 'mlb']

    result = {
        'status': 'success',
        'sports': sports,
        'articles_fetched': 0,
        'articles_new': 0,
        'articles_saved': 0,
        'insights_saved': 0,
        'player_links_saved': 0,
        'summaries_generated': 0,
        'summary_cost_usd': 0.0,
        'gcs_exports': 0,
        'errors': []
    }

    try:
        # Initialize components
        fetcher = RSSFetcher()
        raw_storage = NewsStorage()
        insights_storage = NewsInsightsStorage()
        links_storage = NewsPlayerLinksStorage()
        extractor = KeywordExtractor()

        # Ensure tables exist
        raw_storage.ensure_table_exists()
        insights_storage.ensure_table_exists()
        links_storage.ensure_table_exists()

        # Step 1: Fetch RSS feeds
        logger.info(f"Fetching RSS feeds for: {sports}")
        all_articles = fetcher.fetch_all(sports=sports)
        result['articles_fetched'] = len(all_articles)
        logger.info(f"Fetched {len(all_articles)} articles from RSS")

        if not all_articles:
            logger.info("No articles found in RSS feeds")
            return result

        # Step 2: Deduplicate
        new_articles = raw_storage.filter_new_articles(all_articles, hours_lookback=72)
        result['articles_new'] = len(new_articles)
        logger.info(f"Found {len(new_articles)} new articles after deduplication")

        if not new_articles:
            logger.info("No new articles to process")
            return result

        # Step 3: Save raw articles
        saved_count = raw_storage.save_articles(new_articles)
        result['articles_saved'] = saved_count
        logger.info(f"Saved {saved_count} articles to BigQuery")

        # Step 4: Extract keywords and categorize
        insights_to_save = []
        player_links_to_save = []
        article_extractions = {}  # Map article_id -> extraction for player linking

        for article in new_articles:
            # Extract keywords
            extraction = extractor.extract(
                article_id=article.article_id,
                title=article.title,
                summary=article.summary or '',
                sport=article.sport
            )

            # Convert ExtractedMention objects to serializable format
            player_mention_names = [m.likely_full_name for m in extraction.player_mentions]

            insight = {
                'article_id': article.article_id,
                'category': extraction.category.value,
                'subcategory': extraction.subcategory,
                'confidence': extraction.confidence,
                'player_mentions': player_mention_names,
                'teams_mentioned': extraction.teams_mentioned,
                'keywords_matched': extraction.keywords_matched,
            }
            insights_to_save.append(insight)
            article_extractions[article.article_id] = (extraction, player_mention_names, article)

        # Step 5: Generate AI summaries BEFORE saving insights
        # This avoids BigQuery streaming buffer UPDATE issues
        # See docs/05-development/guides/bigquery-best-practices.md
        summaries_dict = {}  # Map article_id -> {summary, headline, generated_at}

        if generate_summaries and new_articles:
            try:
                from scrapers.news import NewsSummarizer

                summarizer = NewsSummarizer()
                articles_for_summary = [
                    {
                        'article_id': a.article_id,
                        'title': a.title,
                        'summary': a.summary or '',
                        'sport': a.sport,
                    }
                    for a in new_articles[:max_articles]
                ]

                summaries, stats = summarizer.summarize_batch(articles_for_summary)
                result['summaries_generated'] = len(summaries)
                result['summary_cost_usd'] = stats.get('total_cost_usd', 0)

                # Build summaries dict for passing to save_insights
                for summary_result in summaries:
                    if summary_result.summary and not summary_result.summary.startswith("Summary unavailable"):
                        summaries_dict[summary_result.article_id] = {
                            'summary': summary_result.summary,
                            'headline': summary_result.headline,
                            'generated_at': summary_result.generated_at.isoformat(),
                        }

                logger.info(f"Generated {len(summaries)} AI summaries (cost: ${stats.get('total_cost_usd', 0):.4f})")

            except Exception as e:
                logger.error(f"AI summarization failed: {e}", exc_info=True)
                result['errors'].append(f"ai_summarization: {str(e)}")

        # Save insights with AI summaries included (single insert, no UPDATE needed)
        insights_saved = insights_storage.save_insights(insights_to_save, summaries=summaries_dict)
        result['insights_saved'] = insights_saved
        logger.info(f"Saved {insights_saved} insights")

        # Link players to registry
        for article_id, (extraction, player_mention_names, article) in article_extractions.items():
            if player_mention_names:
                try:
                    linker = PlayerLinker(sport=article.sport)
                    for i, player_name in enumerate(player_mention_names[:5]):  # Limit to first 5
                        link_result = linker.link_player(player_name)
                        if link_result and link_result.player_lookup:
                            player_links_to_save.append({
                                'player_lookup': link_result.player_lookup,
                                'article_id': article.article_id,
                                'sport': article.sport,
                                'mention_role': 'primary' if i == 0 else 'mentioned',
                                'link_confidence': link_result.confidence,
                                'link_method': link_result.method,
                                'article_category': extraction.category.value,
                                'article_published_at': article.published_at.isoformat() if article.published_at else None,
                            })
                except Exception as e:
                    logger.warning(f"Player linking failed for article {article.article_id}: {e}")

        # Save player links
        if player_links_to_save:
            links_saved = links_storage.save_links(player_links_to_save)
            result['player_links_saved'] = links_saved
            logger.info(f"Saved {links_saved} player links")

        # Step 6: Export to GCS for frontend consumption
        # Use incremental export (only players with new articles) for efficiency
        if export_to_gcs:
            try:
                from data_processors.publishing.news_exporter import NewsExporter

                total_exports = 0
                for sport in sports:
                    exporter = NewsExporter(sport=sport)

                    # Use incremental export - only exports players with recent links
                    # This exports tonight-summary + only players who have new articles
                    try:
                        paths = exporter.export_incremental(minutes_back=20)
                        total_exports += len(paths)
                        logger.info(f"Incremental export for {sport}: {len(paths)} files")
                    except Exception as e:
                        logger.warning(f"Failed incremental export for {sport}: {e}")
                        # Fallback to full export if incremental fails
                        try:
                            exporter.export()
                            paths = exporter.export_all_players(limit=100)
                            total_exports += len(paths) + 1
                            logger.info(f"Fallback full export for {sport}: {len(paths)+1} files")
                        except Exception as e2:
                            logger.error(f"Full export also failed for {sport}: {e2}")
                            result['errors'].append(f"gcs_export_{sport}: {str(e2)}")

                result['gcs_exports'] = total_exports
                logger.info(f"GCS export complete: {total_exports} files uploaded")

            except Exception as e:
                logger.error(f"GCS export failed: {e}", exc_info=True)
                result['errors'].append(f"gcs_export: {str(e)}")

    except Exception as e:
        logger.error(f"News fetch failed: {e}", exc_info=True)
        result['status'] = 'failed'
        result['errors'].append(str(e))

    if result['errors'] and result['status'] != 'failed':
        result['status'] = 'partial'

    return result


@functions_framework.http
def main(request):
    """
    HTTP-triggered Cloud Function for news fetching.

    Triggered by Cloud Scheduler every 15 minutes.

    Request JSON parameters:
        sports: list of sports to fetch (default: ['nba', 'mlb'])
        generate_summaries: whether to generate AI summaries (default: true)
        max_articles: max articles for AI summaries (default: 50)
        export_to_gcs: whether to export to GCS for frontend (default: true)

    Returns:
        JSON response with fetch status and counts
    """
    start_time = time.time()

    # Get parameters from request
    request_json = request.get_json(silent=True) or {}
    sports = request_json.get('sports', ['nba', 'mlb'])
    generate_summaries = request_json.get('generate_summaries', True)
    max_articles = request_json.get('max_articles', 50)
    export_to_gcs = request_json.get('export_to_gcs', True)

    logger.info(f"News fetch triggered: sports={sports}, summaries={generate_summaries}, export={export_to_gcs}")

    try:
        result = run_news_fetch(
            sports=sports,
            generate_summaries=generate_summaries,
            max_articles=max_articles,
            export_to_gcs=export_to_gcs
        )

        duration = time.time() - start_time
        result['duration_seconds'] = round(duration, 2)
        result['triggered_at'] = datetime.now(timezone.utc).isoformat()

        if result['status'] == 'success':
            logger.info(f"News fetch completed in {duration:.2f}s: {result['articles_new']} new articles")
            return jsonify(result), 200
        elif result['status'] == 'partial':
            logger.warning(f"News fetch partial in {duration:.2f}s: {result['errors']}")
            return jsonify(result), 200
        else:
            logger.error(f"News fetch failed in {duration:.2f}s: {result['errors']}")
            return jsonify(result), 500

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"News fetch error after {duration:.2f}s: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'duration_seconds': round(duration, 2)
        }), 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'function': 'news_fetcher',
        'version': '1.0'
    }), 200


# For local testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='News Fetcher')
    parser.add_argument('--sports', nargs='+', default=['nba', 'mlb'], help='Sports to fetch')
    parser.add_argument('--no-summaries', action='store_true', help='Skip AI summaries')
    parser.add_argument('--no-export', action='store_true', help='Skip GCS export')
    parser.add_argument('--max-articles', type=int, default=50, help='Max articles for summaries')

    args = parser.parse_args()

    result = run_news_fetch(
        sports=args.sports,
        generate_summaries=not args.no_summaries,
        max_articles=args.max_articles,
        export_to_gcs=not args.no_export
    )
    print(json.dumps(result, indent=2, default=str))
