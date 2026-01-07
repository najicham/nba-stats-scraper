# Layer 5 & Layer 6 Implementation Guide

**Date:** 2026-01-01 Evening Session
**Status:** 🔄 Ready to Implement
**Time Required:** 4-6 hours
**Priority:** ⭐⭐⭐⭐⭐ Critical for 2-minute detection

---

## 📋 QUICK START (TL;DR)

```bash
# 1. Add Layer 5 code to processor_base.py (Section 1 below)
# 2. Deploy processors
./bin/raw/deploy/deploy_processors_simple.sh

# 3. Create Layer 6 Cloud Function (Section 2 below)
# 4. Deploy real-time checker
gcloud functions deploy realtime-completeness-checker ...

# 5. Test with manual run
# 6. Monitor tonight's games for validation
```

**Result:** Missing game detection drops from **10 hours → 2 minutes** ⚡

---

## 🎯 WHAT WE'RE BUILDING

### Layer 5: Processor Output Validation
**Goal:** Catch 0-row bugs immediately (gamebook bug would have been caught in <1 second)

**How it works:**
```
Processor completes → Check: expected rows vs actual rows
  ↓
If actual = 0 but expected > 0:
  ↓
Diagnose reason → Is it acceptable?
  ↓
If NO: Send IMMEDIATE alert + log to BigQuery
```

**Detection time:** Immediate (during processing)

---

### Layer 6: Real-Time Completeness Check
**Goal:** Detect missing games 2 minutes after processing (vs 10 hours)

**How it works:**
```
Processor completes → Publish to Pub/Sub
  ↓
Cloud Function triggered → Track completion
  ↓
All expected processors done? → Run completeness check
  ↓
Compare schedule vs BigQuery → Missing games?
  ↓
If YES: Send alert + log missing games
```

**Detection time:** 2 minutes after all processors complete

---

## 📝 SECTION 1: LAYER 5 IMPLEMENTATION

### Step 1.1: Add Validation Code to processor_base.py

**File:** `data_processors/raw/processor_base.py`

**Location:** After line 187 (after `self.stats["save_time"] = save_seconds`)

**Add this code:**

```python
            # LAYER 5: Validate save result (catch 0-row bugs immediately)
            self._validate_and_log_save_result()
```

**Full context (lines 183-193):**
```python
            # Save to BigQuery
            self.mark_time("save")
            self.save_data()
            save_seconds = self.get_elapsed_seconds("save")
            self.stats["save_time"] = save_seconds

            # LAYER 5: Validate save result (catch 0-row bugs immediately)
            self._validate_and_log_save_result()

            # Publish Phase 2 completion event (triggers Phase 3)
            self._publish_completion_event()

            # Complete
```

---

### Step 1.2: Add Validation Methods

**Location:** Right BEFORE the `save_data()` method (around line 460)

**Add ALL these methods:**

