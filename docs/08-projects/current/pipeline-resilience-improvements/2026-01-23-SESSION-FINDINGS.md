# Session Findings: Jan 23, 2026 - Data Pipeline Issues

**Date:** 2026-01-23
**Status:** Active Investigation
**Priority:** P0/P1

## Executive Summary

During routine system monitoring, multiple critical issues were discovered affecting the betting lines data pipeline. These issues combined to prevent Jan 23 predictions from being generated with proper line data.

## Issues Discovered

### 1. Phase 2 Batch Processor Bug (P1 - HIGH)

**Problem:** The `OddsApiPropsBatchProcessor` only processes 1 of 16 files when triggered.

**Location:** `data_processors/raw/oddsapi/oddsapi_batch_processor.py`

**Symptoms:**
- GCS has 16 odds_api player-props files for Jan 23
- BigQuery only shows 27 records (should be 400+)
- Manual batch trigger returns `processed_files: 1`

**Root Cause:** Under investigation - likely iterator exhaustion or path matching issue.

**Workaround:** Clear Firestore lock and trigger manually with specific file path.

**Fix Needed:**
```python
# Investigate batch_processor.py batch file discovery logic
# Ensure all files matching pattern are processed
```

---

### 2. BettingPros Proxy Blocking (P1 - CRITICAL)

**Problem:** Both ProxyFuel AND Decodo proxies are now returning 403 from BettingPros.

**Location:** `scrapers/bettingpros/bp_*.py`

**Evidence:**
```
bettingpros_player_props - HTTP 403 errors, 11 occurrences
bettingpros_events - HTTP 403 errors, 1 occurrence
```

**Root Cause:** BettingPros has upgraded bot detection, blocking all known proxy IP ranges.

**Impact:**
- Jan 23 has ZERO bettingpros data in BigQuery
- Predictions rely 100% on odds_api which has fewer players

**Potential Solutions:**
1. Investigate BettingPros API key authentication (already have key)
2. Try different proxy region/provider
3. Increase reliance on odds_api as primary source
4. Consider scraping from alternate BettingPros endpoints

---

### 3. Firestore Lock Accumulation (P2 - MEDIUM)

**Problem:** Stale Firestore locks block batch processing indefinitely.

**Location:** `data_processors/raw/processor_base.py` (lock logic)

**Evidence:**
```
Deleted locks found:
- br_roster_batch_2025-26
- espn_roster_batch_2026-01-08
- odds_api_player_props_batch_2026-01-22
- odds_api_player_props_batch_2026-01-23
(12 total stale locks)
```

**Root Cause:** Failed batch runs don't release locks; locks have no TTL.

**Fix Implemented:** Manual lock cleanup script:
```python
from google.cloud import firestore
db = firestore.Client()
for doc in db.collection('batch_processing_locks').stream():
    doc.reference.delete()
```

**Permanent Fix Needed:**
1. Add TTL to locks (max 30 min)
2. Auto-cleanup on job failure
3. Alert on lock age > 15 min

---

### 4. Pub/Sub Retry Storm (P2 - MEDIUM)

**Problem:** Failed messages retry indefinitely, drowning new messages.

**Location:** `nba-phase2-raw-sub` subscription

**Evidence:**
- Messages with malformed gcs_path retrying continuously
- New valid messages delayed or lost
- Dead letter queue not catching all failures

**Fix Applied:** Subscription seek to current time:
```bash
gcloud pubsub subscriptions seek nba-phase2-raw-sub --time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

**Permanent Fix Needed:**
1. Increase dead letter max attempts (currently 5 -> 10)
2. Add message age validation in processor
3. Better message schema validation

---

### 5. Health Email Metrics Bug (P3 - LOW)

**Problem:** Daily health email shows incorrect phase completion stats.

**Location:** `monitoring/health_summary/main.py:214`

**Evidence:**
```
Phase 1 (Scrapers): 0/21  <- Always 0 because scrapers don't log to processor_run_history
Phase 2 (Raw): 1530/21   <- Uses success_count instead of distinct processor count
```

**Root Cause:** Query uses `SUM(success_count)` instead of `COUNT(DISTINCT processor_name)`.

**Fix Needed:**
```python
# Line ~214 in monitoring/health_summary/main.py
# Change: success_count -> COUNT(DISTINCT processor_name)
# Add: Separate logging for Phase 1 scrapers
```

---

## Data State Summary

### Jan 23, 2026 (Updated End of Session)

| Component | Expected | Actual | Status |
|-----------|----------|--------|--------|
| odds_api props | 400+ | 27 | GCS has data, BQ only partial |
| bettingpros props | 300+ | 0 | 403 errors, no data |
| Predictions (staging) | 81 players | 615 tables, 18,170 rows | Needs consolidation |
| Predictions (main) | 81 players | 0 | Batch stuck at 95% |

**Note:** The batch is stalled at 95% (77/81 players). 4 players are failing LINE QUALITY VALIDATION. The 18,170 predictions in staging need to be consolidated to become active.

### Jan 19-22 Historical

| Date | odds_api | bettingpros | Predictions |
|------|----------|-------------|-------------|
| Jan 19 | 0 | ~300 | Using BP only |
| Jan 20 | 0 | ~350 | Using BP only |
| Jan 21 | 0 | ~380 | Using BP only |
| Jan 22 | 0 | ~320 | Using BP only |

---

## Resolution Steps Taken

1. **Cleared Firestore locks** - Unblocked batch processing
2. **Cleared Pub/Sub backlog** - Allowed new messages to process
3. **Manually scraped Jan 23 events** - 8 events, 442 records to GCS
4. **Triggered Phase 2 batch** - Partial success (1 file processed)
5. **Started new prediction batch** - `batch_2026-01-23_1769180406`

---

## Recommendations for System Resilience

### Immediate (This Week)

1. **Fix Phase 2 batch processor** - Debug why only 1 file processed
2. **Add Firestore lock TTL** - Prevent indefinite locks
3. **Investigate BettingPros auth** - API key may bypass bot detection

### Short Term (Next Sprint)

4. **Enhance health email metrics** - Fix the counting bug
5. **Add self-heal monitoring** - Dashboard for regeneration actions
6. **Historical backfill** - Jan 19-22 odds_api data (use historical endpoint)

### Medium Term (Next Month)

7. **Pub/Sub message validation** - Reject malformed messages early
8. **Redundant line sources** - Add third source (DraftKings API?)
9. **Auto-recovery playbooks** - Document common failure modes

---

## Related Documents

- [Proxy Infrastructure](../proxy-infrastructure/README.md)
- [Line Quality Self-Healing](../line-quality-self-healing/README.md)
- [Data Cascade Architecture](../data-cascade-architecture/)

## Files Modified During Session

```
orchestration/cloud_functions/line_quality_self_heal/ (verified deployment)
```

## Commands Used

```bash
# Check prediction batch status
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key) && \
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=BATCH_ID" \
  -H "X-API-Key: $API_KEY"

# Clear Firestore locks
python3 -c "from google.cloud import firestore; db = firestore.Client(); [d.reference.delete() for d in db.collection('batch_processing_locks').stream()]"

# Clear Pub/Sub backlog
gcloud pubsub subscriptions seek nba-phase2-raw-sub --time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Trigger Phase 2 batch
TOKEN=$(gcloud auth print-identity-token) && \
curl -X POST "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"processor": "odds_api_props_batch", "date": "2026-01-23"}'
```
