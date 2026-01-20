# Comprehensive TODO List - NBA Stats Scraper
**Created**: 2026-01-20 22:45 UTC
**Current Status**: Week 0 at 80-85% complete (12/17 tasks done)
**Next Milestone**: Choose between Week 0 validation OR Week 1 improvements

---

## 🎯 **DECISION POINT: WHAT TO WORK ON NEXT?**

You have **3 excellent options**:

### Option A: Complete Week 0 Validation ⏱️ 2-3 hours
**Status**: Optional testing/validation tasks
**Impact**: Confidence building, no direct prevention improvement
**When**: Can do now OR skip and move to Week 1

### Option B: Start Week 1 Improvements 🚀 12 hours over 5 days
**Status**: Comprehensive plan ready, high ROI
**Impact**: 80-85% → 99.5% reliability, -$60-90/month costs
**When**: Can start immediately, already planned

### Option C: Hybrid Approach ⚡ Mix & Match
**Status**: Cherry-pick quick wins from both
**Impact**: Balanced validation + new features
**When**: Flexible based on priorities

---

## 📋 **OPTION A: COMPLETE WEEK 0 VALIDATION**

### Remaining Week 0 Tasks (5 tasks, all MEDIUM priority)

#### Task 4: Deploy Dashboard (30-120 min) - Nice-to-Have
**Status**: Attempted but blocked by API complexity
**Blocker**: Scorecard threshold requirements + log filter syntax
**Alternative**: Monitoring via Slack already works perfectly
**Recommendation**: ⚠️ SKIP - Not worth the time investment

- [ ] Investigate scorecard threshold API requirements
- [ ] Fix log-based metric filters (=~ syntax issues)
- [ ] Test dashboard deployment
- [ ] Validate all widgets render correctly

**Effort**: 30-120 min depending on API issues
**Value**: LOW - Slack alerts already provide monitoring
**Decision**: SKIP unless you really want the dashboard

---

#### Tasks 8-10: Circuit Breaker Testing (60 min) - Validation
**Status**: Not started
**Impact**: Confidence that circuit breakers work correctly
**Risk**: Testing in production (could trigger alerts)

- [ ] **Task 8**: Design circuit breaker test plan (15 min)
  - Choose test date (use future date to avoid real data)
  - Plan how to remove Phase 3 data temporarily
  - Document expected behavior

- [ ] **Task 9**: Execute Phase 3→4 gate test (30 min)
  - Trigger Phase 3→4 orchestrator with missing data
  - Verify circuit breaker blocks Phase 4
  - Check Firestore for block record

- [ ] **Task 10**: Verify Slack alert fires (15 min)
  - Confirm Slack alert received
  - Validate alert content (game_date, missing tables)
  - Document results

**Effort**: 60 min total
**Value**: MEDIUM - Builds confidence in deployed systems
**Decision**: OPTIONAL - Could do for peace of mind

---

#### Task 14: Pub/Sub ACK Testing (45 min) - Validation
**Status**: Not started
**Impact**: Validates ROOT CAUSE fix works correctly

- [ ] Create test Cloud Function that throws exception
- [ ] Publish test message to Pub/Sub topic
- [ ] Verify message is NACKed (not ACKed)
- [ ] Confirm Pub/Sub retries the message
- [ ] Document NACK behavior and retry timing

**Effort**: 45 min
**Value**: MEDIUM - Validates most critical fix
**Decision**: OPTIONAL - ROOT CAUSE fix is already working in production

---

#### Task 2: Daily Health Score Metrics (2-3 hours) - Automation
**Status**: Not started, requires infrastructure
**Blocker**: Need to create Cloud Scheduler job + metrics publishing

- [ ] Create Cloud Scheduler job to run smoke test daily
- [ ] Write script to publish metrics to Cloud Monitoring
- [ ] Create dashboard widgets for health scores
- [ ] Set up alerts for health score < 90%
- [ ] Test automated health reporting

**Effort**: 2-3 hours
**Value**: LOW - Manual smoke test already available
**Decision**: DEFER - Not worth time investment now

---

### Week 0 Validation Summary

