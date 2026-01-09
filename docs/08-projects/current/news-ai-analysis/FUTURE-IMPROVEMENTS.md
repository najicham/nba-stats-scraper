# News & AI Analysis - Future Improvements

**Created:** 2026-01-09
**Status:** Backlog
**Last Updated:** 2026-01-09

---

## Overview

This document tracks potential improvements for the News & AI Analysis feature. Items are organized by priority and estimated effort.

---

## High Priority

### 1. MLB Player Registry

**Status:** Not Started
**Effort:** 2-4 hours
**Blocking:** MLB news player linking

**Problem:**
Cloud Function logs show: `WARNING: MLB registry reader not available, using NBA reader`

MLB articles are being fetched but cannot be linked to players because there's no MLB player registry. The `tonight-summary.json` for MLB shows 0 players.

**Solution:**
- Create MLB player registry similar to NBA
- Populate with active MLB rosters
- Update `PlayerLinker` to use sport-specific registry

**When Needed:** Before MLB season starts (late March)

---

### 2. News Metrics Dashboard

**Status:** Not Started
**Effort:** 2-3 hours
**Value:** Operational visibility

**Current Gap:**
No centralized view of news pipeline health. Must check Cloud Function logs manually.

**Proposed Metrics:**
- Articles fetched per day (by source, sport)
- AI summary success rate
- Player link rate (articles with at least one player linked)
- AI cost tracking (daily/monthly)
- GCS export freshness

**Implementation Options:**
1. BigQuery scheduled query → dashboard view
2. Add to existing admin dashboard
3. Cloud Monitoring custom metrics

---

### 3. Automated Alerting

**Status:** Not Started
**Effort:** 1-2 hours
**Value:** Proactive issue detection

**Alert Conditions:**
| Condition | Threshold | Channel |
|-----------|-----------|---------|
| News fetch failures | 3 consecutive | Slack/email |
| AI summary rate drop | < 80% for 1 hour | Slack/email |
| GCS export stale | > 30 min | Slack/email |
| Anthropic API errors | Any | Slack/email |

**Implementation:**
- Cloud Monitoring alerting policies
- Or Cloud Function error → Pub/Sub → alert handler

---

## Medium Priority

### 4. Additional News Sources

**Status:** Not Started
**Effort:** 30 min - 2 hours per source

| Source | Type | Effort | Notes |
|--------|------|--------|-------|
| The Athletic | RSS (if available) | 30 min | Premium content, may require auth |
| Yahoo Sports | RSS | 30 min | Already implemented, just disabled |
| Bleacher Report | RSS/Scrape | 1-2 hr | May need scraping |
| Team-specific feeds | RSS | 2 hr | 30 NBA + 30 MLB team feeds |
| Twitter/X | API | 4+ hr | Rate limits, API costs |

**Note:** RotoWire RSS feeds were discontinued in January 2026.

---

### 5. Real-time Injury Alerts via Pub/Sub

**Status:** Not Started
**Effort:** 2-3 hours
**Value:** Time-sensitive injury news for bettors

**Flow:**
```
News Fetch → Detect injury category → Pub/Sub topic →
  → Push notification service
  → Slack/Discord webhook
  → Frontend real-time update
```

**Implementation:**
1. Add Pub/Sub publish in Cloud Function for high-impact news
2. Create subscriber for each notification channel
3. Add `injury_alert_sent` flag to avoid duplicates

---

### 6. Batch Loading for All News Tables

**Status:** Partial
**Effort:** 2-3 hours
**Value:** Data consistency, avoid streaming buffer issues

**Current State:**
All three news storage classes use streaming inserts (`insert_rows_json`):
- `NewsStorage.save_articles()`
- `NewsInsightsStorage.save_insights()`
- `NewsPlayerLinksStorage.save_links()`

**Issue:**
Streaming inserts create 90-minute window where UPDATE/DELETE operations are blocked. We fixed the AI summary issue (commit `8b051e7`) but other UPDATE operations could still hit this.

