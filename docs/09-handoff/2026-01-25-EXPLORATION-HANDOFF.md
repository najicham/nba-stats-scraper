# Exploration Handoff: Continue Finding Improvements

**Date:** 2026-01-25
**Purpose:** Guide for continuing system exploration and finding more improvements
**Context:** Multiple sessions have analyzed the system; this continues that work

---

## What's Been Done

### Documents to Read First

1. **`docs/09-handoff/2026-01-25-FINAL-COMPREHENSIVE-HANDOFF.md`** - Complete findings from implementation session
2. **`docs/08-projects/current/validation-framework/MASTER-IMPROVEMENT-PLAN.md`** - Master plan with all improvements
3. **`docs/09-handoff/2026-01-25-ADDITIONAL-RECOMMENDATIONS.md`** - Latest findings including HTTP URL issue

### Issues Already Identified

| Issue | Status | Priority |
|-------|--------|----------|
| Grading not running for 3 games | Needs backfill | P0 |
| Auto-retry HTTP URLs may not resolve | Needs verification | P0 |
| Duplicate prediction records | Needs cleanup | P1 |
| 7,061 bare `except: pass` statements | Needs phased cleanup | P1 |
| Phase execution log empty | Needs investigation | P2 |
| Gate overrides table not created | Needs creation | P2 |
| Daily reconciliation not scheduled | Needs automation | P2 |
| ESPN fallback not implemented | Future work | P3 |

### Improvements Already Implemented

- P0 validators (Phase 4→5 gate, quality trends, cross-phase consistency)
- Auto-retry processor HTTP fix (needs URL verification)
- Lazy imports for cloud functions
- Game ID mapping view
- Fallback subscription setup script
- Entity tracing tool
- Post-backfill validation

---

## Areas to Explore for More Improvements

### 1. Scraper Resilience

**Location:** `/scrapers/`

**Questions to investigate:**
- What happens when BDL API returns partial data?
- Are there rate limiting issues causing failures?
- How are API errors logged and tracked?
- Is there retry logic with exponential backoff?

**Commands to explore:**
```bash
# Find error handling in scrapers
grep -rn "except" scrapers/ --include="*.py" | head -30

# Check for rate limiting
grep -rn "rate\|limit\|throttle" scrapers/ --include="*.py"

# Check retry logic
grep -rn "retry\|backoff" scrapers/ --include="*.py"
```

---

### 2. Data Processor Edge Cases

**Location:** `/data_processors/`

**Questions to investigate:**
- What happens when upstream data is incomplete?
- Are there any processors that silently skip records?
- How is data quality validated before processing?
- Are there memory issues with large batches?

**Commands to explore:**
```bash
# Find processors without proper error handling
grep -rn "except:" data_processors/ --include="*.py" | grep -v "except.*:"

# Check for skip/continue patterns that might hide issues
grep -rn "continue\|skip" data_processors/ --include="*.py"

# Find any hardcoded limits or thresholds
grep -rn "LIMIT\|limit\|threshold" data_processors/ --include="*.py"
```

---

### 3. Prediction System Quality

**Location:** `/predictions/`

**Questions to investigate:**
- Why are predictions being inserted twice? (duplicate issue found)
- What's the prediction accuracy by model type?
- Are there edge cases where predictions fail silently?
- How are feature quality issues handled?

**Queries to run:**
```sql
-- Check prediction accuracy by system
SELECT
  system_id,
  COUNT(*) as predictions,
  AVG(ABS(predicted_points - actual_points)) as avg_error
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.player_prop_predictions` p USING (player_lookup, game_date)
WHERE pa.game_date >= '2026-01-15'
  AND actual_points IS NOT NULL
GROUP BY 1
ORDER BY avg_error;

-- Find predictions with extreme values (potential bugs)
SELECT player_lookup, game_date, predicted_points, system_id
FROM `nba_predictions.player_prop_predictions`
WHERE predicted_points > 50 OR predicted_points < 0
LIMIT 20;
```

---

### 4. Orchestration Gaps

**Location:** `/orchestration/`

**Questions to investigate:**
- Are there any race conditions in phase transitions?
- What happens if Firestore is slow but not down?
- Are timeouts appropriate for each phase?
- How are partial completions handled?

**Commands to explore:**
```bash
# Check timeout configurations
grep -rn "timeout\|TIMEOUT" orchestration/ --include="*.py"

# Find potential race conditions
grep -rn "atomic\|transaction\|lock" orchestration/ --include="*.py"