**Total Time**: 4-6 hours if doing everything
**Total Value**: Medium (confidence building only)
**Recommendation**:
- ✅ **Skip dashboard** (not worth debugging API issues)
- ⚠️ **Optional circuit breaker testing** (if you want confidence)
- ⚠️ **Optional Pub/Sub ACK testing** (if you want validation)
- ❌ **Skip health score automation** (defer to later)

**Quick Decision**: If you want to validate circuit breakers work, spend 60 min on Tasks 8-10. Otherwise, **move to Week 1**.

---

## 🚀 **OPTION B: START WEEK 1 IMPROVEMENTS**

Week 1 has a **comprehensive plan already written** in `docs/10-week-1/WEEK-1-PLAN.md`

### Week 1 Overview (12 hours over 5 days)
**Goal**: 99.5% reliability + $60-90/month cost savings
**Status**: Fully planned with implementation guides
**Risk**: LOW - All feature-flagged with gradual rollout

---

### Day 1 (Wednesday Jan 22): Critical Scalability (3 hours)

#### Morning: Phase 2 Completion Deadline (1-2h) 🔴 CRITICAL
**Problem**: Phase 2→3 can wait indefinitely for processors
**Impact**: Prevents SLA violations

- [ ] Add 30-minute deadline to phase2_to_phase3/main.py
- [ ] Implement timeout logic (trigger Phase 3 with partial data)
- [ ] Add Slack alert on timeout
- [ ] Test timeout behavior
- [ ] Deploy with ENABLE_PHASE2_COMPLETION_DEADLINE=false
- [ ] Enable flag at 10%, monitor

**File**: `orchestration/cloud_functions/phase2_to_phase3/main.py`
**Guide**: `docs/10-week-1/implementation-guides/01-phase2-completion-deadline.md`
**Feature Flag**: `ENABLE_PHASE2_COMPLETION_DEADLINE`

---

#### Afternoon: ArrayUnion to Subcollection (2h) 🔴 CRITICAL
**Problem**: completed_players array approaching 1,000 element Firestore limit
**Impact**: System will BREAK at ~800-1000 players

- [ ] Implement dual-write pattern (write to both old + new)
- [ ] Create subcollection: predictions_batches/{batch_id}/completions/{player_id}
- [ ] Add completion counter (replaces array length)
- [ ] Validate both structures match
- [ ] Switch reads to subcollection
- [ ] Monitor for 24h, then delete old array

**File**: `predictions/coordinator/batch_state_manager.py`
**Guide**: `docs/10-week-1/implementation-guides/02-arrayunion-to-subcollection.md`
**Feature Flags**: `ENABLE_SUBCOLLECTION_COMPLETIONS`, `DUAL_WRITE_MODE`

**Why Critical**: You're approaching the Firestore limit NOW (800 players). This will break soon!

---

### Day 2 (Thursday Jan 23): BigQuery Cost Optimization (2-3h) 💰

#### Full Day: Reduce BigQuery Costs by 30-45% (2-3h)
**Problem**: Full table scans costing $200/month
**Impact**: Save $60-90/month

- [ ] **Task 1**: Add date filters to all queries (30 min)
  - Add `WHERE DATE(timestamp_column) = CURRENT_DATE()` everywhere
  - Use partitioned queries
  - Test queries return same results

- [ ] **Task 2**: Enable query result caching (1h)
  - Cache workflow decision queries (24h TTL)
  - Cache execution logs (1h TTL)
  - Monitor cache hit rate

- [ ] **Task 3**: Add table clustering (1h)
  - Cluster workflow_decisions by workflow_name, action
  - Cluster workflow_executions by workflow_name, status
  - Rebuild tables with clustering

- [ ] **Task 4**: Monitor & validate (30 min)
  - Set up BigQuery cost dashboard
  - Compare costs before/after
  - Document savings

**Files**: All BigQuery queries across the codebase
**Guide**: `docs/10-week-1/implementation-guides/03-bigquery-optimization.md`
**Feature Flag**: `ENABLE_QUERY_CACHING`

**ROI**: $60-90/month savings = $720-1080/year for 2-3 hours work

---

### Day 3 (Friday Jan 24): Idempotency & Data Integrity (2-3h)

