# Feature Flags Configuration - Week 1-4

**Purpose:** Safe, gradual rollout of all improvements
**Strategy:** Feature flags for all behavioral changes
**Rollout:** 0% → 10% → 50% → 100% over 3-4 days

---

## 🎯 Feature Flag Philosophy

### Why Feature Flags?
1. **Safety:** Instant rollback without code deployment
2. **Gradual Rollout:** Test with small percentage first
3. **A/B Testing:** Compare old vs new behavior
4. **Confidence:** Monitor impact before full rollout
5. **Emergency:** Disable instantly if issues arise

### When to Use
- ✅ All behavioral changes
- ✅ New code paths
- ✅ Configuration changes that affect logic
- ❌ Pure bug fixes (deploy immediately)
- ❌ Documentation changes

---

## 📋 Week 1 Feature Flags

### 1. Phase 2 Completion Deadline
```python
# Environment Variables
ENABLE_PHASE2_COMPLETION_DEADLINE = bool(os.getenv('ENABLE_PHASE2_COMPLETION_DEADLINE', 'false').lower() == 'true')
PHASE2_COMPLETION_TIMEOUT_MINUTES = int(os.getenv('PHASE2_COMPLETION_TIMEOUT_MINUTES', '30'))

# Usage in Code
if ENABLE_PHASE2_COMPLETION_DEADLINE:
    if wait_minutes > PHASE2_COMPLETION_TIMEOUT_MINUTES:
        # New behavior: Trigger with partial data
        trigger_phase3_with_partial_data()
else:
    # Old behavior: Wait indefinitely
    continue_waiting()
```

**Deployment Command:**
```bash
gcloud run services update nba-phase2-to-phase3 \
  --update-env-vars ENABLE_PHASE2_COMPLETION_DEADLINE=true,PHASE2_COMPLETION_TIMEOUT_MINUTES=30
```

---

### 2. Subcollection Completions (Dual-Write)
```python
# Environment Variables
ENABLE_SUBCOLLECTION_COMPLETIONS = bool(os.getenv('ENABLE_SUBCOLLECTION_COMPLETIONS', 'false').lower() == 'true')
DUAL_WRITE_MODE = bool(os.getenv('DUAL_WRITE_MODE', 'true').lower() == 'true')
USE_SUBCOLLECTION_READS = bool(os.getenv('USE_SUBCOLLECTION_READS', 'false').lower() == 'true')

# Usage in Code (Dual-Write Pattern)
def record_completion(batch_id, player_id):
    if ENABLE_SUBCOLLECTION_COMPLETIONS:
        if DUAL_WRITE_MODE:
            # Write to both old and new
            write_to_array(batch_id, player_id)  # Old way
            write_to_subcollection(batch_id, player_id)  # New way
        else:
            # Write only to new
            write_to_subcollection(batch_id, player_id)
    else:
        # Old behavior only
        write_to_array(batch_id, player_id)

def get_completed_players(batch_id):
    if ENABLE_SUBCOLLECTION_COMPLETIONS and USE_SUBCOLLECTION_READS:
        return read_from_subcollection(batch_id)
    else:
        return read_from_array(batch_id)
```

**Rollout Phases:**
```bash
# Phase 1: Dual-write enabled, reads from old
gcloud run services update prediction-coordinator \
  --update-env-vars ENABLE_SUBCOLLECTION_COMPLETIONS=true,DUAL_WRITE_MODE=true,USE_SUBCOLLECTION_READS=false

# Phase 2: Validate both structures match (24h monitoring)
# Compare array vs subcollection counts

# Phase 3: Switch reads to new structure
gcloud run services update prediction-coordinator \
  --update-env-vars USE_SUBCOLLECTION_READS=true

# Phase 4: Stop writing to old structure (after 7 days validation)
gcloud run services update prediction-coordinator \
  --update-env-vars DUAL_WRITE_MODE=false

# Phase 5: Delete old array field (manual Firestore cleanup)
```

---

### 3. BigQuery Query Caching
```python
# Environment Variables
ENABLE_QUERY_CACHING = bool(os.getenv('ENABLE_QUERY_CACHING', 'false').lower() == 'true')
QUERY_CACHE_TTL_SECONDS = int(os.getenv('QUERY_CACHE_TTL_SECONDS', '3600'))

# Usage in Code
def execute_bigquery_query(query, use_cache=True):
    if ENABLE_QUERY_CACHING and use_cache:
        # Use BigQuery result caching
        job_config = bigquery.QueryJobConfig(use_query_cache=True)
    else:
        # Disable caching
        job_config = bigquery.QueryJobConfig(use_query_cache=False)

    return client.query(query, job_config=job_config).result()
```

