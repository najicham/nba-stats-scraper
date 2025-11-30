# Observability Gaps & Improvement Plan

**File:** `docs/monitoring/04-observability-gaps-and-improvement-plan.md`
**Created:** 2025-11-18
**Last Updated:** 2025-11-18
**Purpose:** Document current observability capabilities, identify gaps, and plan improvements
**Status:** Current
**Audience:** Engineers improving monitoring infrastructure, on-call engineers identifying limitations

---

## 🎯 Executive Summary

**Current State:** Phase 1 (scrapers) has excellent observability with full BigQuery logging. Phase 2-5 processors rely primarily on Cloud Logging, which creates visibility gaps for long-term analysis and debugging.

**Key Gaps:**
1. No centralized processor execution log (Phase 2-5)
2. Dependency check failures only in ephemeral Cloud Logging
3. Limited Pub/Sub retry visibility
4. Unclear if graceful degradation metadata is being stored

**Recommendation:** Create structured BigQuery tables for processor executions and dependency checks, similar to existing scraper logging.

---

## ✅ What's Working Well (Phase 1 Scrapers)

### Excellent Visibility - No Changes Needed

**Table:** `nba_orchestration.scraper_execution_log`

**What You Can See:**
- ✅ **Every scraper execution** - Success, no_data, or failed status
- ✅ **Exact parameters used** - Stored in `opts` JSON field (date, season, group, etc.)
- ✅ **Error details** - `error_type` (exception class) + `error_message` (full stack trace)
- ✅ **Retry tracking** - `retry_count` field shows how many retries occurred
- ✅ **Timing data** - `triggered_at`, `completed_at`, `duration_seconds`
- ✅ **Execution context** - Which workflow triggered it, manual vs scheduled
- ✅ **Output location** - `gcs_path` (where data was written)
- ✅ **Data summary** - Record counts and scraper-specific stats in JSON

**What You Can Answer:**
- "Which scrapers failed today?" ✅
- "What parameters caused the failure?" ✅
- "Did it retry and succeed later?" ✅ (compare multiple executions with same params)
- "How long did it take?" ✅
- "Where's the output file?" ✅

**Supporting Tables:**
- `workflow_executions` - High-level workflow tracking
- `workflow_decisions` - Master controller RUN/SKIP/ABORT decisions
- `daily_expected_schedule` - Expected vs actual comparison
- `cleanup_operations` - Missing file recovery tracking

**Retention:** Permanent in BigQuery, queryable indefinitely

**Example Success Query:**
```sql
-- See all scraper activity today with parameters
SELECT
  scraper_name,
  status,
  JSON_VALUE(opts, '$.date') as date_param,
  error_message
FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY triggered_at DESC;
```

---

## 🔴 Gap 1: No Processor Execution Log (Phase 2-5)

### Current State

**How processors are currently monitored:**
1. **Cloud Logging** - Errors logged but only retained 30 days
2. **Cloud Run job status** - Check via `gcloud run jobs executions list`
3. **Output table row counts** - Indirect evidence of success (query BigQuery tables)
4. **Grafana queries** - Query output tables to infer processor ran

**Problems:**
- ❌ No centralized view of "what processors ran today"
- ❌ Can't easily answer "did Phase 3 complete successfully?"
- ❌ No historical tracking beyond 30 days
- ❌ Parameters/context not stored in queryable format
- ❌ Can't track processor performance trends
- ❌ No structured error tracking for processors

### What's Missing

**Needed:** `nba_orchestration.processor_execution_log` table

**Should capture:**
- Execution ID (unique identifier)
- Processor name (e.g., "phase3-player-game-summary")
- Phase number (2, 3, 4, 5)
- Triggered timestamp
- Completed timestamp
- Status (success, failed, partial)
- Input parameters (game_date, analysis_date, etc.)
- Rows processed
- Rows inserted/updated
- Data quality score (if applicable)
- Error type and message
- Dependencies used (which data sources/tables)
- Metadata (JSON for additional context)