#### Full Day: Idempotency Keys (2-3h) 🟡 HIGH
**Problem**: Duplicate Pub/Sub messages create duplicate batch entries
**Impact**: Inaccurate batch progress tracking

- [ ] Extract message ID from Pub/Sub headers
- [ ] Create deduplication Firestore collection
- [ ] Check if message already processed
- [ ] Store processed message IDs (7 day TTL)
- [ ] Return 204 if duplicate detected
- [ ] Test with duplicate messages
- [ ] Monitor dedup hit rate

**File**: `predictions/coordinator/coordinator.py`
**Guide**: `docs/10-week-1/implementation-guides/04-idempotency-keys.md`
**Feature Flag**: `ENABLE_IDEMPOTENCY_KEYS`

---

### Day 4 (Monday Jan 27): Configuration Improvements (2h)

#### Morning: Config-Driven Parallel Execution (1h) 🟢
**Problem**: Only morning_operations runs in parallel (hardcoded)
**Impact**: Flexible parallelism per workflow

- [ ] Add execution_mode to workflow config
- [ ] Add max_workers to workflow config
- [ ] Read from config instead of hardcoded check
- [ ] Support parallel and sequential modes
- [ ] Test with different workflows

**File**: `orchestration/workflow_executor.py`
**Guide**: `docs/10-week-1/implementation-guides/05-config-driven-parallel.md`
**Feature Flag**: `ENABLE_PARALLEL_CONFIG`

---

#### Afternoon: Centralize Timeout Configuration (1h) 🟢
**Problem**: 1,070 hardcoded timeout values across codebase
**Impact**: Single source of truth

- [ ] Create shared/config/timeout_config.py
- [ ] Create TimeoutConfig dataclass
- [ ] Define all timeout constants
- [ ] Update all timeout references
- [ ] Import from central location

**Files**: 1,070 timeout references across codebase
**Guide**: `docs/10-week-1/implementation-guides/06-centralize-timeouts.md`
**Feature Flag**: `ENABLE_CENTRALIZED_TIMEOUTS`

---

### Day 5 (Tuesday Jan 28): Observability Improvements (2h)

#### Morning: Structured Logging (1-2h) 🟢
**Problem**: String-based logging hard to query
**Impact**: Better Cloud Logging queries

- [ ] Add JSON logging formatter
- [ ] Use extra parameter for structured fields
- [ ] Include context: workflow_name, correlation_id
- [ ] Update all logging statements
- [ ] Test Cloud Logging queries

**Files**: All logging calls
**Guide**: `docs/10-week-1/implementation-guides/07-structured-logging.md`
**Feature Flag**: `ENABLE_STRUCTURED_LOGGING`

---

#### Afternoon: Health Check Metrics (1h) 🟢
**Problem**: Health checks only return true/false
**Impact**: Latency and performance visibility

- [ ] Add metrics to health endpoints
- [ ] Include uptime, request count, avg latency
- [ ] Add dependency checks (BigQuery, Firestore)
- [ ] Return detailed health status
- [ ] Update monitoring dashboards

**Files**: Health endpoint implementations
**Guide**: `docs/10-week-1/implementation-guides/08-health-check-metrics.md`

---

### Week 1 Success Metrics
After completing all 8 improvements:
- ✅ Reliability: 80-85% → 99.5%
- ✅ Cost: -$60-90/month ($720-1080/year)
- ✅ Scalability: 800 players → Unlimited
- ✅ Data integrity: 100% idempotent
- ✅ Maintainability: Centralized config

**Total Time**: 12 hours over 5 days (2-3h per day)
**Total Value**: VERY HIGH - Critical fixes + major cost savings

---

## ⚡ **OPTION C: HYBRID APPROACH (RECOMMENDED)**

Pick quick wins from both Week 0 validation and Week 1 improvements:

### Recommended Hybrid Plan (4-6 hours)

#### Session 1: Critical Week 1 Fixes (3h)
- [ ] ArrayUnion to Subcollection (2h) - CRITICAL scalability
- [ ] Phase 2 Completion Deadline (1h) - Prevent indefinite waits

**Why**: These are CRITICAL issues that could break the system

---

