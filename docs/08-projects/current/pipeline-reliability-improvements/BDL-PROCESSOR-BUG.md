# BDL Player Box Scores Processor Bug: 0 Rows Inserted

**Date Discovered:** 2026-01-01
**Severity:** HIGH
**Status:** UNDER INVESTIGATION 🔍
**Affected Data:** Nov 10-12 backfill (35,991 player box scores)

---

## Summary

The BDL player box scores processor successfully receives data from Pub/Sub, processes the file, but inserts 0 rows into BigQuery. The processor returns "success" status with no errors, making this a silent failure.

---

## Impact

### Data Loss
- **Nov 10-12**: 35,991 player box scores scraped, 0 loaded to BigQuery
- **Dec 30**: Partial data loaded (unclear source/mechanism)
- **Earlier dates**: Unknown - needs verification

### Detection Lag
- Backfill ran: 2026-01-01 ~03:30 UTC
- Data should have loaded: 2026-01-01 ~03:35 UTC
- Bug discovered: 2026-01-01 ~10:15 UTC
- **Detection lag: ~7 hours**

### Silent Failure Pattern
- ✅ Scraper: Success (35,991 rows fetched from BDL API)
- ✅ GCS Upload: Success (45 MB file saved)
- ✅ Pub/Sub: Success (message published)
- ✅ Processor: Returns HTTP 200 "success"
- ❌ BigQuery: 0 rows inserted

---

## Investigation Log

### Timeline

| Time (UTC) | Event | Result |
|------------|-------|--------|
| 03:30 | Backfill script started for Nov 10-12 | ✅ Success |
| 03:35 | Data scraped: 35,991 player box scores | ✅ Success |
| 03:35 | GCS file saved: `ball-dont-lie/player-box-scores/2026-01-01/20260101_100708.json` (45 MB) | ✅ Success |
| 03:35 | Pub/Sub message published (ID: 17694147003159020) | ✅ Success |
| 10:14 | Phase 2 processor triggered (initial) | ❌ 0 rows processed |
| 10:45 | Cleanup processor retry #1 | ❌ 0 rows processed |
| 11:00 | Cleanup processor retry #2 | ❌ 0 rows processed |

### Findings

#### 1. File Structure is Correct
```bash
gsutil cat gs://.../20260101_100708.json | python3 -m json.tool | head -50

{
  "startDate": "2025-11-10",
  "endDate": "2025-11-12",
  "datesProcessed": ["2025-11-11", "2025-11-12"],
  "timestamp": "2026-01-01T10:13:42.765513+00:00",
  "rowCount": 35991,
  "stats": [
    {
      "id": 21539577,
      "min": "38",
      "pts": 19,
      "player": {...},
      "team": {...},
      "game": {...}
    },
    ...
  ]
}
```

✅ File contains 35,991 records in correct format

#### 2. Processor Routing Works
Checked processor logs:
```
INFO: Successfully processed ball-dont-lie/player-box-scores/.../20260101_100708.json:
  {'rows_processed': 0, 'rows_failed': 0, 'run_id': 'c68a68e7', 'total_runtime': 0}
```

✅ Processor received file and ran
❌ But inserted 0 rows

#### 3. Processor Registry is Correct
```python
PROCESSOR_REGISTRY = {
    'ball-dont-lie/player-box-scores': BdlPlayerBoxScoresProcessor,  # ✅ Registered
    ...
}
```

✅ Path matches, processor invoked

#### 4. Comparison with Working File (Dec 30)

**Dec 30 file (WORKED - 141 players loaded):**
```json
{
  "startDate": "2025-12-30",
  "endDate": "2025-12-30",
  "datesProcessed": [],  // ← EMPTY
  "rowCount": 457,
  "stats": [...]
}
```

**Nov 10-12 file (FAILED - 0 players loaded):**
```json
{
  "startDate": "2025-11-10",
  "endDate": "2025-11-12",
  "datesProcessed": ["2025-11-11", "2025-11-12"],  // ← POPULATED
  "rowCount": 35991,
  "stats": [...]
}
```

**Key difference:** `datesProcessed` field populated in multi-date scrapes

#### 5. Processor Code Analysis
```python
class BdlPlayerBoxScoresProcessor(SmartIdempotencyMixin, ProcessorBase):
    def transform_data(self) -> None:
        raw_data = self.raw_data
        file_path = raw_data.get('metadata', {}).get('source_file', 'unknown')
        rows = []

        stats = raw_data.get('stats', [])
        logger.info(f"Processing {len(stats)} stat rows from {file_path}")

        # Group stats by game...
        games_data = {}
        for stat in stats:
            game = stat.get('game', {})
            team = stat.get('team', {})
            player = stat.get('player', {})

            if not game or not team or not player:
                skipped_count += 1
                continue
            # ... build rows ...
```

**No obvious bug found in code inspection**

---

## Hypotheses

### Hypothesis 1: Smart Idempotency Blocking ⭐ LIKELY
**Theory:** Nov data already exists with different hash, blocking insert

**Evidence:**
- Dec 30 loaded despite similar format
- Smart idempotency uses hash of specific fields
- Nov backfill may have run before with different data

**Test:** Check `nba_raw.bdl_player_boxscores` for Nov data
```sql
SELECT COUNT(*)
FROM nba_raw.bdl_player_boxscores
WHERE game_date IN ('2025-11-10', '2025-11-11', '2025-11-12')
```
**Result:** 0 rows ❌ (no existing data to conflict)

