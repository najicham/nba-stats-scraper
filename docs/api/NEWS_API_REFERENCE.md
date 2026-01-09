# News API Reference

**Created:** 2026-01-08
**Status:** Active
**Last Updated:** 2026-01-09

This document describes the news data available for frontend integration.

---

## Overview

The news system scrapes sports news from RSS feeds (ESPN, CBS Sports), categorizes articles, links player mentions to our registry, and generates AI summaries.

**Data Flow:**
```
RSS Feeds → BigQuery → (Future: GCS JSON Export) → Frontend
```

---

## Current Access Method: BigQuery

Until a Phase 6 exporter is built, query BigQuery directly or use the Python API.

### Python API

```python
from scrapers.news import NewsPlayerLinksStorage

storage = NewsPlayerLinksStorage()

# Get news for a specific player
articles = storage.get_player_articles(
    player_lookup='lebronjames',  # From player registry
    sport='nba',
    limit=10
)

for article in articles:
    print(article)
```

---

## Data Schemas

### Player News Response

When querying news for a player, you receive:

```json
{
  "article_id": "a1b2c3d4e5f6",
  "title": "LeBron James ruled out vs. Spurs with multiple injuries",
  "summary": "Lakers star LeBron James did not play against the Spurs on Wednesday...",
  "source": "espn_nba",
  "source_url": "https://www.espn.com/nba/story/_/id/12345",
  "published_at": "2026-01-08T19:30:00Z",
  "author": "Adrian Wojnarowski",
  "mention_role": "primary",
  "article_category": "injury",
  "link_confidence": 1.0,
  "ai_summary": "LeBron James is OUT for Wednesday's game against the Spurs due to ankle and foot injuries."
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `article_id` | string | Unique identifier for the article |
| `title` | string | Article headline |
| `summary` | string | Article excerpt/description from RSS |
| `source` | string | Source identifier (see Sources below) |
| `source_url` | string | Link to original article |
| `published_at` | timestamp | When article was published |
| `author` | string? | Author name (may be null) |
| `mention_role` | string | `primary`, `secondary`, or `mentioned` |
| `article_category` | string | Category (see Categories below) |
| `link_confidence` | float | 0-1 confidence of player link |
| `ai_summary` | string? | AI-generated 1-2 sentence summary |

---

## Sources

| Source ID | Display Name | Sport |
|-----------|--------------|-------|
| `espn_nba` | ESPN | NBA |
| `espn_mlb` | ESPN | MLB |
| `cbs_nba` | CBS Sports | NBA |
| `cbs_mlb` | CBS Sports | MLB |
| `yahoo_nba` | Yahoo Sports | NBA |
| `yahoo_mlb` | Yahoo Sports | MLB |

**Display Logic:**
```javascript
const sourceDisplay = {
  'espn_nba': 'ESPN',
  'espn_mlb': 'ESPN',
  'cbs_nba': 'CBS Sports',
  'cbs_mlb': 'CBS Sports',
  'yahoo_nba': 'Yahoo Sports',
  'yahoo_mlb': 'Yahoo Sports'
};
```

---

## Categories

| Category | Description | Display Priority |
|----------|-------------|------------------|
| `injury` | Player injuries, status updates | High |
| `trade` | Trades, trade rumors | High |
| `signing` | Contract signings, extensions | Medium |
| `lineup` | Lineup changes, rotations | Medium |
| `suspension` | Suspensions, fines | Medium |
| `performance` | Game performances | Low |
| `preview` | Game previews | Low |
| `recap` | Game recaps | Low |
| `other` | Uncategorized | Low |

**Suggested Category Colors:**
```javascript
const categoryColors = {
  'injury': '#dc2626',      // red
  'trade': '#7c3aed',       // purple
  'signing': '#2563eb',     // blue
  'lineup': '#059669',      // green
  'suspension': '#d97706',  // orange
  'performance': '#6b7280', // gray
  'preview': '#6b7280',     // gray
  'recap': '#6b7280',       // gray
  'other': '#6b7280'        // gray
};
```

---

## Example: Player News Card

### Data
```json
{
  "title": "LeBron James ruled out vs. Spurs with multiple injuries",
  "source": "espn_nba",
  "source_url": "https://www.espn.com/nba/story/_/id/12345",
  "published_at": "2026-01-08T19:30:00Z",
  "article_category": "injury",
  "ai_summary": "LeBron James is OUT for Wednesday's game against the Spurs due to ankle and foot injuries."
}
```

### Suggested UI Rendering

```
┌─────────────────────────────────────────────────────────┐
│ 🔴 INJURY                                    2 hours ago│
├─────────────────────────────────────────────────────────┤
│ LeBron James ruled out vs. Spurs with multiple injuries │
│                                                         │
│ LeBron James is OUT for Wednesday's game against the    │
│ Spurs due to ankle and foot injuries.                   │
│                                                         │
│ ESPN · Read more →                                      │
└─────────────────────────────────────────────────────────┘
```

---

## GCS JSON Endpoints (LIVE)

News is available as static JSON files via GCS CDN.

**Base URL:** `https://storage.googleapis.com/nba-props-platform-api/v1`

### Player News Endpoint
```
/player-news/{sport}/{player_lookup}.json
```

**Examples:**
```
https://storage.googleapis.com/nba-props-platform-api/v1/player-news/nba/lebronjames.json
https://storage.googleapis.com/nba-props-platform-api/v1/player-news/mlb/shoheiohtani.json
```

