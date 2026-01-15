# OddsAPI Batch Processing Implementation Plan

**Created:** 2026-01-14
**Status:** Pending Implementation
**Priority:** Medium (containerConcurrency reduction already helps)

---

## Problem

OddsAPI processors (OddsGameLinesProcessor, OddsApiPropsProcessor) are taking 60+ minutes due to:
1. **File Flood:** 14 files per scrape cycle (7 games x 2 endpoints)
2. **MERGE Contention:** Concurrent MERGE operations competing for BigQuery locks
3. **Resource Starvation:** Multiple processors fighting for CPU/memory

## Interim Fix Applied

Reduced `containerConcurrency` from 10 to 4 (revision 00091), which limits resource contention.

## Long-Term Fix: Batch Processing

Follow the pattern used for ESPN/BR rosters in `main_processor_service.py`:

### Pattern Overview

```python
# When first OddsAPI file arrives:
lock_id = f"oddsapi_batch_{game_date}"
lock_ref = db.collection('batch_processing_locks').document(lock_id)

try:
    # Atomic create - fails if lock exists
    lock_ref.create(lock_data)

    # Got lock - run batch processor for ALL files
    batch_processor = OddsApiBatchProcessor()
    batch_processor.run(...)

except AlreadyExists:
    # Another instance got the lock - skip
    return {"status": "skipped"}
```

### Files to Create

1. **`data_processors/raw/oddsapi/oddsapi_batch_processor.py`**
   - Process ALL OddsAPI files for a date in one operation
   - Single MERGE per table instead of 14 individual MERGEs
   - Pattern: See `br_roster_batch_processor.py`

2. **`data_processors/raw/oddsapi/oddsapi_game_lines_batch_processor.py`**
   - Batch processor specifically for game-lines

3. **`data_processors/raw/oddsapi/oddsapi_props_batch_processor.py`**
   - Batch processor specifically for player-props

### Changes to main_processor_service.py

Add before the PROCESSOR_REGISTRY lookup (around line 870):

```python
# ============================================================
# ODDSAPI BATCH PROCESSING
# When multiple OddsAPI files arrive, use Firestore lock to ensure
# only ONE instance processes the batch, preventing MERGE contention
# ============================================================
if 'odds-api/game-lines' in file_path or 'odds-api/player-props' in file_path:
    # Extract date from path: odds-api/game-lines/2026-01-14/...
    date_match = re.search(r'odds-api/[^/]+/(\d{4}-\d{2}-\d{2})/', file_path)
    if date_match:
        game_date = date_match.group(1)
        endpoint_type = 'game-lines' if 'game-lines' in file_path else 'player-props'
        lock_id = f"oddsapi_{endpoint_type}_batch_{game_date}"

        try:
            db = firestore.Client()
            lock_ref = db.collection('batch_processing_locks').document(lock_id)

            lock_data = {
                'status': 'processing',
                'started_at': datetime.now(timezone.utc),
                'trigger_file': file_path,
                'expireAt': datetime.now(timezone.utc) + timedelta(hours=2)
            }

            lock_ref.create(lock_data)

            # Got lock - run batch processor
            if endpoint_type == 'game-lines':
                batch_processor = OddsApiGameLinesBatchProcessor()
            else:
                batch_processor = OddsApiPropsBatchProcessor()

            success = batch_processor.run({
                'bucket': bucket,
                'game_date': game_date,
                'project_id': os.environ.get('GCP_PROJECT_ID')
            })

            lock_ref.update({
                'status': 'complete' if success else 'failed',
                'completed_at': datetime.now(timezone.utc)
            })

            return jsonify({"status": "success", "mode": "batch"}), 200

        except Exception as e:
            if 'already exists' in str(e).lower():
                return jsonify({"status": "skipped", "reason": "batch_processing"}), 200
            raise
```

### Batch Processor Logic

```python
class OddsApiGameLinesBatchProcessor:
    """Process all game-lines files for a date in one batch."""

    def run(self, opts):
        game_date = opts['game_date']
        bucket = opts['bucket']

        # List all game-lines files for the date
        prefix = f"odds-api/game-lines/{game_date}/"
        blobs = list(storage_client.list_blobs(bucket, prefix=prefix))

        # Read and combine all files
        all_rows = []
        for blob in blobs:
            data = json.loads(blob.download_as_string())
            all_rows.extend(self._transform(data))

        # Single MERGE operation (instead of 14)
        self._batch_merge(all_rows, game_date)

        return True
```

## Benefits

| Metric | Before | After |
|--------|--------|-------|
| MERGE Operations | 14 per scrape | 1-2 per scrape |
| Processing Time | 60+ minutes | <5 minutes |
| BigQuery Contention | High | Low |
| Stuck Processors | Frequent | Rare |

## Risk Assessment

- **Low Risk:** Pattern is proven with ESPN/BR rosters
- **Rollback:** Firestore lock can be deleted to fall back to individual processing
- **Testing:** Can be tested with a single date before full rollout

---

## Implementation Steps

1. [ ] Create `OddsApiGameLinesBatchProcessor` class
2. [ ] Create `OddsApiPropsBatchProcessor` class
3. [ ] Add batch processing section to `main_processor_service.py`
4. [ ] Test with a single date
5. [ ] Deploy and monitor
6. [ ] Document results
