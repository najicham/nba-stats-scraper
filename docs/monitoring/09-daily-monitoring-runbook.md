# Daily Monitoring Runbook

**Created:** 2025-11-23
**Last Updated:** 2025-11-23
**Purpose:** Daily health check procedures for NBA analytics pipeline
**Time Required:** 10-15 minutes
**When to Run:** Every morning (9-10 AM PT)

---

## Quick Overview

**What This Covers:**
- ✅ Complete pipeline health check (Phase 1→4)
- ✅ CASCADE scheduler status (NEW - runs nightly at 11 PM & 11:30 PM)
- ✅ Pub/Sub flow monitoring (NEW - Phase 3→4 automatic flow)
- ✅ Completeness checking validation
- ✅ Circuit breaker alerts

**Expected Time:** 10-15 minutes for daily check

---

## Morning Checklist

### Step 1: CASCADE Scheduler Check (2 mins)
**What:** Verify last night's CASCADE scheduler jobs ran successfully

**Commands:**
```bash
# Quick check
./bin/monitoring/check_cascade_schedulers.sh

# Or check manually
gcloud scheduler jobs list \
  --location us-west2 \
  --filter="name:player-composite OR name:ml-feature" \
  --format="table(name.basename(),lastAttemptTime,status.code)"
```

**Expected Results:**
- ✅ Both jobs show `lastAttemptTime` from last night (11 PM & 11:30 PM PT)
- ✅ `status.code` = `0` (success)
- ✅ BigQuery tables have data for yesterday with ≥90% production ready

**If Issues:**
- Check Cloud Run logs: `gcloud run services logs read nba-phase4-precompute-processors --region us-west2 --limit 50`
- Look for "AUTO date resolved to" messages
- Check for dependency errors in logs

---

### Step 2: Pub/Sub Flow Check (3 mins)
**What:** Verify Phase 3→4 Pub/Sub flow is working

**Commands:**
```bash
# Full check
./bin/monitoring/check_pubsub_flow.sh

# Quick backlog check
gcloud pubsub subscriptions describe nba-phase3-analytics-complete-sub \
  --format="value(numUndeliveredMessages)"
```

**Expected Results:**
- ✅ No message backlog (numUndeliveredMessages = 0)
- ✅ Phase 4 processors ran within 5-30 minutes of Phase 3
- ✅ All Phase 3 tables triggered corresponding Phase 4 processors

**If Issues:**
- Backlog >0: Phase 4 service may be down
- Missing Phase 4 runs: Check Cloud Run service is running
- High latency: Check Cloud Run logs for cold start or resource issues

---

### Step 3: Completeness Health Check (5 mins)
**What:** Check all processors have acceptable completeness percentages

**Commands:**
```bash
# Use existing SQL query (updated for new processors)
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Phase 4: team_defense_zone_analysis' as processor,
  COUNT(*) as total,
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) as ready,
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1) as ready_pct,
  ROUND(AVG(completeness_percentage), 1) as avg_completeness
FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
WHERE analysis_date >= CURRENT_DATE() - 3

UNION ALL

SELECT
  'Phase 4: player_shot_zone_analysis',
  COUNT(*),
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1),
  ROUND(AVG(completeness_percentage), 1)
FROM \`nba-props-platform.nba_precompute.player_shot_zone_analysis\`
WHERE analysis_date >= CURRENT_DATE() - 3

UNION ALL

SELECT
  'Phase 4: player_daily_cache',
  COUNT(*),
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1),
  ROUND(AVG(completeness_percentage), 1)
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= CURRENT_DATE() - 3

UNION ALL

SELECT
  'Phase 4: player_composite_factors',
  COUNT(*),
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1),
  ROUND(AVG(completeness_percentage), 1)
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= CURRENT_DATE() - 3

UNION ALL

SELECT
  'Phase 4: ml_feature_store',
  COUNT(*),
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1),
  ROUND(AVG(completeness_percentage), 1)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= CURRENT_DATE() - 3

UNION ALL

SELECT
  'Phase 3: upcoming_player_game_context',
  COUNT(*),
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1),
  ROUND(AVG(completeness_percentage), 1)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date >= CURRENT_DATE() - 3

UNION ALL

SELECT
  'Phase 3: upcoming_team_game_context',
  COUNT(*),
  SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN is_production_ready THEN 1 ELSE 0 END) / COUNT(*), 1),
  ROUND(AVG(completeness_percentage), 1)
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date >= CURRENT_DATE() - 3;
"
```

