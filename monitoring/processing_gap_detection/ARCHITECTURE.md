# Processing Gap Detection System - Architecture

**Version:** 1.0  
**Last Updated:** October 4, 2025  
**Status:** Production Ready

---

## Executive Summary

The Processing Gap Detection System monitors NBA data processing pipelines to detect when scraped files exist in Google Cloud Storage but have not been processed into BigQuery. This indicates potential failures in Pub/Sub messaging, processor errors, or pipeline disruptions that could impact revenue-generating prop betting operations.

**Key Capabilities:**
- Detects unprocessed GCS files within configurable tolerance windows
- Supports multiple GCS path patterns (simple date-based, nested structures)
- Sends alerts via Slack and Email with retry information
- Provides foundation for Phase 2 automated retry system

---

## System Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    SCHEDULED MONITORING JOB                     │
│                   (Cloud Run - us-west2)                        │
│                                                                 │
│  ┌──────────────────┐      ┌──────────────────┐               │
│  │  Gap Detector    │──────│ Processor Config │               │
│  │  Core Logic      │      │   Registry       │               │
│  └────────┬─────────┘      └──────────────────┘               │
│           │                                                     │
│           │                                                     │
│  ┌────────▼─────────┐      ┌──────────────────┐               │
│  │ GCS Inspector    │      │ Notification     │               │
│  │ File Discovery   │      │   System         │               │
│  └────────┬─────────┘      └────────┬─────────┘               │
└───────────┼────────────────────────┼─────────────────────────┘
            │                        │
            │                        │
    ┌───────▼────────┐      ┌────────▼─────────┐
    │ Google Cloud   │      │ Slack Webhooks   │
    │   Storage      │      │ Email (Brevo)    │
    │   BigQuery     │      └──────────────────┘
    └────────────────┘
```

### Component Interactions

1. **Cloud Run Job (Scheduled)**
   - Runs on schedule (configured for NBA season start)
   - Can be triggered manually via gcloud CLI
   - Passes date range and processor filters as arguments

2. **Gap Detector** (`utils/gap_detector.py`)
   - Orchestrates checking all enabled processors
   - Compares GCS file existence against BigQuery records
   - Enforces tolerance windows before alerting
   - **Critical Fix (Oct 4, 2025):** Path normalization to match BigQuery storage format

3. **GCS Inspector** (`utils/gcs_inspector.py`)
   - Lists files matching GCS patterns
   - Returns latest file for a given date/prefix
   - Provides file creation timestamps

4. **Processor Config Registry** (`config/processor_config.py`)
   - Centralized configuration for all monitored processors
   - Defines GCS patterns, BigQuery tables, tolerance hours
   - Supports multiple pattern types for extensibility

5. **Notification System** (`shared/utils/notification_system.py`)
   - Sends alerts to Slack (#gap-monitoring channel)
   - Sends email alerts via Brevo (when configured)
   - Provides structured error/warning/info messages

---

## Data Flow

### Successful Processing (No Gap)

```
Scraper → GCS File Created → Pub/Sub Message → Processor Triggered
                                                        ↓
                                              BigQuery Insert
                                                        ↓
                                              Gap Monitor Check
                                                        ↓
                                                   ✅ File Found
                                                   No Alert Sent
```

### Failed Processing (Gap Detected)

```
Scraper → GCS File Created → Pub/Sub Message → ❌ Processor Fails
              ↓
              │  (tolerance window: 6-24 hours)
              ↓
        Gap Monitor Check
              ↓
        ❌ File NOT in BigQuery
              ↓
        🚨 Alert Sent (Slack + Email)
              ↓
        Log Retry Information (Phase 2)
```

---

## Design Decisions

### 1. Standalone Cloud Run Job (Not a Processor)

**Decision:** Gap monitoring runs as a separate scheduled Cloud Run job rather than being integrated into the processor workflow.

**Rationale:**
- Monitoring should be independent of the system it monitors
- Can run on different schedule than data processing (e.g., hourly checks)
- Easier to debug monitoring issues without affecting data pipeline
- Allows checking multiple days/processors in a single run

### 2. Path Normalization Strategy

**Problem:** BigQuery stores paths without bucket prefix, GCS returns full paths.
- BigQuery: `nba-com/player-list/2025-10-01/file.json`
- GCS: `gs://nba-scraped-data/nba-com/player-list/2025-10-01/file.json`

