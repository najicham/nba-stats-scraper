# CASCADE Scheduler Jobs - Operations Guide

**Created:** 2025-11-23
**Status:** PRODUCTION - Schedulers Active
**Location:** us-west2

---

## Overview

CASCADE processors (PlayerCompositeFactors and MLFeatureStore) check multiple upstream dependencies before running. They run on a **nightly schedule** via Cloud Scheduler to ensure all dependencies are ready.

**Why Schedulers?**
- CASCADE processors depend on multiple Phase 4 processors
- Pub/Sub triggers aren't suitable (would need to wait for ALL upstreams)
- Scheduled runs at 11 PM ensure all daily processing is complete

---

## Active Scheduler Jobs

### 1. player-composite-factors-daily

**Schedule:** `0 23 * * *` (11:00 PM PT daily)
**Processor:** PlayerCompositeFactorsProcessor
**Dependencies:** 4 upstreams
- `team_defense_zone_analysis`
- `player_shot_zone_analysis`
- `player_daily_cache`
- `upcoming_player_game_context`

**Endpoint:** POST `/process-date`
**Payload:**
```json
{
  "processors": ["PlayerCompositeFactorsProcessor"],
  "analysis_date": "AUTO"
}
```

**What it does:**
1. Resolves "AUTO" to yesterday's date
2. Checks all 4 upstreams for `is_production_ready = true`
3. If all ready: runs processor
4. If any missing: logs error and sends email alert

### 2. ml-feature-store-daily

**Schedule:** `30 23 * * *` (11:30 PM PT daily)
**Processor:** MLFeatureStoreProcessor
**Dependencies:** 5 upstreams
- `team_defense_zone_analysis`
- `player_shot_zone_analysis`
- `player_daily_cache`
- `player_composite_factors`
- `upcoming_player_game_context`

**Endpoint:** POST `/process-date`
**Payload:**
```json
{
  "processors": ["MLFeatureStoreProcessor"],
  "analysis_date": "AUTO"
}
```

**What it does:**
1. Resolves "AUTO" to yesterday's date
2. Checks all 5 upstreams for `is_production_ready = true`
3. If all ready: runs processor
4. If any missing: logs error and sends email alert

---

## AUTO Date Feature

**What is it?**
"AUTO" is a special date value that resolves to yesterday's date automatically.

**Why?**
Late-night scheduler jobs (11 PM) process data from the previous day (games that finished earlier that evening).

**Implementation:**
```python
# In main_precompute_service.py
if analysis_date == "AUTO":
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    analysis_date = yesterday.strftime('%Y-%m-%d')
```

**Example:**
- Scheduler runs: 2025-11-24 at 11:00 PM PT
- AUTO resolves to: 2025-11-23
- Processes data from: November 23rd games

---

## Management Commands

### List All Scheduler Jobs
```bash
gcloud scheduler jobs list \
  --project nba-props-platform \
  --location us-west2 \
  --format="table(name.basename(),schedule,state,httpTarget.uri)"
```

### View Specific Job Details
```bash
# PlayerCompositeFactorsProcessor job
gcloud scheduler jobs describe player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2

# MLFeatureStoreProcessor job
gcloud scheduler jobs describe ml-feature-store-daily \
  --project nba-props-platform \
  --location us-west2
```

### Check Job Execution History
```bash
# View recent executions
gcloud scheduler jobs describe player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2 \
  --format="value(status.lastAttemptTime,status.status)"
```

### Manually Trigger a Job (Testing)
```bash
# Test player-composite-factors
gcloud scheduler jobs run player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2

# Test ml-feature-store
gcloud scheduler jobs run ml-feature-store-daily \
  --project nba-props-platform \
  --location us-west2
```

### Check Cloud Run Logs After Execution
```bash
gcloud run services logs read nba-phase4-precompute-processors \
  --project nba-props-platform \
  --region us-west2 \
  --limit 50
```

---

## Monitoring

### Daily Checks (Next Morning)

**1. Check if jobs ran:**
```bash
gcloud scheduler jobs list \
  --project nba-props-platform \
  --location us-west2 \
  --filter="name:player-composite OR name:ml-feature"
```

**2. Check Phase 4 logs for SUCCESS:**
```bash
gcloud run services logs read nba-phase4-precompute-processors \
  --project nba-props-platform \
  --region us-west2 \
  --format="table(time,textPayload)" \
  --limit 100
```

Look for:
- `INFO: AUTO date resolved to: YYYY-MM-DD`
- `INFO: Running PlayerCompositeFactorsProcessor for YYYY-MM-DD`
- `INFO: Successfully ran PlayerCompositeFactorsProcessor`

