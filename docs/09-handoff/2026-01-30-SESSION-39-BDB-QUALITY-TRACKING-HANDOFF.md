# Session 39 Handoff - BigDataBall Quality Tracking System

**Date:** 2026-01-30
**Status:** Implementation Complete, Deployment Pending

---

## Executive Summary

Built a comprehensive system to:
1. **Track** when BigDataBall data is missing
2. **Alert** when predictions are degraded
3. **Auto-retry** when BDB data arrives
4. **Log** everything for audit trail

### Root Cause Finding

**BigDataBall data IS available** for all recent games. The problem was that 21 dates in January were processed BEFORE BDB was available. The current pipeline is working correctly for new data.

---

## What Was Built

### 1. Shot Zone Validation Fixes (Prevent Corruption)

| File | Change |
|------|--------|
| `shot_zone_analyzer.py` | Fixed NBAC to extract three-point data (was missing!) |
| `shot_zone_analyzer.py` | Added completeness validation before returning data |
| `shot_zone_analyzer.py` | Tracks games that used fallback for later re-run |
| `player_shot_zone_analysis_processor.py` | Validates all zones before calculating rates |
| `validate_tonight_data.py` | Added `check_shot_zone_quality()` to daily validation |

### 2. BigDataBall Monitoring & Alerting

| File | Purpose |
|------|---------|
| `bin/monitoring/bdb_critical_monitor.py` | Main monitor - checks BDB availability, sends alerts |
| `bin/monitoring/bdb_pending_monitor.py` | Checks for pending games, triggers re-runs |
| `schemas/.../pending_bdb_games.sql` | Table to track games awaiting BDB |

### 3. Prediction Quality Tracking

| File | Purpose |
|------|---------|
| `predictions/worker/quality_tracker.py` | Tracks data quality for each prediction |
| `schemas/.../prediction_audit_log.sql` | Audit log table schema |

### 4. Automatic Re-run System

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/bdb_arrival_trigger/main.py` | Cloud Function that detects BDB arrival and triggers re-runs |

### 5. Documentation

| File | Purpose |
|------|---------|
| `docs/08-projects/current/data-recovery-strategy/DATA-RECOVERY-STRATEGY.md` | Overall strategy |
| `docs/08-projects/current/data-recovery-strategy/PREDICTION-QUALITY-TRACKING.md` | Detailed design |

---

## Key Design Decisions

### 1. When to Re-run Predictions?

**Decision:** Only if >1 hour before game start

**Reasoning:**
- Users may have bet based on our prediction
- Changing predictions close to game time is confusing
- But early re-runs with better data improve accuracy

### 2. Should Missing Shot Zones Block Predictions?

**Decision:** No - always generate, but flag quality tier

**Quality Tiers:**
- **Gold**: All data available (BDB + full features)
- **Silver**: Using NBAC fallback (BDB unavailable)
- **Bronze**: Shot zone features unavailable

### 3. How to Show Quality in API?

**Decision:** Add quality object to each prediction:

```json
{
  "prediction": "over",
  "confidence": 0.72,
  "quality": {
    "tier": "silver",
    "shot_zones_available": false,
    "warning": "Shot zone data unavailable - using fallback"
  }
}
```

---

## Deployment Steps

### Step 1: Create BigQuery Tables

```bash
# Create audit log table
bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/prediction_audit_log.sql

# pending_bdb_games already created in this session
```

### Step 2: Deploy Cloud Function

```bash
gcloud functions deploy bdb-arrival-trigger \
  --gen2 \
  --runtime python311 \
  --region us-west2 \
  --source orchestration/cloud_functions/bdb_arrival_trigger \
  --entry-point bdb_arrival_handler \
  --trigger-topic nba-bdb-arrival
```

### Step 3: Set Up Cloud Scheduler

```bash
# Run BDB monitor every 30 minutes
gcloud scheduler jobs create pubsub bdb-monitor-scheduled \
  --schedule="*/30 * * * *" \
  --topic=nba-bdb-arrival \
  --message-body='{"source": "scheduler"}'
```

### Step 4: Add Slack Webhook

```bash
# Set environment variable for BDB monitor
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

### Step 5: Backfill Affected Dates

21 dates need Phase 3 re-processing:
```
Jan 1, 3, 9, 12-20, 22-24
```

---

## Testing Commands

