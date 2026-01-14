# ESPN Roster Batch Mode Implementation Handoff

**Date:** 2026-01-09
**Session Focus:** Fix BigQuery serialization conflicts for ESPN roster processing
**Status:** COMPLETE - Deployed and tested

---

## Executive Summary

Fixed a recurring BigQuery serialization conflict error for ESPN roster processing by implementing batch mode with a Firestore distributed lock. This eliminates concurrent write conflicts by ensuring only ONE processor handles all 30 teams per date.

**Result:** 30 individual DELETE+INSERT operations → 1 batch operation (96.7% reduction)

---

## The Problem

### Error Received
```
Error: Could not serialize access to table nba-props-platform:nba_raw.espn_team_rosters
       due to concurrent update
Processor: EspnTeamRosterProcessor
```

### Root Cause
1. ESPN roster scraper runs for all 30 teams in sequence
2. Each team file triggers a Pub/Sub message
3. 30 processors start nearly simultaneously
4. All 30 try to DELETE + INSERT on the same table
5. BigQuery serialization conflicts occur

### Architecture Before
```
Scraper → 30 files → 30 Pub/Sub messages → 30 processors → 30 DELETE + 30 INSERT → CONFLICTS
```

### Architecture After
```
Scraper → 30 files → 30 Pub/Sub messages → First wins lock → 1 batch processor → 1 DELETE + 1 INSERT
                                         → Other 29 skip (ACK immediately)
```

---

## Changes Made

### 1. Firestore Lock Pattern (`main_processor_service.py`)

**Lines 727-815:** Added ESPN roster batch handling with distributed lock

```python
# When ESPN roster file message arrives:
lock_id = f"espn_roster_batch_{roster_date}"
lock_ref = db.collection('batch_processing_locks').document(lock_id)

# Try to create lock (atomic - fails if exists)
lock_ref.create({
    'status': 'processing',
    'started_at': datetime.now(timezone.utc),
    'expireAt': datetime.now(timezone.utc) + timedelta(days=7)  # TTL
})

# If we got lock → run batch processor for ALL 30 teams
# If lock exists → return 200 "skipped" (another processor handling it)
```

### 2. Retry Logic (`espn_team_roster_processor.py`)

Added `@SERIALIZATION_RETRY` decorator to all BigQuery operations as defense-in-depth:
- `_fast_partition_replace()` DELETE
- `_fast_partition_replace()` INSERT
- `_batch_delete_partitions()` DELETE
- `batch_process_rosters()` INSERT

### 3. Fixed Attribute Name Bug

Changed `processor.storage_client` → `processor.gcs_client` in batch mode (ProcessorBase uses `gcs_client`)

### 4. Firestore TTL Policy

- Added `expireAt` field to lock documents (7 days from creation)
- Enabled TTL policy on `batch_processing_locks` collection
- Locks auto-delete after 7 days

### 5. Dependencies

Added `google-cloud-firestore>=2.11.0` to `shared/requirements.txt`

---

## Commits

| Commit | Description |
|--------|-------------|
| `e808d14` | Add batch mode with Firestore lock for ESPN rosters |
| `8dd8914` | Add google-cloud-firestore dependency |
| `4960861` | Fix gcs_client attribute name in batch mode |
| `6c706fe` | Add TTL expiration (7 days) to batch processing locks |
| `f9593ee` | Document batch processing mode in processors.md |

---

## Deployment

**Service:** `nba-phase2-raw-processors`
**Region:** us-west2
**Current Revision:** `nba-phase2-raw-processors-00083-lwn`

---

## Test Results

### Batch Processing Test
```
First message: Acquired lock, processed all 30 teams
  - teams_loaded: 30
  - players_loaded: 527
  - errors: 0
  - Duration: ~1.5 minutes

Second message: Detected lock, skipped
  - Response: {"status":"skipped","reason":"batch_already_processing"}
  - Duration: ~200ms
```

### Firestore Lock Document
```json
{
  "status": "complete",
  "teams_loaded": 30,
  "players_loaded": 527,
  "errors": 0,
  "started_at": "2026-01-09T05:26:24Z",
  "completed_at": "2026-01-09T05:28:02Z",
  "expireAt": "2026-01-16T05:26:24Z"
}
```

---

## Analysis: Other Processors

Analyzed whether other processors need similar batch mode:

### Don't Need Batch Mode
- **MLB Props** - Uses APPEND_ALWAYS (no DELETE), snapshots spread throughout day
- **ESPN Boxscores** - Games finish at different times, natural separation
- **Single-file processors** - Already efficient (BDL, NBA.com player boxscores)

### Already Have Batch Mode
- **ESPN Rosters** - ✅ Implemented this session
- **Basketball Reference Rosters** - ✅ Already had batch processor

### Key Insight
The batch mode fix was necessary specifically because:
1. All 30 teams scraped in one workflow run
2. DELETE + INSERT operations (MERGE_UPDATE strategy)
3. All hitting the same table partition simultaneously

Processors using APPEND_ALWAYS or naturally time-separated don't have this issue.

---

## Monitoring

### Firestore Collection
- Collection: `batch_processing_locks`
- Documents: One per date (e.g., `espn_roster_batch_2026-01-09`)
- TTL: 7 days automatic cleanup

### Logs to Watch
```
🔒 Acquired batch lock for ESPN rosters {date}  → First processor won
🔓 ESPN roster batch for {date} already being processed  → Subsequent processors skipped
✅ ESPN roster batch complete for {date}  → Success
❌ ESPN roster batch failed for {date}  → Failure (check stats)
```

---

## Files Modified

| File | Changes |
|------|---------|
| `data_processors/raw/main_processor_service.py` | Added Firestore lock pattern for ESPN rosters |
| `data_processors/raw/espn/espn_team_roster_processor.py` | Added retry decorators, fixed gcs_client |
| `shared/requirements.txt` | Added google-cloud-firestore |
| `docs/06-reference/processors.md` | Documented batch processing mode |

---

## Future Considerations

1. **If serialization errors appear for other processors**, apply the same Firestore lock pattern
2. **Lock cleanup** is automatic via TTL - no maintenance needed
3. **The pattern is reusable** - just change lock_id prefix and call appropriate batch processor

---

## Session Duration

~2 hours including:
- Diagnosis and root cause analysis
- Implementation of batch mode
- Bug fixes (gcs_client, Firestore dependency)
- TTL setup
- Testing and deployment
- Analysis of other processors
- Documentation