**Expected Results:**
- ✅ ready_pct ≥ 90% for all processors
- ✅ avg_completeness ≥ 90%
- ✅ total >0 (data exists)

**Thresholds:**
- **≥95%:** ✅ EXCELLENT
- **≥90%:** ✓ GOOD
- **≥80%:** ⚠ WARNING - investigate
- **<80%:** ❌ CRITICAL - immediate action required

**If Issues:**
- Check data quality issues array
- Review circuit breaker status
- Check upstream data availability

---

### Step 4: Circuit Breaker Check (2 mins)
**What:** Check if any entities are blocked by circuit breaker

**Commands:**
```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  DATETIME_DIFF(circuit_breaker_until, CURRENT_DATETIME(), DAY) as days_until_retry
FROM \`nba-props-platform.nba_orchestration.reprocess_attempts\`
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_DATETIME()
ORDER BY circuit_breaker_until DESC
LIMIT 10;
"
```

**Expected Results:**
- ✅ No rows returned (no active circuit breakers)

**If Circuit Breakers Found:**
- Review skip_reason to understand why
- Check if upstream data is now available
- If >7 days old, circuit breaker will reset automatically
- If critical entity, may need manual override

---

### Step 5: Phase 1-2 Health (3 mins)
**What:** Quick check that scrapers and raw processors are running

**Commands:**
```bash
# Check scraper health
./bin/orchestration/quick_health_check.sh

# Or check manually
bq query --use_legacy_sql=false --format=pretty "
SELECT
  DATE(triggered_at, 'America/New_York') as scrape_date,
  COUNT(DISTINCT scraper_name) as scrapers_run,
  COUNTIF(status IN ('success', 'no_data')) as succeeded,
  COUNTIF(status = 'failed') as failed
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at, 'America/New_York') >= CURRENT_DATE() - 3
GROUP BY scrape_date
ORDER BY scrape_date DESC;
"
```

**Expected Results:**
- ✅ scrapers_run ≥ 30 for each date
- ✅ failed <5 (some no_data is normal)
- ✅ Most recent date is yesterday

---

## Daily Report Template

After running all checks, create a quick status summary:

```
NBA ANALYTICS PIPELINE - DAILY STATUS
Date: 2025-11-23 09:30 AM PT

CASCADE SCHEDULERS:
  ✅ player-composite-factors: Ran 11:01 PM, 95% ready
  ✅ ml-feature-store: Ran 11:32 PM, 93% ready

PUB/SUB FLOW (Phase 3→4):
  ✅ No message backlog
  ✅ Average latency: 3 minutes

COMPLETENESS:
  ✅ Phase 3: 97% production ready
  ✅ Phase 4: 94% production ready

CIRCUIT BREAKERS:
  ✅ No active circuit breakers

PHASE 1-2:
  ✅ 45 scrapers ran successfully
  ✅ All raw tables populated

OVERALL STATUS: ✅ HEALTHY
Action Required: None
```

---

## Weekly Tasks

**Every Monday:**
1. Review Circuit Breaker History (last 7 days)
2. Check for Pattern in Reprocess Attempts
3. Review Completeness Trends

**Commands:**
```bash
# Circuit breaker history
bq query --use_legacy_sql=false --format=pretty "
SELECT
  processor_name,
  skip_reason,
  COUNT(DISTINCT entity_id) as affected_entities,
  COUNT(*) as total_attempts,
  SUM(CASE WHEN circuit_breaker_tripped THEN 1 ELSE 0 END) as breaker_trips
FROM \`nba-props-platform.nba_orchestration.reprocess_attempts\`
WHERE attempted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, skip_reason
ORDER BY affected_entities DESC;
"
```

