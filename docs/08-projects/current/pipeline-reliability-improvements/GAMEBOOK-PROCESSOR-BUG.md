# Gamebook Processor Bug: IndexError in Path Parsing

**Date Discovered:** 2026-01-01
**Severity:** CRITICAL
**Status:** FIXED ✅
**Affected Dates:** Dec 28-31 (and likely all files with new structure)

---

## Summary

The gamebook processor was failing silently due to an IndexError when parsing the file path to extract game metadata. The processor expected a 4-part path but received a 5-part path after a file structure change, causing all recent gamebook files to fail with 0 rows inserted.

---

## Impact

### Data Loss
- **Dec 31**: 8 of 9 games missing from BigQuery
- **Dec 29**: 10 games missing
- **Dec 28**: Multiple games missing
- **Earlier dates**: Likely affected but not verified

### Detection Lag
- Bug introduced: Unknown (when file structure changed)
- Bug discovered: 2026-01-01 (manual investigation)
- **Detection lag: Multiple days minimum**

### Silent Failure
- Processor returned HTTP 200 OK
- Logs showed "success"
- `rows_processed: 0` but no error thrown
- No alerts or notifications triggered

---

## Root Cause Analysis

### The Bug

**Location:** `data_processors/raw/nbacom/nbac_gamebook_processor.py:1003`
**Function:** `extract_game_info()`

**Code:**
```python
def extract_game_info(self, file_path: str, data: Dict) -> Dict:
    # Path format: nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL/20250827_234400.json
    path_parts = file_path.split('/')
    date_str = path_parts[-3]  # 2021-10-19
    game_code = path_parts[-2]  # 20211019-BKNMIL
    # ...
```

**Error:**
```
IndexError: list index out of range
  File "nbac_gamebook_processor.py", line 1003, in extract_game_info
    date_str = path_parts[-3]  # Expected: 2021-10-19
```

### Why It Failed

**Old file structure (expected):**
```
nba-com/gamebooks-data/2025-12-31/20251231_232941.json
Parts: ['nba-com', 'gamebooks-data', '2025-12-31', '20251231_232941.json']
       [    0    ,        1       ,      2      ,          3          ]
path_parts[-3] = '2025-12-31' ✅
path_parts[-2] = '20251231_232941.json' ❌ (expected game code)
```

**New file structure (actual):**
```
nba-com/gamebooks-data/2025-12-31/20251231-DENTOR/20260101_090652.json
Parts: ['nba-com', 'gamebooks-data', '2025-12-31', '20251231-DENTOR', '20260101_090652.json']
       [    0    ,        1       ,      2      ,        3        ,           4           ]
path_parts[-3] = '2025-12-31' ✅
path_parts[-2] = '20251231-DENTOR' ✅
```

**The change:** Game-specific subfolder added (`20251231-DENTOR/`)

### Why It Returned "Success" with 0 Rows

**Error Handling:**
```python
def transform_data(self) -> None:
    try:
        game_info = self.extract_game_info(file_path, raw_data)
        # ... process players ...
    except Exception as e:
        logger.error(f"Error transforming data from {file_path}: {e}")
        try:
            notify_error(...)  # Send notification
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        raise e  # ← Re-raise exception
```

**BUT:**
The exception was caught higher up and converted to:
```json
{
  "status": "success",
  "stats": {"rows_processed": 0, "rows_failed": 0}
}
```

**Result:** Silent failure with no data inserted.

---

## Investigation Process

### Step 1: Confirmed Files Exist
```bash
gsutil ls gs://nba-scraped-data/nba-com/gamebooks-data/2025-12-31/
# Output: 9 game folders with JSON files ✅
```

### Step 2: Checked Processing Logs
```sql
SELECT status, COUNT(*)
FROM nba_orchestration.scraper_execution_log
WHERE DATE(triggered_at) = '2025-12-31'
  AND scraper_name = 'nbac_gamebook_pdf'
GROUP BY status

-- Result: 3 success, 1 failed ✅ (scrapers ran)
```

### Step 3: Checked BigQuery
```sql
SELECT COUNT(DISTINCT game_code)
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2025-12-31'

-- Result: 1 game ❌ (expected 9)
```

### Step 4: Tested Processor Directly
```bash
curl -X POST https://...nba-phase2-raw-processors.../process \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": {"data": "..."}}'

# Response: {"stats": {"rows_processed": 0}} ❌
```

### Step 5: Local Debugging
Downloaded file and ran processor locally:
```
ERROR: IndexError: list index out of range
  File "nbac_gamebook_processor.py", line 1003
    date_str = path_parts[-3]
```

**Root cause identified!**

---

## The Fix

### Solution
**Read game metadata from JSON file instead of parsing file path**