# Check deadline/SLA handling
grep -rn "deadline\|sla\|SLA" orchestration/ --include="*.py"
```

---

### 5. Monitoring Gaps

**Location:** `/bin/monitoring/`, `/bin/validation/`

**Questions to investigate:**
- What metrics are NOT being tracked?
- Are there silent failures that go undetected?
- Is alerting working for all critical paths?
- What's the mean time to detection for issues?

**Commands to explore:**
```bash
# List all monitoring scripts
ls -la bin/monitoring/ bin/validation/

# Check what's being logged vs what should be
grep -rn "logger\|logging" shared/ --include="*.py" | wc -l

# Find Sentry integration gaps
grep -rn "sentry\|capture_exception" --include="*.py" | wc -l
```

---

### 6. Database/BigQuery Issues

**Questions to investigate:**
- Are there any tables without proper partitioning?
- Are there expensive queries that could be optimized?
- Is data retention being managed?
- Are there orphaned records in any tables?

**Queries to run:**
```sql
-- Check table sizes and partitioning
SELECT
  table_name,
  ROUND(SUM(total_logical_bytes) / 1024 / 1024 / 1024, 2) as size_gb
FROM `nba_raw.INFORMATION_SCHEMA.TABLE_STORAGE`
GROUP BY 1
ORDER BY size_gb DESC
LIMIT 20;

-- Find tables without partitioning
SELECT table_name, partition_column
FROM `nba_raw.INFORMATION_SCHEMA.COLUMNS`
WHERE is_partitioning_column = 'YES';

-- Check for orphaned records (analytics without boxscores)
SELECT COUNT(*) as orphaned
FROM `nba_analytics.player_game_summary` a
LEFT JOIN `nba_raw.bdl_player_boxscores` b
  ON a.game_id = b.game_id AND a.player_lookup = b.player_lookup
WHERE b.player_lookup IS NULL
  AND a.game_date >= '2026-01-01';