```python
    def _validate_and_log_save_result(self) -> None:
        """
        LAYER 5: Validate processor output to catch silent failures.

        Detects suspicious patterns like:
        - Expected data but got 0 rows (gamebook bug scenario)
        - Partial writes (some rows failed silently)
        - Stats mismatch (processor returned different count than self.stats)

        Logs all results to monitoring table and sends alerts for critical issues.
        """
        try:
            # Get actual rows inserted from stats
            actual_rows = self.stats.get('rows_inserted', 0)

            # Estimate expected rows based on input data
            expected_rows = self._estimate_expected_rows()

            # Validate result
            validation_result = {
                'processor_name': self.__class__.__name__,
                'file_path': self.opts.get('file_path', ''),
                'game_date': str(self.opts.get('game_date', '')),
                'expected_rows': expected_rows,
                'actual_rows': actual_rows,
                'is_valid': True,
                'severity': 'OK',
                'issue_type': None,
                'reason': None,
            }

            # CASE 1: Zero rows when we expected data
            if actual_rows == 0 and expected_rows > 0:
                reason = self._diagnose_zero_rows()
                is_acceptable = self._is_acceptable_zero_rows(reason)

                validation_result.update({
                    'is_valid': is_acceptable,
                    'severity': 'INFO' if is_acceptable else 'CRITICAL',
                    'issue_type': 'zero_rows',
                    'reason': reason
                })

                # Alert if unexpected
                if not is_acceptable:
                    self._send_zero_row_alert(validation_result)

            # CASE 2: Partial write (significant data loss)
            elif 0 < actual_rows < expected_rows * 0.9:  # >10% loss
                validation_result.update({
                    'is_valid': False,
                    'severity': 'WARNING',
                    'issue_type': 'partial_write',
                    'reason': f'{((expected_rows - actual_rows) / expected_rows * 100):.1f}% of data lost'
                })

                notify_warning(
                    title=f"{self.__class__.__name__}: Partial Data Loss",
                    message=f"Expected {expected_rows} rows but only saved {actual_rows}",
                    details=validation_result
                )

            # Log all validations to monitoring table (for trending)
            self._log_processor_metrics(validation_result)

        except Exception as e:
            # Don't fail processor if validation fails
            logger.warning(f"Output validation failed: {e}")

    def _estimate_expected_rows(self) -> int:
        """Estimate expected output rows based on input data."""
        # If we have transformed data, that's our expectation
        if hasattr(self, 'transformed_data'):
            if isinstance(self.transformed_data, list):
                return len(self.transformed_data)
            elif isinstance(self.transformed_data, dict):
                return 1

        # Fallback: check raw_data size as rough estimate
        if hasattr(self, 'raw_data'):
            if isinstance(self.raw_data, list):
                return len(self.raw_data)
            elif isinstance(self.raw_data, dict):
                # Check for common patterns
                if 'stats' in self.raw_data:
                    return len(self.raw_data.get('stats', []))
                if 'players' in self.raw_data:
                    return len(self.raw_data.get('players', []))
                return 1

        return 0

    def _diagnose_zero_rows(self) -> str:
        """Diagnose why 0 rows were saved."""
        reasons = []

        # Check if data was loaded
        if not hasattr(self, 'raw_data') or not self.raw_data:
            reasons.append("No raw data loaded")

        # Check if transform produced output
        if not hasattr(self, 'transformed_data') or not self.transformed_data:
            reasons.append("Transform produced empty dataset")
        elif len(self.transformed_data) == 0:
            reasons.append("Transformed data is empty array")

        # Check for idempotency/deduplication
        if hasattr(self, 'idempotency_stats'):
            skipped = self.idempotency_stats.get('rows_skipped', 0)
            if skipped > 0:
                reasons.append(f"Smart idempotency: {skipped} duplicates skipped")

        # Check run history
        if self.stats.get('rows_skipped_by_run_history'):
            reasons.append("Skipped by run history (already processed)")

        return " | ".join(reasons) if reasons else "Unknown - needs investigation"

    def _is_acceptable_zero_rows(self, reason: str) -> bool:
        """Determine if 0-row result is expected/acceptable."""
        acceptable_patterns = [
            "Smart idempotency",
            "duplicates skipped",
            "Preseason",
            "All-Star",
            "No games scheduled",
            "Already processed",
            "Off season"
        ]
        return any(pattern.lower() in reason.lower() for pattern in acceptable_patterns)

    def _send_zero_row_alert(self, validation_result: dict) -> None:
        """Send immediate alert for unexpected 0-row result."""
        try:
            notify_warning(
                title=f"⚠️ {self.__class__.__name__}: Zero Rows Saved",
                message=f"Expected {validation_result['expected_rows']} rows but saved 0",
                details={
                    'processor': validation_result['processor_name'],
                    'reason': validation_result['reason'],
                    'file_path': validation_result['file_path'],
                    'game_date': validation_result['game_date'],
                    'severity': validation_result['severity'],
                    'run_id': getattr(self, 'run_id', None),
                    'detection_layer': 'Layer 5: Processor Output Validation',
                    'detection_time': datetime.now(timezone.utc).isoformat()
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send zero-row alert: {e}")

    def _log_processor_metrics(self, validation_result: dict) -> None:
        """Log processor output validation to monitoring table."""
        try:
            # Only log if we have project_id
            if not hasattr(self, 'project_id') or not self.project_id:
                return

            table_id = f"{self.project_id}.nba_orchestration.processor_output_validation"

            row = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'processor_name': validation_result['processor_name'],
                'file_path': validation_result['file_path'],
                'game_date': validation_result['game_date'] or None,
                'expected_rows': validation_result['expected_rows'],
                'actual_rows': validation_result['actual_rows'],
                'issue_type': validation_result['issue_type'],
                'severity': validation_result['severity'],
                'reason': validation_result['reason'],
                'is_acceptable': validation_result['is_valid'],
                'run_id': getattr(self, 'run_id', None)
            }

            # Insert to monitoring table (non-blocking)
            errors = self.bq_client.insert_rows_json(table_id, [row])
            if errors:
                logger.warning(f"Failed to log processor metrics: {errors}")

        except Exception as e:
            # Don't fail processor if logging fails
            logger.debug(f"Could not log processor metrics: {e}")
```

