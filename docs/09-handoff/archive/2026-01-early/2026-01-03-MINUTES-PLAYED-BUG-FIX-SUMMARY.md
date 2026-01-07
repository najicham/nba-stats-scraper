# Minutes Played Bug Fix - Session Summary

**Date**: 2026-01-03 22:00-00:15 PST
**Status**: ✅ FIXED & COMMITTED | 🚀 BACKFILL RUNNING
**Next Action**: Validate backfill completion tomorrow morning

---

## TL;DR - What Was Fixed

**The Problem**:
- 99.5% NULL rate in `minutes_played` field for ALL historical data (2021-2024)
- Affected 83,111 of 83,534 records
- Blocked ML model training

**The Root Cause**:
- Processor bug in `player_game_summary_processor.py` line 752
- `_clean_numeric_columns()` incorrectly coerced minutes field ("45:58" format) to numeric
- `pd.to_numeric("45:58", errors='coerce')` silently returned NaN (NULL)

**The Fix**:
- Removed `'minutes'` from `numeric_columns` list
- Added explanatory comment
- Enhanced `_parse_minutes_to_decimal()` error handling

**The Result**:
- ✅ Bug fix committed and pushed to GitHub (commit: 83d91e2)
- 🚀 Full 3-year backfill running (2021-2024) in tmux
- ⏳ Expected completion: 2026-01-04 11:00 AM PST

---

## What Happened - Investigation Timeline

### 22:00 - Started Investigation
- Read handoff doc suggesting "data never backfilled"
- Planned to run sample test then full backfill

### 22:15 - Pre-flight Checks (PASSED)
```sql
-- Raw BDL data: 0.0% NULL ✅
-- Raw NBA.com data: 0.26-0.48% NULL ✅
-- Environment: Ready ✅
```

### 22:30 - Sample Test (FAILED - Led to Discovery!)
- Ran backfill for 2021-10-19 to 2021-10-26
- Processor completed successfully: "235 records processed"
- BUT: minutes_played still 100% NULL!

### 22:45 - Critical Discovery
Checked raw data vs processed data:
```sql
-- Raw gamebook (source):
Jaylen Brown | 46 pts | "45:58" minutes ✅

-- Analytics table (after processing):
Jaylen Brown | 46 pts | NULL minutes ❌
```

**Realization**: Processor writes records but loses minutes data!

### 23:00 - Bug Found
**File**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Line 752** in `_clean_numeric_columns()`:
```python
# BUGGY:
numeric_columns = [
    'points', 'assists', 'minutes',  # ← BUG HERE!
    ...
]

for col in numeric_columns:
    # This converts "45:58" → NaN (NULL)!
    self.raw_data[col] = pd.to_numeric(self.raw_data[col], errors='coerce')
```

**Why this is wrong**:
- Minutes is in "MM:SS" format: "45:58" = 45 minutes 58 seconds
- `pd.to_numeric("45:58", errors='coerce')` can't parse "45:58" as a number
- Returns NaN (NULL) silently
- This happens BEFORE the proper parser `_parse_minutes_to_decimal()` runs

### 23:15 - Fix Applied
```python
# FIXED:
numeric_columns = [
    'points', 'assists',  # Removed 'minutes'
    'field_goals_made', 'field_goals_attempted',
    ...
]
# NOTE: 'minutes' is NOT included because it's in "MM:SS" format and must be
# parsed by _parse_minutes_to_decimal() later, not coerced to numeric here
```

### 23:20 - Fix Validated
Re-ran single day (2021-10-20):
```sql
-- BEFORE FIX:
Jaylen Brown | 46 pts | NULL minutes

-- AFTER FIX:
Cole Anthony    | 10 pts | 30 minutes ✅
Chris Duarte    | 27 pts | 33 minutes ✅
Svi Mykhailiuk  |  4 pts | 16 minutes ✅
```

**SUCCESS!** Minutes now populated correctly.

### 23:30 - Full Backfill Launched
```bash
tmux new-session -d -s backfill-2021-2024 \
  "PYTHONPATH=. python backfill_jobs/analytics/player_game_summary/\
   player_game_summary_analytics_backfill.py \
   --start-date 2021-10-01 --end-date 2024-05-01"
```

**Progress as of 23:45**:
- Days 1-18: 0 records (offseason)
- Day 19 (2021-10-19): ✅ 47 records
- Day 20 (2021-10-20): ✅ 235 records
- Day 21+: Processing...
- Expected completion: ~12 hours (11:00 AM tomorrow)

### 00:13 - Committed to Git
```bash
git commit -m "fix: Critical bug - minutes_played field incorrectly coerced to NULL"
git push
```

Commit: `83d91e2`

---

## Technical Details

### The Bug (Before)

**File**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
**Line**: 752
**Function**: `_clean_numeric_columns()`

```python
def _clean_numeric_columns(self) -> None:
    numeric_columns = [
        'points', 'assists', 'minutes',  # ← PROBLEM
        'field_goals_made', ...
    ]

    for col in numeric_columns:
        # Converts string to numeric, "coerce" errors to NaN
        self.raw_data[col] = pd.to_numeric(self.raw_data[col], errors='coerce')
        # "45:58" → NaN ❌
```

### The Fix (After)

```python
def _clean_numeric_columns(self) -> None:
    numeric_columns = [
        'points', 'assists',  # 'minutes' REMOVED
        'field_goals_made', ...
    ]
    # NOTE: 'minutes' is NOT included because it's in "MM:SS" format and must be
    # parsed by _parse_minutes_to_decimal() later, not coerced to numeric here

    for col in numeric_columns:
        self.raw_data[col] = pd.to_numeric(self.raw_data[col], errors='coerce')
```

