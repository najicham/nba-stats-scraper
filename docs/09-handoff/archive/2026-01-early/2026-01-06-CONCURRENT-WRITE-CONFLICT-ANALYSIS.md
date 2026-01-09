# Concurrent Write Conflict Analysis

**Date**: January 6, 2026
**Issue**: BigQuery serialization conflict during backfill

---

## 🚨 Error Details

**Timestamp**: 2026-01-06 10:25:43 UTC (2:25 AM PST)
**Processor**: NBA.com Gamebook Processor
**Table**: `nba-props-platform:nba_raw.nbac_gamebook_player_stats`
**Error**: `400 Could not serialize access to table... due to concurrent update`

```
Failed to load gamebook data to BigQuery: 400 Could not serialize access
to table nba-props-platform:nba_raw.nbac_gamebook_player_stats due to
concurrent update

Location: us-west2
Job ID: 48dbce6e-e551-4065-b994-80d734d603e1
Rows attempted: 34
```

---

## 🔍 Root Cause Analysis

### What Was Happening at 2:25 AM PST

**Backfill Processes** (Running):
1. **TDZA** (team_defense_zone_analysis) - Still processing
   - Status: 86% complete
   - **Reading** from `nbac_gamebook_player_stats`

2. **PSZA** (player_shot_zone_analysis) - Still processing
   - Status: 43% complete
   - **Reading** from `nbac_gamebook_player_stats`

**Live Scraper** (Triggered):
3. **NBA.com Gamebook Processor** - Attempted to run
   - Tried to **INSERT** 34 rows into `nbac_gamebook_player_stats`
   - **FAILED** due to concurrent access

### Why This Happened

**BigQuery Serialization Conflict**:
- Multiple processes tried to access the same table simultaneously
- BigQuery couldn't guarantee transaction isolation
- Live scraper's INSERT conflicted with backfill's READ operations

**This is NOT the MERGE bug** - this is a different issue:
- MERGE bug: DELETE + INSERT race condition within a single process
- This issue: Multiple processes accessing same table at same time

---

## 💡 Solutions

### Option 1: Pause Live Scrapers During Backfill (Recommended)

**Why**: Eliminates conflicts completely
**How**: Temporarily disable scheduled scrapers

```bash
# List all Cloud Scheduler jobs
gcloud scheduler jobs list

# Pause gamebook scraper
gcloud scheduler jobs pause [JOB_NAME]

# Resume after backfill complete
gcloud scheduler jobs resume [JOB_NAME]
```

**When to Resume**: After Phase 4 complete (~11 PM tonight)

---

### Option 2: Implement Retry Logic with Backoff

**Why**: Allow temporary failures to self-recover
**How**: Add retry logic to scraper

**Current behavior**: Fails on first conflict
**Better behavior**: Retry with exponential backoff

```python
from google.api_core import retry

@retry.Retry(
    predicate=retry.if_exception_type(google.api_core.exceptions.BadRequest),
    initial=1.0,
    maximum=60.0,
    multiplier=2.0,
    deadline=300.0
)
def load_to_bigquery(self, rows):
    # Load operation here
    pass
```

---

### Option 3: Stagger Scraper Schedule

**Why**: Reduce probability of overlap
**How**: Shift scraper timing away from backfill peak

**Current**: Runs every hour (on the hour?)
**Better**: Run at :15 and :45 minutes past the hour

**Example**:
```yaml
schedule: "15,45 * * * *"  # Run at :15 and :45
```

---

### Option 4: Use BigQuery Streaming Inserts

**Why**: Streaming inserts don't conflict with batch operations
**How**: Change scraper to use `insert_rows()` instead of load jobs

**Pros**:
- No serialization conflicts
- Faster for small batches

**Cons**:
- 90-minute streaming buffer (blocks DML)
- Costs slightly more

---

## 📊 Impact Assessment

### Severity: **LOW** ⚠️

**Why Low**:
- Only 1 occurrence detected
- Only 34 rows affected (small batch)
- Scraper likely retried automatically or will retry next run
- No data loss (just delayed)