**Schema Example:**
```sql
CREATE TABLE nba_orchestration.processor_execution_log (
  execution_id STRING NOT NULL,
  processor_name STRING NOT NULL,
  phase STRING NOT NULL,  -- 'phase2', 'phase3', etc.
  triggered_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  duration_seconds FLOAT64,
  status STRING NOT NULL,  -- 'success', 'failed', 'partial'

  -- Input context
  input_params JSON,  -- e.g., {"game_date": "2025-11-18", "analysis_date": "2025-11-18"}
  trigger_source STRING,  -- 'pubsub', 'scheduler', 'manual'
  pubsub_message_id STRING,  -- If triggered by Pub/Sub

  -- Output metrics
  rows_processed INT64,
  rows_inserted INT64,
  rows_updated INT64,
  rows_deleted INT64,

  -- Quality indicators
  data_quality_score FLOAT64,  -- 0-100 if applicable
  quality_tier STRING,  -- 'high', 'medium', 'low'
  early_season_flag BOOLEAN,

  -- Error tracking
  error_type STRING,
  error_message STRING,
  error_context JSON,

  -- Dependency tracking
  dependencies_checked JSON,  -- What dependencies were checked
  dependencies_used JSON,  -- Which data sources were actually used
  fallback_used BOOLEAN,  -- Did processor use fallback data?
  fallback_details JSON,  -- Which fallbacks, why

  -- Metadata
  environment STRING,  -- 'production', 'development'
  processor_version STRING,
  metadata JSON
)
PARTITION BY DATE(triggered_at)
CLUSTER BY processor_name, status;
```

### Impact of Gap

**Questions you CAN'T answer today:**
- ❌ "Show me all Phase 3 processor runs today"
- ❌ "Did phase3-player-game-summary run successfully?"
- ❌ "How long did Phase 4 take last night?"
- ❌ "Which processors failed in the past week?"
- ❌ "What's the trend in Phase 3 processing time?"

**Workarounds required:**
- Check multiple Cloud Run jobs individually via gcloud
- Query output tables and infer success from row counts
- Search Cloud Logging text (limited to 30 days)
- No historical analysis possible

### Recommended Fix

**Priority:** High (blocks operational visibility for Phase 2-5)

**Implementation:**
1. Create `processor_execution_log` table in BigQuery
2. Update all processor code to log execution start/end to this table
3. Use similar pattern as `scraper_execution_log` (proven design)
4. Add to Grafana dashboards alongside scraper metrics

**Estimated Effort:** 6-8 hours
- Table creation: 1 hour
- Update Phase 2 processors: 2 hours
- Update Phase 3-5 templates: 2 hours
- Grafana dashboard updates: 2 hours
- Testing: 1-2 hours

---

## 🔴 Gap 2: No Dependency Check Logging

### Current State

**How dependency checks work:**
- Each processor checks required tables at startup
- If dependencies missing → processor fails immediately
- Logs error to Cloud Logging: "dependency check failed"
- Cloud Run job shows FAILED status

**How you debug dependency failures today:**
```bash
# Search Cloud Logging for dependency failures
gcloud logging read \
  "textPayload:\"dependency check failed\" OR textPayload:\"Missing dependency\"" \
  --limit=50 \
  --freshness=1d
```

**Then manually investigate:**
```sql
-- Check if dependency exists
SELECT COUNT(*)
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date = '2025-11-18';
```

**Problems:**
- ❌ Dependency check results not stored anywhere persistent
- ❌ Can't see "what was missing?" without Cloud Logging search
- ❌ Can't track dependency patterns over time
- ❌ No alerts on specific missing dependencies
- ❌ Logs expire after 30 days

### What's Missing

**Needed:** `nba_orchestration.dependency_check_log` table

**Should capture:**
- Check ID (unique identifier)
- Check timestamp
- Processor name
- Required table name
- Required date/partition
- Check result (PASS/FAIL)
- Row count found (if any)
- Error message (if failed)
- Check duration

**Schema Example:**
```sql
CREATE TABLE nba_orchestration.dependency_check_log (
  check_id STRING NOT NULL,
  check_time TIMESTAMP NOT NULL,
  processor_name STRING NOT NULL,
  phase STRING NOT NULL,

  -- What was checked
  required_table STRING NOT NULL,  -- 'nba_raw.nbac_gamebook_player_stats'
  required_partition JSON,  -- {"game_date": "2025-11-18"}
  dependency_type STRING,  -- 'required', 'optional', 'fallback'

  -- Check result
  check_result STRING NOT NULL,  -- 'PASS', 'FAIL', 'PARTIAL'
  row_count INT64,  -- How many rows found (NULL if table doesn't exist)
  table_exists BOOLEAN,
  partition_exists BOOLEAN,

  -- Error details
  error_message STRING,
  error_context JSON,

  -- Resolution
  fallback_available BOOLEAN,
  fallback_used BOOLEAN,
  can_proceed BOOLEAN,  -- Can processor continue despite failure?

  -- Metadata
  execution_id STRING,  -- Link to processor_execution_log
  check_duration_ms FLOAT64
)
PARTITION BY DATE(check_time)
CLUSTER BY processor_name, check_result;
```

