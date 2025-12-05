# Session 35: Canary Deployment Plan - Parallelized Processors

**Date:** 2025-12-04
**Session:** 35 (Canary Deployment for Sessions 32-34 Parallelization)
**Status:** 📋 PLAN READY FOR EXECUTION
**Objective:** Deploy parallelized Priority 1 processors to Cloud Run with canary testing

---

## Executive Summary

Sessions 32-34 delivered **production-ready parallelization** for 3 Priority 1 processors:
- **PCF:** 621 players/sec (960-1200x speedup)
- **MLFS:** 12.5 players/sec (~200x speedup)
- **PGS:** 6560 records/sec (~10000x+ speedup)

**This session provides a detailed canary deployment plan** to safely roll out these changes to Cloud Run production.

---

## Deployment Strategy: Canary + Gradual Rollout

### Phase 1: Canary Testing (Single Instance)
Deploy to **ONE** Cloud Run instance first, monitor for 24-48 hours.

### Phase 2: Gradual Rollout
After canary success, deploy to all instances in waves.

### Phase 3: Full Production
All instances running parallelized code.

---

## Phase 1: Canary Deployment

### Pre-Deployment Checklist

- [ ] **Code Review**: All parallelization code merged to main branch
- [ ] **Feature Flag Verified**: `ENABLE_PLAYER_PARALLELIZATION=true` (default)
- [ ] **Rollback Plan**: `ENABLE_PLAYER_PARALLELIZATION=false` for instant serial mode
- [ ] **Monitoring Setup**:
  - [ ] Cloud Run metrics dashboard configured
  - [ ] Alert rules for CPU/memory/error rates
  - [ ] Slack notifications configured
- [ ] **Baseline Metrics Captured**:
  - [ ] Current per-date processing time (~111-115 min)
  - [ ] Current CPU utilization (~20-40%)
  - [ ] Current memory usage
  - [ ] Current error rates

### Deployment Steps

#### 1. Deploy Canary Instance

**For each processor (PCF, MLFS, PGS):**

```bash
# Deploy updated processor to Cloud Run
./bin/precompute/deploy/deploy_precompute_processors.sh player_composite_factors
./bin/precompute/deploy/deploy_precompute_processors.sh ml_feature_store

# Deploy analytics processor
./bin/analytics/deploy/deploy_analytics_processors.sh player_game_summary
```

**Deployment Configuration:**
- **Min instances:** 1 (keep one instance always warm)
- **Max instances:** 3 (limit blast radius)
- **CPU:** 4 vCPU (increased from 2 to handle parallel load)
- **Memory:** 8 GiB (increased from 4 to handle concurrent workers)
- **Timeout:** 900s (15 min - unchanged)
- **Concurrency:** 1 (one request at a time)

**Environment Variables:**
```bash
ENABLE_PLAYER_PARALLELIZATION=true  # Feature flag ON
BACKFILL_MODE=false  # Normal production mode
```

#### 2. Trigger Test Execution

**Manual Test Run (Single Date):**
```bash
# Test PCF
curl -X POST https://<cloud-run-url>/process \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_composite_factors", "date": "2025-12-04"}'

# Test MLFS
curl -X POST https://<cloud-run-url>/process \
  -H "Content-Type: application/json" \
  -d '{"processor": "ml_feature_store", "date": "2025-12-04"}'

# Test PGS
curl -X POST https://<cloud-run-url>/process \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_game_summary", "date": "2025-12-04"}'
```

#### 3. Monitor Canary (24-48 Hours)

**Key Metrics to Track:**

| Metric | Baseline (Serial) | Expected (Parallel) | Threshold | Status |
|--------|-------------------|---------------------|-----------|--------|
| **Processing Time (per date)** | ~111-115 min | ~31 sec | <60 sec | ⏱️ |
| **CPU Utilization** | 20-40% | 60-80% | <90% | 📊 |
| **Memory Usage** | 2-3 GiB | 3-4 GiB | <7 GiB | 💾 |
| **Error Rate** | <1% | <1% | <2% | ⚠️ |
| **Worker Threads** | 1 | 10 | 10 | 🧵 |
| **Players/sec (PCF)** | ~1 | 621 | >500 | 🚀 |
| **Players/sec (MLFS)** | ~0.1 | 12.5 | >10 | 🚀 |
| **Records/sec (PGS)** | ~1 | 6560 | >5000 | 🚀 |

**Monitoring Queries (Cloud Console):**

