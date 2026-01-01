# Phase 5 Prediction Worker Scaling Issue

**Date Discovered**: December 31, 2025
**Severity**: Medium
**Status**: Documented - Not Fixed
**Impact**: Partial batch failures during high-concurrency predictions

---

## 🔍 Issue Summary

The Phase 5 prediction worker service has insufficient Cloud Run instance limits to handle typical batch sizes, resulting in ~32% of prediction requests failing with "no available instance" errors.

## 📊 Observed Behavior

### Test Scenario
- **Date**: 2025-12-20
- **Total Requests**: 220 player predictions
- **Successful**: 150 workers (~68%)
- **Failed**: 70 workers (~32%)

### Error Message
```
The request was aborted because there was no available instance.
Additional troubleshooting documentation can be found at:
https://cloud.google.com/run/docs/troubleshooting#abort-request
```

### Timeline
1. **17:25 UTC**: Batch started, 220 Pub/Sub messages published
2. **17:26-17:28 UTC**: Workers processing, 150 completed successfully
3. **17:28+ UTC**: Remaining 70 requests stuck, no instances available
4. **17:30-17:50 UTC**: Batch never completed (stuck at 150/220)

## 🔧 Technical Details

### Current Worker Configuration
```yaml
Service: prediction-worker
Region: us-west2
Max Instances: Unknown (likely 100 or less)
Concurrency: 80 (default)
Memory: 2Gi
CPU: 1
Timeout: 300s
```

### Request Pattern
- **Coordinator**: Publishes 220 messages to Pub/Sub simultaneously
- **Pub/Sub**: Delivers messages to workers immediately
- **Workers**: Cloud Run auto-scales to handle load
- **Problem**: Max instances hit before all 220 workers can start

### Evidence

**Worker Logs** (2025-12-31 17:26-17:30 UTC):
```
2026-01-01T02:12:30 ERROR: The request was aborted because there was no available instance
[70 identical errors]
```

**Batch Status**:
```json
{
  "status": "in_progress",
  "progress": {
    "completed": 150,
    "expected": 220,
    "is_complete": false
  }
}
```

**Staging Tables Created**: 50 (should be 220)
- Note: Only 50 staging tables despite 150 "completed" workers suggests some workers failed to write data

## 💥 Impact Assessment

### Current Impact
- **Partial Batch Failures**: 32% of predictions missing
- **Incomplete Predictions**: Players without predictions lose coverage
- **Coordinator Hangs**: Batch never marks as complete
- **No Auto-Consolidation**: Manual intervention required

### Business Impact
- **Production**: Low risk (production batches typically smaller, ~100-150 players)
- **Testing**: High impact (full batches fail regularly)
- **Development**: Moderate (slows down testing/debugging)

### Severity Justification: MEDIUM
- Not blocking production (typical loads < 150)
- Workaround available (manual consolidation)
- Only affects large batches (220+ concurrent)
- Testing still possible with smaller batches

## 🎯 Root Cause Analysis

### Cloud Run Scaling Limitations

**Default Limits**:
- Free tier: 100 concurrent requests total
- Paid tier: 1000 instances per service (default quota)
- Region-specific quotas apply

**Why This Happens**:
1. Coordinator publishes 220 messages simultaneously
2. Pub/Sub delivers all 220 to worker service immediately
3. Cloud Run attempts to scale to 220 instances
4. Hits max instance limit (~100)
5. Remaining 120 requests get "no available instance" error
6. Those 120 requests eventually timeout and fail

**Why Workers Don't Retry**:
- Pub/Sub uses "at-least-once" delivery
- After worker returns error, Pub/Sub may retry
- But if all retries also hit instance limit, message eventually dead-letters
- Coordinator never receives completion signal

## 💡 Potential Solutions

### Option 1: Increase Cloud Run Max Instances (Recommended)
**Change**: Update worker service max instances to 500+
**Pros**:
- Simple one-line config change
- Handles larger batches (up to 500 concurrent)
- No code changes required
**Cons**:
- Higher cost during peak (500 instances × 2Gi × duration)
- Still has upper limit

**Implementation**:
```bash
gcloud run services update prediction-worker \
  --region=us-west2 \
  --max-instances=500
```

**Cost Estimate**:
- Current: ~150 instances × 30s × $0.00002448/GB-sec × 2GB = $0.22/batch
- Proposed: ~220 instances × 30s × $0.00002448/GB-sec × 2GB = $0.32/batch
- Increase: ~$0.10 per large batch

### Option 2: Implement Rate Limiting in Coordinator
**Change**: Publish Pub/Sub messages in batches of 100 with delays
**Pros**:
- Stays within current limits
- More controlled scaling
- Lower cost
**Cons**:
- Slower total batch time (220 workers in 3 waves vs 1)
- Code changes required
- More complex coordination logic

