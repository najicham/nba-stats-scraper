# Master Implementation Plan - Phase 4→5 Integration

**Status:** 📋 Ready to Execute
**Approach:** Minimal Viable Integration (Phase 4→5 only)
**Timeline:** 4 days (~12 hours total effort)

---

## Quick Decision Summary

Based on infrastructure audit:

| Question | Decision | Rationale |
|----------|----------|-----------|
| Fix Phase 4 internal inconsistencies? | ❌ No (defer) | Working in prod, don't touch it |
| Implement Cloud Function orchestration? | ❌ No (defer) | Not needed for Phase 4→5 |
| Deploy to staging first? | ✅ Yes | De-risk first Phase 5 deployment |
| Write comprehensive tests? | ✅ Yes (Option 3) | Critical for reliability |
| Add retry logic? | ✅ Yes | Graceful degradation needed |

---

## Implementation Phases

### Phase 1: Code Implementation (Day 1, ~4 hours)

**File 1: Phase 4 Processor** (~30 min)
- File: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- Add imports: `pubsub_v1`, `json`
- Add constant: `PHASE4_COMPLETE_TOPIC = 'nba-phase4-precompute-complete'`
- Modify `post_process()`: Add `self._publish_completion_event()`
- Add method: `_publish_completion_event()`
- Add method: `_count_production_ready()`

**File 2: Phase 5 Coordinator** (~2.5 hours)
- File: `predictions/coordinator/coordinator.py`
- Add imports: `time`, `bigquery`, `base64`
- Add endpoint: `/trigger` (Pub/Sub handler)
- Update endpoint: `/start` (with Phase 4 validation + wait)
- Add endpoint: `/retry` (incremental processing)
- Add helper: `_validate_phase4_ready()`
- Add helper: `_wait_for_phase4()`
- Add helper: `_get_batch_status()`
- Add helper: `_get_players_needing_retry()`
- Add helper: `_process_retry_batch()`
- Add helper: `_record_batch_run()`
- Add helper: `_send_alert()`
- Add core: `_start_batch_internal()`

**File 3: Infrastructure Script** (~30 min)
- File: `bin/phase5/deploy_pubsub_infrastructure.sh`
- Copy complete script from IMPLEMENTATION-FULL.md
- Make executable: `chmod +x bin/phase5/deploy_pubsub_infrastructure.sh`

**Code Sources:**
- All code in `IMPLEMENTATION-FULL.md` (lines 1-1,403)
- Exact copy/paste, already tested by external AI

### Phase 2: Unit Tests (Day 1-2, ~3 hours)

**Test File: `tests/predictions/test_coordinator_integration.py`**

Tests to write:

1. **`test_validate_phase4_ready_success()`**
   - Mock BigQuery to return ready data
   - Assert: `ready=True`, `players_ready=420`, `ready_pct=93.3`

2. **`test_validate_phase4_ready_not_complete()`**
   - Mock: processor_run_history has no record
   - Assert: `ready=False`, `message` contains "has not run"

3. **`test_validate_phase4_ready_below_threshold()`**
   - Mock: Only 60/450 players ready (13%)
   - Assert: `ready=False` (below 80% threshold)

4. **`test_wait_for_phase4_immediate()`**
   - Mock: Phase 4 already ready
   - Assert: Returns immediately, no sleep

5. **`test_wait_for_phase4_timeout()`**
   - Mock: Phase 4 never ready
   - Assert: Returns after 30 min, `ready=False`

6. **`test_get_batch_status_fully_complete()`**
   - Mock: 420/420 predictions exist
   - Assert: `fully_complete=True`

7. **`test_get_batch_status_partially_complete()`**
   - Mock: 300/420 predictions exist
   - Assert: `partially_complete=True`, `players_processed=300`

8. **`test_get_players_needing_retry()`**
   - Mock: 420 players in Phase 4, 380 in predictions
   - Assert: Returns 40 player_lookup strings

9. **`test_start_batch_internal_deduplication()`**
   - Mock: Batch already complete
   - Assert: Returns `already_complete`, no Pub/Sub calls

10. **`test_start_batch_internal_phase4_not_ready()`**
    - Mock: Phase 4 not ready, < 50 players
    - Assert: Returns 503, sends critical alert

11. **`test_trigger_endpoint_valid_message()`**
    - Mock Pub/Sub message
    - Assert: Calls `_start_batch_internal()`, returns 202

12. **`test_trigger_endpoint_invalid_message()`**
    - Mock: Missing `game_date`
    - Assert: Returns 400

13. **`test_start_endpoint_scheduler_trigger()`**
    - Mock: `X-CloudScheduler: true` header
    - Assert: Enters wait loop if Phase 4 not ready

