# Pipeline Investigation Report

**Date**: 2026-01-27 11:00 AM ET
**Investigator**: Claude (Opus 4.5)
**Status**: INVESTIGATION COMPLETE - AWAITING REVIEW BEFORE CHANGES

---

## Executive Summary

The prediction pipeline is not generating predictions for today (Jan 27) due to **missing props data**. The root cause is a **stale deployment** of the `nba-scrapers` service, which is using an outdated 6-hour window instead of the configured 12-hour window for the `betting_lines` workflow.

Additionally, the **BigQuery quota issue** from the previous session is still active - monitoring tables are exceeding the 1,500 load jobs/table/day limit by 5-12x.

---

## Issue #1: No Predictions for Today

### Symptoms
- 0 predictions generated for Jan 27
- Prediction worker returning HTTP 500 with "LINE QUALITY VALIDATION FAILED"
- Error: `line_value=20.0 (PLACEHOLDER)` for all prediction systems

### Root Cause Chain
```
1. nba-scrapers service is stale (deployed Jan 24, config changed Jan 26)
   ↓
2. betting_lines workflow uses 6-hour window (default) instead of 12-hour (configured)
   ↓
3. Controller skips workflow: "First game in 9.0h (window starts 6h before)"
   ↓
4. bp_player_props scraper doesn't run → No props data for today
   ↓
5. Predictions use placeholder line values → Quality validation fails
```

### Evidence

**Service Deployment Status:**
```
nba-scrapers last deployed: 2026-01-24T02:17:15Z
Config change committed:    2026-01-26 (f4385d03)
Change: window_before_game_hours: 6 → 12
```

**Controller Decision at 10:00 AM ET:**
```
📊 Evaluating: betting_lines (type: game_aware)
⏭️ Decision: SKIP - First game in 9.0h (window starts 6h before)
```

**Props Data Status:**
| Date | Props Count | First Prop | Last Prop |
|------|-------------|------------|-----------|
| Jan 27 | **0** | - | - |
| Jan 26 | 201,060 | 17:07 UTC | 04:00 UTC |
| Jan 25 | 251,380 | 14:07 UTC | 04:15 UTC |

**Betting Lines Workflow History (ET):**
| Date | Time ET | Scrapers | Status |
|------|---------|----------|--------|
| Jan 26 | 7:06 PM | 13 | completed |
| Jan 26 | 7:05 PM | 13 | completed |
| Jan 26 | 3:05 PM | 17 | completed |
| Jan 26 | 12:05 PM | 17 | completed |
| **Jan 27** | **None during business hours** | - | - |

**Today's Games:**
- 7 games scheduled
- First game: 7:00 PM ET (POR @ WAS)
- With 12-hour window: workflow should start at 7 AM ET
- With 6-hour window (current): workflow starts at 1 PM ET

### Impact
- No predictions for any of today's 7 games
- Revenue impact: 100% prediction loss for Jan 27

---

## Issue #2: BigQuery Quota Exceeded

### Symptoms
- Monitoring tables exceeding 1,500 load jobs/table/day limit
- Quota errors in Phase 3 logs: `403 Quota exceeded`
- Batch writer showing "Failed to flush 1 records" (batching ineffective)

### Root Cause
The batch writer code exists but is ineffective because **Cloud Run instances scale to zero**. Each instance has its own in-memory buffer, and when instances terminate, they flush partial batches (often just 1-2 records).

### Evidence

**Current Quota Usage (Jan 27):**
| Table | Load Jobs | % of 1,500 Limit |
|-------|-----------|------------------|
| processor_run_history | 17,512 | **1,168%** |
| pipeline_event_log | 11,633 | **776%** |
| circuit_breaker_state | 8,005 | **534%** |
| analytics_processor_runs | 7,064 | **471%** |
| bdl_live_boxscores | 2,711 | 181% |

**Records vs Load Jobs (processor_run_history):**
- Actual records written today: ~805
- Load jobs used: 17,512
- Expected with 100:1 batching: ~8 jobs
- Actual ratio: **~22 load jobs per record** (batching defeated)

**Hourly Peak Analysis:**
| Table | Peak Hourly Jobs |
|-------|------------------|
| processor_run_history | 4,079 |
| circuit_breaker_state | 1,770 |
| analytics_processor_runs | 1,742 |
| pipeline_event_log | 1,458 |

**Quota Errors (last 4 hours):**
- All from `nba-phase3-analytics-processors`
- Error: `403 Quota exceeded: Your table exceeded quota for imports or query appends per table`
- Pattern: Errors occurring at regular intervals (every 15-30 min)

### Impact
- Monitoring data being dropped silently
- Phase 3 processors logging failures (non-blocking but losing observability)
- Self-healing mechanism not working as intended

---

## Issue #3: Phase 2 Malformed Messages

### Symptoms
- Phase 2 processor receiving unrecognized Pub/Sub message format
- Every 15 minutes, errors logged

### Evidence
```
ERROR: Invalid message format: Unrecognized message format.
Expected 'name' (GCS), 'gcs_path' (Scraper), or 'processor_name' (Unified) field.
Got fields: ['game_date', 'output_table', 'status', 'triggered_by', 'retry_count']
```

### Analysis
The message format `['game_date', 'output_table', 'status', 'triggered_by', 'retry_count']` looks like a **Phase 3 completion message** or an **auto-retry message** being incorrectly routed to the Phase 2 subscription.

**Pub/Sub Subscriptions:**
- `nba-phase2-raw-sub` subscribes to `nba-phase1-scrapers-complete`
- The bad messages appear to be from a different source (possibly auto-retry system)