**Status:** RULED OUT

### Hypothesis 2: datesProcessed Field Triggers Different Code Path
**Theory:** Multi-date scrapes handled differently

**Evidence:**
- Dec 30: `datesProcessed: []` → 141 rows loaded ✅
- Nov 10-12: `datesProcessed: [...]` → 0 rows loaded ❌

**Test:** Local processor test needed

**Status:** NEEDS INVESTIGATION

### Hypothesis 3: Validation Silently Rejecting Rows
**Theory:** Validation logic rejects all rows without logging

**Evidence:**
- No validation errors in logs
- Processor returns "success"
- 0 rows processed, 0 rows failed

**Test:** Add debug logging to validation

**Status:** NEEDS INVESTIGATION

### Hypothesis 4: Transform Loop Never Executes
**Theory:** Code path exits early before processing stats

**Evidence:**
- `transform_data()` runs but produces no output
- No logged errors or exceptions
- Stats array exists with 35,991 records

**Test:** Step through transform logic locally

**Status:** NEEDS INVESTIGATION

---

## Reproduction Steps

### 1. Download Test File
```bash
gsutil cp gs://nba-scraped-data/ball-dont-lie/player-box-scores/2026-01-01/20260101_100708.json /tmp/test_bdl.json
```

### 2. Run Processor Locally
```python
from data_processors.raw.balldontlie.bdl_player_box_scores_processor import BdlPlayerBoxScoresProcessor

processor = BdlPlayerBoxScoresProcessor()
opts = {
    'bucket': 'nba-scraped-data',
    'file_path': 'ball-dont-lie/player-box-scores/2026-01-01/20260101_100708.json',
    'project_id': 'nba-props-platform'
}

result = processor.run(opts)
print(f"Result: {result}")
```

### 3. Observe Behavior
- Expected: Errors or validation messages
- Actual: "Success" with 0 rows

### 4. Add Debug Logging
```python
# In transform_data():
print(f"Stats array length: {len(stats)}")
print(f"First stat: {stats[0] if stats else 'EMPTY'}")

for stat in stats:
    game = stat.get('game', {})
    team = stat.get('team', {})
    player = stat.get('player', {})
    print(f"Processing: player={bool(player)}, team={bool(team)}, game={bool(game)}")

    if not game or not team or not player:
        print(f"  SKIPPED: missing data")
        continue
```

---

## Comparison: Same Bug Pattern as Gamebook Processor

### Similarities
1. ✅ Processor returns "success"
2. ❌ 0 rows inserted
3. 📁 Files exist in GCS with correct data
4. 🔄 Pub/Sub messages processed
5. 🤐 Silent failure (no errors logged)

### Differences
- **Gamebook:** IndexError (fixed)
- **BDL:** Unknown (still investigating)

### Pattern Recognition
**Both processors:**
- Run without exceptions
- Return HTTP 200 OK
- Log "success" message
- Insert 0 rows to BigQuery
- Provide no indication of failure

**This suggests a systemic issue in error handling/validation**

---

## Next Steps

### Investigation
- [ ] Run processor locally with debug logging
- [ ] Step through `transform_data()` line by line
- [ ] Check if validation is rejecting rows
- [ ] Verify smart idempotency logic
- [ ] Compare working vs failing file processing

### Testing
- [ ] Test with Dec 30 file (known working)
- [ ] Test with Nov file (known failing)
- [ ] Compare execution paths
- [ ] Identify where divergence occurs

### Fix
- [ ] Once root cause identified, implement fix
- [ ] Add validation logging
- [ ] Deploy updated processor
- [ ] Re-process Nov 10-12 data

---

## Monitoring Gaps

### What Failed to Detect This
1. **No completeness checks** - Missing 35K rows went unnoticed
2. **No 0-row alerts** - "Success" with 0 rows is suspicious
3. **No validation logging** - Can't tell why rows were skipped
4. **No automated backfill** - Manual intervention required

### What We're Adding
1. ✅ Daily completeness checker (Phase 1)
2. ✅ Alert on 0-row results (Phase 2)
3. ✅ Enhanced validation logging (Phase 2)
4. 🔄 Auto-backfill workflow (Phase 3)

---

## Workarounds

### Option 1: Re-scrape with Different Parameters
```bash
# Try single-date scrapes instead of date range
PYTHONPATH=. python3 scrapers/balldontlie/bdl_player_box_scores.py \
  --startDate 2025-11-10 \
  --endDate 2025-11-10 \
  --group gcs
```

### Option 2: Manual BigQuery Load
```bash
# Download file, transform locally, load to BigQuery
# (Last resort - time-consuming)
```

### Option 3: Wait for Fix
- Investigate root cause
- Deploy fix
- Re-process automatically

**Recommendation:** Option 3 (proper fix)

---

## Related Issues
- [Gamebook Processor Bug](./GAMEBOOK-PROCESSOR-BUG.md) - Similar pattern
- [Session Summary](./SESSION-JAN1-PM-DATA-GAPS.md) - Full investigation
- [Monitoring Implementation](./MONITORING-IMPLEMENTATION.md) - Prevention system

---

## Status: INVESTIGATION ONGOING 🔍

**Priority:** HIGH (data gap exists)
**Blocker:** Need to understand root cause before fix
**Next Action:** Local debugging with step-through execution
