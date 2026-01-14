# Session 25 Handoff - BettingPros Brotli Fix

**Date:** January 12, 2026 (4:30 PM PT)
**Duration:** ~45 minutes
**Focus:** BettingPros API scraper failures - Brotli compression fix
**Status:** RESOLVED and DEPLOYED

---

## Quick Start for Next Session

```bash
# 1. Verify BettingPros scrapers are working in Cloud Run
gcloud logging read 'resource.type="cloud_run_revision" AND "BettingProsEvents" AND "success"' --limit=5 --format='table(timestamp,textPayload)'

# 2. Check if GCS files appear after scheduled runs
gsutil ls "gs://nba-scraped-data/bettingpros/events/2026-01-13/"

# 3. Test locally if needed
python scrapers/bettingpros/bp_events.py --date 2026-01-13 --group dev
python scrapers/bettingpros/bp_player_props.py --date 2026-01-13 --market_type points --group dev

# 4. Quick health check
./bin/orchestration/quick_health_check.sh
```

---

## What Was Fixed

### Problem
BettingPros scrapers were failing with:
- "No events found for date" errors
- JSON decode errors (empty responses)
- UTF-8 decode failures: `byte 0x85 in position 1: invalid start byte`

### Root Cause
BettingPros API (via CloudFront CDN) was returning **Brotli-compressed responses**, but the `brotli` Python package wasn't installed. The `requests` library couldn't auto-decompress, so raw binary data was passed to `json.loads()`.

### Solution
1. Added `brotli>=1.1.0` to `scrapers/requirements.txt`
2. Added Brotli detection and manual decompression fallback in `scraper_base.py`
3. Deployed to Cloud Run

---

## Files Changed

| File | Change |
|------|--------|
| `scrapers/requirements.txt` | Added `brotli>=1.1.0` |
| `scrapers/scraper_base.py:1723-1740` | Added Brotli detection/decompression |
| `scrapers/utils/nba_header_utils.py:129-138` | Updated docstring |
| `docs/09-handoff/2026-01-12-ISSUE-BETTINGPROS-API.md` | Full resolution details |

---

## Code Change Details

### scrapers/requirements.txt
```diff
+ # Compression handling (needed for Brotli responses from some APIs)
+ brotli>=1.1.0
```

### scrapers/scraper_base.py (decode_download_content)
Added after gzip handling (line 1722):
```python
# Check if response is brotli-compressed but wasn't auto-decompressed
elif content and content[0:1] not in (b'{', b'[', b'"', b' ', b'\n', b'\t'):
    try:
        import brotli
        decompressed = brotli.decompress(content)
        content = decompressed
        logger.info("Manually decompressed brotli response (%d -> %d bytes)",
                   len(self.raw_response.content), len(content))
    except ImportError:
        logger.warning("Brotli package not installed")
    except Exception as e:
        logger.debug("Brotli decompression not applicable: %s", e)
```

---

## Deployment Info

| Item | Value |
|------|-------|
| Service | nba-phase1-scrapers |
| Region | us-west2 |
| Revision | nba-phase1-scrapers-00099-rxw |
| Git Commit | bb1aa77 |
| Deploy Time | 2026-01-12 16:25 PT |
| Duration | 9m 50s |

---

## Verification Results

### Local Testing (Pre-deployment)
```
bp_events: 6 events for Jan 12
bp_player_props: 94 props for 94 players
```

### Post-Deployment
- Cloud Run deployment successful
- Commit SHA verified: bb1aa77
- Service URL: https://nba-phase1-scrapers-756957797294.us-west2.run.app

---

## Monitoring Commands

```bash
# Check Cloud Run logs for BettingPros
gcloud logging read 'resource.type="cloud_run_revision" AND "bettingpros"' --limit=20 --format='table(timestamp,textPayload)'

# Watch for Brotli decompression logs
gcloud logging read 'resource.type="cloud_run_revision" AND "decompressed brotli"' --limit=10

# Check for any remaining decode errors
gcloud logging read 'resource.type="cloud_run_revision" AND "decode failed"' --limit=10

# Verify GCS data
gsutil ls "gs://nba-scraped-data/bettingpros/events/2026-01-13/"
gsutil ls "gs://nba-scraped-data/bettingpros/player_props/2026-01-13/"
```

---

## Outstanding Issues (From Previous Sessions)

### P2: BDL West Coast Game Gap
- **Issue:** BigDataBall box scores miss late West Coast games (10+ PM ET)
- **Status:** Fix implemented (3 options in workflow), needs monitoring
- **Details:** `docs/09-handoff/2026-01-12-ISSUE-BDL-WEST-COAST-GAP.md`

### P3: Historical Backfill Audit
- **Issue:** Some gaps in historical data
- **Status:** Audit complete, remediation in progress
- **Details:** `docs/08-projects/current/historical-backfill-audit/`

---

## Architecture Reference

### BettingPros Scraper Flow
```
bp_player_props.py (entry point)
    |-- _fetch_event_ids_from_date()
           |-- bp_events.py
                  |-- GET /v3/events?sport=NBA&date=YYYY-MM-DD
                  |-- Returns event IDs
    |-- GET /v3/offers (paginated, up to 50 pages)
           |-- Uses event IDs from above
           |-- Returns player props data
```

### Response Decompression Flow (scraper_base.py)
```
HTTP Response received
    |-- requests library checks Content-Encoding
    |     |-- gzip: auto-decompressed
    |     |-- br: auto-decompressed (if brotli installed)
    |
    |-- decode_download_content() fallbacks:
          |-- Check gzip magic (0x1f 0x8b): manual gzip decompress
          |-- Check non-JSON start: try brotli decompress
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `scrapers/bettingpros/bp_events.py` | Events scraper (event IDs) |
| `scrapers/bettingpros/bp_player_props.py` | Player props scraper |
| `scrapers/scraper_base.py:1700-1780` | Response decoding logic |
| `scrapers/utils/nba_header_utils.py:129-155` | BettingPros headers |
| `scrapers/utils/proxy_utils.py` | Proxy configuration |

---

## Session Timeline

1. **Investigation** - Read handoff doc, explored codebase with agents
2. **API Testing** - Confirmed API works (returns gzip-compressed JSON)
3. **Proxy Testing** - Confirmed proxy passes headers correctly
4. **Log Analysis** - Found 0x82 and 0x85 bytes indicating Brotli
5. **Root Cause** - Identified missing brotli package
6. **Fix Implementation** - Added brotli to requirements + fallback code
7. **Local Testing** - Verified both scrapers work
8. **Deployment** - Deployed to Cloud Run (revision 00099-rxw)
9. **Documentation** - Updated issue doc and created this handoff

---

## Notes for Next Session

- The fix provides **defense in depth**: both automatic decompression via requests library AND manual fallback in decode_download_content()
- BettingPros is a **secondary data source** (P3 priority) - OddsAPI is primary
- If issues persist, check CloudFront cache headers and consider adding `Cache-Control: no-cache` to requests
