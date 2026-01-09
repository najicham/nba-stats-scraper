# News & AI Analysis Feature

**Created:** 2026-01-08
**Status:** Fully Operational (Phase 1-3 Complete, AI Summaries Generated)
**Priority:** Active
**Last Verified:** 2026-01-08

---

## Overview

This feature scrapes sports news from RSS feeds, extracts player mentions, links them to our player registry, and generates AI summaries - enabling news articles to be displayed on player pages on the website.

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | Complete | RSS fetching from ESPN + CBS Sports |
| Phase 2 | Complete | Keyword extraction and categorization |
| Phase 2.5 | Complete | Player registry linking |
| Phase 3 | Complete | AI summarization with Claude Haiku (100/100 articles) |
| Phase 4 | Not Started | ML feature integration |

## Current Data Stats (2026-01-08)

| Table | Records | AI Summaries |
|-------|---------|--------------|
| `news_articles_raw` | 100 | N/A |
| `news_insights` | 100 | 100 (100%) |
| `news_player_links` | 41 | N/A |

**Categories:** trade (30), signing (21), other (19), preview (11), injury (10), lineup (4), performance (4), recap (1)

**Top Players:** traeyoung (13), anthonydavis (3), giannisantetokounmpo (2), cooperflagg (2), konknueppel (2)

---

## Quick Start

### Fetch and Store News Articles

```bash
# Dry run - display articles
python bin/scrapers/fetch_news.py --dry-run --sport nba

# Save to BigQuery (with deduplication)
python bin/scrapers/fetch_news.py --save --dedupe

# Show recent from database
python bin/scrapers/fetch_news.py --show-recent --sport nba
```

### Get News for a Player (Website API)

```python
from scrapers.news import NewsPlayerLinksStorage

storage = NewsPlayerLinksStorage()
articles = storage.get_player_articles('lebronjames', sport='nba', limit=10)

for article in articles:
    print(f"Title: {article['title']}")
    print(f"Category: {article['article_category']}")
    print(f"URL: {article['source_url']}")
    print(f"AI Summary: {article['ai_summary']}")
```

### Generate AI Summaries

```python
from scrapers.news import NewsSummarizer

# Requires ANTHROPIC_API_KEY env var
summarizer = NewsSummarizer()

result = summarizer.summarize(
    article_id='abc123',
    title='LeBron ruled out vs Spurs',
    content='Lakers star LeBron James...',
    sport='NBA'
)
print(result.summary)  # "LeBron James (ankle, foot) is OUT for Wednesday's game."
print(f"Cost: ${result.cost_usd:.6f}")
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         NEWS PROCESSING PIPELINE                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ESPN RSS ──────┐                                                        │
│  CBS Sports ────┤──▶ RSSFetcher ──▶ news_articles_raw (BigQuery)        │
│                                           │                              │
│                                           ▼                              │
│                                    KeywordExtractor                      │
│                                           │                              │
│                                           ▼                              │
│                                    news_insights (BigQuery)              │
│                                           │                              │
│                                           ▼                              │
│                    PlayerLinker ──▶ news_player_links (BigQuery)        │
│                    (Registry)              │                             │
│                                           ▼                              │
│                                    NewsSummarizer ──▶ ai_summary         │
│                                    (Claude Haiku)                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## BigQuery Tables

| Table | Dataset | Purpose |
|-------|---------|---------|
| `news_articles_raw` | nba_raw | Raw articles from RSS feeds |
| `news_insights` | nba_analytics | Categories, keywords, AI summaries |
| `news_player_links` | nba_analytics | Player-article links for website |

### Sample Data

**news_player_links:**
```
+----------------------+---------------+-------------------------+
|    player_lookup     | article_count |       categories        |
+----------------------+---------------+-------------------------+
| traeyoung            |            13 | ["signing","trade"]     |
| anthonydavis         |             3 | ["lineup","trade"]      |
| lebronjames          |             1 | ["injury"]              |
+----------------------+---------------+-------------------------+
```

---

## Module Structure

```
scrapers/news/
├── __init__.py              # Module exports
├── rss_fetcher.py           # RSSFetcher, NewsArticle
├── storage.py               # NewsStorage, NewsInsightsStorage, NewsPlayerLinksStorage
├── keyword_extractor.py     # KeywordExtractor, NewsCategory
├── player_linker.py         # PlayerLinker (registry integration)
└── ai_summarizer.py         # NewsSummarizer (Claude Haiku)