**Solution:**
Migrate to batch loading (`load_table_from_json`) per BigQuery best practices doc.

**Trade-off:** Slightly higher latency (2-5 seconds vs immediate), but no streaming buffer restrictions.

---

### 7. News Impact Scoring for ML

**Status:** Not Started
**Effort:** 4-6 hours
**Value:** Improve prediction accuracy

**Concept:**
Create ML features from news data:
- `has_injury_news_24h` - Boolean
- `injury_severity_score` - 0-1 based on keywords
- `trade_news_recency` - Days since trade news
- `news_sentiment_score` - AI-derived sentiment

**Integration:**
- Add to Phase 4 ML feature store
- Include in prediction models

---

## Low Priority

### 8. Improve Player Linking Accuracy

**Status:** Not Started
**Effort:** 4-6 hours
**Current Accuracy:** ~80% (estimated)

**Issues:**
- Partial name matches (e.g., "James" could be LeBron or others)
- Nicknames not in registry
- Players with similar names

**Solutions:**
- Use AI (Claude) for ambiguous cases
- Add nickname mapping to registry
- Use article context (team mentions) to disambiguate

---

### 9. News Deduplication Improvements

**Status:** Not Started
**Effort:** 2-3 hours

**Current:**
Content hash-based deduplication (title + summary)

**Issues:**
- Same story from multiple sources not deduplicated
- Slightly different headlines for same news

**Solutions:**
- Semantic similarity check (embeddings)
- Link related articles as "same story"
- Primary/secondary source designation

---

### 10. Historical News Backfill

**Status:** Not Started
**Effort:** Variable

**Value:**
Historical news for ML training, trend analysis

**Challenges:**
- RSS only has recent articles (~50-100)
- Would need web scraping or API access
- Storage costs for historical data

---

### 11. `ai_processed` Flag Cleanup

**Status:** Low Priority
**Effort:** 1 hour

**Background:**
The `ai_processed` and `ai_processed_at` fields in `news_articles_raw` are no longer being updated (removed in streaming buffer fix). They remain FALSE for new articles.

**Options:**
1. **Do nothing** - Field is redundant (can check `ai_summary IS NOT NULL` in `news_insights`)
2. **Remove fields** - Schema migration to drop unused columns
3. **Add to initial insert** - Set `ai_processed=TRUE` in `save_articles()` if summaries will be generated

**Recommendation:** Option 1 (do nothing) - the fields aren't used anywhere critical.

---

## Completed Improvements

| Item | Completed | Notes |
|------|-----------|-------|
| Fix streaming buffer issue | 2026-01-09 | Commit `8b051e7` |
| Add validation to daily checklist | 2026-01-09 | Commit `9da0797` |
| Phase 6 NewsExporter | 2026-01-09 | GCS export working |
| Yahoo Sports RSS | 2026-01-09 | Enabled |
| Sport-specific GCS paths | 2026-01-09 | `/player-news/{sport}/` |
| AI headline generation | 2026-01-09 | Max 50 chars |

---

## Effort Estimates Key

| Effort | Time |
|--------|------|
| 30 min | Quick fix, config change |
| 1-2 hr | Small feature, single file |
| 2-4 hr | Medium feature, multiple files |
| 4-6 hr | Larger feature, testing needed |
| 1+ day | Major feature, design needed |

---

## Related Documentation

- [README.md](./README.md) - Project overview
- [DATA-SOURCES-PLAN.md](./DATA-SOURCES-PLAN.md) - Source planning
- [NEWS_API_REFERENCE.md](../../api/NEWS_API_REFERENCE.md) - API docs
- [Daily Validation Checklist](../../02-operations/daily-validation-checklist.md) - News validation section
- [BigQuery Best Practices](../../05-development/guides/bigquery-best-practices.md) - Streaming buffer guidance
