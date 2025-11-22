# Pattern Monitoring - Quick Reference

**Created:** 2025-11-21
**Purpose:** Quick copy-paste queries for monitoring processing patterns
**For:** Daily monitoring and troubleshooting

---

## 🚨 Critical Health Checks (Run Daily)

### 1. Phase 2 Skip Rate (Last 24 Hours)

```sql
-- Quick health check: Are Phase 2 processors skipping writes?
WITH recent_runs AS (
  SELECT
    REGEXP_EXTRACT(_TABLE_SUFFIX, r'^(.+)$') as table_name,
    COUNT(*) as total_runs,
    COUNT(DISTINCT data_hash) as unique_hashes
  FROM `nba-props-platform.nba_raw.*`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND data_hash IS NOT NULL
  GROUP BY table_name
)
SELECT
  table_name,
  total_runs,
  unique_hashes,
  total_runs - unique_hashes as skipped_writes,
  ROUND(SAFE_DIVIDE(total_runs - unique_hashes, total_runs) * 100, 1) as skip_rate_pct
FROM recent_runs
WHERE total_runs > 1
ORDER BY skip_rate_pct DESC;
```

**Expected:** 30-60% skip rate
**Alert if:** < 10% (pattern not working) or > 80% (possible duplicate processing)

---

### 2. Phase 3 Skip Rate (Last 24 Hours)

```sql
-- Quick health check: Are Phase 3 processors skipping processing?
WITH hash_comparison AS (
  SELECT
    game_date,
    game_id,
    source_nbac_hash,
    LAG(source_nbac_hash) OVER (
      PARTITION BY game_date, game_id
      ORDER BY processed_at
    ) as prev_hash
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
```

**Expected:** 30-50% skip rate
**Alert if:** < 20% (Phase 2 data constantly changing)

---

### 3. Dependency Check Failures (Last 6 Hours)

```sql
-- Critical: Are Phase 3 processors failing due to missing dependencies?
SELECT
  processor,
  COUNT(*) as failures,
  STRING_AGG(DISTINCT missing_source, ', ') as missing_sources
FROM (
  -- Player game summary
  SELECT
    'player_game_summary' as processor,
    game_date,
    CASE
      WHEN source_nbac_rows_found IS NULL OR source_nbac_rows_found = 0
        THEN 'nbac_gamebook'
      WHEN source_bdl_rows_found IS NULL OR source_bdl_rows_found = 0
        THEN 'bdl_boxscores'
    END as missing_source
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
    AND (source_nbac_rows_found IS NULL OR source_nbac_rows_found = 0
         OR source_bdl_rows_found IS NULL OR source_bdl_rows_found = 0)
)
WHERE missing_source IS NOT NULL
GROUP BY processor;
```

**Expected:** 0 failures
**Alert if:** > 0 (critical dependency missing)

---

### 4. Backfill Queue Size

```sql
-- How many games need backfill processing?
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
  MAX(p2.game_date) as newest_missing_date
FROM phase2_games p2
LEFT JOIN phase3_games p3 USING (game_date, game_id)
WHERE p3.game_id IS NULL;
```

**Expected:** < 10 games
**Alert if:** > 50 games (run backfill job)

---

## 📊 Performance Metrics

### 5. Operations Saved Today

```sql
-- How many operations did we save today vs without patterns?
WITH phase2_stats AS (
  SELECT
    COUNT(*) as writes,
    COUNT(*) * 2 as potential_without_idempotency
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE DATE(processed_at) = CURRENT_DATE()
),
phase3_stats AS (
  SELECT
    COUNT(*) as runs,
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id ORDER BY processed_at
      )
    ) as skips
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE DATE(processed_at) = CURRENT_DATE()
)
SELECT
  p2.writes as phase2_actual_writes,
  p2.potential_without_idempotency - p2.writes as phase2_writes_saved,
  p3.skips as phase3_processing_saved,
  (p2.potential_without_idempotency - p2.writes) + p3.skips as total_operations_saved
FROM phase2_stats p2, phase3_stats p3;
```

