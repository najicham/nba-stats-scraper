# Event-Driven Orchestration System - Executive Summary

**Created:** December 31, 2025
**Full Design:** `EVENT-DRIVEN-ORCHESTRATION-DESIGN.md`

---

## TL;DR

Replace fixed-scheduler orchestration with event-driven cascades that intelligently check dependencies and adapt behavior based on processing mode (overnight, same-day, tomorrow, manual, backfill).

**Key Innovation:** Mode-aware dependency checking that knows when to be strict (overnight: 100% required) vs lenient (same-day: 80% OK, better than nothing).

---

## Architecture at a Glance

```
Phase 2 Complete → Dependency Check → Phase 3 Trigger
Phase 3 Complete → Dependency Check → Phase 4 Trigger
Phase 4 Complete → Dependency Check → Phase 5 Trigger
Phase 5 Complete → Quality Check → Phase 6 Trigger

+ Fallback: Schedulers (if cascade fails)
+ Safety Net: Self-heal (if schedulers fail)
+ Last Resort: Manual intervention
```

---

## Key Improvements

### 1. Event-Driven Cascades

**Before:**
```
12:30 PM → Scheduler triggers Phase 3 (hope Phase 2 is done)
1:00 PM  → Scheduler triggers Phase 4 (hope Phase 3 is done)
1:00 PM  → Scheduler triggers Phase 6 export (NO PREDICTIONS YET!)
1:30 PM  → Scheduler triggers predictions
2:15 PM  → Self-heal actually generates predictions
```

**After:**
```
Phase 2 completes → Immediately triggers Phase 3
Phase 3 completes → Immediately triggers Phase 4
Phase 4 completes → Immediately triggers Phase 5
Phase 5 completes → Immediately triggers Phase 6

Result: Predictions ready by 12:30 PM instead of 2:45 PM (2+ hours faster)
```

### 2. Intelligent Dependency Checking

**Before:**
```python
if row_count < 200:
    raise Error("Not enough data")  # Blocks entire pipeline
```

**After:**
```python
result = check_dependencies(mode='same_day')
# result.decision = PROCEED | WAIT | PROCEED_DEGRADED | FAIL
# result.completeness = 95%
# result.quality_score = 0.92

if result.decision in (PROCEED, PROCEED_DEGRADED):
    trigger_next_phase()  # 10 predictions better than 0!
```

**Decision Matrix:**

| Scenario | Overnight | Same-Day | Action |
|----------|-----------|----------|--------|
| 10/11 games | **WAIT** (expect 100%) | **PROCEED** (91% is good) | Different thresholds |
| Missing critical table | **FAIL** | **FAIL** | Universal rules |
| Stale data (12h old) | **WAIT** (re-scrape) | **PROCEED** (use what we have) | Mode awareness |

### 3. Multi-Mode Orchestration

**5 Modes, 5 Different Behaviors:**

| Mode | When | Completeness | Quality | Retry | Alerts |
|------|------|--------------|---------|-------|--------|
| **Overnight** | 11 PM - 6 AM | 100% required | 0.95 | Every 10 min | Alert if <100% |
| **Same-day** | 10:30 AM | 80% OK | 0.90 | Every 5 min | Alert if <50% |
| **Tomorrow** | 5 PM | 75% OK | 0.85 | Every 30 min | Alert if <30% |
| **Manual** | On-demand | 50% OK | 0.80 | One-shot | No alerts |
| **Backfill** | Batch | 100% required | 0.95 | Manual | No alerts |

**Example: Phase 3→4 Orchestrator**

```python
# Detect mode
mode = detect_mode(message, current_time)

# Get expected processors for this mode
expected = {
    'overnight': [5 processors],  # All analytics
    'same_day': [2 processors],   # Only upcoming context
    'backfill': [3 processors]    # No upcoming context
}[mode]

# Wait for the RIGHT processors, not just any 5
if all_expected_complete(mode):
    trigger_phase4(mode)
```

### 4. Dual State Management

**Firestore (Real-Time Coordination):**
- Atomic transactions prevent race conditions
- `_triggered` flag prevents duplicates
- TTL: 7 days (lightweight)

**BigQuery (Audit & Analysis):**
- Full event log (orchestration_events)
- Dependency check history (dependency_check_log)
- SLO tracking (phase_completion_log)
- Retention: 1 year

**Benefits:**
- Query historical trends: "Why did Dec 15 fail?"
- Real-time coordination: No duplicate triggers
- Root cause analysis: "Which table was missing?"

### 5. Comprehensive Monitoring

**Real-Time Dashboard:**
```
Game Date: 2025-12-31 (Same-Day Mode)

Phase 2: ✅ Complete (6/6, 100%)
Phase 3: ⏳ In Progress (1/2, 50%)
Phase 4: ⏸️ Pending
Phase 5: ⏸️ Pending

Overall: 40% complete
ETA: 11:30 AM ET
```

**SLO Tracking:**
- End-to-end latency: Target < 2 hours (same-day)
- Phase completeness: Target >= 80% (same-day)
- Quality score: Target >= 0.90
- Cascade success rate: Target >= 95%

**Alerts:**
- Pipeline stuck (> 2 hours in same-day mode)
- Dependency check failed (critical data missing)
- SLO violation (predictions late)
- Self-heal triggered (cascade failed)

---

## Implementation Plan

### Week 1: Infrastructure
- Create BigQuery tables (orchestration_events, dependency_check_log)
- Create Pub/Sub topics (orchestration-status, slo-violation)
- Deploy dependency-checker function
- Deploy state-monitor function

