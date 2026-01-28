# Phase 0.5 (Orchestrator Health) - Investigation Findings

**Investigated**: 2026-01-28
**Status**: Ready for Implementation
**Priority**: P1 (Critical) - Prevents 2+ day silent failures

---

## Key Finding: Infrastructure Exists, Just Need Integration

The `phase_execution_log` table exists and is well-designed. Firestore tracks completion state. Just need to add checks to `/validate-daily` skill.

---

## 1. Schema of `nba_orchestration.phase_execution_log`

```sql
CREATE TABLE phase_execution_log (
  execution_timestamp TIMESTAMP NOT NULL,
  phase_name STRING NOT NULL,          -- 'phase2_to_phase3', 'phase3_to_phase4', 'phase4_to_phase5'
  game_date DATE NOT NULL,
  correlation_id STRING,
  start_time TIMESTAMP NOT NULL,
  duration_seconds FLOAT64 NOT NULL,
  games_processed INT64,
  status STRING NOT NULL,              -- 'complete', 'partial', 'deadline_exceeded'
  metadata JSON,                       -- completed_processors, missing_processors, trigger_reason
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY phase_name, status, execution_timestamp
```

**Retention**: 90 days

---

## 2. Other State Tracking

**Firestore Collections:**
- `phase2_completion/{game_date}` - 6 expected processors
- `phase3_completion/{game_date}` - 5 expected processors
- `phase4_completion/{game_date}` - Phase 4 processors

**Document Structure:**
```javascript
{
  "processor_name": {
    "completed_at": Timestamp,
    "status": "success",
    "record_count": 450
  },
  "_triggered": true,
  "_triggered_at": Timestamp,
  "_trigger_reason": "all_complete"
}
```

---

## 3. Expected Timing for Phase Transitions

| Transition | Timeout | Typical Duration |
|------------|---------|------------------|
| Phase 2 → 3 | 30 min | 5-10 min |
| Phase 3 → 4 | Mode-dependent | 10-20 min (overnight) |
| Phase 4 → 5 | 60 min | 15-30 min |

**Detection Thresholds:**
- Stalled: >30 min in 'started' or 'running'
- Timing gaps: >60 min between phase completions

---

## 4. Cloud Logging Export

**Status**: NOT CONFIGURED

**Alternative**: Use `gcloud logging read` command:
```bash
gcloud logging read \
  "resource.type=cloud_function AND resource.labels.function_name:phase3_to_phase4 AND severity=ERROR" \
  --limit=50 --format=json
```

---

## 5. Slack Webhooks

| Channel | Env Var | Purpose |
|---------|---------|---------|
| #daily-orchestration | `SLACK_WEBHOOK_URL` | Primary alerts |
| #app-error-alerts | `SLACK_WEBHOOK_URL_ERROR` | Critical errors |
| #nba-alerts | `SLACK_WEBHOOK_URL_WARNING` | Warnings |

**Recommendation**: Use `SLACK_WEBHOOK_URL_ERROR` for Phase 0.5 critical failures.

---

## 6. Integration with /validate-daily

**Current Structure:**
- Phase 0: Quota check
- Phase 1: Baseline health
- Phase 2: Main validation
- Phase 3: Spot checks
- Phase 3B: Player coverage
- Phase 4: Phase completion
- Phase 5: Investigation tools

**Insert Phase 0.5 after Phase 0**, before Phase 1.

---

## 7. Ready-to-Use SQL Queries

**Check 1: Missing phase logs**
```sql
WITH expected AS (
  SELECT 'phase2_to_phase3' as phase_name UNION ALL
  SELECT 'phase3_to_phase4' UNION ALL
  SELECT 'phase4_to_phase5'
),
actual AS (
  SELECT DISTINCT phase_name
  FROM nba_orchestration.phase_execution_log
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT e.phase_name,
  CASE WHEN a.phase_name IS NULL THEN 'MISSING' ELSE 'OK' END as status
FROM expected e LEFT JOIN actual a USING (phase_name);
```

**Check 2: Stalled orchestrators**
```sql
SELECT phase_name, game_date, start_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) as minutes_stalled
FROM nba_orchestration.phase_execution_log
WHERE status IN ('started', 'running')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) > 30;
```

**Check 3: Phase timing gaps**
```sql
WITH phase_times AS (
  SELECT game_date, phase_name, MAX(execution_timestamp) as completed_at
  FROM nba_orchestration.phase_execution_log
  WHERE status = 'complete'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date, phase_name
)
SELECT p1.game_date, p1.phase_name, p2.phase_name,
  TIMESTAMP_DIFF(p2.completed_at, p1.completed_at, MINUTE) as gap_minutes
FROM phase_times p1
JOIN phase_times p2 ON p1.game_date = p2.game_date
WHERE (p1.phase_name = 'phase2_to_phase3' AND p2.phase_name = 'phase3_to_phase4')
   OR (p1.phase_name = 'phase3_to_phase4' AND p2.phase_name = 'phase4_to_phase5')
HAVING gap_minutes > 60;
```

---

## Summary

| Component | Status |
|-----------|--------|
| phase_execution_log table | ✅ Exists, well-designed |
| Firestore completion tracking | ✅ Exists |
| Expected timing documented | ✅ 30/60 min thresholds |
| Cloud Logging export | ❌ Not configured (use gcloud) |
| Slack webhooks | ✅ Multiple available |
| /validate-daily skill | ✅ Ready for Phase 0.5 insertion |

**Estimated implementation**: 3-4 hours
