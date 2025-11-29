# Phase 4→5 Integration Project

**Status:** Ready for Implementation  
**Created:** 2025-11-28  
**Timeline:** 1-2 weeks to production  
**Effort:** ~10-12 hours development + testing

---

## Quick Links

- **[ACTION PLAN](./ACTION-PLAN.md)** ← Start here for implementation steps
- **[IMPLEMENTATION](./IMPLEMENTATION.md)** - Detailed code changes
- **[OPERATIONS](./OPERATIONS.md)** - Manual intervention procedures  
- **[MONITORING](./MONITORING.md)** - Queries and dashboards
- **[TESTING](./TESTING.md)** - Test plan and validation

---

## Problem Statement

**Current State:**
- Phase 4 (ml_feature_store_v2) completes ~12:30 AM PT
- Phase 5 (predictions) waits until 6:00 AM PT to run
- **Result:** 5.5 hours of wasted time, predictions available at 9:00 AM ET

**Issues:**
1. ❌ No event-driven trigger (Phase 4 doesn't notify Phase 5)
2. ❌ No Phase 4 validation (Phase 5 doesn't check if data is ready)
3. ❌ No alerting (failures discovered hours later)
4. ❌ No retry mechanism (incomplete batches stay incomplete)

---

## Solution: Hybrid Event-Driven + Backup Architecture

```
Phase 4 completes (12:30 AM PT)
    ↓
Publishes Pub/Sub event  
    ↓
Phase 5 triggers IMMEDIATELY (12:30 AM PT)  ← PRIMARY PATH (6+ hours faster!)
    ↓
Predictions ready by 12:33 AM PT (6:33 AM ET)


6:00 AM PT - Scheduler backup (if Pub/Sub missed)    ← SAFETY NET
6:15 AM PT - Retry #1 (catch stragglers)              ← INCREMENTAL
6:30 AM PT - Retry #2 (final retry)                   ← INCREMENTAL
7:00 AM PT - Status check (alert if <90% coverage)    ← SLA MONITORING
```

---

## Key Benefits

| Benefit | Impact |
|---------|--------|
| **6+ hours faster** | Predictions available at 12:33 AM PT (6:33 AM ET) instead of 6:03 AM PT (9:03 AM ET) |
| **Automatic recovery** | If Phase 4 late, scheduler backup + retries handle it |
| **Comprehensive alerting** | Know immediately when Phase 4 fails |
| **Graceful degradation** | Process available players, retry for rest |
| **Foundation for real-time** | Same architecture enables future injury updates |

---

## Architecture Overview

### Components Added/Modified

**Phase 4 (ml_feature_store_processor.py):**
- ✅ Add `_publish_phase4_completion()` method
- Publishes Pub/Sub event when processing completes
- Non-blocking (fails gracefully if Pub/Sub unavailable)

**Phase 5 Coordinator (coordinator.py):**
- ✅ Add `/trigger` endpoint (primary Pub/Sub path)
- ✅ Add `/retry` endpoint (incremental processing)
- ✅ Update `/start` endpoint (add validation + 30-min wait)
- ✅ Add `_validate_phase4_ready()` helper
- ✅ Add `_get_batch_status()` deduplication
- ✅ Add `_wait_for_phase4()` polling logic

**Infrastructure:**
- ✅ Create Pub/Sub topic: `nba-phase4-precompute-complete`
- ✅ Create push subscription to `/trigger`
- ✅ Update Cloud Scheduler (4 jobs total)

### Data Flow

```
┌──────────────────────────────────────────────────┐
│ Phase 4: ml_feature_store_v2                     │
│  - Processes 450 players                         │
│  - Sets is_production_ready flag                 │
│  - Publishes completion event (NEW)              │
└───────────────────┬──────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────┐
│ Pub/Sub: nba-phase4-precompute-complete         │
│  Message: {                                      │
│    game_date, players_ready, players_total       │
│  }                                               │
└───────────────────┬──────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────┐
│ Phase 5 Coordinator /trigger (PRIMARY)           │
│  1. Check deduplication (already ran?)           │
│  2. Validate Phase 4 (enough players ready?)     │
│  3. Query Phase 3 for player list                │
│  4. Filter already-processed players             │
│  5. Publish prediction requests                  │
└───────────────────┬──────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────┐
│ Phase 5 Workers (450 concurrent)                 │
│  - Query Phase 4 for each player                 │
│  - Run 5 prediction systems                      │
│  - Write to BigQuery                             │
└──────────────────────────────────────────────────┘


Cloud Scheduler (BACKUP PATH):
  6:00 AM PT → /start (validate + 30-min wait if needed)
  6:15 AM PT → /retry (incremental)
  6:30 AM PT → /retry (incremental)
  7:00 AM PT → /status (alert if <90%)
```

---

## Critical Decision: Timezone & SLA

⚠️ **MUST RESOLVE BEFORE IMPLEMENTATION**

**Current Inconsistency:**
- Deployment script: 6:00 AM **PT** (Pacific Time)
- Documentation: 7:00 AM **ET** (Eastern Time) SLA
- These conflict: 6:00 AM PT = 9:00 AM ET

**Choose One:**

### Option A: Realistic SLA (Recommended)
- **SLA:** Predictions ready by **10:00 AM ET / 7:00 AM PT**  
- Matches current scheduler
- No code changes needed
- **Action:** Update all docs to reflect this SLA

### Option B: Aggressive SLA  
- **SLA:** Predictions ready by **7:00 AM ET / 4:00 AM PT**
- Requires moving scheduler to 3:00 AM PT
- Higher risk if Phase 4 late
- **Action:** Change all scheduler times

**Recommendation:** Option A (realistic and safe)

---

## Implementation Summary

### Phase 1: Core Integration (~6-8 hours)
- Add validation helpers to coordinator
- Add `/trigger` endpoint for Pub/Sub
- Update `/start` endpoint with Phase 4 checks
- Add Pub/Sub publishing to Phase 4

### Phase 2: Infrastructure (~2 hours)
- Create Pub/Sub topic + subscription
- Deploy Cloud Scheduler jobs
- Deploy updated services

### Phase 3: Retry & Alerting (~4 hours)
- Add `/retry` endpoint
- Integrate alert system
- Configure Email + Slack notifications

### Phase 4: Testing (~2-3 days)
- Unit tests + integration tests
- Staging deployment (3-5 days monitoring)
- Production deployment

**Total:** 10-12 hours development + 3-5 days validation = **1-2 weeks**

---

## Key Design Decisions

### 1. Hybrid Trigger (Not Pure Event-Driven)
**Why:** Reliability over speed. If Pub/Sub fails, scheduler backup ensures predictions still run.

### 2. Deduplication via Batch Status Check
**Why:** Prevents double-processing if both Pub/Sub and scheduler trigger.

### 3. 30-Minute Wait Timeout (Not 15)
**Why:** Gives Phase 4 enough time to complete if running slow.

### 4. Percentage-Based Alert Threshold (5% OR 20 players)
**Why:** Scales better than fixed threshold as player count varies.

### 5. Multiple Retry Times (6:15, 6:30 AM PT)
**Why:** Multiple chances to catch stragglers before SLA deadline.

### 6. Process Partial Data (Not All-or-Nothing)
**Why:** Better UX for bettors - some predictions better than none.

---

## Rollback Strategy

**If event-driven path fails:**
```bash
gcloud pubsub subscriptions delete nba-phase5-trigger-sub
# Result: Falls back to scheduler only (original behavior)
```

**If completely broken:**
```bash
gcloud run services update-traffic prediction-coordinator \
    --to-revisions=prediction-coordinator-00003=100
# Result: Previous version restored
```

---

## Success Metrics

### Day 1 (After First Run)
- ✅ Predictions generated automatically
- ✅ Zero critical alerts
- ✅ Latency < 10 minutes

### Week 1  
- ✅ 7 consecutive successful runs
- ✅ Average latency < 5 minutes (event-driven working)
- ✅ Completion rate > 95%

### Week 2
- ✅ Metrics baseline established
- ✅ Dashboards operational  
- ✅ Ready for sign-off

---

## Cost Impact

| Component | Monthly Cost |
|-----------|--------------|
| Pub/Sub | ~$0.40 |
| Cloud Scheduler (4 jobs) | ~$0.40 |
| Additional Cloud Run | ~$2-5 |
| BigQuery queries | ~$1-2 |
| **Total** | **~$5/month** |

**ROI:** Negligible cost for major operational benefit

---

## Next Steps

1. ✅ Read ACTION-PLAN.md for detailed implementation steps
2. ⏳ **CRITICAL:** Make timezone SLA decision
3. ⏳ Review IMPLEMENTATION.md for code changes
4. ⏳ Review OPERATIONS.md for runbook procedures
5. ⏳ Start Phase 1: Core Integration

---

## Related Documentation

- **Original Analysis:** `/docs/10-prompts/2025-11-28-phase4-to-phase5-integration-review.md`
- **Phase 4 Docs:** `/docs/03-phases/phase4-precompute/`
- **Phase 5 Docs:** `/docs/03-phases/phase5-predictions/`
- **Pipeline Architecture:** `/docs/01-architecture/pipeline-design.md`

---

**Project Status:** Ready for Implementation  
**Last Updated:** 2025-11-28  
**Contact:** @engineering-team