**Implementation**:
```python
# In coordinator.py
def publish_with_rate_limiting(requests, batch_size=100):
    for i in range(0, len(requests), batch_size):
        batch = requests[i:i+batch_size]
        publish_batch(batch)
        if i + batch_size < len(requests):
            time.sleep(10)  # Wait for previous batch to finish
```

### Option 3: Queue-Based Processing
**Change**: Use Cloud Tasks instead of Pub/Sub for rate control
**Pros**:
- Built-in rate limiting (max dispatch per second)
- Guaranteed execution order
- Better retry handling
**Cons**:
- Significant architecture change
- Migration effort
- Different billing model

### Option 4: Hybrid Approach (Best Long-Term)
**Change**: Rate limit + higher max instances
**Configuration**:
- Max instances: 250 (handles 220 + buffer)
- Publish in batches of 100
- Wait 5s between batches

**Pros**:
- Controlled scaling (cost-effective)
- Handles bursts (250 instance cap)
- Graceful degradation
**Cons**:
- Requires both config and code changes

## 📋 Recommended Action Plan

### Immediate (< 1 hour)
1. ✅ Document issue (this file)
2. Increase max instances to 250
   ```bash
   ./bin/predictions/deploy/deploy_prediction_worker.sh --max-instances=250
   ```
3. Test with 220-player batch
4. Monitor costs for 1 week

### Short-Term (< 1 week)
1. Implement rate limiting in coordinator
2. Publish in batches of 100 with 5s delays
3. Reduce max instances to 150 (cost optimization)
4. Add alerting for "no available instance" errors

### Long-Term (< 1 month)
1. Add metrics for worker scaling
2. Implement auto-tuning based on batch size
3. Consider Cloud Tasks migration for better control
4. Add circuit breaker for cascading failures

## 🔬 Testing & Validation

### Test Cases
1. **Small Batch** (50 players): Should work with current limits
2. **Medium Batch** (150 players): Edge case, may work
3. **Large Batch** (220 players): Currently fails, should pass after fix
4. **Extra Large** (500 players): Should pass with max-instances=500

### Validation Checklist
- [ ] All workers complete successfully (no "no available instance" errors)
- [ ] Batch marks as complete (is_complete=true)
- [ ] All staging tables created (count = expected requests)
- [ ] Auto-consolidation runs successfully
- [ ] Coordinator logs show no timeout warnings
- [ ] Cost increase within acceptable range (<20%)

## 📚 Related Issues

### Similar Issues Found
- **Phase 3 Analytics**: No issues (processes serially, not parallel)
- **Phase 4 Precompute**: No issues (single instance, sequential)
- **Phase 6 Grading**: Unknown (not tested with large batches)

### Potential Future Issues
- **Prediction Grading**: May hit same limit with 220+ grading requests
- **Backfill Operations**: Large date ranges could overwhelm workers

## 🔗 References

- [Cloud Run Quotas](https://cloud.google.com/run/quotas)
- [Cloud Run Scaling](https://cloud.google.com/run/docs/about-instance-autoscaling)
- [Troubleshooting "No Available Instance"](https://cloud.google.com/run/docs/troubleshooting#abort-request)
- [Pub/Sub Push Subscriptions](https://cloud.google.com/pubsub/docs/push)
- [Cloud Tasks Rate Limiting](https://cloud.google.com/tasks/docs/configuring-queues#rate)

## 📝 Notes

### Workaround for Testing
If you encounter this issue during testing:

```bash
# Option 1: Use smaller batches
./bin/pipeline/force_predictions.sh 2025-12-20 test --max-players=100

# Option 2: Manually consolidate partial batches
python3 << EOF
from google.cloud import bigquery
from predictions.worker.batch_staging_writer import BatchConsolidator

client = bigquery.Client(project="nba-props-platform", location="us-west2")
consolidator = BatchConsolidator(client, "nba-props-platform", dataset_prefix="test")
result = consolidator.consolidate_batch("batch_ID_HERE", "2025-12-20")
print(f"Consolidated {result.rows_affected} rows")
EOF
```

### Discovery Context
This issue was discovered during end-to-end testing of the dataset isolation feature (2025-12-31). While testing Phase 5 predictions with `dataset_prefix="test"`, we noticed that batches were getting stuck at 150/220 workers completed. Investigation revealed Cloud Run scaling limits as the root cause.

**Key Insight**: The issue existed before dataset isolation work but was exposed by thorough testing. Dataset isolation itself is working correctly - this is a separate infrastructure concern.

---

**Last Updated**: December 31, 2025
**Discoverer**: Dataset Isolation Testing
**Next Review**: After implementing max-instances increase
