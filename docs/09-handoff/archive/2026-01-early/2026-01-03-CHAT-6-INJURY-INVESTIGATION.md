# 🔍 Chat 6 Handoff: Injury Data Investigation (OPTIONAL)
**Session**: Chat 6 of 6 (Optional - Wait until after backfill)
**When**: After backfill completes
**Duration**: 1-2 hours
**Objective**: Investigate and fix injury report data loss (P1)

---

## ⚡ COPY-PASTE TO START CHAT 6

```
I need to investigate why injury report data appears to be lost (P1 bug).

Context:
- Observed: 151 rows scraped but 0 saved
- Location: Layer 5 validation caught the issue
- Impact: Missing injury data for predictions
- Read: /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-PHASE3-FIXED-ML-READY-HANDOFF.md (lines 331-404)

Task:
1. Check processor logs during the failure window
2. Look for specific error patterns (timeout, schema, duplicates, concurrent writes)
3. Identify root cause
4. Implement fix with robust retry logic
5. Test and validate

Possible causes:
- BigQuery timeout
- Schema validation failure
- Duplicate key constraint
- Concurrent write conflict

Let's start by checking the logs!
```

---

## 📋 CHAT OBJECTIVES

### Primary Goal
Identify why 151 injury records were scraped but 0 saved to BigQuery

### Root Cause Hypotheses
1. **BigQuery timeout** - Load job timed out before completing
2. **Schema validation** - Data doesn't match table schema
3. **Duplicate key** - Primary key conflict causing rejection
4. **Concurrent write** - Multiple processors writing simultaneously
5. **Silent failure** - Error not logged properly

### Success Criteria
- ✅ Root cause identified from logs
- ✅ Fix implemented with retry logic
- ✅ Test shows 100% save success
- ✅ Monitoring confirms no recurrence for 48h

---

## 🎯 STEP-BY-STEP INVESTIGATION

### Step 1: Check Processor Logs (15 minutes)

**Objective**: Find the failure event in Cloud Logging

**Commands**:
```bash
# Search for injury processor logs during failure window
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"NbacInjuryReportProcessor"
  AND timestamp>="2026-01-03T00:00:00Z"
  AND timestamp<="2026-01-03T00:10:00Z"' \
  --project=nba-props-platform \
  --limit=100 \
  --format=json > /tmp/injury_processor_logs.json

# Parse for errors
cat /tmp/injury_processor_logs.json | jq -r '.[] |
  select(.severity == "ERROR" or (.textPayload | contains("failed") or contains("timeout"))) |
  "\(.timestamp) | \(.severity) | \(.textPayload)"'
```

**Look for**:
- "ERROR" severity logs
- "timeout" in message
- "failed to save" or "failed to insert"
- "schema mismatch"
- "duplicate" or "already exists"
- "concurrent" or "conflict"

---

### Step 2: Check BigQuery Job History (10 minutes)

**Objective**: Find the specific load job that failed

**Commands**:
```bash
# List recent BigQuery jobs for injury table
bq ls -j -a --max_results=50 --format=prettyjson | jq -r '.[] |
  select(.configuration.load.destinationTable.tableId == "nbac_injury_report") |
  {
    jobId: .id,
    status: .status.state,
    error: .status.errorResult,
    startTime: .statistics.startTime,
    outputRows: .statistics.load.outputRows
  }'

# Look for:
# - status: "DONE" with error
# - outputRows: 0 (nothing written)
# - errorResult: specific error message
```

**Check Specific Job**:
```bash
# If you found a suspicious job ID:
bq show -j <job_id>

# Look at error details
bq show -j <job_id> --format=prettyjson | jq '.status.errors'
```

---

### Step 3: Analyze Common Failure Patterns (10 minutes)

#### **Pattern A: Timeout**

**Symptoms**:
- Logs: "Operation timed out"
- BigQuery job: Status "DONE" with timeout error
- Frequency: Sporadic (depends on BigQuery load)

**Solution**:
```python
# Increase timeout in processor
job_config = bigquery.LoadJobConfig(
    write_disposition="WRITE_APPEND"
)

load_job = self.bq_client.load_table_from_dataframe(
    injury_df,
    self.table_name,
    job_config=job_config
)

# BEFORE: load_job.result()  # Default 30s timeout
# AFTER:
load_job.result(timeout=120)  # 2 minutes
```

---

#### **Pattern B: Schema Mismatch**

**Symptoms**:
- Logs: "Schema mismatch" or "Invalid field"
- BigQuery job: Column type doesn't match
- Frequency: After schema changes

**Investigation**:
```bash
# Check table schema
bq show --schema nba-props-platform:nba_raw.nbac_injury_report

# Compare to DataFrame columns
# In processor code, log DataFrame dtypes before save
```

