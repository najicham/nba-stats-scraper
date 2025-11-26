# Phase 3 Monitoring Quick Start Guide

**Created:** 2025-11-21 17:00:00 PST
**Last Updated:** 2025-11-21 17:04:07 PST
**Goal:** Start monitoring Phase 3 analytics processors (already deployed)
**Timeline:** 30 minutes setup
**Prerequisites:** Access to GCP project, BigQuery, Grafana

---

## 🚀 Quick Commands (Copy & Paste)

### 1. Verify Phase 3 Is Logging Skip Events

```bash
# Check for smart reprocessing skip logs (last hour)
gcloud logging read \
  "resource.type=cloud_run_revision \
   AND resource.labels.service_name=nba-phase3-analytics-processors \
   AND textPayload=~\"SMART REPROCESSING.*Skipping\"" \
  --limit=20 \
  --format=json \
  --freshness=1h

# Expected output: JSON array with skip events
# If empty: Phase 3 not skipping yet (may need more data)
```

**What to look for:**
```json
{
  "textPayload": "SMART REPROCESSING: Skipping processing for game_date=2025-11-20, all source hashes unchanged",
  "timestamp": "2025-11-21T...",
  "resource": {
    "labels": {
      "service_name": "nba-phase3-analytics-processors"
    }
  }
}
```

---

### 2. Check Phase 3 Skip Rate (Last 24 Hours)

```bash
# Open BigQuery and run this query
bq query --use_legacy_sql=false '
WITH hash_comparison AS (
  SELECT
    game_date,
    game_id,
    source_nbac_hash,
    LAG(source_nbac_hash) OVER (
      PARTITION BY game_date, game_id
      ORDER BY processed_at
    ) as prev_hash,
    processed_at
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
SELECT
  COUNT(*) as total_runs,
  COUNTIF(source_nbac_hash = prev_hash) as skipped,
  COUNTIF(source_nbac_hash != prev_hash OR prev_hash IS NULL) as processed,
  ROUND(SAFE_DIVIDE(
    COUNTIF(source_nbac_hash = prev_hash),
    COUNT(*)
  ) * 100, 1) as skip_rate_pct
FROM hash_comparison
WHERE prev_hash IS NOT NULL;
'
```

**Expected Results:**
```
+------------+---------+-----------+---------------+
| total_runs | skipped | processed | skip_rate_pct |
+------------+---------+-----------+---------------+
|        150 |      65 |        85 |          43.3 |
+------------+---------+-----------+---------------+
```

**Interpretation:**
- Skip rate 30-50%: ✅ **Excellent** - Pattern working as expected
- Skip rate 10-30%: ⚠️ **OK** - Phase 2 data changing frequently
- Skip rate <10%: ❌ **Issue** - Pattern may not be working
- Skip rate >80%: ❌ **Issue** - Possible duplicate processing or stale data

---

### 3. Check Dependency Failures (Last 6 Hours)

```bash
bq query --use_legacy_sql=false '
SELECT
  processor,
  COUNT(*) as failures,
  STRING_AGG(DISTINCT missing_source, ", ") as missing_sources
FROM (
  -- Player game summary
  SELECT
    "player_game_summary" as processor,
    game_date,
    CASE
      WHEN source_nbac_rows_found IS NULL OR source_nbac_rows_found = 0
        THEN "nbac_gamebook"
      WHEN source_bdl_rows_found IS NULL OR source_bdl_rows_found = 0
        THEN "bdl_boxscores"
    END as missing_source
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
    AND (source_nbac_rows_found IS NULL OR source_nbac_rows_found = 0
         OR source_bdl_rows_found IS NULL OR source_bdl_rows_found = 0)
)
WHERE missing_source IS NOT NULL
GROUP BY processor;
'
```

**Expected:** 0 failures

**If failures found:**
```bash
# Check Phase 2 processor status
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 \
  --format="value(status.conditions)"
```

---

### 4. Check Backfill Queue

```bash
bq query --use_legacy_sql=false '
WITH phase2_games AS (
  SELECT DISTINCT game_date, game_id
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
phase3_games AS (
  SELECT DISTINCT game_date, game_id
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  COUNT(*) as backfill_needed,
  MIN(p2.game_date) as oldest_missing_date,
  MAX(p2.game_date) as newest_missing_date,
  ARRAY_AGG(STRUCT(p2.game_date, p2.game_id) ORDER BY p2.game_date DESC LIMIT 10) as recent_missing
FROM phase2_games p2
LEFT JOIN phase3_games p3 USING (game_date, game_id)
WHERE p3.game_id IS NULL;
'
```

**Expected:** < 10 games

**If > 50 games:**
```bash
# Run backfill job (if script exists)
python bin/maintenance/phase3_backfill_check.py --dry-run
```

---

### 5. Check Service Health

```bash
# Phase 3 service status
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="table(status.url,status.conditions.status,status.latestCreatedRevisionName)"

# Recent errors (last hour)
gcloud logging read \
  "resource.type=cloud_run_revision \
   AND resource.labels.service_name=nba-phase3-analytics-processors \
   AND severity>=ERROR" \
  --limit=10 \
  --freshness=1h
```

**Expected:** No errors

---

## 📊 Daily Monitoring Routine (5 minutes)

### Morning Check (9 AM)

