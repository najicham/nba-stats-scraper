# Week 1: Cost & Reliability Sprint

**Duration:** 5 days (12 hours total)
**Goal:** 99.5% reliability + $60-90/month cost savings
**Start:** Wednesday, January 22, 2026 (after Week 0 validation)

---

## 🎯 Week 1 Objectives

1. **Fix critical scalability blocker** (ArrayUnion limit)
2. **Reduce BigQuery costs by 30-45%** ($60-90/month savings)
3. **Prevent duplicate processing** (idempotency)
4. **Improve maintainability** (centralized config)
5. **Enhance observability** (structured logging)

---

## 📅 Day-by-Day Plan

### Day 1 (Wednesday): Critical Scalability Fixes
**Time:** 3 hours
**Priority:** 🔴 CRITICAL

#### Morning: Phase 2 Completion Deadline (1-2h)
**Problem:** Phase 2→3 orchestrator can wait indefinitely for processors
**Impact:** Prevents SLA violations

**Implementation:**
- File: `orchestration/cloud_functions/phase2_to_phase3/main.py`
- Add 30-minute deadline after first processor completes
- If timeout, trigger Phase 3 with available data
- Send Slack alert on timeout

**Success Criteria:**
- Timeout triggers after 30 minutes
- Phase 3 receives partial data
- Slack alert sent
- No indefinite waits

**Guide:** [implementation-guides/01-phase2-completion-deadline.md](implementation-guides/01-phase2-completion-deadline.md)

---

#### Afternoon: ArrayUnion to Subcollection Migration (2h)
**Problem:** `completed_players` array approaching 1,000 element Firestore limit
**Impact:** CRITICAL - System will break at scale

**Implementation:**
- File: `predictions/coordinator/batch_state_manager.py`
- Dual-write pattern (write to both old + new)
- New subcollection: `predictions_batches/{batch_id}/completions/{player_id}`
- Use counter instead of array
- Validate, then switch reads
- Delete old structure after validation

**Success Criteria:**
- Both old and new structures updated
- Counter matches array length
- Reads work from subcollection
- Old array can be deleted
- Supports unlimited players

**Guide:** [implementation-guides/02-arrayunion-to-subcollection.md](implementation-guides/02-arrayunion-to-subcollection.md)

---

### Day 2 (Thursday): BigQuery Cost Optimization
**Time:** 2-3 hours
**Priority:** 💰 HIGH - $60-90/month savings

#### Full Day: BigQuery Optimization (2-3h)
**Problem:** Full table scans costing $200/month on BigQuery
**Impact:** 30-45% cost reduction ($60-90/month)

**Implementation Tasks:**

**Task 1: Add Date Filters (30 min)**
- Review all BigQuery queries
- Add `WHERE DATE(timestamp_column) = CURRENT_DATE()` to all
- Use partitioned queries everywhere
- Test queries return same results

**Task 2: Implement Query Result Caching (1h)**
- Enable BigQuery result caching
- Cache workflow decision queries (24h TTL)
- Cache execution logs (1h TTL)
- Monitor cache hit rate

**Task 3: Add Clustering (1h)**
- Cluster `workflow_decisions` by workflow_name, action
- Cluster `workflow_executions` by workflow_name, status
- Rebuild tables with clustering
- Validate query performance

**Task 4: Monitor & Validate (30 min)**
- Set up BigQuery cost monitoring dashboard
- Compare costs before/after
- Validate all queries still work
- Document savings

**Success Criteria:**
- All queries use date filters
- Cache hit rate > 50%
- Clustering reduces slot usage
- Cost reduced by 30-45%

**Guide:** [implementation-guides/03-bigquery-optimization.md](implementation-guides/03-bigquery-optimization.md)

---

### Day 3 (Friday): Idempotency & Data Integrity
**Time:** 2-3 hours
**Priority:** 🟡 HIGH

#### Full Day: Idempotency Keys (2-3h)
**Problem:** Duplicate Pub/Sub messages create duplicate batch entries
**Impact:** Inaccurate batch progress tracking

**Implementation:**
- File: `predictions/coordinator/coordinator.py`
- Extract message ID from headers
- Create deduplication collection
- Check if message already processed
- Store processed message IDs (7 day TTL)
- Return 204 if duplicate

**Success Criteria:**
- Duplicate messages return 204
- Dedup collection has 7-day TTL
- Batch progress accurate
- No duplicate completions

**Guide:** [implementation-guides/04-idempotency-keys.md](implementation-guides/04-idempotency-keys.md)

---