```bash
# Test BDB monitor (dry run)
python bin/monitoring/bdb_critical_monitor.py --dry-run

# Test BDB arrival trigger locally
python orchestration/cloud_functions/bdb_arrival_trigger/main.py

# Check pending BDB games
bq query --use_legacy_sql=false "
SELECT game_date, game_id, status, fallback_source
FROM nba_orchestration.pending_bdb_games
ORDER BY game_date DESC"

# Check quality distribution
bq query --use_legacy_sql=false "
SELECT data_quality_tier, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1"
```

---

## Data Flow

```
                                   ┌─────────────────────┐
                                   │ BDB Scraper Runs    │
                                   └──────────┬──────────┘
                                              │
                                              ▼
┌──────────────────┐              ┌─────────────────────┐
│ Phase 2: BDB PBP │◄─────────────│ bigdataball_play_   │
│ Processing       │              │ by_play table       │
└────────┬─────────┘              └──────────┬──────────┘
         │                                   │
         │ If BDB unavailable                │ BDB arrival detected
         ▼                                   ▼
┌──────────────────┐              ┌─────────────────────┐
│ Phase 3: Uses    │              │ bdb_arrival_trigger │
│ NBAC fallback    │              │ Cloud Function      │
└────────┬─────────┘              └──────────┬──────────┘
         │                                   │
         │                                   │ Check: Is re-run safe?
         ▼                                   │ (>1h before game?)
┌──────────────────┐                         │
│ pending_bdb_     │◄────────────────────────┘
│ games table      │                  │
│ status=pending   │                  │ Yes
└────────┬─────────┘                  ▼
         │                   ┌─────────────────────┐
         │                   │ Trigger Phase 3     │
         │                   │ Re-run              │
         │                   └──────────┬──────────┘
         │                              │
         ▼                              ▼
┌──────────────────┐         ┌─────────────────────┐
│ Phase 4/5:       │         │ Phase 4/5: Re-run   │
│ quality=silver   │         │ quality=gold        │
└──────────────────┘         └─────────────────────┘
```

---

## Commits from Session 39

```
30fa1c99 feat: Add BigDataBall critical monitoring and shot zone validation
ef7cba45 feat: Add prediction quality tracking and BDB auto-rerun system
ee190236 docs: Add BigDataBall operations guide and backfill script
```

---

## Dates Needing Backfill

Run `python bin/backfill/backfill_shot_zones.py --dry-run` to see current state.

Found 10 dates with <50% paint_attempts coverage despite BDB data being available:

| Date | Current Coverage | BDB Available |
|------|-----------------|---------------|
| 2026-01-02 | 9.3% | Yes |
| 2026-01-03 | 7.9% | Yes |
| 2026-01-04 | 12.2% | Yes |
| 2026-01-05 | 15.9% | Yes |
| 2026-01-06 | 15.9% | Yes |
| 2026-01-07 | 15.5% | Yes |
| 2026-01-10 | 7.9% | Yes |
| 2026-01-11 | 8.5% | Yes |
| 2026-01-21 | 0.0% | Yes |
| 2026-01-24 | 7.6% | Yes |

---

## Known Issues

1. **2 dates cannot be backfilled** - Jan 22-23 missing `nbac_gamebook_player_stats` source data
2. **Pub/Sub trigger not connected** - The `nba-phase3-trigger` topic has no subscriptions
3. **Quality tracker not integrated** - Prediction worker needs to call quality_tracker
4. **NBAC play-by-play table is EMPTY** - Fallback path has nothing to fall back to

### RESOLVED: Stale Dependencies

The stale dependency issue was resolved by deploying the latest code. Cloud Scheduler
successfully ran overnight-analytics-6am-et which updated the analytics tables.

### Backfill Status

After investigation, found that Phase 3 requires `nbac_gamebook_player_stats` as source:

| Date | nbac_gamebook_stats | bdl_boxscores | Can Backfill? |
|------|---------------------|---------------|---------------|
| Jan 20 | ✅ 245 records | ✅ | ✅ Done (30.3%) |
| Jan 21 | ✅ 247 records | ✅ | ✅ Done |
| Jan 22 | ❌ 0 records | ✅ 282 | ❌ Missing source |
| Jan 23 | ❌ 0 records | ✅ 281 | ❌ Missing source |
| Jan 24 | ✅ 243 records | ✅ | ✅ Done |

**To fix Jan 22-23:** Need to re-run NBAC scraper for those dates to populate the source table.

---

## Tables Created This Session

