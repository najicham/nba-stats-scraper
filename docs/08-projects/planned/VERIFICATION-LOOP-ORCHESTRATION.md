# Project: Verification Loop for Daily Orchestration

**Status**: PLANNED (Not Started)
**Priority**: P2 - Medium (After root causes fixed)
**Estimated Effort**: 2-3 days implementation
**Prerequisites**: Fix current P0 issues first (Phase 4 SQLAlchemy, Phase 3 stale deps, betting timing)

---

## Executive Summary

Implement an automated verification loop that monitors daily orchestration health and takes corrective action for transient failures. This reduces manual intervention and enables self-healing for recoverable issues while still surfacing systemic problems for human investigation.

**Key Principle**: The verification loop handles transient failures, NOT broken code. Root causes must be fixed first.

---

## Problem Statement

### Current State

The daily orchestration pipeline requires manual intervention when issues occur:

```
Issue Detected → Human Reads Alert → Human Investigates → Human Triggers Fix → Human Verifies
```

**Typical Timeline**: 1-3 hours from detection to resolution

**Impact**:
- Delays predictions for users
- Requires human availability (problematic for overnight/weekend issues)
- Same manual steps repeated for similar issues

### Examples of Manual Intervention Required

| Date | Issue | Manual Action | Time to Resolve |
|------|-------|---------------|-----------------|
| 2026-01-26 | Phase 3 stalled | Manual trigger via gcloud | 2+ hours |
| 2026-01-26 | 0 predictions | Manual pipeline recovery | 3+ hours |
| 2026-01-25 | PBP games missing | Manual retry with delays | 1+ hours |

---

## Vision

### Target State

An automated verification loop that:

1. **Detects** issues through existing validation
2. **Diagnoses** the type of failure (transient vs systemic)
3. **Remediates** transient failures automatically
4. **Escalates** systemic issues to humans
5. **Verifies** that remediation worked

```
┌─────────────────────────────────────────────────────────────────┐
│                    VERIFICATION LOOP                             │
│                                                                  │
│   ┌────────┐    ┌──────────┐    ┌────────────┐                  │
│   │ CHECK  │───▶│ HEALTHY? │─Y─▶│   DONE     │                  │
│   └────────┘    └──────────┘    └────────────┘                  │
│                      │ N                                         │
│                      ▼                                           │
│               ┌─────────────┐                                    │
│               │  DIAGNOSE   │                                    │
│               └─────────────┘                                    │
│                 │         │                                      │
│            Transient   Systemic                                  │
│                 │         │                                      │
│                 ▼         ▼                                      │
│           ┌────────┐  ┌──────────┐                              │
│           │  FIX   │  │ ESCALATE │                              │
│           └────────┘  └──────────┘                              │
│                 │                                                │
│                 ▼                                                │
│           ┌────────┐                                            │
│           │  WAIT  │                                            │
│           └────────┘                                            │
│                 │                                                │
│                 └──────────────────────────────────┐            │
│                                        (loop back to CHECK)      │
└─────────────────────────────────────────────────────────────────┘
```

### Expected Outcome

**Typical Timeline with Verification Loop**: 10-30 minutes from detection to resolution (for transient issues)

**Impact**:
- Faster recovery from transient failures
- No human intervention needed for recoverable issues
- Works overnight and weekends
- Humans focus on systemic issues, not repetitive fixes

---

## Scope

### In Scope (Auto-Remediate)

These are **transient failures** that the verification loop should handle:

| Issue Type | Detection | Auto-Remediation |
|------------|-----------|------------------|
| Phase 3 not triggered | Firestore shows <5/5 complete | `gcloud scheduler jobs run same-day-phase3` |
| Phase 4 not triggered | ML features = 0 after Phase 3 done | `gcloud scheduler jobs run same-day-phase4` |
| Phase 5 not triggered | Predictions = 0 after Phase 4 done | `gcloud scheduler jobs run same-day-predictions` |
| Betting data delayed | 0 records 2h after window start | Trigger betting scraper manually |
| API rate limit | Scraper failed with 429 | Wait 15 min, retry |
| Cloud Run cold start | Service timeout on first call | Retry with backoff |
| Network blip | Transient connection error | Retry with backoff |

### Out of Scope (Escalate to Humans)

These are **systemic failures** that should NOT be auto-remediated:

| Issue Type | Why Not Auto-Remediate |
|------------|------------------------|
| Missing dependency (SQLAlchemy) | Code/deployment bug - needs fix |
| Stale dependency false positives | Logic bug - needs investigation |
| Configuration errors | Human error - needs review |
| API credentials expired | Needs manual credential rotation |
| IP banned | Needs proxy/infrastructure change |
| Data corruption | Needs investigation before action |
| Repeated failures (>3 attempts) | Indicates systemic issue |

---

## Prerequisites

**This project should NOT start until these are complete:**

### P0 Prerequisites (Must Fix First)

- [ ] Phase 4 SQLAlchemy dependency resolved
- [ ] Phase 3 stale dependency logic fixed
- [ ] Betting timing fix deployed (6h → 12h window)
- [ ] System stable for 1+ week with no manual intervention needed

### P1 Prerequisites (Should Complete)

- [ ] Source-block tracking system operational
- [ ] Spot check data regeneration complete
- [ ] Validation script timing-awareness implemented

### Why Wait?

If implemented before prerequisites:
- Loop would mask the SQLAlchemy bug (keeps restarting broken service)
- Loop would hide stale dependency false positives (keeps retrying)
- Can't distinguish transient vs systemic failures
- Creates false sense of stability

---

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Verification Loop Service                     │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │  Health Checker  │  │    Diagnoser     │  │  Remediator   │ │
│  │                  │  │                  │  │               │ │
│  │ - Phase 2 check  │  │ - Classify error │  │ - Trigger     │ │
│  │ - Phase 3 check  │  │ - Check history  │  │   schedulers  │ │
│  │ - Phase 4 check  │  │ - Determine if   │  │ - Retry       │ │
│  │ - Phase 5 check  │  │   transient      │  │   scrapers    │ │
│  │ - Scraper check  │  │                  │  │ - Wait/backoff│ │
│  └──────────────────┘  └──────────────────┘  └───────────────┘ │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │    Escalator     │  │   State Manager  │  │    Logger     │ │
│  │                  │  │                  │  │               │ │
│  │ - Alert humans   │  │ - Track attempts │  │ - Audit trail │ │
│  │ - PagerDuty/Slack│  │ - Cooldown timers│  │ - Metrics     │ │
│  │ - Incident create│  │ - Circuit breaker│  │ - BigQuery log│ │
│  └──────────────────┘  └──────────────────┘  └───────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. Health Checker

Reuses existing validation logic:

```python
class HealthChecker:
    def check_pipeline_health(self, target_date: date) -> PipelineHealth:
        """Run all health checks and return structured results."""
        return PipelineHealth(
            betting_data=self._check_betting_data(target_date),
            phase3_complete=self._check_phase3_completion(target_date),
            phase4_complete=self._check_phase4_completion(target_date),
            predictions_generated=self._check_predictions(target_date),
            scraper_health=self._check_scraper_health(),
        )
```

#### 2. Diagnoser

Classifies failures as transient or systemic:

```python
class Diagnoser:
    def diagnose(self, health: PipelineHealth, history: AttemptHistory) -> Diagnosis:
        """Determine if failure is transient (auto-fix) or systemic (escalate)."""

        # Check attempt history
        if history.consecutive_failures > MAX_ATTEMPTS:
            return Diagnosis(type="SYSTEMIC", reason="Max attempts exceeded")

        # Check for known systemic patterns
        if self._is_known_systemic_error(health.error_details):
            return Diagnosis(type="SYSTEMIC", reason=health.error_details)

        # Check timing (is it too early to expect data?)
        if self._is_within_expected_lag(health):
            return Diagnosis(type="WAIT", reason="Within expected processing lag")

        # Default: assume transient, try to fix
        return Diagnosis(type="TRANSIENT", actions=self._determine_actions(health))
```

#### 3. Remediator

Takes corrective action:

```python
class Remediator:
    def remediate(self, diagnosis: Diagnosis) -> RemediationResult:
        """Execute remediation actions."""
        results = []

        for action in diagnosis.actions:
            if action.type == "TRIGGER_PHASE3":
                result = self._trigger_scheduler("same-day-phase3")
            elif action.type == "TRIGGER_PHASE4":
                result = self._trigger_scheduler("same-day-phase4")
            elif action.type == "TRIGGER_PREDICTIONS":
                result = self._trigger_scheduler("same-day-predictions")
            elif action.type == "RETRY_SCRAPER":
                result = self._retry_scraper(action.scraper_name)
            elif action.type == "WAIT":
                result = self._wait(action.wait_minutes)

            results.append(result)

        return RemediationResult(actions=results)
```