---

### Step 1.3: Deploy Processors

```bash
# Deploy with Layer 5 validation
cd /home/naji/code/nba-stats-scraper
./bin/raw/deploy/deploy_processors_simple.sh

# Wait for deployment (5-6 minutes)
# Verify deployment
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"
```

**Expected output:** New revision number (e.g., `nba-phase2-raw-processors-00058-xxx`)

---

### Step 1.4: Verify BigQuery Table Exists

```bash
# Table should already exist (created in this session)
bq show nba_orchestration.processor_output_validation

# If NOT exists, create it:
bq mk --table \
  --project_id=nba-props-platform \
  --time_partitioning_field=timestamp \
  --time_partitioning_type=DAY \
  --description="Layer 5: Processor output validation" \
  --label=system:monitoring \
  --label=layer:processor_validation \
  nba_orchestration.processor_output_validation \
  timestamp:TIMESTAMP,processor_name:STRING,file_path:STRING,game_date:DATE,expected_rows:INTEGER,actual_rows:INTEGER,issue_type:STRING,severity:STRING,reason:STRING,is_acceptable:BOOLEAN,run_id:STRING
```

---

### Step 1.5: Test Layer 5

**Manual test - trigger a processor:**

```bash
# Republish one gamebook file that has data
# This should trigger validation and log to monitoring table

# Get a file path
FILE_PATH="nba-com/gamebooks-data/2025-12-31/20251231-DENTOR/20260101_090646.json"

# Publish test message
python3 - <<EOF
from google.cloud import pubsub_v1
import json

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('nba-props-platform', 'nba-phase1-scrapers-complete')

message_data = {
    'bucket': 'nba-scraped-data',
    'name': '$FILE_PATH',
    'metageneration': '1'
}

message_json = json.dumps(message_data)
future = publisher.publish(topic_path, message_json.encode('utf-8'))
print(f"Published: {future.result()}")
EOF

# Wait 30 seconds, then check monitoring table
sleep 30

bq query --use_legacy_sql=false "
SELECT
  timestamp,
  processor_name,
  expected_rows,
  actual_rows,
  severity,
  reason
FROM nba_orchestration.processor_output_validation
ORDER BY timestamp DESC
LIMIT 5
"
```

**Expected result:**
- ✅ Row appears in monitoring table
- ✅ `actual_rows` > 0 for successful run
- ✅ `severity` = 'OK' for normal case

**Test 0-row alert:**
- Temporarily break a processor to return 0 rows
- Verify alert is sent immediately
- Check email for warning

---

## 📝 SECTION 2: LAYER 6 IMPLEMENTATION

### Step 2.1: Create Real-Time Completeness Checker

**Create directory:**
```bash
mkdir -p functions/monitoring/realtime_completeness_checker
```

**File:** `functions/monitoring/realtime_completeness_checker/main.py`