### Impact of Gap

**Questions you CAN'T answer today:**
- ❌ "What dependency was missing when Phase 3 failed?"
- ❌ "How often does Phase 4 fail due to missing dependencies?"
- ❌ "Which dependencies are most frequently missing?"
- ❌ "Did the dependency exist at the time of check?" (no historical record)
- ❌ "What's the pattern of early season dependency failures?"

**Scenario you CAN'T handle well:**
```
User: "Phase 3 failed at 2 AM. What was missing?"
Engineer: *searches Cloud Logging for "dependency check failed"*
Engineer: *manually queries 10 different tables to see what existed at 2 AM*
Engineer: "I think it was missing gamebook data, but logs only say 'dependency check failed'"
```

**With proper logging:**
```sql
SELECT
  required_table,
  check_result,
  row_count,
  error_message
FROM nba_orchestration.dependency_check_log
WHERE processor_name = 'phase3-player-game-summary'
  AND DATE(check_time) = '2025-11-18'
  AND check_result = 'FAIL';

-- Returns:
-- required_table: nba_raw.nbac_gamebook_player_stats
-- check_result: FAIL
-- row_count: 0
-- error_message: No data found for game_date = 2025-11-17
```

### Recommended Fix

**Priority:** Medium-High (improves debugging significantly)

**Implementation:**
1. Create `dependency_check_log` table
2. Update dependency check functions to log all checks (pass and fail)
3. Add to Phase 3-5 processor startup sequence
4. Create Grafana dashboard for dependency health

**Estimated Effort:** 4-6 hours
- Table creation: 1 hour
- Update dependency check utility: 2 hours
- Update all processors: 2 hours
- Grafana dashboard: 1 hour

---

## 🔴 Gap 3: Limited Pub/Sub Retry Visibility

### Current State

**What happens when Pub/Sub message fails:**
1. Message delivered to processor → Processor fails → Returns error to Pub/Sub
2. Pub/Sub retries with exponential backoff (10s, 20s, 40s)
3. After 3 attempts → Message moves to Dead Letter Queue (DLQ)

**What you can see:**
- ✅ Scraper execution logged (original event that triggered message)
- ✅ Final processor result (if it eventually succeeds)
- ✅ DLQ message count: `gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub`

**What you CANNOT see:**
- ❌ Individual Pub/Sub delivery attempts
- ❌ When message was retried
- ❌ Which attempt succeeded (1st? 2nd? 3rd?)
- ❌ How long message was stuck in retry loop
- ❌ When message moved to DLQ
- ❌ Why message moved to DLQ (what was the final error?)

### What's Missing

**Partial solution:** Cloud Logging has some Pub/Sub delivery logs, but not structured

**Needed:** Either:
1. Enhance `processor_execution_log` to capture Pub/Sub message ID and attempt number
2. Create separate `pubsub_delivery_log` table

**Option 1: Enhance processor_execution_log** (Recommended)
```sql
-- Add to processor_execution_log table:
pubsub_message_id STRING,  -- Link to original message
pubsub_delivery_attempt INT64,  -- 1, 2, or 3
pubsub_received_at TIMESTAMP,  -- When processor received message
```

**Option 2: Separate table** (More complex, more detailed)
```sql
CREATE TABLE nba_infrastructure.pubsub_delivery_log (
  delivery_id STRING NOT NULL,
  message_id STRING NOT NULL,
  subscription_name STRING NOT NULL,
  delivery_attempt INT64 NOT NULL,
  delivered_at TIMESTAMP NOT NULL,

  -- Message content
  message_data JSON,
  message_attributes JSON,

  -- Processor response
  processor_name STRING,
  processor_response_code INT64,  -- HTTP status code
  processor_response_time_ms FLOAT64,
  processor_error STRING,

  -- Outcome
  delivery_result STRING,  -- 'SUCCESS', 'RETRY', 'DLQ'
  moved_to_dlq_at TIMESTAMP,
  dlq_reason STRING
)
PARTITION BY DATE(delivered_at)
CLUSTER BY subscription_name, delivery_result;
```