#### 4. State Manager

Tracks attempts and prevents infinite loops:

```python
class StateManager:
    def __init__(self):
        self.attempt_history = {}  # Firestore-backed
        self.circuit_breakers = {}

    def record_attempt(self, target_date: date, action: str, success: bool):
        """Record remediation attempt for tracking."""
        key = f"{target_date}:{action}"
        if key not in self.attempt_history:
            self.attempt_history[key] = AttemptHistory()

        self.attempt_history[key].add_attempt(success)

    def is_circuit_open(self, action: str) -> bool:
        """Check if circuit breaker is open (too many failures)."""
        return self.circuit_breakers.get(action, False)
```

#### 5. Escalator

Alerts humans when needed:

```python
class Escalator:
    def escalate(self, diagnosis: Diagnosis, health: PipelineHealth):
        """Escalate systemic issue to humans."""

        alert = Alert(
            severity="HIGH" if health.predictions_generated == 0 else "MEDIUM",
            title=f"Pipeline Issue Requires Human Intervention",
            message=f"Verification loop cannot auto-fix: {diagnosis.reason}",
            details={
                "health": health.to_dict(),
                "attempts": diagnosis.attempt_count,
                "recommendation": diagnosis.human_action,
            }
        )

        self._send_slack_alert(alert)

        if alert.severity == "HIGH":
            self._send_pagerduty_alert(alert)
```

### Main Loop

```python
def verification_loop(
    target_date: date,
    max_attempts: int = 3,
    check_interval_minutes: int = 10,
    max_duration_hours: int = 4
):
    """
    Main verification loop for daily orchestration.

    Runs until either:
    - Pipeline is healthy
    - Max attempts exceeded (escalate)
    - Max duration exceeded (escalate)
    """
    checker = HealthChecker()
    diagnoser = Diagnoser()
    remediator = Remediator()
    state = StateManager()
    escalator = Escalator()

    start_time = datetime.now()

    while True:
        # Check duration limit
        if (datetime.now() - start_time).hours > max_duration_hours:
            escalator.escalate(
                Diagnosis(type="TIMEOUT", reason="Max duration exceeded"),
                checker.check_pipeline_health(target_date)
            )
            return False

        # 1. CHECK
        health = checker.check_pipeline_health(target_date)

        # 2. HEALTHY?
        if health.is_fully_healthy():
            log.info(f"✅ Pipeline healthy for {target_date}")
            return True

        # 3. DIAGNOSE
        history = state.get_attempt_history(target_date)
        diagnosis = diagnoser.diagnose(health, history)

        # 4. SYSTEMIC? → ESCALATE
        if diagnosis.type == "SYSTEMIC":
            escalator.escalate(diagnosis, health)
            return False

        # 5. WAIT? → Just wait
        if diagnosis.type == "WAIT":
            log.info(f"⏳ {diagnosis.reason} - checking again in {check_interval_minutes}m")
            time.sleep(check_interval_minutes * 60)
            continue

        # 6. TRANSIENT → FIX
        log.info(f"🔧 Attempting remediation: {diagnosis.actions}")
        result = remediator.remediate(diagnosis)

        # Record attempt
        state.record_attempt(target_date, diagnosis.actions, result.success)

        # 7. WAIT for fix to take effect
        log.info(f"⏳ Waiting {check_interval_minutes}m for remediation to take effect...")
        time.sleep(check_interval_minutes * 60)
```

---

## Scheduling

### When to Run

```yaml
# Cloud Scheduler configuration
verification_loop:
  # Morning run: Verify overnight processing completed
  morning_check:
    schedule: "0 8 * * *"  # 8 AM ET daily
    target_date: "today"
    max_attempts: 3

  # Pre-game run: Verify predictions ready before games
  pre_game_check:
    schedule: "0 17 * * *"  # 5 PM ET daily
    target_date: "today"
    max_attempts: 5  # More attempts closer to game time

  # Post-game run: Verify game data collected
  post_game_check:
    schedule: "0 2 * * *"  # 2 AM ET daily
    target_date: "yesterday"
    max_attempts: 3
```

### Integration with Existing Orchestration

