# Handoff: December 30, 2025 Early Morning Session

**Created:** December 30, 2025 01:45 AM ET
**Previous Session:** December 29, 2025 Late Evening (context exhausted twice)
**Priority:** CRITICAL - Prediction coverage fix implemented but not yet tested

---

## Executive Summary

We identified and fixed a **critical data loss issue** where 57% of predictions were being silently dropped due to BigQuery DML concurrency limits. The fix is implemented and deployed but **not yet tested in production**.

### Key Numbers
- **Dec 29 Issue:** Only 68 of 158 players got predictions (43% coverage)
- **Root Cause:** 100 concurrent workers hitting BigQuery's 20 DML limit
- **Fix Status:** Implemented, deployed, awaiting verification
- **Dec 30 Schedule:** 2 games, 60 players in context

---

## What Was Done

### 1. Root Cause Analysis (Complete)

**Problem:** BigQuery limits concurrent DML operations to 20 per table. Our architecture had:
- 20 Cloud Run instances × 5 concurrent = 100 concurrent workers
- Each worker doing MERGE (DML operation)
- Result: 80+ workers rate-limited, predictions lost

**Investigation findings:**
- 158 players processed by workers (all generated predictions)
- 68 writes succeeded, 90 failed with DML rate limit
- Cloud Logging showed: "Too many DML statements outstanding against table"

### 2. Batch Staging Write Pattern (Implemented)

**Solution Architecture:**
```
BEFORE (Broken):
Worker 1 → MERGE → predictions_table  }
Worker 2 → MERGE → predictions_table  } 100 DML = 80 fail
Worker 3 → MERGE → predictions_table  }

AFTER (Fixed):
Worker 1 → INSERT → _staging_batch_worker1  }
Worker 2 → INSERT → _staging_batch_worker2  } No DML limit on INSERT
Worker 3 → INSERT → _staging_batch_worker3  }
...
Coordinator → Single MERGE → predictions_table (1 DML)
```

**Files Created:**
- `predictions/worker/batch_staging_writer.py` (20 KB)
  - `BatchStagingWriter`: Workers write to individual staging tables
  - `BatchConsolidator`: Coordinator merges all staging tables
  - `StagingWriteResult`, `ConsolidationResult`: Result dataclasses

**Files Modified:**
- `predictions/worker/worker.py`
  - Added `get_staging_writer()` lazy loader
  - Modified `write_predictions_to_bigquery()` to use staging pattern
  - Added write metrics tracking

- `predictions/coordinator/coordinator.py`
  - Added `get_batch_consolidator()` lazy loader
  - Modified `publish_batch_summary()` to call consolidation
  - Added coverage monitoring

- `docker/predictions-worker.Dockerfile`
  - Added COPY for `write_metrics.py` and `batch_staging_writer.py`

### 3. Configurable Concurrency (Implemented)

**Problem:** Concurrency was hardcoded in deploy script, required redeployment to change.

**Solution:** Environment variable support + config system.

**Files Modified:**
- `bin/predictions/deploy/deploy_prediction_worker.sh`
  - `MAX_INSTANCES="${WORKER_MAX_INSTANCES:-20}"`
  - `CONCURRENCY="${WORKER_CONCURRENCY:-5}"`

- `shared/config/orchestration_config.py`
  - Added `WorkerConcurrencyConfig` dataclass
  - Added `SelfHealingConfig` dataclass
  - Environment variable loading for both

**Quick Commands:**
```bash
# Check current settings
gcloud run services describe prediction-worker --region=us-west2 \
  --format="table(spec.template.metadata.annotations.'autoscaling.knative.dev/maxScale', spec.template.spec.containerConcurrency)"

# Emergency reduce (use when DML errors occur)
gcloud run services update prediction-worker \
  --max-instances=4 --concurrency=3 --region=us-west2

# Deploy with custom settings
WORKER_MAX_INSTANCES=10 WORKER_CONCURRENCY=5 \
  ./bin/predictions/deploy/deploy_prediction_worker.sh
```

### 4. DML Rate Limit Alerting & Self-Healing (Implemented)

