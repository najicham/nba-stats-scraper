# News & AI Analysis: Data Sources Plan

**Created:** 2026-01-08
**Status:** Planning
**Purpose:** Define sources, extraction strategy, and data organization for news/AI analysis feature

---

## Table of Contents

1. [Data Sources Overview](#1-data-sources-overview)
2. [Recommended Sources by Tier](#2-recommended-sources-by-tier)
3. [Team News Strategy](#3-team-news-strategy)
4. [Player Entity Extraction](#4-player-entity-extraction)
5. [Data Schema Design](#5-data-schema-design)
6. [Implementation Architecture](#6-implementation-architecture)
7. [Cost Analysis](#7-cost-analysis)

---

## 1. Data Sources Overview

### Source Types Comparison

| Type | Pros | Cons | Best For |
|------|------|------|----------|
| **RSS Feeds** | Free, reliable, structured | Headlines only, no full text | Primary news monitoring |
| **News APIs** | Rich data, searchable | Cost at scale, rate limits | Targeted searches |
| **Web Scraping** | Full content access | Fragile, legal concerns | Last resort |
| **Social/X API** | Real-time breaking news | Noisy, expensive | Injury/trade alerts |

### Coverage Matrix

| Source | NBA | MLB | Update Freq | Cost | Content Type |
|--------|-----|-----|-------------|------|--------------|
| ESPN RSS | Yes | Yes | Real-time | Free | Headlines + Summary |
| CBS Sports RSS | Yes | Yes | Real-time | Free | Headlines + Summary |
| Yahoo Sports RSS | Yes | Yes | Real-time | Free | Headlines |
| MLB.com RSS | No | Yes | Real-time | Free | Full articles |
| NBA.com | Yes | No | Hourly | Free | Team news pages |
| RotoWire RSS | Yes | Yes | Real-time | Free | Player news |
| The Athletic RSS | Yes | Yes | Real-time | Free* | Titles only (*sub for full) |
| NewsAPI.org | Yes | Yes | Real-time | Freemium | Full articles |
| X/Twitter API | Yes | Yes | Real-time | Paid | Tweets |

---

## 2. Recommended Sources by Tier

### Tier 1: Primary Sources (Implement First)

These are free, reliable, and provide good coverage.

#### 2.1 ESPN RSS Feeds

**NBA Feed:**
```
https://www.espn.com/espn/rss/nba/news
```

**MLB Feed:**
```
https://www.espn.com/espn/rss/mlb/news
```

**Sample RSS Item Structure:**
```xml
<item>
  <title>LeBron James questionable for Lakers game vs Warriors</title>
  <link>https://www.espn.com/nba/story/_/id/12345678</link>
  <description>Lakers star LeBron James is listed as questionable...</description>
  <pubDate>Wed, 08 Jan 2026 14:30:00 EST</pubDate>
  <guid>https://www.espn.com/nba/story/_/id/12345678</guid>
</item>
```

**Pros:**
- Comprehensive coverage
- Reliable uptime
- Well-structured RSS
- Includes injury reports

**Cons:**
- Headlines + summary only (no full article)
- Must link back to ESPN per ToS

---

#### 2.2 MLB.com Official RSS

**Main Feed:**
```
http://mlb.mlb.com/news/rss/
```

**Team-Specific Feeds:**
```
https://www.mlb.com/yankees/feeds/news/rss.xml
https://www.mlb.com/dodgers/feeds/news/rss.xml
https://www.mlb.com/braves/feeds/news/rss.xml
... (all 30 teams)
```

**Pros:**
- Official source
- Team-level granularity
- Often includes full article text

**Cons:**
- MLB only
- Some feeds may be less active

---

#### 2.3 RotoWire Player News

**RSS Hub:**
```
https://www.rotowire.com/rss/
```

**NBA Player News:**
```
https://www.rotowire.com/basketball/news.php?rss=1
```

**MLB Player News:**
```
https://www.rotowire.com/baseball/news.php?rss=1
```

**Why RotoWire is Valuable:**
- **Player-focused**: Each item typically about one player
- **Fantasy-oriented**: Includes impact analysis
- **Timely**: Updates for injury/lineup changes

**Sample RotoWire Item:**
```xml
<item>
  <title>Anthony Davis (ankle) probable for Wednesday</title>
  <description>Davis (ankle) is listed as probable for Wednesday's
  game against the Suns. Fantasy Impact: Davis appears ready to return
  after missing the last two games...</description>
  <pubDate>Wed, 08 Jan 2026 11:00:00 EST</pubDate>
</item>
```

---

#### 2.4 CBS Sports RSS

**Main RSS Page:**
```
https://www.cbssports.com/xml/rss
```

**NBA:**
```
https://www.cbssports.com/rss/headlines/nba/
```

**MLB:**
```
https://www.cbssports.com/rss/headlines/mlb/
```

**Pros:**
- Good secondary source
- Different editorial perspective than ESPN

---

### Tier 2: Secondary Sources (Add Later)

#### 2.5 Yahoo Sports

**Syndication Hub:**
```
https://sports.yahoo.com/syndication/
```

**NBA:**
```
https://sports.yahoo.com/nba/rss.xml
```

**MLB:**
```
https://sports.yahoo.com/mlb/rss.xml
```

---

#### 2.6 NewsAPI.org (For Broader Coverage)

**Endpoint:**
```
GET https://newsapi.org/v2/everything?q=NBA+injury&apiKey=YOUR_KEY
GET https://newsapi.org/v2/everything?q=MLB+trade&apiKey=YOUR_KEY
```

**Parameters:**
- `q`: Search query (e.g., "Lakers injury", "Dodgers trade")
- `sources`: Limit to specific sources
- `from`/`to`: Date range
- `sortBy`: `publishedAt`, `relevancy`, `popularity`

**Free Tier:**
- 100 requests/day
- 1 month historical data
- Developer use only

**Paid Tiers:**
- $449/month for 250k requests
- Full article content
- Commercial use

**Best For:**
- Searching for specific player/team news
- Backfilling historical articles
- Broader news coverage

---

### Tier 3: Real-Time Breaking News

#### 2.7 X/Twitter API v2

**Key Accounts to Monitor:**

| Account | Type | Followers | Content |
|---------|------|-----------|---------|
| @wojespn | NBA Insider | 6M+ | Breaking trades, injuries |
| @ShamsCharania | NBA Insider | 3M+ | Breaking news |
| @JeffPassan | MLB Insider | 1.5M+ | MLB trades, signings |
| @Ken_Rosenthal | MLB Insider | 1M+ | MLB news |
| @FantasyLabsNBA | Fantasy | 200k+ | Injury updates |
| @Underdog__NBA | Fantasy | 150k+ | Lineup news |

**Filtered Stream Endpoint:**
```
POST https://api.twitter.com/2/tweets/search/stream/rules
{
  "add": [
    {"value": "from:wojespn", "tag": "woj"},
    {"value": "from:ShamsCharania", "tag": "shams"},
    {"value": "from:JeffPassan", "tag": "passan"}
  ]
}

GET https://api.twitter.com/2/tweets/search/stream
```

**Cost:**
- Basic: $100/month (10k tweets/month)
- Pro: $5000/month (1M tweets/month)

**Best For:**
- Breaking injury news (first to report)
- Trade announcements
- Lineup changes before games

**Recommendation:** Start without Twitter, add if value is proven.

---

### Tier 4: Specialized Sources (Optional)

#### 2.8 The Athletic (If Subscribed)

**RSS Pattern:**
```
https://theathletic.com/nba/?rss
https://theathletic.com/mlb/?rss
https://theathletic.com/team/lakers/?rss
```

**Note:** Only titles/summaries in RSS. Full content requires subscription ($8/month).

---

#### 2.9 Team Official Sites

**NBA Team News Pages:**
```
https://www.nba.com/lakers/news
https://www.nba.com/celtics/news
... (all 30 teams)
```

**Would require scraping** - not recommended unless critical.

---

## 3. Team News Strategy

### Should We Collect Team News?

**Recommendation: YES, but prioritize player-specific news**

### Team News Value Analysis

| News Type | Prediction Impact | Priority |
|-----------|------------------|----------|
| Starting lineup changes | HIGH | P0 |
| Coaching changes | HIGH | P0 |
| Trade announcements | HIGH | P0 |
| Team injury reports | HIGH | P0 |
| Rotation changes | MEDIUM | P1 |
| Practice reports | MEDIUM | P1 |
| Contract news | LOW | P2 |
| Front office changes | LOW | P2 |
| Fan/arena news | NONE | Skip |

### Team News Collection Strategy

**Option A: Aggregate from Player News (Recommended)**
- Most team news mentions players
- Extract team context from player-focused sources
- Simpler implementation

**Option B: Dedicated Team Feeds**
- Use MLB.com team-specific RSS feeds
- Scrape NBA.com team pages (more complex)
- More complete but higher maintenance

**Recommendation:** Start with Option A, add team feeds for MLB only (since they have good RSS).

### MLB Team RSS Feeds (30 Teams)

```python
MLB_TEAM_RSS_FEEDS = {
    'ARI': 'https://www.mlb.com/dbacks/feeds/news/rss.xml',
    'ATL': 'https://www.mlb.com/braves/feeds/news/rss.xml',
    'BAL': 'https://www.mlb.com/orioles/feeds/news/rss.xml',
    'BOS': 'https://www.mlb.com/redsox/feeds/news/rss.xml',
    'CHC': 'https://www.mlb.com/cubs/feeds/news/rss.xml',
    'CWS': 'https://www.mlb.com/whitesox/feeds/news/rss.xml',
    'CIN': 'https://www.mlb.com/reds/feeds/news/rss.xml',
    'CLE': 'https://www.mlb.com/guardians/feeds/news/rss.xml',
    'COL': 'https://www.mlb.com/rockies/feeds/news/rss.xml',
    'DET': 'https://www.mlb.com/tigers/feeds/news/rss.xml',
    'HOU': 'https://www.mlb.com/astros/feeds/news/rss.xml',
    'KC':  'https://www.mlb.com/royals/feeds/news/rss.xml',
    'LAA': 'https://www.mlb.com/angels/feeds/news/rss.xml',
    'LAD': 'https://www.mlb.com/dodgers/feeds/news/rss.xml',
    'MIA': 'https://www.mlb.com/marlins/feeds/news/rss.xml',
    'MIL': 'https://www.mlb.com/brewers/feeds/news/rss.xml',
    'MIN': 'https://www.mlb.com/twins/feeds/news/rss.xml',
    'NYM': 'https://www.mlb.com/mets/feeds/news/rss.xml',
    'NYY': 'https://www.mlb.com/yankees/feeds/news/rss.xml',
    'OAK': 'https://www.mlb.com/athletics/feeds/news/rss.xml',
    'PHI': 'https://www.mlb.com/phillies/feeds/news/rss.xml',
    'PIT': 'https://www.mlb.com/pirates/feeds/news/rss.xml',
    'SD':  'https://www.mlb.com/padres/feeds/news/rss.xml',
    'SF':  'https://www.mlb.com/giants/feeds/news/rss.xml',
    'SEA': 'https://www.mlb.com/mariners/feeds/news/rss.xml',
    'STL': 'https://www.mlb.com/cardinals/feeds/news/rss.xml',
    'TB':  'https://www.mlb.com/rays/feeds/news/rss.xml',
    'TEX': 'https://www.mlb.com/rangers/feeds/news/rss.xml',
    'TOR': 'https://www.mlb.com/bluejays/feeds/news/rss.xml',
    'WSH': 'https://www.mlb.com/nationals/feeds/news/rss.xml',
}
```

---

## 4. Player Entity Extraction

### The Core Challenge

Raw news articles mention players by various names:
- "LeBron" (first name only)
- "James" (last name only)
- "LeBron James"
- "The King" (nickname)
- "Lakers star"
- "the 39-year-old forward"

We need to:
1. **Extract** player mentions from text
2. **Resolve** mentions to canonical player IDs
3. **Link** articles to players in our registry

### Extraction Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PLAYER EXTRACTION PIPELINE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Raw Article                                                         │
│       │                                                              │
│       ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  STAGE 1: AI Entity Extraction                               │    │
│  │  - Extract all player name mentions                          │    │
│  │  - Extract team mentions                                     │    │
│  │  - Classify news type (injury, trade, etc.)                  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│       │                                                              │
│       ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  STAGE 2: Player Registry Lookup                             │    │
│  │  - Try direct match on player_lookup                         │    │
│  │  - Try alias matching                                        │    │
│  │  - Try fuzzy matching with team context                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│       │                                                              │
│       ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  STAGE 3: AI Resolution (for unmatched)                      │    │
│  │  - Use existing AINameResolver pattern                       │    │
│  │  - Resolve ambiguous names with context                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│       │                                                              │
│       ▼                                                              │
│  Structured Output: Article + Player Links                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Stage 1: AI Entity Extraction Prompt

```python
NEWS_EXTRACTION_PROMPT = """
You are a sports news analyst. Extract structured information from this article.

Article:
{article_text}

Source: {source}
Published: {publish_date}

Extract and return as JSON:
{{
  "players_mentioned": [
    {{
      "name_as_written": "exact name from article",
      "likely_full_name": "best guess at full name",
      "team_context": "team mentioned or null",
      "role": "primary" | "secondary" | "mentioned",
      "context": "brief context of mention (injury, trade, etc.)"
    }}
  ],
  "teams_mentioned": ["LAL", "BOS", ...],
  "news_category": "injury" | "trade" | "lineup" | "performance" | "personal" | "other",
  "news_subcategory": "questionable" | "out" | "trade_rumor" | "signed" | etc,
  "sentiment": "positive" | "negative" | "neutral",
  "prediction_relevance": 1-10,
  "key_facts": ["fact 1", "fact 2", ...],
  "effective_date": "YYYY-MM-DD or null if ongoing"
}}

Rules:
1. "primary" player = main subject of article
2. "secondary" = significantly discussed
3. "mentioned" = briefly referenced
4. Include ALL players mentioned, even briefly
5. Use standard team abbreviations (LAL, BOS, NYY, etc.)
6. prediction_relevance: 10 = critical (injury, trade), 1 = not relevant
"""
```

### Stage 2: Player Registry Lookup

```python
def resolve_player_mention(mention: dict, sport: str) -> Optional[str]:
    """
    Resolve a player mention to canonical player_lookup.

    Returns player_lookup or None if unresolved.
    """
    full_name = mention['likely_full_name']
    team = mention.get('team_context')

    # Step 1: Direct lookup (normalize name)
    normalized = normalize_name(full_name)  # "LeBron James" -> "lebronjames"
    if player_exists(normalized, sport):
        return normalized

    # Step 2: Alias lookup
    alias_match = lookup_alias(full_name, sport)
    if alias_match:
        return alias_match

    # Step 3: Fuzzy match with team context
    if team:
        team_roster = get_team_roster(team, sport)
        fuzzy_match = fuzzy_match_name(full_name, team_roster, threshold=0.85)
        if fuzzy_match:
            return fuzzy_match

    # Step 4: Return None -> needs AI resolution
    return None
```

### Stage 3: AI Resolution (Existing Pattern)

We already have `AINameResolver` in `shared/utils/player_registry/ai_resolver.py`.

```python
from shared.utils.player_registry.ai_resolver import AINameResolver, ResolutionContext

def ai_resolve_player(mention: dict, sport: str) -> Optional[str]:
    """Use AI to resolve ambiguous player mention."""

    resolver = AINameResolver()

    context = ResolutionContext(
        unresolved_lookup=normalize_name(mention['likely_full_name']),
        unresolved_display=mention['likely_full_name'],
        team_abbr=mention.get('team_context'),
        season=get_current_season(sport),
        team_roster=get_team_roster(mention.get('team_context'), sport),
        similar_names=find_similar_names(mention['likely_full_name'], sport),
        source='news_extraction'
    )

    result = resolver.resolve_single(context)

    if result.resolution_type == 'MATCH':
        return result.canonical_lookup
    return None
```

### Article-Player Linking Table

```sql
-- Links articles to players (many-to-many)
CREATE TABLE news_article_players (
    article_id STRING NOT NULL,
    player_lookup STRING NOT NULL,
    sport STRING NOT NULL,  -- 'nba' or 'mlb'
    mention_role STRING,  -- 'primary', 'secondary', 'mentioned'
    mention_context STRING,  -- brief context
    confidence FLOAT64,  -- extraction confidence
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (article_id, player_lookup)
);
```

---

## 5. Data Schema Design

### Core Tables

#### 5.1 Raw News Articles

```sql
CREATE TABLE nba_raw.news_articles (
    -- Identity
    article_id STRING NOT NULL,  -- hash of url or guid

    -- Source Info
    source STRING NOT NULL,  -- 'espn_rss', 'rotowire', 'newsapi', etc.
    source_url STRING,
    source_guid STRING,  -- original RSS guid

    -- Content
    title STRING NOT NULL,
    summary STRING,  -- RSS description or article excerpt
    full_text STRING,  -- if available (NewsAPI, scraping)

    -- Metadata
    published_at TIMESTAMP NOT NULL,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sport STRING NOT NULL,  -- 'nba' or 'mlb'

    -- Processing Status
    ai_processed BOOL DEFAULT FALSE,
    ai_processed_at TIMESTAMP,

    -- Deduplication
    content_hash STRING,  -- hash of title+summary for dedup

    PRIMARY KEY (article_id)
)
PARTITION BY DATE(published_at)
CLUSTER BY sport, source;
```

#### 5.2 AI-Extracted News Insights

```sql
CREATE TABLE nba_analytics.news_insights (
    -- Identity
    insight_id STRING NOT NULL,  -- generated UUID
    article_id STRING NOT NULL,  -- FK to news_articles

    -- Classification
    news_category STRING,  -- 'injury', 'trade', 'lineup', 'performance', 'personal', 'other'
    news_subcategory STRING,  -- 'questionable', 'out', 'trade_rumor', 'signed', etc.
    sentiment STRING,  -- 'positive', 'negative', 'neutral'
    prediction_relevance INT64,  -- 1-10 scale

    -- Key Facts
    key_facts ARRAY<STRING>,
    effective_date DATE,  -- when the news takes effect

    -- Teams
    teams_mentioned ARRAY<STRING>,  -- ['LAL', 'BOS']
    primary_team STRING,  -- main team in article

    -- AI Metadata
    ai_model STRING,
    ai_confidence FLOAT64,
    extraction_tokens INT64,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (insight_id)
)
PARTITION BY DATE(created_at)
CLUSTER BY news_category, primary_team;
```

#### 5.3 Article-Player Links

```sql
CREATE TABLE nba_analytics.news_player_links (
    -- Keys
    article_id STRING NOT NULL,
    player_lookup STRING NOT NULL,
    sport STRING NOT NULL,

    -- Mention Details
    mention_role STRING,  -- 'primary', 'secondary', 'mentioned'
    name_as_written STRING,  -- "LeBron", "James", "the Lakers star"
    mention_context STRING,  -- "ankle injury", "trade target", etc.

    -- Resolution
    resolution_method STRING,  -- 'direct', 'alias', 'fuzzy', 'ai'
    resolution_confidence FLOAT64,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (article_id, player_lookup, sport)
)
CLUSTER BY sport, player_lookup;
```

#### 5.4 Player News Feed (Denormalized View)

```sql
-- Materialized view for fast player news lookups
CREATE MATERIALIZED VIEW nba_analytics.player_news_feed AS
SELECT
    pl.player_lookup,
    pl.sport,
    a.article_id,
    a.title,
    a.summary,
    a.source,
    a.source_url,
    a.published_at,
    i.news_category,
    i.news_subcategory,
    i.sentiment,
    i.prediction_relevance,
    i.key_facts,
    pl.mention_role,
    pl.mention_context
FROM nba_analytics.news_player_links pl
JOIN nba_raw.news_articles a ON pl.article_id = a.article_id
LEFT JOIN nba_analytics.news_insights i ON a.article_id = i.article_id
ORDER BY pl.player_lookup, a.published_at DESC;
```

### ML Feature Store Integration

```sql
-- Add news-derived features to ML feature store
ALTER TABLE nba_precompute.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS news_injury_flag BOOL,
ADD COLUMN IF NOT EXISTS news_injury_severity STRING,  -- 'out', 'doubtful', 'questionable', 'probable'
ADD COLUMN IF NOT EXISTS news_trade_rumor_flag BOOL,
ADD COLUMN IF NOT EXISTS news_recent_count INT64,  -- articles in last 7 days
ADD COLUMN IF NOT EXISTS news_sentiment_avg FLOAT64,  -- avg sentiment last 7 days
ADD COLUMN IF NOT EXISTS news_last_update TIMESTAMP;
```

---

## 6. Implementation Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NEWS PROCESSING PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐                                                        │
│  │   RSS FEEDS      │ ESPN, CBS, RotoWire, MLB.com, Yahoo                   │
│  │   (Tier 1)       │ ─────┐                                                │
│  └──────────────────┘      │                                                │
│                            │                                                │
│  ┌──────────────────┐      │     ┌─────────────────────┐                    │
│  │   NEWS APIS      │      ├────▶│  NEWS SCRAPER       │                    │
│  │   (Tier 2)       │ ─────┤     │  (Cloud Function)   │                    │
│  └──────────────────┘      │     │                     │                    │
│                            │     │  - Fetch RSS        │                    │
│  ┌──────────────────┐      │     │  - Deduplicate      │                    │
│  │   TWITTER API    │      │     │  - Store raw        │                    │
│  │   (Tier 3)       │ ─────┘     └─────────┬───────────┘                    │
│  └──────────────────┘                      │                                │
│                                            │ Pub/Sub                        │
│                                            ▼                                │
│                            ┌─────────────────────────────┐                  │
│                            │  AI EXTRACTION PROCESSOR    │                  │
│                            │  (Cloud Run)                │                  │
│                            │                             │                  │
│                            │  - Extract entities         │                  │
│                            │  - Classify news type       │                  │
│                            │  - Extract key facts        │                  │
│                            │  - Resolve player IDs       │                  │
│                            └─────────────┬───────────────┘                  │
│                                          │ Pub/Sub                          │
│                                          ▼                                  │
│                            ┌─────────────────────────────┐                  │
│                            │  FEATURE UPDATER            │                  │
│                            │  (Cloud Run)                │                  │
│                            │                             │                  │
│                            │  - Update ML feature store  │                  │
│                            │  - Update player news feed  │                  │
│                            │  - Trigger alerts           │                  │
│                            └─────────────────────────────┘                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Scraping Schedule

```yaml
# Cloud Scheduler jobs

news_scraper_tier1_frequent:
  schedule: "*/15 * * * *"  # Every 15 minutes
  target: news_scraper
  params:
    sources: ["espn_nba", "espn_mlb", "rotowire_nba", "rotowire_mlb"]
  description: "High-priority sources for injury/lineup news"

news_scraper_tier1_hourly:
  schedule: "0 * * * *"  # Every hour
  target: news_scraper
  params:
    sources: ["cbs_nba", "cbs_mlb", "yahoo_nba", "yahoo_mlb"]
  description: "Secondary sources"

news_scraper_mlb_teams:
  schedule: "0 */2 * * *"  # Every 2 hours
  target: news_scraper
  params:
    sources: ["mlb_team_feeds"]  # All 30 team RSS feeds
  description: "MLB team-specific news"

news_ai_processor:
  schedule: "*/5 * * * *"  # Every 5 minutes
  target: news_ai_processor
  params:
    batch_size: 20
  description: "Process unprocessed articles"
```

### Deduplication Strategy

Articles from different sources often cover the same news:

```python
def compute_content_hash(article: dict) -> str:
    """
    Create hash for deduplication.
    Uses normalized title + first 100 chars of summary.
    """
    title_normalized = normalize_text(article['title'])
    summary_normalized = normalize_text(article.get('summary', ''))[:100]

    content = f"{title_normalized}|{summary_normalized}"
    return hashlib.md5(content.encode()).hexdigest()

def is_duplicate(article: dict, lookback_hours: int = 24) -> bool:
    """Check if article is duplicate of recent article."""
    content_hash = compute_content_hash(article)

    query = """
    SELECT article_id FROM nba_raw.news_articles
    WHERE content_hash = @hash
      AND published_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
    LIMIT 1
    """

    result = bq_client.query(query, params={'hash': content_hash, 'hours': lookback_hours})
    return len(list(result)) > 0
```

---

## 7. Cost Analysis

### AI API Costs (Claude)

| Model | Input Cost | Output Cost | Use Case |
|-------|------------|-------------|----------|
| claude-3-haiku | $0.25/1M tokens | $1.25/1M tokens | Entity extraction |
| claude-3-sonnet | $3/1M tokens | $15/1M tokens | Complex analysis |

**Estimated Usage:**
- ~500 articles/day across all sources
- ~800 tokens/article (input)
- ~300 tokens/article (output)
- Using Haiku: **~$0.30/day** = **$9/month**

### BigQuery Costs

| Operation | Cost | Estimated Volume | Monthly Cost |
|-----------|------|------------------|--------------|
| Storage | $0.02/GB/month | ~1 GB/month | $0.02 |
| Queries | $5/TB scanned | ~10 GB/month | $0.05 |
| Streaming inserts | $0.01/200MB | ~100 MB/month | $0.01 |

**Total BigQuery:** ~$0.10/month

### Cloud Run/Functions

| Service | Free Tier | Estimated Usage | Monthly Cost |
|---------|-----------|-----------------|--------------|
| Cloud Functions | 2M invocations | ~50k/month | $0 |
| Cloud Run | 180k vCPU-sec | ~10k vCPU-sec | $0 |

### Optional: NewsAPI.org

| Tier | Cost | Requests | Notes |
|------|------|----------|-------|
| Developer | Free | 100/day | Non-commercial only |
| Business | $449/month | 250k/month | Full articles |

**Recommendation:** Start without NewsAPI, add if needed.

### Optional: Twitter API

| Tier | Cost | Tweets | Notes |
|------|------|--------|-------|
| Basic | $100/month | 10k/month | Filtered stream |
| Pro | $5000/month | 1M/month | Full access |

**Recommendation:** Skip initially, add only if breaking news latency is critical.

### Total Estimated Monthly Cost

| Component | Cost |
|-----------|------|
| Claude AI (Haiku) | $9 |
| BigQuery | $0.10 |
| Cloud Run/Functions | $0 |
| **Total (Base)** | **~$10/month** |
| + NewsAPI (optional) | +$449 |
| + Twitter (optional) | +$100 |

---

## Summary

### Recommended Implementation Order

1. **Phase 1: MVP** (Tier 1 RSS only)
   - ESPN NBA/MLB RSS
   - RotoWire player news RSS
   - Basic AI extraction
   - Player registry linking
   - **Timeline:** 2-3 weeks
   - **Cost:** ~$10/month

2. **Phase 2: Expand Sources**
   - Add CBS, Yahoo RSS
   - Add MLB team feeds
   - Improve deduplication
   - **Timeline:** 1-2 weeks
   - **Cost:** Same

3. **Phase 3: ML Integration**
   - Add news features to ML feature store
   - Measure prediction impact
   - **Timeline:** 1-2 weeks

4. **Phase 4: Real-time (Optional)**
   - Add Twitter API if value proven
   - Sub-minute breaking news
   - **Timeline:** 1 week
   - **Cost:** +$100/month

### Key Decisions

| Decision | Recommendation | Rationale |
|----------|----------------|-----------|
| Include team news? | Yes (via MLB RSS) | Good signal, low effort |
| Which AI model? | Claude Haiku | Cost-effective, good enough |
| Full article text? | No (start with headlines) | RSS free, NewsAPI expensive |
| Twitter integration? | No (initially) | $100/month, unproven value |
| Scraping? | No | Legal risk, maintenance burden |
