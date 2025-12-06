# Session 45: Phase 3 Data Hash Backfill - Continuation Handoff

**Date:** 2025-12-05
**Session:** 45
**Status:** IN PROGRESS - First month validation 89.12% complete, UPGC running
**Objective:** Complete first month data_hash validation, then address historical backfill

---

## Executive Summary

### Current Situation

**First Month Validation (2021-10-19 to 2021-11-19):**

| Table | Total | With Hash | Coverage | Status |
|-------|-------|-----------|----------|--------|
| player_game_summary | 5,182 | 5,182 | **100%** | Complete |
| team_defense_game_summary | 1,802 | 1,802 | **100%** | Complete |
| team_offense_game_summary | 1,802 | 1,802 | **100%** | Complete |
| upcoming_team_game_context | 476 | 476 | **100%** | Complete |
| upcoming_player_game_context | 8,349 | 7,441 | **89.12%** | Running |

### Critical Discovery This Session

**The SQL-based historical backfill approach WILL NOT WORK.**

Previous sessions recommended using SQL to backfill data_hash values, expecting 15 minutes of runtime. Investigation revealed:

```python
# From data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py

def _calculate_data_hash(self, record: Dict) -> str:
    """Calculate SHA256 hash of meaningful analytics fields."""
    hash_values = {k: record.get(k) for k in self.DATA_HASH_FIELDS}
    hash_string = json.dumps(hash_values, sort_keys=True, default=str)
    return hashlib.sha256(hash_string.encode()).hexdigest()[:16]
```

**The hash is calculated from ALL 34+ analytics fields (sorted JSON, SHA256), NOT just key columns.**

This means:
- SQL cannot easily replicate the complex hash calculation
- Historical backfill **MUST** use processor-based approach
- Estimated runtime: **25-40 days** (not 15 minutes)

---

## Running Processes

### Active Backfill (Check First!)

**Process ID:** 920557

```bash
# Check if still running
ps aux | grep "upcoming_player_game_context.*2021-10-19" | grep -v grep

# View log
tail -50 /tmp/upgc_hash_backfill_nov.log | grep -E "(Processing date|✅)"
```

**Command Running:**
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper \
/home/naji/code/nba-stats-scraper/.venv/bin/python \
backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
--start-date 2021-10-19 --end-date 2021-11-19
```

---

## Issues Found (Session 45 Analysis)

### 1. Completeness Check Timeout (MEDIUM Severity)

**Location:** `shared/utils/completeness_checker.py`

**Issue:** BigQuery queries timing out after 600 seconds during historical data validation.

**Evidence:**
```
WARNING:Completeness check for l10 failed: Timeout of 600.0s exceeded
WARNING:Completeness check for l7d failed: Timeout of 600.0s exceeded
```

**Recommendations:**
- Increase timeout from 600s to 1200s for backfill scenarios
- Add partition pruning to queries: `WHERE _PARTITIONDATE >= '{start_date}'`
- Implement batching for multi-entity checks (10-50x speedup)
- Add caching for schedule data (static historical data)

---

### 2. Game Schedule Table Location Mismatch (HIGH Severity)

**Location:** Early exit mixin / schedule checks

**Issue:** Code expects `nba_raw.game_schedule` in `us-west2`, but table doesn't exist there.

**Evidence:**
```
ERROR:Error checking game schedule: 404 Not found:
Table nba-props-platform:nba_raw.game_schedule was not found in location us-west2
```

**Note:** Bug fix was committed (table renamed to `nbac_schedule`), but region mismatch persists.

**Recommendations:**
- Verify actual table location (`US` vs `us-west2`)
- Use cross-region queries if needed
- Or migrate table to `us-west2` for consistency
- Add graceful fallback (don't fail hard on missing schedule)

---

### 3. Analytics Processor Runs Schema Mismatch (MEDIUM Severity)

**Location:** `nba_processing.analytics_processor_runs`

**Issue:** Schema field `success` changed from REQUIRED to NULLABLE mode.

**Evidence:**
```
WARNING:Failed to log processing run: 400 Provided Schema does not match
Field success has changed mode from REQUIRED to NULLABLE
```

**Impact:** Run history logging fails silently.

**Fix:**
```sql
ALTER TABLE `nba-props-platform.nba_processing.analytics_processor_runs`
ALTER COLUMN success SET OPTIONS (mode='NULLABLE');
```

---

### 4. Missing Travel Distances Table (LOW Severity)

**Location:** `nba_static.travel_distances`

**Issue:** Optional enhancement table missing.

**Impact:** Minor - processors work without it, just missing that enhancement.

---

## What to Do Next

### Immediate (First 10 Minutes)

1. **Check if UPGC backfill completed:**
```bash
# Quick status check
ps aux | grep "upcoming_player_game_context.*2021-10-19" | grep -v grep