### Frequency

**Expected during backfill**: Rare but possible
- Backfills run for hours
- Live scrapers run every hour
- Small overlap window

**After backfill complete**: Should not occur
- Backfills done
- Only live scrapers running

---

## 🎯 Recommended Action

### Immediate (Today)

**1. Check if live scrapers are paused**:
```bash
gcloud scheduler jobs list --format="table(name,state,schedule)"
```

**2. If running, pause them**:
```bash
# Pause all NBA scrapers during backfill
gcloud scheduler jobs pause nba-gamebook-scraper
gcloud scheduler jobs pause nba-boxscore-scraper
# (add other scrapers as needed)
```

**3. Resume after Phase 4 complete** (~11 PM tonight):
```bash
gcloud scheduler jobs resume nba-gamebook-scraper
gcloud scheduler jobs resume nba-boxscore-scraper
```

---

### Long-term (Next Week)

**1. Add Retry Logic**:
- Update scrapers to retry on serialization conflicts
- Use exponential backoff (1s, 2s, 4s, 8s, etc.)
- Max 5 retries before failing

**2. Implement Coordination**:
- Add a "backfill in progress" flag in Firestore/Cloud Storage
- Scrapers check flag before running
- Skip run if backfill active

**3. Add Monitoring**:
- Alert on serialization conflicts
- Track conflict frequency
- Auto-pause scrapers if conflicts spike

---

## 📋 Verification

### Check if Scrapers Are Currently Running

```bash
# Method 1: Cloud Scheduler
gcloud scheduler jobs list

# Method 2: Cloud Functions
gcloud functions list

# Method 3: Cloud Run services
gcloud run services list
```

### Check Recent Scraper Runs

```sql
-- Check recent inserts to gamebook table
SELECT
  game_date,
  COUNT(*) as rows,
  MAX(inserted_at) as last_insert
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY last_insert DESC
LIMIT 10
```

---

## 🔧 Implementation Plan

### Step 1: Identify Live Scrapers (5 min)
```bash
gcloud scheduler jobs list | grep nba
gcloud functions list | grep scraper
```

### Step 2: Pause During Backfill (2 min)
```bash
# For each scraper found:
gcloud scheduler jobs pause [JOB_NAME]
```

### Step 3: Document and Track (5 min)
- List paused jobs
- Set reminder to resume at 11 PM
- Add to handoff document

### Step 4: Resume After Backfill (2 min)
```bash
# After Phase 4 complete:
gcloud scheduler jobs resume [JOB_NAME]
```

**Total time**: 15 minutes

---

## 📝 Related Issues

**This is different from**:
- ✅ MERGE_UPDATE bug (fixed Jan 5) - race condition within single process
- ✅ Duplicate creation (fixed Jan 5) - DELETE + INSERT pattern

**This is about**:
- ❌ Concurrent access from multiple processes
- ❌ Live scrapers vs backfill processes
- ❌ BigQuery serialization limits

---

## 📞 Quick Reference

### Check Scheduler Status
```bash
gcloud scheduler jobs list --format="table(name,state,lastAttemptTime)"
```

### Pause All NBA Scrapers
```bash
for job in $(gcloud scheduler jobs list --format="value(name)" | grep nba); do
  gcloud scheduler jobs pause $job
  echo "Paused: $job"
done
```

### Resume All NBA Scrapers
```bash
for job in $(gcloud scheduler jobs list --format="value(name)" | grep nba); do
  gcloud scheduler jobs resume $job
  echo "Resumed: $job"
done
```

---

## ✅ Resolution Status

- [ ] Identify live scrapers
- [ ] Pause scrapers during backfill
- [ ] Document paused jobs
- [ ] Set reminder to resume at 11 PM
- [ ] Add retry logic (future improvement)
- [ ] Add coordination flag (future improvement)

---

**Created**: January 6, 2026, 8:30 AM PST
**Priority**: Medium (handle today before more backfills run)
**Risk**: Low (only affects live data freshness, no data loss)