- `nba_orchestration.pending_bdb_games` ✅ Created
- `nba_predictions.prediction_audit_log` ✅ Created

---

## Next Session Checklist

1. [ ] **Run backfill** - `python bin/backfill/backfill_shot_zones.py` (10 dates)
2. [ ] Deploy bdb_arrival_trigger Cloud Function
3. [ ] Set up Cloud Scheduler for periodic checks (every 30 min)
4. [ ] Integrate quality_tracker into prediction worker
5. [ ] Add quality fields to predictions API response
6. [ ] Re-run Phase 4/5 after Phase 3 backfill completes
7. [ ] Add Slack webhook for alerts
8. [ ] Investigate why NBAC play-by-play table is empty

---

## Monitoring Queries

### Check BDB Coverage

```sql
SELECT
  game_date,
  COUNT(DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0')) as games_with_bdb,
  (SELECT COUNT(*) FROM nba_raw.nbac_schedule s
   WHERE s.game_date = b.game_date AND s.game_status = 3) as expected_games
FROM nba_raw.bigdataball_play_by_play b
WHERE game_date >= CURRENT_DATE() - 7
  AND bdb_game_id IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC
```

### Check Prediction Quality Distribution

```sql
SELECT
  game_date,
  data_quality_tier,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1 DESC, 2
```

### Check Pending BDB Games

```sql
SELECT
  game_date,
  status,
  COUNT(*) as games
FROM nba_orchestration.pending_bdb_games
GROUP BY 1, 2
ORDER BY 1 DESC
```

---

## Key Learnings

1. **BDB data IS available** - The scraper is working, data exists
2. **Extraction pipeline had gaps** - Old data processed without BDB
3. **Quality visibility is critical** - We didn't know predictions were degraded
4. **Re-run timing matters** - Can't change predictions close to game time (use 1h cutoff)
5. **Audit trail is essential** - Need to know what data was available when

## Orchestration Architecture Findings

### How Phase 3 is Triggered (Correct Understanding)

```
Phase 2 completes
    ↓ publishes to
nba-phase2-raw-complete (Pub/Sub)
    ↓ triggers (via Eventarc)
phase2-to-phase3-orchestrator (Cloud Function)
    ↓ calls HTTP
nba-phase3-analytics-processors (Cloud Run)
```

**Plus Cloud Scheduler fallbacks:**
- `overnight-analytics-6am-et` (6 AM ET) - All 5 processors for yesterday
- `same-day-phase3` (10:30 AM ET) - UpcomingPlayer for today

### Why Backfill Script Was Broken

The backfill script published to `nba-phase3-trigger` Pub/Sub topic, but:
- This topic has **NO subscriptions** (vestigial)
- Phase 3 is triggered via HTTP by Cloud Function, not Pub/Sub directly
- Fixed: Changed script to use HTTP `/process-date-range` endpoint

### Pub/Sub Topics Status

| Topic | Subscribers | Status |
|-------|-------------|--------|
| `nba-phase2-raw-complete` | Eventarc trigger | ✅ Active |
| `nba-phase3-trigger` | None | ❌ Unused |
| `nba-phase3-analytics-complete` | Eventarc trigger | ✅ Active |
| `nba-phase4-trigger` | Phase 4 Cloud Run | ✅ Active |

---

## New Files Created

| File | Purpose |
|------|---------|
| `bin/monitoring/bdb_critical_monitor.py` | BDB availability monitoring and alerts |
| `bin/monitoring/bdb_pending_monitor.py` | Pending game re-run monitor |
| `bin/backfill/backfill_shot_zones.py` | Backfill script for affected dates |
| `predictions/worker/quality_tracker.py` | Prediction quality tracking |
| `orchestration/cloud_functions/bdb_arrival_trigger/main.py` | Auto re-run Cloud Function |
| `schemas/bigquery/nba_orchestration/pending_bdb_games.sql` | Pending games table schema |
| `schemas/bigquery/nba_predictions/prediction_audit_log.sql` | Audit log table schema |
| `docs/02-operations/bigdataball-operations.md` | Complete BDB operations runbook |
| `docs/08-projects/current/data-recovery-strategy/DATA-RECOVERY-STRATEGY.md` | Recovery strategy doc |
| `docs/08-projects/current/data-recovery-strategy/PREDICTION-QUALITY-TRACKING.md` | Quality tracking design |

---

*Session 39 complete. BigDataBall quality tracking system built. Run backfill and deploy Cloud Function next.*