### Week 2: Orchestrator Updates
- Update phase2-to-phase3 to v3.0 (event-driven)
- Update phase3-to-phase4 to v3.0 (mode-aware)
- Update phase4-to-phase5 to v3.0 (mode-aware)
- Update phase5-to-phase6 to v3.0 (quality-aware)

### Week 3: Cutover
- Enable cascades as primary
- Demote schedulers to fallback
- Enable monitoring and alerts
- Monitor for 1 week

### Rollback Plan
If cascade failure rate > 20%:
1. Re-enable schedulers as primary (< 5 minutes)
2. Revert orchestrators to v2.0 (< 1 hour)
3. Analyze and fix (< 24 hours)

---

## Risk Mitigation

### Infinite Loop Prevention
```python
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor, data):
    # Check _triggered flag
    if current.get('_triggered'):
        return False  # Already triggered, skip

    # Mark as triggered atomically
    current['_triggered'] = True
    transaction.set(doc_ref, current)
    return True
```

### Circuit Breaker
```python
if failure_count[game_date] >= 5:
    logger.error("Circuit breaker OPEN")
    alert_operator()
    return  # Don't retry
```

### Graceful Degradation
```
1. Event-driven cascade (primary)
   ↓ fails
2. Scheduler fallback (safety net)
   ↓ fails
3. Self-heal (force trigger)
   ↓ fails
4. Manual intervention (human)
```

---

## Expected Outcomes

### Performance
- Predictions ready 2+ hours earlier (12:30 PM vs 2:45 PM)
- Cascade success rate: 95%+
- Self-heal intervention: < 20%
- End-to-end latency reduced 30%

### Reliability
- No duplicate triggers
- No infinite loops
- No pipeline deadlocks
- Partial data doesn't block pipeline

### Observability
- Real-time pipeline status dashboard
- Historical trend analysis
- Root cause analysis for failures
- SLO compliance tracking

### Operational
- Fewer manual interventions (80% reduction)
- Faster debugging (minutes vs hours)
- Better alerts (context-aware)
- Lower on-call burden

---

## Cost Analysis

**Current:** $0.60/month
**New:** $3.05/month
**Incremental:** +$2.45/month

**ROI:**
- Time saved debugging: $1000/month
- Reduced manual work: $500/month
- **Net benefit: $1497/month**

---

## Success Criteria

### Must Have (P0)
- [ ] Cascades trigger 95%+ of the time
- [ ] No duplicate triggers (0 in 30 days)
- [ ] Mode detection 100% accurate
- [ ] End-to-end latency < 2 hours (same-day)

### Should Have (P1)
- [ ] Dependency checks < 30 seconds (p95)
- [ ] Quality score >= 0.90 (all modes)
- [ ] Self-heal needed < 20% of time
- [ ] Dashboards show real-time status

### Nice to Have (P2)
- [ ] Predictive alerting (warn before SLO violation)
- [ ] ML-based anomaly detection
- [ ] Auto-scaling based on game count
- [ ] Integration with broader observability platform

---

## Key Files to Review

**Design Document:**
- `EVENT-DRIVEN-ORCHESTRATION-DESIGN.md` (full 200+ pages)

**Current Documentation:**
- `docs/01-architecture/orchestration/orchestrators.md`
- `docs/02-operations/orchestrator-monitoring.md`
- `ORCHESTRATION-IMPROVEMENTS.md`
- `ORCHESTRATION-TIMING-IMPROVEMENTS.md`
- `RECURRING-ISSUES.md`

**Implementation Files (to create):**
- `orchestration/dependency_checker.py`
- `orchestration/state_manager.py`
- `orchestration/mode_detector.py`
- `orchestration/cloud_functions/intelligent_dependency_checker/`
- `schemas/bigquery/nba_orchestration/orchestration_events.sql`

**Implementation Files (to update):**
- `orchestration/cloud_functions/phase2_to_phase3/main.py` (v2.0 → v3.0)
- `orchestration/cloud_functions/phase3_to_phase4/main.py` (v1.1 → v3.0)
- `orchestration/cloud_functions/phase4_to_phase5/main.py` (v1.0 → v3.0)
- `shared/config/orchestration_config.py`

---

## Next Actions

### For Approval
1. Review this summary
2. Review full design document
3. Approve migration plan
4. Allocate 3 weeks for implementation

### For Implementation
1. Create GitHub project with migration phases
2. Set up staging environment
3. Create BigQuery tables
4. Deploy dependency checker (staging)
5. Test end-to-end cascade (staging)
6. Deploy to production (phased)

---

## Questions & Answers

**Q: Why not just fix the scheduler timing?**
A: Timing fixes are brittle. If Phase 4 takes 45 min instead of 30, everything breaks. Event-driven adapts automatically.

**Q: What if Firestore goes down?**
A: Fallback to scheduler-only mode. Schedulers still work even if Firestore unavailable.

**Q: Will this handle early games (1 PM starts)?**
A: Yes! Cascades start immediately after Phase 2 completes (whenever that is), not at fixed times.

**Q: How do we test this without breaking production?**
A: Staged rollout: staging → production orchestrators one-by-one → monitor 48h between → rollback if issues.

**Q: What's the rollback plan?**
A: Re-enable schedulers as primary (5 min), revert orchestrators (1 hour). No data loss.

**Q: How does this help with the "Phase 6 exports before predictions" bug?**
A: Phase 6 won't trigger until Phase 5 (predictions) completes and passes quality check. No more exporting empty predictions!

---

**For full details, see:** `EVENT-DRIVEN-ORCHESTRATION-DESIGN.md`

*Created: December 31, 2025*
*Status: Ready for Review*