#### Session 2: Cost Optimization (2-3h)
- [ ] BigQuery Optimization (2-3h) - $60-90/month savings

**Why**: Immediate ROI, pays for itself in 1 month

---

#### Session 3: Optional Validation (1h)
- [ ] Circuit Breaker Testing (1h) - Build confidence

**Why**: Quick validation of Week 0 work

---

### Hybrid Approach Benefits
✅ Fixes critical scalability issues (ArrayUnion)
✅ Prevents indefinite waits (Phase 2 deadline)
✅ Saves money immediately (BigQuery)
✅ Validates existing work (Circuit breakers)
✅ Can be done in 2-3 sessions over 2-3 days

---

## 🎯 **MY RECOMMENDATION**

Based on everything we've accomplished and the current state:

### Start with Week 1 Critical Fixes (Option B - Days 1-2)

**Why**:
1. **ArrayUnion is CRITICAL** - You're at 800 players, approaching the 1,000 limit
2. **Phase 2 deadline prevents SLA violations**
3. **BigQuery optimization has immediate ROI** ($60-90/month = pays for itself fast)
4. **All Week 0 HIGH priority work is done** - validation is optional
5. **Comprehensive implementation guides already written**

**Timeline**:
- Wednesday (Jan 22): Day 1 - ArrayUnion + Phase 2 deadline (3h)
- Thursday (Jan 23): Day 2 - BigQuery optimization (2-3h)
- Friday (Jan 24): Day 3 - Idempotency (2-3h)
- Next week: Days 4-5 - Config + observability (4h)

**Total Impact in 5 Days**:
- 80-85% → 99.5% reliability
- -$60-90/month costs
- Unlimited scalability
- 100% idempotent

---

## 📊 **COMPARISON TABLE**

| Option | Time | Reliability | Cost Savings | Risk | Value |
|--------|------|-------------|--------------|------|-------|
| A: Week 0 Validation | 4-6h | 80-85% (no change) | $0 | Low | Medium |
| B: Week 1 Full | 12h | 80-85% → 99.5% | -$60-90/mo | Low | **VERY HIGH** |
| C: Hybrid | 6-8h | 80-85% → 99% | -$60-90/mo | Low | **HIGH** |

**Winner**: Option B (Week 1 Full) - Best ROI, comprehensive plan, critical fixes

---

## ✅ **NEXT STEPS**

If you choose **Option B (Week 1)** - RECOMMENDED:

1. [ ] Review `docs/10-week-1/WEEK-1-PLAN.md` (you've read it)
2. [ ] Start with Day 1 Morning: Phase 2 completion deadline (1-2h)
3. [ ] Continue with Day 1 Afternoon: ArrayUnion migration (2h)
4. [ ] Deploy with feature flags disabled
5. [ ] Enable flags gradually (10% → 50% → 100%)
6. [ ] Monitor for 24h between increases
7. [ ] Move to Day 2: BigQuery optimization

---

If you choose **Option A (Week 0 Validation)**:

1. [ ] Start with circuit breaker testing (60 min)
2. [ ] Optional: Pub/Sub ACK testing (45 min)
3. [ ] Skip dashboard deployment (not worth it)
4. [ ] Skip health score automation (defer)
5. [ ] Move to Week 1 afterwards

---

If you choose **Option C (Hybrid)**:

1. [ ] ArrayUnion migration (2h) - CRITICAL
2. [ ] BigQuery optimization (2-3h) - HIGH ROI
3. [ ] Phase 2 deadline (1h) - Prevents issues
4. [ ] Optional: Circuit breaker testing (1h)

---

## 🎯 **WHAT DO YOU WANT TO DO?**

I'm ready to help with any of these options. Just let me know:

**A)** Work through Week 0 validation tasks
**B)** Start Week 1 improvements (recommended)
**C)** Hybrid approach - cherry-pick critical items
**D)** Something else entirely

The comprehensive plan is ready, the implementation guides are written, and I'm ready to execute! 🚀

---

**Created**: 2026-01-20 22:45 UTC
**Status**: Ready for your decision
**Recommendation**: Option B - Week 1 improvements (start with ArrayUnion + Phase 2 deadline)
