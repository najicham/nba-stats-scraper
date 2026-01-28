# Master Action List - Data Quality & Observability

**Created**: 2026-01-28
**Status**: Ready for execution

---

## Priority 0: Production Blockers (DO IMMEDIATELY)

### P0-1: Fix Orchestrator Module Imports
**Effort**: 2-3 hours | **Impact**: 🔴 Critical

The `phase3-to-phase4-orchestrator` (and likely other orchestrators) are failing due to import errors:
```
ModuleNotFoundError: No module named 'shared.utils'
```

**Files to fix** (7 files):
1. `orchestration/shared/utils/bigquery_utils.py` (lines 23-24)
2. `orchestration/shared/utils/bigquery_utils_v2.py` (lines 33-35)
3. `orchestration/shared/utils/odds_preference.py`
4. `orchestration/shared/utils/odds_player_props_preference.py`
5. `orchestration/shared/utils/processor_alerting.py`
6. `orchestration/shared/utils/data_freshness_checker.py`
7. `orchestration/shared/utils/phase_execution_logger.py`

**Fix approach**:
```python
# BEFORE (broken):
from shared.utils.retry_with_jitter import retry_with_jitter
from shared.config.gcp_config import get_project_id

# AFTER (fixed):
from orchestration.shared.utils.retry_with_jitter import retry_with_jitter
from orchestration.shared.utils.gcp_config import get_project_id
```

**Additional**: May need to copy `gcp_config.py` from `shared/config/` to `orchestration/shared/utils/`

**Deployment**:
```bash
# After fixing imports, redeploy all orchestrators
gcloud run deploy phase3-to-phase4-orchestrator --source=orchestration/cloud_functions/phase3_to_phase4 --region=us-west2
gcloud run deploy phase4-to-phase5-orchestrator --source=orchestration/cloud_functions/phase4_to_phase5 --region=us-west2
# etc.
```

---

### P0-2: Backfill Missing Predictions
**Effort**: 30 min | **Impact**: 🔴 Critical

After fixing orchestrators, manually trigger Phase 4 and 5 for missing dates:

```bash
# Phase 4 for Jan 26
curl -X POST "https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-01-26", "trigger_source": "manual_backfill"}'

# Phase 4 for Jan 27
curl -X POST "https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-01-27", "trigger_source": "manual_backfill"}'

# Then trigger Phase 5 for each date (predictions)
```

---

## Priority 1: Observability Improvements (This Week)

### P1-1: Add Phase Execution Gap Detection to /validate-daily
**Effort**: 3-4 hours | **Value**: High

Add **Phase 0.5** checks to detect stalled orchestrators BEFORE running other validation:

**New checks to add**:
1. Missing phase execution logs (orchestrator never ran)
2. Stalled orchestrators (started but didn't complete)
3. Phase transition timing gaps (>30 min = critical)
4. Missing processor run records

**File**: `.claude/skills/validate-daily/SKILL.md`

**Key query**:
```sql
-- Detect missing phase execution logs
WITH expected_phases AS (
  SELECT 'phase2_to_phase3' as phase_name UNION ALL
  SELECT 'phase3_to_phase4' UNION ALL
  SELECT 'phase4_to_phase5'
),
actual_logs AS (
  SELECT DISTINCT phase_name
  FROM nba_orchestration.phase_execution_log
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT e.phase_name,
  CASE WHEN a.phase_name IS NULL THEN 'MISSING' ELSE 'EXISTS' END as status
FROM expected_phases e
LEFT JOIN actual_logs a USING (phase_name);
```

---

### P1-2: Create Pipeline Health Summary View
**Effort**: 4-6 hours | **Value**: High

**Good news**: Partial infrastructure already exists at `monitoring/bigquery_views/pipeline_health_summary.sql`

**Action**: Enhance existing view with:
```sql
CREATE OR REPLACE VIEW nba_monitoring.phase_processor_health_summary AS
SELECT
  phase,
  processor_name,
  MAX(processed_at) FILTER (WHERE status = 'success') as last_success_time,
  COUNTIF(status IN ('failed', 'partial')
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)) as failures_24h,
  DATE_DIFF(CURRENT_DATE(),
    CAST(MAX(processed_at) FILTER (WHERE status = 'success') AS DATE), DAY) as days_since_success,
  CASE
    WHEN last_success_time IS NULL THEN 'NEVER_RAN'
    WHEN days_since_success > 7 THEN 'STALE'
    WHEN failures_24h > 5 THEN 'UNHEALTHY'
    WHEN failures_24h > 0 THEN 'DEGRADED'
    ELSE 'HEALTHY'
  END as health_status
FROM nba_reference.processor_run_history
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY phase, processor_name;
```

**Then**: Set up hourly scheduled query to materialize this view.

---

### P1-3: Create Centralized Service Errors Table
**Effort**: 8-10 hours | **Value**: High

**Schema**:
```sql
CREATE TABLE nba_orchestration.service_errors (
  error_id STRING NOT NULL,
  service_name STRING NOT NULL,
  error_timestamp TIMESTAMP NOT NULL,
  error_type STRING NOT NULL,
  error_category STRING NOT NULL,  -- 'transient', 'permanent', 'resource', 'dependency'
  severity STRING NOT NULL,         -- 'critical', 'high', 'medium', 'low'
  error_message STRING NOT NULL,
  stack_trace STRING,
  game_date DATE,
  processor_name STRING,
  correlation_id STRING,
  recovery_attempted BOOLEAN,
  recovery_successful BOOLEAN
)
PARTITION BY DATE(error_timestamp)
CLUSTER BY service_name, error_category, severity;
```

**Implementation**:
1. Create `shared/utils/service_error_logger.py` utility class
2. Integrate into AnalyticsProcessorBase and other base classes
3. Add to Cloud Functions exception handlers

---

## Priority 2: Medium-term Improvements

### P2-1: Cloud Monitoring Alerts for Stale Phases
**Effort**: 2 hours | **Value**: Medium

Create alerts that fire when:
- No phase_execution_log entries for >2 hours during expected processing window
- Orchestrator service returning 5xx errors
- Pub/Sub subscription has >100 unacked messages

### P2-2: Service Deployment Validation
**Effort**: 3 hours | **Value**: Medium

Create pre-deployment check:
```bash
# bin/validation/validate_cloud_function_imports.py
# Validates all imports can be resolved before deployment
```

### P2-3: Update Deployment Commands Doc
**Effort**: 1 hour | **Value**: Low

Update DEPLOYMENT-COMMANDS.md to include orchestrator deployments.

---

## Quick Reference: What Each Improvement Catches

| Issue Type | P0-1 Fix | P1-1 Gaps | P1-2 Health | P1-3 Errors |
|------------|----------|-----------|-------------|-------------|
| Module import errors | ✅ | | | ✅ |
| Stalled orchestrator | | ✅ | ✅ | |
| Phase transition delays | | ✅ | | |
| Processor failures | | | ✅ | ✅ |
| Silent exceptions | | | | ✅ |
| Missing predictions | | ✅ | ✅ | |

---

## Session Checklist

### For Next Session (Priority 0)
- [ ] Fix imports in 7 orchestration files
- [ ] Copy gcp_config.py if needed
- [ ] Redeploy phase3-to-phase4-orchestrator
- [ ] Redeploy phase4-to-phase5-orchestrator
- [ ] Backfill Phase 4 for Jan 26, 27
- [ ] Verify predictions generated

### For This Week (Priority 1)
- [ ] Add Phase 0.5 checks to /validate-daily skill
- [ ] Create/enhance pipeline_health_summary view
- [ ] Set up scheduled query for health view
- [ ] Create service_errors table schema
- [ ] Implement ServiceErrorLogger utility

### Future (Priority 2)
- [ ] Cloud Monitoring alerts
- [ ] Import validation script
- [ ] Documentation updates

---

## Estimated Total Effort

| Priority | Items | Total Hours |
|----------|-------|-------------|
| P0 | 2 | 3-4 hours |
| P1 | 3 | 15-20 hours |
| P2 | 3 | 6 hours |
| **Total** | **8** | **24-30 hours** |

---

## Files Modified/Created

**To Fix (P0)**:
- `orchestration/shared/utils/bigquery_utils.py`
- `orchestration/shared/utils/bigquery_utils_v2.py`
- `orchestration/shared/utils/odds_preference.py`
- `orchestration/shared/utils/odds_player_props_preference.py`
- `orchestration/shared/utils/processor_alerting.py`
- `orchestration/shared/utils/data_freshness_checker.py`
- `orchestration/shared/utils/phase_execution_logger.py`

**To Create (P1)**:
- `shared/utils/service_error_logger.py`
- `monitoring/bigquery_views/phase_processor_health_summary.sql`
- Updates to `.claude/skills/validate-daily/SKILL.md`

**Schema Changes (P1)**:
- `nba_orchestration.service_errors` table
- `nba_monitoring.phase_processor_health_summary` view