**Deployment Command:**
```bash
gcloud run services update nba-orchestrator \
  --update-env-vars ENABLE_QUERY_CACHING=true,QUERY_CACHE_TTL_SECONDS=3600
```

---

### 4. Idempotency Keys
```python
# Environment Variables
ENABLE_IDEMPOTENCY_KEYS = bool(os.getenv('ENABLE_IDEMPOTENCY_KEYS', 'false').lower() == 'true')
DEDUP_TTL_DAYS = int(os.getenv('DEDUP_TTL_DAYS', '7'))

# Usage in Code
def handle_completion_event(request):
    message_id = request.headers.get('X-Message-Id')

    if ENABLE_IDEMPOTENCY_KEYS:
        # Check deduplication
        dedup_ref = db.collection('message_dedup').document(message_id)
        if dedup_ref.get().exists:
            logger.info(f"Duplicate message {message_id}, returning 204")
            return ('', 204)

        # Process normally
        result = process_completion(request)

        # Mark as processed
        expiry = datetime.utcnow() + timedelta(days=DEDUP_TTL_DAYS)
        dedup_ref.set({
            'processed_at': firestore.SERVER_TIMESTAMP,
            'expires_at': expiry
        })
        return result
    else:
        # Old behavior: no deduplication
        return process_completion(request)
```

**Deployment Command:**
```bash
gcloud run services update prediction-coordinator \
  --update-env-vars ENABLE_IDEMPOTENCY_KEYS=true,DEDUP_TTL_DAYS=7
```

---

### 5. Config-Driven Parallel Execution
```python
# Environment Variables
ENABLE_PARALLEL_CONFIG = bool(os.getenv('ENABLE_PARALLEL_CONFIG', 'false').lower() == 'true')

# Usage in Code
def execute_workflow(workflow_name):
    workflow_config = self.config.get_workflow(workflow_name)

    if ENABLE_PARALLEL_CONFIG:
        # Use config to determine execution mode
        execution_mode = workflow_config.get('execution_mode', 'sequential')
        max_workers = workflow_config.get('max_workers', 10)

        if execution_mode == 'parallel':
            return execute_parallel(scrapers, max_workers)
        else:
            return execute_sequential(scrapers)
    else:
        # Old behavior: hardcoded check
        if workflow_name == 'morning_operations':
            return execute_parallel(scrapers, 34)
        else:
            return execute_sequential(scrapers)
```

**Deployment Command:**
```bash
gcloud run services update nba-orchestrator \
  --update-env-vars ENABLE_PARALLEL_CONFIG=true
```

---

### 6. Centralized Timeout Configuration
```python
# Environment Variables
ENABLE_CENTRALIZED_TIMEOUTS = bool(os.getenv('ENABLE_CENTRALIZED_TIMEOUTS', 'false').lower() == 'true')

# Usage in Code
if ENABLE_CENTRALIZED_TIMEOUTS:
    from shared.config.timeout_config import TimeoutConfig
    timeout = TimeoutConfig.SCRAPER_HTTP_TIMEOUT
else:
    timeout = 180  # Hardcoded fallback

response = requests.post(url, timeout=timeout)
```

**Deployment Command:**
```bash
gcloud run services update nba-orchestrator \
  --update-env-vars ENABLE_CENTRALIZED_TIMEOUTS=true
```

---

### 7. Structured Logging
```python
# Environment Variables
ENABLE_STRUCTURED_LOGGING = bool(os.getenv('ENABLE_STRUCTURED_LOGGING', 'false').lower() == 'true')

# Usage in Code
if ENABLE_STRUCTURED_LOGGING:
    logger.info("Workflow executed", extra={
        "workflow_name": workflow_name,
        "duration_seconds": duration,
        "status": status,
        "scrapers_count": len(scrapers)
    })
else:
    logger.info(f"Workflow {workflow_name} executed in {duration}s: {status}")
```

**Deployment Command:**
```bash
gcloud run services update nba-orchestrator \
  --update-env-vars ENABLE_STRUCTURED_LOGGING=true
```

---

## 🚀 Rollout Strategy

### Standard Rollout (Low Risk)
```
Day 1: Deploy with flag=false (0% traffic)
       Verify deployment successful
       Test manually in staging

Day 2: Enable flag for 10% traffic
       Monitor for 4-6 hours
       Check error rates, latency

Day 3: Increase to 50% traffic
       Monitor for 4-6 hours
       Compare metrics old vs new

Day 4: Increase to 100% traffic
       Monitor for 24 hours
       Validate full rollout

Day 5: Clean up old code paths (optional)
```

