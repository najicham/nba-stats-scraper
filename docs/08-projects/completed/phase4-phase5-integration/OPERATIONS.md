# Phase 4→5 Integration - Operations Runbook

**For complete operational procedures, see full spec Section 8 "Manual Intervention Procedures"**

This document provides quick-reference troubleshooting steps.

---

## Common Scenarios

### Scenario 1: Phase 4 Never Completes

**Symptoms:**
- 6:00 AM alert: "Phase 4 not ready after 30 minutes"
- No predictions generated

**Quick Check:**
```sql
SELECT processor_name, status, processed_at
FROM `nba_reference.processor_run_history`
WHERE data_date = CURRENT_DATE()
  AND processor_name = 'ml_feature_store_v2'
ORDER BY processed_at DESC;
```

**Resolution:**
```bash
# Manually trigger Phase 4
curl -X POST "https://ml-feature-store-HASH.run.app/process" \
    -H "Content-Type: application/json" \
    -d '{"analysis_date": "2025-11-28"}'

# Wait for completion, then trigger Phase 5
curl -X POST "https://phase5-coordinator-HASH.run.app/start" \
    -d '{"game_date": "2025-11-28", "force": true}'
```

---

### Scenario 2: Specific Players Missing

**Symptoms:**
- Batch shows 440/450 complete
- 10 players never get predictions

**Investigation:**
```sql
SELECT player_lookup, is_production_ready, 
       circuit_breaker_active, data_quality_issues
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
  AND player_lookup NOT IN (
    SELECT DISTINCT player_lookup 
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = CURRENT_DATE()
  );
```

**Resolution:**
- Check if `is_production_ready = FALSE` (expected for new players/injured)
- Check if circuit breaker tripped (reset if needed)
- Retry: `curl -X POST "[coordinator]/retry"`

---

### Scenario 3: Pub/Sub Messages Lost

**Symptoms:**
- Phase 4 completed hours ago
- Phase 5 never triggered

**Check:**
```bash
# Check dead letter queue
gcloud pubsub subscriptions pull nba-dlq-sub --limit=10 --auto-ack

# Check Phase 4 logs for publish errors
gcloud logging read "resource.labels.service_name=ml-feature-store AND textPayload:publish" --limit=20
```

**Resolution:**
```bash
# Manually trigger Phase 5 (backup path still works)
curl -X POST "https://phase5-coordinator-HASH.run.app/start" \
    -d '{"game_date": "2025-11-28"}'
```

---

## Rollback Procedures

### Rollback Event-Driven Path
```bash
gcloud pubsub subscriptions delete nba-phase5-trigger-sub
# Result: Falls back to 6 AM scheduler only
```

### Rollback Coordinator
```bash
gcloud run services update-traffic prediction-coordinator \
    --to-revisions=prediction-coordinator-00003=100 \
    --region=us-west2
```

---

**For complete procedures, see full spec Section 8.**
