# ADR 001: Unified Health Monitoring System

**Status**: Accepted
**Date**: 2026-02-02
**Decision Makers**: Infrastructure Team, Session 77-78
**Tags**: monitoring, alerting, prevention

---

## Context

Session 77 revealed critical issues that went undetected for days/weeks:
- **Deployment drift**: 598 commits behind production
- **Vegas line coverage drop**: From 92% to 44% undetected
- **Silent degradation**: No alerts for critical metric drops

**Problem**: No automated monitoring to detect system degradation early.

---

## Decision

Implement a **unified health monitoring system** that:
1. Checks 6 critical system metrics every 6 hours
2. Runs as a Cloud Run Job (not Cloud Function)
3. Sends alerts to Slack via webhooks
4. Returns exit codes for automation (0=healthy, 1=warning, 2=critical)

---

## Rationale

### Why Unified vs. Separate Monitors?

**Chosen**: Single unified script checking all metrics

**Alternatives Considered**:
- Separate scripts per metric → Too fragmented, hard to maintain
- Cloud Monitoring only → Doesn't capture business logic (e.g., Vegas coverage)
- Manual checks → Doesn't scale, error-prone

**Why Unified Won**:
- Single source of truth for system health
- Easier to maintain (one script vs many)
- Consistent exit codes and alerting
- Can run locally for debugging

### Why Cloud Run Job vs. Cloud Function?

**Chosen**: Cloud Run Job

**Alternatives Considered**:
- Cloud Function → 540s timeout insufficient for all checks
- Cloud Scheduler directly calling services → No aggregation
- GitHub Actions → Can't access internal GCP resources easily

**Why Cloud Run Job Won**:
- No timeout limits (can run 24 hours if needed)
- Same execution environment as other services
- Easy to test locally with Docker
- Can use Cloud Scheduler to trigger

### Why 6-Hour Frequency?

**Chosen**: Every 6 hours (12 AM, 6 AM, 12 PM, 6 PM PT)

**Alternatives Considered**:
- Hourly → Too noisy, alert fatigue
- Daily → Too infrequent, 24-hour detection delay
- Real-time → Complex, expensive, unnecessary

**Why 6 Hours Won**:
- Meets goal: Detect issues within 24 hours (we achieved 6 hours)
- 4 checks per day = sufficient coverage
- Low cost (<$1/week)
- Aligns with business hours (6 AM check catches overnight issues)

---

## Consequences

### Positive
- ✅ 6-hour detection window (75% better than 24-hour goal)
- ✅ Automated alerting to Slack
- ✅ Vegas coverage drop detected immediately (prevents Session 76)
- ✅ Deployment drift caught daily
- ✅ Low cost (<$1/week)
- ✅ Easy to extend with new checks

### Negative
- ⚠️ Manual Slack webhook configuration (one-time)
- ⚠️ Requires GCP Secret Manager for webhook URL
- ⚠️ 6-hour window still allows some degradation

### Risks Mitigated
- **Session 76 recurrence**: Vegas coverage monitored
- **Deployment drift**: Detected within 6 hours
- **Silent failures**: All critical metrics checked

---

## Implementation

**Files**:
- `bin/monitoring/unified-health-check.sh` - Main script
- `bin/monitoring/unified-health-check-scheduled.sh` - Cloud Run variant
- `deployment/dockerfiles/nba/Dockerfile.health-check` - Container
- `.github/workflows/check-deployment-drift.yml` - GitHub Action

**Checks**:
1. Vegas line coverage (≥90%)
2. Grading completeness (≥90%)
3. Phase 3 completion (5/5 processors)
4. Recent predictions (>100 for scheduled days)
5. BDB coverage (≥90%)
6. Deployment drift (services up-to-date)

**Scheduler**:
```yaml
Schedule: 0 */6 * * * (every 6 hours)
Timezone: America/Los_Angeles
Job: unified-health-check (Cloud Run Job)
```

---

## Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Detection time | Never/Days | 6 hours | 75% better than goal |
| Manual checks | Daily | Automated | 100% reduction |
| Alert latency | N/A | <5 minutes | N/A |
| Cost | $0 | <$1/week | Negligible |

---

## References

- Session 77: Initial design and implementation
- Session 78: Deployment and testing
- `docs/08-projects/current/prevention-and-monitoring/STRATEGY.md`
- `bin/monitoring/unified-health-check.sh`

---

## Lessons Learned

1. **Unified is better than fragmented** for health monitoring
2. **6-hour frequency** balances detection speed with alert fatigue
3. **Cloud Run Jobs** provide flexibility without timeout constraints
4. **Exit codes** enable automation and chaining
5. **Local testability** is critical for debugging

---

## Future Considerations

- Consider 3-hour frequency during high-risk periods (trade deadline)
- Add more business metrics as they're identified
- Integrate with PagerDuty for on-call escalation
- Add anomaly detection (ML-based thresholds)
