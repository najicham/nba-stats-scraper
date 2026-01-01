# Data Completeness Monitoring Implementation

**Created:** 2026-01-01
**Status:** IN PROGRESS 🔄
**Priority:** CRITICAL

---

## Overview

This document describes the implementation of automated data completeness monitoring to prevent silent failures from going undetected. The system will check daily for missing games and alert the team immediately.

---

## Problem Statement

### Current State ❌
- Data gaps discovered manually (days/weeks later)
- Processors return "success" with 0 rows inserted
- No automated checks for missing games
- No alerts when data is incomplete
- Manual SQL queries required to identify gaps

### Discovered Gaps (Jan 1, 2026)
```
Dec 31: 8 of 9 gamebooks missing
Dec 29: 10 gamebooks missing
Dec 28: 2 gamebooks + 2 BDL games missing
Nov 10-12: 35,991 BDL player box scores missing
```

### Detection Lag
- **Best case:** Same day (if manually checking)
- **Actual:** Multiple days (discovered by accident)
- **Worst case:** Never (if not queried)

---

## Solution Design

### Phase 1: Daily Completeness Checker ⭐ CRITICAL
**Timeline:** 3 hours
**Cost:** ~$0.13/month
**Status:** Implementation started

#### What It Does
1. Runs daily at 9 AM ET (after overnight processing)
2. Compares NBA schedule vs actual data in BigQuery
3. Identifies missing games by data source:
   - Gamebook player stats
   - BDL player box scores
4. Sends email alert with actionable report
5. Logs results for trending/analysis

#### Components

##### 1. SQL Query: `check_data_completeness.sql`
```sql
-- Compare schedule vs actual data
-- Returns: missing games by date and source

WITH schedule AS (
  SELECT
    game_date,
    game_id,
    game_code,
    home_team_tricode,
    away_team_tricode
  FROM nba_raw.nbac_schedule
  WHERE game_status_text = 'Final'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
gamebook_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr
  FROM nba_raw.nbac_gamebook_player_stats
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
bdl_games AS (
  SELECT DISTINCT
    game_date,
    home_team_abbr,
    away_team_abbr
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  s.game_date,
  s.game_code,
  CONCAT(s.away_team_tricode, '@', s.home_team_tricode) as matchup,
  CASE WHEN g.game_date IS NULL THEN 'MISSING' ELSE 'OK' END as gamebook_status,
  CASE WHEN b.game_date IS NULL THEN 'MISSING' ELSE 'OK' END as bdl_status
FROM schedule s
LEFT JOIN gamebook_games g
  ON s.game_date = g.game_date
  AND s.home_team_tricode = g.home_team_abbr
  AND s.away_team_tricode = g.away_team_abbr
LEFT JOIN bdl_games b
  ON s.game_date = b.game_date
  AND s.home_team_tricode = b.home_team_abbr
  AND s.away_team_tricode = b.away_team_abbr
WHERE g.game_date IS NULL OR b.game_date IS NULL
ORDER BY s.game_date DESC, s.game_code
```

##### 2. Cloud Function: `data_completeness_checker.py`
```python
# Location: functions/monitoring/data_completeness_checker/main.py

import functions_framework
from google.cloud import bigquery
from datetime import datetime, timedelta
import os

def send_email_alert(missing_games):
    """Send email with missing games report."""
    # Use existing email alerting system
    from shared.utils.email_alerting_ses import EmailAlerter

    subject = f"🚨 Data Completeness Alert - {len(missing_games)} Missing Games"

    body = format_html_report(missing_games)

    alerter = EmailAlerter()
    alerter.send_alert(subject=subject, body=body)

def format_html_report(missing_games):
    """Format missing games as HTML table."""
    # Group by date
    by_date = {}
    for game in missing_games:
        date = game['game_date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(game)

    html = """
    <html>
    <body>
    <h2>Daily Data Completeness Report</h2>
    <p><strong>Check Time:</strong> {check_time}</p>
    <p><strong>Missing Games:</strong> {total}</p>

    <table border="1" cellpadding="5">
    <tr>
        <th>Date</th>
        <th>Game</th>
        <th>Matchup</th>
        <th>Gamebook</th>
        <th>BDL</th>
    </tr>
    """.format(
        check_time=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        total=len(missing_games)
    )

    for date in sorted(by_date.keys(), reverse=True):
        for game in by_date[date]:
            html += f"""
            <tr>
                <td>{game['game_date']}</td>
                <td>{game['game_code']}</td>
                <td>{game['matchup']}</td>
                <td>{'❌ MISSING' if game['gamebook_status'] == 'MISSING' else '✅'}</td>
                <td>{'❌ MISSING' if game['bdl_status'] == 'MISSING' else '✅'}</td>
            </tr>
            """

    html += """
    </table>

    <h3>Recommended Actions</h3>
    <ol>
        <li>Check scraper logs for failed executions</li>
        <li>Verify GCS files exist for missing games</li>
        <li>Re-run scrapers for missing dates if needed</li>
        <li>Trigger backfill jobs</li>
    </ol>

    <p><em>This is an automated daily report from the NBA Stats Pipeline.</em></p>
    </body>
    </html>
    """

    return html

@functions_framework.http
def check_completeness(request):
    """Cloud Function entrypoint."""
    bq_client = bigquery.Client()

    # Run completeness query
    query = open('check_data_completeness.sql').read()
    results = list(bq_client.query(query).result())

    if results:
        # Missing games found - send alert
        missing_games = [dict(row) for row in results]
        send_email_alert(missing_games)

        # Log to orchestration table
        log_missing_games(bq_client, missing_games)

        return {
            'status': 'alert_sent',
            'missing_games': len(missing_games),
            'report': missing_games
        }, 200
    else:
        # All games present - no alert needed
        return {
            'status': 'ok',
            'message': 'All games accounted for',
            'missing_games': 0
        }, 200

def log_missing_games(bq_client, missing_games):
    """Log missing games to orchestration table for trending."""
    # TODO: Implement logging to nba_orchestration.missing_games_log
    pass
```

