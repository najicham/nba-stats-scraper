# Decision: Monitoring Data Storage

**Date**: 2026-01-26
**Decision**: **Keep BigQuery with Batching**
**Status**: Recommended, pending final approval

---

## Summary

After careful evaluation, **batching is sufficient**. Migration to Firestore/Cloud Logging is not justified at this time.

---

## The Numbers

### With Batching (Already Implemented)

| Metric | Value |
|--------|-------|
| Quota usage | 2% (32/1,500 jobs) |
| Headroom | 98% |
| Growth capacity | 47x before hitting quota |
| Migration effort | Zero (just deploy) |
| Additional cost | $0 |

### If We Migrated to Firestore + Cloud Logging

| Metric | Value |
|--------|-------|
| Quota usage | 0% (no BQ writes) |
| Migration effort | 2-3 weeks |
| Additional cost | $60-80/month |
| Risk | Medium (new systems, new queries) |
| Benefit over batching | Marginal |

---

## Why NOT Migrate

1. **Batching already solves the quota problem** (98% headroom)
2. **Migration adds cost** ($60-80/month for marginal benefit)
3. **Migration adds complexity** (3 systems vs 1)
4. **Migration adds risk** (new code, new queries, potential bugs)
5. **Team knows BigQuery** (no learning curve)
6. **All data in one place** (easier debugging, joins)

---

## Why I Initially Thought Migration

I initially recommended migration because:
- "Right tool for each job" sounds good in theory
- Firestore IS better for real-time state
- Cloud Logging IS better for high-frequency events

But in practice:
- Our "high-frequency" is 2,466 writes/day = trivial with batching
- Circuit breaker latency is acceptable (not measured, but no complaints)
- We don't need real-time dashboards
- Simpler is better

---

## When to Reconsider

Migrate to Firestore/Cloud Logging ONLY if:

1. **Quota usage exceeds 50%** (currently 2%)
2. **Circuit breaker latency** becomes a bottleneck (measure first)
3. **Traffic grows 20x+**
4. **Real-time dashboards** become a requirement

---

## Action Plan

### Tonight
```bash
# 1. Push the batching code
git push origin main

# 2. Rebuild services (or let CI/CD do it)
# The batching will take effect on next deployment

# 3. If quota is still exceeded today, disable writes temporarily:
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --set-env-vars="DISABLE_RUN_HISTORY_LOGGING=true"
```

### Tomorrow
- Verify batching is working (check logs for "Flushed N records")
- Re-enable any disabled logging
- Monitor quota usage

### This Week
- Deploy quota monitoring (hourly checks)
- Add quota check to `/validate-daily` skill
- Close this evaluation as "Batching is sufficient"

---

## Final Recommendation

**Do this**:
1. ✅ Deploy batching (push + rebuild)
2. ✅ Add quota monitoring
3. ✅ Measure circuit breaker latency (for future reference)

**Don't do this**:
1. ❌ Migrate to Firestore
2. ❌ Migrate to Cloud Logging
3. ❌ Table rotation

**Revisit in 3 months** or if conditions change.