### Gradual Rollout (Medium Risk - Dual-Write)
```
Day 1: Deploy dual-write, reads from old
       Both structures updated
       Validate consistency

Days 2-7: Monitor both structures
          Compare counts daily
          Ensure no divergence

Day 8: Switch reads to new structure
       Monitor for issues
       Validate performance

Days 9-14: Both structures still updated
           Confidence period

Day 15: Stop writing to old structure
        Monitor for issues

Day 30: Delete old structure (manual cleanup)
```

### Canary Rollout (High Risk - Async)
```
Week 1: Deploy to staging only
        Full integration testing
        Load testing

Week 2: Deploy to 1% production
        Monitor for issues
        Performance validation

Week 3: Increase to 10%, 25%, 50%
        Monitor each step
        Rollback if issues

Week 4: Increase to 100%
        Full rollout complete
```

---

## 📊 Monitoring During Rollout

### Metrics to Watch
1. **Error Rate:** Should not increase
2. **Latency:** Should not degrade
3. **Success Rate:** Should not decrease
4. **Cost:** Should decrease (BigQuery)
5. **Duplicates:** Should decrease (idempotency)

### Alerts to Set
```yaml
- name: "Feature Flag Rollout Error Rate"
  condition: error_rate > baseline * 1.1
  action: Alert team, consider rollback

- name: "Feature Flag Performance Degradation"
  condition: p99_latency > baseline * 1.2
  action: Alert team, investigate

- name: "Feature Flag Success Rate Drop"
  condition: success_rate < baseline * 0.95
  action: Rollback immediately
```

### Dashboards
- Create feature flag dashboard showing:
  - % of traffic with flag enabled
  - Error rate comparison (old vs new)
  - Latency comparison
  - Success rate comparison
  - Cost trend (BigQuery flags)

---

## ⚠️ Rollback Procedures

### Emergency Rollback (< 5 minutes)
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
  ENABLE_QUERY_CACHING=false \
  --no-traffic  # Optional: stop all traffic during rollback

# Wait 30 seconds for deployment
sleep 30

# Resume traffic
gcloud run services update nba-orchestrator --traffic

# Monitor for stabilization
```

### Gradual Rollback
```bash
# Step 1: Reduce to 50%
# Use Cloud Run traffic splitting or feature flag percentage

# Step 2: Monitor for 30 minutes

# Step 3: Reduce to 10%

# Step 4: Monitor for 30 minutes

# Step 5: Disable completely (0%)

# Step 6: Investigate issue

# Step 7: Fix and redeploy

# Step 8: Re-enable gradually
```

### Subcollection Rollback (Dual-Write)
```bash
# Stop reading from subcollection
gcloud run services update prediction-coordinator \
  --update-env-vars USE_SUBCOLLECTION_READS=false

# Continue dual-write for safety
# Investigate issue

# Fix and redeploy

# Re-enable subcollection reads
gcloud run services update prediction-coordinator \
  --update-env-vars USE_SUBCOLLECTION_READS=true
```

---

## 📋 Feature Flag Checklist

### Before Deployment
- [ ] Feature flag code implemented
- [ ] Default value is safe (false for new behavior)
- [ ] Rollback procedure documented
- [ ] Monitoring alerts configured
- [ ] Team notified of rollout plan

### During Rollout
- [ ] Deploy with flag disabled
- [ ] Verify deployment successful
- [ ] Enable for 10% traffic
- [ ] Monitor for 4-6 hours
- [ ] Increase to 50%
- [ ] Monitor for 4-6 hours
- [ ] Increase to 100%
- [ ] Monitor for 24 hours

### After Rollout
- [ ] Validate success metrics
- [ ] Document learnings
- [ ] Plan cleanup (remove flag code after 30 days)
- [ ] Update runbooks

---

## 🎯 Success Criteria

### Week 1 Feature Flags
All Week 1 flags should reach 100% by end of week:
- ✅ ENABLE_PHASE2_COMPLETION_DEADLINE: 100%
- ✅ ENABLE_SUBCOLLECTION_COMPLETIONS: 100% (dual-write)
- ✅ ENABLE_IDEMPOTENCY_KEYS: 100%
- ✅ ENABLE_PARALLEL_CONFIG: 100%
- ✅ ENABLE_CENTRALIZED_TIMEOUTS: 100%
- ✅ ENABLE_STRUCTURED_LOGGING: 100%
- ✅ ENABLE_QUERY_CACHING: 100%

### Zero Incidents
- ✅ No production incidents from feature flags
- ✅ No emergency rollbacks
- ✅ All rollouts completed successfully

---

**Created:** January 20, 2026
**Status:** Ready for Week 1 execution
**Maintenance:** Remove feature flag code 30 days after 100% rollout

Feature flags enable confident, safe improvements! 🚀