##### 3. Cloud Scheduler Job
```bash
# Name: daily-data-completeness-check
# Schedule: 0 14 * * * (9 AM ET = 14:00 UTC)
# Target: data-completeness-checker Cloud Function
# Timezone: UTC

gcloud scheduler jobs create http daily-data-completeness-check \
  --schedule="0 14 * * *" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/data-completeness-checker" \
  --http-method=POST \
  --time-zone="UTC" \
  --description="Daily check for missing game data"
```

##### 4. Orchestration Tables
```sql
-- Track all completeness checks
CREATE TABLE IF NOT EXISTS nba_orchestration.data_completeness_checks (
  check_id STRING NOT NULL,
  check_timestamp TIMESTAMP NOT NULL,
  missing_games_count INT64,
  alert_sent BOOL,
  check_duration_seconds FLOAT64,
  status STRING
);

-- Log missing games for trending
CREATE TABLE IF NOT EXISTS nba_orchestration.missing_games_log (
  log_id STRING NOT NULL,
  check_id STRING NOT NULL,
  game_date DATE NOT NULL,
  game_code STRING NOT NULL,
  matchup STRING,
  gamebook_missing BOOL,
  bdl_missing BOOL,
  discovered_at TIMESTAMP NOT NULL,
  backfilled_at TIMESTAMP
);
```

#### Deployment Steps

1. **Create SQL query file**
   ```bash
   mkdir -p functions/monitoring/data_completeness_checker
   # Create check_data_completeness.sql
   ```

2. **Create Cloud Function**
   ```bash
   # Create main.py, requirements.txt
   # Deploy function
   ```

3. **Create orchestration tables**
   ```bash
   # Run CREATE TABLE statements
   ```

4. **Set up Cloud Scheduler**
   ```bash
   # Create scheduler job
   ```

5. **Test manually**
   ```bash
   # Trigger function, verify email sent
   ```

---

### Phase 2: Enhanced Processor Validation 🔧 IMPORTANT
**Timeline:** 2 hours
**Cost:** $0 (no new infrastructure)
**Status:** Not started

#### What It Does
1. Enhance processor response validation
2. Flag `rows_processed: 0` as WARNING (not SUCCESS)
3. Log detailed reason for 0 rows:
   - "Smart idempotency: all rows already exist"
   - "Validation failed: X rows rejected"
   - "Season type: Pre Season (skipped intentionally)"
4. Alert on suspicious patterns:
   - Multiple consecutive 0-row results
   - Expected data but got 0 rows

#### Implementation

##### 1. Processor Response Handler
```python
# In data_processors/raw/processor_base.py

def save_data(self) -> dict:
    """Save data and validate result."""
    result = self._insert_to_bigquery()

    # VALIDATION: Check for suspicious 0-row results
    if result['rows_processed'] == 0:
        reason = self._get_zero_rows_reason()

        # Log warning
        logger.warning(
            f"Processor completed with 0 rows inserted. "
            f"Reason: {reason}"
        )

        # Decide if this is expected or suspicious
        if self._is_suspicious_zero_rows(reason):
            # Send alert
            notify_warning(
                title=f"{self.__class__.__name__} - No Rows Inserted",
                message=f"Processor returned 0 rows: {reason}",
                details={
                    'processor': self.__class__.__name__,
                    'file_path': self.opts.get('file_path'),
                    'reason': reason,
                    'run_id': self.processing_run_id
                }
            )

    return result

def _get_zero_rows_reason(self) -> str:
    """Get human-readable reason for 0 rows."""
    # Check various conditions
    if hasattr(self, 'idempotency_duplicates'):
        return f"Idempotency: {self.idempotency_duplicates} duplicate rows filtered"

    if hasattr(self, 'validation_errors'):
        return f"Validation failed: {len(self.validation_errors)} errors"

    if hasattr(self, 'season_type_skip'):
        return f"Season type: {self.season_type_skip} (skipped intentionally)"

    return "Unknown - needs investigation"

def _is_suspicious_zero_rows(self, reason: str) -> bool:
    """Determine if 0 rows is suspicious or expected."""
    expected_reasons = [
        'Pre Season',
        'All Star',
        'Idempotency'
    ]

    for expected in expected_reasons:
        if expected in reason:
            return False

    return True  # Suspicious!
```

