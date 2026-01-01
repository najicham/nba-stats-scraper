# Gamebook Processor: Run History Architectural Issue

**Date:** 2026-01-01
**Status:** 🔴 DOCUMENTED - Not Fixed Yet
**Priority:** Medium (will be caught by monitoring layers)
**Impact:** Prevents backfilling multiple games for same date

---

## Issue Summary

The gamebook processor has an architectural mismatch:
- **Processes:** One gamebook file = one game at a time
- **Run history tracks:** By date only, not by game_code
- **Result:** After first game for a date succeeds, all other games for that date are blocked

---

## Detailed Problem

### How Gamebook Processing Works

```
File structure:
  gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-MINATL/file.json
  gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-NYKSAS/file.json
  gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-DENTOR/file.json

Each file = ONE game
Multiple files per date = Multiple games per date
```

### How Run History Works

```python
# In run_history_mixin.py
def check_already_processed(self, processor_name: str, data_date: date):
    """Check if processor already ran for this DATE."""

    query = f"""
    SELECT status, run_id
    FROM nba_reference.processor_run_history
    WHERE processor_name = '{processor_name}'
      AND data_date = '{data_date}'  # ❌ Only checks DATE, not game_code
    """

    # If ANY run succeeded for this date → skip ALL future runs
    if row.status == 'success':
        return True  # Skip processing
```

### The Problem Sequence

```
1. Process 20251231-MINATL
   → Run history: NbacGamebookProcessor, data_date=2025-12-31, status=success ✅
   → Data loaded for MIN@ATL ✅

2. Try to process 20251231-NYKSAS
   → Run history check: "Already processed 2025-12-31" ❌
   → SKIPPED - no data loaded for NYK@SAS ❌

3. Try to process 20251231-DENTOR
   → Run history check: "Already processed 2025-12-31" ❌
   → SKIPPED - no data loaded for DEN@TOR ❌
```

**Result:** Only 1 game per date gets processed, rest are silently skipped.

---

## Evidence from Production

### Backfill Attempt on 2026-01-01

**Expected:** 26 games across 3 dates
- Dec 28: 6 games
- Dec 29: 10 games
- Dec 31: 8 games

**Actual Result:** Only 10 games loaded
- Dec 28: 4 games (67% missing)
- Dec 29: 3 games (70% missing)
- Dec 31: 3 games (63% missing)

**Missing:** 16 games (62% failure rate)

### Log Evidence

```
# First game for 2025-12-31 succeeded
INFO: Successfully processed 20251231-MINATL
INFO: Recorded run history: status=success, data_date=2025-12-31

# Second game blocked
INFO: Processor NbacGamebookProcessor already processed 2025-12-31
      with status 'success' (run_id: ...). Skipping duplicate.

# Third game blocked
INFO: Processor NbacGamebookProcessor already processed 2025-12-31
      with status 'success' (run_id: ...). Skipping duplicate.
```

---

## Root Cause Analysis

### Gamebook is Different from Other Processors

**Most processors** (BDL, ESPN, etc.):
- One file = all games for a date
- Processing by date makes sense
- Run history by date prevents re-processing entire day

**Gamebook processor**:
- One file = one specific game
- Multiple files per date is normal
- Run history by date blocks valid games

### Why This Wasn't Caught Earlier

1. **Normal operation:** Gamebooks are scraped once per game, processed immediately
   - Scraper creates ONE file per game
   - Processor runs immediately
   - No duplicate prevention needed

2. **Backfill scenario:** Need to process multiple games for same date
   - Scraper already created all files days ago
   - Trying to republish multiple games for same date
   - Run history blocks after first game ❌