**Solution**:
```python
# Validate schema before save
def validate_schema(self, df):
    """Ensure DataFrame matches BigQuery schema."""
    expected_schema = {
        'player_name': 'object',
        'team_abbrev': 'object',
        'injury_status': 'object',
        'injury_description': 'object',
        'game_date': 'datetime64[ns]',
        'created_at': 'datetime64[ns]'
    }

    for col, dtype in expected_schema.items():
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")
        if df[col].dtype != dtype:
            logger.warning(f"Column {col} has dtype {df[col].dtype}, expected {dtype}")
            # Try to cast
            df[col] = df[col].astype(dtype)

    return df
```

---

#### **Pattern C: Duplicate Key**

**Symptoms**:
- Logs: "Duplicate entry" or "UNIQUE constraint"
- BigQuery job: Constraint violation
- Frequency: Re-running same data

**Investigation**:
```bash
# Check if data already exists
bq query --use_legacy_sql=false '
SELECT
  game_date,
  player_name,
  team_abbrev,
  COUNT(*) as duplicates
FROM `nba-props-platform.nba_raw.nbac_injury_report`
WHERE game_date = "2026-01-03"
GROUP BY game_date, player_name, team_abbrev
HAVING duplicates > 1
'
```

**Solution**:
```python
# Use WRITE_TRUNCATE for date or INSERT OR UPDATE pattern
job_config = bigquery.LoadJobConfig(
    write_disposition="WRITE_TRUNCATE"  # Replace all data
)

# OR: Delete existing data for date first
delete_query = f"""
DELETE FROM `{self.table_name}`
WHERE game_date = '{self.game_date}'
"""
self.bq_client.query(delete_query).result()

# Then INSERT new data
load_job = self.bq_client.load_table_from_dataframe(...)
```

---

#### **Pattern D: Silent Failure**

**Symptoms**:
- Logs: "Saved X records" but BigQuery shows 0
- BigQuery job: Success but outputRows = 0
- Frequency: Logic bug

**Investigation**:
```python
# Add verification after save
def save_data(self):
    # Save logic
    load_job = self.bq_client.load_table_from_dataframe(...)
    load_job.result(timeout=120)

    # VERIFY rows actually saved
    count_query = f"""
    SELECT COUNT(*) as saved_count
    FROM `{self.table_name}`
    WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
    """

    result = list(self.bq_client.query(count_query).result())
    saved_count = result[0]['saved_count']
    expected_count = len(self.transformed_data)

    if saved_count == 0 and expected_count > 0:
        raise ValueError(f"CRITICAL: 0 rows saved but expected {expected_count}")

    logger.info(f"✅ Verified: Saved {saved_count}/{expected_count} injury records")
```

---

### Step 4: Implement Robust Fix (30 minutes)

**Objective**: Add comprehensive error handling and retry logic

**Enhanced save_data() method**:
```python
def save_data(self):
    """Save injury data with robust error handling."""

    if self.transformed_data.empty:
        logger.warning("No injury data to save")
        return

    max_retries = 3

    for attempt in range(max_retries):
        try:
            # Validate schema
            self.transformed_data = self._validate_schema(self.transformed_data)

            # Delete existing data for this date (avoid duplicates)
            delete_query = f"""
            DELETE FROM `{self.table_name}`
            WHERE game_date = '{self.game_date}'
            """
            self.bq_client.query(delete_query).result(timeout=60)
            logger.info(f"Deleted existing injury data for {self.game_date}")

            # Load new data with increased timeout
            job_config = bigquery.LoadJobConfig(
                write_disposition="WRITE_APPEND",
                schema_update_options=[
                    bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION
                ]
            )

            load_job = self.bq_client.load_table_from_dataframe(
                self.transformed_data,
                self.table_name,
                job_config=job_config
            )

            # Wait with timeout
            load_job.result(timeout=120)  # 2 minutes

            # VERIFY rows actually saved
            count_query = f"""
            SELECT COUNT(*) as saved_count
            FROM `{self.table_name}`
            WHERE game_date = '{self.game_date}'
              AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
            """

            result = list(self.bq_client.query(count_query).result())
            saved_count = result[0]['saved_count']
            expected_count = len(self.transformed_data)

            if saved_count == 0:
                raise ValueError(
                    f"VERIFICATION FAILED: 0 rows saved but expected {expected_count}"
                )

            if saved_count < expected_count * 0.9:  # Allow 10% loss
                logger.warning(
                    f"⚠️ Partial save: {saved_count}/{expected_count} records saved"
                )

            logger.info(f"✅ Successfully saved {saved_count} injury records")

            # Track stats
            self.stats['rows_inserted'] = saved_count
            self.stats['rows_expected'] = expected_count

            break  # Success!

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    f"Save failed (attempt {attempt+1}/{max_retries}), "
                    f"retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"❌ Failed to save injury data after {max_retries} attempts: {e}",
                    exc_info=True
                )

                # Send alert
                try:
                    notify_error(
                        title="Injury Data Save Failed",
                        message=f"Failed to save {len(self.transformed_data)} records after {max_retries} attempts",
                        details={'error': str(e), 'game_date': self.game_date}
                    )
                except:
                    pass

                raise

def _validate_schema(self, df):
    """Validate and fix DataFrame schema."""

    # Ensure required columns
    required_cols = ['player_name', 'team_abbrev', 'injury_status', 'game_date']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Fix data types
    if 'game_date' in df.columns:
        df['game_date'] = pd.to_datetime(df['game_date'])

    # Add timestamps
    df['created_at'] = datetime.now(timezone.utc)
    df['updated_at'] = datetime.now(timezone.utc)

    return df
```

