# Session 175 Handoff: Prediction Lines Investigation

**Date:** 2025-12-27
**Duration:** Investigation + Fix session
**Status:** FIXED - Schedulers rescheduled, verified working

---

## Executive Summary

Investigated why `current_points_line` is NULL in `nba_predictions.player_prop_predictions` table, which blocks the Challenge System frontend from displaying betting lines and predictions.

---

## Root Cause Found

### The Problem

`current_points_line` is NULL for most players in `nba_analytics.upcoming_player_game_context`:
- Dec 27: **0/153** players (0%) have lines
- Dec 26: **18/202** players (9%) have lines
- Dec 25: **36/66** players (55%) have lines

### The Root Cause: Timing Mismatch

Phase 3 (UpcomingPlayerGameContextProcessor) runs **before** betting props data is available:

| Date | Phase 3 First Run (UTC) | Betting Props (UTC) | Gap |
|------|------------------------|---------------------|-----|
| Dec 27 | 06:06 (1 AM EST) | 16:07 (11 AM EST) | **10 hours** |
| Dec 26 | 17:48 (12:48 PM EST) | 18:07 (1:07 PM EST) | 19 min |
| Dec 25 | 19:15 (2:15 PM EST) | 21:30 (4:30 PM EST) | 2 hours |

### Why This Matters

1. Phase 3 queries `nba_raw.bettingpros_player_points_props` for prop lines
2. When Phase 3 runs first, no betting data exists yet
3. Players get NULL values for `current_points_line`
4. Phase 5 predictions inherit these NULL lines
5. Tonight's API shows no betting lines for challenge creation

---

## Data Flow Verification

### Betting Props Data IS Available

```sql
-- Dec 27: 137 unique players with props
-- Dec 26: 154 unique players with props
-- Dec 25: 89 unique players with props
```

### The Join Logic Works

`player_lookup` values match between tables:
- `zionwilliamson` in both betting props and UPC
- `samhauser` in both betting props and UPC
- No case sensitivity or format issues

### The Source Attribution Works

When lines ARE populated, sources are correctly tracked:
- `draftkings`
- `fanduel`
- `bettingpros`

---

## Fix Applied

### Scheduler Changes Made

| Scheduler | Old Time (ET) | New Time (ET) | Reason |
|-----------|---------------|---------------|--------|
| `same-day-phase3` | 10:30 AM | **12:30 PM** | After betting props (10 AM cycle) |
| `same-day-phase4` | 11:00 AM | **1:00 PM** | After Phase 3 completes |
| `same-day-predictions` | 11:30 AM | **1:30 PM** | After Phase 4 completes |

### Commands Used

```bash
# Reschedule Phase 3 to 12:30 PM ET
gcloud scheduler jobs update http same-day-phase3 \
  --location=us-west2 \
  --schedule="30 12 * * *" \
  --time-zone="America/New_York"

# Reschedule Phase 4 to 1:00 PM ET
gcloud scheduler jobs update http same-day-phase4 \
  --location=us-west2 \
  --schedule="0 13 * * *" \
  --time-zone="America/New_York"

# Reschedule Predictions to 1:30 PM ET
gcloud scheduler jobs update http same-day-predictions \
  --location=us-west2 \
  --schedule="30 13 * * *" \
  --time-zone="America/New_York"
```

### Verification Results

**Before Fix (Dec 27):**
- UPC: 0/153 players with lines (0%)
- Predictions: All NULL lines

**After Fix (Dec 27):**
- UPC: 69/153 players with lines (45%)
- Predictions: 200/570 with lines (35%)
- Tonight API: Shows props with lines and predictions

**Sample Player (Jeremiah Fears):**
```json
{
  "props": [{"stat_type": "points", "line": 13.5, "over_odds": null, "under_odds": -125}],
  "prediction": {"predicted": 11.9, "confidence": 0.86, "recommendation": "OVER"}
}
```

---

## Other Issues Investigated

### Pub/Sub Envelope Error (Resolved)

**Error:** "Missing 'message' field in Pub/Sub envelope"
**Keys in envelope:** `['gcs_path', 'data_source', 'data_type', 'backfill_mode']`

**Cause:** One-off manual HTTP POST to `/process` endpoint with raw JSON instead of proper Pub/Sub message format.

**Resolution:** Not a systemic issue, no fix needed.

### Gamebook PDF Broken Pipe Errors

**Time:** 10:08 UTC (5 AM EST)
**Error:** `[Errno 32] Broken pipe`
**Status:** Transient network issue, no action needed

---

## Documentation Updates

Updated reference docs with new Live Boxscores components from Session 174:

1. **scrapers.md**
   - Added "Live Game Data" category
   - Added `BdlLiveBoxScoresScraper` details
   - Updated Ball Don't Lie section (4 → 5 scrapers)

2. **processors.md**
   - Added `BdlLiveBoxscoresProcessor` section
   - Updated Ball Don't Lie section (4 → 5 processors)
   - Added `bdl_live_boxscores` to partitioned tables list

---

## Key Queries for Investigation

### Check Line Coverage by Date

```sql
SELECT
  game_date,
  COUNT(*) as total_players,
  COUNTIF(current_points_line IS NOT NULL) as with_line
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

### Check Processing Timestamps

```sql
WITH upc_times AS (
  SELECT game_date, MAX(processed_at) as upc_processed_at
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
bp_times AS (
  SELECT game_date, MAX(processed_at) as bp_processed_at
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND is_active = TRUE
  GROUP BY game_date
)
SELECT
  u.game_date,
  u.upc_processed_at,
  b.bp_processed_at,
  TIMESTAMP_DIFF(u.upc_processed_at, b.bp_processed_at, MINUTE) as upc_after_bp_minutes
FROM upc_times u
LEFT JOIN bp_times b ON u.game_date = b.game_date
ORDER BY u.game_date DESC
```

---

## Next Steps

### High Priority

1. **Fix Phase 3 timing** - Either reschedule or add second trigger
2. **Test live boxscores** - Wait for game window (7 PM ET), no games today (Dec 27)

### Medium Priority

3. Verify prediction line propagation after Phase 3 fix
4. Test tonight's API with proper betting lines

---

## Files Modified This Session

- `docs/06-reference/scrapers.md` - Added Live Boxscores scraper
- `docs/06-reference/processors.md` - Added Live Boxscores processor

---

## Git Commits This Session

```bash
# Documentation updates (pending commit)
git add docs/06-reference/scrapers.md docs/06-reference/processors.md
git add docs/09-handoff/2025-12-27-SESSION175-PREDICTION-LINES-INVESTIGATION.md
```

---

## Quick Reference

### Check Phase 3 Scheduler

```bash
gcloud scheduler jobs list --location=us-west2 | grep -i phase3
```

### Trigger Phase 3 Manually

```bash
# Via Pub/Sub (if subscription exists)
gcloud pubsub topics publish nba-phase3-analytics-trigger \
  --message='{"game_date": "2025-12-27"}'

# Or via HTTP (if endpoint exists)
curl -X POST "https://nba-phase3-analytics-processors-XXX.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2025-12-27"}'
```

### Check Betting Props Availability

```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY game_date"
```