### Day 4 (Monday): Configuration Improvements
**Time:** 2 hours
**Priority:** 🟢 MEDIUM

#### Morning: Config-Driven Parallel Execution (1h)
**Problem:** Only `morning_operations` runs in parallel (hardcoded)
**Impact:** Flexible parallelism per workflow

**Implementation:**
- File: `orchestration/workflow_executor.py`
- Add `execution_mode` to workflow config
- Add `max_workers` to workflow config
- Read from config instead of hardcoded check
- Support `parallel` and `sequential` modes

**Success Criteria:**
- All workflows configurable
- Parallel execution works for new workflows
- Sequential fallback works
- Easy to toggle per workflow

**Guide:** [implementation-guides/05-config-driven-parallel.md](implementation-guides/05-config-driven-parallel.md)

---

#### Afternoon: Centralize Timeout Configuration (1h)
**Problem:** 1,070 hardcoded timeout values across codebase
**Impact:** Single source of truth for all timeouts

**Implementation:**
- Create `shared/config/timeout_config.py`
- Create `TimeoutConfig` dataclass
- Define all timeout constants
- Update all timeout references
- Import from central location

**Success Criteria:**
- All timeouts defined in one file
- No hardcoded timeout values
- Easy to adjust timeouts
- Documentation for each timeout

**Guide:** [implementation-guides/06-centralize-timeouts.md](implementation-guides/06-centralize-timeouts.md)

---

### Day 5 (Tuesday): Observability Improvements
**Time:** 2 hours
**Priority:** 🟢 MEDIUM

#### Morning: Structured Logging (1-2h)
**Problem:** String-based logging hard to query
**Impact:** Better Cloud Logging queries

**Implementation:**
- Add JSON logging formatter
- Use `extra` parameter for structured fields
- Include context: workflow_name, correlation_id, etc.
- Update all logging statements
- Test Cloud Logging queries

**Success Criteria:**
- All logs JSON-formatted
- Structured fields queryable
- Cloud Logging dashboards work
- Performance unaffected

**Guide:** [implementation-guides/07-structured-logging.md](implementation-guides/07-structured-logging.md)

---

#### Afternoon: Health Check Metrics (1h)
**Problem:** Health checks only return true/false
**Impact:** Latency and performance visibility

**Implementation:**
- Add metrics to health endpoints
- Include: uptime, request count, avg latency
- Add dependency checks (BigQuery, Firestore)
- Return detailed health status

**Success Criteria:**
- Health endpoints include metrics
- Latency tracked
- Dependency status visible
- Monitoring dashboards updated

**Guide:** [implementation-guides/08-health-check-metrics.md](implementation-guides/08-health-check-metrics.md)

---

## 📊 Week 1 Success Metrics

### Reliability
```
Target:   99.5%+
Current:  98.0%
Goal:     +1.5% improvement
```

### Cost
```
Target:   -$60-90/month
Current:  $800/month
Goal:     ~$730/month (9% reduction)
```

### Scalability
```
Target:   Unlimited players
Current:  ~800 players (at limit!)
Goal:     No limit with subcollections
```

### Data Integrity
```
Target:   Zero duplicates
Current:  Duplicates possible
Goal:     100% idempotent
```

---

## 🔧 Feature Flags Configuration

### Environment Variables
```bash
# Phase 2 completion deadline
ENABLE_PHASE2_COMPLETION_DEADLINE=false
PHASE2_COMPLETION_TIMEOUT_MINUTES=30

# Subcollection completions
ENABLE_SUBCOLLECTION_COMPLETIONS=false
DUAL_WRITE_MODE=true  # Write to both old + new

# BigQuery optimization
ENABLE_QUERY_CACHING=false
QUERY_CACHE_TTL_SECONDS=3600

# Idempotency
ENABLE_IDEMPOTENCY_KEYS=false
DEDUP_TTL_DAYS=7

# Config-driven parallel
ENABLE_PARALLEL_CONFIG=false

# Centralized timeouts
ENABLE_CENTRALIZED_TIMEOUTS=false

# Structured logging
ENABLE_STRUCTURED_LOGGING=false
```

### Rollout Schedule
```
Day 1: Deploy with all flags=false
Day 2: Enable 10% traffic
Day 3: Enable 50% traffic
Day 4: Enable 100% traffic
Day 5: Monitor full rollout
```

---

## 🚀 Deployment Workflow

### Pre-Deployment
1. Complete implementation
2. Run unit tests
3. Test in local environment
4. Deploy to staging
5. Validate in staging
6. Create deployment PR

