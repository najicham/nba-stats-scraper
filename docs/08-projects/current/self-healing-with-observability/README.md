# Self-Healing with Observability

**Date:** 2026-02-05
**Philosophy:** Auto-heal, but track everything so we can prevent recurrence

## Core Principle

> "Silent self-healing masks problems. Observable self-healing prevents them."

Every self-healing action must:
1. ✅ **Log the action** - What was healed
2. ✅ **Log the root cause** - Why it needed healing
3. ✅ **Track metrics** - How often does this happen
4. ✅ **Alert on patterns** - If healing too frequently, alert humans
5. ✅ **Store for analysis** - Keep history for root cause analysis

## Components

### Phase 1: Investigation (Session 135)
- [x] Investigate worker injury handling bug
- [x] Investigate batch completion tracking inconsistency
- [x] Document findings

### Phase 2: Self-Healing Infrastructure (Session 135)
- [ ] Healing event tracking system (Firestore + BigQuery)
- [ ] Healing metrics dashboard
- [ ] Pattern detection alerts

### Phase 3: Implementations (Session 135)
- [ ] Auto-batch cleanup with full audit trail
- [ ] Worker injury handling fix (prevent future issues)
- [ ] Batch completion tracking fix

### Phase 4: Deploy & Monitor
- [ ] Deploy resilience monitoring (Layer 1-2)
- [ ] Deploy self-healing components
- [ ] Monitor healing patterns for 7 days
- [ ] Identify root causes to prevent

## Healing Event Schema

Every healing action creates a record:

```python
{
    'healing_id': str,  # Unique ID
    'timestamp': datetime,
    'healing_type': str,  # 'batch_cleanup', 'retry', 'fallback', etc.
    'trigger_reason': str,  # Why healing was needed
    'action_taken': str,  # What we did
    'before_state': dict,  # State before healing
    'after_state': dict,  # State after healing
    'success': bool,  # Did healing work?
    'metadata': dict,  # Type-specific data
}
```

## Alerting Thresholds

**Yellow Alert:** Same healing action 3+ times in 1 hour
**Red Alert:** Same healing action 10+ times in 1 day
**Critical Alert:** Healing failure rate >20%

## Next Steps

See session docs for implementation details.
