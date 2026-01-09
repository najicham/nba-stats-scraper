# News Pipeline Fixes - Session Handoff

**Date:** 2026-01-09
**Session:** Afternoon/Evening
**Status:** Complete
**Focus:** BigQuery streaming buffer fix + JSON parsing fix

---

## Executive Summary

This session fixed two issues in the news-fetcher Cloud Function:

1. **BigQuery streaming buffer error** - AI summaries weren't being saved because UPDATE queries were blocked by the streaming buffer
2. **JSON parsing issue** - Raw JSON was being stored in summary fields when parsing failed

Both fixes are deployed and verified working.

---

## Issue 1: Streaming Buffer Fix

### Problem

Cloud Function logs showed:
```
UPDATE or DELETE statement over table nba_analytics.news_insights
would affect rows in the streaming buffer, which is not supported
```

The pipeline was:
1. Insert insights to BigQuery (streaming insert)
2. Generate AI summaries
3. UPDATE insights with summaries → **BLOCKED** (rows in streaming buffer)

### Solution

Reordered pipeline to generate summaries BEFORE inserting:
1. Extract keywords/categories
2. Generate AI summaries
3. Insert insights WITH summaries (single insert, no UPDATE)

### Files Changed

| File | Change |
|------|--------|
| `scrapers/news/storage.py` | `save_insights()` accepts optional `summaries` dict |
| `orchestration/cloud_functions/news_fetcher/main.py` | Reordered pipeline |

### Commit

`8b051e7` - fix(news): Avoid BigQuery streaming buffer issue in AI summarization

---

## Issue 2: JSON Parsing Fix

### Problem

Some articles had raw JSON stored as summaries:
```
summary_preview: {"headline": "Grizzlies Reportedly Open to Trade...
```

The `_parse_response()` method was falling back to raw content when JSON parsing failed.

### Solution

Added robust `_extract_json()` method that:
- Handles markdown code blocks (```json)
- Uses brace matching to find JSON in mixed content
- Falls back to "Summary unavailable" instead of raw JSON
- Logs warnings when parsing fails

### File Changed

`scrapers/news/ai_summarizer.py` - New `_extract_json()` method, improved `_parse_response()`

### Commit

`fadfb30` - fix(news): Improve JSON parsing robustness in AI summarizer

---

## Verification Results

### After Streaming Buffer Fix

```
INFO:main:Generated 1 AI summaries (cost: $0.0002)
INFO:main:Saved 1 insights
INFO:main:News fetch completed in 12.47s: 1 new articles
```

No streaming buffer errors - status 200.

### After JSON Parsing Fix

| Metric | Before | After |
|--------|--------|-------|
| Raw JSON in summary | Yes | **0** |
| Proper summaries | ~35% | 80% |

---

## Documentation Updates

### Added

1. **News Pipeline Validation** section in `docs/02-operations/daily-validation-checklist.md`
   - Health check commands
   - BigQuery verification queries
   - Red flags table
   - Manual trigger commands

2. **Future Improvements** doc at `docs/08-projects/current/news-ai-analysis/FUTURE-IMPROVEMENTS.md`
   - High priority: MLB registry, metrics dashboard, alerting
   - Medium priority: Additional sources, real-time alerts, ML features
   - Low priority: Player linking accuracy, deduplication

### Commits

- `9da0797` - docs(ops): Add news pipeline validation to daily checklist
- `50eb416` - docs(news): Add future improvements backlog

---

## Cloud Function Status

- **Name:** `news-fetcher`
- **Region:** us-west2
- **Version:** 10
- **Schedule:** Every 15 minutes (`*/15 * * * *`)
- **Last Deployed:** 2026-01-09 19:21 UTC

---

## Verification Queries

### Check AI Summaries Are Being Saved

```sql
SELECT
  article_id,
  category,
  SUBSTR(ai_summary, 1, 50) as summary_preview,
  headline,
  ai_summary_generated_at IS NOT NULL as has_timestamp
FROM `nba-props-platform.nba_analytics.news_insights`
WHERE extracted_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
ORDER BY extracted_at DESC
LIMIT 10
```

### Check for Raw JSON (Should Be 0)

```sql
SELECT COUNT(*) as raw_json_count
FROM `nba-props-platform.nba_analytics.news_insights`
WHERE ai_summary LIKE '{%'
  AND extracted_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
```

---

## Known Issues / Future Work

### MLB Player Registry Missing

Cloud Function logs show:
```
WARNING: MLB registry reader not available, using NBA reader
```

MLB articles can't be linked to players. Need to create MLB player registry before MLB season (late March).

### ~20% Articles Missing Summaries

Some articles still have NULL summaries due to:
- AI API failures
- Edge cases in response format
- `max_articles` limit (default 50)

This is acceptable - the main fix (no raw JSON) is working.

---

## Files Modified This Session

```
scrapers/news/storage.py                              # save_insights() with summaries param
scrapers/news/ai_summarizer.py                        # _extract_json(), improved parsing
orchestration/cloud_functions/news_fetcher/main.py    # Reordered pipeline
docs/02-operations/daily-validation-checklist.md      # News validation section
docs/08-projects/current/news-ai-analysis/FUTURE-IMPROVEMENTS.md  # New file
docs/08-projects/current/news-ai-analysis/README.md   # Updated references
```

---

## Git Log

```
fadfb30 fix(news): Improve JSON parsing robustness in AI summarizer
50eb416 docs(news): Add future improvements backlog
9da0797 docs(ops): Add news pipeline validation to daily checklist
8b051e7 fix(news): Avoid BigQuery streaming buffer issue in AI summarization
```

---

## Next Steps (Optional)

1. **Monitor** - Check BigQuery over next 24 hours to confirm sustained fix
2. **MLB Registry** - Create before MLB season starts
3. **Alerting** - Set up Cloud Monitoring alerts for news pipeline failures
4. **Metrics Dashboard** - Add news metrics to admin dashboard

---

## Quick Reference

### Trigger News Fetch Manually
```bash
gcloud scheduler jobs run news-fetcher --project=nba-props-platform --location=us-west2
```

### Check Logs
```bash
gcloud functions logs read news-fetcher --project=nba-props-platform --region=us-west2 --limit=30
```

### Deploy Function
```bash
./bin/deploy/deploy_news_fetcher.sh --function-only
```
