# News & AI Analysis Feature

**Created:** 2026-01-08
**Status:** Implemented (Phase 1-3 Complete)
**Priority:** Active

---

## Overview

This feature scrapes sports news from RSS feeds, extracts player mentions, links them to our player registry, and generates AI summaries - enabling news articles to be displayed on player pages on the website.

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | Complete | RSS fetching from ESPN + CBS Sports |
| Phase 2 | Complete | Keyword extraction and categorization |
| Phase 2.5 | Complete | Player registry linking |
| Phase 3 | Complete | AI summarization with Claude Haiku |
| Phase 4 | Not Started | ML feature integration |

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
- ~200 input + ~80 output tokens per article
- **~$0.01 per 100 articles**
- **~$0.30/month for 3000 articles**

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

- **[DATA-SOURCES-PLAN.md](./DATA-SOURCES-PLAN.md)** - Detailed source planning
- **[ULTRATHINK-ANALYSIS.md](./ULTRATHINK-ANALYSIS.md)** - Deep analysis of approach
- **[IMPLEMENTATION-LOG.md](./IMPLEMENTATION-LOG.md)** - Progress tracking
- `shared/utils/player_registry/ai_resolver.py` - Claude API pattern reference

---

## Future Enhancements

1. **Scheduled Jobs** - Auto-run news fetching every 15 minutes
2. **ML Integration** - Add news features to prediction models
3. **More Sources** - RotoWire, The Athletic, Twitter/X
4. **Real-time Alerts** - Push notifications for injury news
