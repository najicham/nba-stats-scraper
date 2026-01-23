# Session Handoff - January 23, 2026

## Executive Summary

This session fixed critical infrastructure issues (Odds API, Decodo proxy) and discovered that historical betting line backfills require using the **historical Odds API endpoints**.

---

## What Was Fixed This Session

### 1. Odds API Scraper - ✅ FIXED
**Problem**: `oddsa_events` scraper was failing with HTTP 500
**Root Cause**: `cleanup_processor.py` was querying non-existent table `nbac_player_list`
**Fix**: Removed the reference from cleanup_processor.py
**Commit**: Uncommitted - needs commit

### 2. Decodo Proxy - ✅ FIXED
**Problem**: Decodo proxy wasn't working in Cloud Run
**Root Cause**: `DECODO_PROXY_CREDENTIALS` was NOT mounted in deploy script
**Fix**:
- Added to `bin/scrapers/deploy/deploy_scrapers_simple.sh`
- Added to `nba-scrapers` service via `gcloud run services update`
**Verification**: Credentials confirmed correct: `spioed6ilb:~NqEanHhodVes6717q`

### 3. Grading Function - ✅ DEPLOYED
**Change**: Added `BETTINGPROS` as valid line_source (fallback when odds_api unavailable)
**File**: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

---

## Current Data Status

### Predictions by Date (Jan 19-22)

| Date | ACTUAL_PROP | Placeholder (20.0) | Status |
|------|-------------|-------------------|--------|
| Jan 19 | 285 | 0 | ✅ Good |
| Jan 20 | 432 | 0 | ✅ Good |
| Jan 21 | 262 | 865 (156 players) | ⚠️ Needs historical backfill |
| Jan 22 | 449 | 0 | ✅ Good |
| Jan 23 | Not run yet | - | Scheduled |

### Jan 21 Backfill Attempted But Incomplete
- Batch `batch_2026-01-21_1769176603` completed successfully
- Only updated 52 players who already had betting lines
- 156 players with placeholder lines were NOT processed
- **Reason**: No betting lines available in `upcoming_player_game_context` for historical dates

---

## How to Backfill Historical Betting Lines

### The Historical Odds API Scrapers

Located in `scrapers/oddsapi/`:
- `oddsa_events_his.py` - Get historical events list
- `oddsa_player_props_his.py` - Get historical player prop odds
- `oddsa_game_lines_his.py` - Get historical game lines

### Workflow to Backfill Jan 21 Betting Lines

```bash
# Step 1: Get event IDs for Jan 21 using historical events scraper
python -m scrapers.oddsapi.oddsa_events_his \
    --sport basketball_nba \
    --date 2026-01-21T04:00:00Z \
    --debug

# Step 2: For each event_id, get historical player props
# Use a timestamp BEFORE games started (04:00-18:00 UTC is safe)
python -m scrapers.oddsapi.oddsa_player_props_his \
    --event_id <EVENT_ID> \
    --game_date 2026-01-21 \
    --snapshot_timestamp 2026-01-21T18:00:00Z \
    --markets player_points \
    --debug
```

### Critical Timing Constraint
- Events disappear from API when games start
- Use snapshot_timestamp BEFORE game time
- NBA games typically start 23:00-02:00 UTC
- Safe windows: 04:00-18:00 UTC for most games

---

## Secrets Configuration

| Secret | Location | Status |
|--------|----------|--------|
| `ODDS_API_KEY` | Secret Manager | ✅ `6479e1937a40b5f11a222d3c9949a590` |
| `DECODO_PROXY_CREDENTIALS` | Secret Manager | ✅ `spioed6ilb:~NqEanHhodVes6717q` |
| `coordinator-api-key` | Secret Manager | ✅ Working |

---

## Services Deployed

| Service | Status | Notes |
|---------|--------|-------|
| `nba-phase1-scrapers` | ✅ Deployed | With Decodo secret |
| `nba-scrapers` | ✅ Deployed | With Decodo secret |
| `prediction-coordinator` | ✅ Running | |
| `prediction-worker` | ✅ Running | Max 10 instances × 5 concurrency |
| `phase5b-grading` | ✅ Deployed | Accepts BETTINGPROS line_source |

---

## Pending Tasks

### High Priority
1. **Backfill Jan 21 betting lines** using historical Odds API
2. **Run grading backfill** for Jan 17-22 after betting lines fixed
3. **Commit pending changes**:
   - `cleanup_processor.py` (removed nbac_player_list reference)
   - `deploy_scrapers_simple.sh` (added DECODO_PROXY_CREDENTIALS)

### Medium Priority
4. Investigate Jan 18 low analytics completeness (16.3%)
5. Decide on historical completeness backfill strategy (124k records with NULL)

### Low Priority
6. Backfill schedule data for 2021-2023 seasons (optional)
7. Archive remaining old handoff docs

---

## Key Commands

### Check Prediction Status
```bash
bq query --use_legacy_sql=false "
SELECT game_date, line_source, COUNT(*) as cnt,
       COUNTIF(current_points_line = 20.0) as placeholder
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-19'
GROUP BY 1, 2 ORDER BY 1, 2"
```

### Trigger Prediction Batch
```bash
COORD_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $COORD_KEY" \
  -d '{"game_date": "2026-01-21"}'
```

### Check Proxy Logs
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND textPayload=~"proxy"' --limit=20 --freshness=1h
```

### Test Odds API
```bash
curl -s "https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey=6479e1937a40b5f11a222d3c9949a590&regions=us&markets=h2h" | head -100
```

---

## Files Modified This Session

| File | Change | Committed |
|------|--------|-----------|
| `orchestration/cleanup_processor.py` | Removed nbac_player_list reference | ❌ |
| `bin/scrapers/deploy/deploy_scrapers_simple.sh` | Added DECODO_PROXY_CREDENTIALS | ❌ |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Added BETTINGPROS | Already committed |

---

## Architecture Notes

### Prediction Flow
1. `upcoming_player_game_context` (Phase 3) provides betting lines
2. `prediction-coordinator` starts batch, publishes to Pub/Sub
3. `prediction-worker` processes each player, writes to staging tables
4. Consolidation merges staging → `player_prop_predictions`

### Why Backfill Didn't Work for Placeholder Players
- Coordinator queries `upcoming_player_game_context` for betting lines
- Historical dates have no betting lines in this table
- Must use historical Odds API to fetch lines first
- Then either update `upcoming_player_game_context` or modify coordinator to use historical data

---

## Documentation Created

- `docs/09-handoff/2026-01-23-PREDICTION-CONSOLIDATION-BUG.md` - Analysis of backfill behavior
- `docs/09-handoff/2026-01-23-SESSION-HANDOFF.md` - This document

---

## Next Session Priorities

1. **Use historical Odds API** to fetch betting lines for Jan 21
2. **Populate the lines** into appropriate table or run predictions with historical data
3. **Commit the pending changes** to cleanup_processor.py and deploy script
4. **Run grading backfill** once predictions are fixed
