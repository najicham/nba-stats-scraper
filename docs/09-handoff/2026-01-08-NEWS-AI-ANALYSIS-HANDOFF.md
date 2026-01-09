# News & AI Analysis Feature - Session Handoff

**Date:** 2026-01-08
**Status:** Feature Complete, Needs API Key Fix for Local Testing
**Priority:** Ready for Use

---

## Executive Summary

Built a complete news scraping and AI analysis pipeline for displaying player news on the website. Everything works except AI summaries need the `ANTHROPIC_API_KEY` to be accessible locally (it's in Secret Manager but not exported to local env).

---

## What Was Built

### Files Created

```
scrapers/news/
├── __init__.py              # Module exports
├── rss_fetcher.py           # RSS feed fetching (ESPN, CBS Sports)
├── storage.py               # 3 storage classes for BigQuery
├── keyword_extractor.py     # Category classification (injury, trade, etc.)
├── player_linker.py         # Links player names to registry
└── ai_summarizer.py         # Claude Haiku summaries (cost-optimized)

bin/scrapers/
└── fetch_news.py            # CLI tool for fetching/saving news

docs/08-projects/current/news-ai-analysis/
├── README.md                # Full documentation (updated)
├── DATA-SOURCES-PLAN.md     # Source planning
├── ULTRATHINK-ANALYSIS.md   # Design decisions
└── IMPLEMENTATION-LOG.md    # Progress tracking
```

### BigQuery Tables Created

| Table | Dataset | Records | Purpose |
|-------|---------|---------|---------|
| `news_articles_raw` | nba_raw | 100 | Raw articles from RSS |
| `news_insights` | nba_analytics | 100 | Categories, keywords, AI summaries |
| `news_player_links` | nba_analytics | 41 | Player-article links for website |

### Dependencies Added

```
scrapers/requirements.txt:
  feedparser>=6.0.0
```

---

## What Works

### 1. RSS Fetching (100% Working)

```bash
# Fetch and display NBA news
python bin/scrapers/fetch_news.py --dry-run --sport nba

# Save to BigQuery with deduplication
python bin/scrapers/fetch_news.py --save --dedupe
```

### 2. Keyword Extraction (100% Working)

Automatically categorizes articles:
- injury, trade, signing, lineup, suspension, performance, preview, recap

### 3. Player Registry Linking (100% Working)

Links extracted player names to our registry:
```python
from scrapers.news import PlayerLinker

linker = PlayerLinker(sport='nba')
result = linker.link_player("LeBron James", team_context="LAL")
# Returns: player_lookup='lebronjames', confidence=1.0
```

### 4. Website Queries (100% Working)

```python
from scrapers.news import NewsPlayerLinksStorage

storage = NewsPlayerLinksStorage()
articles = storage.get_player_articles('traeyoung', sport='nba', limit=10)
# Returns articles with title, summary, source_url, category, ai_summary
```

### 5. AI Summarizer (Module Complete, Needs API Key Access)

```python
from scrapers.news import NewsSummarizer

# This fails locally because ANTHROPIC_API_KEY not in local env
summarizer = NewsSummarizer()
```

---

## What Needs to be Done

### Priority 1: Fix API Key Access for Local Testing

The `anthropic-api-key` EXISTS in Secret Manager:
```
gcloud secrets list --filter="name:anthropic"
# Shows: anthropic-api-key created 2025-12-06
```

**Options to fix:**

**Option A: Export from Secret Manager to local env**
```bash
export ANTHROPIC_API_KEY=$(gcloud secrets versions access latest --secret=anthropic-api-key)
```

**Option B: Add to .env file**
```bash
echo "ANTHROPIC_API_KEY=$(gcloud secrets versions access latest --secret=anthropic-api-key)" >> .env
```

**Option C: The AI resolver already works in Cloud Run** - Just test there

### Priority 2: Generate AI Summaries for Existing Articles

Once API key is accessible:
```python
from scrapers.news import NewsSummarizer, NewsStorage, NewsPlayerLinksStorage

# Get articles without summaries
storage = NewsStorage()
articles = storage.get_unprocessed_articles(limit=100)

# Generate summaries
summarizer = NewsSummarizer()
results, stats = summarizer.summarize_batch(articles, sport='NBA')

# Save summaries
links_storage = NewsPlayerLinksStorage()
for result in results:
    links_storage.update_ai_summary(result.article_id, result.summary)

print(f"Cost: ${stats['total_cost_usd']:.4f}")
```

### Priority 3 (Optional): Set Up Scheduled Job

Add to Cloud Scheduler to run every 15 minutes:
- Fetch new articles from RSS
- Extract keywords and link players
- Generate AI summaries for new articles

---

## Key Files to Study

| File | Purpose | Priority |
|------|---------|----------|
| `docs/08-projects/current/news-ai-analysis/README.md` | Full documentation | HIGH |
| `scrapers/news/__init__.py` | Module exports | HIGH |
| `scrapers/news/ai_summarizer.py` | AI summary generation | HIGH |
| `scrapers/news/player_linker.py` | Registry integration | MEDIUM |
| `shared/utils/player_registry/ai_resolver.py` | Existing Claude API pattern | MEDIUM |

---

## Architecture Diagram

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

## Cost Analysis

| Component | Monthly Cost |
|-----------|--------------|
| RSS Fetching | Free |
| AI Summaries (~3000 articles) | ~$0.30 |
| BigQuery Storage | ~$0.10 |
| **Total** | **~$0.50/month** |

---

## Sample Data in BigQuery

### Player Links
```sql
SELECT player_lookup, COUNT(*) as articles
FROM `nba-props-platform.nba_analytics.news_player_links`
GROUP BY player_lookup
ORDER BY articles DESC
LIMIT 5;

-- Results:
-- traeyoung: 13 articles
-- anthonydavis: 3 articles
-- giannisantetokounmpo: 2 articles
```

### Articles by Category
```sql
SELECT category, COUNT(*) as count
FROM `nba-props-platform.nba_analytics.news_insights`
GROUP BY category
ORDER BY count DESC;

-- Results:
-- trade: 30
-- signing: 21
-- other: 19
-- preview: 11
-- injury: 10
```

---

## Testing Commands

```bash
# Test RSS fetching (no API key needed)
python bin/scrapers/fetch_news.py --dry-run --sport nba --limit 5

# Test player linking (no API key needed)
python -c "
from scrapers.news import PlayerLinker
linker = PlayerLinker(sport='nba')
result = linker.link_player('LeBron James', 'LAL')
print(f'Linked: {result.player_lookup}')
"

# Test website query (no API key needed)
python -c "
from scrapers.news import NewsPlayerLinksStorage
storage = NewsPlayerLinksStorage()
articles = storage.get_player_articles('traeyoung', limit=3)
for a in articles:
    print(f'{a[\"title\"][:50]}...')
"

# Test AI summarizer (NEEDS API KEY)
export ANTHROPIC_API_KEY=\$(gcloud secrets versions access latest --secret=anthropic-api-key)
python -c "
from scrapers.news import NewsSummarizer
s = NewsSummarizer()
r = s.summarize('test', 'LeBron out vs Spurs', 'Lakers star...', 'NBA')
print(r.summary)
"
```

---

## Git Status

Files modified/created (not committed):
- `scrapers/news/` (new directory with 5 files)
- `bin/scrapers/fetch_news.py` (new CLI)
- `scrapers/requirements.txt` (added feedparser)
- `docs/08-projects/current/news-ai-analysis/` (4 docs updated)

---

## Questions for Next Session

1. Should we commit the news scraper code?
2. Should we set up the scheduled job now or wait?
3. Do you want to test AI summaries by exporting the API key?
4. Should we integrate news into the website now?

---

## Related Existing Code

- `shared/utils/player_registry/ai_resolver.py` - Uses same Claude API pattern
- `shared/utils/auth_utils.py` - API key management (get_api_key function)
- Secret Manager: `anthropic-api-key` - Already exists and working for AI name resolver