```sql
-- Processing time trend (Cloud Run Logs)
resource.type="cloud_run_revision"
jsonPayload.message=~"PRECOMPUTE_STEP Precompute processor completed in.*"
| parse "completed in ${time}s" as time
| timechart avg(time) by resource.labels.service_name

-- CPU utilization (Cloud Monitoring)
fetch cloud_run_revision
| metric 'run.googleapis.com/container/cpu/utilizations'
| group_by 1m, [value_cpu_utilizations_mean: mean(value.cpu_utilizations)]

-- Memory usage (Cloud Monitoring)
fetch cloud_run_revision
| metric 'run.googleapis.com/container/memory/utilizations'
| group_by 1m, [value_memory_utilizations_mean: mean(value.memory_utilizations)]

-- Error rate (Cloud Run Logs)
resource.type="cloud_run_revision"
severity>=ERROR
| rate 5m
```

**Slack Alerts:**
- Processing time >60s for any date
- CPU utilization >90% for >5 min
- Memory utilization >90% for >5 min
- Error rate >2% for any processor
- Any failed player/record processing

#### 4. Canary Success Criteria

**Proceed to Phase 2 if ALL criteria met:**
- ✅ Processing time: 30-40s per date (200-220x speedup vs 111-115 min)
- ✅ CPU utilization: 60-80% (healthy increase)
- ✅ Memory usage: 3-5 GiB (stable, threads share memory)
- ✅ Error rate: <1% (unchanged from baseline)
- ✅ Zero crashes or OOM kills
- ✅ Parallel mode logging visible ("Processing X players with 10 workers")
- ✅ 24-48 hours of stable operation

**Rollback if ANY criterion fails:**
- ❌ Processing time >60s
- ❌ CPU utilization >90% sustained
- ❌ Memory >7 GiB or OOM kills
- ❌ Error rate >2%
- ❌ Any crashes or timeout errors

---

## Phase 2: Gradual Rollout

### Wave 1: 25% of Instances (Day 3-4)

**Deploy to 25% of Cloud Run instances:**
- Update Cloud Run revision
- Set traffic split: 25% new revision, 75% old revision
- Monitor for 24 hours

**Success Criteria:**
- Same metrics as canary phase
- No increase in aggregate error rate
- Processing load balanced correctly

### Wave 2: 50% of Instances (Day 5-6)

**Deploy to 50% of instances:**
- Update traffic split: 50% new, 50% old
- Monitor for 24 hours

### Wave 3: 100% Rollout (Day 7)

**Full production deployment:**
- Update traffic split: 100% new revision
- Delete old revision
- Monitor for 48 hours

---

## Phase 3: Production Monitoring

### Ongoing Monitoring (Post-Deployment)

**Daily Metrics Dashboard:**
- Processing time per date (target: <60s)
- CPU/memory utilization trends
- Error rates by processor
- Throughput (players/sec, records/sec)

**Weekly Review:**
- Aggregate performance gains
- Cost analysis (CPU/memory vs time savings)
- Identify optimization opportunities

**Monthly Review:**
- Backfill completion rates
- Production readiness for Priority 2 processors
- Consider expanding parallelization

---

## Rollback Plan

### Instant Rollback (Feature Flag)

**If issues detected during canary or rollout:**

```bash
# Disable parallelization via environment variable
gcloud run services update player-composite-factors-processor \
  --set-env-vars ENABLE_PLAYER_PARALLELIZATION=false

gcloud run services update ml-feature-store-processor \
  --set-env-vars ENABLE_PLAYER_PARALLELIZATION=false

gcloud run services update player-game-summary-processor \
  --set-env-vars ENABLE_PLAYER_PARALLELIZATION=false
```

**Processors will immediately revert to serial mode** (original for-loop).

### Full Rollback (Code Revert)

**If feature flag rollback insufficient:**

```bash
# Revert to previous Cloud Run revision
gcloud run services update-traffic player-composite-factors-processor \
  --to-revisions PREVIOUS_REVISION=100

gcloud run services update-traffic ml-feature-store-processor \
  --to-revisions PREVIOUS_REVISION=100

gcloud run services update-traffic player-game-summary-processor \
  --to-revisions PREVIOUS_REVISION=100
```

---

## Cost Analysis

### Expected Cost Changes

**Compute Costs:**
- **CPU usage:** +200-300% per request (10 workers vs 1)
- **Request duration:** -99.5% (31s vs 111-115 min)
- **Net compute cost:** -98% per date (massive savings)