**3. Check BigQuery for output data:**
```sql
-- PlayerCompositeFactors
SELECT analysis_date, COUNT(*) as player_count, is_production_ready
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE analysis_date >= CURRENT_DATE() - 2
GROUP BY analysis_date, is_production_ready
ORDER BY analysis_date DESC;

-- MLFeatureStore
SELECT analysis_date, COUNT(*) as feature_count, is_production_ready
FROM `nba-props-platform.nba_precompute.ml_feature_store_v2`
WHERE analysis_date >= CURRENT_DATE() - 2
GROUP BY analysis_date, is_production_ready
ORDER BY analysis_date DESC;
```

### Email Alerts

You should receive email alerts if:
- ❌ Missing critical dependencies
- ❌ Processor fails during execution
- ❌ Completeness check fails

**No email = good!** Jobs ran successfully.

---

## Troubleshooting

### Job Didn't Run

**Check job state:**
```bash
gcloud scheduler jobs describe player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2 \
  --format="value(state)"
```

**Expected:** `ENABLED`
**If PAUSED:** Re-enable it:
```bash
gcloud scheduler jobs resume player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2
```

### Job Ran But Processor Failed

**Common causes:**
1. **Missing dependencies** - Check upstream `is_production_ready` status
2. **Early exit logic** - Date too old (>90 days)
3. **Completeness threshold** - Not enough data

**Check logs:**
```bash
gcloud run services logs read nba-phase4-precompute-processors \
  --project nba-props-platform \
  --region us-west2 \
  --limit 100 | grep -A 10 "PlayerCompositeFactors"
```

**Check dependencies:**
```sql
SELECT
  'team_defense_zone_analysis' as table_name,
  MAX(analysis_date) as last_date,
  is_production_ready
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date >= CURRENT_DATE() - 2
GROUP BY is_production_ready;
```

### Change Schedule Time

**Example: Change to 10:30 PM instead of 11:00 PM:**
```bash
gcloud scheduler jobs update http player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2 \
  --schedule="30 22 * * *"
```

### Disable Job Temporarily

**Pause job:**
```bash
gcloud scheduler jobs pause player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2
```

**Resume job:**
```bash
gcloud scheduler jobs resume player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2
```

### Delete and Recreate Job

**Delete:**
```bash
gcloud scheduler jobs delete player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2
```

**Recreate:**
```bash
gcloud scheduler jobs create http player-composite-factors-daily \
  --project nba-props-platform \
  --location us-west2 \
  --schedule="0 23 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"processors": ["PlayerCompositeFactorsProcessor"], "analysis_date": "AUTO"}' \
  --description="Daily CASCADE processor for PlayerCompositeFactors at 11:00 PM PT"
```

---

## Adding New CASCADE Processors

**If you create a new CASCADE processor:**

1. **Add to CASCADE_PROCESSORS registry** in `main_precompute_service.py`
2. **Create Cloud Scheduler job:**

```bash
gcloud scheduler jobs create http your-processor-daily \
  --project nba-props-platform \
  --location us-west2 \
  --schedule="0 23 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"processors": ["YourProcessorName"], "analysis_date": "AUTO"}' \
  --description="Your processor description"
```

3. **Test manually first:**
```bash
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["YourProcessorName"], "analysis_date": "2024-11-22"}'
```

4. **Update this documentation** with the new job details

---

## Schedule Timing Strategy

**Current timing:**
- **11:00 PM PT:** PlayerCompositeFactors (depends on Phase 4 Pub/Sub processors)
- **11:30 PM PT:** MLFeatureStore (depends on PlayerCompositeFactors)

**Why these times?**
1. NBA games typically finish by 10:00-10:30 PM PT
2. Phase 1 (scrapers) run throughout the evening
3. Phase 2 (raw) processes immediately after scrapers
4. Phase 3 (analytics) triggered by Phase 2 Pub/Sub
5. Phase 4 Pub/Sub processors triggered by Phase 3
6. By 11 PM, all upstream processing should be complete

**Adjusting times:**
- Earlier = risk of missing data
- Later = delay for Phase 5 predictions
- 11 PM is a good balance

---

## Best Practices

1. **Monitor first week closely** - Watch for timing issues
2. **Check logs daily** - Ensure jobs are succeeding
3. **Don't change schedules without testing** - Could break dependency chain
4. **Use AUTO date for schedulers** - Don't hardcode dates
5. **Keep 30-minute gap** between dependent jobs (11:00 PM and 11:30 PM)

---

## Related Documentation

- **Deployment Status:** `docs/deployment/00-deployment-status.md`
- **CASCADE Pattern Implementation:** `docs/deployment/02-cascade-pattern-implementation.md`
- **Processor Registry:** `docs/reference/04-processor-registry-reference.md`

---

## Quick Reference

**Check job status:**
```bash
gcloud scheduler jobs list --location us-west2 | grep -E "player-composite|ml-feature"
```

**Manual trigger (testing):**
```bash
gcloud scheduler jobs run player-composite-factors-daily --location us-west2
```

**View logs:**
```bash
gcloud run services logs read nba-phase4-precompute-processors --region us-west2 --limit 50
```

---

**Document Status:** ✅ Current
**Last Updated:** 2025-11-23
**Maintained By:** NBA Platform Team
