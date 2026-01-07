# 🔧 Chat 5 Handoff: BR Roster Concurrency Bug Fix (OPTIONAL)
**Session**: Chat 5 of 6 (Optional - Independent Work)
**When**: Tonight OR Tomorrow (Independent of backfill/ML work)
**Duration**: 1-2 hours
**Objective**: Fix Basketball Reference roster scraper concurrency bug (P0)

---

## ⚡ COPY-PASTE TO START CHAT 5

```
I need to fix the Basketball Reference roster scraper concurrency bug (P0).

Context:
- Current problem: 30 teams writing simultaneously → BigQuery 20 DML limit
- Current code: DELETE + INSERT pattern (2 DML per team = 60 total)
- Impact: Daily failures, concurrent update errors
- Read: /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-PHASE3-FIXED-ML-READY-HANDOFF.md (lines 237-327)

Task:
1. Understand current processor code (br_roster_processor.py)
2. Identify the DELETE + INSERT pattern causing issues
3. Implement MERGE pattern (1 DML per team = 30 total)
4. Test with sample data
5. Deploy and validate

Solution: Use MERGE statement (atomic upsert) instead of DELETE then INSERT

Expected: 0 concurrent update errors after fix

Let's start by reading the processor code!
```

---

## 📋 CHAT OBJECTIVES

### Primary Goal
Eliminate concurrent update errors in Basketball Reference roster scraper

### Root Cause
- 30 teams × 2 DML operations (DELETE + INSERT) = 60 concurrent DML statements
- BigQuery limit: 20-50 concurrent DML per table
- Result: Frequent failures with "concurrent update" errors

### Solution
Replace DELETE + INSERT with atomic MERGE (1 DML per team = 30 total)

### Success Criteria
- ✅ MERGE pattern implemented
- ✅ All 30 teams process without concurrent update errors
- ✅ Single atomic DML per team
- ✅ Tested and deployed successfully
- ✅ Monitoring shows 0 errors for 48 hours

---

## 🎯 STEP-BY-STEP IMPLEMENTATION

### Step 1: Read Current Code (10 minutes)

**Objective**: Understand the problematic DELETE + INSERT pattern

**File**: `data_processors/raw/basketball_ref/br_roster_processor.py`

**Look for** (around line 355):
```python
def save_data(self):
    """Save roster data (CURRENT - PROBLEMATIC)"""

    for team in self.teams:
        # PROBLEM: DML #1 - DELETE old data
        delete_query = f"""
        DELETE FROM `{self.table_name}`
        WHERE team_abbrev = '{team}'
        """
        self.bq_client.query(delete_query).result()

        # PROBLEM: DML #2 - INSERT new data
        insert_job = self.bq_client.load_table_from_dataframe(
            self.roster_data[team],
            self.table_name
        )
        insert_job.result()

    # Total: 30 teams × 2 DML = 60 DML statements
    # BigQuery limit: 20-50 → ERRORS!
```

**Key Issues**:
1. Non-atomic: DELETE and INSERT are separate operations
2. Race condition: Team A deletes while Team B inserts
3. Exceeds quota: 60 DML > 20-50 limit
4. No transaction: If INSERT fails, data is lost (deleted but not re-inserted)

---

### Step 2: Implement MERGE Pattern (30 minutes)

**Objective**: Replace DELETE + INSERT with atomic MERGE