```bash
# 1. Check skip rate from last 24 hours
bq query --use_legacy_sql=false < phase3_skip_rate.sql

# 2. Check for dependency failures
bq query --use_legacy_sql=false < phase3_dependency_check.sql

# 3. Check backfill queue
bq query --use_legacy_sql=false < phase3_backfill_queue.sql
```

### Weekly Review (Friday)

```bash
# 1. Weekly skip rate trend
bq query --use_legacy_sql=false '
SELECT
  DATE(processed_at) as date,
  ROUND(AVG(skip_rate), 1) as avg_skip_rate_pct
FROM (
  SELECT
    processed_at,
    SAFE_DIVIDE(
      COUNTIF(source_nbac_hash = LAG(source_nbac_hash) OVER w),
      COUNT(*) OVER w
    ) * 100 as skip_rate
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  WINDOW w AS (PARTITION BY game_date, game_id ORDER BY processed_at)
)
GROUP BY date
ORDER BY date DESC;
'

# 2. Cost savings estimate
echo "Calculate: (skip_rate_pct / 100) * estimated_weekly_cost"
```

---

## 🔧 Troubleshooting

### Issue: Skip Rate < 10%

**Diagnosis:**
```bash
# Check if Phase 2 data is changing frequently
bq query --use_legacy_sql=false '
WITH hash_changes AS (
  SELECT
    game_date,
    data_hash,
    LAG(data_hash) OVER (PARTITION BY game_date, game_id ORDER BY processed_at) as prev_hash
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
SELECT
  ROUND(SAFE_DIVIDE(
    COUNTIF(data_hash != prev_hash OR prev_hash IS NULL),
    COUNT(*)
  ) * 100, 1) as phase2_change_rate_pct
FROM hash_changes
WHERE prev_hash IS NOT NULL;
'
```

**Expected:** 40-60% (Phase 2 should also be skipping)

**If Phase 2 change rate is high:**
- Phase 2 data is volatile (upstream sources changing)
- This is normal during live games
- Phase 3 correctly reprocessing due to actual data changes

---

### Issue: Dependency Failures

**Check Phase 2 processor status:**
```bash
# Recent Phase 2 processing activity
gcloud logging read \
  "resource.type=cloud_run_revision \
   AND resource.labels.service_name=nba-phase2-raw-processors" \
  --limit=50 \
  --freshness=1h \
  --format=json | jq '.[].textPayload' | grep -i "error\|failed"
```

**Check Phase 2 table status:**
```bash
# Check when Phase 2 tables were last updated
bq query --use_legacy_sql=false '
SELECT
  table_name,
  MAX(processed_at) as last_updated,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_old,
  COUNT(*) as row_count
FROM (
  SELECT "nbac_gamebook" as table_name, processed_at FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  UNION ALL
  SELECT "bdl_boxscores", processed_at FROM `nba-props-platform.nba_raw.bdl_player_boxscores` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
GROUP BY table_name
ORDER BY hours_old DESC;
'
```

---

### Issue: High Backfill Queue (>50 games)

**Option 1: Wait for automatic backfill**
- Phase 3 processors should automatically process missing games

**Option 2: Manual trigger (if available)**
```bash
# Check if backfill script exists
ls -la bin/maintenance/phase3_backfill_check.py

# Run dry-run to see what would be processed
python bin/maintenance/phase3_backfill_check.py --dry-run

# Execute backfill
python bin/maintenance/phase3_backfill_check.py
```

---

## 📈 Add to Grafana (Optional)

### Panel 1: Phase 3 Skip Rate

**Query:**
```sql
WITH hash_comparison AS (
  SELECT
    source_nbac_hash,
    LAG(source_nbac_hash) OVER (
      PARTITION BY game_date, game_id ORDER BY processed_at
    ) as prev_hash
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
SELECT
  ROUND(SAFE_DIVIDE(
    COUNTIF(source_nbac_hash = prev_hash),
    COUNT(*)
  ) * 100, 1) as skip_rate_pct
FROM hash_comparison
WHERE prev_hash IS NOT NULL;
```

**Alert Threshold:**
- Warn: < 20%
- Critical: < 10%

### Panel 2: Phase 3 Processing Volume

**Use existing Cloud Monitoring:**
```
metric.type="run.googleapis.com/request_count"
resource.type="cloud_run_revision"
resource.labels.service_name="nba-phase3-analytics-processors"
```

---

## 🎯 Success Metrics (Week 1)

| Metric | Target | Action if Outside Range |
|--------|--------|------------------------|
| Skip Rate | 30-50% | Investigate if <20% or >80% |
| Dependency Failures | 0 | Check Phase 2 processors |
| Backfill Queue | <10 | Run backfill if >50 |
| Processing Errors | <1% | Review logs, fix issues |
| Cost Reduction | 25-35% | Calculate from skip rate |

---

## 📋 Checklist: First Week Monitoring

**Day 1 (Today):**
- [ ] Verify Phase 3 skip events are logged
- [ ] Run skip rate query
- [ ] Check for dependency failures
- [ ] Check backfill queue

**Day 2-7 (Daily):**
- [ ] Check skip rate (5 min)
- [ ] Review any errors (5 min)
- [ ] Document trends in shared doc

**End of Week:**
- [ ] Calculate average skip rate
- [ ] Calculate cost savings
- [ ] Decide: Proceed to Phase 4 or optimize Phase 3

---

**Created with:** Claude Code
**Next:** Phase 4 schema updates (after Phase 3 validation)
**Questions:** See `DEPLOYMENT_STATUS_SUMMARY.md` for full context