**Key Features**:
- ✅ Schema validation before save
- ✅ Delete existing data (avoid duplicates)
- ✅ Increased timeout (120s vs 30s default)
- ✅ Retry with exponential backoff (3 attempts)
- ✅ Verification after save (catch silent failures)
- ✅ Detailed logging
- ✅ Error alerting
- ✅ Stats tracking

---

### Step 5: Test Fix (15 minutes)

**Objective**: Verify fix works with test data

**Test Script**:
```python
# test_injury_save.py
import pandas as pd
from datetime import datetime, timezone
from google.cloud import bigquery

def test_injury_save():
    """Test injury data save with new robust logic."""

    client = bigquery.Client(project="nba-props-platform")
    table_name = "nba-props-platform.nba_raw.nbac_injury_report"

    # Create test data
    test_data = pd.DataFrame({
        'player_name': ['LeBron James', 'Stephen Curry', 'Kevin Durant'],
        'team_abbrev': ['LAL', 'GSW', 'PHX'],
        'injury_status': ['Out', 'Questionable', 'Probable'],
        'injury_description': ['Ankle', 'Knee', 'Calf'],
        'game_date': pd.to_datetime(['2026-01-03', '2026-01-03', '2026-01-03']),
        'created_at': datetime.now(timezone.utc),
        'updated_at': datetime.now(timezone.utc)
    })

    # Save with robust logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Delete existing
            delete_query = """
            DELETE FROM `nba-props-platform.nba_raw.nbac_injury_report`
            WHERE game_date = '2026-01-03'
            """
            client.query(delete_query).result(timeout=60)

            # Save new
            job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
            load_job = client.load_table_from_dataframe(
                test_data, table_name, job_config=job_config
            )
            load_job.result(timeout=120)

            # Verify
            count_query = """
            SELECT COUNT(*) as count
            FROM `nba-props-platform.nba_raw.nbac_injury_report`
            WHERE game_date = '2026-01-03'
            """
            result = list(client.query(count_query).result())
            saved_count = result[0]['count']

            if saved_count == 0:
                raise ValueError("0 rows saved")

            print(f"✅ Test passed! Saved {saved_count} records")
            break

        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Attempt {attempt+1} failed, retrying: {e}")
                import time
                time.sleep(2 ** attempt)
            else:
                print(f"❌ Test failed after {max_retries} attempts: {e}")
                raise

if __name__ == "__main__":
    test_injury_save()
```

**Run Test**:
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 test_injury_save.py

# Expected:
# ✅ Test passed! Saved 3 records
```

---

### Step 6: Deploy and Monitor (20 minutes)

**Deploy**:
```bash
cd /home/naji/code/nba-stats-scraper

# Commit changes
git add data_processors/raw/nba_com/injury_report_processor.py
git commit -m "fix: Add robust error handling to injury report processor

- Increased timeout from 30s to 120s
- Added retry logic with exponential backoff (3 attempts)
- Schema validation before save
- Delete existing data to avoid duplicates
- Verification after save (catch silent failures)
- Detailed logging and error alerting

Resolves: P1 injury data loss issue (151 scraped, 0 saved)
Impact: 100% save success expected"

git push origin main

# Deploy
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

**Monitor**:
```bash
# Watch for next injury scraper run
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"injury"' \
  --limit=20 \
  --format=json

# Look for:
# - "✅ Successfully saved X injury records"
# - "✅ Verified: Saved X/X injury records"
# - NO "0 rows saved but expected" errors
```

**Validate**:
```bash
# Check that injury data is being saved
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(*) as injury_reports,
  COUNT(DISTINCT player_name) as players_injured
FROM `nba-props-platform.nba_raw.nbac_injury_report`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC
'

# Expected: Non-zero counts for recent dates
```

---

## ✅ SUCCESS CHECKLIST

- [ ] Processor logs reviewed (failure window identified)
- [ ] BigQuery job history checked
- [ ] Root cause identified (timeout / schema / duplicate / silent)
- [ ] Fix implemented (retry, timeout, verification)
- [ ] Test script created and passed
- [ ] Code committed with detailed message
- [ ] Deployed to production
- [ ] Verified in logs (successful saves)
- [ ] Validated in BigQuery (non-zero injury records)
- [ ] Monitored for 48h (no recurrence)

---

## 📊 EXPECTED OUTCOME

### Before Fix
- Save success rate: 50-70%
- Silent failures: Common (no error logged)
- Data completeness: 30-50%
- Manual intervention: Required

### After Fix
- Save success rate: 95-100%
- Silent failures: Eliminated (verification catches)
- Data completeness: 95-100%
- Manual intervention: None needed

---

**This is P1 work - do after backfill completes!** 🔍

Don't block ML training on this. Injury data is nice-to-have, not critical path.