**Files Modified:**
- `predictions/worker/write_metrics.py`
  - `track_dml_rate_limit()` - sends metrics + checks threshold
  - `_check_and_send_dml_alert()` - threshold-based alerting
  - `_send_dml_alert_notification()` - Slack notification
  - `with_exponential_backoff()` - retry with backoff

**Behavior:**
- Tracks DML errors in sliding window (100 most recent)
- Threshold: 5 errors in 60 seconds triggers alert
- Sends Slack message with remediation command
- Exponential backoff: 5s base, doubles each retry, max 120s, with jitter

### 5. Coverage Monitoring (Implemented)

**Files Created:**
- `predictions/coordinator/coverage_monitor.py` (17 KB)
  - `PredictionCoverageMonitor` class
  - `check_coverage()` - checks against thresholds
  - `track_missing_players()` - logs which players missing
  - Thresholds: 95% warning, 85% critical

### 6. Player Aliases (Partial)

**Added 7 aliases to `nba_reference.player_aliases`:**
```sql
herbjones → herbertjones (nickname)
garytrentjr → garytrent (suffix_variation)
jabarismithjr → jabarismith (suffix_variation)
jaimejaquezjr → jaimejaquez (suffix_variation)
michaelporterjr → michaelporter (suffix_variation)
treymurphyiii → treymurphy (suffix_variation)
marvinbagleyiii → marvinbagley (suffix_variation)
```

**Still Missing (from investigation):**
- kevinporterjr
- timhardawayjr
- wendellcarterjr
- nicolasclaxton
- robertwilliams (existing alias is wrong direction)
- alexsarr
- boneshyland

---

## Current State

### Infrastructure

| Component | Current Setting | Notes |
|-----------|-----------------|-------|
| prediction-worker | 4 instances × 3 concurrent = 12 | Emergency mode (manual) |
| prediction-coordinator | 1 instance × 8 concurrent | Default |
| Staging pattern | Deployed | Not yet tested |
| Consolidation | Integrated | Not yet tested |

### Deployments

| Service | Revision | Time |
|---------|----------|------|
| prediction-worker | prediction-worker-00011-zw5 | Dec 30 01:20 UTC |
| prediction-coordinator | prediction-coordinator-00005-b2r | Dec 30 01:18 UTC |

### Data State

| Game Date | Players in Context | Predictions | Coverage |
|-----------|-------------------|-------------|----------|
| Dec 29 | 352 | 1,700 (68 players) | 43% (BROKEN) |
| Dec 30 | 60 | 0 (not yet run) | TBD |

---

## Critical Next Steps

### 1. Test the Fix (HIGHEST PRIORITY)

The staging pattern is deployed but **not yet validated**. Need to:

```bash
# Option A: Wait for scheduled Dec 30 predictions
# Check scheduler: what time does it run?
gcloud scheduler jobs list --location=us-west2 | grep prediction

# Option B: Manually trigger Dec 30 predictions
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-30"}'

# Option C: Force re-run Dec 29 predictions (overwrite existing)
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-29", "force": true}'
```

**What to verify:**
1. Staging tables are created (`_staging_*` in nba_predictions dataset)
2. Consolidation runs successfully (check coordinator logs)
3. All 60 players get predictions (not just 30-40)
4. Staging tables are cleaned up after consolidation

### 2. Monitor Logs

```bash
# Worker logs - look for staging writes
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"Staging write"' --limit=50 --format="table(timestamp,textPayload)"

# Coordinator logs - look for consolidation
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-coordinator" AND textPayload=~"Consolidation"' --limit=50 --format="table(timestamp,textPayload)"

# DML errors (should be zero with staging pattern)
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload=~"DML"' --limit=50 --format="table(timestamp,textPayload)"
```

### 3. Verify Results

```sql
-- Check Dec 30 predictions after run
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-30' AND is_active = TRUE
GROUP BY 1;

-- Expected: ~60 players × 5 systems × 5 lines = ~1500 predictions

-- Check for any staging tables left behind (should be 0)
SELECT table_id, creation_time
FROM `nba-props-platform.nba_predictions.__TABLES__`
WHERE table_id LIKE '_staging_%'
ORDER BY creation_time DESC;
```

---

## Research Findings

### Player Registry Integration Gap

**Finding:** The player registry exists (`shared/utils/player_registry/`) but is underutilized.