##### 2. Enhanced Logging
```python
# In each processor's transform_data():

def transform_data(self) -> None:
    rows = []

    # Track skipped rows with reasons
    skip_reasons = defaultdict(int)

    for player in raw_data.get('active_players', []):
        try:
            row = self.process_player(player)
            rows.append(row)
        except ValidationError as e:
            skip_reasons[str(e)] += 1
            continue

    # Log summary
    if skip_reasons:
        logger.warning(
            f"Skipped {sum(skip_reasons.values())} rows. "
            f"Reasons: {dict(skip_reasons)}"
        )

    self.transformed_data = rows
```

---

### Phase 3: Auto-Backfill Workflow 🤖 NICE-TO-HAVE
**Timeline:** 4 hours
**Cost:** ~$0.02/month
**Status:** Not started

#### What It Does
1. Daily completeness check identifies gaps
2. Auto-queue backfill jobs via Cloud Tasks
3. Retry scraping + processing for missing games
4. Track success/failure
5. Manual intervention only for persistent failures

#### Implementation (High-level)

```python
# When completeness check finds missing games:

for missing_game in missing_games:
    # Create backfill task
    task = {
        'game_date': missing_game['game_date'],
        'game_code': missing_game['game_code'],
        'sources': []
    }

    if missing_game['gamebook_missing']:
        task['sources'].append('gamebook')

    if missing_game['bdl_missing']:
        task['sources'].append('bdl')

    # Queue task
    cloud_tasks_client.create_task(
        parent=queue_path,
        task={'http_request': {
            'url': 'https://.../backfill',
            'body': json.dumps(task).encode()
        }}
    )
```

---

## Deployment Schedule

### Day 1 (Today)
- [x] Document bugs
- [ ] Implement Phase 1 SQL query
- [ ] Build Phase 1 Cloud Function
- [ ] Create orchestration tables
- [ ] Deploy Phase 1
- [ ] Test with current gaps

### Day 2 (Tomorrow)
- [ ] Verify Phase 1 email received
- [ ] Implement Phase 2 validation
- [ ] Deploy Phase 2
- [ ] Monitor for 0-row alerts

### Week 1
- [ ] Analyze Phase 1/2 effectiveness
- [ ] Tune alert thresholds
- [ ] Plan Phase 3 implementation

---

## Success Metrics

### Phase 1
- ✅ Daily email report received
- ✅ All current gaps detected in report
- ✅ No false negatives (missed gaps)
- ⚠️ Low false positives (< 5%)

### Phase 2
- ✅ 0-row processors trigger warnings
- ✅ Reason codes logged for investigation
- ✅ Suspicious 0-rows alerted immediately

### Phase 3
- ✅ Missing games auto-backfilled
- ✅ 95%+ success rate on auto-backfill
- ✅ Manual intervention < 5% of gaps

---

## Monitoring the Monitoring

### Phase 1 Health Checks
- Scheduler job runs daily ✅
- Function executes successfully ✅
- Email alert delivered ✅
- Orchestration tables updated ✅

### Alerts on Monitor Failures
- Cloud Scheduler job fails → PagerDuty
- Cloud Function errors → Email alert
- Email delivery failure → Slack notification

---

## Cost Analysis

| Component | Usage | Cost/Month |
|-----------|-------|------------|
| Cloud Scheduler | 1 job @ 1/day | $0.10 |
| Cloud Function | 30 invocations | $0.001 |
| BigQuery | ~10 MB/day scan | < $0.01 |
| Email (SES) | ~30 emails/month | $0.01 |
| Cloud Tasks (Phase 3) | ~20 tasks/month | < $0.01 |
| **Total** | | **~$0.15/month** |

**ROI:** Prevents hours of manual investigation = $$$$ saved

---

## Related Documentation
- [Session Summary](./SESSION-JAN1-PM-DATA-GAPS.md)
- [Gamebook Bug](./GAMEBOOK-PROCESSOR-BUG.md)
- [BDL Bug](./BDL-PROCESSOR-BUG.md)
- [Data Completeness Architecture](./data-quality/data-completeness-architecture.md)