```python
"""
Layer 6: Real-Time Completeness Checker

Triggered when Phase 2 processors complete.
Checks if all processors done for that date.
Runs completeness check if so.
Detects missing games in ~2 minutes vs 10 hours.
"""

import functions_framework
from google.cloud import bigquery
from datetime import datetime
import json
import base64
import uuid


@functions_framework.cloud_event
def check_completeness_realtime(cloud_event):
    """
    Triggered when Phase 2 processor completes.
    Checks if all processors done for that date.
    Runs completeness check if so.
    """

    # Parse Pub/Sub message
    message_data = json.loads(
        base64.b64decode(cloud_event.data["message"]["data"])
    )

    processor_name = message_data.get('processor_name')
    game_date = message_data.get('game_date')
    status = message_data.get('status')
    rows_processed = message_data.get('rows_processed', 0)

    print(f"📥 Processor completed: {processor_name} for {game_date}")
    print(f"   Status: {status}, Rows: {rows_processed}")

    # Track this completion
    track_processor_completion(
        processor_name=processor_name,
        game_date=game_date,
        status=status,
        rows_processed=rows_processed
    )

    # Check if all expected processors have completed
    expected_processors = get_expected_processors_for_date(game_date)
    completed_processors = get_completed_processors(game_date)

    pending = set(expected_processors) - set(completed_processors)

    if pending:
        print(f"⏳ Waiting for: {pending}")
        return {
            'status': 'waiting',
            'game_date': game_date,
            'completed': list(completed_processors),
            'pending': list(pending)
        }

    # All processors done - run completeness check
    print(f"✅ All processors complete for {game_date}, checking completeness...")

    missing_games = check_completeness_for_date(game_date)

    if missing_games:
        send_immediate_alert(game_date, missing_games)
        log_missing_games(game_date, missing_games)

        print(f"⚠️  {len(missing_games)} games missing for {game_date}")
        return {
            'status': 'gaps_found',
            'game_date': game_date,
            'missing_count': len(missing_games),
            'games': missing_games
        }
    else:
        print(f"🎉 All games accounted for {game_date}")
        return {
            'status': 'complete',
            'game_date': game_date,
            'missing_count': 0
        }


def get_expected_processors_for_date(game_date):
    """Return list of processors that should run for this date."""
    # Core processors that must complete
    return [
        'NbacGamebookProcessor',
        'BdlPlayerBoxScoresProcessor',
        'BdlLiveBoxscoresProcessor'
    ]


def track_processor_completion(processor_name, game_date, status, rows_processed):
    """Record processor completion."""
    bq_client = bigquery.Client()
    table_id = "nba-props-platform.nba_orchestration.processor_completions"

    row = {
        'processor_name': processor_name,
        'game_date': str(game_date),
        'completed_at': datetime.utcnow().isoformat(),
        'status': status,
        'rows_processed': rows_processed
    }

    errors = bq_client.insert_rows_json(table_id, [row])
    if errors:
        print(f"❌ Error tracking completion: {errors}")


def get_completed_processors(game_date):
    """Get processors that completed in last 2 hours for this date."""
    bq_client = bigquery.Client()

    query = f"""
    SELECT DISTINCT processor_name
    FROM `nba-props-platform.nba_orchestration.processor_completions`
    WHERE game_date = '{game_date}'
      AND completed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
      AND status = 'success'
    """

    results = list(bq_client.query(query).result())
    return [row.processor_name for row in results]


def check_completeness_for_date(game_date):
    """Run completeness check for specific date."""
    bq_client = bigquery.Client()

    # Use same SQL as daily checker but for this date only
    query = f"""
    WITH schedule AS (
      SELECT DISTINCT
        game_date,
        game_code,
        home_team_tricode,
        away_team_tricode
      FROM `nba-props-platform.nba_raw.nbac_schedule`
      WHERE game_date = '{game_date}'
    ),
    gamebook_games AS (
      SELECT
        game_date,
        game_code,
        COUNT(DISTINCT player_lookup) as player_count
      FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
      WHERE game_date = '{game_date}'
      GROUP BY game_date, game_code
      HAVING COUNT(DISTINCT player_lookup) >= 10
    ),
    bdl_games AS (
      SELECT
        game_date,
        CONCAT(
          FORMAT_DATE('%Y%m%d', game_date),
          '_',
          away_team_abbr,
          '_',
          home_team_abbr
        ) as game_code,
        COUNT(DISTINCT player_lookup) as player_count
      FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
      WHERE game_date = '{game_date}'
      GROUP BY game_date, game_code, away_team_abbr, home_team_abbr
      HAVING COUNT(DISTINCT player_lookup) >= 10
    )

    SELECT
      s.game_date,
      s.game_code,
      CONCAT(s.away_team_tricode, '@', s.home_team_tricode) as matchup,

      CASE
        WHEN g.game_code IS NULL THEN 'MISSING'
        WHEN g.player_count < 10 THEN 'INCOMPLETE'
        ELSE 'OK'
      END as gamebook_status,
      COALESCE(g.player_count, 0) as gamebook_players,

      CASE
        WHEN b.game_code IS NULL THEN 'MISSING'
        WHEN b.player_count < 10 THEN 'INCOMPLETE'
        ELSE 'OK'
      END as bdl_status,
      COALESCE(b.player_count, 0) as bdl_players

    FROM schedule s
    LEFT JOIN gamebook_games g ON s.game_code = g.game_code
    LEFT JOIN bdl_games b ON s.game_code = b.game_code

    WHERE g.game_code IS NULL
       OR b.game_code IS NULL
       OR g.player_count < 10
       OR b.player_count < 10
    """

    results = list(bq_client.query(query).result())
    return [dict(row) for row in results]


def send_immediate_alert(game_date, missing_games):
    """Send immediate alert for missing games."""
    # Import email alerter
    import sys
    sys.path.insert(0, '/workspace')

    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
    except ImportError:
        print("⚠️  Email alerting not available in this environment")
        return

    subject = f"⚠️ Real-Time Alert: {len(missing_games)} Games Missing for {game_date}"

    body_html = f"""
    <h2>⚠️ Data Gaps Detected Immediately After Processing</h2>
    <p><strong>Date:</strong> {game_date}</p>
    <p><strong>Missing Games:</strong> {len(missing_games)}</p>
    <p><strong>Detection Time:</strong> ~2 minutes after processing</p>
    <p><strong>Detection Layer:</strong> Layer 6 - Real-Time Completeness Check</p>

    <table border="1" style="border-collapse: collapse;">
        <tr style="background-color: #f0f0f0;">
            <th style="padding: 8px;">Game</th>
            <th style="padding: 8px;">Matchup</th>
            <th style="padding: 8px;">Gamebook</th>
            <th style="padding: 8px;">BDL</th>
        </tr>
    """

    for game in missing_games:
        gamebook_cell = (
            '✅ OK' if game['gamebook_status'] == 'OK'
            else f"❌ {game['gamebook_status']}"
        )
        bdl_cell = (
            '✅ OK' if game['bdl_status'] == 'OK'
            else f"❌ {game['bdl_status']}"
        )

        body_html += f"""
        <tr>
            <td style="padding: 8px;">{game['game_code']}</td>
            <td style="padding: 8px;">{game['matchup']}</td>
            <td style="padding: 8px;">{gamebook_cell}</td>
            <td style="padding: 8px;">{bdl_cell}</td>
        </tr>
        """

    body_html += """
    </table>

    <h3>Recommended Actions:</h3>
    <ol>
        <li>Check processor logs for errors</li>
        <li>Verify GCS files exist and are complete</li>
        <li>Check scraper execution logs</li>
        <li>Trigger backfill if needed</li>
    </ol>

    <p style="color: #666; font-size: 12px;">
    This is a real-time alert triggered immediately after processors completed.
    You're receiving this 2 minutes after processing, not 10 hours later.
    Detection lag reduced by 98%.
    </p>
    """

    try:
        alerter._send_email(
            subject=subject,
            body_html=body_html,
            recipients=alerter.alert_recipients,
            alert_level="WARNING"
        )
        print(f"✅ Alert email sent to {alerter.alert_recipients}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def log_missing_games(game_date, missing_games):
    """Log missing games to tracking table."""
    bq_client = bigquery.Client()
    table_id = "nba-props-platform.nba_orchestration.missing_games_log"

    check_id = str(uuid.uuid4())

    rows = []
    for game in missing_games:
        rows.append({
            'log_id': str(uuid.uuid4()),
            'check_id': check_id,
            'game_date': str(game['game_date']),
            'game_code': game['game_code'],
            'matchup': game['matchup'],
            'gamebook_missing': game['gamebook_status'] != 'OK',
            'bdl_missing': game['bdl_status'] != 'OK',
            'discovered_at': datetime.utcnow().isoformat(),
            'backfilled_at': None
        })

    errors = bq_client.insert_rows_json(table_id, rows)
    if errors:
        print(f"❌ Error logging missing games: {errors}")
```