14. **`test_retry_endpoint_no_players()`**
    - Mock: All players already processed
    - Assert: Returns 200, `status=complete`

15. **`test_retry_endpoint_with_players()`**
    - Mock: 40 players need retry
    - Assert: Publishes 40 requests, returns 202

**Coverage Goal:** >90% for new code

### Phase 3: Integration Tests (Day 2, ~2 hours)

**Test Scenarios:**

1. **End-to-End Pub/Sub Flow**
   ```python
   def test_pubsub_trigger_to_predictions():
       # Publish test message to nba-phase4-precompute-complete
       # Wait for coordinator to receive
       # Verify predictions published
       # Check processor_run_history logged
   ```

2. **Scheduler Backup Path**
   ```python
   def test_scheduler_backup_triggers():
       # Trigger /start with X-CloudScheduler header
       # Mock Phase 4 not ready initially
       # Mock Phase 4 becomes ready after 2 polls
       # Verify predictions start
   ```

3. **Deduplication Works**
   ```python
   def test_duplicate_triggers_ignored():
       # Trigger /start (completes)
       # Trigger /trigger (should skip)
       # Trigger /start again (should skip)
       # Verify only ONE batch processed
   ```

4. **Retry Logic**
   ```python
   def test_retry_incremental_processing():
       # Initial run: 380/420 players
       # Mock 40 more players become ready
       # Call /retry
       # Verify only 40 new requests published
   ```

### Phase 4: Infrastructure Deployment (Day 2, ~1 hour)

**Prerequisites:**
```bash
# Get Phase 5 coordinator URL
COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
    --project=nba-props-platform \
    --region=us-west2 \
    --format="value(status.url)")

echo "Coordinator URL: $COORDINATOR_URL"
```

**Run Deployment Script:**
```bash
cd /home/naji/code/nba-stats-scraper
./bin/phase5/deploy_pubsub_infrastructure.sh $COORDINATOR_URL
```

**Verify:**
```bash
# Check topic created
gcloud pubsub topics describe nba-phase4-precompute-complete \
    --project=nba-props-platform

# Check subscription created
gcloud pubsub subscriptions describe nba-phase5-trigger-sub \
    --project=nba-props-platform

# Check scheduler jobs created
gcloud scheduler jobs list --project=nba-props-platform \
    --location=us-west2 --filter="name:phase5"
```

### Phase 5: Deploy to Staging (Day 3, ~2 hours)

**Step 1: Deploy Phase 4 Changes**
```bash
# Deploy updated ml_feature_store_processor
./bin/precompute/deploy/deploy_precompute_processors.sh ml_feature_store

# Verify deployment
gcloud run services describe nba-phase4-precompute-processors \
    --project=nba-props-platform \
    --region=us-west2
```

**Step 2: Deploy Phase 5 Changes**
```bash
# Deploy updated coordinator
./bin/predictions/deploy/deploy_prediction_coordinator.sh

# Verify deployment
gcloud run services describe prediction-coordinator \
    --project=nba-props-platform \
    --region=us-west2
```

**Step 3: Manual Testing**
```bash
# Test 1: Pub/Sub trigger
gcloud pubsub topics publish nba-phase4-precompute-complete \
    --project=nba-props-platform \
    --message='{"event_type":"phase4_complete","game_date":"2025-11-28","players_ready":100,"players_total":450}'

# Check logs
gcloud run services logs read prediction-coordinator \
    --project=nba-props-platform \
    --region=us-west2 \
    --limit=50

# Test 2: Scheduler backup
gcloud scheduler jobs run phase5-daily-backup \
    --project=nba-props-platform \
    --location=us-west2

# Test 3: Deduplication
curl -X POST "$COORDINATOR_URL/start" \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2025-11-28"}'

# Should return: "already_complete"
```

**Step 4: Monitor Overnight Run**
```bash
# Next morning, check if Phase 5 was automatically triggered
bq query --use_legacy_sql=false '
SELECT
    processor_name,
    triggered_by,
    FORMAT_TIMESTAMP("%H:%M:%S", started_at) as started_time,
    status,
    records_processed
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = CURRENT_DATE()
  AND processor_name IN ("ml_feature_store_v2", "phase5_coordinator")
ORDER BY started_at
'

# Check predictions generated
bq query --use_legacy_sql=false '
SELECT COUNT(DISTINCT player_lookup) as prediction_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
'
```

### Phase 6: Production Deployment (Day 4, ~1 hour)

