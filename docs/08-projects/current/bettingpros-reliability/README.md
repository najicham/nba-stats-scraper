# BettingPros Player Props Reliability

**Status:** IMPLEMENTED - PENDING DEPLOYMENT
**Priority:** P1
**Created:** January 13, 2026 (Session 27)

---

## Problem Summary

The `bp_player_props` scraper fails intermittently due to:
1. Proxy timeouts (502 Bad Gateway, read timeouts)
2. API rate limiting during pagination
3. No automatic retry mechanism for the scheduled betting_lines workflow

When the scraper fails, **no player props are collected for that game date**, which impacts prediction generation.

---

## Incident: January 12, 2026

### Timeline

| Time (ET) | Event |
|-----------|-------|
| 1:06 PM | betting_lines workflow triggered bp_player_props - **FAILED** |
| 4:06 PM | betting_lines workflow triggered bp_player_props - **FAILED** |
| 7:06 PM | betting_lines workflow triggered bp_player_props - **FAILED** (3 retries exhausted) |
| 8:17 PM | Manual re-run via Session 27 - **SUCCESS** (97 points props) |
| 8:19 PM | Manual re-run for rebounds, assists, threes - **SUCCESS** |
| 8:20 PM | Manual re-run for steals, blocks - **SUCCESS** |

### Root Cause

```
DownloadDataException: No events found for date: 2026-01-12
```

The player props scraper calls `BettingProsEvents` internally to get event IDs. When this internal call fails (due to proxy issues), the entire scraper fails.

**Contributing factors:**
1. Proxy instability (502 Bad Gateway, read timeouts observed)
2. 20-second HTTP timeout too short for slow proxy responses
3. No retry logic around the internal events fetch
4. No automatic recovery for missing props

---

## Implemented Fixes (Session 27)

### Layer 1: Increase HTTP Timeout ✅

**File:** `scrapers/bettingpros/bp_player_props.py`

```python
# Before: inherited 20s from scraper_base
# After:
timeout_http = 45  # Handle slow proxy/API responses
```

### Layer 2: Add Retry with Exponential Backoff ✅

**File:** `scrapers/bettingpros/bp_player_props.py`

Added retry logic around `_fetch_event_ids_from_date()`:
- 3 retry attempts with exponential backoff (15s, 30s, 60s)
- Creates fresh scraper instance for each attempt
- Logs warnings on each failure
- Sends notification only after all retries exhausted

```python
EVENTS_FETCH_MAX_RETRIES = 3
EVENTS_FETCH_BACKOFF_BASE = 15  # seconds (15, 30, 60)
```

### Layer 3: Add Recovery Script ✅

**File:** `scripts/betting_props_recovery.py` (NEW)

Automated recovery script that:
1. Checks if games are scheduled for target date
2. Checks if BettingPros props exist (minimum 150 per game)
3. If props missing, triggers bp_player_props for all 6 market types
4. Sends notifications on recovery

**Usage:**
```bash
# Check and recover today's props
PYTHONPATH=. python scripts/betting_props_recovery.py

# Check specific date (dry run)
PYTHONPATH=. python scripts/betting_props_recovery.py --date 2026-01-12 --dry-run

# Schedule via Cloud Scheduler at 3 PM, 6 PM, 9 PM ET
```

### Layer 4: Add Monitoring Check ✅

**File:** `scripts/check_data_completeness.py`

Added BettingPros props check to daily completeness report:
- Counts props for each game date
- Compares against minimum expected (150 per game)
- Shows recovery command if props below threshold

---

## Files Changed

| File | Change |
|------|--------|
| `scrapers/bettingpros/bp_player_props.py` | Added timeout_http=45, retry logic with backoff |
| `scripts/betting_props_recovery.py` | NEW - Recovery script |
| `scripts/check_data_completeness.py` | Added BettingPros props check |

---

## Deployment Steps

1. **Deploy to Cloud Run:**
   ```bash
   gcloud run deploy nba-phase1-scrapers \
     --source . \
     --region us-west2 \
     --project nba-props-platform
   ```

2. **Verify deployment:**
   ```bash
   curl -s https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health | jq .status
   ```

3. **(Optional) Add recovery to Cloud Scheduler:**
   ```bash
   # Create job to run at 3 PM, 6 PM, 9 PM ET
   gcloud scheduler jobs create http betting-props-recovery-3pm \
     --schedule="0 15 * * *" \
     --time-zone="America/New_York" \
     --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/run-script" \
     --http-method=POST \
     --headers="Content-Type=application/json" \
     --message-body='{"script": "betting_props_recovery"}'
   ```

---

## Verification

After deployment, verify fixes work:

```bash
# Test scraper with new timeout and retry
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "bp_player_props", "date": "2026-01-13", "market_type": "points", "group": "prod"}'

# Check props in BigQuery
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as props
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date >= '2026-01-12' GROUP BY 1 ORDER BY 1"
```

---

## Monitoring Queries

```sql
-- Check BettingPros props for recent dates
SELECT
  game_date,
  COUNT(*) as props,
  COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1;

-- Check for missing props (should have ~10k+ per game day)
SELECT game_date, COUNT(*) as props
FROM `nba_raw.bettingpros_player_points_props`
WHERE game_date >= '2026-01-10'
GROUP BY 1
HAVING COUNT(*) < 5000;
```

---

## Related Issues

- [Session 25] BettingPros brotli fix - **RESOLVED** (revision 00099)
- [Session 26] ESPN roster reliability - **RESOLVED** (revision 00100)
- [Session 27] BettingPros retry/recovery - **IMPLEMENTED** (this issue)

---

*Last Updated: January 13, 2026 (Session 27)*
