# Handoff: Orchestration Validation - January 25, 2026

**Created:** 2026-01-25 ~6:00 PM PST
**Purpose:** Validate today's (Jan 24) and yesterday's (Jan 23) orchestration completed properly
**Priority:** High - System was down for ~2 days due to Firestore permission issue

---

## Context: What Happened

### Root Cause (Fixed Jan 25)
The master controller was blocked since Jan 23 due to missing Firestore permissions:
```
ERROR: Firestore error acquiring lock: 403 Missing or insufficient permissions.
```

**Fix Applied:**
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:bigdataball-puller@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### Impact
- Post-game workflows stopped running (Jan 23-24)
- Schedule data became stale (games showed "Scheduled" instead of "Final")
- Only `bdl_live_boxscores` kept running (has dedicated scheduler)
- Phase 2→3→4 cascade was blocked

### Recovery Actions Taken
1. ✅ Granted Firestore permissions to service account
2. ✅ Manually updated schedule with correct game statuses
3. ✅ Triggered workflow evaluation - workflows now running
4. ✅ Triggered boxscore scrapers for Jan 24
5. ✅ Started Phase 3 analytics backfill for Jan 23-24
6. ✅ Started background monitoring

---

## Current State (as of ~6:00 PM PST Jan 24)

### Boxscore Data Status
| Date | Records | Games | Expected | Status |
|------|---------|-------|----------|--------|
| Jan 24 | 174 | 5 | 7 (2 Final, 2 IP, 3 Scheduled) | ✅ On track |
| Jan 23 | 281 | 8 | 8 | ✅ Complete |
| Jan 22 | 282 | 8 | 8 | ✅ Complete |

### Jan 24 Schedule Status
- 3 games: Scheduled (West Coast evening games)
- 2 games: In Progress
- 2 games: Final

### Analytics Tables
| Table | Jan 23 | Jan 24 | Jan 25 |
|-------|--------|--------|--------|
| player_game_summary | 281 ✅ | Pending | - |
| upcoming_player_game_context | - | 181 ✅ | 189 ✅ |

### System Health
- ✅ Pipeline Event Logging: Working
- ✅ Failed Processor Queue: Empty
- ✅ Live Boxscores: Running every 3 min
- ✅ Firestore Locks: No stuck locks

---

## Validation Tasks for New Session

### 1. Check Schedule Data is Current
```bash
bq query --use_legacy_sql=false "
SELECT game_date, game_status, COUNT(*) as games
FROM \`nba_raw.nbac_schedule\`
WHERE game_date >= '2026-01-24' AND game_date <= '2026-01-25'
GROUP BY 1, 2
ORDER BY game_date, game_status"
```
**Expected:** Jan 24 should show most/all games as Final (status=3)

### 2. Verify Boxscore Data Complete
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as records,
  COUNT(DISTINCT game_id) as games
FROM \`nba_raw.bdl_player_boxscores\`
WHERE game_date >= '2026-01-23'
GROUP BY 1
ORDER BY game_date DESC"
```
**Expected:**
- Jan 24: ~245 records (7 games × ~35 players)
- Jan 23: 281 records (8 games) ✅

### 3. Check Analytics Tables Updated
```bash
bq query --use_legacy_sql=false "
SELECT table_name, game_date, records FROM (
  SELECT 'player_game_summary' as table_name, game_date, COUNT(*) as records
  FROM \`nba_analytics.player_game_summary\` WHERE game_date >= '2026-01-23' GROUP BY 1, 2
  UNION ALL
  SELECT 'team_offense_game_summary', game_date, COUNT(*)
  FROM \`nba_analytics.team_offense_game_summary\` WHERE game_date >= '2026-01-23' GROUP BY 1, 2
  UNION ALL
  SELECT 'upcoming_player_game_context', game_date, COUNT(*)
  FROM \`nba_analytics.upcoming_player_game_context\` WHERE game_date >= '2026-01-24' GROUP BY 1, 2
)
ORDER BY table_name, game_date DESC"
```
**Expected:** Data for Jan 23 and Jan 24 should exist

### 4. Verify Phase 2 Completion Tracking
```bash
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  game_date,
  status,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', completed_at) as completed
FROM \`nba_orchestration.processor_completions\`
WHERE game_date >= '2026-01-23'
ORDER BY game_date DESC, completed_at DESC
LIMIT 30"
```

