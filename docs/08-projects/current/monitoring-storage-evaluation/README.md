# Project: Monitoring Data Storage Evaluation

**Created**: 2026-01-26
**Status**: Evaluation in Progress
**Priority**: P1 (blocking production)
**Decision Needed By**: 2026-01-27

---

## Problem Statement

BigQuery's hard limit of 1,500 load jobs per table per day caused a complete pipeline outage. Three monitoring tables exceeded this quota:

| Table | Writes/Day | Purpose |
|-------|-----------|---------|
| `processor_run_history` | 1,321 | Debug/audit trail |
| `circuit_breaker_state` | 575 | Failure protection |
| `analytics_processor_runs` | 570 | Phase 3 tracking |

**Question**: Should we migrate this data to different storage systems, or is batching sufficient?

---

## Options Under Consideration

### Option A: BigQuery with Batching (Already Implemented)

Keep all data in BigQuery, use batching to reduce load jobs.

### Option B: Full Migration

- `processor_run_history` → Cloud Logging
- `circuit_breaker_state` → Firestore
- `analytics_processor_runs` → Cloud Logging

### Option C: Partial Migration (Circuit Breaker Only)

- `circuit_breaker_state` → Firestore (real-time state)
- Keep others in BigQuery with batching

### Option D: Table Rotation

- Create daily tables: `processor_run_history_20260126`
- Each table has fresh quota
- Query with wildcards

---

## Detailed Analysis

### Option A: BigQuery with Batching

**Implementation Status**: ✅ Complete (commit 129d0185, not deployed)

**Quota Impact After Batching**:
| Table | Before | After | Reduction |
|-------|--------|-------|-----------|
| processor_run_history | 1,321/day | 14/day | 94x |
| circuit_breaker_state | 575/day | 12/day | 48x |
| analytics_processor_runs | 570/day | 6/day | 95x |
| **TOTAL** | 2,466/day | 32/day | **77x** |

**Quota Headroom**: 98% (can handle 47x traffic growth)

**Pros**:
- ✅ Already implemented, just needs deploy
- ✅ No migration effort
- ✅ All data in one place (easy joins, familiar SQL)
- ✅ No new infrastructure to manage
- ✅ No new query patterns to learn
- ✅ Cost: $0 additional (load jobs are free)
- ✅ 47x growth headroom before hitting quota again

**Cons**:
- ⚠️ Still have hard limit (but 98% headroom)
- ⚠️ Batching adds 30s latency for low-traffic writes
- ⚠️ Not the "optimal" tool for high-frequency small writes
- ⚠️ Circuit breaker reads are slower (BQ query vs Firestore read)

**Risk Assessment**:
- What if traffic grows 50x? We'd hit quota again
- But: We have monitoring now, would catch it at 80%
- And: Can increase batch size (100 → 500) for another 5x
- Effective ceiling: ~250x current traffic before real problems

**Verdict**: ✅ **Sufficient for current and foreseeable needs**

---

### Option B: Full Migration (Firestore + Cloud Logging)

**Migration Effort**: High (2-3 weeks)

**Architecture**:
```
processor_run_history → Cloud Logging (structured logs)
circuit_breaker_state → Firestore (real-time state)
analytics_processor_runs → Cloud Logging (structured logs)
```

**Pros**:
- ✅ No write quotas (effectively unlimited)
- ✅ "Right tool for each job" philosophy
- ✅ Faster circuit breaker reads (Firestore: <10ms vs BQ: 500ms+)
- ✅ Cloud Logging is free up to 50GB/month

**Cons**:
- ❌ Significant migration effort (2-3 weeks)
- ❌ New infrastructure to manage
- ❌ Can't easily join with BigQuery data
- ❌ Team needs to learn new query patterns
- ❌ Cloud Logging queries are NOT SQL (different syntax)
- ❌ Firestore costs ~$2-3/day for writes ($60-90/month)
- ❌ Need to export to BigQuery anyway for analytics dashboards
- ❌ More complexity (3 systems instead of 1)
- ❌ Debugging harder (data in multiple places)

**Cost Analysis**:
| Component | Current (BQ) | After Migration |
|-----------|--------------|-----------------|
| Storage | $9/month | $9/month (BQ) + $60/month (Firestore) |
| Queries | $5/month | $5/month + Log Analytics costs |
| Operations | Low | Medium (more systems) |
| **Total** | ~$14/month | ~$80/month |

**Risk Assessment**:
- Migration could introduce bugs
- Team unfamiliar with Firestore/Logging queries
- Adds operational complexity
- Solving a problem that batching already solves

**Verdict**: ❌ **Over-engineered for current needs**

---

### Option C: Partial Migration (Circuit Breaker Only)

**Migration Effort**: Medium (1 week)

**Rationale**: Circuit breaker is the only table where BigQuery is arguably wrong:
- It's **real-time state** (open/closed/half-open)
- Needs **fast reads** for every processor run
- Currently queries BQ for state (slow: 500ms+)
- Firestore reads: <10ms

**Architecture**:
```
processor_run_history → BigQuery (with batching) ✓
circuit_breaker_state → Firestore (real-time state)
analytics_processor_runs → BigQuery (with batching) ✓
```

**Pros**:
- ✅ Faster circuit breaker checks (50x faster)
- ✅ Firestore is naturally suited for state
- ✅ Already have Firestore (phase3_completion uses it)
- ✅ Minimal migration (just circuit breaker)
- ✅ Other tables stay in BigQuery with batching