### Impact of Gap

**Questions you CAN'T answer today:**
- ❌ "Did this message succeed on the first try or after retries?"
- ❌ "How long was this message stuck retrying?"
- ❌ "What messages are in the DLQ right now?" (can see count, not details)
- ❌ "Why did this specific message go to DLQ?" (only in Cloud Logging)

**Debugging scenario:**
```
User: "Data from 2 AM scraper didn't get processed. Why?"
Engineer: *checks scraper_execution_log* "Scraper succeeded, published to Pub/Sub"
Engineer: *checks DLQ count* "5 messages in DLQ"
Engineer: *pulls DLQ messages* "Can see the message, but can't see the error that caused failure"
Engineer: *searches Cloud Logging* "Hope the logs are still available..."
```

### Recommended Fix

**Priority:** Low-Medium (nice to have, not blocking)

**Recommendation:** Start with Option 1 (enhance processor_execution_log)
- Simpler to implement
- Covers 80% of use cases
- Can add separate table later if needed

**Implementation:**
1. Add `pubsub_message_id` and `pubsub_delivery_attempt` to `processor_execution_log`
2. Processors extract these from Pub/Sub message headers
3. Log with each processor execution

**Estimated Effort:** 2-3 hours
- Schema update: 30 min
- Code changes: 1-2 hours
- Testing: 1 hour

---

## 🟡 Gap 4: Graceful Degradation Metadata (Unclear Status)

### Current State

**Designed:** Phase 3-5 processors are designed to use fallback data sources and log quality degradation

**From documentation:**
- Phase 3 should fall back from nbac_gamebook → bdl → espn
- Phase 4 ML Feature Store should calculate `feature_quality_score` (0-100)
- Phase 5 should track `early_season_flag` and degraded predictions

**What's unclear:**
- ❓ Are output tables actually storing `data_source` field?
- ❓ Is `data_quality_score` being calculated and stored?
- ❓ Are fallback usage details being logged?

### What Should Exist (If Implemented)

**Phase 3 output tables:**
```sql
-- Example: player_game_summary
SELECT
  player_id,
  game_date,
  points,
  -- Quality metadata
  data_source,  -- 'nbac_gamebook', 'bdl', 'espn'
  data_quality_tier,  -- 'high', 'medium', 'low'
  fallback_used,  -- TRUE if primary source unavailable
  processed_at
FROM nba_analytics.player_game_summary
WHERE game_date = CURRENT_DATE() - 1
  AND data_quality_tier != 'high';  -- Show degraded records
```

**Phase 4 ML Feature Store:**
```sql
-- Should already have this
SELECT
  player_name,
  game_date,
  feature_quality_score,  -- 0-100
  early_season_flag,
  metadata  -- JSON with fallback details
FROM nba_predictions.ml_feature_store_v2
WHERE feature_quality_score < 85;  -- Show degraded quality
```

### Impact of Gap (If Not Implemented)

**Questions you CAN'T answer:**
- ❓ "Did we use fallback data for yesterday's games?"
- ❓ "Which players have low-quality data today?"
- ❓ "What percentage of data is from primary vs fallback sources?"
- ❓ "Should we alert on degraded data quality?"

### Recommended Action

**Priority:** Medium (important for production quality monitoring)

**Next Steps:**
1. **Verify implementation** - Check if Phase 2-5 processors actually store these fields
2. **Review output table schemas** - Confirm `data_source`, `data_quality_tier`, etc. exist
3. **Test fallback scenarios** - Trigger fallback and verify metadata is logged
4. **Document findings** - Update this section with actual status

**If NOT implemented:**
- Add quality metadata fields to output table schemas
- Update processor code to populate these fields
- Create Grafana dashboard to monitor data quality

**Estimated Effort (if needs implementation):** 8-12 hours
- Schema updates: 2 hours
- Code changes across Phase 3-5: 4-6 hours
- Testing: 2-3 hours
- Documentation: 1-2 hours

---

## 📊 Summary Table: Observability Status