```
┌─────────────────────────────────────────────────────────────────┐
│                    Daily Timeline                                │
│                                                                  │
│  6 AM   Morning Ops (schedule scraper)                          │
│    │                                                             │
│  7 AM   Betting workflow starts (12h before 7 PM games)         │
│    │                                                             │
│  8 AM   ► VERIFICATION LOOP (morning check)                     │
│    │      - Verify overnight processing complete                 │
│    │      - Auto-fix if Phase 3/4 stalled                       │
│    │                                                             │
│  9 AM   Phase 3 analytics (should be done by now)               │
│    │                                                             │
│ 10 AM   Phase 4 precompute (should be done by now)              │
│    │                                                             │
│ 11 AM   Predictions available                                   │
│    │                                                             │
│  5 PM   ► VERIFICATION LOOP (pre-game check)                    │
│    │      - Verify predictions ready                             │
│    │      - Last chance auto-fix before games                    │
│    │                                                             │
│  7 PM   Games start                                              │
│    │                                                             │
│ 11 PM   Games end                                                │
│    │                                                             │
│  2 AM   ► VERIFICATION LOOP (post-game check)                   │
│    │      - Verify game data collected                           │
│    │      - Trigger retries for missing data                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Metrics & Monitoring

### Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Auto-remediation success rate | >80% | Transient issues fixed without human |
| Time to recovery (transient) | <30 min | From detection to healthy |
| False escalation rate | <10% | Escalated but was actually transient |
| Missed systemic issues | 0% | Auto-fixed but was actually systemic |

### Dashboard Queries

```sql
-- Verification loop outcomes by day
SELECT
  DATE(started_at) as date,
  outcome,  -- SUCCESS, ESCALATED, TIMEOUT
  COUNT(*) as count,
  AVG(duration_minutes) as avg_duration,
  AVG(attempt_count) as avg_attempts
FROM nba_orchestration.verification_loop_runs
WHERE started_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY date, outcome
ORDER BY date DESC;

-- Most common auto-remediation actions
SELECT
  action_type,
  COUNT(*) as total,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as succeeded,
  ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
FROM nba_orchestration.verification_loop_actions
WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY action_type
ORDER BY total DESC;
```

---

## Rollout Plan

### Phase 1: Dry Run Mode (Week 1)

- Run verification loop in "observe only" mode
- Log what actions WOULD be taken
- Don't actually remediate
- Validate diagnosis logic

### Phase 2: Limited Remediation (Week 2-3)

- Enable auto-remediation for low-risk actions only:
  - Trigger Phase 3/4/5 schedulers
  - Wait and retry
- Keep high-risk actions in escalate-only mode
- Monitor closely

### Phase 3: Full Remediation (Week 4+)

- Enable all transient failure remediations
- Tune thresholds based on learnings
- Reduce monitoring frequency

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Infinite loop | Low | High | Max attempts + duration limits |
| Masks systemic issue | Medium | High | Strict transient vs systemic classification |
| Makes debugging harder | Medium | Medium | Comprehensive audit logging |
| Increases API costs | Low | Low | Rate limiting, cooldowns |
| Alert fatigue | Medium | Medium | Smart escalation thresholds |

---

## Success Criteria for Project Completion

- [ ] Verification loop deployed to production
- [ ] 3 scheduled runs per day (morning, pre-game, post-game)
- [ ] >80% of transient failures auto-remediated
- [ ] <10% false escalation rate
- [ ] Audit logging to BigQuery working
- [ ] Dashboard created for monitoring
- [ ] Runbook updated with verification loop operations
- [ ] 2 weeks of stable operation

---

## Timeline

**Prerequisites**: 1-2 weeks (fix current P0 issues, stabilize)

**Implementation**:
- Week 1: Core components (Health Checker, Diagnoser, Remediator)
- Week 2: State management, escalation, logging
- Week 3: Scheduling, integration, dry run mode
- Week 4: Limited remediation rollout
- Week 5+: Full rollout and tuning

**Total**: ~5-6 weeks from prerequisites complete

---

## References

- Current validation: `scripts/validate_tonight_data.py`
- Health check: `bin/monitoring/daily_health_check.sh`
- Manual recovery steps: `docs/sessions/2026-01-26-COMPREHENSIVE-ACTION-PLAN.md`
- Session 33 findings: `docs/09-handoff/2026-01-26-SESSION-33-ORCHESTRATION-VALIDATION-CRITICAL-FINDINGS.md`

---

**Document Created**: 2026-01-26
**Author**: Planning Session
**Status**: PLANNED - Waiting for prerequisites
