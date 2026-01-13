# Issue: BettingPros API Errors

**Priority:** P3
**Status:** RESOLVED
**Created:** January 12, 2026 (Session 23)
**Resolved:** January 12, 2026 (Session 25)

---

## Resolution Summary

**Root Cause:** BettingPros API (via CloudFront CDN) was returning Brotli-compressed responses, but the `brotli` Python package was not installed. The `requests` library couldn't auto-decompress these responses, resulting in binary data being passed to JSON decode, which failed.

**Fix Applied:**
1. Added `brotli>=1.1.0` to `scrapers/requirements.txt`
2. Added automatic Brotli detection and decompression in `scrapers/scraper_base.py:decode_download_content()`
3. Updated header documentation in `scrapers/utils/nba_header_utils.py`

**Verification:**
- `bp_events` scraper: Successfully fetched 6 events for Jan 12
- `bp_player_props` scraper: Successfully fetched 94 props for 94 players

**Deployment Required:** Yes - Cloud Run needs to be redeployed to pick up the new `brotli` dependency.

---

## Problem Statement

BettingPros scrapers were failing with:
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

## Root Cause Analysis

The byte `0x85` at position 1 is characteristic of Brotli-compressed data. Investigation revealed:

1. **API Response:** BettingPros API returns valid JSON compressed with gzip or Brotli
2. **CDN Behavior:** CloudFront CDN sometimes serves cached Brotli responses even when `Accept-Encoding: br` is not in the request
3. **Missing Dependency:** The `brotli` Python package was not installed
4. **Requests Behavior:** Without `brotli`, the requests library cannot auto-decompress Brotli content
5. **Result:** Raw compressed bytes were passed to `json.loads()`, causing decode failures

Timeline of events:
- **Jan 10:** Original fix removed `br` from Accept-Encoding (commit 3f21072)
- **Jan 12:** Errors continued because CDN was still serving cached Brotli responses
- **Jan 12 (Session 25):** Root cause identified and proper fix applied

---

## Changes Made

### 1. scrapers/requirements.txt
```diff
+ # Compression handling (needed for Brotli responses from some APIs)
+ brotli>=1.1.0
```

### 2. scrapers/scraper_base.py (decode_download_content)
```python
# Added Brotli detection after gzip handling
elif content and content[0:1] not in (b'{', b'[', b'"', b' ', b'\n', b'\t'):
    try:
        import brotli
        decompressed = brotli.decompress(content)
        content = decompressed
        logger.info("Manually decompressed brotli response")
    except ImportError:
        logger.warning("Brotli package not installed")
    except Exception as e:
        logger.debug("Brotli decompression not applicable: %s", e)
```

### 3. scrapers/utils/nba_header_utils.py
Updated docstring to reflect that brotli is now installed and fallback exists.

---

## Verification Results

### bp_events Test
```
INFO:scraper_base:Validation passed: 6 events found for 2026-01-12
INFO:scraper_base:Processed 6 events for 2026-01-12: UTH@CLE, PHI@TOR, BOS@IND, BKN@DAL, LAL@SAC...
```

### bp_player_props Test
```
INFO:scraper_base:Completed pagination: 94 total offers from 9 pages
INFO:scraper_base:Validation passed: 94 total offers found
INFO:scraper_base:Processed 94 props for 94 players
```

---

## Deployment Instructions

To deploy the fix to Cloud Run:

```bash
# Deploy scrapers service
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Verify deployment
gcloud run services describe nba-scrapers --region us-west2 --format='value(status.latestReadyRevisionName)'
```

---

## Prevention

This fix provides defense in depth:
1. **Primary:** `brotli` package enables automatic Brotli decompression by requests library
2. **Fallback:** Manual detection and decompression in `decode_download_content()`
3. **Header Strategy:** Keep `Accept-Encoding: gzip, deflate` (no br) to prefer simpler compression, but handle Brotli if CDN serves it anyway

---

## Success Criteria (Verified)

1. ✅ `BettingProsEvents` scraper completes successfully
2. ⏳ GCS files appear in `bettingpros/events/{date}/` (pending deployment)
3. ✅ `BettingProsPlayerProps` can fetch event IDs
4. ✅ No JSON decode errors in local tests

---

## Related Files

| File | Change |
|------|--------|
| `scrapers/requirements.txt` | Added brotli>=1.1.0 |
| `scrapers/scraper_base.py:1723-1740` | Added Brotli detection/decompression |
| `scrapers/utils/nba_header_utils.py:129-138` | Updated docstring |
