# Daily Orchestration Analysis - December 29, 2025

**Analysis Date:** December 29, 2025
**Session:** 180+
**Status:** Analysis Complete - Recommendations Provided

---

## 1. Current State Assessment

### 1.1 Today's Pipeline Status (Dec 29, 2025)

| Phase | Status | Records | Issue |
|-------|--------|---------|-------|
| **Phase 1** (Scrapers) | Nominal | N/A | Working - schedule data collected |
| **Phase 2** (Raw Processors) | Nominal | Working | ESPN roster fix deployed (storage import) |
| **Phase 3** (Analytics) | **Working** | 352 records | Data flowing correctly |
| **Phase 4** (Precompute) | **STUCK** | 0 records | Not triggered despite Phase 3 data |
| **Phase 5** (Predictions) | **BLOCKED** | 0 predictions | Waiting on Phase 4 |
| **Phase 6** (Export) | N/A | - | Nothing to export |

**11 NBA games scheduled tonight** - predictions need to be generated urgently.

### 1.2 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Pipeline Flow                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 1        Phase 2           Phase 3           Phase 4        Phase 5  │
│  ┌─────────┐    ┌─────────┐       ┌─────────┐       ┌─────────┐   ┌─────────┐
│  │ Scrapers │──▶│  Raw    │──▶    │Analytics│       │Precompute│──▶│Predictions│
│  │         │    │Processors│      │         │       │         │   │         │
│  └─────────┘    └─────────┘       └─────────┘       └─────────┘   └─────────┘
│       │              │                  │                │              │
│       │         [nba-phase2-       [nba-phase3-    [nba-phase4-        │
│       │          raw-complete]      analytics-       trigger]          │
│       │              │              complete]            │              │
│       ▼              ▼                  │                ▼              │
│  Pub/Sub ──────▶ Pub/Sub ──────────────┼───────▶ Pub/Sub ──────▶ Pub/Sub
│                                        │                               │
│                                        ▼                               │
│                              ┌─────────────────┐                       │
│                              │ Phase 3→4       │                       │
│                              │ Orchestrator    │◀────── THE GAP        │
│                              │ (Firestore)     │                       │
│                              └─────────────────┘                       │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Key Services & Their Roles

| Service | Role | Trigger Method |
|---------|------|----------------|
| `nba-phase3-analytics-processors` | Runs 5 analytics processors | Direct Pub/Sub subscription |
| `phase3-to-phase4-orchestrator` | Tracks Phase 3 completion, triggers Phase 4 | Pub/Sub (`nba-phase3-analytics-complete`) |
| `nba-phase4-precompute-processors` | Runs 5 precompute processors | Pub/Sub (`nba-phase4-trigger`) + Schedulers |
| `prediction-coordinator` | Orchestrates prediction generation | HTTP + Pub/Sub |
| `self-heal-check` | Auto-recovery at 2:15 PM ET | Cloud Scheduler |

---

## 2. Root Cause Analysis for Today's Issues

### 2.1 Primary Issue: Phase 4 Not Triggered

**Observation:**
- Phase 3 has 352 records for Dec 29
- Phase 4 has 0 records
- Phase 3 to Phase 4 orchestrator should have triggered Phase 4

**Potential Causes (ranked by likelihood):**

#### Cause A: Phase 3 Processors Not Publishing Completion Messages (HIGH PROBABILITY)

The Phase 3→4 orchestrator listens to `nba-phase3-analytics-complete` topic. It expects **5 processors** to publish completion messages:

```python
# From orchestrators.md - Expected Phase 3 Processors:
EXPECTED_PROCESSORS = [
    'player_game_summary',
    'team_defense_game_summary',
    'team_offense_game_summary',
    'upcoming_player_game_context',
    'upcoming_team_game_context',
]
```

If any processor:
1. Fails before publishing completion
2. Has `skip_downstream_trigger=True`
3. Has a Pub/Sub publishing error

Then the orchestrator never sees 5/5 completions and never triggers Phase 4.

**Diagnostic Check:**
```bash
# Check Firestore for today's Phase 3 completion state
gcloud firestore documents get phase3_completion/2025-12-29
```

#### Cause B: Same-Day Scheduler Issue (MEDIUM PROBABILITY)

The same-day schedulers run at:
- 10:30 AM ET: `same-day-phase3`
- 11:00 AM ET: `same-day-phase4`
- 11:30 AM ET: `same-day-predictions`