bin/scrapers/
└── fetch_news.py            # CLI tool
```

---

## Cost Analysis

### RSS Fetching
- **Free** - No API costs

### AI Summarization (Claude Haiku)
- Input: $0.25 per 1M tokens
- Output: $1.25 per 1M tokens
- ~180 input + ~100 output tokens per article (actual observed)
- **Actual cost: $0.018 for 100 articles** ($0.00018/article)
- **~$0.54/month for 3000 articles**

### BigQuery Storage
- ~$0.10/month

**Total Estimated Cost: ~$0.50/month**

---

## Data Sources

### Active Sources (RSS)

| Source | Sport | URL | Update Frequency |
|--------|-------|-----|------------------|
| ESPN NBA | NBA | espn.com/espn/rss/nba/news | Real-time |
| ESPN MLB | MLB | espn.com/espn/rss/mlb/news | Real-time |
| CBS Sports NBA | NBA | cbssports.com/rss/headlines/nba/ | Real-time |
| CBS Sports MLB | MLB | cbssports.com/rss/headlines/mlb/ | Real-time |

### Disabled Sources (Available if needed)
- Yahoo Sports (RSS)
- MLB.com team feeds (30 team RSS feeds)

---

## News Categories

| Category | Description | Example Keywords |
|----------|-------------|------------------|
| injury | Player injuries, status updates | out, questionable, ankle, surgery |
| trade | Trades, trade rumors | traded, acquired, deal, deadline |
| signing | Contract signings, extensions | signed, contract, deal, extension |
| lineup | Lineup changes, rotations | starting, bench, rotation, rest |
| suspension | Suspensions, fines | suspended, banned, fined |
| performance | Game performances | scored, triple-double, career-high |
| preview | Game previews | matchup, tonight, odds |
| recap | Game recaps | beat, defeated, final score |

---

## Prerequisites

### For RSS Fetching
- `feedparser>=6.0.0` (in scrapers/requirements.txt)

### For AI Summaries
- `anthropic` package
- `ANTHROPIC_API_KEY` environment variable, OR
- `anthropic-api-key` secret in Secret Manager (Cloud Run)

---

## Related Documentation

- **[FUTURE-IMPROVEMENTS.md](./FUTURE-IMPROVEMENTS.md)** - Backlog of improvements
- **[DATA-SOURCES-PLAN.md](./DATA-SOURCES-PLAN.md)** - Detailed source planning
- **[ULTRATHINK-ANALYSIS.md](./ULTRATHINK-ANALYSIS.md)** - Deep analysis of approach
- **[IMPLEMENTATION-LOG.md](./IMPLEMENTATION-LOG.md)** - Progress tracking
- **[NEWS_API_REFERENCE.md](../../api/NEWS_API_REFERENCE.md)** - Frontend integration guide
- **[Daily Validation Checklist](../../02-operations/daily-validation-checklist.md)** - News validation section
- `shared/utils/player_registry/ai_resolver.py` - Claude API pattern reference

---

## Deployment

### Cloud Function
```bash
# Deploy function and scheduler
./bin/deploy/deploy_news_fetcher.sh

# Deploy function only
./bin/deploy/deploy_news_fetcher.sh --function-only

# Deploy scheduler only
./bin/deploy/deploy_news_fetcher.sh --scheduler-only
```

### Cloud Scheduler
- **Job name:** `news-fetcher`
- **Schedule:** Every 15 minutes (`*/15 * * * *`)
- **Timezone:** America/New_York

### Manual Trigger
```bash
gcloud scheduler jobs run news-fetcher --project=nba-props-platform --location=us-west2
```

---

## Future Enhancements

See **[FUTURE-IMPROVEMENTS.md](./FUTURE-IMPROVEMENTS.md)** for the full backlog.

**High Priority:**
- MLB player registry (needed before MLB season)
- News metrics dashboard
- Automated alerting for failures

**Medium Priority:**
- Additional news sources (The Athletic, team feeds)
- Real-time injury alerts via Pub/Sub
- News impact scoring for ML features

**Completed:**
- Phase 6 NewsExporter (GCS export)
- Streaming buffer fix (2026-01-09)
- Validation added to daily checklist