### 5. Check Pipeline Event Log
```bash
bq query --use_legacy_sql=false "
SELECT event_type, COUNT(*) as count
FROM \`nba_orchestration.pipeline_event_log\`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 12 HOUR)
GROUP BY event_type"
```
**Expected:** Should show processor_start and processor_complete events

### 6. Check Failed Processor Queue
```bash
bq query --use_legacy_sql=false "
SELECT status, COUNT(*) FROM \`nba_orchestration.failed_processor_queue\` GROUP BY status"
```
**Expected:** Empty or all 'succeeded'

### 7. Verify Master Controller Working
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND textPayload:"/evaluate"' --project=nba-props-platform --limit=10 --format="table(timestamp,textPayload)"
```
**Expected:** Regular /evaluate calls with 200 responses

### 8. Check for Firestore Lock Issues
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND textPayload:"403"' --project=nba-props-platform --limit=5 --format="table(timestamp,textPayload)"
```
**Expected:** No recent 403 errors

---

## If Issues Found

### If boxscore data missing for Jan 24:
```bash
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "bdl_player_box_scores", "game_date": "2026-01-24"}'
```

### If analytics tables missing data:
```bash
./bin/backfill/run_year_phase3.sh --start-date 2026-01-23 --end-date 2026-01-24
```

### If schedule data stale:
```bash
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_schedule_api", "season": "2025"}'
```

### If workflows not evaluating:
```bash
curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/evaluate" \
  -H "Content-Type: application/json" -d '{}'
```

---

## New Infrastructure Deployed (Jan 25)

### Auto-Retry System
- **BigQuery Tables:**
  - `nba_orchestration.failed_processor_queue` - Tracks failed processors for retry
  - `nba_orchestration.pipeline_event_log` - Audit trail of all processor runs
  - `nba_orchestration.v_recovery_dashboard` - View for monitoring recovery

- **Cloud Function:** `auto-retry-processor`
  - Triggered every 15 min by Cloud Scheduler
  - Retries failed processors up to 3 times with exponential backoff

- **Event Logging:** Integrated into `analytics_base.py` and `precompute_base.py`
  - All Phase 3-4 processors now log start/complete/error events

### Validation Scripts
- `bin/validation/validate_orchestration_config.py` - Validates processor names match
- `bin/validation/validate_cloud_function_imports.py` - Validates CF imports
- `bin/validation/detect_config_drift.py` - Detects Cloud resource config drift
- `bin/monitoring/setup_memory_alerts.sh` - Sets up memory warning alerts

---

## Key Files Modified (Jan 25)

| File | Change |
|------|--------|
| `shared/utils/pipeline_logger.py` | NEW - Event logging utility |
| `orchestration/cloud_functions/auto_retry_processor/` | NEW - Auto-retry function |
| `data_processors/analytics/analytics_base.py` | Added pipeline logger integration |
| `data_processors/precompute/precompute_base.py` | Added pipeline logger integration |
| `bin/alerts/daily_summary/main.py` | Added recovery stats section |
| `docs/00-orchestration/troubleshooting.md` | Added Firestore permission section |

---

## Documentation Updated

- `docs/08-projects/current/MASTER-PROJECT-TRACKER.md` - Session 15 summary
- `docs/08-projects/current/jan-23-orchestration-fixes/CHANGELOG.md` - Full changelog
- `docs/08-projects/current/pipeline-resilience-improvements/RESILIENCE-PLAN-2026-01-24.md` - Week 1+2 complete

---

## Expected State After Tonight

By tomorrow morning (Jan 25):
1. All Jan 24 games should be Final
2. All boxscore data collected (Jan 24: ~245 records)
3. Phase 3 analytics complete for Jan 24
4. Phase 4 precompute complete for Jan 24
5. Upcoming contexts generated for Jan 25 games
6. No entries in failed_processor_queue

---

## Quick Health Check Command

Run this one-liner to check overall health:
```bash
echo "=== ORCHESTRATION HEALTH CHECK ===" && \
bq query --use_legacy_sql=false "SELECT 'boxscores' as check, game_date, COUNT(*) as records FROM nba_raw.bdl_player_boxscores WHERE game_date >= '2026-01-23' GROUP BY 1,2 UNION ALL SELECT 'analytics', game_date, COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date >= '2026-01-23' GROUP BY 1,2 ORDER BY check, game_date DESC"
```

---

**End of Handoff Document**