If `same-day-phase4` failed or didn't run, Phase 4 wouldn't have data.

**Diagnostic Check:**
```bash
gcloud scheduler jobs describe same-day-phase4 --location=us-west2 --format="value(state,lastAttemptTime,status)"
```

#### Cause C: ESPN Roster Fix Side Effect (LOW PROBABILITY)

The `storage` import fix for ESPN roster processor was just deployed. While this fix was necessary, the redeployment may have:
- Restarted services mid-processing
- Caused transient failures during deployment

### 2.2 Secondary Issue: Self-Heal at 2:15 PM Should Have Caught This

The `self-heal-check` Cloud Function runs at 2:15 PM ET daily. For today:
- It should have detected 0 predictions for tomorrow (Dec 30)
- It should have triggered the pipeline bypass

**Possible reasons self-heal didn't help:**
1. It checks for **tomorrow's** predictions, not today's
2. If there were no games tomorrow, it would have exited early
3. The self-heal function may not have run yet (depends on timezone)

---

## 3. Improvement Recommendations

### 3.1 Priority Matrix

| Priority | Impact | Effort | Recommendation |
|----------|--------|--------|----------------|
| **P0** | Critical | Low | Immediate fix for today |
| **P1** | High | Medium | Better visibility and monitoring |
| **P2** | High | High | Auto-healing improvements |
| **P3** | Medium | Medium | Robustness improvements |

---

### Priority 0: Immediate Fix for Today (Do Now)

**Action: Manually trigger Phase 4 and predictions**

```bash
# Option 1: Use existing scheduler triggers
gcloud scheduler jobs run same-day-phase4 --location=us-west2
sleep 120
gcloud scheduler jobs run same-day-predictions --location=us-west2

# Option 2: Direct HTTP trigger with bypass flags
TOKEN=$(gcloud auth print-identity-token)

# Trigger Phase 4 with skip_dependency_check
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2025-12-29",
    "processors": ["MLFeatureStoreProcessor"],
    "strict_mode": false,
    "skip_dependency_check": true
  }'

# Wait 2 minutes, then trigger predictions
sleep 120
curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-29"}'

# Option 3: Use force_predictions.sh script
./bin/pipeline/force_predictions.sh 2025-12-29
```

---

### Priority 1: Better Visibility and Monitoring (1-2 Days)

#### 1.1 Create Phase Completion Dashboard Query

Create a single BigQuery view that shows phase completion status:

```sql
-- Create or replace view: nba_orchestration.daily_phase_status
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.daily_phase_status` AS
WITH schedule AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games_scheduled
  FROM `nba_raw.nbac_schedule`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase2 AS (
  SELECT DATE(processed_at) as game_date, COUNT(DISTINCT game_id) as phase2_games
  FROM `nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1
),
phase3 AS (
  SELECT game_date, COUNT(*) as phase3_records
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase4 AS (
  SELECT game_date, COUNT(*) as phase4_records, ROUND(AVG(feature_quality_score), 1) as avg_quality
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase5 AS (
  SELECT game_date, COUNT(*) as predictions
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND is_active = TRUE
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.games_scheduled,
  COALESCE(p2.phase2_games, 0) as phase2_games,
  COALESCE(p3.phase3_records, 0) as phase3_records,
  COALESCE(p4.phase4_records, 0) as phase4_records,
  p4.avg_quality,
  COALESCE(p5.predictions, 0) as predictions,
  CASE
    WHEN COALESCE(p5.predictions, 0) > 0 THEN 'COMPLETE'
    WHEN COALESCE(p4.phase4_records, 0) > 0 THEN 'PHASE_5_PENDING'
    WHEN COALESCE(p3.phase3_records, 0) > 0 THEN 'PHASE_4_STUCK'
    WHEN COALESCE(p2.phase2_games, 0) > 0 THEN 'PHASE_3_PENDING'
    WHEN s.games_scheduled > 0 THEN 'PHASE_2_PENDING'
    ELSE 'NO_GAMES'
  END as pipeline_status
FROM schedule s
LEFT JOIN phase2 p2 ON s.game_date = p2.game_date
LEFT JOIN phase3 p3 ON s.game_date = p3.game_date
LEFT JOIN phase4 p4 ON s.game_date = p4.game_date
LEFT JOIN phase5 p5 ON s.game_date = p5.game_date
ORDER BY s.game_date DESC;
```

**Effort:** 2-3 hours

#### 1.2 Morning Health Check Script Enhancement

Create an enhanced daily health script:

```bash
# bin/pipeline/morning_health_check.sh
```

Should check:
1. Games scheduled today vs predictions generated
2. Firestore phase completion states
3. Pub/Sub message backlogs
4. Recent errors in Cloud Logging
5. Service health endpoints

**Effort:** 4-6 hours

#### 1.3 Firestore State Query Tool

Create a simple CLI tool to check orchestration state:

```bash
# bin/monitoring/check_orchestration_state.sh DATE
# Example: ./bin/monitoring/check_orchestration_state.sh 2025-12-29
```

Output:
```
Phase 3 Completion for 2025-12-29:
  - player_game_summary: COMPLETE (12:05 PM)
  - team_defense_game_summary: COMPLETE (12:06 PM)
  - team_offense_game_summary: COMPLETE (12:06 PM)
  - upcoming_player_game_context: COMPLETE (12:08 PM)
  - upcoming_team_game_context: MISSING
  _triggered: FALSE (waiting for 5/5)
```

**Effort:** 2-3 hours

---

### Priority 2: Auto-Healing Improvements (1 Week)

#### 2.1 Enhanced Self-Heal Function

Current self-heal only checks **tomorrow's** predictions. Enhance to also check:
- **Today's** predictions (if games today)
- Phase completion states in Firestore
- Alert if Phase 3 complete but Phase 4 not triggered

```python
# orchestration/cloud_functions/self_heal/main.py enhancements

def check_phase_completion_state(bq_client, target_date):
    """Check Firestore for phase completion state."""
    db = firestore.Client()

    # Check Phase 3 completion
    p3_doc = db.collection('phase3_completion').document(target_date).get()
    if p3_doc.exists:
        p3_data = p3_doc.to_dict()
        completed = [k for k in p3_data if not k.startswith('_')]
        triggered = p3_data.get('_triggered', False)

        if len(completed) == 5 and not triggered:
            # All processors complete but not triggered - orchestrator issue!
            return 'ORCHESTRATOR_STUCK'
        elif len(completed) < 5:
            return f'PHASE3_INCOMPLETE ({len(completed)}/5)'

    return 'HEALTHY'
```

**Effort:** 6-8 hours

#### 2.2 Circuit Breaker Pattern

Add circuit breaker to prevent cascade failures:

```python
# shared/utils/circuit_breaker.py

class CircuitBreaker:
    """
    Circuit breaker for service calls.

    States:
    - CLOSED: Normal operation, calls allowed
    - OPEN: Too many failures, calls blocked
    - HALF_OPEN: Testing if service recovered
    """

    def __init__(self, failure_threshold=5, reset_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = 'CLOSED'
        self.last_failure_time = None
```

**Effort:** 8-10 hours

#### 2.3 Retry with Exponential Backoff

Add standardized retry mechanism:

```python
# shared/utils/retry.py

def retry_with_backoff(func, max_retries=3, base_delay=1):
    """Retry function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt+1} failed, retrying in {delay}s: {e}")
            time.sleep(delay)
```

**Effort:** 4-6 hours

---

### Priority 3: Robustness Improvements (2-4 Weeks)

#### 3.1 Dependency Validation Before Processing

Add pre-flight checks before each phase:

```python
# shared/utils/dependency_validator.py

class DependencyValidator:
    """Validate upstream data exists before processing."""

    def validate_phase4_dependencies(self, game_date):
        """Check Phase 3 tables have data before running Phase 4."""
        required_tables = [
            ('nba_analytics.player_game_summary', 100),  # min 100 rows
            ('nba_analytics.team_defense_game_summary', 30),
            ('nba_analytics.upcoming_player_game_context', 50),
        ]

        missing = []
        for table, min_rows in required_tables:
            count = self._count_rows(table, game_date)
            if count < min_rows:
                missing.append((table, count, min_rows))

        return missing
```

**Effort:** 8-10 hours

#### 3.2 Phase 3→4 Orchestrator Timeout

Add timeout-based fallback trigger:

```python
# In phase3_to_phase4 orchestrator

# If 3/5 processors complete within 30 min but 2 never arrive,
# trigger Phase 4 anyway with partial data
COMPLETION_TIMEOUT_MINUTES = 30
MINIMUM_PROCESSORS_TO_TRIGGER = 3  # Instead of 5

def check_for_timeout_trigger(game_date):
    """Trigger Phase 4 if minimum processors complete and timeout exceeded."""
    doc = db.collection('phase3_completion').document(game_date).get()
    if not doc.exists:
        return False

    data = doc.to_dict()
    completed = [k for k in data if not k.startswith('_')]
    first_completion = min(data[k]['completed_at'] for k in completed)

    elapsed = datetime.now() - first_completion
    if len(completed) >= MINIMUM_PROCESSORS_TO_TRIGGER and elapsed.minutes > COMPLETION_TIMEOUT_MINUTES:
        logger.warning(f"Timeout trigger: {len(completed)}/5 processors, {elapsed} elapsed")
        return True

    return False
```

**Effort:** 6-8 hours

#### 3.3 Processor Execution Log Table

Create unified logging table for all phases:

```sql
CREATE TABLE nba_orchestration.processor_execution_log (
  execution_id STRING NOT NULL,
  processor_name STRING NOT NULL,
  phase STRING NOT NULL,
  triggered_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  status STRING NOT NULL,

  data_date DATE,
  trigger_source STRING,
  pubsub_message_id STRING,
  correlation_id STRING,

  records_processed INT64,
  error_message STRING,

  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(triggered_at)
CLUSTER BY processor_name, status;
```

**Effort:** 8-12 hours (table + processor updates)

---

## 4. Implementation Plan

### Week 1: Emergency Fixes & Quick Wins

| Day | Task | Priority | Owner |
|-----|------|----------|-------|
| Mon (Dec 29) | Manual Phase 4/5 trigger for tonight | P0 | - |
| Mon (Dec 29) | Investigate Firestore state for today | P0 | - |
| Tue | Create daily phase status view | P1 | - |
| Wed | Create orchestration state CLI tool | P1 | - |
| Thu | Morning health check script | P1 | - |
| Fri | Test and document new tools | P1 | - |

### Week 2: Self-Healing Improvements

| Day | Task | Priority |
|-----|------|----------|
| Mon | Enhance self-heal to check today's predictions | P2 |
| Tue | Add Firestore state checking to self-heal | P2 |
| Wed | Add retry with backoff to key services | P2 |
| Thu | Add dependency validation pre-checks | P3 |
| Fri | Testing and documentation | - |

### Week 3-4: Robustness & Circuit Breakers

| Week | Task | Priority |
|------|------|----------|
| Week 3 | Circuit breaker implementation | P2 |
| Week 3 | Phase 3→4 timeout trigger | P3 |
| Week 4 | Processor execution log table | P3 |
| Week 4 | Integration testing | - |

---

## 5. Success Metrics

After implementing these improvements, we should be able to:

### Visibility Metrics
- [ ] Answer "Did today's pipeline complete?" in < 30 seconds
- [ ] See all phase states in a single dashboard query
- [ ] Know exact failure point within 5 minutes of issue

### Reliability Metrics
- [ ] Auto-recover from 80% of Phase stuck issues
- [ ] Reduce manual interventions by 50%
- [ ] Never miss predictions for a game day

### Alert Metrics
- [ ] Alert within 15 minutes if phase stuck
- [ ] Alert if predictions not ready by 2 PM ET on game days
- [ ] Daily summary email of pipeline health

---

## 6. Related Documentation

- `/home/naji/code/nba-stats-scraper/docs/00-orchestration/README.md` - Orchestration overview
- `/home/naji/code/nba-stats-scraper/docs/01-architecture/orchestration/orchestrators.md` - Orchestrator architecture
- `/home/naji/code/nba-stats-scraper/docs/08-projects/current/ORCHESTRATION-IMPROVEMENTS.md` - Existing improvement plan
- `/home/naji/code/nba-stats-scraper/docs/08-projects/current/self-healing-pipeline/README.md` - Self-healing system
- `/home/naji/code/nba-stats-scraper/docs/02-operations/daily-validation-checklist.md` - Daily validation

---

## 7. Immediate Next Steps

1. **Right Now:** Run the manual Phase 4/5 trigger commands from Priority 0
2. **Today:** Check Firestore to understand why Phase 3→4 orchestrator didn't fire
3. **This Week:** Implement Priority 1 visibility improvements
4. **Next Week:** Enhance self-heal function

---

*Analysis created: December 29, 2025*
*Next review: January 5, 2026*