| Processor | Uses Registry? | Impact |
|-----------|----------------|--------|
| PlayerGameSummary | ✅ Yes | Works |
| UpcomingPlayerGameContext | ✅ Yes | Works |
| OddsApiPropsProcessor | ❌ No | HIGH - causes mismatches |
| BettingPropsProcessor | ❌ No | HIGH - causes mismatches |
| MLFeatureStoreProcessor | ❌ No | MEDIUM |

**Root Cause:** OddsApiPropsProcessor uses `normalize_name()` directly without alias resolution:
```python
# data_processors/raw/oddsapi/odds_api_props_processor.py:482
'player_lookup': normalize_name(player_name)  # No registry lookup!
```

**Recommended Fix:**
```python
from shared.utils.player_registry import RegistryReader

class OddsApiPropsProcessor:
    def __init__(self):
        self.registry = RegistryReader(source_name='odds_api_props')

    def _resolve_player_lookup(self, player_name):
        raw_lookup = normalize_name(player_name)
        uid = self.registry.get_universal_id(raw_lookup, required=False)
        if uid:
            return uid.rsplit('_', 1)[0]  # Extract canonical lookup
        return raw_lookup
```

### Registry Data Quality Issue

**Finding:** Same player has multiple registry entries with different IDs.

```sql
SELECT player_lookup, universal_player_id
FROM nba_players_registry
WHERE player_lookup IN ('garytrent', 'garytrentjr');

-- Result:
-- garytrent   → garytrent_001
-- garytrentjr → garytrentjr_001  -- Different ID for same player!
```

This violates the registry contract. Need to consolidate these entries.

### Monitoring Gaps

**No Cloud Monitoring alert policies configured for:**
- DML rate limit errors
- Prediction coverage drops
- Write latency spikes
- Consolidation failures

**Recommended:** Create alert policies in Cloud Monitoring console.

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_MAX_INSTANCES` | 20 | Max Cloud Run instances |
| `WORKER_CONCURRENCY` | 5 | Concurrent requests per instance |
| `WORKER_EMERGENCY_MODE` | false | Use reduced concurrency (4×3) |
| `SELF_HEALING_DML_BACKOFF_ENABLED` | true | Enable exponential backoff |
| `SELF_HEALING_DML_MAX_RETRIES` | 3 | Max retry attempts |
| `SELF_HEALING_ALERT_ON_DML_LIMIT` | true | Send alerts on DML errors |
| `SELF_HEALING_AUTO_REDUCE_CONCURRENCY` | true | Auto-reduce on errors |

### Config Dataclasses

See `shared/config/orchestration_config.py`:
- `WorkerConcurrencyConfig` - concurrency settings with emergency mode
- `SelfHealingConfig` - alerting thresholds and backoff settings

---

## Files Changed This Session

### New Files
```
predictions/worker/batch_staging_writer.py     # 20 KB - Staging write pattern
predictions/worker/write_metrics.py            # Updated with alerting
predictions/coordinator/coverage_monitor.py    # 17 KB - Coverage monitoring
```

### Modified Files
```
predictions/worker/worker.py                   # Staging integration
predictions/coordinator/coordinator.py         # Consolidation + coverage
docker/predictions-worker.Dockerfile           # New file copies
bin/predictions/deploy/deploy_prediction_worker.sh  # Configurable concurrency
shared/config/orchestration_config.py          # New config classes
```

### Documentation
```
docs/08-projects/current/prediction-coverage-fix/
├── README.md                  # Updated with all solutions
├── PROGRESS-LOG.md            # Updated with session progress
├── INVESTIGATION-REPORT.md    # Original investigation
├── PLAYER-NAME-INVESTIGATION.md  # Registry gaps
├── SOLUTION-OPTIONS.md        # Solution approaches
├── DEEP-ANALYSIS.md           # Technical deep dive
└── IMPLEMENTATION-PLAN.md     # Implementation details
```

---

## Potential Issues to Watch For

### 1. Staging Table Cleanup

If consolidation fails, staging tables may be left behind. The `BatchConsolidator` has `cleanup_orphaned_staging_tables()` for this:

```python
# Clean up staging tables older than 24 hours
consolidator.cleanup_orphaned_staging_tables(max_age_hours=24)
```

### 2. Consolidation Timing

The consolidation happens in `publish_batch_summary()` which is called when `current_tracker.is_complete`. If workers hang, consolidation may not run.

Check with:
```bash
# Look for "Consolidation complete" or "Consolidation failed"
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-coordinator" AND textPayload=~"Consolidation"' --limit=20
```

### 3. Emergency Mode Not Automatic

The concurrency reduction is currently manual. If DML errors occur, someone needs to run:
```bash
gcloud run services update prediction-worker \
  --max-instances=4 --concurrency=3 --region=us-west2