---

**File:** `functions/monitoring/realtime_completeness_checker/requirements.txt`

```
functions-framework==3.*
google-cloud-bigquery
google-cloud-storage
google-cloud-pubsub
```

---

### Step 2.2: Create BigQuery Tables

```bash
# Table 1: Track processor completions
bq mk --table \
  --project_id=nba-props-platform \
  --time_partitioning_field=game_date \
  --time_partitioning_type=DAY \
  --description="Layer 6: Tracks processor completions for real-time monitoring" \
  --label=system:monitoring \
  --label=layer:realtime_completeness \
  nba_orchestration.processor_completions \
  processor_name:STRING,game_date:DATE,completed_at:TIMESTAMP,status:STRING,rows_processed:INTEGER

# Table 2 (missing_games_log) should already exist from evening session
# Verify it exists:
bq show nba_orchestration.missing_games_log

# If NOT exists, create it:
bq mk --table \
  --project_id=nba-props-platform \
  --time_partitioning_field=game_date \
  --time_partitioning_type=DAY \
  --description="Logs individual missing games discovered by monitoring" \
  nba_orchestration.missing_games_log \
  log_id:STRING,check_id:STRING,game_date:DATE,game_code:STRING,matchup:STRING,gamebook_missing:BOOLEAN,bdl_missing:BOOLEAN,discovered_at:TIMESTAMP,backfilled_at:TIMESTAMP
```