---

### 6. Source Data Freshness

```sql
-- How old is Phase 2 data when Phase 3 uses it?
SELECT
  DATE(processed_at) as date,
  ROUND(AVG(TIMESTAMP_DIFF(processed_at, source_nbac_last_updated, HOUR)), 1) as avg_age_hours,
  ROUND(MAX(TIMESTAMP_DIFF(processed_at, source_nbac_last_updated, HOUR)), 1) as max_age_hours,
  COUNT(*) as records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND source_nbac_last_updated IS NOT NULL
GROUP BY date
ORDER BY date DESC;
```

**Expected:** < 6 hours average
**Alert if:** > 24 hours (stale Phase 2 data)

---

## 🔍 Troubleshooting Queries

### 7. Find Games with Processing Issues

```sql
-- Which games failed or had incomplete processing?
SELECT
  game_date,
  game_id,
  COUNT(*) as processing_attempts,
  MAX(processed_at) as last_attempt,
  ROUND(AVG(source_nbac_completeness_pct), 1) as avg_completeness,
  STRING_AGG(
    DISTINCT CASE
      WHEN source_nbac_rows_found = 0 THEN 'missing_nbac'
      WHEN source_bdl_rows_found = 0 THEN 'missing_bdl'
      WHEN source_nbac_completeness_pct < 80 THEN 'incomplete_nbac'
    END,
    ', '
  ) as issues
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND (
    source_nbac_rows_found = 0
    OR source_bdl_rows_found = 0
    OR source_nbac_completeness_pct < 80
  )
GROUP BY game_date, game_id
ORDER BY last_attempt DESC
LIMIT 20;
```

---

### 8. Hash Change Analysis (Why is Phase 3 not skipping?)

```sql
-- Which Phase 2 sources are changing frequently?
WITH hash_changes AS (
  SELECT
    game_date,
    game_id,
    processed_at,
    -- Track changes in each source
    source_nbac_hash != LAG(source_nbac_hash) OVER w as nbac_changed,
    source_bdl_hash != LAG(source_bdl_hash) OVER w as bdl_changed,
    source_odds_hash != LAG(source_odds_hash) OVER w as odds_changed
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  WINDOW w AS (PARTITION BY game_date, game_id ORDER BY processed_at)
)
SELECT
  'nbac' as source,
  COUNTIF(nbac_changed) as changes,
  COUNT(*) as total_runs,
  ROUND(SAFE_DIVIDE(COUNTIF(nbac_changed), COUNT(*)) * 100, 1) as change_rate_pct
FROM hash_changes
WHERE nbac_changed IS NOT NULL

UNION ALL

SELECT
  'bdl' as source,
  COUNTIF(bdl_changed) as changes,
  COUNT(*) as total_runs,
  ROUND(SAFE_DIVIDE(COUNTIF(bdl_changed), COUNT(*)) * 100, 1) as change_rate_pct
FROM hash_changes
WHERE bdl_changed IS NOT NULL

UNION ALL

SELECT
  'odds' as source,
  COUNTIF(odds_changed) as changes,
  COUNT(*) as total_runs,
  ROUND(SAFE_DIVIDE(COUNTIF(odds_changed), COUNT(*)) * 100, 1) as change_rate_pct
FROM hash_changes
WHERE odds_changed IS NOT NULL

ORDER BY change_rate_pct DESC;
```

---

### 9. Specific Game Deep Dive

```sql
-- Detailed history for a specific game (replace game_id)
SELECT
  processed_at,
  source_nbac_hash,
  source_bdl_hash,
  source_nbac_rows_found,
  source_bdl_rows_found,
  source_nbac_completeness_pct,
  TIMESTAMP_DIFF(processed_at, LAG(processed_at) OVER (ORDER BY processed_at), MINUTE) as minutes_since_last_run,
  source_nbac_hash = LAG(source_nbac_hash) OVER (ORDER BY processed_at) as hash_unchanged
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_id = '0022400259'  -- Replace with actual game_id
ORDER BY processed_at DESC
LIMIT 10;
```