```

---

### 7. Configuration Drift

**Location:** `/shared/config/`, `/orchestration/cloud_functions/*/shared/config/`

**Questions to investigate:**
- Are configs consistent across cloud functions?
- Are there hardcoded values that should be configurable?
- Is there config validation on startup?

**Commands to explore:**
```bash
# Compare configs between cloud functions
diff orchestration/cloud_functions/phase3_to_phase4/shared/config/orchestration_config.py \
     orchestration/cloud_functions/phase4_to_phase5/shared/config/orchestration_config.py

# Find hardcoded values
grep -rn "= [0-9]\+\|= '[^']*'\|= \"[^\"]*\"" shared/config/ --include="*.py" | head -30

# Check if config drift detection exists
cat bin/validation/detect_config_drift.py 2>/dev/null | head -50
```

---

### 8. Cloud Function Resource Issues

**Questions to investigate:**
- Are memory limits appropriate?
- Are there cold start issues?
- Are timeouts causing failures?

**Commands to explore:**
```bash
# Check all cloud function configs
for fn in phase2-to-phase3-orchestrator phase3-to-phase4-orchestrator phase4-to-phase5-orchestrator phase5-to-phase6-orchestrator auto-retry-processor; do
  echo "=== $fn ==="
  gcloud functions describe $fn --region us-west2 2>&1 | grep -E "memory|timeout|availableMemory"
done

# Check for OOM errors in logs
gcloud functions logs read --region us-west2 --limit 500 2>&1 | grep -i "memory\|oom\|killed"
```

---

### 9. External API Dependencies

**Questions to investigate:**
- What happens when BDL API is slow?
- Are there circuit breakers for external calls?
- How are API quotas tracked?
- Is there fallback when APIs fail?

**Commands to explore:**
```bash
# Find external API calls
grep -rn "requests\.\|httpx\.\|urllib" --include="*.py" | grep -v test | head -30

# Check for circuit breaker patterns
grep -rn "circuit\|breaker\|fallback" --include="*.py"

# Find timeout configurations for API calls
grep -rn "timeout=" --include="*.py" | head -20
```

---

### 10. Testing Coverage

**Location:** `/tests/`

**Questions to investigate:**
- What's the test coverage?
- Are critical paths tested?
- Are there integration tests?
- Do tests run in CI?

**Commands to explore:**
```bash
# Count tests
find tests/ -name "test_*.py" | wc -l

# Check what's tested
ls -la tests/

# Look for CI configuration
cat .github/workflows/*.yml 2>/dev/null | head -50
```

---

## Quick Validation Commands

Run these to get current system health:

```bash
# Data completeness last 3 days
python bin/validation/daily_data_completeness.py --days 3

# Workflow health
python bin/validation/workflow_health.py --hours 48

# Phase transitions
python bin/validation/phase_transition_health.py --days 3

# Check failed processor queue
bq query --use_legacy_sql=false "
SELECT game_date, processor_name, status, retry_count
FROM nba_orchestration.failed_processor_queue
WHERE status IN ('pending', 'retrying', 'failed_permanent')
ORDER BY first_failure_at DESC
LIMIT 10"

# Check recent errors
bq query --use_legacy_sql=false "
SELECT DATE(timestamp) as date, event_type, COUNT(*) as count
FROM nba_orchestration.pipeline_event_log
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
GROUP BY 1, 2
ORDER BY 1 DESC, count DESC"
```

---

## Known Patterns to Look For

### Red Flags in Code

```python
# Silent error swallowing (7,061 instances found)
except:
    pass

# Hardcoded credentials or secrets
API_KEY = "abc123"

# Missing timeout on external calls
requests.get(url)  # Should have timeout=

# Unbounded queries
SELECT * FROM table  # Should have LIMIT or date filter

# Race condition prone patterns
if not exists:
    create()  # Another process might create between check and create
```

### Red Flags in Data

```sql
-- Duplicate records (found in predictions)
SELECT key, COUNT(*) FROM table GROUP BY key HAVING COUNT(*) > 1

-- NULL in required fields
SELECT * FROM table WHERE required_field IS NULL

-- Orphaned records
SELECT * FROM child LEFT JOIN parent WHERE parent.id IS NULL

-- Data outside expected ranges
SELECT * FROM table WHERE value < 0 OR value > 100
```

---

## Suggested Exploration Order

1. **Start with validation scripts** - Run them, see what they report
2. **Check recent errors** - Query pipeline_event_log for errors
3. **Review scraper resilience** - Most external-facing, most failure prone
4. **Examine processor edge cases** - Where data transformations happen
5. **Audit orchestration logic** - Complex state management
6. **Check monitoring coverage** - What's NOT being tracked

---

## When You Find Issues

For each issue found, document:

1. **What:** Clear description of the problem
2. **Where:** File path and line numbers
3. **Impact:** What breaks if this isn't fixed
4. **Fix:** Proposed solution or investigation steps
5. **Priority:** P0 (critical), P1 (high), P2 (medium), P3 (low)

Add findings to:
- `docs/09-handoff/2026-01-25-ADDITIONAL-RECOMMENDATIONS.md` for urgent items
- `docs/08-projects/current/validation-framework/MASTER-IMPROVEMENT-PLAN.md` for planned improvements

---

## Context: System Architecture

```
Phase 1: Scrapers (BDL, NBA.com, Odds API) → GCS
    ↓ Pub/Sub: nba-phase1-scrapers-complete
Phase 2: Raw Processors → BigQuery nba_raw.*
    ↓ Pub/Sub: nba-phase2-raw-complete
Phase 3: Analytics Processors → BigQuery nba_analytics.*
    ↓ Pub/Sub: nba-phase3-analytics-complete
Phase 4: Precompute Processors → BigQuery nba_precompute.*
    ↓ Pub/Sub: nba-phase4-precompute-complete
Phase 5: Predictions → BigQuery nba_predictions.*
    ↓ Pub/Sub: nba-phase5-predictions-complete
Phase 6: Grading/Export
```

**Key Tables:**
- `nba_orchestration.failed_processor_queue` - Retry queue
- `nba_orchestration.pipeline_event_log` - Event audit log
- `nba_orchestration.workflow_decisions` - Master controller decisions
- `nba_predictions.player_prop_predictions` - ML predictions
- `nba_predictions.prediction_accuracy` - Grading results

---

## Tips for Effective Exploration

1. **Use the Task tool with Explore agent** for codebase searches
2. **Query BigQuery directly** for data issues
3. **Check cloud function logs** for runtime errors
4. **Compare expected vs actual** - counts, values, timing
5. **Follow the data flow** - trace from scraper to prediction
6. **Look for silent failures** - things that fail but don't alert

---

*Created: 2026-01-25*
*Purpose: Guide for continued system exploration*
*Related: MASTER-IMPROVEMENT-PLAN.md, ADDITIONAL-RECOMMENDATIONS.md*