---

### Step 2.3: Deploy Real-Time Checker

```bash
# Deploy Cloud Function
gcloud functions deploy realtime-completeness-checker \
  --gen2 \
  --runtime=python312 \
  --region=us-west2 \
  --source=functions/monitoring/realtime_completeness_checker \
  --entry-point=check_completeness_realtime \
  --trigger-topic=nba-phase2-raw-complete \
  --timeout=540 \
  --memory=512MB \
  --service-account=nba-props-platform@appspot.gserviceaccount.com

# Wait for deployment (2-3 minutes)

# Verify deployment
gcloud functions describe realtime-completeness-checker \
  --region=us-west2 \
  --gen2 \
  --format="value(state,updateTime)"
```

**Expected output:** `ACTIVE` state

---

### Step 2.4: Test Layer 6

**Trigger a processor and watch for real-time check:**

```bash
# Publish a test message
python3 - <<EOF
from google.cloud import pubsub_v1
import json

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('nba-props-platform', 'nba-phase1-scrapers-complete')

message_data = {
    'bucket': 'nba-scraped-data',
    'name': 'nba-com/gamebooks-data/2025-12-31/20251231-DENTOR/20260101_090646.json'
}

future = publisher.publish(topic_path, json.dumps(message_data).encode('utf-8'))
print(f"Published: {future.result()}")
EOF

# Wait 2-3 minutes for:
# 1. Processor to run
# 2. Real-time checker to trigger
# 3. Completeness check to run

# Check function logs
gcloud functions logs read realtime-completeness-checker \
  --region=us-west2 \
  --gen2 \
  --limit=50

# Check processor_completions table
bq query --use_legacy_sql=false "
SELECT * FROM nba_orchestration.processor_completions
ORDER BY completed_at DESC
LIMIT 5
"
```