3. **Silent failure:**
   - Processor returns HTTP 200 "success"
   - Logs say "Skipping duplicate" (looks intentional)
   - No alerts or errors
   - Detection lag = 10 hours (next morning's check)

---

## Impact Assessment

### Current Impact: Medium
- **Live processing:** ✅ Works fine (one game at a time)
- **Backfills:** ❌ Severely broken (only 38% success rate)
- **Detection:** ⏱️ 10-hour lag before we notice missing games
- **Workaround:** Delete run history before each backfill game (manual, tedious)

### Future Impact After Monitoring: Low
Once we deploy monitoring layers:
- **Layer 5:** Processor output validation catches "processed but 0 rows" immediately
- **Layer 6:** Real-time completeness check detects missing games in 2 minutes
- **Alert:** We know about the issue before users do
- **Manual fix:** Re-process specific missing games

---

## Proposed Solutions

### Solution A: Track by Game Code (Comprehensive Fix)

**Change run history to track game-level granularity for gamebook:**

```python
# In nbac_gamebook_processor.py

class NbacGamebookProcessor(RunHistoryMixin, ProcessorBase):

    def _get_run_history_key(self, opts: dict) -> dict:
        """Override to use game_code instead of date for deduplication."""

        # Extract game code from file path
        # gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-NYKSAS/file.json
        file_path = opts.get('file_path', '')
        parts = file_path.split('/')
        game_code_with_date = parts[-2]  # "20251231-NYKSAS"

        return {
            'processor_name': self.__class__.__name__,
            'data_date': opts['game_date'],  # Keep for partitioning
            'game_code': game_code_with_date,  # Add for uniqueness
        }

    def check_already_processed(self, opts: dict) -> bool:
        """Check if THIS SPECIFIC GAME already processed."""

        key = self._get_run_history_key(opts)

        query = f"""
        SELECT status
        FROM nba_reference.processor_run_history
        WHERE processor_name = '{key['processor_name']}'
          AND data_date = '{key['data_date']}'
          AND game_code = '{key['game_code']}'  # ✅ Check specific game
        """

        # Only skip if THIS GAME was processed, not just this date
```

**Pros:**
- ✅ Fixes backfills completely
- ✅ Accurate deduplication
- ✅ Works for all scenarios

**Cons:**
- ⏱️ Requires schema change to processor_run_history
- ⏱️ Need to handle backward compatibility
- ⏱️ ~4-6 hours to implement and test

---

### Solution B: Disable Run History for Gamebook (Quick Fix)

**Turn off run history deduplication for gamebook:**

```python
# In nbac_gamebook_processor.py

class NbacGamebookProcessor(ProcessorBase):  # Remove RunHistoryMixin

    # Don't use run history at all
    # Rely on smart idempotency at row level instead

    def run(self, opts):
        # Process every file
        # Smart idempotency prevents duplicate rows in BigQuery
        self.load_data()
        self.transform_data()
        self.save_data()  # Idempotency checks happen here
```

**Pros:**
- ✅ Quick to implement (~30 minutes)
- ✅ Fixes backfills immediately
- ✅ Smart idempotency already prevents duplicate data

**Cons:**
- ❌ More BigQuery queries (check duplicates every time)
- ❌ Slightly higher cost
- ❌ No tracking of "already processed" in run history

---

### Solution C: Monitor and Manual Fix (Current Approach)

**Deploy monitoring layers, fix issues manually when detected:**

1. Build **Layer 5: Processor Output Validation**
   - Catches "processed but 0 rows" immediately
   - Alerts within 1 second

2. Build **Layer 6: Real-Time Completeness Check**
   - Detects missing games within 2 minutes
   - Compares schedule vs actual data

3. When alert fires:
   - Manually delete run history for missing games
   - Re-trigger processing
   - Verify data loaded

**Pros:**
- ✅ Works for ALL processor issues, not just gamebook
- ✅ Builds infrastructure that prevents entire class of problems
- ✅ Catches issues before they impact users
- ✅ No code changes to gamebook processor needed right now

**Cons:**
- ❌ Requires manual intervention for gamebook backfills
- ❌ Doesn't fix root cause

---

## Recommendation

**Short-term (Today):** Solution C - Build monitoring layers
- Prevents this entire class of issues
- Detects problems in 2 minutes vs 10 hours
- Works for all processors
- **Time investment:** 6-8 hours
- **Value:** Prevents 100+ future issues

**Long-term (This Week):** Solution A - Fix run history architecture
- Proper fix for gamebook-specific issue
- **Time investment:** 4-6 hours
- **Value:** Fixes backfills permanently

---

## Detection Timeline

### Without Monitoring (Current)
```
9:30 PM - Game finishes
9:35 PM - Gamebook scraped
9:36 PM - First game processed ✅
9:37 PM - Other games silently skipped ❌
...
9:00 AM - Morning check detects missing games ⚠️
```
**Detection lag:** 10-12 hours

### With Layer 5 + 6 (After Implementation)
```
9:30 PM - Game finishes
9:35 PM - Gamebook scraped
9:36 PM - First game processed ✅
9:37 PM - Other games skipped ❌
9:37 PM - Layer 5: "Expected 35 rows, got 0" → Alert 🚨
9:40 PM - Layer 6: Real-time check finds missing game → Alert 🚨
9:42 PM - Manual intervention triggered
9:45 PM - Issue resolved ✅
```
**Detection lag:** 2 minutes

---

## Test Case for Future Fix

```python
def test_gamebook_multiple_games_same_date():
    """
    Verify gamebook can process multiple games for same date.
    This test currently FAILS due to run history blocking.
    """

    # Setup: 3 games on same date
    games = [
        'gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-MINATL/file.json',
        'gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-NYKSAS/file.json',
        'gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/20251231-DENTOR/file.json',
    ]

    # Process all 3
    for game_file in games:
        processor = NbacGamebookProcessor()
        result = processor.run({'file_path': game_file, 'game_date': '2025-12-31'})
        assert result['rows_processed'] > 0, f"Game {game_file} failed to process"

    # Verify all 3 games in BigQuery
    query = """
    SELECT COUNT(DISTINCT game_code) as game_count
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE game_date = '2025-12-31'
    """
    result = bq_client.query(query).result()
    game_count = list(result)[0].game_count

    assert game_count == 3, f"Expected 3 games, got {game_count}"
    # Currently FAILS: game_count = 1 (only first game processed)
```

---

## Related Issues

This architectural mismatch also affects:
1. **Manual re-processing:** Can't re-run single game without deleting run history
2. **Data corrections:** Can't fix one bad game without affecting whole date
3. **Testing:** Can't test specific games in isolation

---

## Next Steps

**Immediate (Today):**
- [x] Document this issue
- [ ] Build Layer 5: Processor Output Validation
- [ ] Build Layer 6: Real-Time Completeness Check
- [ ] Test with tonight's games

**This Week:**
- [ ] Implement Solution A (game-level run history)
- [ ] Add test case above
- [ ] Verify backfills work for multiple games per date

**Monitoring Will Catch This:**
Once monitoring is deployed, this issue becomes:
- **Visible:** 2-minute detection instead of 10 hours
- **Actionable:** Clear alert with specific missing games
- **Temporary:** Can manually fix while we implement proper solution

---

## Lessons Learned

### Why This Matters
This issue demonstrates the value of multi-layered monitoring:

1. **Silent failures are dangerous**
   - Processor returns HTTP 200
   - Logs look normal ("Skipping duplicate")
   - No errors or warnings
   - Data just quietly missing

2. **Detection lag compounds problems**
   - 10 hours before we notice
   - 62% of games missing
   - Manual backfill required

3. **Monitoring prevents entire class of issues**
   - Layer 5 catches unexpected 0-row results
   - Layer 6 detects missing data within minutes
   - Works for all processors, not just gamebook
   - **Prevention > Reaction**

### Investment Justification

**Time spent debugging this issue:** 2+ hours
**Similar issues likely:** 10-20 per year
**Total time saved by monitoring:** 20-40 hours/year

**Time to build monitoring:** 8-10 hours
**ROI:** Positive within 3-6 months

---

**Status:** Documented, not fixed. Monitoring layers being built to prevent future occurrences.