**Response:**
```json
{
  "player_lookup": "lebronjames",
  "player_name": "LeBron James",
  "team_abbr": "LAL",
  "sport": "nba",
  "updated_at": "2026-01-09T03:49:40Z",
  "has_critical_news": true,
  "critical_category": "injury",
  "news_count": 1,
  "articles": [
    {
      "id": "a1b2c3d4",
      "headline": "LeBron OUT vs Spurs",
      "title": "LeBron James ruled out vs. Spurs with multiple injuries",
      "summary": "LeBron James is OUT for Wednesday's game against the Spurs due to ankle and foot injuries.",
      "category": "injury",
      "impact": "high",
      "source": "ESPN",
      "source_url": "https://www.espn.com/...",
      "published_at": "2026-01-08T19:30:00Z",
      "is_primary_mention": true
    }
  ]
}
```

**Cache:** `public, max-age=900` (15 minutes)

---

### Tonight Summary Endpoint
```
/player-news/{sport}/tonight-summary.json
```

**Examples:**
```
https://storage.googleapis.com/nba-props-platform-api/v1/player-news/nba/tonight-summary.json
https://storage.googleapis.com/nba-props-platform-api/v1/player-news/mlb/tonight-summary.json
```

**Response:**
```json
{
  "updated_at": "2026-01-09T03:49:37Z",
  "sport": "nba",
  "total_players": 22,
  "players": [
    {
      "player_lookup": "traeyoung",
      "has_critical_news": true,
      "critical_category": "trade",
      "news_count": 13,
      "latest_category": "signing"
    },
    {
      "player_lookup": "lebronjames",
      "has_critical_news": true,
      "critical_category": "injury",
      "news_count": 1,
      "latest_category": "injury"
    }
  ]
}
```

**Cache:** `public, max-age=300` (5 minutes)

---

## Impact Levels

| Impact | Categories | UI Treatment |
|--------|------------|--------------|
| `high` | injury, trade, suspension | Red indicator |
| `medium` | signing, lineup | Orange indicator |
| `low` | preview, recap, performance, other | Gray/none |

---

## BigQuery Direct Query Examples

### Get Recent Injury News
```sql
SELECT
  l.player_lookup,
  a.title,
  a.source_url,
  a.published_at,
  i.ai_summary
FROM `nba-props-platform.nba_analytics.news_player_links` l
JOIN `nba-props-platform.nba_raw.news_articles_raw` a
  ON l.article_id = a.article_id
LEFT JOIN `nba-props-platform.nba_analytics.news_insights` i
  ON l.article_id = i.article_id
WHERE l.article_category = 'injury'
  AND l.sport = 'nba'
  AND a.published_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY a.published_at DESC
LIMIT 20
```

### Get News for a Player
```sql
SELECT
  a.title,
  a.summary,
  a.source,
  a.source_url,
  a.published_at,
  l.article_category,
  i.ai_summary
FROM `nba-props-platform.nba_analytics.news_player_links` l
JOIN `nba-props-platform.nba_raw.news_articles_raw` a
  ON l.article_id = a.article_id
LEFT JOIN `nba-props-platform.nba_analytics.news_insights` i
  ON l.article_id = i.article_id
WHERE l.player_lookup = 'lebronjames'
  AND l.sport = 'nba'
ORDER BY a.published_at DESC
LIMIT 10
```

---

## Data Freshness

| Metric | Value |
|--------|-------|
| RSS fetch frequency | Every 15 minutes (Cloud Scheduler) |
| AI summary generation | Automatic for new articles |
| GCS export frequency | Automatic every 15 minutes (incremental) |
| Typical latency | < 20 minutes from publication |

---

## Answers to Frontend Questions

**1. Headline generation:** Yes, AI generates short headlines (max 50 chars). Fallback truncates title at word boundary if AI fails.

**2. Impact derivation:** Computed server-side based on category. Frontend receives ready-to-use `impact` field.

**3. Update frequency:** RSS fetching is batch every 15 minutes. GCS exports can be triggered independently.

**4. Tonight summary endpoint:** Implemented at `/player-news/tonight-summary.json`. Returns lightweight `{player_lookup, has_critical_news, news_count}` for all players.

**5. Timeline:** GCS exporter is LIVE as of 2026-01-09. Endpoints are accessible now.

---

## Sample Data (Current)

### Articles by Category
| Category | Count |
|----------|-------|
| trade | 30 |
| signing | 21 |
| other | 19 |
| preview | 11 |
| injury | 10 |
| lineup | 4 |
| performance | 4 |
| recap | 1 |

### Top Players by Article Count
| Player | Articles |
|--------|----------|
| traeyoung | 13 |
| anthonydavis | 3 |
| giannisantetokounmpo | 2 |
| cooperflagg | 2 |
| lebronjames | 1 |

---

## Integration Checklist

- [ ] Query player news using `player_lookup` from player registry
- [ ] Display `ai_summary` when available, fall back to `summary`
- [ ] Color-code by `article_category`
- [ ] Show relative time (e.g., "2 hours ago")
- [ ] Link to `source_url` for full article
- [ ] Filter by category if needed (injury-only view)
- [ ] Handle null `ai_summary` gracefully

---

## Related Documentation

- [Scrapers Reference](../06-reference/scrapers.md) - News RSS section
- [News Project Docs](../08-projects/current/news-ai-analysis/README.md) - Full implementation details
- [Frontend API Reference](./FRONTEND_API_REFERENCE.md) - Other API endpoints