### Impact
- Non-blocking (messages are rejected, not processed)
- Adds noise to logs
- May indicate a configuration issue in Pub/Sub routing

---

## Issue #4: Other Scraper Failures

### Evidence (Today's Scraper Runs)
| Scraper | Runs | Success | Failed | Notes |
|---------|------|---------|--------|-------|
| bdb_pbp_scraper | 109 | 7 | 102 | **93% failure rate** |
| nbac_team_boxscore | 95 | 28 | 67 | **71% failure rate** |
| nbac_play_by_play | 18 | 0 | 4 | Some failures |
| nbac_player_boxscore | 9 | 0 | 4 | Some failures |

### Analysis
- `bdb_pbp_scraper` (Big Data Ball): High failure rate, possibly API issues
- `nbac_team_boxscore`: Known issue (NBA API returning 0 teams since Dec 2025)
- These are for yesterday's games (post-game collection), not today's predictions

---

## Service Deployment Status

| Service | Revision | Deployed | Needs Update |
|---------|----------|----------|--------------|
| nba-scrapers | 00101-lkv | Jan 24 | **YES** (config stale) |
| nba-phase2-raw-processors | 00105-4g2 | Recent | No |
| nba-phase3-analytics-processors | 00115-tzs | Jan 27 | No |
| nba-phase4-precompute-processors | 00059-lw4 | Jan 27 | No |
| prediction-coordinator | qkh | Recent | No |
| prediction-worker | 54v | Recent | No |

---

## Pipeline Data Flow Status

| Stage | Status | Data for Jan 27 |
|-------|--------|-----------------|
| Phase 1 (Scrapers) | Partial | Games: 7, Props: **0** |
| Phase 2 (Raw Processing) | Working | N/A (no props to process) |
| Phase 3 (Analytics) | Working | 236 rows |
| Phase 4 (ML Features) | Working | 236 rows |
| Phase 5 (Predictions) | **Failing** | 0 predictions |

---

## Recommended Actions

### Immediate (to restore predictions today)

1. **Redeploy nba-scrapers service**
   ```bash
   # This will pick up the 12-hour window config
   bash bin/deploy/deploy_scrapers.sh
   ```
   - Risk: Low (just deploying existing code + config)
   - Time: ~10 minutes

2. **Manually trigger betting_lines workflow**
   ```bash
   # After redeployment, or manually invoke scrapers
   curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"force_workflows": ["betting_lines"]}'
   ```
   - Risk: Low
   - Time: ~15 minutes for props collection

3. **Re-trigger predictions after props are collected**
   ```bash
   gcloud scheduler jobs run morning-predictions --location=us-west2
   ```

### Short-term (BigQuery quota fix)

4. **Switch monitoring tables to streaming inserts**
   - Modify `BigQueryBatchWriter` to use `insert_rows_json()` instead of `load_table_from_json()`
   - Cost impact: ~$0.49/year (negligible)
   - This completely bypasses the load job quota

5. **Alternative: Set Cloud Run min-instances > 0**
   - Keeps instances warm, allows batching to work
   - Cost: ~$15/month per service
   - Less effective than streaming inserts

### Investigation needed

6. **Phase 2 malformed messages**
   - Identify source of messages with `['game_date', 'output_table', 'status', 'triggered_by', 'retry_count']`
   - Likely the auto-retry system publishing to wrong topic
   - Low priority (non-blocking)

7. **bdb_pbp_scraper failures**
   - 93% failure rate needs investigation
   - May be API rate limiting or endpoint changes

---

## Questions for Review

1. **Should we redeploy nba-scrapers immediately?**
   - Pro: Restores normal workflow timing
   - Con: None identified (config change already committed)

2. **Should we manually trigger betting_lines before redeployment?**
   - This would work but uses the 6-hour window
   - Games start at 7 PM, so we have time either way

3. **BigQuery streaming inserts - proceed with implementation?**
   - Recommended as the cleanest fix
   - Alternative: accept some monitoring data loss

4. **Phase 2 malformed messages - priority?**
   - Currently non-blocking
   - Can investigate after predictions are restored

---

## Appendix: Raw Data

### A. Workflow Decision Log (10:00 AM ET)
```
📊 Evaluating: betting_lines (type: game_aware)
⏭️ Decision: SKIP - First game in 9.0h (window starts 6h before)
schedule_locker: betting_lines: 1 expected runs
```

### B. Prediction Worker Errors
```
2026-01-27 15:53:13 - worker - ERROR - LINE QUALITY VALIDATION FAILED
Issues:
  - moving_average: line_value=20.0 (PLACEHOLDER)
  - zone_matchup_v1: line_value=20.0 (PLACEHOLDER)
  - similarity_balanced_v1: line_value=20.0 (PLACEHOLDER)
  - catboost_v8: line_value=20.0 (PLACEHOLDER)
  - ensemble_v1: line_value=20.0 (PLACEHOLDER)
Failed: 6/30 predictions
```

### C. Config Diff (committed Jan 26)
```yaml
# config/workflows.yaml - betting_lines workflow
schedule:
  game_aware: true
  window_before_game_hours: 12  # Changed from 6
  business_hours:
    start: 8   # 8 AM ET
    end: 20    # 8 PM ET
  frequency_hours: 2
```

### D. BigQuery Batch Writer Limitation
```python
# shared/utils/bigquery_batch_writer.py
# Line 452: window_hours = schedule.get('window_before_game_hours', 6)
# Default is 6, config file says 12, but config not deployed
```

---

**Document created for review before any changes are made.**