**Solution:** `_normalize_file_path()` method strips `gs://bucket/` prefix before querying BigQuery.

**Implementation:** Applied in both `_check_file_processed()` and `_get_record_count()`.

### 3. Multiple GCS Pattern Support

**Requirement:** Different scrapers use different GCS path structures.

**Solution:** Three pattern types with extensible design:
```python
'gcs_pattern_type': 'simple_date'     # {source}/{type}/{date}/
'gcs_pattern_type': 'date_nested'     # {source}/{type}/{date}/{subdir}/
'gcs_pattern_type': 'season_based'    # {source}/{type}/{season}/
```

**Future:** Pattern-specific GCS inspection logic for nested structures.

### 4. Tolerance Windows

**Design:** Each processor defines `tolerance_hours` before alerting.

**Examples:**
- Critical processors (boxscores): 4 hours
- Player lists: 6 hours
- Standings: 12 hours

**Rationale:**
- Prevents false alerts for files still within processing window
- Accounts for different data urgency levels
- Configurable per processor based on business requirements

### 5. Direct Notification System Import

**Problem:** Shared `__init__.py` loads unnecessary dependencies (pub/sub, fuzzywuzzy).

**Solution:** Direct import of `notification_system.py` via `importlib.util`.

**Trade-off:** Less elegant but avoids dependency bloat in monitoring job.

---

## Database Schema Requirements

### BigQuery Table Requirements

All monitored processors must have:

1. **source_file_path field** (or configurable equivalent)
   - Stores GCS path WITHOUT `gs://bucket/` prefix
   - Used for gap detection queries
   - Type: STRING

2. **Partition/Clustering** (recommended)
   - Partitioning by date reduces query costs
   - Clustering by source_file_path improves lookup performance

### Example Schema:
```sql
CREATE TABLE `nba_raw.example_table` (
  -- Data fields...
  source_file_path STRING NOT NULL,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(processed_at)
CLUSTER BY source_file_path;
```

---

## Error Handling

### Failure Scenarios

1. **GCS Access Denied**
   - Logs error, skips processor
   - Continues checking other processors
   - Does not send false alerts

2. **BigQuery Query Failure**
   - Logs error with query details
   - Returns `processed = False` (conservative)
   - Alerts may be triggered (better safe than sorry)

3. **Notification System Failure**
   - Logs error but continues monitoring
   - Falls back to console logging
   - Still provides retry information in logs

4. **Invalid Processor Configuration**
   - Validation catches at startup
   - Job exits with clear error message
   - Prevents partial monitoring runs

### Logging Strategy

- **INFO:** Normal operations, file discoveries
- **WARNING:** Retry information, tolerance approaching
- **ERROR:** Processing failures, notification failures
- **Structured Details:** All alerts include processor name, file path, timestamps

---

## Performance Considerations

### Scalability

**Current Load (5 enabled processors):**
- Execution time: ~5-10 seconds per date
- BigQuery queries: 2 per processor (check + count)
- API calls: 1 GCS list per processor

**Projected Load (20 processors):**
- Execution time: ~20-30 seconds per date
- BigQuery queries: 40 per date
- Well within Cloud Run limits

### Cost Optimization

1. **BigQuery Queries:**
   - Parameterized queries prevent SQL injection and enable caching
   - Partition filters reduce data scanned
   - Expected cost: <$0.01 per monitoring run

2. **GCS Operations:**
   - List operations are free
   - Metadata retrieval is lightweight
   - No data transfer costs (metadata only)

3. **Cloud Run:**
   - Billed per request + CPU time
   - Scheduled jobs have minimal cost
   - Expected cost: <$1/month for hourly monitoring

---

## Security & Permissions

### Required IAM Roles

**Cloud Run Service Account needs:**
```yaml
roles/bigquery.jobUser         # Run queries
roles/bigquery.dataViewer      # Read table data
roles/storage.objectViewer     # List GCS files
roles/secretmanager.accessor   # Read webhook URLs (Slack)
```

### Environment Variables