```

Future improvement: Auto-reduce via Cloud Run API when threshold exceeded.

### 4. Aliases Not Used Yet

The 7 aliases were added to the database, but they won't take effect until:
1. The odds processor is updated to use the registry (P2)
2. OR the context processor resolves them when building context

Currently, the aliases exist but the odds data still uses the original names.

---

## Things to Investigate Further

### 1. Why Do Some Players Have No Context?

15 players had odds but were NOT_IN_CONTEXT. Possible reasons:
- Not on active roster
- Too few minutes projection
- Schedule data missing

```sql
-- Find players with odds but no context
WITH props AS (
  SELECT DISTINCT player_lookup FROM nba_raw.odds_api_player_points_props
  WHERE game_date = '2025-12-30'
),
context AS (
  SELECT DISTINCT player_lookup FROM nba_analytics.upcoming_player_game_context
  WHERE game_date = '2025-12-30'
)
SELECT p.player_lookup
FROM props p
LEFT JOIN context c ON p.player_lookup = c.player_lookup
WHERE c.player_lookup IS NULL;
```

### 2. Consolidation Performance

With 100+ staging tables, the MERGE query could be slow. Monitor:
- How long does consolidation take?
- Does it hit any timeouts?
- Is the query efficient?

### 3. Staging Table Naming Collisions

Staging tables use `_staging_{batch_id}_{worker_id}`. If batch_id is reused (e.g., force re-run), old staging tables might interfere.

### 4. Coverage vs Write Success

The fix should improve write success, but coverage depends on more factors:
- Feature quality
- Min minutes threshold
- Circuit breaker state
- Model errors

Need to distinguish between:
- Predictions generated but not written (DML issue - fixed)
- Predictions not generated (upstream issue)

---

## Quick Reference Commands

### Check Current State
```bash
# Current concurrency
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.metadata.annotations.'autoscaling.knative.dev/maxScale', spec.template.spec.containerConcurrency)"

# Dec 30 predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as preds, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-30' AND is_active = TRUE GROUP BY 1"

# Staging tables (should be empty)
bq query --use_legacy_sql=false "
SELECT table_id FROM \`nba-props-platform.nba_predictions.__TABLES__\`
WHERE table_id LIKE '_staging_%'"
```

### Emergency Actions
```bash
# Reduce concurrency
gcloud run services update prediction-worker \
  --max-instances=4 --concurrency=3 --region=us-west2

# Force re-run predictions
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-30", "force": true}'

# Check logs for errors
gcloud logging read 'severity>=ERROR AND resource.labels.service_name=~"prediction"' \
  --limit=20 --format="table(timestamp,textPayload)"
```

### Dashboard
```
https://nba-admin-dashboard-756957797294.us-west2.run.app/dashboard?key=d223a00eed9fb9c44620f88a572fd4c6
```

---

## For the Next Chat

**Start with:**
```
Read the handoff doc and continue:
docs/09-handoff/2025-12-30-EARLY-MORNING-HANDOFF.md
```

**Immediate priorities:**
1. **TEST THE FIX** - Trigger Dec 30 predictions and verify staging pattern works
2. Monitor logs for consolidation success/failure
3. Verify all 60 players get predictions (not just 30-40)

**Key context:**
1. Fix is deployed but untested
2. Current concurrency: 4×3=12 (reduced for safety)
3. Dec 30 has 2 games, 60 players - good test case
4. If staging pattern works, can increase concurrency back to 20×5=100

**If something breaks:**
1. Check logs for "Consolidation failed" or "DML"
2. Check for orphaned staging tables
3. Fall back to direct MERGE by reverting worker.py changes
4. Reduce concurrency further if needed

---

*Handoff created: December 30, 2025 01:45 AM ET*