**Memory Costs:**
- **Memory usage:** +25-50% per request (threads share memory)
- **Request duration:** -99.5%
- **Net memory cost:** -98% per date

**Overall:**
- **Cost per date:** -98% (31s vs 115 min of compute)
- **Backfill time:** Hours instead of days/weeks
- **Cloud Run costs:** Significantly lower due to shorter execution time

---

## Success Metrics (30 Days Post-Deployment)

### Performance Targets

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| **Per-Date Processing** | 111-115 min | <60 sec | Cloud Run logs |
| **Backfill Speed** | Days/weeks | Hours | Actual backfill runs |
| **Error Rate** | <1% | <1% | Aggregate error logs |
| **CPU Efficiency** | 20-40% | 60-80% | Cloud Monitoring |
| **Cost per Date** | $X | ~$0.02X | GCP billing |

### Business Impact

- **Faster Data Freshness:** Phase 4 precompute data available within minutes instead of hours
- **Improved Prediction Quality:** More timely features for Phase 5 predictions
- **Reduced Backfill Overhead:** Historical data gaps filled in hours, not days
- **Better Developer Experience:** Faster iteration on model improvements

---

## Risk Assessment

### Low Risk
- **Feature flag works:** ✅ Tested in Sessions 32-34
- **Thread safety proven:** ✅ Zero errors in 369 players (PCF), 389 players (MLFS), 241 records (PGS)
- **Rollback available:** ✅ Instant via env var, full via revision rollback

### Medium Risk
- **Cloud Run resource limits:** May need CPU/memory adjustments
  - **Mitigation:** Monitor closely during canary, adjust limits if needed
- **BigQuery quota:** 10 concurrent workers may hit rate limits
  - **Mitigation:** Already tested locally, BQ handles concurrent queries well

### High Risk
- **Unforeseen production edge cases:** Different data patterns than test dates
  - **Mitigation:** Canary testing with recent production date (2025-12-04)
  - **Mitigation:** Gradual rollout catches issues before full deployment

---

## Timeline

### Week 1: Canary Testing
- **Day 1:** Deploy canary instance, run test executions
- **Day 2-3:** Monitor canary metrics (24-48 hours)
- **Day 3:** Review canary results, decision to proceed

### Week 2: Gradual Rollout
- **Day 4:** Wave 1 (25% rollout), monitor 24h
- **Day 5:** Wave 2 (50% rollout), monitor 24h
- **Day 6-7:** Wave 3 (100% rollout), monitor 48h

### Week 3+: Production Monitoring
- **Ongoing:** Daily metrics review
- **Week 3:** Weekly performance review
- **Month 1:** Monthly cost/benefit analysis

---

## Next Steps

### Immediate Actions (Session 35)
1. **Review this plan** with stakeholders
2. **Capture baseline metrics** from current production
3. **Set up monitoring dashboards** and alert rules
4. **Deploy canary instance** for PCF processor first (highest impact)

### Follow-Up Actions (Session 36+)
5. Monitor canary for 24-48 hours
6. If successful, deploy MLFS and PGS canaries
7. After all canaries pass, begin gradual rollout
8. Document production performance vs predictions

---

## Priority 2 Processors (Future Work)

After Priority 1 success, consider parallelizing:
- **Player Daily Cache (PDC)** - Similar pattern to PCF/MLFS
- **Verify PSZA/TDZA** - Already have parallelization, need runtime testing
- **Other Analytics Processors** - UPGC, UTGC (already parallelized), TDGS, TOGS

**Estimated Impact:** Additional 50-100x speedup for remaining processors

---

## References

- **Session 31 Plan:** `docs/09-handoff/2025-12-04-SESSION31-PARALLELIZE-ALL-PROCESSORS.md`
- **Session 32 Implementation:** `docs/09-handoff/2025-12-04-SESSION32-PARALLELIZATION-HANDOFF.md`
- **Session 33 Verification:** `docs/09-handoff/2025-12-04-SESSION33-VERIFICATION-HANDOFF.md`
- **Session 34 Runtime Testing:** `docs/09-handoff/2025-12-04-SESSION34-RUNTIME-TESTING.md`
- **Cloud Run Best Practices:** https://cloud.google.com/run/docs/best-practices
- **Feature Flags Pattern:** https://martinfowler.com/articles/feature-toggles.html

---

**Last Updated:** 2025-12-04 (Session 35)
**Status:** 📋 READY FOR CANARY DEPLOYMENT
**Next Session:** Execute canary deployment (Day 1)