---

## Monthly Tasks

**First Monday of Month:**
1. Review Completeness Thresholds
2. Backfill Any Missing Gaps
3. Update Documentation

**Commands:**
```bash
# Find date gaps
bq query --use_legacy_sql=false "
SELECT
  date,
  CASE WHEN p4.game_date IS NULL THEN '❌ MISSING' ELSE '✅ EXISTS' END as status
FROM UNNEST(GENERATE_DATE_ARRAY(DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY), CURRENT_DATE())) AS date
LEFT JOIN (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
) p4 ON date = p4.game_date
WHERE p4.game_date IS NULL
ORDER BY date DESC;
"
```

---

## Troubleshooting Quick Reference

### Issue: CASCADE Scheduler Didn't Run
**Symptoms:** No data for yesterday in player_composite_factors or ml_feature_store

**Steps:**
1. Check scheduler job status: `gcloud scheduler jobs describe player-composite-factors-daily --location us-west2`
2. Check if job is ENABLED or PAUSED
3. View Cloud Run logs for errors
4. Check dependency completeness (Phase 4 pub/sub processors)
5. Manually trigger if needed: `gcloud scheduler jobs run player-composite-factors-daily --location us-west2`

### Issue: Pub/Sub Message Backlog
**Symptoms:** numUndeliveredMessages >0

**Steps:**
1. Check Phase 4 Cloud Run service is running
2. Check subscription push endpoint is correct
3. Review Cloud Run logs for errors
4. Check authentication (should be --allow-unauthenticated)
5. Test manually: `curl -X POST https://nba-phase4-precompute-processors-xxx.run.app/health`

### Issue: Low Completeness Percentage
**Symptoms:** ready_pct <90%

**Steps:**
1. Check data_quality_issues array for specific problems
2. Verify upstream tables have data
3. Check schedule for expected games
4. Review circuit breaker status
5. Check if in bootstrap mode (first 30 days)

---

## Related Documentation

- **CASCADE Schedulers:** `docs/operations/04-cascade-scheduler-jobs.md`
- **Completeness Checking:** `docs/monitoring/05-data-completeness-validation.md`
- **Pub/Sub Architecture:** `docs/deployment/02-cascade-pattern-implementation.md`
- **Grafana Dashboards:** `docs/monitoring/01-grafana-monitoring-guide.md`

---

## Monitoring Scripts

**Location:** `/bin/monitoring/`

- `check_cascade_schedulers.sh` - CASCADE scheduler monitoring
- `check_pubsub_flow.sh` - Pub/Sub Phase 3→4 flow monitoring
- `../orchestration/quick_health_check.sh` - Overall pipeline health

**Run All:**
```bash
./bin/monitoring/check_cascade_schedulers.sh
./bin/monitoring/check_pubsub_flow.sh
./bin/orchestration/quick_health_check.sh
```

---

## Alert Thresholds

**Immediate Action Required:**
- ❌ ready_pct <80% for any processor
- ❌ Pub/Sub message backlog >100
- ❌ CASCADE schedulers didn't run for 2+ days
- ❌ Circuit breaker tripped for critical entities

**Warning - Investigate Soon:**
- ⚠ ready_pct 80-90%
- ⚠ Pub/Sub latency >30 minutes
- ⚠ Circuit breaker tripped for >10 entities
- ⚠ Completeness trending downward

**Normal - Monitor:**
- ✓ ready_pct 90-95%
- ✓ Pub/Sub latency 5-30 minutes
- ✓ 1-5 circuit breaker trips (transient issues)
- ✓ Completeness stable

**Excellent:**
- ✅ ready_pct ≥95%
- ✅ Pub/Sub latency <5 minutes
- ✅ No circuit breaker trips
- ✅ Completeness trending upward

---

**Document Status:** ✅ Current
**Last Updated:** 2025-11-23
**Next Review:** After first week of CASCADE scheduler operation
