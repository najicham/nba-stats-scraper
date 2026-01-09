#!/usr/bin/env python3
"""
AI-powered news summarization using Claude Haiku.

Cost-optimized design:
- Uses Claude Haiku (cheapest model: $0.25/1M input, $1.25/1M output)
- Minimal prompts (~200 tokens input, ~50 tokens output per article)
- Estimated cost: ~$0.01 per 100 articles
- Caches results to avoid re-processing
"""

import os
import json
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Cost tracking (Haiku pricing as of 2024)
HAIKU_INPUT_COST_PER_1M = 0.25  # $0.25 per 1M input tokens
HAIKU_OUTPUT_COST_PER_1M = 1.25  # $1.25 per 1M output tokens


@dataclass
class SummaryResult:
    """Result from AI summarization."""
    article_id: str
    summary: str
    headline: str  # Short headline, max 50 chars
    key_facts: List[str]
    fantasy_impact: Optional[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    generated_at: datetime

    def to_dict(self) -> dict:
        return {
            'article_id': self.article_id,
            'summary': self.summary,
            'headline': self.headline,
            'key_facts': self.key_facts,
            'fantasy_impact': self.fantasy_impact,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'cost_usd': self.cost_usd,
            'model': self.model,
            'generated_at': self.generated_at.isoformat(),
        }


class NewsSummarizer:
    """
    Generate concise summaries for sports news articles.

    Cost-optimized for high volume processing.

    Usage:
        summarizer = NewsSummarizer()
        result = summarizer.summarize(
            article_id='abc123',
            title='LeBron ruled out vs Spurs',
            summary='Lakers star LeBron James...',
            category='injury'
        )
    """

    # Minimal prompt template - optimized for token efficiency
    PROMPT_TEMPLATE = """Summarize this {sport} news. Create a short headline (max 50 chars) and 1-2 sentence summary.

Title: {title}
Content: {content}

Respond in JSON:
{{"headline": "Short headline max 50 chars", "summary": "1-2 sentence summary", "facts": ["fact1", "fact2"], "impact": "fantasy/betting impact or null"}}"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = 'claude-3-haiku-20240307'
    ):
        """
        Initialize summarizer.

        Args:
            api_key: Anthropic API key (uses env/Secret Manager if not provided)
            model: Model to use (defaults to Haiku for cost efficiency)
        """
        # Get API key - try multiple sources
        if api_key is None:
            # Try environment variable first
            api_key = os.environ.get('ANTHROPIC_API_KEY')

            # Try loading from .env file
            if not api_key:
                try:
                    from dotenv import load_dotenv
                    load_dotenv()
                    api_key = os.environ.get('ANTHROPIC_API_KEY')
                except ImportError:
                    pass

            # Try Secret Manager (for Cloud Run)
            if not api_key:
                try:
                    from shared.utils.auth_utils import get_api_key as get_secret
                    api_key = get_secret(
                        secret_name='anthropic-api-key',
                        default_env_var='ANTHROPIC_API_KEY'
                    )
                except Exception as e:
                    logger.debug(f"Secret Manager lookup failed: {e}")

            if not api_key:
                raise ValueError(
                    "Anthropic API key not found. Set ANTHROPIC_API_KEY env var "
                    "or add to .env file."
                )

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package required: pip install anthropic")

        self.model = model
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.articles_processed = 0

        logger.info(f"Initialized NewsSummarizer with model={model}")

    def summarize(
        self,
        article_id: str,
        title: str,
        content: str,
        sport: str = 'NBA',
        category: Optional[str] = None
    ) -> SummaryResult:
        """
        Generate summary for a single article.

        Args:
            article_id: Unique article identifier
            title: Article title
            content: Article summary/body text
            sport: 'NBA' or 'MLB'
            category: Optional category hint (injury, trade, etc.)

        Returns:
            SummaryResult with summary and token usage
        """
        # Truncate content to save tokens (first 500 chars is usually enough)
        truncated_content = content[:500] if content else ''

        prompt = self.PROMPT_TEMPLATE.format(
            sport=sport.upper(),
            title=title,
            content=truncated_content
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=150,  # Limit output tokens
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse response
            result = self._parse_response(response, article_id)

            # Track costs
            self._track_usage(result.input_tokens, result.output_tokens)

            return result

        except Exception as e:
            logger.error(f"Summarization failed for {article_id}: {e}")
            return SummaryResult(
                article_id=article_id,
                summary=f"Summary unavailable: {title[:100]}",
                headline=self._create_headline_from_title(article_id, title),
                key_facts=[],
                fantasy_impact=None,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                model=self.model,
                generated_at=datetime.now(timezone.utc)
            )

    def summarize_batch(
        self,
        articles: List[dict],
        sport: str = 'NBA',
        max_articles: Optional[int] = None
    ) -> Tuple[List[SummaryResult], dict]:
        """
        Summarize multiple articles.

        Args:
            articles: List of dicts with 'article_id', 'title', 'summary'
            sport: 'NBA' or 'MLB'
            max_articles: Optional limit (for cost control)

        Returns:
            (list of SummaryResults, usage stats dict)
        """
        results = []
        to_process = articles[:max_articles] if max_articles else articles

        logger.info(f"Summarizing {len(to_process)} articles...")

        for i, article in enumerate(to_process):
            if i > 0 and i % 10 == 0:
                logger.info(f"Progress: {i}/{len(to_process)} articles, cost so far: ${self.total_cost:.4f}")

            result = self.summarize(
                article_id=article['article_id'],
                title=article['title'],
                content=article.get('summary', ''),
                sport=sport,
                category=article.get('category')
            )
            results.append(result)

        stats = self.get_usage_stats()
        logger.info(f"Completed {len(results)} summaries. Total cost: ${stats['total_cost_usd']:.4f}")

        return results, stats

    def _parse_response(self, response, article_id: str) -> SummaryResult:
        """Parse Claude response into SummaryResult."""
        content = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Calculate cost
        cost = (
            (input_tokens / 1_000_000) * HAIKU_INPUT_COST_PER_1M +
            (output_tokens / 1_000_000) * HAIKU_OUTPUT_COST_PER_1M
        )

        # Try to parse JSON response
        try:
            # Handle potential markdown code blocks
            if '```' in content:
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            data = json.loads(content.strip())
            summary = data.get('summary', content[:200])
            headline = data.get('headline', '')
            facts = data.get('facts', [])
            impact = data.get('impact')
        except (json.JSONDecodeError, IndexError):
            # Fallback: use raw response as summary
            summary = content[:200]
            headline = ''
            facts = []
            impact = None

        # Ensure headline is max 50 chars, generate fallback if missing
        if not headline:
            # Create headline from title - truncate at word boundary
            headline = self._create_headline_from_title(article_id, summary)
        elif len(headline) > 50:
            headline = headline[:47] + '...'

        return SummaryResult(
            article_id=article_id,
            summary=summary,
            headline=headline,
            key_facts=facts if isinstance(facts, list) else [],
            fantasy_impact=impact if impact and impact != 'null' else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=self.model,
            generated_at=datetime.now(timezone.utc)
        )

    def _create_headline_from_title(self, article_id: str, title: str) -> str:
        """Create a short headline from title, max 50 chars, truncated at word boundary."""
        if len(title) <= 50:
            return title
        # Truncate at word boundary
        truncated = title[:47]
        last_space = truncated.rfind(' ')
        if last_space > 30:
            truncated = truncated[:last_space]
        return truncated + '...'

    def _track_usage(self, input_tokens: int, output_tokens: int):
        """Track cumulative token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += (
            (input_tokens / 1_000_000) * HAIKU_INPUT_COST_PER_1M +
            (output_tokens / 1_000_000) * HAIKU_OUTPUT_COST_PER_1M
        )
        self.articles_processed += 1

    def get_usage_stats(self) -> dict:
        """Get cumulative usage statistics."""
        return {
            'articles_processed': self.articles_processed,
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_cost_usd': self.total_cost,
            'avg_cost_per_article': self.total_cost / max(self.articles_processed, 1),
            'model': self.model,
        }

    def estimate_cost(self, num_articles: int) -> dict:
        """
        Estimate cost for processing N articles.

        Based on observed averages:
        - ~200 input tokens per article
        - ~80 output tokens per article
        """
        est_input_tokens = num_articles * 200
        est_output_tokens = num_articles * 80

        est_cost = (
            (est_input_tokens / 1_000_000) * HAIKU_INPUT_COST_PER_1M +
            (est_output_tokens / 1_000_000) * HAIKU_OUTPUT_COST_PER_1M
        )

        return {
            'num_articles': num_articles,
            'estimated_input_tokens': est_input_tokens,
            'estimated_output_tokens': est_output_tokens,
            'estimated_cost_usd': est_cost,
            'cost_per_article': est_cost / num_articles if num_articles > 0 else 0,
        }


def test_summarizer():
    """Test the summarizer with sample articles."""
    logging.basicConfig(level=logging.INFO)

    summarizer = NewsSummarizer()

    # Cost estimate
    print("\nCost Estimate:")
    print("-" * 40)
    estimate = summarizer.estimate_cost(100)
    print(f"100 articles: ${estimate['estimated_cost_usd']:.4f}")
    estimate = summarizer.estimate_cost(1000)
    print(f"1000 articles: ${estimate['estimated_cost_usd']:.4f}")

    # Test articles
    test_articles = [
        {
            'article_id': 'test1',
            'title': 'LeBron James ruled out vs. Spurs with multiple injuries',
            'summary': 'Lakers star LeBron James did not play against the Spurs on Wednesday -- the second game of a back-to-back -- with the team citing ankle and foot injuries.',
        },
        {
            'article_id': 'test2',
            'title': 'Hawks trade Trae Young to Wizards for CJ McCollum',
            'summary': 'The Atlanta Hawks have traded four-time All-Star guard Trae Young to the Washington Wizards for CJ McCollum and Corey Kispert, sources told ESPN.',
        },
    ]

    print("\n" + "="*60)
    print("  AI Summarization Test")
    print("="*60)

    for article in test_articles:
        print(f"\nOriginal: {article['title']}")
        result = summarizer.summarize(
            article['article_id'],
            article['title'],
            article['summary']
        )
        print(f"Summary: {result.summary}")
        print(f"Facts: {result.key_facts}")
        print(f"Impact: {result.fantasy_impact}")
        print(f"Cost: ${result.cost_usd:.6f} ({result.input_tokens} in, {result.output_tokens} out)")

    print("\n" + "-"*40)
    print("Usage Stats:", summarizer.get_usage_stats())


if __name__ == '__main__':
    test_summarizer()
