# Grading System Monitoring Guide

**Last Updated:** 2026-01-18 (Session 99)
**Status:** Production

---

## Quick Health Check (5 minutes)

Run this to check overall grading system health:

```bash
# 1. Check recent grading coverage
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(*) as graded_predictions,
  MAX(graded_at) as last_graded,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(graded_at), HOUR) as hours_since_grading
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 10
'

# 2. Check for Phase 3 503 errors
gcloud functions logs read phase5b-grading --region=us-west2 --limit=100 | grep -i "503\|Phase 3"

# 3. Check Phase 3 service health
curl -s https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health | jq
```

**Expected Results:**
- ✅ Recent dates graded within last 24 hours
- ✅ No 503 errors in logs
- ✅ Phase 3 service returns `{"status":"healthy"}`

---

## Detailed Coverage Analysis

### Grading Coverage by Date

```sql
-- Check grading coverage percentage for last 14 days
WITH predictions_by_date AS (
  SELECT
    game_date,
    COUNT(DISTINCT CONCAT(player_lookup, '|', system_id)) as total_predictions
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND is_active = TRUE
  GROUP BY game_date
),
graded_by_date AS (
  SELECT
    game_date,
    COUNT(DISTINCT CONCAT(player_lookup, '|', system_id)) as graded_predictions
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  GROUP BY game_date
),
boxscores_by_date AS (
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_with_actuals
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  GROUP BY game_date
)
SELECT
  p.game_date,
  p.total_predictions,
  COALESCE(g.graded_predictions, 0) as graded,
  COALESCE(b.players_with_actuals, 0) as boxscores_available,
  ROUND(COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0), 1) as coverage_pct,
  CASE
    WHEN b.players_with_actuals = 0 THEN '⏳ No boxscores yet'
    WHEN COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0) > 80 THEN '✅ Excellent'
    WHEN COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0) > 70 THEN '✅ Good'
    WHEN COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0) > 40 THEN '🟡 Moderate'
    ELSE '❌ Low - investigate'
  END as status
FROM predictions_by_date p
LEFT JOIN graded_by_date g ON p.game_date = g.game_date
LEFT JOIN boxscores_by_date b ON p.game_date = b.game_date
ORDER BY p.game_date DESC
```

**Interpretation:**
- **>80%**: Excellent coverage
- **70-80%**: Good coverage (some predictions legitimately ungradeable)
- **40-70%**: Moderate coverage (may indicate partial grading issues)
- **<40%**: Low coverage (investigate immediately if boxscores exist)

---

## Phase 3 Auto-Heal Monitoring

### Check Auto-Heal Success Rate

```bash
# Check for auto-heal attempts in last 7 days
gcloud functions logs read phase5b-grading --region=us-west2 --limit=500 | \
  grep -E "auto-heal|Phase 3" | \
  grep -v "UserWarning" | \
  tail -30
```

**Healthy Patterns:**
- ✅ "Phase 3 analytics triggered successfully"
- ✅ "auto_heal_pending" → followed by successful grading later
- ❌ "Phase 3 analytics trigger failed: 503" (should NOT see this after Session 99 fix)
- ❌ "auto-heal failed" repeatedly

### Phase 3 Service Status

```bash
# Check Phase 3 service configuration
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="yaml(spec.template.metadata.annotations, status.conditions)"

# Should see:
# - minScale: 1  (Session 99 fix)
# - maxScale: 10
# - status: Ready = True
```

### Phase 3 Response Time Test

```bash
# Test Phase 3 endpoint response time
TOKEN=$(gcloud auth print-identity-token --audiences="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")

time curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-01-15",
    "end_date": "2026-01-15",
    "processors": ["PlayerGameSummaryProcessor"],
    "backfill_mode": true
  }' \
  -w "\nHTTP: %{http_code}\nTime: %{time_total}s\n"
```

**Expected:**
- HTTP 200
- Time: <10 seconds (should be 3-5s with warm instance)

---

## Cost Monitoring

### Phase 3 Service Cost

**Expected Cost:** ~$12-15/month for minScale=1

```bash
# Check current month costs for Phase 3
gcloud billing accounts list
# Then in Cloud Console > Billing > Reports:
# - Filter by: Service = Cloud Run
# - Filter by: SKU contains "CPU" or "Memory"
# - Group by: Service
```

**Alert Thresholds:**
- 🟢 <$20/month: Normal
- 🟡 $20-30/month: Higher than expected, monitor
- 🔴 >$30/month: Investigate (may indicate scaling issues)

### Total Grading Pipeline Cost

```bash
# Monthly cost breakdown (Cloud Console > Billing)
# Components:
# - Cloud Function (grading): ~$5-10/month
# - Phase 3 Cloud Run: ~$12-15/month (minScale=1)
# - BigQuery (grading queries): ~$1-2/month
# - Total expected: ~$18-27/month
```

---

## Alert Conditions

### Critical (Immediate Action)

1. **Grading Coverage <40% for 2+ consecutive days** (with boxscores available)
   - Indicates grading pipeline failure
   - Check grading function logs
   - Check Phase 3 503 errors

2. **Phase 3 503 Errors Recurring**
   - Should NOT happen after Session 99 (minScale=1)
   - Indicates cold start issues or service down
   - Check Phase 3 service status

3. **No Grading for 48+ Hours**
   - Check Cloud Scheduler: `nba-daily-grading` job status
   - Check grading function deployment status

### Warning (Monitor)

1. **Grading Coverage 40-70%** (with boxscores available)
   - May indicate partial issues
   - Check specific date coverage
   - Verify boxscore quality

2. **Phase 3 Cost >$30/month**
   - Higher than expected
   - Check scaling events
   - May need to adjust concurrency

### Info (Track Trends)

1. **Grading Coverage >80%**
   - Normal, healthy operation

2. **Occasional auto-heal attempts**
   - Normal for dates without boxscores yet
   - Should resolve when boxscores publish

---

## Dashboard Queries (Cloud Monitoring)

### Grading Lag (Hours Since Last Grading)

```sql
SELECT
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(graded_at), HOUR) as hours_since_grading
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
```

**Chart:** Line chart, alert if >48 hours

### Grading Volume (Last 7 Days)

```sql
SELECT
  game_date,
  COUNT(*) as graded_count
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

**Chart:** Bar chart showing daily grading volume

---

## Troubleshooting

See: `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md`

---

## Related Documentation

- **Phase 3 Fix:** `docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md`
- **Distributed Locking:** `docs/09-handoff/SESSION-97-MONITORING-COMPLETE.md`
- **Troubleshooting:** `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md`

---

**Last Reviewed:** 2026-01-18 (Session 99)