**Cons**:
- ⚠️ Still some migration effort (1 week)
- ⚠️ Circuit breaker state now in different place
- ⚠️ Firestore cost: ~$1/day ($30/month)
- ⚠️ Need to update dashboards/queries

**Cost Analysis**:
| Component | Current | After |
|-----------|---------|-------|
| BigQuery | $14/month | $14/month |
| Firestore | $0 | $30/month |
| **Total** | $14/month | $44/month |

**Performance Improvement**:
- Circuit breaker read: 500ms → 10ms (50x faster)
- Every processor run checks circuit state
- ~600 processor runs/day × 490ms saved = 294 seconds/day saved

**Verdict**: ⚠️ **Nice to have, not urgent**

---

### Option D: Table Rotation

**Migration Effort**: Low (few days)

**Architecture**:
- Create daily tables: `processor_run_history_20260126`
- Each table has fresh 1,500 quota
- Query with wildcards: `processor_run_history_*`

**Pros**:
- ✅ Simple to implement
- ✅ Each day has fresh quota
- ✅ Natural data partitioning
- ✅ Easy to delete old data (drop table)

**Cons**:
- ❌ Wildcard queries are slower
- ❌ Table management overhead
- ❌ Need cleanup job for old tables
- ❌ Batching is simpler and achieves same goal
- ❌ More tables = more metadata overhead

**Verdict**: ❌ **Unnecessary complexity when batching works**

---

## Comparison Matrix

| Criteria | A: Batching | B: Full Migration | C: Partial | D: Rotation |
|----------|-------------|-------------------|------------|-------------|
| Implementation effort | ✅ Done | ❌ 2-3 weeks | ⚠️ 1 week | ⚠️ Few days |
| Quota headroom | ✅ 98% | ✅ Unlimited | ✅ 98% + unlimited CB | ✅ Unlimited |
| Query simplicity | ✅ SQL | ❌ Mixed | ⚠️ Mostly SQL | ⚠️ Wildcards |
| Operational complexity | ✅ Low | ❌ High | ⚠️ Medium | ⚠️ Medium |
| Cost | ✅ $14/mo | ❌ $80/mo | ⚠️ $44/mo | ✅ $14/mo |
| Performance | ⚠️ OK | ✅ Fast CB | ✅ Fast CB | ⚠️ OK |
| Future-proofing | ⚠️ 47x growth | ✅ Unlimited | ✅ Good | ⚠️ OK |

---

## Recommendation

### Immediate (Tonight): Option A - Deploy Batching

**Rationale**:
1. Already implemented, just needs push + deploy
2. Solves 98% of the problem immediately
3. Zero migration risk
4. Can evaluate other options later with data

**Actions**:
```bash
git push origin main
# Then rebuild Cloud Run services
```

### Short-term (This Week): Add Monitoring + Evaluate

1. Deploy quota monitoring (hourly checks)
2. Measure actual circuit breaker read latency
3. Collect data on query patterns
4. Make informed decision about Option C

### Medium-term (Next Sprint): Consider Option C if Justified

**Only migrate circuit breaker to Firestore if**:
- Circuit breaker reads are proven bottleneck (measure first)
- Team has bandwidth for migration
- Performance improvement justifies $30/month cost

### Do NOT Do: Options B and D

- **Option B** (full migration): Over-engineered, high cost, high risk
- **Option D** (rotation): Unnecessary when batching works

---

## Decision Framework

### When to Reconsider Migration

Re-evaluate if ANY of these occur:

1. **Quota usage exceeds 50%** after batching (currently 2%)
2. **Circuit breaker latency** causes measurable delays (measure first)
3. **Traffic grows 20x+** and approaching quota limits
4. **Team requests** better debugging tools that BigQuery can't provide

### When NOT to Migrate

1. ✅ Batching keeps quota under 50%
2. ✅ Circuit breaker latency is acceptable
3. ✅ Team is comfortable with BigQuery queries
4. ✅ No budget for additional infrastructure costs

---

## Open Questions

1. **What is current circuit breaker read latency?** (Need to measure)
2. **How often do we query run_history?** (Daily? On-demand?)
3. **Do we need real-time dashboards?** (If yes, Firestore might help)
4. **What's acceptable cost increase?** ($30/mo? $80/mo?)

---

## Project Files

```
docs/08-projects/current/monitoring-storage-evaluation/
├── README.md                    # This file
├── DECISION.md                  # Final decision (TBD)
├── benchmarks/                  # Performance measurements (TBD)
│   ├── circuit-breaker-latency.md
│   └── query-patterns.md
└── implementation/              # If we decide to migrate (TBD)
    ├── firestore-migration.md
    └── cloud-logging-migration.md
```

---

## Timeline

| Date | Action |
|------|--------|
| 2026-01-26 | Deploy batching (immediate fix) |
| 2026-01-27 | Deploy quota monitoring |
| 2026-01-28 | Measure circuit breaker latency |
| 2026-01-31 | Review data, make final decision |
| 2026-02-07 | Implement migration if decided |

---

## Conclusion

**Batching is sufficient.** It solves 98% of the quota problem with zero migration risk.

Migration to Firestore/Cloud Logging is:
- Not necessary for quota (batching solves this)
- Potentially beneficial for circuit breaker performance (measure first)
- Not worth the cost/complexity for run_history

**Recommended path**: Deploy batching now, measure, then decide on circuit breaker migration with real data.