**Expected:**
- ✅ Processor completion tracked
- ✅ Function triggered
- ✅ Completeness check ran
- ✅ Alert sent if gaps found (or "all complete" logged)

---

## 🧪 SECTION 3: COMPREHENSIVE TESTING

### Test 1: Layer 5 Catches 0-Row Bug

**Simulate the gamebook bug:**

1. Temporarily modify gamebook processor to NOT update self.stats
2. Run a test file
3. Verify Layer 5 sends alert immediately

**Expected:**
- ✅ Email alert: "Zero Rows Saved"
- ✅ Alert details include diagnosis
- ✅ Logged to processor_output_validation table

---

### Test 2: Layer 6 Detects Missing Game

**Simulate missing data:**

1. Wait for tonight's games
2. Manually delete one game from BigQuery after processing
3. Verify Layer 6 detects it

**Expected:**
- ✅ Real-time check finds missing game
- ✅ Alert sent within 2 minutes
- ✅ Logged to missing_games_log

---

### Test 3: End-to-End Flow

**Full pipeline test:**

1. Tonight's games run naturally
2. Monitor both layers
3. Verify detection times

**Expected timeline:**
```
11:00 PM - Games finish
11:05 PM - Scrapers run
11:10 PM - Processors run
11:10 PM - Layer 5: Validates each processor (immediate)
11:12 PM - Layer 6: All processors done, checks completeness (2 min)
11:13 PM - Alert if any gaps (vs 9 AM next day = 10 hours)
```

---

## 📊 SECTION 4: MONITORING QUERIES

### Check Layer 5 Validations

```sql
-- Recent validation results
SELECT
  timestamp,
  processor_name,
  game_date,
  expected_rows,
  actual_rows,
  severity,
  reason
FROM nba_orchestration.processor_output_validation
ORDER BY timestamp DESC
LIMIT 20;

-- Critical issues only
SELECT
  DATE(timestamp) as date,
  processor_name,
  COUNT(*) as critical_issues
FROM nba_orchestration.processor_output_validation
WHERE severity = 'CRITICAL'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date, processor_name
ORDER BY date DESC;
```

---

### Check Layer 6 Completeness

```sql
-- Recent completeness checks
SELECT
  game_date,
  COUNT(*) as missing_games,
  STRING_AGG(matchup, ', ') as games
FROM nba_orchestration.missing_games_log
WHERE discovered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND backfilled_at IS NULL
GROUP BY game_date
ORDER BY game_date DESC;

-- Detection timeline
SELECT
  game_date,
  MIN(discovered_at) as first_detection,
  COUNT(*) as gap_count
FROM nba_orchestration.missing_games_log
WHERE discovered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## ⚠️ TROUBLESHOOTING

### Issue: Linter Removes Code Changes

**Problem:** Auto-formatter reverts processor_base.py changes

**Solutions:**

1. **Disable linter temporarily:**
   ```bash
   # Add to .gitignore or linter config
   # Disable for specific lines:
   # fmt: off
   self._validate_and_log_save_result()
   # fmt: on
   ```

2. **Commit immediately after changes:**
   ```bash
   git add data_processors/raw/processor_base.py
   git commit -m "feat: Add Layer 5 processor output validation"
   # Prevents linter from running
   ```

3. **Use Edit tool carefully:**
   - Make small, targeted changes
   - Don't leave gaps in line numbers
   - Commit each change immediately

---

### Issue: BigQuery Table Not Found

**Problem:** `processor_output_validation` table doesn't exist

**Solution:**
```bash
bq mk --table \
  --project_id=nba-props-platform \
  --time_partitioning_field=timestamp \
  --time_partitioning_type=DAY \
  nba_orchestration.processor_output_validation \
  timestamp:TIMESTAMP,processor_name:STRING,file_path:STRING,game_date:DATE,expected_rows:INTEGER,actual_rows:INTEGER,issue_type:STRING,severity:STRING,reason:STRING,is_acceptable:BOOLEAN,run_id:STRING