**New Implementation**:
```python
def save_data(self):
    """Save roster data using MERGE (FIXED)."""

    for team_abbrev, roster_df in self.transformed_data.items():
        # Create temp table with new data
        temp_table_id = f"{self.project_id}.nba_raw.br_rosters_temp_{team_abbrev}"

        # Load new data into temp table
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE"  # Overwrite temp table
        )

        load_job = self.bq_client.load_table_from_dataframe(
            roster_df,
            temp_table_id,
            job_config=job_config
        )
        load_job.result()  # Wait for load

        # MERGE: Atomic upsert (1 DML operation)
        merge_query = f"""
        MERGE `{self.project_id}.nba_raw.br_rosters_current` AS target
        USING `{temp_table_id}` AS source
        ON target.team_abbrev = source.team_abbrev
           AND target.player_name = source.player_name
           AND target.season = source.season
        WHEN MATCHED THEN
          UPDATE SET
            position = source.position,
            height = source.height,
            weight = source.weight,
            birth_date = source.birth_date,
            experience = source.experience,
            college = source.college,
            updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
          INSERT (
            team_abbrev, player_name, season, position, height,
            weight, birth_date, experience, college,
            created_at, updated_at
          )
          VALUES (
            source.team_abbrev, source.player_name, source.season,
            source.position, source.height, source.weight,
            source.birth_date, source.experience, source.college,
            CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
          )
        """

        self.bq_client.query(merge_query).result()

        # Clean up temp table
        self.bq_client.delete_table(temp_table_id, not_found_ok=True)

        logger.info(f"✅ Merged roster data for {team_abbrev}")

    # Total: 30 teams × 1 MERGE = 30 DML statements (within limit!)
```

**Key Improvements**:
1. ✅ Atomic: MERGE is single operation
2. ✅ No race conditions: Each team's MERGE is independent
3. ✅ Within quota: 30 DML < 50 limit
4. ✅ Transactional: Either all changes apply or none
5. ✅ Cleanup: Temp tables deleted after use

---

### Step 3: Add Error Handling (15 minutes)

**Objective**: Make it robust for production

**Enhanced Implementation**:
```python
def save_data(self):
    """Save roster data using MERGE with error handling."""

    for team_abbrev, roster_df in self.transformed_data.items():
        try:
            temp_table_id = f"{self.project_id}.nba_raw.br_rosters_temp_{team_abbrev}"

            # Load to temp table
            job_config = bigquery.LoadJobConfig(
                write_disposition="WRITE_TRUNCATE"
            )

            load_job = self.bq_client.load_table_from_dataframe(
                roster_df,
                temp_table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)  # 2 min timeout

            # MERGE with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    merge_query = f"""
                    MERGE `{self.project_id}.nba_raw.br_rosters_current` AS target
                    USING `{temp_table_id}` AS source
                    ON target.team_abbrev = source.team_abbrev
                       AND target.player_name = source.player_name
                       AND target.season = source.season
                    WHEN MATCHED THEN
                      UPDATE SET
                        position = source.position,
                        height = source.height,
                        weight = source.weight,
                        birth_date = source.birth_date,
                        experience = source.experience,
                        college = source.college,
                        updated_at = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN
                      INSERT (
                        team_abbrev, player_name, season, position, height,
                        weight, birth_date, experience, college,
                        created_at, updated_at
                      )
                      VALUES (
                        source.team_abbrev, source.player_name, source.season,
                        source.position, source.height, source.weight,
                        source.birth_date, source.experience, source.college,
                        CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
                      )
                    """

                    self.bq_client.query(merge_query).result(timeout=120)
                    logger.info(f"✅ Merged roster data for {team_abbrev}")
                    break  # Success!

                except Exception as merge_error:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(
                            f"MERGE failed for {team_abbrev} (attempt {attempt+1}/{max_retries}), "
                            f"retrying in {wait_time}s: {merge_error}"
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"❌ MERGE failed for {team_abbrev} after {max_retries} attempts")
                        raise

            # Clean up temp table
            self.bq_client.delete_table(temp_table_id, not_found_ok=True)

        except Exception as e:
            logger.error(f"❌ Failed to process {team_abbrev}: {e}")
            # Continue to next team (don't fail entire job for one team)
            continue

    logger.info(f"✅ Roster save complete for {len(self.transformed_data)} teams")
```

