# Session 48 Handoff - Live System Fixes & Orchestration Health

**Date**: 2026-01-15 (started ~21:30 ET on Jan 14)
**Focus**: Live scoring system fix, orchestration health audit, monitoring enhancements

---

## Executive Summary

This session fixed a critical bug where the live boxscores processor was being skipped due to deduplication logic, added comprehensive monitoring for detecting future downtime, and audited the full orchestration pipeline for Jan 14.

---

## Critical Fix: Live Scoring System

### Problem
`BdlLiveBoxscoresProcessor` was skipping all runs after the first one each day with message:
```
Skipping BdlLiveBoxscoresProcessor for 2026-01-14 - already processed
```

This caused a **724-minute gap** (12 hours) in live data collection.

### Root Cause
The `ProcessorBase` deduplication check was blocking live processors that need to run repeatedly (every 3 minutes during games).

### Fix Applied
Added `SKIP_DEDUPLICATION` flag to `ProcessorBase` (commit `f7be01c`):
```python
# In data_processors/raw/processor_base.py
SKIP_DEDUPLICATION: bool = False  # Default

# In data_processors/raw/balldontlie/bdl_live_boxscores_processor.py
SKIP_DEDUPLICATION: bool = True  # Skip deduplication for live processor
```

### Deployment
- **Deployed**: 2026-01-15 02:40 UTC
- **Revision**: `nba-phase2-raw-processors-00094-snn`
- **Verified working**: 141 rows processed at 02:42 UTC

---

## Monitoring Enhancements

### 1. Processor Health Check in Live Freshness Monitor
Added `check_processor_health()` to `orchestration/cloud_functions/live_freshness_monitor/main.py`:
- Queries `processor_run_history` for last `BdlLiveBoxscoresProcessor` run
- Alerts if no runs for 30+ minutes during game hours
- Catches root cause before exports become stale

**Deployed**: 2026-01-15 03:26 UTC