```

---

### Issue: Cloud Function Import Errors

**Problem:** Can't import shared utils in Cloud Function

**Solutions:**

1. **Remove shared imports** (email alerting is optional)
2. **Use inline notification** (print statements)
3. **Deploy shared utils** as separate package

---

## 📝 SECTION 5: ROLLBACK PLAN

If issues arise, rollback is simple:

### Rollback Layer 5

```bash
# Revert code changes
git checkout HEAD -- data_processors/raw/processor_base.py

# Re-deploy processors
./bin/raw/deploy/deploy_processors_simple.sh

# Table can stay (won't receive data but harmless)
```

---

### Rollback Layer 6

```bash
# Delete Cloud Function
gcloud functions delete realtime-completeness-checker \
  --region=us-west2 \
  --gen2

# Tables can stay (for future use)
```

---

## 🎯 SUCCESS CRITERIA

### Layer 5 Success

- ✅ Code deployed without linter issues
- ✅ Validation runs on every processor completion
- ✅ 0-row bugs trigger immediate alerts
- ✅ Acceptable 0-rows (idempotency) logged but not alerted
- ✅ All results logged to monitoring table

### Layer 6 Success

- ✅ Cloud Function deploys successfully
- ✅ Triggers when processors complete
- ✅ Detects missing games within 2 minutes
- ✅ Sends email alerts for gaps
- ✅ Logs to missing_games_log table

### Combined Success

- ✅ Detection lag: 10 hours → 2 minutes (98% reduction)
- ✅ 0-row bugs caught immediately (vs never)
- ✅ No false positives (smart filtering works)
- ✅ Tonight's games monitored successfully

---

## 📈 METRICS TO TRACK

### Before (Baseline)

- Detection lag: 10 hours (next morning check)
- False negatives: Unknown (silent failures)
- Manual intervention: Required every time

### After (Target)

- Detection lag: 2 minutes (real-time)
- False negatives: 0% (caught by 2 layers)
- Manual intervention: Triggered by alerts (80% reduction)

---

## 🚀 NEXT STEPS AFTER IMPLEMENTATION

1. **Monitor for 1 week**
   - Collect metrics
   - Tune alert thresholds
   - Fix false positives

2. **Implement Layer 1** (Scraper Output Validation)
   - Catch API gaps before processing
   - ~3-4 hours

3. **Add Dashboard** (Admin portal widgets)
   - Visual pipeline health
   - One-click backfill buttons
   - ~4-5 hours

4. **Fix Gamebook Architecture**
   - Game-level run history tracking
   - Proper backfill support
   - ~4-6 hours

---

## 📚 DOCUMENTATION LINKS

- **Architecture:** `ULTRA-DEEP-THINK-DETECTION-ARCHITECTURE.md`
- **Gamebook Issue:** `GAMEBOOK-RUN-HISTORY-ARCHITECTURAL-ISSUE.md`
- **Evening Handoff:** `HANDOFF-JAN1-EVENING-MONITORING-COMPLETE.md`
- **Gamebook Fix:** `GAMEBOOK-PROCESSOR-BUG-FIX.md`

---

## ✅ FINAL CHECKLIST

Before starting:
- [ ] Read this entire document
- [ ] Check git status (clean working directory)
- [ ] Verify BigQuery tables exist
- [ ] Have email configured for alerts

Implementation:
- [ ] Add Layer 5 code to processor_base.py
- [ ] Deploy processors
- [ ] Test Layer 5 with manual run
- [ ] Create Layer 6 Cloud Function
- [ ] Deploy Cloud Function
- [ ] Test Layer 6 with manual trigger
- [ ] Monitor tonight's games

After completion:
- [ ] Document results
- [ ] Update handoff for next session
- [ ] Tune alert thresholds if needed

---

**Estimated time:** 4-6 hours total
- Layer 5: 2-3 hours
- Layer 6: 2-3 hours

**Impact:** Detection lag 10 hours → 2 minutes ⚡

**You've got this! Everything is documented step-by-step. 🚀**