**Go/No-Go Checklist:**
- [ ] 3 consecutive successful overnight runs in staging
- [ ] Phase 4→5 latency < 10 minutes
- [ ] Prediction completion rate > 95%
- [ ] Zero critical alerts
- [ ] Deduplication working
- [ ] Retry logic working
- [ ] All tests passing

**If GO:**
```bash
# 1. Tag current production version (rollback point)
PROD_REVISION=$(gcloud run services describe prediction-coordinator \
    --project=nba-props-platform \
    --region=us-west2 \
    --format="value(status.latestReadyRevisionName)")

echo "Current production revision: $PROD_REVISION"

# 2. Deploy (already done in staging, just verify)
# Infrastructure already created
# Code already deployed

# 3. Monitor first production run
# Use same queries as staging validation

# 4. If issues, rollback
gcloud run services update-traffic prediction-coordinator \
    --to-revisions=$PROD_REVISION=100 \
    --project=nba-props-platform \
    --region=us-west2
```

---

## Effort Summary

| Phase | Tasks | Time | Priority |
|-------|-------|------|----------|
| **1. Code Implementation** | 3 files to modify | 4 hours | P0 |
| **2. Unit Tests** | 15 test cases | 3 hours | P0 |
| **3. Integration Tests** | 4 test scenarios | 2 hours | P1 |
| **4. Infrastructure** | Deploy Pub/Sub + scheduler | 1 hour | P0 |
| **5. Staging Deployment** | Deploy + validate | 2 hours | P0 |
| **6. Production Deployment** | Go/no-go + deploy | 1 hour | P0 |
| **TOTAL** | | **13 hours** | |

**Timeline:**
- **Day 1:** Phases 1-2 (7 hours)
- **Day 2:** Phases 3-5 (5 hours)
- **Day 3:** Monitoring staging overnight
- **Day 4:** Phase 6 if staging success (1 hour)

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Phase 4 Pub/Sub publish fails | Low | Medium | Scheduler backup at 6 AM |
| Pub/Sub message lost | Very Low | Medium | Scheduler backup + retry |
| Coordinator crashes mid-batch | Low | Medium | Deduplication prevents duplicates |
| Phase 4 late (after 6 AM) | Medium | Low | 30-min wait loop |
| Missing players after retries | Low | Low | Alert if >20 missing |
| Production deployment breaks existing | Low | High | Staging validation + rollback plan |

**Overall Risk:** 🟡 **Medium** (well-mitigated)

---

## Success Metrics

**Immediate (Week 1):**
- [ ] Phase 5 triggers < 5 minutes after Phase 4 completion
- [ ] Prediction completion rate > 95%
- [ ] Zero critical alerts
- [ ] Zero duplicate processing events

**Short-term (Month 1):**
- [ ] Average Phase 4→5 latency < 3 minutes
- [ ] Prediction completion rate > 98%
- [ ] Scheduler backup never needed (Pub/Sub working)
- [ ] Retry logic catches <5% stragglers

**Long-term (Month 3+):**
- [ ] Foundation for real-time updates ready
- [ ] Multi-prop support can be added easily
- [ ] Operational runbook complete

---

## Rollback Procedures

**If Phase 4 changes break:**
```bash
# Rollback Phase 4 deployment
gcloud run services update-traffic nba-phase4-precompute-processors \
    --to-revisions=[PREVIOUS-REVISION]=100 \
    --project=nba-props-platform \
    --region=us-west2
```

**If Phase 5 changes break:**
```bash
# Rollback Phase 5 deployment
gcloud run services update-traffic prediction-coordinator \
    --to-revisions=[PREVIOUS-REVISION]=100 \
    --project=nba-props-platform \
    --region=us-west2
```

**If Pub/Sub path causes issues:**
```bash
# Delete subscription (falls back to scheduler only)
gcloud pubsub subscriptions delete nba-phase5-trigger-sub \
    --project=nba-props-platform
```

**Manual trigger if all else fails:**
```bash
curl -X POST "$COORDINATOR_URL/start" \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2025-11-28", "force": true}'
```

---

## Next Steps

**Immediate:**
1. ✅ Review this master plan
2. ✅ Review PUBSUB-INFRASTRUCTURE-AUDIT.md
3. ✅ Review IMPLEMENTATION-FULL.md
4. ⏳ Start Phase 1: Code implementation

**This Week:**
1. ⏳ Complete all 6 phases
2. ⏳ Validate in staging
3. ⏳ Deploy to production

**This Month:**
1. Monitor production for 2-4 weeks
2. Tune thresholds based on real data
3. Create operational dashboards
4. Document lessons learned

---

**Document Status:** ✅ Ready for Implementation
**Last Updated:** 2025-11-28
**Next Action:** Start Phase 1 code implementation