**Required:**
```bash
GCP_PROJECT_ID=nba-props-platform
SLACK_WEBHOOK_MONITORING_ERROR=https://hooks.slack.com/...
SLACK_WEBHOOK_MONITORING_WARNING=https://hooks.slack.com/...
```

**Optional (Email):**
```bash
BREVO_SMTP_USERNAME=...
BREVO_SMTP_PASSWORD=...
BREVO_FROM_EMAIL=...
```

---

## Extension Points

### Phase 2: Automated Retry

**Foundation Already Built:**
- Retry information logged in alert details
- Pub/Sub topic and attributes included
- Structured retry message format

**Implementation Path:**
1. Add Pub/Sub publishing to gap detector
2. Processors listen for retry messages with `retry=true` attribute
3. Re-process files when retry triggered
4. Update gap monitoring to track retry attempts

### Future Enhancements

1. **Nested Path Support**
   - Enhanced GCS inspector for date/{subdir}/ patterns
   - Configurable subdirectory structures (hourly, event_id, game_code)

2. **Multi-Source Validation**
   - Cross-check multiple data sources
   - Detect discrepancies between sources
   - Flag data quality issues

3. **Predictive Alerting**
   - Learn normal processing times
   - Alert on anomalies before tolerance exceeded
   - Machine learning for pattern detection

4. **Dashboard Integration**
   - Web UI for monitoring status
   - Historical gap trends
   - Processor health metrics

---

## Testing Strategy

### Unit Testing

**Test Coverage:**
- Path normalization logic
- GCS pattern generation
- Tolerance window calculations
- Retry message formatting

### Integration Testing

**Test Scenarios:**
1. File exists in both GCS and BigQuery → No alert
2. File exists in GCS only, within tolerance → No alert
3. File exists in GCS only, tolerance exceeded → Alert sent
4. No file in GCS for date → No alert (expected missing data)

### Production Validation

**Dry Run Mode:**
```bash
python processing_gap_monitor_job.py --date=2025-10-01 --dry-run
```
- Performs all checks
- Suppresses actual alerts
- Logs what would be sent
- Safe for testing in production

---

## Deployment Architecture

### Cloud Run Job Configuration

```yaml
name: processing-gap-monitor
region: us-west2
memory: 2Gi
cpu: 1
timeout: 30m
max_retries: 2
service_account: gap-monitoring@nba-props-platform.iam.gserviceaccount.com
```

### Scheduling (Future)

**Planned Schedule:**
```bash
# During NBA season: Hourly checks
0 * * * * (every hour)

# Off-season: Daily checks
0 8 * * * (8 AM PT daily)
```

**Flexible Arguments:**
```bash
--date=YYYY-MM-DD              # Check specific date
--lookback-days=N              # Check last N days
--processors=proc1,proc2       # Check specific processors
--dry-run                      # Test without alerting
```

---

## Monitoring the Monitor

### Health Checks

**Job Execution Monitoring:**
- Cloud Logging tracks all executions
- Alerting on job failures
- Execution duration tracking

**Alert Delivery Verification:**
- Slack webhooks return status codes
- Failed notifications logged
- Fallback to console logging

### Success Metrics

- **Detection Accuracy:** % of real gaps detected
- **False Positive Rate:** Alerts for already-processed files
- **Alert Latency:** Time from gap occurrence to notification
- **System Uptime:** Successful monitoring runs / total scheduled runs

---

## Known Limitations

1. **Single Snapshot per Date**
   - Currently assumes one file per processor per date
   - Multiple files per date requires enhancement

2. **Nested Paths Not Fully Supported**
   - Simple date-based patterns work perfectly
   - Nested structures (date/{subdir}/) need enhanced GCS inspector

3. **No Automatic Retry (Yet)**
   - Phase 1 only detects gaps and alerts
   - Phase 2 will add automated retry capability

4. **Email Requires External Dependencies**
   - fuzzywuzzy library needed for email
   - Slack alerting works without additional dependencies

---

## Conclusion

The Processing Gap Detection System provides production-ready monitoring for NBA data processing pipelines with:

✅ Proven path normalization logic  
✅ Extensible pattern support  
✅ Configurable tolerance windows  
✅ Multi-channel alerting  
✅ Foundation for automated retry  

**Production Status:** Deployed and validated with 5 enabled processors monitoring critical NBA data flows.