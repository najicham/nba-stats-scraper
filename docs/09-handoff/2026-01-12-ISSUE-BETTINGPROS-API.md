# Issue: BettingPros API Errors

**Priority:** P3
**Status:** Investigation needed
**Created:** January 12, 2026 (Session 23)

---

## Problem Statement

BettingPros scrapers are failing with:
1. "No events found for date" errors
2. JSON decode errors (empty responses)
3. Encoding issues (UTF-8 decode failures)

---

## Error Details

### Error 1: No Events Found
```
scrapers.utils.exceptions.DownloadDataException: Failed to fetch events for date 2026-01-12: No events found for date: 2026-01-12
```

### Error 2: Empty JSON Response
```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

### Error 3: Encoding Issues
```
WARNING:scraper_base:UTF-8 decode failed for BettingProsEvents, trying latin-1: 'utf-8' codec can't decode byte 0x85 in position 1: invalid start byte
```

---

## Evidence

```bash
# Jan 11 has data (5 files)
gsutil ls "gs://nba-scraped-data/bettingpros/events/2026-01-11/"
# First file: 2026-01-11T14:05:19Z (9:05 AM ET)

# Jan 12 has NO data
gsutil ls "gs://nba-scraped-data/bettingpros/events/2026-01-12/"
# 0 files

# Error count (all on Jan 12)
gcloud logging read 'resource.type="cloud_run_revision" AND "bettingpros" AND "No events found"' --limit=50 | grep -c "Jan 12"
# 24 errors
```

---

## Affected Scrapers

| Scraper | File | Issue |
|---------|------|-------|
| `BettingProsEvents` | `scrapers/bettingpros/bp_events.py` | Empty/binary responses |
| `BettingProsPlayerProps` | `scrapers/bettingpros/bp_player_props.py` | Depends on events, fails cascade |

---

## Scraper Configuration

```python
# From bp_events.py
class BettingProsEvents(ScraperBase, ScraperFlaskMixin):
    header_profile = "bettingpros"  # Uses BettingPros headers
    proxy_enabled = True            # May need proxy for high volume
    download_type = DownloadType.JSON

# API endpoint
# https://api.bettingpros.com/v3/events?sport=NBA&date=YYYY-MM-DD
```

---

## Possible Causes

1. **API Rate Limiting** - BettingPros blocking requests
2. **Proxy Issues** - Proxy not working or blocked
3. **API Changes** - Endpoint or response format changed
4. **Timing Issue** - Data not available yet for game day
5. **Authentication** - Headers or API key issues

---

## Investigation Steps

### 1. Test API Directly
```bash
# Test from local machine
curl -v "https://api.bettingpros.com/v3/events?sport=NBA&date=2026-01-13"

# Check response headers and content
```

### 2. Check Proxy Status
```bash
# Review proxy configuration
grep -r "proxy" scrapers/bettingpros/

# Check if proxy service is healthy
```

### 3. Compare Headers
```bash
# Check header profile
cat shared/utils/nba_header_utils.py | grep -A20 "bettingpros"
```

### 4. Check Recent Changes
```bash
# Any recent changes to BettingPros scrapers?
git log --oneline -10 -- scrapers/bettingpros/
```

### 5. Check Cloud Logs for More Context
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND "bettingpros"' --limit=50 --format='table(timestamp,textPayload)'
```

---

## Key Files

| File | Purpose |
|------|---------|
| `scrapers/bettingpros/bp_events.py` | Events scraper |
| `scrapers/bettingpros/bp_player_props.py` | Player props scraper |
| `shared/utils/nba_header_utils.py` | Header profiles |
| `scrapers/scraper_base.py:1713` | JSON decode logic |

---

## Impact Assessment

- **Data loss:** BettingPros odds/props data
- **Alternative sources:** Odds API is primary source (working)
- **Analytics impact:** Minimal - BettingPros is secondary/comparison source
- **Urgency:** P3 - system functions without this data

---

## Potential Fixes

### If Rate Limited
- Add exponential backoff
- Reduce scrape frequency
- Rotate proxy IPs

### If API Changed
- Update endpoint URL
- Modify response parsing
- Update headers

### If Proxy Issue
- Check proxy service health
- Test without proxy locally
- Consider alternative proxy

---

## Success Criteria

1. `BettingProsEvents` scraper completes successfully
2. GCS files appear in `bettingpros/events/{date}/`
3. `BettingProsPlayerProps` can fetch event IDs
4. No JSON decode errors in logs