# If running, check progress
tail -20 /tmp/upgc_hash_backfill_nov.log | grep -E "(Processing date|✅)"

# Query BigQuery for actual coverage
bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as total, COUNT(data_hash) as with_hash
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'"
```

2. **If 100% complete, verify all 5 tables:**
```bash
bq query --use_legacy_sql=false --format=csv "
SELECT
  'player_game_summary' as tbl, COUNT(*) as total, COUNT(data_hash) as with_hash
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL SELECT 'team_defense_game_summary', COUNT(*), COUNT(data_hash)
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL SELECT 'team_offense_game_summary', COUNT(*), COUNT(data_hash)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL SELECT 'upcoming_player_game_context', COUNT(*), COUNT(data_hash)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
UNION ALL SELECT 'upcoming_team_game_context', COUNT(*), COUNT(data_hash)
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-19'
"
```

### Decision Point: Historical Backfill Strategy

**Once first month validation is 100% complete:**

You need to decide on the historical backfill approach for the remaining ~3 years of data (2021-11-20 to 2024-12-31).

**Option A: Accept Slow Processor-Based Approach (RECOMMENDED)**
- Runtime: 25-40 days
- Correct hash calculation guaranteed
- Run in background, monitor periodically
- No risk of hash mismatch

**Option B: Skip Historical Backfill**
- Smart reprocessing will only work for data processed after data_hash was added
- Historical data won't benefit from change detection
- May be acceptable if you don't need to reprocess historical data

**Option C: Investigate SQL Hash Approach (Research)**
- Try to replicate Python's JSON serialization + SHA256 in BigQuery
- High complexity, risk of hash mismatch
- Potential speedup if successful

---

## Historical Backfill Commands (Option A)

If you decide to run processor-based historical backfills, here are the commands:

```bash
# Team tables (fastest, ~1-2 days each)
PYTHONPATH=/home/naji/code/nba-stats-scraper \
/home/naji/code/nba-stats-scraper/.venv/bin/python \
backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2021-11-20 --end-date 2024-12-31 \
  2>&1 | tee /tmp/togs_historical_backfill.log &

PYTHONPATH=/home/naji/code/nba-stats-scraper \
/home/naji/code/nba-stats-scraper/.venv/bin/python \
backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2021-11-20 --end-date 2024-12-31 \
  2>&1 | tee /tmp/tdgs_historical_backfill.log &

# Player context (slowest, ~8-12 days)
PYTHONPATH=/home/naji/code/nba-stats-scraper \
/home/naji/code/nba-stats-scraper/.venv/bin/python \
backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-11-20 --end-date 2024-12-31 \
  2>&1 | tee /tmp/upgc_historical_backfill.log &

# Team context (~4-6 days)
PYTHONPATH=/home/naji/code/nba-stats-scraper \
/home/naji/code/nba-stats-scraper/.venv/bin/python \
backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2021-11-20 --end-date 2024-12-31 \
  2>&1 | tee /tmp/utgc_historical_backfill.log &
```

**Monitor with:**
```bash
# Check running processes
ps aux | grep backfill | grep -v grep

# Check logs
tail -20 /tmp/*_historical_backfill.log
```

---

## Code Files Reference

### Hash Calculation Logic

Each processor has a `_calculate_data_hash()` method and a `DATA_HASH_FIELDS` list:

- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
- `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

### Analysis Document

Session 45 code analysis: `/tmp/session45_code_analysis.md`

### Previous Handoff Documents

- Session 44: `docs/09-handoff/2025-12-05-SESSION44-FIRST-MONTH-NEARLY-COMPLETE.md`
- Session 43: `docs/09-handoff/2025-12-05-SESSION43-PHASE3-DATA-HASH-FIRST-MONTH.md`
- Session 42: `docs/09-handoff/2025-12-05-SESSION42-BACKFILL-STATUS-CORRECTION.md`

---

## Summary

**Where We Are:**
- 4 of 5 tables at 100% first-month validation
- 1 table (UPGC) at 89.12%, process running
- Critical discovery: SQL approach won't work for historical backfill
- Several code issues identified for future fixes

**What Needs Deciding:**
1. Wait for UPGC to complete (~5-10 min if still running)
2. Verify 100% first month coverage across all 5 tables
3. Decide on historical backfill strategy (processor-based vs skip)
4. Optionally fix code issues (schema mismatch, timeout, etc.)

**Timeline:**
- First month completion: Within next 10-15 minutes (if not already done)
- Historical backfill decision: User choice
- Historical backfill execution: 25-40 days if chosen

**Risk Level:** Low for first month, Medium for historical (long runtime)

---

**Session 45 Handoff Status:** READY FOR TAKEOVER
**Next Milestone:** Complete first month validation (100% all 5 tables)
**Blocker:** None - just waiting for UPGC backfill to finish
