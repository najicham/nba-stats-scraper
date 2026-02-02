# ADR 002: Service-Specific Deployment Runbooks

**Status**: Accepted
**Date**: 2026-02-02
**Decision Makers**: Infrastructure Team, Session 79
**Tags**: deployment, documentation, operations

---

## Context

Multiple deployment failures occurred due to:
- Lack of documented procedures
- Tribal knowledge (only in Claude's memory)
- No troubleshooting guides for common issues
- Session-specific fixes not documented for future use

**Problem**: Deployment procedures not documented, causing repeated mistakes.

---

## Decision

Create **service-specific deployment runbooks** with:
1. Pre-deployment checklists
2. Step-by-step deployment procedures
3. Common issues with real examples from past sessions
4. Rollback procedures
5. Service dependencies
6. Success criteria

---

## Rationale

### Why Service-Specific vs. Generic?

**Chosen**: Service-specific runbooks (one per critical service)

**Alternatives**:
- Generic deployment guide → Too abstract, misses service nuances
- Inline comments in scripts → Not discoverable
- Wiki/Notion → Separate from codebase, gets stale

**Why Service-Specific Won**:
- Each service has unique critical metrics (Vegas coverage, hit rate, etc.)
- Real examples from past sessions are service-specific
- Easier to find (in repo, named by service)
- Can reference specific issues (Session 76, 64, etc.)

### What to Include?

**Included**:
- Pre-deployment checklist (tests, schema, sync)
- Deployment steps (with commands)
- Common issues from actual sessions
- Rollback procedures
- Service dependencies
- Success criteria (specific metrics)

**Excluded**:
- Generic Docker info → Already documented elsewhere
- GCP basics → Not service-specific
- Code architecture → Separate docs

---

## Implementation

**Runbooks Created** (4):
1. `deployment-prediction-worker.md` (458 lines)
   - ML model deployment
   - Hit rate validation (55-58%)
   - Model version control

2. `deployment-prediction-coordinator.md` (245 lines)
   - Batch orchestration
   - Scheduler integration

3. `deployment-phase4-processors.md` (421 lines)
   - Vegas line coverage (90%+ critical)
   - Session 76 prevention

4. `deployment-phase3-processors.md` (400 lines)
   - Evening processing
   - Shot zone validation

**Structure** (consistent across all):
```markdown
1. Overview - Service description, criticality
2. Pre-Deployment Checklist - What to check before
3. Deployment Process - Step-by-step with commands
4. Common Issues - Real examples with fixes
5. Rollback Procedure - Emergency recovery
6. Monitoring - What to watch post-deploy
7. Success Criteria - When deployment is "done"
```

---

## Consequences

### Positive
- ✅ Deployment procedures documented for all critical services
- ✅ Common issues preserved with solutions
- ✅ Reduces MTTR (Mean Time To Resolution)
- ✅ New team members can deploy with confidence
- ✅ Real session examples make it actionable

### Negative
- ⚠️ Requires maintenance as services evolve
- ⚠️ Can become stale if not updated

### Risks Mitigated
- **Repeat failures**: Session 76 (Vegas coverage), Session 64 (stale code) documented
- **Tribal knowledge loss**: Procedures captured in repo
- **Inconsistent deployments**: Standard process for all

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Deployment procedures | 0 | 4 (1,524 lines) |
| Common issues documented | 0 | ~20 issues |
| Session references | 0 | 8+ sessions |
| Rollback procedures | Undocumented | 4 detailed guides |

---

## References

- `docs/02-operations/runbooks/nba/`
- Session 79 handoff
- Session 76 (Vegas coverage drop)
- Session 64 (Stale code deployment)

---

## Future Considerations

- Add runbooks for Phase 2 processors, scrapers
- Video walkthroughs for complex procedures
- Automated runbook testing
- Link to incident post-mortems