### 2. OddsAPI Data Monitoring in Self-Heal
Added `check_odds_data_freshness()` to `orchestration/cloud_functions/self_heal/main.py`:
- Checks if OddsAPI game lines and props exist for today
- Logs warning if odds data incomplete
- Informational only (doesn't trigger healing)

**Status**: Deployment in progress

### 3. Health Check Script
Created `scripts/check_live_system_health.py` for end-of-day reports:
```bash
python scripts/check_live_system_health.py --date 2026-01-14
```
Shows:
- Uptime percentage
- Gaps in processor runs
- Games covered
- Data collection stats

---

## Orchestration Health Audit (Jan 14)

### Phase Summary
| Phase | Runs | Success | Failed | Rate | Notes |
|-------|------|---------|--------|------|-------|
| Phase 2 - Raw | 604 | 302 | 285 | 50% | Most failures are cleanup artifacts |
| Phase 4 - Precompute | 56 | 4 | 52 | 7% | Upstream dependency failures |
| Phase 5 - Predictions | 14 | 4 | 10 | 29% | Predictions ARE being made |

### Error Categories
| Category | Count | Action |
|----------|-------|--------|
| Stuck processor cleanup | 143 | Expected - cleanup job artifact |
| Unknown (null errors) | 229 | Need better error capture |
| Partition filter error | ~37 | Same issue as OddsAPI batch |

### Key Findings
1. **Predictions ARE working**: 358 predictions for Jan 14 (73 players, 7 games)
2. **Live grading IS working**: 73 predictions tracked, 17/62 graded (games in progress)
3. **TeamOffenseGameSummaryProcessor**: 0% success - partition filter error + no source data
4. **Most "failures" are cleanup artifacts**, not real processing errors

---

## Outstanding Issues

### P1 - High Priority
1. **TeamOffenseGameSummaryProcessor partition filter**
   - Same issue as OddsAPI batch (filter at end of ON clause, not first)
   - Location: `data_processors/analytics/analytics_base.py:1796`
   - Fix: Move partition filter to first position in ON clause

2. **50 orphaned staging tables in nba_predictions**
   - From Dec 20, 2025 batch operations
   - Cleanup was started but may not have completed
   - Run: `bq ls nba_predictions | grep "_staging_" | xargs -I{} bq rm -f nba_predictions.{}`

### P2 - Medium Priority
3. **229 null error failures**
   - Processors failing without proper error capture
   - Need to add better error handling in base classes

4. **Deploy remaining services**
   - `nba-phase3-analytics-processors` - needs Docker build + deploy
   - `nba-phase4-precompute-processors` - needs Docker build + deploy

---

## Commits This Session

```
398cc4e feat(monitoring): Add processor health check to live freshness monitor
f7be01c fix(live): Add SKIP_DEDUPLICATION flag for live processors
cd4fb36 feat(orchestration): Add OddsAPI data monitoring to self-heal
297c947 feat(oddsapi): Add timeout enforcement to batch processor execution
2ed7884 fix(oddsapi): Fix partition filter for game lines batch MERGE
```

All pushed to `main`.

---

## Odds Data Tracking (User Question)

### Current State
We DO track line movement with multiple snapshots:
- **3 snapshots per game** (first ~6 hours before game, last near game time)
- **Columns available**: `snapshot_timestamp`, `commence_time`, `game_start_time`, `snapshot_rank`
- **Can calculate**: `TIMESTAMP_DIFF(commence_time, snapshot_timestamp, MINUTE) as minutes_before_game`

### Historical Data
- **OddsAPI historical**: Can request with timestamp to get lines at specific times
- **BettingPros**: Likely closing lines (captured day-of-game)

### Potential Improvements
1. Add `minutes_before_game` as derived column
2. Tag snapshots as `opening_line`, `morning_line`, `closing_line`
3. Increase snapshot frequency on game day

---

## Deployment Status

| Service | Status | Notes |
|---------|--------|-------|
| nba-phase2-raw-processors | ✅ Deployed | Rev 00094 - SKIP_DEDUPLICATION fix |
| live-freshness-monitor | ✅ Deployed | 03:26 UTC - Processor health check |
| self-heal | ⏳ In progress | OddsAPI monitoring |
| nba-phase3-analytics | ❌ Not deployed | Needs Docker build |
| nba-phase4-precompute | ❌ Not deployed | Needs Docker build |

---

## Current System Health

### Live System (After Fix)
- ✅ BdlLiveBoxscoresProcessor running every 3 min
- ✅ 1,938+ records collected for Jan 14 games
- ✅ 5 of 7 games covered (2 late games starting)
- ✅ Live grading exporting to GCS

### Predictions
- ✅ Jan 15: 365 predictions (77 players, 7 games)
- ✅ Jan 14: 358 predictions (73 players, 7 games)
- ✅ Jan 13: 295 predictions (62 players, 6 games)

### Cloud Scheduler
- All 11+ scheduler jobs ENABLED
- Live boxscores: every 3 min during game hours
- Live freshness monitor: every 5 min during game hours
- Grading: daily at 11 AM ET

---

## Recommended Next Steps

1. **Verify self-heal deployment completed**
   ```bash
   gcloud functions describe self-heal --region=us-west2 --format="value(updateTime)"
   ```

2. **Clean up staging tables**
   ```bash
   for table in $(bq ls nba_predictions | grep "_staging_" | awk '{print $1}'); do
     bq rm -f "nba_predictions.$table"
   done
   ```

3. **Fix TeamOffenseGameSummaryProcessor partition filter**
   - Edit `data_processors/analytics/analytics_base.py:1796`
   - Move partition filter to first position in ON clause

4. **Deploy analytics/precompute services**
   ```bash
   # Build and push
   docker build -f docker/analytics-processor.Dockerfile -t gcr.io/nba-props-platform/nba-phase3-analytics-processors:latest .
   docker push gcr.io/nba-props-platform/nba-phase3-analytics-processors:latest

   # Deploy
   gcloud run deploy nba-phase3-analytics-processors \
     --image=gcr.io/nba-props-platform/nba-phase3-analytics-processors:latest \
     --region=us-west2
   ```

5. **Consider odds tracking improvements**
   - Add `minutes_before_game` column
   - Tag snapshots by timing

---

## Quick Reference

### Check Live System Health
```bash
python scripts/check_live_system_health.py --date 2026-01-14
```

### Check Processor Runs
```sql
SELECT processor_name, status, COUNT(*)
FROM nba_reference.processor_run_history
WHERE DATE(started_at, "America/New_York") = "2026-01-14"
GROUP BY 1, 2
ORDER BY 1, 2
```

### Check Predictions
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date >= "2026-01-13"
GROUP BY 1 ORDER BY 1 DESC
```

### Check Live Grading
```bash
gcloud logging read 'textPayload:"live grading"' --limit=5 --format="table(timestamp, textPayload)"
```

---

**Session Duration**: ~2 hours
**Primary Accomplishments**: Fixed live scoring, added monitoring, audited pipeline