### Deployment
1. Merge PR to week-1-improvements branch
2. Deploy with feature flags disabled
3. Verify health checks pass
4. Enable feature flag at 10%
5. Monitor for 4 hours
6. Increase to 50%
7. Monitor for 4 hours
8. Increase to 100%

### Post-Deployment
1. Monitor for 24 hours
2. Check error rates
3. Verify cost savings (Day 2+)
4. Update progress tracker
5. Document learnings

---

## ⚠️ Rollback Procedures

### Quick Rollback (Emergency)
```bash
# Disable all Week 1 flags
gcloud run services update nba-orchestrator \
  --update-env-vars \
  ENABLE_PHASE2_COMPLETION_DEADLINE=false,\
  ENABLE_SUBCOLLECTION_COMPLETIONS=false,\
  ENABLE_IDEMPOTENCY_KEYS=false,\
  ENABLE_PARALLEL_CONFIG=false,\
  ENABLE_CENTRALIZED_TIMEOUTS=false,\
  ENABLE_STRUCTURED_LOGGING=false,\
  ENABLE_QUERY_CACHING=false
```

### Gradual Rollback
1. Reduce feature flag percentage (100% → 50% → 10% → 0%)
2. Monitor for stabilization
3. Investigate issue
4. Fix and redeploy
5. Re-enable gradually

### ArrayUnion Rollback
If subcollection migration fails:
1. Set `DUAL_WRITE_MODE=false`
2. Set `USE_SUBCOLLECTION_READS=false`
3. System reverts to array-based tracking
4. Investigate and fix issue
5. Re-enable dual-write

---

## 📋 Daily Checklist

### Each Morning
- [ ] Review previous day's metrics
- [ ] Check error logs
- [ ] Verify feature flag status
- [ ] Review cost dashboard (Days 3-5)
- [ ] Start today's implementation

### Each Afternoon
- [ ] Complete implementation
- [ ] Run tests
- [ ] Deploy to staging
- [ ] Validate in staging
- [ ] Create deployment PR

### Each Evening
- [ ] Deploy to production
- [ ] Enable feature flag (if applicable)
- [ ] Monitor for 2 hours
- [ ] Update progress tracker
- [ ] Document learnings

---

## 📊 Monitoring & Validation

### Daily Metrics to Track
1. **Reliability:** Workflow success rate
2. **Cost:** BigQuery spend (Day 2+)
3. **Performance:** Workflow duration
4. **Errors:** Error rate by service
5. **Duplicates:** Idempotency hit rate (Day 3+)

### Dashboards to Monitor
- Cloud Logging: Error rates
- Cloud Monitoring: Service health
- BigQuery: Cost & slot usage
- Firestore: Read/write operations
- Custom: Workflow execution dashboard

### Alerts to Set Up
- Workflow failure rate > 2%
- Error rate spike > 10%
- Cost anomaly detection
- Health check failures
- Feature flag rollout issues

---

## 🎯 End of Week 1 Goals

### Must Have ✅
- [ ] ArrayUnion migration complete
- [ ] BigQuery costs down 30%+
- [ ] Zero orphaned decisions
- [ ] All feature flags at 100%
- [ ] No production incidents

### Nice to Have 🎁
- [ ] 99.5%+ reliability achieved
- [ ] Full test coverage for new code
- [ ] Documentation complete
- [ ] Monitoring dashboards set up
- [ ] Team trained on new features

### Stretch Goals 🚀
- [ ] Cost down 40%+ (exceeds target)
- [ ] 99.7% reliability (Week 2 goal early!)
- [ ] Additional observability improvements
- [ ] Performance improvements identified

---

## 📞 Support & Questions

### Implementation Questions
- Check specific implementation guide
- Review code examples
- Test in staging first

### Production Issues
- Follow rollback procedure immediately
- Document in progress tracker
- Post-mortem after resolution

### Cost Validation
- Wait 48 hours for BigQuery costs to reflect
- Compare same-day-of-week (Wed-Wed)
- Account for traffic variations

---

## 🎉 Week 1 Celebration Criteria

At the end of Week 1, we celebrate if:
- ✅ Reliability ≥ 99.5%
- ✅ Cost savings ≥ $60/month validated
- ✅ Zero production incidents from changes
- ✅ All 8 improvements deployed
- ✅ ArrayUnion migration successful

**Celebration Plan:** Team retrospective + Week 2 planning session

---

**Created:** January 20, 2026
**Status:** Ready to execute after Week 0 validation
**Next:** Complete Week 0 validation, then begin Day 1

Let's make Week 1 a success! 🚀