| Feature | Phase 1 (Scrapers) | Phase 2-5 (Processors) | Priority | Effort |
|---------|-------------------|------------------------|----------|--------|
| **Execution logging** | ✅ Full (scraper_execution_log) | ❌ Missing | High | 6-8 hrs |
| **Error details** | ✅ Structured in BigQuery | ⚠️ Cloud Logging only | High | Included above |
| **Parameter tracking** | ✅ opts JSON field | ❌ Not tracked | High | Included above |
| **Dependency checks** | N/A | ❌ Not logged | Medium-High | 4-6 hrs |
| **Retry visibility** | ✅ retry_count field | ⚠️ Partial | Low-Medium | 2-3 hrs |
| **Pub/Sub lifecycle** | ⚠️ Basic | ⚠️ Basic | Low-Medium | Included above |
| **Data quality metadata** | N/A | ❓ Unclear if implemented | Medium | 8-12 hrs (if needed) |
| **Fallback tracking** | N/A | ❓ Unclear if implemented | Medium | Included above |
| **Historical analysis** | ✅ Permanent BigQuery | ❌ 30-day Cloud Logging | High | Included above |
| **Performance trends** | ✅ duration_seconds tracked | ❌ Not tracked | Medium | Included above |

**Legend:**
- ✅ = Fully implemented and working well
- ⚠️ = Partial implementation or workarounds required
- ❌ = Not implemented, clear gap
- ❓ = Designed but unclear if actually implemented

---

## 🎯 Recommended Implementation Plan

### Phase 1: Critical Gaps (High Priority)

**Goal:** Enable basic operational visibility for Phase 2-5

**Tasks:**
1. ✅ Create `processor_execution_log` table
2. ✅ Update Phase 2 processors to log executions
3. ✅ Add basic error tracking for processors
4. ✅ Create Grafana dashboard for processor health

**Acceptance Criteria:**
- Can answer "Did Phase 3 run today?" from BigQuery
- Can see processor errors in structured format
- Can track processor performance over time

**Timeline:** 1-2 days
**Effort:** 6-8 hours

---

### Phase 2: Dependency Visibility (Medium-High Priority)

**Goal:** Understand why processors fail due to missing dependencies

**Tasks:**
1. ✅ Create `dependency_check_log` table
2. ✅ Update dependency check utility to log all checks
3. ✅ Add dependency health to Grafana dashboards
4. ✅ Create alerts for common dependency failures

**Acceptance Criteria:**
- Can see exactly what dependency was missing
- Can track dependency failure patterns
- Automated alerts when critical dependencies missing

**Timeline:** 1 day
**Effort:** 4-6 hours

---

### Phase 3: Enhanced Metadata (Medium Priority)

**Goal:** Track data quality and fallback usage

**Tasks:**
1. ✅ Verify if quality metadata is implemented in Phase 3-5
2. ✅ Add missing fields to output table schemas (if needed)
3. ✅ Update processor code to populate metadata
4. ✅ Create data quality dashboard

**Acceptance Criteria:**
- Can see which data came from fallback sources
- Can track data quality scores over time
- Can alert on degraded data quality

**Timeline:** 2-3 days (if needs implementation)
**Effort:** 8-12 hours

---

### Phase 4: Pub/Sub Observability (Low-Medium Priority)

**Goal:** Detailed Pub/Sub message lifecycle tracking

**Tasks:**
1. ✅ Add Pub/Sub metadata to `processor_execution_log`
2. ✅ Track delivery attempts and timing
3. ✅ Enhanced DLQ monitoring

**Acceptance Criteria:**
- Can see which delivery attempt succeeded
- Can track message retry timing
- Better DLQ diagnostics

**Timeline:** 1 day
**Effort:** 2-3 hours

---

## 🔗 Related Documentation

**Current Monitoring:**
- `01-grafana-monitoring-guide.md` - Existing BigQuery queries for Phase 1
- `02-grafana-daily-health-check.md` - Quick daily health dashboard
- `03-grafana-phase2-phase3-pipeline-monitoring.md` - Pipeline monitoring

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub setup and testing

**Troubleshooting:**
- `docs/processors/04-phase3-troubleshooting.md` - Phase 3 failure scenarios
- `docs/processors/07-phase4-troubleshooting.md` - Phase 4 failure scenarios

**Architecture:**
- `docs/01-architecture/monitoring-error-handling-design.md` - Overall monitoring strategy

---

## 📝 Change Log

**2025-11-18:** Initial document created based on observability assessment

---

**Next Review:** After implementing Phase 1 (processor_execution_log)
**Owner:** Engineering team
**Maintained By:** On-call engineers and platform team
