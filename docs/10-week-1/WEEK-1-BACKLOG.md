# Week 1 Backlog - NBA Stats Pipeline

**Created:** January 20, 2026  
**Status:** Ready for Week 1  
**Priority:** Items ordered by impact/effort ratio

---

## 🎯 Week 1 Goals

1. Fix orchestration reliability (40% → 95%+)
2. Improve observability & monitoring
3. Add proper integration testing
4. Validate Quick Win #1 results

---

## 🔥 Priority 1: Critical Reliability Fixes

### 1.1 Add Workflow Execution Timeouts (2 hours, P0)

**Problem:** Workflows can hang indefinitely → orphaned decisions

**Solution:** Per-workflow 120s timeout with signal.alarm()

**Impact:** Prevents 100% of timeout-based orphans

---

### 1.2 Implement Parallel Workflow Execution (3 hours, P0)

**Problem:** Sequential execution = 3x slower + timeout risk

**Solution:** ThreadPoolExecutor with max_workers=3

**Impact:** 3x faster (45s → 15s), reduces timeout risk 90%

---

### 1.3 Add Retry Logic for Orphaned Decisions (2 hours, P1)

**Problem:** 2 orphaned decisions today (never retried)

**Solution:** New endpoint checks every 15 min, retries old unexecuted RUN decisions

**Impact:** Auto-recovery from timeouts

---

## 🔍 Priority 2: Observability & Monitoring

### 2.1 Improve Health Check Endpoints (4 hours, P1)

**Problem:** Worker/Phase1 returned 200 but functionality broken

**Solution:** Integration tests in /health (test imports, BigQuery, actual operations)

**Impact:** Catch 90% of bugs before they reach production

---

### 2.2 Add Workflow Failure Alerting (3 hours, P1)

**Problem:** Silent failures, discovered 30+ min later

**Solution:** Cloud Function monitors every 15 min, alerts on failures/orphans

**Impact:** <5 min detection time

---

### 2.3 Add Execution Progress Logging (1 hour, P2)

**Solution:** Log at 25%, 50%, 75%, 100% completion

**Impact:** Better debugging for hung workflows

---

## 🧪 Priority 3: Testing & Quality

### 3.1 Create Integration Test Suite (8 hours, P1)

**Tests:**
- Worker prediction end-to-end
- Phase 1 scraper execution
- Phase 3 analytics processing
- Full pipeline validation

**Impact:** Catch bugs in CI, not production

---

### 3.2 Add Dependency Audit Process (2 hours, P2)

**Solution:** Script checks for non-optional dev dependencies (dotenv, ipdb, pytest)

**Run:** Before every deployment

**Impact:** Prevents dotenv-style cascading failures

---

## 📊 Priority 4: Quick Win #1 Validation

### 4.1 Validate Phase 3 Weight Boost (2 hours, P0) **JAN 21 MORNING**

**Expected:** +10-15% quality score improvement (75 → 87 weight)

**Script:** `./scripts/validate_quick_win_1.sh`

---

### 4.2 Update PR with Results (1 hour, P0)

After validation: Update PR, mark ready, merge

---

## 🚀 Priority 5: Nice-to-Haves

### 5.1 BigQuery Cost Analysis (2 hours, P3)
### 5.2 Monitoring Dashboard (8 hours, P3)
### 5.3 Circuit Breaker Pattern (4 hours, P3)

---

## 📋 Week 1 Schedule

**Mon:** Validate Quick Win #1 (P0), Update PR (P0), Add timeouts (P0)  
**Tue:** Parallel execution (P0), Better health checks (P1)  
**Wed:** Retry logic (P1), Failure alerting (P1)  
**Thu:** Integration tests (P1)  
**Fri:** Dependency audit (P2), Buffer

---

## 📈 Success Metrics

| Metric | Week 0 | Week 1 Target |
|--------|--------|---------------|
| Workflow Reliability | 40% | 95%+ |
| Orphaned Decisions | 2 | 0 |
| Health Check Accuracy | 50% | 95%+ |
| Avg Execution Time | 45s | 15s |
| Test Coverage | 0% | 60%+ |

---

## ✅ Week 1 Done When:

- [ ] All P0 items complete
- [ ] All P1 items complete  
- [ ] Quick Win #1 validated and merged
- [ ] No orphaned decisions in 48h
- [ ] Alerting functional

---

**See full details:** docs/09-handoff/2026-01-20-ORCHESTRATION-INVESTIGATION.md
