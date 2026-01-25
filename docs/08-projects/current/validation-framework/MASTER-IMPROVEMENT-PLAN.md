# NBA Stats Pipeline - Master Improvement Plan

**Created:** 2026-01-25
**Last Updated:** 2026-01-25 (Integrated Exploration Session Findings)
**Status:** Implementation In Progress
**System Health:** 7/10 → Target: 9.5/10

> **Latest Update (2026-01-25 Evening):** This plan has been updated with critical findings from exploration session and discovery analysis. Added 15+ new P0/P1 issues including prediction duplicates, test coverage gaps, and performance bottlenecks.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Critical Bugs (Fix First)](#critical-bugs-fix-first)
3. [P0 Improvements (Proactive Prevention)](#p0-improvements-proactive-prevention)
4. [P1 Improvements (Automation & Observability)](#p1-improvements-automation--observability)
5. [P1 Critical Additions (From V2 Recommendations)](#p1-critical-additions-from-v2-recommendations)
6. [P2 Improvements (Advanced Features)](#p2-improvements-advanced-features)
7. [P2 Operational Improvements (From V2 Recommendations)](#p2-operational-improvements-from-v2-recommendations)
8. [P3 Advanced Features (From V2 Recommendations)](#p3-advanced-features-from-v2-recommendations)
9. [Implementation Dependencies](#implementation-dependencies)
10. [Success Metrics](#success-metrics)
11. [Quick Reference](#quick-reference)

---

## Executive Summary

### The Problem

Recent 45-hour Firestore outage revealed the core issue:
```
Firestore 403 → Master Controller blocked (45h)
    → No Phase 2 processors triggered
    → No new boxscores collected
    → Rolling windows stale
    → Feature quality drops (78→64)
    → Players filtered out (282→85 predictions)
    → Cascade failure
```

**Key insight:** Count-based validation showed "data exists" while quality was severely degraded.

### The Solution

Shift from **reactive detection** to **proactive prevention**:
- **Phase gates** - Block bad data from flowing downstream
- **Trend monitoring** - Detect degradation before it becomes severe
- **Real-time validation** - Catch issues within minutes, not hours
- **Automated recovery** - Self-healing where possible
- **Quality-aware validation** - Monitor quality metrics, not just counts

### Impact Goals

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| Time to detect issues | 4+ hours | < 30 minutes | 8x faster |
| Time to alert operators | N/A | < 5 minutes | NEW (P1.A) |
| Manual intervention needed | 100% | < 20% | 80% reduction |
| Validation coverage | ~60% | > 95% | Near-complete |
| False positive rate | Unknown | < 5% | High precision |
| System health score | 7/10 | 9.5/10 | 36% improvement |
| Deployment rollback MTTR | Unknown | < 15 minutes | NEW (P1.D) |

### Additional V2 Recommendations Summary

This master plan has been enhanced with **16 additional improvements** from the V2 comprehensive review:

**P1 Critical Additions (4 items - HIGH PRIORITY):**
- P1.A: Alerting implementation (Slack/PagerDuty integration)
- P1.B: Circuit breaker for HTTP retries
- P1.C: Health checks before HTTP calls
- P1.D: Rollback procedures documentation

**P2 Operational Improvements (5 items - MEDIUM PRIORITY):**
- P2.A: Operational runbook
- P2.B: Timezone handling standardization
- P2.C: Query cost monitoring
- P2.D: Structured logging standard
- P2.E: Seasonal edge case handling

**P3 Advanced Features (4 items - LOW PRIORITY):**
- P3.A: Concurrency protection (distributed locks)
- P3.B: NBA stat correction handling
- P3.C: Meta-validator (validates validators)
- P3.D: Partial recovery scripts

**Additional Critical Items from Original Recommendations:**
- HTTP endpoint URL verification (verify before deployment)
- Gate overrides audit table creation
- Daily reconciliation automation

---

## BREAKING: Critical Findings from Exploration Session (2026-01-25)

### New P0 Critical Issues (Must Fix Immediately)

#### 1. Prediction Duplicates - 6,473 Extra Rows
**Status:** CRITICAL DATA INTEGRITY ISSUE
**Impact:** Database bloat, potential grading errors, storage waste

**Evidence:**
- 1,692 duplicate business key combinations
- 6,473 extra prediction rows in last 10 days
- Example: dariusgarland has 10 NULL duplicates per system_id on Jan 19

**Root Cause:**
- Multiple prediction batches run at different times (13:28, 15:06, 22:00)
- MERGE logic in `batch_staging_writer.py:330-347` not preventing duplicates
- COALESCE(-1) fix insufficient for NULL current_points_line values
- Distributed lock is per-game_date but multiple batch_ids can run

**Files:**
- `/predictions/shared/batch_staging_writer.py` (lines 330-347)

**Fix Required:**
```sql
-- Immediate cleanup
DELETE FROM nba_predictions.player_prop_predictions
WHERE prediction_id NOT IN (
  SELECT MIN(prediction_id)
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= '2026-01-15'
  GROUP BY game_id, player_lookup, system_id,
           CAST(COALESCE(current_points_line, -1) AS INT64)
);

-- Long-term: Add UNIQUE constraint
ALTER TABLE nba_predictions.player_prop_predictions
ADD CONSTRAINT unique_prediction_key
UNIQUE (game_id, player_lookup, system_id, current_points_line);
```

**Priority:** P0 - Fix immediately

---

#### 2. Zero Test Coverage for 47 Validators
**Status:** CRITICAL RELIABILITY GAP
**Impact:** Cannot verify validators work correctly, high regression risk

**Evidence:**
```bash
find validation/validators -name "*.py" | wc -l  # 47 validators
ls tests/validation/validators/                   # Directory doesn't exist
```

**Components with 0% Test Coverage:**
- All 9 raw data validators (box_scores, schedules, props, injury_reports)
- All 3 analytics validators
- All 5 precompute validators
- All 4 grading validators
- New validators: consistency/, gates/, trends/, recovery/

**Impact:**
- Cannot safely refactor validator code
- Breaking changes go undetected until production
- No regression testing after fixes

**Files Affected:**
- `validation/validators/raw/*`
- `validation/validators/analytics/*`
- `validation/validators/precompute/*`
- `validation/validators/grading/*`
- `validation/validators/consistency/*`
- `validation/validators/gates/*`
- `validation/validators/trends/*`
- `validation/validators/recovery/*`

**Fix Required:**
1. Create `tests/validation/validators/` directory structure
2. Add unit tests for each validator (mock BigQuery)
3. Add integration tests with real data samples
4. Setup CI to require tests for new validators

**Priority:** P0 - Start immediately

---

#### 3. Master Controller Untested
**Status:** CRITICAL PATH NOT COVERED
**Impact:** Pipeline orchestration failures not caught in testing

**Evidence:**
- `orchestration/master_controller.py` - 0 tests
- All phase transition entry points - 0 tests:
  - `phase2_to_phase3/main.py`
  - `phase3_to_phase4/main.py`
  - `phase4_to_phase5/main.py`
  - `phase5_to_phase6/main.py`

**Risk:**
- Orchestration logic changes break pipeline silently
- Cannot validate orchestration fixes before deployment
- Difficult to debug orchestration issues

**Fix Required:**
1. Add unit tests for master_controller.py
2. Add integration tests for each phase transition
3. Mock Cloud Functions calls
4. Test error handling and retry logic

**Priority:** P0 - High risk

---

#### 4. nbac_player_boxscore Scraper Failing for Jan 24
**Status:** ACTIVE FAILURE
**Impact:** Missing 2026-01-24 data (1 of 7 games incomplete)

**Evidence:**
```
Error: Max decode/download retries reached: 8
URL: https://stats.nba.com/stats/leaguegamelog?Counter=1000&DateFrom=2026-01-24&...
Exception: NoHttpStatusCodeException: No status_code on download response.
```

**Current State:**
- Jan 24: 85.7% complete (6/7 games)
- Grading: 42.9% complete for Jan 24
- 1 processor in failed_processor_queue

**Root Cause:**
- NBA.com API returning no HTTP status code
- Possible rate limiting or blocking
- Max retries (8) exhausted

**Files:**
- `scrapers/scraper_base.py:2476` - check_download_status()
- `scrapers/nbacom/nbac_player_boxscore.py`

**Fix Required:**
```bash
# Manual retry with longer timeout
python -c "
from scrapers.nbacom.nbac_player_boxscore import NbacPlayerBoxscoreScraper
scraper = NbacPlayerBoxscoreScraper()
scraper.timeout_http = 60  # Increase timeout
scraper.run(game_date='2026-01-24')
"
```

**Priority:** P0 - Blocking data completeness

---

### New P1 High Priority Issues

#### 5. Scraper Resilience Coordination Gap
**Status:** ARCHITECTURAL ISSUE
**Impact:** Inconsistent retry behavior, proxy failures

**Evidence:** Three uncoordinated retry systems:

| System | File | Threshold | Cooldown |
|--------|------|-----------|----------|
| ProxyCircuitBreaker | proxy_utils.py | 3 failures | 5 min |
| ProxyManager | proxy_manager.py | Score < 20 | 60s × 2^n |
| RateLimitHandler | rate_limit_handler.py | 5 retries | 2-120s |

**Problems:**
- No coordination between systems
- Circuit breaker opens too aggressively (3 failures)
- Temporary rate limits trigger unnecessary proxy blocking
- BDL pagination loses partial data on failure

**Files:**
- `scrapers/utils/proxy_utils.py:46` - Circuit breaker threshold
- `shared/utils/proxy_manager.py`
- `shared/utils/rate_limit_handler.py`
- `scrapers/balldontlie/bdl_player_box_scores.py:306-324`

**Fix Required:**
1. Consolidate retry logic into single coordinated system
2. Increase circuit breaker threshold to 5-7 failures
3. Add partial data preservation in BDL pagination
4. Coordinate proxy health across all scrapers

**Priority:** P1 - Affects reliability

---

#### 6. Performance: 100 Files Using .iterrows()
**Status:** MAJOR PERFORMANCE BOTTLENECK
**Impact:** 50-100x slower than vectorized operations

**Evidence:**
```bash
grep -rn "\.iterrows()" --include="*.py" | wc -l  # 100+ instances
```

**Worst Offenders:**
- `data_processors/grading/mlb/mlb_prediction_grading_processor.py` (lines 155, 223, 274)
- `data_processors/analytics/upcoming_player_game_context_processor.py` (lines 841, 978, 1079, 1408)
- `bin/validation/validate_data_quality_january.py`

**Example Performance Impact:**
```python
# Current (100x slower)
for _, row in df.iterrows():
    has_prop = row.get('has_prop_line', False)

# Better (50-100x faster)
players_with_props = df['has_prop_line'].sum()
```

**Fix Required:**
1. Replace .iterrows() with vectorized pandas operations
2. Use .itertuples() for row-by-row logic (3x faster minimum)
3. Use .apply() for complex operations (10x faster)

**Priority:** P1 - Quick wins for performance

---

#### 7. Performance: 127 Unbounded Queries
**Status:** MEMORY PRESSURE RISK
**Impact:** OOM kills, slow queries, high costs

**Evidence:**
- 127 SELECT * queries without LIMIT
- 631 .to_dataframe() calls loading full results to memory
- `predictions/coordinator/player_loader.py` has 15+ unbounded queries

**Files:**
- `predictions/coordinator/player_loader.py` (lines 199, 320, 647, 714, 879, 952, 1028, 1106, 1149, 1187)
- `shared/utils/bigquery_utils.py:94-97`

**Example:**
```python
# Current (loads ALL results)
results = query_job.result(timeout=60)
return [dict(row) for row in results]  # Creates massive list in memory

# Better (streaming)
results = query_job.result(page_size=1000, timeout=60)
for page in results.pages:
    for row in page:
        yield dict(row)
```

**Fix Required:**
1. Add LIMIT clauses to all queries
2. Implement pagination for large result sets
3. Use streaming iteration instead of full load
4. Add query result size monitoring

**Priority:** P1 - Affects stability

---

#### 8. 618 Orphaned Analytics Records
**Status:** DATA CONSISTENCY ISSUE
**Impact:** Analytics without source data

**Evidence:**
```sql
SELECT COUNT(*) as orphaned
FROM nba_analytics.player_game_summary a
LEFT JOIN nba_raw.bdl_player_boxscores b
  ON a.game_id = b.game_id
  AND a.player_lookup = b.player_lookup
  AND b.game_date >= '2026-01-01'
WHERE b.player_lookup IS NULL AND a.game_date >= '2026-01-01'
-- Result: 618 orphaned records
```

**Root Cause:**
- Analytics processor ran when raw data incomplete
- No validation preventing orphan creation
- Raw data deleted/missing for some games

**Fix Required:**
1. Add foreign key validation in analytics processors
2. Alert on orphaned records
3. Create cleanup job for orphans
4. Add cross-phase consistency validator (already in plan as P0.3)

**Priority:** P1 - Data quality

---

#### 9. Streaming Buffer Row Loss
**Status:** DATA LOSS RISK
**Impact:** Rows skipped without retry on streaming buffer conflicts

**Evidence:**
```python
# data_processors/raw/processor_base.py:1296-1323
if "streaming buffer" in str(load_e).lower():
    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
    self.stats["rows_skipped"] = len(rows)
    return  # Rows NOT retried in this run
```

**Impact:**
- Rows lost if processor doesn't retry
- No automatic recovery
- Silent data gaps

**Fix Required:**
1. Queue skipped rows for retry
2. Implement streaming buffer backoff strategy
3. Add retry counter to prevent infinite loops
4. Alert on repeated streaming buffer blocks

**Priority:** P1 - Data integrity

---

### New P2 Medium Priority Issues

#### 10. Large Files Need Refactoring
**Status:** MAINTAINABILITY ISSUE
**Impact:** Hard to understand, test, and modify

**Files:**
- `scrapers/scraper_base.py` - 2,985 lines (proxy, retries, browser, HTTP, Sentry, notifications)
- `data_processors/analytics/analytics_base.py` - 2,947 lines
- `services/admin_dashboard/main.py` - 2,718 lines
- `data_processors/analytics/upcoming_player_game_context_processor.py` - 2,636 lines
- `data_processors/precompute/player_composite_factors_processor.py` - 2,630 lines
- `data_processors/precompute/precompute_base.py` - 2,596 lines

**Recommendation:** Break into smaller modules (target: < 1,000 lines per file)

**Priority:** P2 - Technical debt

---

#### 11. Batch Size Hardcoding
**Status:** CONFIGURATION ISSUE
**Impact:** Memory pressure risk, no flexibility

**Evidence:**
- `data_processors/reference/base/database_strategies.py:70` - batch_size = 1000 (hardcoded)
- `data_processors/precompute/ml_feature_store/batch_writer.py:460` - BATCH_SIZE = 100 (hardcoded)

**Fix Required:**
1. Move batch sizes to configuration
2. Add dynamic batch sizing based on memory
3. Make batch sizes environment-specific

**Priority:** P2 - Optimization

---

#### 12. No Phase Transitions in 48 Hours
**Status:** OBSERVABILITY GAP
**Impact:** Cannot track orchestration health

**Evidence:**
```
🟠 phase_transitions: No phase transitions in last 48 hours
```

**Potential Causes:**
1. Phase transition logging broken
2. Orchestration stopped/paused
3. No games in window (unlikely - 7 games on Jan 24)

**Investigation Required:**
```sql
SELECT * FROM nba_orchestration.phase_transitions
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
ORDER BY timestamp DESC LIMIT 20;
```

**Priority:** P2 - Investigate

---

#### 13. DR Procedures Not Regularly Tested
**Status:** RISK MANAGEMENT GAP
**Impact:** Recovery procedures may be stale/incorrect

**Evidence:**
- DR runbook exists: `docs/02-operations/disaster-recovery-runbook.md` (1,100+ lines)
- No evidence of regular DR testing
- Manual rollback only - no automation

**Fix Required:**
1. Schedule quarterly DR drills
2. Automate common rollback scenarios
3. Document recovery time for each scenario
4. Test backup restoration procedures

**Priority:** P2 - Risk management

---

### CORRECTED: Bare Except Statements

**Previous Documentation:** 7,061 bare except: pass statements
**Actual Finding:** **ONLY 1 INSTANCE**

**Location:**
- `bin/monitoring/phase_transition_monitor.py:311`
- Context: Parsing ISO timestamp, returns 0 on any exception
- Fix needed: Change to `except (ValueError, TypeError):` with proper logging

**Status:** Much better than documented - low priority fix

**Priority:** P3 - Minor fix needed

---

## Critical Bugs (Fix First)

### Bug #1: Auto-Retry Processor - Pub/Sub Topics Don't Exist ⚠️ CRITICAL

**Status:** Blocking all Phase 2 automatic retries
**Impact:** GSW@MIN boxscore stuck in retry queue, cannot auto-recover

**Problem:**
```python
# main.py lines 44-49
PHASE_TOPIC_MAP = {
    'phase_2': 'nba-phase1-scraper-trigger',      # ❌ DOESN'T EXIST
    'phase_3': 'nba-phase3-analytics-trigger',    # ❌ DOESN'T EXIST
    'phase_4': 'nba-phase4-precompute-trigger',   # ❌ DOESN'T EXIST
    'phase_5': 'nba-predictions-trigger',          # ❌ DOESN'T EXIST
}
```

**Solution:** Replace Pub/Sub with direct HTTP calls (more reliable)

**Files:**
- `/orchestration/cloud_functions/auto_retry_processor/main.py`

**Deployment:**
```bash
./bin/orchestrators/deploy_auto_retry_processor.sh
```

---

### Bug #2: Phase Execution Log Not Populating

**Status:** Observability gap
**Impact:** Cannot track orchestrator performance

**Possible Causes:**
1. Logger not called in deployed code
2. BigQuery write permission issue
3. Exception being swallowed

**Investigation:**
```bash
# Check for logging errors
gcloud functions logs read phase3-to-phase4-orchestrator \
  --region us-west2 --limit 100 | grep -i "phase_execution\|log"

# Test manual insert
bq query --use_legacy_sql=false "
INSERT INTO nba_orchestration.phase_execution_log
(execution_timestamp, phase_name, game_date, status, duration_seconds, games_processed)
VALUES (CURRENT_TIMESTAMP(), 'test', '2026-01-25', 'test', 0.1, 0)"
```

**Files:**
- `/shared/utils/phase_execution_logger.py`
- `/orchestration/cloud_functions/phase*/main.py`

---

### Bug #3: Game ID Format Mismatch

**Status:** Causes confusing validation results
**Impact:** Cannot join tables directly

**Problem:**
| Table | Format | Example |
|-------|--------|---------|
| v_nbac_schedule_latest | NBA.com numeric | `0022500644` |
| bdl_player_boxscores | Date_Away_Home | `20260124_GSW_MIN` |
| player_game_summary | Date_Away_Home | `20260124_GSW_MIN` |

**Solution:** Create mapping view

**Files:**
- `/schemas/bigquery/raw/v_game_id_mappings.sql` (already exists)

**Deployment:**
```bash
bq query --use_legacy_sql=false < schemas/bigquery/raw/v_game_id_mappings.sql
```

---

## P0 Improvements (Proactive Prevention)

### P0.1: Phase 4→5 Gating Validator

**Goal:** Block predictions when feature data is degraded

**Gate Checks:**
- ✅ Feature quality score >= 70 average
- ✅ Player count >= 80% of expected from Phase 3
- ✅ Rolling window freshness <= 48 hours stale
- ✅ Critical features NULL rate <= 5%

**Decision Logic:**
```python
if any_check_fails:
    return GateDecision.BLOCK  # Stop Phase 5
elif warnings_exist:
    return GateDecision.WARN_AND_PROCEED  # Alert but continue
else:
    return GateDecision.PROCEED  # Green light
```

**Integration:**
```python
# In phase4_to_phase5/main.py
gate = Phase4ToPhase5Gate()
result = gate.evaluate(target_date)

if result.decision == GateDecision.BLOCK:
    logger.warning(f"Gate blocked: {result.blocking_reasons}")
    send_alert(result)
    return {"status": "blocked"}

# Continue with normal processing
```

**Files to Create:**
- `/validation/validators/gates/base_gate.py`
- `/validation/validators/gates/phase4_to_phase5_gate.py`
- `/validation/configs/gates/phase4_to_phase5_gate.yaml`

**Files to Modify:**
- `/orchestration/cloud_functions/phase4_to_phase5/main.py`

---

### P0.2: Quality Trend Monitoring

**Goal:** Detect gradual degradation before it becomes severe

**Approach:** Compare current metrics against rolling baselines

**Metrics Monitored:**
- Feature quality score (7-day rolling avg)
- Player count trends
- NULL rate increases
- Processing time anomalies

**Alert Thresholds:**
- **WARNING:** Quality drops >10% from baseline
- **ERROR:** Quality drops >25% from baseline
- **CRITICAL:** Quality drops >40% from baseline

**Query Pattern:**
```sql
WITH baseline AS (
  SELECT AVG(feature_quality_score) as avg_quality
  FROM `nba_precompute.ml_feature_store`
  WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 14 DAY)
    AND DATE_SUB(@target_date, INTERVAL 7 DAY)
),
current AS (
  SELECT AVG(feature_quality_score) as avg_quality
  FROM `nba_precompute.ml_feature_store`
  WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 7 DAY)
    AND @target_date
)
SELECT
  current.avg_quality,
  baseline.avg_quality,
  (baseline.avg_quality - current.avg_quality) / baseline.avg_quality * 100 as pct_drop
FROM current, baseline
```

**Files to Create:**
- `/validation/validators/trends/quality_trend_validator.py`
- `/validation/configs/trends/quality_trend.yaml`
- `/bin/validation/quality_trend_monitor.py`

---

### P0.3: Cross-Phase Consistency Validator

**Goal:** Validate data flows correctly through all pipeline phases

**Consistency Checks:**

| Check | Source | Target | Expected Rate | Severity |
|-------|--------|--------|---------------|----------|
| Schedule → Boxscores | v_nbac_schedule_latest (Final games) | bdl_player_boxscores | 98% | ERROR |
| Boxscores → Analytics | bdl_player_boxscores | player_game_summary | 95% | ERROR |
| Analytics → Features | player_game_summary | ml_feature_store | 90% | WARNING |
| Features → Predictions | ml_feature_store (prod ready) | player_prop_predictions | 85% | WARNING |

**Orphan Detection:**
- Predictions without features
- Analytics without boxscores
- Features without analytics

**Query Pattern:**
```sql
WITH source_records AS (
    SELECT DISTINCT player_lookup, game_date
    FROM `nba_analytics.player_game_summary`
    WHERE game_date BETWEEN @start_date AND @end_date
),
target_records AS (
    SELECT DISTINCT player_lookup, game_date
    FROM `nba_precompute.ml_feature_store`
    WHERE game_date BETWEEN @start_date AND @end_date
)
SELECT
    s.game_date,
    COUNT(DISTINCT s.player_lookup) as source_count,
    COUNT(DISTINCT t.player_lookup) as target_count,
    COUNT(DISTINCT t.player_lookup) / COUNT(DISTINCT s.player_lookup) as match_rate
FROM source_records s
LEFT JOIN target_records t USING (player_lookup, game_date)
GROUP BY s.game_date
HAVING match_rate < 0.90
```

**Files to Create:**
- `/validation/validators/consistency/cross_phase_validator.py`
- `/validation/configs/consistency/cross_phase.yaml`
- `/bin/validation/cross_phase_consistency.py`

---

## P1 Improvements (Automation & Observability)

### P1.1: Validation Scheduling System

**Goal:** Run validators at strategic times automatically

**Schedule:**

| Time (ET) | Validator | Purpose | Frequency |
|-----------|-----------|---------|-----------|
| 6:00 AM | `daily_data_completeness.py` | Morning reconciliation | Daily |
| 3:00 PM | `workflow_health.py` | Pre-game health check | Daily |
| 11:00 PM | `comprehensive_health_check.py` | Post-game validation | Daily |
| 4pm-1am | `phase_transition_health.py` | Live monitoring | Every 30 min |

**Implementation:**
```yaml
# validation_schedules.yaml
validation_schedules:
  morning_reconciliation:
    schedule: "0 6 * * *"
    timezone: "America/New_York"
    script: "daily_data_completeness.py"
    args: "--days 3"
    notification_channels:
      - slack: "#nba-pipeline-health"

  pre_game_health:
    schedule: "0 15 * * *"
    timezone: "America/New_York"
    script: "workflow_health.py"
    args: "--hours 24"

  post_game_validation:
    schedule: "0 23 * * *"
    timezone: "America/New_York"
    script: "comprehensive_health_check.py"
    args: "--date today"

  live_monitoring:
    schedule: "*/30 16-1 * * *"
    timezone: "America/New_York"
    script: "phase_transition_health.py"
    args: "--hours 2"
    alert_on_failure: true
```

**Cloud Scheduler Setup:**
```bash
gcloud scheduler jobs create pubsub validation-morning-check \
  --schedule="0 6 * * *" \
  --time-zone="America/New_York" \
  --topic=validation-trigger \
  --location=us-central1 \
  --message-body='{"validator": "daily_data_completeness", "args": "--days 3"}'
```

**Files to Create:**
- `/bin/orchestrators/deploy_validation_schedulers.sh`
- `/orchestration/cloud_functions/validation_scheduler/main.py`
- `/orchestration/cloud_functions/validation_scheduler/schedules.yaml`

---

### P1.2: Post-Backfill Validation

**Goal:** Automatically verify backfills worked

**Validates:**
- ✅ Gap is now filled (count check)
- ✅ Data quality meets expected levels
- ✅ Downstream phases were reprocessed
- ✅ No new gaps introduced

**Usage Pattern:**
```bash
# Run backfill
python bin/backfill/bdl_boxscores.py --date 2026-01-24

# Automatically validate (integrated)
# OR manually:
python bin/validation/validate_backfill.py \
  --phase raw \
  --table nbac_player_boxscore \
  --date 2026-01-24

# Output:
# ✅ Gap filled: 6/6 games now present
# ✅ Quality check: avg 78.5 (expected: >70)
# ⚠️  Analytics not reprocessed: 0/6 games in player_game_summary
#
# Recommended action:
# python bin/backfill/phase3.py --date 2026-01-24
```

**Integration with Backfill Scripts:**
```python
# In backfill scripts, add:
from validation.validators.recovery import PostBackfillValidator

def main():
    # ... run backfill ...

    # Validate
    validator = PostBackfillValidator()
    result = validator.validate(
        phase='raw',
        table='nbac_player_boxscore',
        date=target_date
    )

    if not result.passed:
        print(f"⚠️  Backfill validation failed: {result.message}")
        print("\nRecommended actions:")
        for action in result.remediation:
            print(f"  - {action}")
    else:
        print("✅ Backfill validated successfully")
```

**Files to Create:**
- `/validation/validators/recovery/post_backfill_validator.py`
- `/bin/validation/validate_backfill.py`

**Files to Modify:**
- All backfill scripts in `/bin/backfill/`

---

### P1.3: Recovery Validation Framework

**Goal:** Validate pipeline health after outages with baseline comparison

**Use Case:** After 45-hour Firestore outage, verify complete recovery

**Features:**
- Compare pre-outage baseline to post-recovery state
- Verify all phases recovered to normal levels
- Generate recovery report with metrics
- Track time to full recovery
- Identify any lingering issues

**Usage:**
```bash
python bin/validation/validate_recovery.py \
  --outage-start "2026-01-23 04:20" \
  --outage-end "2026-01-25 01:35" \
  --baseline-date "2026-01-22"

# Output:
# 🔍 Recovery Validation Report
#
# Outage Duration: 45.25 hours (2026-01-23 04:20 → 2026-01-25 01:35)
# Baseline Date: 2026-01-22 (last known good state)
#
# Phase Recovery Status:
# ✅ Phase 2 (Raw): Recovered
#    - Baseline: 280 players, 7 games
#    - Current:  278 players, 7 games (99.3% recovery)
#
# ⚠️  Phase 3 (Analytics): Partial Recovery
#    - Baseline: 280 players
#    - Current:  268 players (95.7% recovery)
#    - Missing: 12 players need reprocessing
#
# ❌ Phase 4 (Features): Not Recovered
#    - Baseline: Feature quality 78.2
#    - Current:  Feature quality 64.1 (17.9% degradation)
#    - Issue: Rolling windows still stale
#
# Recommended Actions:
# 1. Backfill Phase 3: python bin/backfill/phase3.py --start-date 2026-01-23 --end-date 2026-01-25
# 2. Rebuild rolling windows: python bin/backfill/rebuild_rolling_windows.py
# 3. Re-validate in 2 hours
```

**Validation Criteria:**
- All phases >= 95% of baseline volume
- Feature quality >= 95% of baseline quality
- No stuck processors in retry queue
- Workflow decisions resumed normal frequency

**Files to Create:**
- `/validation/validators/recovery/outage_recovery_validator.py`
- `/bin/validation/validate_recovery.py`

---

### P1.4: Fallback Topic Subscriptions

**Goal:** Enable fallback processing when auto-retry triggers fallback topics

**Current State:** Topics exist but have no subscribers

**Subscriptions to Create:**

| Topic | Subscriber | Endpoint |
|-------|------------|----------|
| nba-phase2-fallback-trigger | nba-phase2-fallback-sub | nba-phase2-raw-processors |
| nba-phase3-fallback-trigger | nba-phase3-fallback-sub | nba-phase3-analytics-processors |
| nba-phase4-fallback-trigger | nba-phase4-fallback-sub | nba-phase4-precompute-processors |
| nba-phase5-fallback-trigger | nba-phase5-fallback-sub | prediction-coordinator |

**Setup Script:**
```bash
#!/bin/bash
# bin/orchestrators/setup_fallback_subscriptions.sh

PROJECT_ID="nba-props-platform"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

# Phase 2 fallback
gcloud pubsub subscriptions create nba-phase2-fallback-sub \
  --topic=nba-phase2-fallback-trigger \
  --push-endpoint=https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d

# Phase 3 fallback
gcloud pubsub subscriptions create nba-phase3-fallback-sub \
  --topic=nba-phase3-fallback-trigger \
  --push-endpoint=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d

# Phase 4 fallback
gcloud pubsub subscriptions create nba-phase4-fallback-sub \
  --topic=nba-phase4-fallback-trigger \
  --push-endpoint=https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d

# Phase 5 fallback
gcloud pubsub subscriptions create nba-phase5-fallback-sub \
  --topic=nba-phase5-fallback-trigger \
  --push-endpoint=https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/predict \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d

echo "✅ Fallback subscriptions created"
```

**Files to Create:**
- `/bin/orchestrators/setup_fallback_subscriptions.sh`

---

### P1.5: Lazy Imports in shared/utils

**Goal:** Fix dependency cascade causing cloud function deployment failures

**Problem:**
```python
# Current: shared/utils/__init__.py
from .roster_manager import RosterManager  # Imports pandas at load time
from .prometheus_metrics import PrometheusMetrics  # Imports psutil
# ... 20+ more eager imports
```

**Solution:**
```python
# Improved: shared/utils/__init__.py
"""Shared utilities with lazy loading."""

# Lightweight imports only - no external dependencies
from .game_id_converter import GameIdConverter, convert_game_id
from .env_validation import validate_required_env_vars

__all__ = [
    'GameIdConverter',
    'convert_game_id',
    'validate_required_env_vars',
    # Lazy-loaded modules
    'RosterManager',
    'PrometheusMetrics',
    'RateLimiter',
    'BigQueryClient',
    'StorageClient',
]

def __getattr__(name):
    """Lazy load heavy modules only when accessed."""
    if name == 'RosterManager':
        from .roster_manager import RosterManager
        return RosterManager
    elif name == 'PrometheusMetrics':
        from .prometheus_metrics import PrometheusMetrics
        return PrometheusMetrics
    elif name == 'RateLimiter':
        from .rate_limiter import RateLimiter
        return RateLimiter
    elif name == 'BigQueryClient':
        from .bigquery_client import BigQueryClient
        return BigQueryClient
    elif name == 'StorageClient':
        from .storage_client import StorageClient
        return StorageClient
    raise AttributeError(f"module 'shared.utils' has no attribute '{name}'")
```

**Benefits:**
- ✅ Cloud functions only load what they need
- ✅ Reduced cold start time
- ✅ Prevents import errors from missing dependencies
- ✅ Backwards compatible with existing code

**Files to Modify:**
- `/shared/utils/__init__.py`

---

## P1 Critical Additions (From V2 Recommendations)

> **Source:** ADDITIONAL-RECOMMENDATIONS-V2.md - High-priority operational gaps identified during comprehensive review

### P1.A: Alerting Implementation 🚨 HIGH PRIORITY

**Status:** NEW from V2 review
**Priority:** P1 (High)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §1.1

**The Gap:**

Validators produce results but there's no implementation showing how alerts reach operators. The master plan mentions validation but doesn't show alerting integration.

**Solution:**

Create centralized alerting dispatcher that routes alerts by severity:
- **CRITICAL** → PagerDuty + Slack critical channel
- **ERROR** → Slack alerts channel
- **WARNING** → Slack pipeline health channel
- **INFO** → Logged only

**Implementation:**

```python
# shared/utils/alerting.py
from dataclasses import dataclass
from enum import Enum

class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class Alert:
    title: str
    message: str
    severity: AlertSeverity
    source: str  # validator name
    affected_date: Optional[str] = None
    affected_items: Optional[List[str]] = None
    remediation: Optional[List[str]] = None

class AlertDispatcher:
    """Dispatch alerts to appropriate channels based on severity."""

    SLACK_WEBHOOKS = {
        "critical": os.environ.get("SLACK_WEBHOOK_CRITICAL"),
        "error": os.environ.get("SLACK_WEBHOOK_ALERTS"),
        "warning": os.environ.get("SLACK_WEBHOOK_PIPELINE_HEALTH"),
    }

    PAGERDUTY_KEY = os.environ.get("PAGERDUTY_INTEGRATION_KEY")

    def dispatch(self, alert: Alert):
        if alert.severity == AlertSeverity.CRITICAL:
            self._send_pagerduty(alert)
            self._send_slack(alert, self.SLACK_WEBHOOKS["critical"])
        elif alert.severity == AlertSeverity.ERROR:
            self._send_slack(alert, self.SLACK_WEBHOOKS["error"])
        elif alert.severity == AlertSeverity.WARNING:
            self._send_slack(alert, self.SLACK_WEBHOOKS["warning"])

        self._log_alert(alert)  # Always log to BigQuery
```

**Environment Variables Required:**
```bash
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/xxx
SLACK_WEBHOOK_ALERTS=https://hooks.slack.com/services/xxx
SLACK_WEBHOOK_PIPELINE_HEALTH=https://hooks.slack.com/services/xxx
PAGERDUTY_INTEGRATION_KEY=xxx
```

**Files to Create:**
- `/shared/utils/alerting.py`

**Files to Modify:**
- All validators in `/validation/validators/`
- `/bin/validation/*.py` scripts

**Integration with Validators:**
```python
# In any validator
from shared.utils.alerting import Alert, AlertDispatcher, AlertSeverity

def send_validation_alert(result: ValidationResult):
    alert = Alert(
        title=result.check_name,
        message=result.message,
        severity=AlertSeverity(result.severity),
        source=result.validator_name,
        affected_date=result.date_checked,
        affected_items=result.affected_items,
        remediation=result.remediation,
    )
    AlertDispatcher().dispatch(alert)
```

---

### P1.B: Circuit Breaker for HTTP Retries 🛡️ HIGH PRIORITY

**Status:** NEW from V2 review
**Priority:** P1 (High)
**Effort:** Low
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §2.1

**The Gap:**

Auto-retry processor makes HTTP calls without circuit breaker protection. If a Cloud Run service is overloaded, auto-retry will keep hammering it, potentially making the problem worse.

**Solution:**

Implement circuit breaker pattern:
- **CLOSED** (normal) → Requests go through
- **OPEN** (failing) → Requests blocked, defer retry
- **HALF-OPEN** (testing) → Try one request to check recovery

**Implementation:**

```python
# Add to auto_retry_processor/main.py

class CircuitBreaker:
    """Simple circuit breaker implementation."""

    def __init__(self, failure_threshold=3, recovery_timeout=300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = {}  # endpoint -> failure count
        self.last_failure = {}  # endpoint -> timestamp
        self.state = {}  # endpoint -> 'closed' | 'open' | 'half-open'

    def call(self, endpoint: str, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""

        if self._is_open(endpoint):
            raise CircuitOpenError(f"Circuit open for {endpoint}")

        try:
            result = func(*args, **kwargs)
            self._record_success(endpoint)
            return result
        except Exception as e:
            self._record_failure(endpoint)
            raise

    def _is_open(self, endpoint: str) -> bool:
        if self.state.get(endpoint) != 'open':
            return False

        # Check if recovery timeout has passed
        if time.time() - self.last_failure.get(endpoint, 0) > self.recovery_timeout:
            self.state[endpoint] = 'half-open'
            return False

        return True

    def _record_success(self, endpoint: str):
        self.failures[endpoint] = 0
        self.state[endpoint] = 'closed'

    def _record_failure(self, endpoint: str):
        self.failures[endpoint] = self.failures.get(endpoint, 0) + 1
        self.last_failure[endpoint] = time.time()

        if self.failures[endpoint] >= self.failure_threshold:
            self.state[endpoint] = 'open'
            logger.warning(f"Circuit opened for {endpoint} after {self.failures[endpoint]} failures")

# Global circuit breaker instance
circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)

def call_phase_endpoint_with_circuit_breaker(endpoint: str, payload: dict) -> dict:
    """Call endpoint with circuit breaker protection."""

    def _make_call():
        response = requests.post(
            endpoint,
            json=payload,
            headers=get_auth_headers(),
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    try:
        return circuit_breaker.call(endpoint, _make_call)
    except CircuitOpenError:
        logger.warning(f"Circuit open for {endpoint}, deferring retry")
        return {"status": "deferred", "reason": "circuit_open"}
```

**Files to Modify:**
- `/orchestration/cloud_functions/auto_retry_processor/main.py`

---

### P1.C: Health Check Before HTTP Calls ❤️ HIGH PRIORITY

**Status:** NEW from V2 review
**Priority:** P1 (High)
**Effort:** Low
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §2.2

**The Gap:**

Auto-retry calls endpoints without checking if they're healthy first. This wastes retry attempts on services that are down.

**Solution:**

Add health check endpoints to all Cloud Run services and check them before making process requests. Cache health status for 60 seconds to avoid overhead.

**Implementation:**

```python
# Add to auto_retry_processor/main.py

import requests
from typing import Dict

# Cache health check results (TTL: 60 seconds)
_health_cache: Dict[str, tuple] = {}  # endpoint -> (healthy: bool, timestamp: float)
HEALTH_CHECK_TTL = 60

def check_endpoint_health(endpoint: str) -> bool:
    """
    Check if endpoint is healthy before making requests.

    Uses cached result if available and fresh.
    """
    # Check cache
    cached = _health_cache.get(endpoint)
    if cached and (time.time() - cached[1]) < HEALTH_CHECK_TTL:
        return cached[0]

    # Derive health endpoint from process endpoint
    # e.g., https://service/process -> https://service/health
    health_endpoint = endpoint.rsplit('/', 1)[0] + '/health'

    try:
        response = requests.get(health_endpoint, timeout=5)
        healthy = response.status_code == 200
    except Exception:
        healthy = False

    # Cache result
    _health_cache[endpoint] = (healthy, time.time())

    if not healthy:
        logger.warning(f"Endpoint unhealthy: {endpoint}")

    return healthy

def retry_with_health_check(processor_info: dict) -> dict:
    """Retry processor only if target endpoint is healthy."""

    phase = processor_info.get('phase')
    endpoint = PHASE_HTTP_ENDPOINTS.get(phase)

    if not endpoint:
        return {"status": "error", "message": f"Unknown phase: {phase}"}

    # Health check first
    if not check_endpoint_health(endpoint):
        logger.info(f"Deferring retry for {processor_info['processor_name']} - endpoint unhealthy")
        return {"status": "deferred", "reason": "endpoint_unhealthy"}

    # Proceed with retry
    return call_phase_endpoint_with_circuit_breaker(endpoint, processor_info)
```

**Cloud Run Health Endpoints:**

Add to each Cloud Run service:
```python
# In each Cloud Run service main.py

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for load balancers and monitors."""
    checks = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Optional: Check dependencies
    try:
        bq_client.query("SELECT 1").result()
        checks["bigquery"] = "ok"
    except Exception as e:
        checks["bigquery"] = f"error: {e}"
        checks["status"] = "degraded"

    status_code = 200 if checks["status"] == "healthy" else 503
    return jsonify(checks), status_code
```

**Files to Modify:**
- `/orchestration/cloud_functions/auto_retry_processor/main.py`
- `/orchestration/cloud_functions/phase2_to_phase3/main.py`
- `/orchestration/cloud_functions/phase3_to_phase4/main.py`
- `/orchestration/cloud_functions/phase4_to_phase5/main.py`
- `/orchestration/cloud_functions/phase5_to_phase6/main.py`

---

### P1.D: Rollback Procedures Documentation 📋 HIGH PRIORITY

**Status:** NEW from V2 review
**Priority:** P1 (High)
**Effort:** Low
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §1.2

**The Gap:**

No documented procedures for rolling back if deployments cause issues. This creates risk during deployments and slows incident response.

**Solution:**

Add comprehensive rollback procedures to DEPLOYMENT-GUIDE.md covering:
- Auto-retry processor rollback
- Phase orchestrator rollback
- Gate emergency disable
- Validator rollback
- Full system rollback checklist

**Content to Add:**

```markdown
## Rollback Procedures

### Auto-Retry Processor Rollback

If auto-retry processor causes issues after deployment:

```bash
# Option 1: Disable the function temporarily
gcloud functions delete auto-retry-processor --region us-west2

# Option 2: Revert to previous version (if available in source control)
git checkout HEAD~1 -- orchestration/cloud_functions/auto_retry_processor/main.py
./bin/orchestrators/deploy_auto_retry_processor.sh

# Option 3: Deploy minimal "no-op" version
cat > /tmp/noop_main.py << 'EOF'
def process_failed_processors(request):
    """Temporarily disabled - returns success without processing."""
    return {"status": "disabled", "message": "Auto-retry temporarily disabled"}
EOF
# Deploy this instead
```

### Phase 4→5 Gate Emergency Disable

If the gate is blocking legitimate processing:

```bash
# Method 1: Environment variable override (preferred)
gcloud functions update phase4-to-phase5-orchestrator \
  --update-env-vars GATE_OVERRIDE=true \
  --region us-west2

# Method 2: Lower thresholds temporarily
gcloud functions update phase4-to-phase5-orchestrator \
  --update-env-vars GATE_QUALITY_THRESHOLD=50,GATE_PLAYER_THRESHOLD=0.5 \
  --region us-west2
```

### Validator Rollback

Validators are standalone scripts, so rollback is simpler:

```bash
# Just don't run the validator, or:
git checkout HEAD~1 -- bin/validation/<validator>.py

# If scheduled, disable the Cloud Scheduler job:
gcloud scheduler jobs pause validation-<name> --location us-central1
```

### Full System Rollback Checklist

If multiple components need rollback:

1. [ ] Pause all Cloud Scheduler jobs for validators
2. [ ] Disable auto-retry processor
3. [ ] Remove gate environment variables
4. [ ] Revert code changes in git
5. [ ] Redeploy affected cloud functions
6. [ ] Verify system health with manual checks
7. [ ] Gradually re-enable components one by one
```

**Files to Modify:**
- `/DEPLOYMENT-GUIDE.md` (add rollback section)

**Files to Create:**
- `/docs/runbooks/ROLLBACK-PROCEDURES.md` (detailed version)

---

### P1.E: Missing Props Alerting 🚨 HIGH PRIORITY (NEW - USER REQUEST)

**Status:** NEW - User-requested feature
**Priority:** P1 (High) - USER REQUEST
**Effort:** Low (COMPLETED)
**Source:** User request + Defense-in-Depth §2.1

**The Need:**

User specifically requested a validator that alerts when games have missing or insufficient betting lines. This is CRITICAL for betting operations.

**Solution:**

Created comprehensive props availability validator that checks:
- Games with ZERO betting lines (CRITICAL alert)
- Games with < 3 players with props (CRITICAL threshold)
- Games with < 8 players with props (WARNING threshold)
- Which bookmakers/sources were checked
- Props data freshness (staleness detection)

**Alert Message Format:**

```
🚨 CRITICAL: BOS @ CHI has ZERO betting lines from any source
- Checked: BettingPros, Odds API
- Game time: 7:00 PM ET
- Recommendation: Manually verify on DraftKings app if props are offered
- Possible causes: Scraper bug, DraftKings not offering props, API outage
```

**Implementation:**

```python
# validation/validators/raw/props_availability_validator.py
class PropsAvailabilityValidator(BaseValidator):
    """Validator for props availability across scheduled games."""

    CRITICAL_PLAYER_THRESHOLD = 3   # < 3 players is critical
    WARNING_PLAYER_THRESHOLD = 8    # < 8 players is warning

    def _run_custom_validations(self, start_date, end_date, season_year):
        # Check 1: Games with ZERO props (most critical)
        self._validate_zero_props_games(start_date, end_date)

        # Check 2: Games with insufficient player coverage
        self._validate_player_coverage(start_date, end_date)

        # Check 3: Bookmaker coverage tracking
        self._validate_bookmaker_coverage(start_date, end_date)

        # Check 4: Props freshness (staleness)
        self._validate_props_freshness(start_date, end_date)
```

**Usage:**

```bash
# Check today's games
python validation/validators/raw/props_availability_validator.py --last-days 1

# Check next 3 days (for upcoming games)
python validation/validators/raw/props_availability_validator.py --start-date 2026-01-25 --end-date 2026-01-28

# Check without sending alerts (dry run)
python validation/validators/raw/props_availability_validator.py --last-days 3 --no-notify
```

**Integration with Alerting:**

Once P1.A (Alerting implementation) is complete, this validator will automatically:
- Send CRITICAL alerts to PagerDuty + Slack for games with 0 props
- Send WARNING alerts to Slack for games with < 8 players
- Include actionable remediation in alerts

**Files Created:**
- `/validation/validators/raw/props_availability_validator.py` ✅
- `/validation/configs/raw/props_availability.yaml` ✅

**Files to Modify (After P1.A):**
- Integrate with alerting system when P1.A is complete

**Success Criteria:**
- Alerts sent within 5 minutes of props data becoming available
- Zero false positives for legitimately unavailable games
- Clear actionable recommendations in every alert
- Integration with P1.A alerting system

---

### P1.F: Model Drift Detection 📉 HIGH PRIORITY

**Status:** NEW from Defense-in-Depth
**Priority:** P1 (High)
**Effort:** Medium
**Source:** DEFENSE-IN-DEPTH-IMPROVEMENTS.md §1.1

**The Gap:**

No monitoring for whether the prediction model is degrading over time. Model could become less accurate without anyone noticing.

**Why It Matters:**
- Model could become less accurate without detection
- External factors (rule changes, play style shifts) affect predictions
- Need to know when to retrain or adjust model

**Implementation:**

```python
# validation/validators/predictions/model_drift_validator.py
class ModelDriftValidator:
    """Monitor prediction accuracy trends for model drift."""

    ACCURACY_DROP_WARNING = 0.05  # 5% drop from baseline
    ACCURACY_DROP_ERROR = 0.10   # 10% drop from baseline

    def check_model_drift(self, lookback_days: int = 30) -> Dict:
        """
        Compare recent accuracy to historical baseline.

        Returns drift metrics and alerts.
        """
        # Get accuracy by week
        query = """
        SELECT
            DATE_TRUNC(game_date, WEEK) as week,
            AVG(CAST(prediction_correct AS FLOAT64)) as accuracy,
            COUNT(*) as predictions
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND NOT is_voided
        GROUP BY 1
        ORDER BY 1
        """

        weekly_accuracy = self._run_query(query, {"days": lookback_days})

        # Calculate baseline (first half) vs recent (second half)
        midpoint = len(weekly_accuracy) // 2
        baseline_accuracy = statistics.mean([w.accuracy for w in weekly_accuracy[:midpoint]])
        recent_accuracy = statistics.mean([w.accuracy for w in weekly_accuracy[midpoint:]])

        drift = baseline_accuracy - recent_accuracy
        drift_pct = drift / baseline_accuracy

        # Check thresholds and alert
        if drift_pct >= self.ACCURACY_DROP_ERROR:
            return {"status": "error", "drift_pct": drift_pct, "message": f"Model accuracy dropped {drift_pct:.1%}"}
        elif drift_pct >= self.ACCURACY_DROP_WARNING:
            return {"status": "warning", "drift_pct": drift_pct}
        else:
            return {"status": "healthy"}
```

**Files to Create:**
- `/validation/validators/predictions/model_drift_validator.py`
- `/validation/configs/predictions/model_drift.yaml`
- `/bin/validation/model_drift_monitor.py`

**Integration:**
- Run daily at 6:00 AM
- Alert on >5% drift (WARNING) or >10% drift (ERROR)
- Track by prop type to identify specific issues

---

### P1.G: Confidence Calibration Check ✅ HIGH PRIORITY

**Status:** NEW from Defense-in-Depth
**Priority:** P1 (High)
**Effort:** Low
**Source:** DEFENSE-IN-DEPTH-IMPROVEMENTS.md §1.2

**The Gap:**

Confidence scores might not reflect actual probability of being correct. If 80% confidence predictions are only right 50% of the time, confidence is meaningless.

**Why It Matters:**
- Users/systems rely on confidence for decision-making
- Poorly calibrated confidence erodes trust
- Need to validate confidence matches reality

**Implementation:**

```python
# validation/validators/predictions/confidence_calibration_validator.py
class ConfidenceCalibrationValidator:
    """Check if confidence scores are well-calibrated."""

    def check_calibration(self, days: int = 30) -> Dict:
        """
        Compare confidence deciles to actual accuracy.

        Well-calibrated: decile 10 should be ~90% accurate,
        decile 5 should be ~50% accurate, etc.
        """
        query = """
        SELECT
            confidence_decile,
            AVG(CAST(prediction_correct AS FLOAT64)) as actual_accuracy,
            COUNT(*) as predictions,
            AVG(confidence_score) as avg_confidence
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND NOT is_voided
        AND confidence_decile IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """

        calibration = self._run_query(query, {"days": days})

        # Calculate calibration error
        total_error = 0
        for row in calibration:
            expected = row.avg_confidence
            actual = row.actual_accuracy
            error = abs(expected - actual)
            total_error += error

            # Flag large errors
            if error > 0.15:  # More than 15% off
                logger.warning(f"Decile {row.confidence_decile}: expected {expected:.1%}, actual {actual:.1%}")

        avg_error = total_error / len(calibration) if calibration else 0
        is_calibrated = avg_error < 0.10

        return {"is_calibrated": is_calibrated, "calibration_error": avg_error}
```

**Files to Create:**
- `/validation/validators/predictions/confidence_calibration_validator.py`
- `/validation/configs/predictions/confidence_calibration.yaml`

**Integration:**
- Run weekly
- Alert if calibration error > 10%
- Track by prop type and confidence band

---

### P1.H: Odds Staleness Detection ⏰ HIGH PRIORITY

**Status:** NEW from Defense-in-Depth
**Priority:** P1 (High)
**Effort:** Low
**Source:** DEFENSE-IN-DEPTH-IMPROVEMENTS.md §2.1

**The Gap:**

Using stale betting lines invalidates predictions. No systematic check for line freshness.

**Why It Matters:**
- Stale lines (>6 hours before game) may not reflect current information
- Predictions based on stale lines are unreliable
- Need to catch staleness before predictions run

**Implementation:**

```python
# validation/validators/raw/odds_staleness_validator.py
class OddsStalenessValidator:
    """Validate betting lines are fresh before predictions."""

    MAX_LINE_AGE_HOURS = 6  # Lines older than 6h before game are stale

    def check_lines_freshness(self, game_date: str) -> Dict:
        """Check if betting lines are fresh enough for predictions."""

        query = """
        SELECT
            p.game_id,
            s.home_team,
            s.away_team,
            s.game_time_et,
            MAX(p.scraped_at) as latest_line_time,
            TIMESTAMP_DIFF(s.game_time_et, MAX(p.scraped_at), HOUR) as hours_before_game
        FROM `nba_raw.odds_api_props` p
        JOIN `nba_raw.v_nbac_schedule_latest` s
            ON p.game_id = s.game_id
        WHERE p.game_date = @game_date
        GROUP BY 1, 2, 3, 4
        """

        games = self._run_query(query, {"game_date": game_date})

        stale_games = [g for g in games if g.hours_before_game and g.hours_before_game > self.MAX_LINE_AGE_HOURS]

        return {
            "total_games": len(games),
            "stale_games": len(stale_games),
            "status": "error" if stale_games else "healthy"
        }
```

**Files to Create:**
- `/validation/validators/raw/odds_staleness_validator.py`
- `/validation/configs/raw/odds_staleness.yaml`

**Integration:**
- Run before Phase 5 (predictions)
- Block predictions if lines are stale
- Can be integrated into Phase 4→5 gate

---

### P1.I: Pub/Sub Idempotency 🔁 HIGH PRIORITY

**Status:** NEW from Defense-in-Depth
**Priority:** P1 (High)
**Effort:** Medium
**Source:** DEFENSE-IN-DEPTH-IMPROVEMENTS.md §3.1

**The Gap:**

Pub/Sub delivers at-least-once; same message could be processed multiple times. No idempotency protection.

**Why It Matters:**
- Duplicate processing wastes resources
- Can cause data inconsistencies
- Important for cost control and data quality

**Implementation:**

```python
# shared/utils/idempotency.py
class IdempotencyChecker:
    """Ensure messages are only processed once."""

    TABLE = "nba_orchestration.processed_messages"

    def get_idempotency_key(self, message_data: dict) -> str:
        """Generate unique key for a message."""
        content = str(sorted(message_data.items()))
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def is_already_processed(self, idempotency_key: str) -> bool:
        """Check if message was already processed."""
        query = f"""
        SELECT 1 FROM `{self.TABLE}`
        WHERE idempotency_key = @key
        AND processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        LIMIT 1
        """

        result = list(self.bq_client.query(query, ...).result())
        return len(result) > 0

    def mark_as_processed(self, idempotency_key: str, processor: str):
        """Record that message was processed."""
        query = f"""
        INSERT INTO `{self.TABLE}`
        (idempotency_key, processor, message_id, processed_at)
        VALUES (@key, @processor, @message_id, CURRENT_TIMESTAMP())
        """
        self.bq_client.query(query, ...).result()

    def process_idempotently(self, message_data: dict, processor_name: str, process_func):
        """Process message only if not already processed."""
        key = self.get_idempotency_key(message_data)

        if self.is_already_processed(key):
            logger.info(f"Message already processed (key={key}), skipping")
            return {"status": "skipped", "reason": "duplicate"}

        # Process the message
        result = process_func()

        # Mark as processed
        self.mark_as_processed(key, processor_name)

        return result
```

**Table Schema:**
```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.processed_messages` (
    idempotency_key STRING NOT NULL,
    processor STRING NOT NULL,
    message_id STRING,
    processed_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(processed_at)
OPTIONS (
    partition_expiration_days = 7  -- Auto-cleanup after 7 days
);
```

**Files to Create:**
- `/shared/utils/idempotency.py`
- `/schemas/bigquery/orchestration/processed_messages.sql`

**Files to Modify:**
- All Cloud Run processors that consume Pub/Sub messages
- Auto-retry processor
- Phase orchestrators

**Integration:**
- Wrap all Pub/Sub message handlers with idempotency check
- Use 24-hour window for duplicate detection
- Auto-cleanup after 7 days

---

## P2 Improvements (Advanced Features)

### P2.1: Real-Time Validation Hooks

**Goal:** Catch issues during processing, not just in batch validation

**Implementation:** Add pre/post validation hooks to processor base classes

**Pattern:**
```python
# In processor_base.py
class ProcessorWithValidation(ProcessorBase):
    def process(self, data):
        # Pre-validation
        if not self._validate_input(data):
            self._alert("Input validation failed")
            self._log_validation_failure("input", data)
            return

        # Process
        result = super().process(data)

        # Post-validation
        if not self._validate_output(result):
            self._alert("Output validation failed")
            self._log_validation_failure("output", result)

        return result

    def _validate_input(self, data):
        """Validate input data quality."""
        checks = [
            self._check_required_fields(data),
            self._check_data_types(data),
            self._check_value_ranges(data),
        ]
        return all(checks)

    def _validate_output(self, result):
        """Validate output data quality."""
        checks = [
            self._check_record_count(result),
            self._check_null_rates(result),
            self._check_duplicates(result),
        ]
        return all(checks)
```

**Checks:**
- ✅ Required fields present
- ✅ Data types correct
- ✅ Value ranges reasonable
- ✅ Record counts match expectations
- ✅ NULL rates within limits
- ✅ No duplicate records

**Files to Modify:**
- `/data_processors/raw/processor_base.py`
- `/data_processors/analytics/analytics_base.py`
- `/data_processors/precompute/precompute_base.py`

---

### P2.2: Validation Analytics Dashboard

**Goal:** Analyze validation results for trends and effectiveness

**Metrics:**
- Pass rate by validator over time
- Most common failure types
- Mean time to detection (MTD)
- Remediation effectiveness
- Validation coverage gaps

**Views to Create:**
```sql
-- v_validation_pass_rate_trend
CREATE OR REPLACE VIEW `nba_orchestration.v_validation_pass_rate_trend` AS
SELECT
  DATE(run_timestamp) as run_date,
  validator_name,
  COUNT(CASE WHEN passed THEN 1 END) / COUNT(*) as pass_rate,
  COUNT(*) as total_runs,
  COUNT(CASE WHEN passed THEN 1 END) as passed_count,
  COUNT(CASE WHEN NOT passed THEN 1 END) as failed_count
FROM `nba_orchestration.validation_results`
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- v_validation_failure_types
CREATE OR REPLACE VIEW `nba_orchestration.v_validation_failure_types` AS
SELECT
  check_type,
  severity,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT validator_name) as affected_validators
FROM `nba_orchestration.validation_results`
WHERE NOT passed
  AND run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1, 2
ORDER BY failure_count DESC;

-- v_validation_mtd
CREATE OR REPLACE VIEW `nba_orchestration.v_validation_mtd` AS
SELECT
  check_type,
  AVG(TIMESTAMP_DIFF(detected_at, issue_started_at, MINUTE)) as avg_mtd_minutes,
  MIN(TIMESTAMP_DIFF(detected_at, issue_started_at, MINUTE)) as min_mtd_minutes,
  MAX(TIMESTAMP_DIFF(detected_at, issue_started_at, MINUTE)) as max_mtd_minutes
FROM `nba_orchestration.validation_detections`
WHERE detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY avg_mtd_minutes DESC;
```

**Dashboard Script:**
```python
# bin/validation/validation_analytics.py
"""Generate validation analytics report."""

def generate_report():
    print("\n📊 Validation Analytics Report (Last 30 Days)\n")

    # Pass rate by validator
    print("Pass Rate by Validator:")
    print_pass_rate_table()

    # Most common failures
    print("\nTop Failure Types:")
    print_failure_types()

    # Mean time to detection
    print("\nMean Time to Detection:")
    print_mtd_table()

    # Coverage gaps
    print("\nValidation Coverage Gaps:")
    print_coverage_gaps()
```

**Files to Create:**
- `/schemas/bigquery/orchestration/v_validation_analytics.sql`
- `/bin/validation/validation_analytics.py`

---

### P2.3: Config Drift Detection in CI/CD

**Goal:** Block deployments when config drift is detected

**Implementation:**
```bash
# In deploy_phase3_to_phase4.sh
echo "🔍 Checking for config drift..."
python bin/validation/detect_config_drift.py --strict

if [ $? -ne 0 ]; then
    echo "❌ ERROR: Config drift detected. Fix before deploying."
    echo ""
    echo "Run this to see details:"
    echo "  python bin/validation/detect_config_drift.py --show-diff"
    exit 1
fi

echo "✅ No config drift detected"
```

**GitHub Actions Workflow:**
```yaml
# .github/workflows/config-validation.yml
name: Config Validation

on:
  pull_request:
    paths:
      - 'shared/config/**'
      - 'orchestration/cloud_functions/*/shared/config/**'

jobs:
  validate-config:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Check config drift
        run: python bin/validation/detect_config_drift.py --strict

      - name: Check config syntax
        run: python bin/validation/validate_orchestration_config.py
```

**Files to Modify:**
- `/bin/orchestrators/deploy_phase2_to_phase3.sh`
- `/bin/orchestrators/deploy_phase3_to_phase4.sh`
- `/bin/orchestrators/deploy_phase4_to_phase5.sh`
- `/bin/orchestrators/deploy_phase5_to_phase6.sh`

**Files to Create:**
- `/.github/workflows/config-validation.yml`

---

### P2.4: Duplicate/Idempotency Validation

**Goal:** Detect duplicate processing systematically

**Implementation:**
```python
# In validation/base_validator.py

def _check_duplicates(self, table: str, key_fields: List[str],
                      date_field: str, date_value: str):
    """Check for duplicate records based on business key."""
    query = f"""
    SELECT {', '.join(key_fields)}, COUNT(*) as cnt
    FROM `{table}`
    WHERE {date_field} = @date_value
    GROUP BY {', '.join(key_fields)}
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC
    LIMIT 100
    """

    duplicates = self._run_query(query, {"date_value": date_value})

    if duplicates:
        self.results.append(ValidationResult(
            check_name="duplicate_detection",
            check_type="data_quality",
            layer="bigquery",
            passed=False,
            severity="error",
            message=f"Found {len(duplicates)} duplicate record groups",
            affected_count=sum(d.cnt - 1 for d in duplicates),  # Extra records
            affected_items=[
                f"{', '.join(str(getattr(d, f)) for f in key_fields)}: {d.cnt} copies"
                for d in duplicates[:10]
            ],
            remediation=[
                f"# Deduplicate {table}",
                f"python bin/maintenance/deduplicate_table.py --table {table} --date {date_value}"
            ]
        ))
    else:
        self.results.append(ValidationResult(
            check_name="duplicate_detection",
            check_type="data_quality",
            layer="bigquery",
            passed=True,
            severity="info",
            message="No duplicate records found",
            affected_count=0
        ))
```

**Standard Checks:**
- Business key duplicates (game_id + player_id)
- Timestamp duplicates (same record inserted multiple times)
- Streaming buffer conflicts
- Processing run duplicates

**Files to Modify:**
- `/validation/base_validator.py`

---

### P2.5: ESPN Boxscore Fallback

**Goal:** When BDL fails, automatically use ESPN as secondary source

**Architecture:**
```
BDL Scraper (primary)
    ↓ fails 2+ times
ESPN Scraper (fallback)
    ↓
Format Transformer (ESPN → BDL schema)
    ↓
Phase 2 Processor (unified handling)
```

**Implementation:**
```python
# scrapers/espn/espn_boxscores.py
class ESPNBoxscoreScraper(ScraperBase):
    """ESPN boxscore scraper for fallback."""

    def __init__(self):
        super().__init__(source='espn_boxscore')
        self.rate_limiter = RateLimiter(calls_per_minute=20)  # Conservative

    def scrape_game(self, game_id: str, game_date: str) -> dict:
        """Scrape boxscore from ESPN."""
        self.rate_limiter.wait_if_needed()

        # ESPN game ID format: 401584893
        espn_game_id = self._convert_game_id(game_id)

        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
        params = {"event": espn_game_id}

        response = self._make_request(url, params=params)

        # Transform to BDL schema
        return self._transform_to_bdl_schema(response)
```

**Trigger Logic:**
```python
# In auto_retry_processor
if processor_name == 'nbac_player_boxscore' and retry_count >= 2:
    # Try ESPN fallback
    logger.info(f"Triggering ESPN fallback for {game_date}")
    trigger_espn_scraper(game_date)
```

**Files to Create:**
- `/scrapers/espn/espn_boxscores.py`
- `/scrapers/espn/transformers/espn_to_bdl.py`

---

### P2.6: Entity Tracing Script

**Goal:** Debug pipeline issues by tracing entities through all phases

**Usage:**
```bash
# Trace player
python bin/validation/trace_entity.py --player "LeBron James" --date 2026-01-24

# Output:
# 🔍 Tracing: LeBron James on 2026-01-24
#
# Phase 1 (Schedule):
# ✅ Game scheduled: LAL @ BOS
#    Game ID: 0022500645
#    Status: Final
#
# Phase 2 (Boxscore):
# ✅ Boxscore exists
#    Points: 28, Assists: 7, Rebounds: 11
#    Minutes: 36.5
#
# Phase 3 (Analytics):
# ✅ Analytics computed
#    Usage Rate: 32.1%
#    TS%: 61.2%
#    Source Coverage: 100%
#
# Phase 4 (Features):
# ⚠️  Feature quality degraded
#    Quality Score: 64 (expected: >70)
#    Issue: Rolling windows stale (72h)
#
# Phase 5 (Predictions):
# ❌ No prediction found
#    Reason: Filtered out due to low feature quality
#
# Phase 6 (Grading):
# ❌ No grading (no prediction to grade)
#
# 🔍 Root Cause: Rolling windows stale → low quality → filtered from predictions
```

**Implementation:**
```python
# bin/validation/trace_entity.py
def trace_player(player_lookup: str, game_date: str):
    """Trace player through all phases."""

    results = {
        'player': player_lookup,
        'date': game_date,
        'phases': {}
    }

    # Phase 1: Schedule
    results['phases']['schedule'] = check_schedule(player_lookup, game_date)

    # Phase 2: Boxscore
    results['phases']['boxscore'] = check_boxscore(player_lookup, game_date)

    # Phase 3: Analytics
    results['phases']['analytics'] = check_analytics(player_lookup, game_date)

    # Phase 4: Features
    results['phases']['features'] = check_features(player_lookup, game_date)

    # Phase 5: Predictions
    results['phases']['prediction'] = check_prediction(player_lookup, game_date)

    # Phase 6: Grading
    results['phases']['grading'] = check_grading(player_lookup, game_date)

    # Analyze and print
    print_trace_report(results)
```

**Files to Create:**
- `/bin/validation/trace_entity.py`

---

## P2 Operational Improvements (From V2 Recommendations)

> **Source:** ADDITIONAL-RECOMMENDATIONS-V2.md - Operational enhancements for production resilience

### P2.A: Operational Runbook

**Status:** NEW from V2 review
**Priority:** P2 (Medium)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §1.3

**The Gap:**

No quick-reference runbook for common validation issues. Operators need to remember or search through docs for common procedures.

**Solution:**

Create `/docs/runbooks/VALIDATION-RUNBOOK.md` with:
- Decision tree for which validator to run
- Common issues & fixes (gate blocking, auto-retry stuck, false positives)
- Emergency contacts
- Quick diagnostic commands

**Files to Create:**
- `/docs/runbooks/VALIDATION-RUNBOOK.md`
- `/docs/runbooks/COMMON-ISSUES.md`

---

### P2.B: Timezone Handling Standardization

**Status:** NEW from V2 review
**Priority:** P2 (Medium)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §3.2

**The Gap:**

Games are scheduled in ET, servers run in UTC, BigQuery timestamps are UTC. Inconsistent handling causes validation issues around midnight.

**Solution:**

Standardize on timezone convention:
- `game_date` columns: Always ET date (YYYY-MM-DD)
- Timestamps (`created_at`, etc): Always UTC
- Schedule times: Stored as ET, displayed as ET
- Validation: Always use `get_current_nba_date()` not `date.today()`

**Implementation:**

```python
# shared/utils/timezone_utils.py
"""Standardized timezone handling for NBA pipeline."""

from datetime import datetime, date, timedelta
import pytz

ET = pytz.timezone('America/New_York')
UTC = pytz.UTC

def get_nba_game_date(utc_timestamp: datetime) -> date:
    """
    Convert UTC timestamp to NBA game date (ET).

    Example:
        UTC 2026-01-25 03:00:00 -> NBA date 2026-01-24
        (because it's 10pm ET on Jan 24)
    """
    if utc_timestamp.tzinfo is None:
        utc_timestamp = UTC.localize(utc_timestamp)

    et_time = utc_timestamp.astimezone(ET)
    return et_time.date()

def get_current_nba_date() -> date:
    """Get current NBA game date (in ET)."""
    return get_nba_game_date(datetime.now(UTC))

def is_games_likely_complete(game_date: date) -> bool:
    """
    Check if games for a date are likely complete.

    Games typically end by 1am ET the next day.
    """
    now_et = datetime.now(ET)
    game_date_end = ET.localize(datetime.combine(game_date + timedelta(days=1), datetime.min.time()))
    game_date_end = game_date_end.replace(hour=1)  # 1am ET next day

    return now_et > game_date_end

def get_validation_date_range(days_back: int = 7) -> tuple:
    """
    Get safe date range for validation.

    Excludes today if games haven't completed yet.
    """
    end_date = get_current_nba_date()

    # If it's before 1am ET, don't include today's date
    if not is_games_likely_complete(end_date):
        end_date = end_date - timedelta(days=1)

    start_date = end_date - timedelta(days=days_back - 1)

    return (start_date, end_date)
```

**Files to Create:**
- `/shared/utils/timezone_utils.py`

**Files to Modify:**
- All validators that use `date.today()` or `CURRENT_DATE()`
- All processors that compute game dates

---

### P2.C: Query Cost Monitoring

**Status:** NEW from V2 review
**Priority:** P2 (Medium)
**Effort:** Low
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §4.2

**The Gap:**

New validators run many BigQuery queries. No cost monitoring to track if validation is becoming expensive.

**Solution:**

Create BigQuery views to track query costs by source (validation, backfill, prediction, etc.) and alert if daily validation cost exceeds threshold.

**Implementation:**

```sql
-- Create cost monitoring view
CREATE OR REPLACE VIEW `nba_orchestration.v_query_costs_by_source` AS
SELECT
  DATE(creation_time) as query_date,
  CASE
    WHEN query LIKE '%validation%' THEN 'validation'
    WHEN query LIKE '%backfill%' THEN 'backfill'
    WHEN query LIKE '%prediction%' THEN 'prediction'
    WHEN query LIKE '%grading%' THEN 'grading'
    ELSE 'other'
  END as query_source,
  COUNT(*) as query_count,
  SUM(total_bytes_billed) / POW(1024, 4) as tb_billed,
  SUM(total_bytes_billed) / POW(1024, 4) * 6.25 as estimated_cost_usd,
  AVG(total_slot_ms) / 1000 as avg_slot_seconds
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
AND job_type = 'QUERY'
AND state = 'DONE'
GROUP BY 1, 2
ORDER BY 1 DESC, estimated_cost_usd DESC;

-- Alert if daily validation cost exceeds threshold
CREATE SCHEDULED QUERY check_validation_costs
SCHEDULE 'every day 08:00'
AS
SELECT
  query_date,
  query_source,
  estimated_cost_usd
FROM `nba_orchestration.v_query_costs_by_source`
WHERE query_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
AND query_source = 'validation'
AND estimated_cost_usd > 5.00;  -- Alert if > $5/day
```

**Files to Create:**
- `/schemas/bigquery/orchestration/v_query_costs_by_source.sql`

---

### P2.D: Structured Logging Standard

**Status:** NEW from V2 review
**Priority:** P2 (Medium)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §4.1

**The Gap:**

Logs are inconsistent across modules. No correlation IDs for tracing requests through pipeline phases.

**Solution:**

Implement structured logging with:
- JSON format for Cloud Logging
- Correlation IDs (run_id) for request tracing
- Standard log context (environment, service, processor)
- Consistent event naming

**Implementation:**

```python
# shared/utils/structured_logger.py
"""Structured logging with correlation IDs."""

import structlog
import uuid
from contextvars import ContextVar

# Context variable for request/run ID
_run_id: ContextVar[str] = ContextVar('run_id', default='')

def get_run_id() -> str:
    return _run_id.get() or str(uuid.uuid4())[:8]

def set_run_id(run_id: str):
    _run_id.set(run_id)

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()  # JSON for cloud logging
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

def get_logger(name: str = None):
    """Get a structured logger with automatic context."""
    logger = structlog.get_logger(name)

    # Bind common context
    return logger.bind(
        run_id=get_run_id(),
        environment=os.environ.get('ENVIRONMENT', 'development'),
        service=os.environ.get('K_SERVICE', 'unknown'),
    )

# Usage:
"""
from shared.utils.structured_logger import get_logger, set_run_id

logger = get_logger(__name__)
set_run_id(str(uuid.uuid4())[:8])

logger.info(
    "processing_started",
    processor="boxscore_processor",
    game_id=game_id,
    game_date=game_date
)
"""
```

**Files to Create:**
- `/shared/utils/structured_logger.py`

**Files to Modify:**
- All processors and cloud functions (gradual migration)

---

### P2.E: Seasonal Edge Case Handling

**Status:** NEW from V2 review
**Priority:** P2 (Medium)
**Effort:** Low
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §3.1

**The Gap:**

Validators might alert on "missing data" when there are legitimately no games (All-Star break, off-season, etc.)

**Solution:**

Create schedule-aware utilities that validators can use to check if games are expected before alerting.

**Implementation:**

```python
# shared/utils/schedule_awareness.py
"""Schedule-aware utilities for validators."""

from datetime import date

# NBA schedule constants
ALL_STAR_BREAK_2026 = (date(2026, 2, 14), date(2026, 2, 19))
REGULAR_SEASON_2026 = (date(2025, 10, 22), date(2026, 4, 13))
PLAYOFFS_2026 = (date(2026, 4, 19), date(2026, 6, 22))

def is_game_day(check_date: date) -> bool:
    """Check if games are expected on this date."""
    # Off-season: no games expected
    if check_date < REGULAR_SEASON_2026[0] or check_date > PLAYOFFS_2026[1]:
        return False

    # All-Star break: no games (except All-Star game itself)
    if ALL_STAR_BREAK_2026[0] <= check_date <= ALL_STAR_BREAK_2026[1]:
        if check_date == date(2026, 2, 16):  # All-Star Sunday
            return True
        return False

    return True

def get_schedule_context(check_date: date) -> dict:
    """Get context about the schedule for a date."""
    return {
        "is_game_day": is_game_day(check_date),
        "is_all_star_break": ALL_STAR_BREAK_2026[0] <= check_date <= ALL_STAR_BREAK_2026[1],
        "is_playoffs": PLAYOFFS_2026[0] <= check_date <= PLAYOFFS_2026[1],
        "is_off_season": check_date < REGULAR_SEASON_2026[0] or check_date > PLAYOFFS_2026[1],
    }

# Usage in validators:
def validate_with_schedule_awareness(check_date: str):
    """Only alert if games were expected."""

    context = get_schedule_context(date.fromisoformat(check_date))

    if not context["is_game_day"]:
        logger.info(f"No games expected for {check_date}, skipping validation")
        return {"status": "skipped", "reason": "no_games_expected", "context": context}

    # Proceed with normal validation
    return run_normal_validation(check_date)
```

**Files to Create:**
- `/shared/utils/schedule_awareness.py`

**Files to Modify:**
- All validators that check for "missing games"

---

## P3 Advanced Features (From V2 Recommendations)

> **Source:** ADDITIONAL-RECOMMENDATIONS-V2.md - Advanced features for long-term resilience

### P3.A: Concurrency Protection (Distributed Locks)

**Status:** NEW from V2 review
**Priority:** P3 (Low)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §2.3

**The Gap:**

What happens if two validator instances run simultaneously? Or if auto-retry processes the same job twice? No protection against concurrent execution.

**Solution:**

Implement distributed locking using BigQuery (simple approach) or Redis (production approach).

**Implementation:**

```python
# shared/utils/distributed_lock.py
"""Distributed locking using BigQuery (simple approach)."""

from google.cloud import bigquery
from datetime import datetime, timedelta
import uuid

class BigQueryLock:
    """Simple distributed lock using BigQuery."""

    def __init__(self, lock_name: str, ttl_seconds: int = 300):
        self.lock_name = lock_name
        self.ttl_seconds = ttl_seconds
        self.lock_id = str(uuid.uuid4())
        self.bq_client = bigquery.Client()

    def acquire(self) -> bool:
        """Attempt to acquire lock. Returns True if successful."""

        query = """
        INSERT INTO `nba_orchestration.distributed_locks`
        (lock_name, lock_id, acquired_at, expires_at)
        SELECT
            @lock_name,
            @lock_id,
            CURRENT_TIMESTAMP(),
            TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL @ttl SECOND)
        WHERE NOT EXISTS (
            SELECT 1 FROM `nba_orchestration.distributed_locks`
            WHERE lock_name = @lock_name
            AND expires_at > CURRENT_TIMESTAMP()
        )
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lock_name", "STRING", self.lock_name),
                bigquery.ScalarQueryParameter("lock_id", "STRING", self.lock_id),
                bigquery.ScalarQueryParameter("ttl", "INT64", self.ttl_seconds),
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        return result.num_dml_affected_rows > 0

    def release(self):
        """Release the lock."""
        query = """
        DELETE FROM `nba_orchestration.distributed_locks`
        WHERE lock_name = @lock_name AND lock_id = @lock_id
        """
        # ... implementation

    def __enter__(self):
        if not self.acquire():
            raise LockNotAcquiredError(f"Could not acquire lock: {self.lock_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

# Usage in validators:
def run_validator_with_lock(validator_name: str, date: str):
    """Run validator with distributed lock to prevent concurrent runs."""

    lock_name = f"validator_{validator_name}_{date}"

    try:
        with BigQueryLock(lock_name, ttl_seconds=600):
            return run_validation(validator_name, date)
    except LockNotAcquiredError:
        logger.info(f"Validator {validator_name} already running for {date}, skipping")
        return {"status": "skipped", "reason": "already_running"}
```

**Lock Table Schema:**
```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.distributed_locks` (
    lock_name STRING NOT NULL,
    lock_id STRING NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL
);
```

**Files to Create:**
- `/shared/utils/distributed_lock.py`
- `/schemas/bigquery/orchestration/distributed_locks.sql`

---

### P3.B: NBA Stat Correction Handling

**Status:** NEW from V2 review
**Priority:** P3 (Low)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §3.4

**The Gap:**

NBA sometimes updates stats 1-3 days after games. Predictions graded against original stats might become "incorrect" after corrections.

**Solution:**

Track stat versions in boxscore tables and trigger regrading when stats are updated.

**Implementation:**

```python
# Track stat versions - add to boxscore tables:
#   - source_version: INT (increments on corrections)
#   - last_updated_at: TIMESTAMP
#   - original_values: JSON (snapshot of first version)

# In grading processor:
def should_regrade_predictions(game_date: str) -> list:
    """
    Check if any boxscores have been updated since grading.

    Returns list of games that need regrading.
    """

    query = """
    SELECT DISTINCT b.game_id
    FROM `nba_raw.bdl_player_boxscores` b
    JOIN `nba_predictions.prediction_accuracy` pa
        ON b.game_id = pa.game_id
    WHERE b.game_date = @game_date
    AND b.last_updated_at > pa.graded_at
    """

    return run_query(query, {"game_date": game_date})

# Add to daily validation:
def check_for_stat_corrections(days_back: int = 7):
    """Alert if stat corrections might affect grading."""

    query = """
    SELECT
        game_date,
        COUNT(DISTINCT game_id) as games_with_updates,
        MAX(last_updated_at) as latest_update
    FROM `nba_raw.bdl_player_boxscores`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    AND last_updated_at > DATE_ADD(game_date, INTERVAL 2 DAY)  -- Updated 2+ days after game
    GROUP BY 1
    HAVING games_with_updates > 0
    """

    corrections = run_query(query, {"days": days_back})

    if corrections:
        logger.warning(f"Found {len(corrections)} dates with stat corrections")
        # Could trigger regrade
```

**Files to Modify:**
- Boxscore table schemas (add version tracking)
- Grading processor (add regrade logic)

**Files to Create:**
- `/bin/validation/check_stat_corrections.py`

---

### P3.C: Meta-Validator (Who Watches the Watchmen?)

**Status:** NEW from V2 review
**Priority:** P3 (Low)
**Effort:** Low
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §4.4

**The Gap:**

What if a validator itself is broken and not running? No system to validate that validators are healthy.

**Solution:**

Create meta-validator that checks:
- Recent validation runs exist (not stale)
- No validator has 100% failure rate
- Scheduled validators actually ran

**Implementation:**

```python
# bin/validation/meta_validator.py
"""Validate that validators are running correctly."""

def check_validator_health():
    """Verify validators are running and producing results."""

    checks = []

    # Check 1: Recent validation runs exist
    query = """
    SELECT validator_name, MAX(run_timestamp) as last_run
    FROM `nba_orchestration.validation_runs`
    GROUP BY 1
    """

    runs = run_query(query)

    for run in runs:
        hours_since_run = (datetime.now() - run.last_run).total_seconds() / 3600

        if hours_since_run > 24:
            checks.append({
                "validator": run.validator_name,
                "status": "stale",
                "hours_since_run": hours_since_run,
                "severity": "warning"
            })

    # Check 2: No validator has 100% failure rate recently
    query = """
    SELECT
        validator_name,
        COUNTIF(passed) / COUNT(*) as pass_rate
    FROM `nba_orchestration.validation_results`
    WHERE run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY 1
    HAVING pass_rate = 0  -- 100% failure rate
    """

    all_failures = run_query(query)

    for failure in all_failures:
        checks.append({
            "validator": failure.validator_name,
            "status": "all_failures",
            "pass_rate": 0,
            "severity": "error"
        })

    # Check 3: Scheduled validators actually ran
    expected_daily = ['daily_data_completeness', 'workflow_health', 'comprehensive_health_check']

    query = """
    SELECT validator_name
    FROM `nba_orchestration.validation_runs`
    WHERE run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND validator_name IN UNNEST(@expected)
    """

    ran_today = [r.validator_name for r in run_query(query, {"expected": expected_daily})]
    missing = set(expected_daily) - set(ran_today)

    for validator in missing:
        checks.append({
            "validator": validator,
            "status": "did_not_run",
            "severity": "error"
        })

    return checks
```

**Files to Create:**
- `/bin/validation/meta_validator.py`

---

### P3.D: Partial Recovery Scripts

**Status:** NEW from V2 review
**Priority:** P3 (Low)
**Effort:** Medium
**Source:** ADDITIONAL-RECOMMENDATIONS-V2.md §5.2

**The Gap:**

Can we recover just one game without affecting others? Current backfill scripts work on date ranges, not individual games.

**Solution:**

Create single-game recovery script that traces through all phases.

**Implementation:**

```python
# bin/backfill/single_game_recovery.py
"""Recover a single game through all phases."""

import argparse
from datetime import date

def recover_single_game(game_id: str, game_date: str):
    """
    Recover a single game through the entire pipeline.

    Use when one game is missing but others are fine.
    """

    print(f"Recovering game {game_id} for {game_date}")

    # Phase 2: Boxscore
    print("Phase 2: Fetching boxscore...")
    from scrapers.balldontlie import BDLBoxscoreScraper
    scraper = BDLBoxscoreScraper()
    scraper.scrape_game(game_id, game_date)

    # Phase 3: Analytics
    print("Phase 3: Processing analytics...")
    from data_processors.analytics import PlayerGameSummaryProcessor
    processor = PlayerGameSummaryProcessor()
    processor.process_game(game_id, game_date)

    # Phase 4: Features
    print("Phase 4: Computing features...")
    from data_processors.precompute import MLFeatureStoreProcessor
    processor = MLFeatureStoreProcessor()
    processor.process_players_for_game(game_id, game_date)

    # Phase 6: Grading (if predictions exist)
    print("Phase 6: Grading predictions...")
    from data_processors.grading import PredictionAccuracyProcessor
    processor = PredictionAccuracyProcessor()
    processor.grade_game(game_id, game_date)

    print(f"Recovery complete for {game_id}")

    # Validate
    print("Validating recovery...")
    from bin.validation.trace_entity import trace_game
    trace_game(game_id)
```

**Files to Create:**
- `/bin/backfill/single_game_recovery.py`

---

## Implementation Dependencies

### Critical Path (Must Complete in Order)

```
1. Fix auto-retry processor (Bug #1)
   ↓ enables
2. Setup fallback subscriptions (P1.4)
   ↓ enables
3. Recover GSW@MIN boxscore (manual task)

Parallel track:
4. Investigate phase execution logging (Bug #2)
5. Create game ID mapping view (Bug #3)
6. Implement lazy imports (P1.5)
```

### P0 Track (Can Parallelize)

```
P0.1: Phase 4→5 gate
P0.2: Quality trend monitoring
P0.3: Cross-phase consistency validator
```

### P1 Track - Original (After P0)

```
P1.1: Validation scheduling ← requires P0.1, P0.2, P0.3
P1.2: Post-backfill validation
P1.3: Recovery validation
P1.4: Fallback topic subscriptions
P1.5: Lazy imports
```

### P1 Critical Additions Track (From V2 + Defense-in-Depth - HIGH PRIORITY)

> **These should be implemented alongside P0/P1 original work**

```
P1.A: Alerting implementation ← HIGH PRIORITY, enables all validators
P1.B: Circuit breaker for HTTP retries ← HIGH PRIORITY, protects auto-retry
P1.C: Health check before HTTP calls ← HIGH PRIORITY, improves retry success rate
P1.D: Rollback procedures documentation ← HIGH PRIORITY, reduces deployment risk
P1.E: Missing props alerting (NEW) ← HIGH PRIORITY, user request - Defense-in-Depth
P1.F: Model drift detection ← P1 from Defense-in-Depth
P1.G: Confidence calibration check ← P1 from Defense-in-Depth
P1.H: Odds staleness detection ← P1 from Defense-in-Depth
P1.I: Pub/Sub idempotency ← P1 from Defense-in-Depth
```

**Recommended Implementation Order:**
1. **Week 1:** P1.A (Alerting) + P1.D (Rollback docs) + P1.E (Props alerting) - Foundation
2. **Week 1:** P1.B (Circuit breaker) + P1.C (Health checks) - Auto-retry improvements
3. **Week 2:** P1.F (Model drift) + P1.G (Confidence calibration) - Prediction quality
4. **Week 2:** P1.H (Odds staleness) + P1.I (Idempotency) - Data freshness + reliability
5. Then proceed with P0 track as originally planned

### P2 Track - Original

```
P2.1: Real-time validation hooks
P2.2: Validation analytics dashboard
P2.3: Config drift in CI/CD
P2.4: Duplicate detection
P2.5: ESPN fallback scraper
P2.6: Entity tracing script
```

### P2 Operational Improvements Track (From V2 - MEDIUM PRIORITY)

```
P2.A: Operational runbook
P2.B: Timezone handling standardization
P2.C: Query cost monitoring
P2.D: Structured logging standard
P2.E: Seasonal edge case handling
```

### P3 Advanced Features Track (From V2 - LOW PRIORITY)

```
P3.A: Concurrency protection (distributed locks)
P3.B: NBA stat correction handling
P3.C: Meta-validator
P3.D: Partial recovery scripts
```

### Documentation

```
Ongoing: Update documentation as tasks complete
Add: DEPLOYMENT-GUIDE.md rollback section (P1.D)
Add: Operational runbooks (P2.A)
```

---

## Success Metrics

### Critical Bugs Fixed

- [x] Auto-retry processor publishes successfully
- [ ] Phase execution log populating
- [ ] Game ID mapping view deployed
- [ ] Fallback subscriptions active
- [ ] GSW@MIN boxscore recovered

### P0 Complete

- [ ] Phase 4→5 gate blocks predictions when quality < 70
- [ ] Quality trend monitoring alerts on >10% degradation
- [ ] Cross-phase validator detects >5% entity drop
- [ ] All P0 validators running in scheduled jobs

**Success Criteria:**
- Issues detected in < 30 minutes (vs 4+ hours)
- No bad predictions from degraded features
- Silent degradation caught before cascade

### P1 Complete (Original)

- [ ] Validators run automatically at strategic times
- [ ] Backfills auto-validate on completion
- [ ] Recovery validation can verify post-outage health
- [ ] Fallback topic subscriptions active
- [ ] Lazy imports implemented

**Success Criteria:**
- 80% reduction in manual intervention
- Backfill effectiveness tracked
- Recovery time measured

### P1 Critical Additions Complete (From V2 + Defense-in-Depth)

- [ ] **P1.A:** Alerting implementation operational (Slack + PagerDuty)
- [ ] **P1.B:** Circuit breaker protecting HTTP retries
- [ ] **P1.C:** Health checks before all HTTP calls
- [ ] **P1.D:** Rollback procedures documented in DEPLOYMENT-GUIDE.md
- [x] **P1.E:** Missing props alerting validator created and tested
- [ ] **P1.F:** Model drift detection monitoring accuracy trends
- [ ] **P1.G:** Confidence calibration validator ensuring confidence accuracy
- [ ] **P1.H:** Odds staleness detector blocking stale predictions
- [ ] **P1.I:** Pub/Sub idempotency preventing duplicate processing

**Success Criteria:**
- Alerts reach operators within 5 minutes of detection
- Circuit breaker prevents cascade failures
- Health checks reduce failed retry attempts by >50%
- Rollback procedures tested and documented
- Props availability alerts sent for games with <3 players (CRITICAL) or <8 players (WARNING)
- Model drift detected within 1 week of >5% accuracy drop
- Confidence scores calibrated within 10% of actual accuracy
- Stale odds (>6h old) blocked before predictions
- Zero duplicate message processing incidents

### P2 Complete (Original)

- [ ] Real-time validation in Cloud Functions
- [ ] Validation analytics dashboard operational
- [ ] Config drift blocks deployments
- [ ] Duplicate detection in all validators
- [ ] ESPN fallback operational
- [ ] Entity tracing available

**Success Criteria:**
- > 95% validation coverage
- < 5% false positive rate
- Config consistency enforced

### P2 Operational Improvements Complete (From V2)

- [ ] **P2.A:** Operational runbook created
- [ ] **P2.B:** Timezone handling standardized
- [ ] **P2.C:** Query cost monitoring active
- [ ] **P2.D:** Structured logging implemented
- [ ] **P2.E:** Seasonal edge cases handled

**Success Criteria:**
- Runbook reduces MTTR by >30%
- No timezone-related validation false positives
- Validation query costs < $5/day
- All logs have correlation IDs
- Validators skip off-season dates

### P3 Advanced Features Complete (From V2)

- [ ] **P3.A:** Distributed locks prevent concurrent execution
- [ ] **P3.B:** Stat corrections trigger regrading
- [ ] **P3.C:** Meta-validator monitors validator health
- [ ] **P3.D:** Single-game recovery script available

**Success Criteria:**
- No duplicate processing incidents
- Stat corrections detected within 24 hours
- Meta-validator catches broken validators
- Single-game recovery works reliably

### Overall System Health

| Metric | Baseline | Current Target | Achieved |
|--------|----------|----------------|----------|
| System health score | 7/10 | 9.5/10 | TBD |
| Time to detect issues | 4+ hours | < 30 min | TBD |
| Manual intervention | 100% | < 20% | TBD |
| Validation coverage | ~60% | > 95% | TBD |
| False positive rate | Unknown | < 5% | TBD |

---

## Quick Reference

### Validation Commands

```bash
# Daily health check
python bin/validation/daily_data_completeness.py --days 3

# Orchestration health
python bin/validation/workflow_health.py --hours 48

# Deep analysis
python bin/validation/comprehensive_health_check.py --date 2026-01-24

# Root cause analysis
python bin/validation/root_cause_analyzer.py --date 2026-01-24

# Phase transitions
python bin/validation/phase_transition_health.py --days 7

# Quality trends (NEW)
python bin/validation/quality_trend_monitor.py --days 14

# Cross-phase consistency (NEW)
python bin/validation/cross_phase_consistency.py --date 2026-01-24

# Post-backfill validation (NEW)
python bin/validation/validate_backfill.py --phase raw --date 2026-01-24

# Recovery validation (NEW)
python bin/validation/validate_recovery.py \
  --outage-start "2026-01-23 04:20" \
  --outage-end "2026-01-25 01:35"

# Entity tracing (NEW)
python bin/validation/trace_entity.py --player "LeBron James" --date 2026-01-24
```

### Deployment Commands

```bash
# Deploy auto-retry fix
./bin/orchestrators/deploy_auto_retry_processor.sh

# Deploy phase orchestrators
./bin/orchestrators/deploy_phase3_to_phase4.sh
./bin/orchestrators/deploy_phase4_to_phase5.sh
./bin/orchestrators/deploy_phase5_to_phase6.sh

# Setup fallback subscriptions
./bin/orchestrators/setup_fallback_subscriptions.sh

# Deploy validation schedulers (NEW)
./bin/orchestrators/deploy_validation_schedulers.sh

# Sync shared utils
./bin/orchestrators/sync_shared_utils.sh
```

### Manual Recovery Commands

```bash
# Backfill boxscores
python bin/backfill/bdl_boxscores.py --date 2026-01-24

# Backfill analytics
python bin/backfill/phase3.py --date 2026-01-24

# Backfill features
python bin/backfill/phase4.py --date 2026-01-24

# Backfill predictions
python bin/backfill/predictions.py --date 2026-01-24

# Backfill grading
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

### BigQuery Quick Checks

```sql
-- Check data completeness for today
SELECT
  'schedule' as phase, COUNT(*) as records
FROM `nba_raw.v_nbac_schedule_latest`
WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'boxscores', COUNT(DISTINCT game_id)
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'analytics', COUNT(DISTINCT player_lookup)
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'features', COUNT(DISTINCT player_lookup)
FROM `nba_precompute.ml_feature_store`
WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'predictions', COUNT(DISTINCT player_lookup)
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE();

-- Check feature quality
SELECT
  AVG(feature_quality_score) as avg_quality,
  MIN(feature_quality_score) as min_quality,
  MAX(feature_quality_score) as max_quality,
  COUNTIF(feature_quality_score >= 75) as high_quality_count,
  COUNTIF(feature_quality_score < 70) as low_quality_count
FROM `nba_precompute.ml_feature_store`
WHERE game_date = CURRENT_DATE();

-- Check failed processor queue
SELECT game_date, processor_name, status, retry_count, error_message
FROM `nba_orchestration.failed_processor_queue`
WHERE status IN ('pending', 'retrying', 'failed_permanent')
ORDER BY first_failure_at DESC
LIMIT 20;
```

---

## Next Steps

### Immediate (This Session)

1. ✅ Create comprehensive master plan (this document)
2. ⏳ Fix auto-retry processor
3. ⏳ Investigate phase execution logging
4. ⏳ Create game ID mapping view

### This Week

1. Complete all critical bugs
2. Implement all P0 improvements
3. Deploy validation scheduling
4. Create post-backfill validation

### This Month

1. Complete all P1 improvements
2. Start P2 improvements
3. Measure success metrics
4. Iterate based on results

---

## Recommended Implementation Timeline

### Week 1: Critical Foundation + Alerting + Props Monitoring

**Goals:** Fix critical bugs, establish alerting, document rollback, deploy props monitoring

1. **Critical Bugs (Days 1-2)**
   - Fix auto-retry processor HTTP endpoints
   - Investigate phase execution logging
   - Create game ID mapping view
   - Deploy fixes

2. **P1 Critical Additions (Days 3-5)**
   - P1.E: ✅ Deploy props availability validator (COMPLETED - user request)
   - P1.A: Implement alerting (Slack + PagerDuty)
   - P1.D: Document rollback procedures
   - P1.B: Add circuit breaker to auto-retry
   - P1.C: Add health checks to Cloud Run services

**Success Criteria:**
- Auto-retry working with HTTP endpoints
- Props availability validator alerting on missing/insufficient lines
- Alerts reaching Slack/PagerDuty
- Rollback procedures tested
- Circuit breaker preventing cascade failures

### Week 2: Prevention Gates + Prediction Quality Monitoring

**Goals:** Implement proactive prevention, automate validators, add prediction quality monitoring

3. **P0 Improvements (Days 6-8)**
   - P0.1: Implement Phase 4→5 gate
   - P0.2: Deploy quality trend monitoring
   - P0.3: Deploy cross-phase consistency validator

4. **P1 Defense-in-Depth (Days 9-10)**
   - P1.F: Model drift detection (monitor accuracy trends)
   - P1.G: Confidence calibration check (validate confidence scores)
   - P1.H: Odds staleness detection (block stale predictions)

5. **P1 Automation (Days 11-12)**
   - P1.1: Setup validation scheduling
   - P1.2: Implement post-backfill validation
   - P1.4: Setup fallback subscriptions

**Success Criteria:**
- Gate blocks low-quality predictions
- Trend monitoring catches degradation early
- Model drift detected within 1 week of >5% drop
- Confidence scores calibrated within 10%
- Stale odds blocked before predictions
- Validators run automatically
- Backfills auto-validate

### Week 3: Operational Improvements + Idempotency

**Goals:** Improve observability, handle edge cases, add idempotency

5. **P2 Operational (Days 13-15)**
   - P2.A: Create operational runbook
   - P2.B: Standardize timezone handling
   - P2.C: Setup query cost monitoring
   - P2.E: Handle seasonal edge cases

6. **P1 + P2 Remaining (Days 16-17)**
   - P1.I: Pub/Sub idempotency implementation (Defense-in-Depth)
   - P1.3: Recovery validation framework
   - P1.5: Implement lazy imports
   - P2.D: Structured logging (start migration)

**Success Criteria:**
- Runbook available for operators
- No timezone false positives
- Query costs monitored
- Zero duplicate message processing
- Recovery validation working

### Week 4: Advanced Features

**Goals:** Add advanced features, improve analytics

7. **P2 Advanced (Days 18-21)**
   - P2.1: Real-time validation hooks
   - P2.2: Validation analytics dashboard
   - P2.3: Config drift in CI/CD
   - P2.4: Duplicate detection
   - P2.6: Entity tracing script

**Success Criteria:**
- Real-time validation catching issues
- Analytics dashboard showing trends
- Config drift blocks bad deployments
- Entity tracing available for debugging

### Future Enhancements (P3 - As Needed)

8. **P3 Advanced Features**
   - P3.A: Distributed locks (if concurrency issues arise)
   - P3.B: Stat correction handling (if NBA corrections become frequent)
   - P3.C: Meta-validator (for validator health monitoring)
   - P3.D: Single-game recovery (if needed frequently)
   - P2.5: ESPN fallback scraper (if BDL becomes unreliable)

**Implement based on:**
- Actual observed issues
- Frequency of need
- Available development time

---

## Summary: Task Count by Priority

| Priority | Original Plan | V2 Additions | Defense-in-Depth | Total | Status |
|----------|--------------|--------------|------------------|-------|--------|
| **Critical Bugs** | 3 | 3 items | - | 6 | In Progress |
| **P0** | 3 | - | - | 3 | Not Started |
| **P1** | 5 | 4 critical | 5 (E-I) | **14** | 1 Complete |
| **P2** | 6 | 5 operational | - | 11 | Not Started |
| **P3** | - | 4 advanced | - | 4 | Future |
| **Total** | 17 | 16 | 5 | **38** | - |

**P1 Breakdown:**
- P1.A-D: V2 Critical Additions (Alerting, Circuit Breaker, Health Checks, Rollback Docs)
- P1.E: Missing Props Alerting (USER REQUEST - ✅ COMPLETED)
- P1.F-I: Defense-in-Depth P1 Items (Model Drift, Confidence Calibration, Odds Staleness, Idempotency)

---

## Key Takeaways

1. **Alerting is Critical:** P1.A should be implemented early to enable all other validators to notify operators

2. **User Requests Take Priority:** P1.E (Missing Props Alerting) was a direct user request and has been completed first

3. **Protection Before Scale:** P1.B and P1.C protect auto-retry from causing issues at scale

4. **Documentation Reduces Risk:** P1.D rollback procedures reduce deployment anxiety and improve MTTR

5. **Defense-in-Depth Matters:** P1.F-I add critical monitoring for prediction quality, data freshness, and reliability

6. **Operational Maturity:** P2 improvements (runbook, timezone, cost monitoring, structured logging, edge cases) significantly improve operational maturity

7. **Build for Future:** P3 features are insurance policies - implement when/if needed

8. **Phased Approach:** Don't try to do everything at once. Week-by-week progression allows for learning and adjustment

9. **Prediction Quality Monitoring:** Model drift (P1.F) and confidence calibration (P1.G) ensure predictions remain accurate over time

10. **Data Freshness is Key:** Odds staleness detection (P1.H) and props availability (P1.E) prevent predictions based on stale data

---

**Document Status:** Living Document - Enhanced with V2 Recommendations
**Last Updated:** 2026-01-25
**Next Review:** After Week 1 completion
**Owner:** NBA Stats Pipeline Team

**Related Documents:**
- `/docs/09-handoff/2026-01-25-ADDITIONAL-RECOMMENDATIONS.md` - Original additional recommendations
- `/docs/08-projects/current/validation-framework/ADDITIONAL-RECOMMENDATIONS-V2.md` - V2 comprehensive recommendations
- `/DEPLOYMENT-GUIDE.md` - Will be enhanced with rollback procedures (P1.D)