### Why This Bug Existed for Years

1. **Silent failure**: `errors='coerce'` doesn't raise exceptions
2. **Recent data works**: Nov 2025+ has ~35% NULL (correct - DNP players)
3. **No error logs**: Processor completes with "success" messages
4. **Wrong assumption**: Blamed on "data never backfilled" not "processor bug"

---

## Current Status

### ✅ Completed
- [x] Bug identified and root cause analyzed
- [x] Fix implemented in local code
- [x] Fix validated on sample data
- [x] Fix committed to git (83d91e2)
- [x] Fix pushed to GitHub
- [x] Full backfill launched in tmux
- [x] Documentation created

### 🚀 In Progress
- [ ] Backfill running: 2021-10-01 to 2024-05-01 (~944 days)
  - Session: `tmux attach -t backfill-2021-2024`
  - Log: `logs/backfill_20260103_230104.log`
  - Expected: 11:00 AM PST 2026-01-04

### ⏳ Next Steps (Tomorrow)
- [ ] Validate backfill completed successfully
- [ ] Check NULL rate dropped to ~40%
- [ ] Deploy fix to production Cloud Run
- [ ] Proceed with ML training

---

## How to Resume Work Tomorrow

### 1. Check Backfill Status

```bash
# Check if still running
tmux ls

# Attach to see progress
tmux attach -t backfill-2021-2024
# Press Ctrl+B then D to detach

# Or check log file
tail -100 logs/backfill_20260103_230104.log | grep -E "SUMMARY|Success rate"
```

### 2. Validate Results

```sql
-- Check overall NULL rate for 2021-2024
SELECT
  COUNT(*) as total_records,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Expected: null_pct ~35-45% (down from 99.5%!)
```

```sql
-- Spot check specific game
SELECT player_full_name, points, minutes_played
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2022-01-18'  -- Lakers vs Warriors
  AND team_abbr IN ('LAL', 'GSW')
ORDER BY minutes_played DESC NULLS LAST
LIMIT 10;

-- Cross-reference: basketball-reference.com
-- Expected: LeBron ~35-40 min, Steph ~35-40 min
```

### 3. Deploy to Production (When Ready)

```bash
# Deploy fixed processor to Cloud Run
./bin/analytics/deploy/deploy_analytics_processors.sh

# Verify deployment
gcloud run services describe nba-phase3-analytics-processors --region=us-west2
```

---

## Expected Impact

### Before Fix
- Training samples with valid `minutes_avg_last_10`: **3,214**
- Training samples missing minutes: **35,320** (91.7%)
- NULL rate: **99.5%**
- ML model MAE: **4.63** (underperforms baseline by 6.9%)

### After Fix (Expected)
- Training samples with valid `minutes_avg_last_10`: **38,500+**
- Training samples missing minutes: **~15,000** (40%)
- NULL rate: **~40%** (legitimate DNP/inactive players)
- ML model MAE: **3.80-4.10** (projected improvement)

### Business Impact
- **Unblocked**: ML model development
- **Enabled**: Training on 3 additional seasons (2021-2024)
- **Value**: $100-150k potential unlocked

---

## Key Files

**Modified Code**:
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Backfill Script**:
- `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py`

**Logs**:
- `logs/backfill_20260103_230104.log`

**Documentation**:
- `docs/09-handoff/2026-01-03-CRITICAL-BUG-FIX-AND-BACKFILL-LAUNCH.md` (detailed)
- `docs/08-projects/current/backfill-system-analysis/BUG-FIX-MINUTES-PLAYED.md` (technical)
- `docs/09-handoff/2026-01-03-MINUTES-PLAYED-BUG-FIX-SUMMARY.md` (this doc)

---

## Monitoring Commands

```bash
# Check backfill progress
tail -f logs/backfill_20260103_230104.log

# See latest processed days
tail -100 logs/backfill_20260103_230104.log | grep "Processing day"

# Attach to tmux session
tmux attach -t backfill-2021-2024

# Check tmux session exists
tmux ls

# Quick validation query (run anytime)
bq query --use_legacy_sql=false '
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
'
```

---

## Lessons Learned

1. **Don't trust initial hypotheses** - "Never backfilled" was wrong, it was "always broken"
2. **Validate assumptions with data** - Check source data vs processed output
3. **Silent failures are dangerous** - `errors='coerce'` masked bug for years
4. **Test historical data separately** - Recent data working ≠ all data working
5. **Deep investigation pays off** - Found critical bug that affected 3 years of data

---

## Success Criteria Checklist

### Tomorrow Morning Validation
- [ ] Backfill completed successfully (>95% success rate)
- [ ] NULL rate dropped from 99.5% to <45%
- [ ] Row count unchanged (±2%)
- [ ] Spot checks match basketball-reference.com
- [ ] No errors in backfill logs

### Production Deployment
- [ ] Fix deployed to Cloud Run
- [ ] Production processor using fixed code
- [ ] Real-time processing continues working
- [ ] No regression in data quality

### ML Training Unblocked
- [ ] 35,000+ new training samples available
- [ ] Models can be retrained on 2021-2024 data
- [ ] Expected MAE improvement: 10-20%

---

**STATUS**: ✅ Bug fixed, committed, pushed to GitHub
**BACKFILL**: 🚀 Running in tmux:backfill-2021-2024
**NEXT**: Validate completion tomorrow ~11:00 AM PST

**Questions?** Read the detailed handoff:
`docs/09-handoff/2026-01-03-CRITICAL-BUG-FIX-AND-BACKFILL-LAUNCH.md`