---

## 📈 Weekly Summary Report

### 10. Weekly Pattern Efficiency Summary

```sql
-- Complete efficiency report for the week
WITH phase2_metrics AS (
  SELECT
    'Phase 2: Smart Idempotency' as metric,
    COUNT(*) as total_operations,
    COUNT(DISTINCT data_hash) as unique_writes,
    COUNT(*) - COUNT(DISTINCT data_hash) as saved,
    ROUND(SAFE_DIVIDE(
      COUNT(*) - COUNT(DISTINCT data_hash),
      COUNT(*)
    ) * 100, 1) as efficiency_pct
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
),
phase3_metrics AS (
  SELECT
    'Phase 3: Smart Reprocessing' as metric,
    COUNT(*) as total_operations,
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id ORDER BY processed_at
      )
    ) as skipped,
    COUNTIF(
      source_nbac_hash = LAG(source_nbac_hash) OVER (
        PARTITION BY game_date, game_id ORDER BY processed_at
      )
    ) as saved,
    ROUND(SAFE_DIVIDE(
      COUNTIF(
        source_nbac_hash = LAG(source_nbac_hash) OVER (
          PARTITION BY game_date, game_id ORDER BY processed_at
        )
      ),
      COUNT(*)
    ) * 100, 1) as efficiency_pct
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
SELECT * FROM phase2_metrics
UNION ALL
SELECT * FROM phase3_metrics
UNION ALL
SELECT
  'TOTAL SAVINGS' as metric,
  p2.total_operations + p3.total_operations as total_operations,
  NULL as unique_writes,
  p2.saved + p3.saved as saved,
  ROUND(SAFE_DIVIDE(
    p2.saved + p3.saved,
    p2.total_operations + p3.total_operations
  ) * 100, 1) as efficiency_pct
FROM phase2_metrics p2, phase3_metrics p3;
```

---

## 🚀 Quick Actions

### If Skip Rate is Low (<20%):
```bash
# Check if Phase 2 data is actually changing
# Run query #8 to see which sources are volatile
# Review Phase 2 processor logs for patterns
```

### If Dependency Failures Occur:
```bash
# Check Phase 2 processor status
gcloud run services describe raw-data-processor --region=us-west2

# Check Phase 2 scraper logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers" --limit=50
```

### If Backfill Queue Growing:
```bash
# Run backfill detection
python bin/maintenance/phase3_backfill_check.py --dry-run

# Process backfill
python bin/maintenance/phase3_backfill_check.py
```

---

## 📱 Alert Thresholds Summary

| Metric | Good | Warning | Critical | Action |
|--------|------|---------|----------|--------|
| Phase 2 Skip Rate | 30-60% | 10-30% | <10% or >80% | Investigate hash computation |
| Phase 3 Skip Rate | 30-50% | 15-30% | <15% | Check Phase 2 volatility |
| Dependency Failures | 0 | 1-5 | >5 | Fix Phase 2 immediately |
| Backfill Queue | <10 | 10-50 | >50 | Run backfill job |
| Source Age | <6h | 6-24h | >24h | Check Phase 2 schedule |
| Completeness | >90% | 80-90% | <80% | Investigate data sources |

---

## 🔗 Related Documentation

- **Full Monitoring Guide:** `08-pattern-efficiency-monitoring.md`
- **Grafana Dashboard:** `monitoring/dashboards/nba_pattern_efficiency_dashboard.json`
- **Pattern Implementation:** `docs/guides/processor-patterns/`
- **Backfill Guide:** `docs/guides/03-backfill-deployment-guide.md`

---

**Created with:** Claude Code
**Last Updated:** 2025-11-21
**Maintained by:** Platform Engineering