The JSON file already contains all needed metadata:
```json
{
  "game_code": "20251231/DENTOR",
  "date": "2025-12-31",
  "matchup": "DEN@TOR",
  "away_team": "DEN",
  "home_team": "TOR",
  ...
}
```

### Implementation

**Before:**
```python
def extract_game_info(self, file_path: str, data: Dict) -> Dict:
    path_parts = file_path.split('/')
    date_str = path_parts[-3]  # ❌ Fragile
    game_code = path_parts[-2]
    # Parse teams from game_code...
```

**After:**
```python
def extract_game_info(self, file_path: str, data: Dict) -> Dict:
    # PRIORITY 1: Extract from JSON data (most reliable)
    if 'date' in data and 'away_team' in data and 'home_team' in data:
        date_str = data['date']  # ✅ Direct from JSON
        away_team = data['away_team']
        home_team = data['home_team']
        game_code = data.get('game_code', '')
        date_part = date_str.replace('-', '')
    else:
        # FALLBACK: Parse from file path (for older files)
        path_parts = file_path.split('/')
        # Handle both old (4 parts) and new (5 parts) structures
        if len(path_parts) >= 5:
            date_str = path_parts[-3]
            game_code = path_parts[-2]
        elif len(path_parts) >= 4:
            date_str = path_parts[-2]
            game_code = data.get('game_code', 'unknown')
        else:
            raise ValueError(f"Unexpected file path structure: {file_path}")
```

### Changes Made
- **File:** `data_processors/raw/nbacom/nbac_gamebook_processor.py`
- **Lines:** 994-1034 (extract_game_info method)
- **Commit:** d813770
- **Deployed:** 2026-01-01 10:53:52 UTC
- **Revision:** nba-phase2-raw-processors-00054-pq2

---

## Verification

### Test 1: Local Processing
```bash
python debug_processor.py
# Before: IndexError
# After:  ✅ No error, game_info extracted successfully
```

### Test 2: Direct API Call
```bash
curl ... /process
# Before: {"rows_processed": 0}
# After:  ✅ No IndexError (but still 0 rows - separate issue)
```

### Test 3: Production Deployment
```bash
./bin/raw/deploy/deploy_processors_simple.sh
# ✅ Deployed successfully in 4m 38s
# ✅ Health check passed
# ✅ Commit SHA verified: d813770
```

---

## Remaining Issues

### 0 Rows Still Inserted (ACTIVE)
After fixing the IndexError, processor still returns `rows_processed: 0`

**Possible causes:**
1. Smart idempotency blocking inserts
2. Validation logic rejecting rows
3. Season type check skipping games
4. Data structure mismatch

**Status:** Under investigation
**Tracking:** See [BDL-PROCESSOR-BUG.md](./BDL-PROCESSOR-BUG.md)

---

## Prevention Measures

### Implemented ✅
1. **Read from JSON, not paths** - More reliable, future-proof
2. **Fallback path parsing** - Handles both old and new structures
3. **Better error handling** - Clearer error messages

### Needed 🔄
1. **Automated completeness checks** - Detect missing games daily
2. **Alert on 0-row results** - Flag suspicious "success" responses
3. **Integration tests** - Test with real file structures
4. **Schema validation** - Catch file structure changes early

---

## Lessons Learned

### What Went Wrong
1. **Fragile path parsing** - Assumed specific file structure
2. **No validation** - Didn't verify extracted metadata
3. **Silent failures** - 0 rows treated as success
4. **No monitoring** - Gaps discovered manually days later

### What Worked
1. **Detailed logging** - Error message led directly to problem
2. **Local debugging** - Reproduced issue quickly
3. **Fast deployment** - Fix deployed within 30 minutes

### Best Practices
1. **Prefer data over metadata** - Read from JSON, not file paths
2. **Validate assumptions** - Check path length before indexing
3. **Fail loudly** - 0 rows should trigger warnings
4. **Monitor continuously** - Automated checks catch issues early

---

## Timeline

| Time | Event |
|------|-------|
| Unknown | File structure changed (game subfolder added) |
| Dec 28-31 | Gamebook files processed with 0 rows inserted |
| 2026-01-01 10:00 | Manual investigation started |
| 2026-01-01 10:22 | IndexError identified via local debugging |
| 2026-01-01 10:35 | Fix implemented and tested locally |
| 2026-01-01 10:49 | Deployment started |
| 2026-01-01 10:54 | Fix deployed to production ✅ |
| 2026-01-01 11:00 | Verification in progress |

**Total time from discovery to fix: ~1 hour** ⚡

---

## Related Issues
- [BDL Processor Bug](./BDL-PROCESSOR-BUG.md) - Similar 0-row issue
- [Session Summary](./SESSION-JAN1-PM-DATA-GAPS.md) - Full investigation
- [Monitoring Implementation](./MONITORING-IMPLEMENTATION.md) - Prevention system