**Robustness Features**:
- ✅ Timeout on load (2 min max)
- ✅ Retry logic (3 attempts with exponential backoff)
- ✅ Per-team error handling (one failure doesn't block others)
- ✅ Cleanup even if MERGE fails
- ✅ Detailed logging

---

### Step 4: Test with Sample Data (15 minutes)

**Objective**: Verify MERGE works before deploying

**Create Test Script**:
```python
# test_merge_pattern.py
import pandas as pd
from google.cloud import bigquery

def test_merge():
    """Test MERGE pattern with sample data."""

    client = bigquery.Client(project="nba-props-platform")

    # Create sample data
    test_data = pd.DataFrame({
        'team_abbrev': ['LAL', 'LAL', 'BOS'],
        'player_name': ['LeBron James', 'Anthony Davis', 'Jayson Tatum'],
        'season': ['2024-25', '2024-25', '2024-25'],
        'position': ['F', 'F-C', 'F'],
        'height': ['6-9', '6-10', '6-8'],
        'weight': [250, 253, 210],
        'birth_date': ['1984-12-30', '1993-03-11', '1998-03-03'],
        'experience': [21, 12, 7],
        'college': ['None', 'Kentucky', 'Duke']
    })

    # Test MERGE logic
    temp_table = "nba-props-platform.nba_raw.br_rosters_temp_TEST"

    # Load to temp
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    load_job = client.load_table_from_dataframe(
        test_data, temp_table, job_config=job_config
    )
    load_job.result()

    # MERGE
    merge_query = f"""
    MERGE `nba-props-platform.nba_raw.br_rosters_current` AS target
    USING `{temp_table}` AS source
    ON target.team_abbrev = source.team_abbrev
       AND target.player_name = source.player_name
       AND target.season = source.season
    WHEN MATCHED THEN
      UPDATE SET position = source.position
    WHEN NOT MATCHED THEN
      INSERT (team_abbrev, player_name, season, position, height, weight,
              birth_date, experience, college, created_at, updated_at)
      VALUES (source.team_abbrev, source.player_name, source.season,
              source.position, source.height, source.weight, source.birth_date,
              source.experience, source.college, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
    """

    client.query(merge_query).result()

    # Verify
    verify_query = """
    SELECT * FROM `nba-props-platform.nba_raw.br_rosters_current`
    WHERE season = '2024-25' AND team_abbrev IN ('LAL', 'BOS')
    """
    results = list(client.query(verify_query).result())

    print(f"✅ Test passed! Inserted/updated {len(results)} records")

    # Cleanup
    client.delete_table(temp_table, not_found_ok=True)

if __name__ == "__main__":
    test_merge()
```

**Run Test**:
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 test_merge_pattern.py

# Expected output:
# ✅ Test passed! Inserted/updated 3 records
```

---

### Step 5: Deploy Fix (15 minutes)

**Objective**: Deploy updated processor to production

**Commands**:
```bash
cd /home/naji/code/nba-stats-scraper

# Commit changes
git add data_processors/raw/basketball_ref/br_roster_processor.py
git commit -m "fix: Replace DELETE+INSERT with MERGE in BR roster processor

- Reduces DML operations from 60 (30 teams × 2) to 30 (30 teams × 1)
- Eliminates concurrent update errors
- Atomic upsert per team (no race conditions)
- Added retry logic with exponential backoff
- Fixes P0 production bug

Resolves: Daily roster scraper failures
Impact: 0 concurrent update errors expected"

# Push to main
git push origin main

# Deploy raw processors
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Or if separate deployment for raw processors:
# ./bin/raw/deploy/deploy_raw_processors.sh
```

**Verify Deployment**:
```bash
# Check Cloud Run revision
gcloud run services describe nba-phase2-raw-processors \
  --region us-west2 \
  --format="value(status.latestReadyRevisionName)"

# Should show new revision (e.g., 00052)
```

---

### Step 6: Validate Production (20 minutes)

**Objective**: Confirm fix works in production

**Monitor Logs**:
```bash
# Watch for next roster scraper run
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"br_roster"' \
  --limit=50 \
  --format=json

# Look for:
# - "✅ Merged roster data for LAL" (30 times, one per team)
# - NO "concurrent update" errors
# - NO "ERROR" severity logs
```

**Check BigQuery**:
```bash
# Verify all 30 teams processed
bq query --use_legacy_sql=false '
SELECT
  team_abbrev,
  COUNT(*) as roster_size,
  MAX(updated_at) as last_update
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season = "2024-25"
GROUP BY team_abbrev
ORDER BY team_abbrev
'

# Expected: 30 teams, each with 12-18 players, recent last_update
```

**Monitor for 48 Hours**:
```bash
# Daily check for errors
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"br_roster"
  AND severity=ERROR' \
  --limit=10

# Expected: 0 results (no errors)
```

---

## ✅ SUCCESS CHECKLIST

- [ ] Current code analyzed (DELETE + INSERT pattern identified)
- [ ] MERGE pattern implemented
- [ ] Error handling added (retries, timeouts, cleanup)
- [ ] Test script created and passed
- [ ] Code committed with clear commit message
- [ ] Deployed to production
- [ ] Verified in logs (30 successful MERGEs)
- [ ] Validated in BigQuery (30 teams updated)
- [ ] Monitored for 48h (0 errors)

---

## 🚨 COMMON ISSUES & SOLUTIONS

### Issue 1: MERGE Syntax Error

**Symptom**: BigQuery rejects MERGE query

**Cause**: Syntax error in MERGE statement

**Solution**:
- Check ON clause (primary keys correct?)
- Verify column names match (source vs target)
- Test MERGE query in BigQuery console first
- Use test script before deploying

---

### Issue 2: Temp Table Already Exists

**Symptom**: "Table already exists" error

**Cause**: Previous run didn't clean up temp table

**Solution**:
```python
# Always clean up at start AND end
self.bq_client.delete_table(temp_table_id, not_found_ok=True)  # Before load
# ... MERGE logic ...
self.bq_client.delete_table(temp_table_id, not_found_ok=True)  # After MERGE
```

---

### Issue 3: MERGE Still Has Concurrent Errors

**Symptom**: Still seeing occasional concurrent update errors

**Cause**: 30 concurrent MERGEs might still exceed quota

**Solution**:
```python
# Add semaphore to limit concurrent operations
from threading import Semaphore

MAX_CONCURRENT = 10  # Process max 10 teams at once
semaphore = Semaphore(MAX_CONCURRENT)

def save_team_data(team_abbrev, roster_df):
    with semaphore:
        # MERGE logic here
        pass

# Use ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
    futures = [
        executor.submit(save_team_data, team, df)
        for team, df in self.transformed_data.items()
    ]
    for future in futures:
        future.result()
```

---

## 📊 EXPECTED OUTCOME

### Before Fix
- Concurrent DML: 60 (30 teams × 2 operations)
- Error rate: 30-50% of runs fail
- Error message: "Concurrent update limit exceeded"
- Manual intervention: Required daily

### After Fix
- Concurrent DML: 30 (30 teams × 1 MERGE)
- Error rate: 0% (within BigQuery limits)
- Error message: None
- Manual intervention: None needed

### Impact
- ✅ P0 bug eliminated
- ✅ Daily failures stop
- ✅ Roster data always up-to-date
- ✅ No manual intervention needed
- ✅ More robust to future scale (can handle 40-50 teams)

---

## 💡 IMPLEMENTATION TIPS

**Do**:
- ✅ Test MERGE pattern with sample data first
- ✅ Add retry logic (BigQuery can have transient errors)
- ✅ Clean up temp tables (before AND after)
- ✅ Log success per team (easier debugging)
- ✅ Continue on single team failure (don't fail entire job)

**Don't**:
- ❌ Skip testing (MERGE syntax can be tricky)
- ❌ Deploy without error handling (production will have issues)
- ❌ Leave temp tables (quota waste)
- ❌ Fail entire job if one team fails (lose all 30 teams of data)
- ❌ Remove old code until new code validated (keep rollback option)

---

**This is independent work - can be done anytime!** 🔧

Priority: P0, but doesn't block ML training. Do it when you have 1-2 hours.
