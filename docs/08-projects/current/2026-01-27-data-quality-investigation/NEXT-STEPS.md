# NEXT STEPS - Jan 27 Data Quality Fix

**Status**: Bug fixed (commit 6311464d), ready for deployment ✅
**Action Required**: Deploy + Reprocess
**Estimated Time**: 20 minutes total

---

## Quick Command Reference

### 1. DEPLOY (3-5 min)
```bash
cd /home/naji/code/nba-stats-scraper
./scripts/deploy/deploy-analytics.sh

# Wait for deployment
watch -n 10 'gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"'
# Press Ctrl+C when revision changes from 00124-hfl
```

### 2. REPROCESS TEAM STATS (2-3 min)
```bash
API_KEY=$(gcloud secrets versions access latest --secret="analytics-api-keys")

curl -X POST \
  "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"start_date":"2026-01-26","end_date":"2026-01-27","processors":["team_offense_game_summary"],"backfill_mode":true}'
```

### 3. WAIT 10 SECONDS
```bash
sleep 10
```

### 4. REPROCESS PLAYER STATS (3-5 min)
```bash
curl -X POST \
  "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"start_date":"2026-01-26","end_date":"2026-01-27","processors":["player_game_summary"],"backfill_mode":true}'
```

### 5. VERIFY DATA QUALITY (30 sec)
```bash
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNT(*) as total,
  COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) as valid,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) / COUNT(*), 1) as pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date IN ('2026-01-26', '2026-01-27')
GROUP BY game_date ORDER BY game_date"
```

**Expected**: Both dates show pct >= 90%

### 6. TRIGGER PREDICTIONS (3-5 min)
```bash
python3 bin/predictions/clear_and_restart_predictions.py --game-date 2026-01-27
```

### 7. VERIFY PREDICTIONS (30 sec)
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27' AND is_active = TRUE
GROUP BY game_date"
```

**Expected**: ~220 predictions for Jan 27

---

## One-Liner (After Deployment)

```bash
API_KEY=$(gcloud secrets versions access latest --secret="analytics-api-keys") && \
curl -sX POST https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"start_date":"2026-01-26","end_date":"2026-01-27","processors":["team_offense_game_summary"],"backfill_mode":true}' && \
sleep 10 && \
curl -sX POST https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"start_date":"2026-01-26","end_date":"2026-01-27","processors":["player_game_summary"],"backfill_mode":true}' && \
python3 bin/predictions/clear_and_restart_predictions.py --game-date 2026-01-27
```

---

## Success Criteria

✅ Jan 26: usage_rate coverage >= 90%
✅ Jan 27: usage_rate coverage >= 90%
✅ Jan 27: ~220 predictions generated

---

## Troubleshooting

### If Cloud Run returns 403 Forbidden
```bash
# Use local execution instead
PYTHONPATH=/home/naji/code/nba-stats-scraper \
  python3 data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py \
  --start-date 2026-01-26 --end-date 2026-01-27 --backfill-mode

PYTHONPATH=/home/naji/code/nba-stats-scraper \
  python3 data_processors/analytics/player_game_summary/player_game_summary_processor.py \
  --start-date 2026-01-26 --end-date 2026-01-27 --backfill-mode
```

### If deployment fails
```bash
# Check deployment logs
gcloud logging read "resource.type=cloud_run_revision" --limit=50 --freshness=10m

# Check service status
gcloud run services describe nba-phase3-analytics-processors --region=us-west2
```

### If predictions don't generate
```bash
# Check coordinator logs
gcloud run services logs read prediction-coordinator --region=us-west2 --limit=50

# Check for blocked batches
bq query --use_legacy_sql=false "
SELECT batch_id, created_at, is_complete, total_predictions
FROM \`nba-props-platform.nba_predictions.coordinator_batches\`
WHERE game_date = '2026-01-27'
ORDER BY created_at DESC
LIMIT 5"
```

---

## Context

- **Bug**: Line 424 in analytics_base.py used `analysis_date` before definition
- **Fix**: Commit 6311464d defines variable before use
- **Root Issue**: game_id mismatch (AWAY_HOME vs HOME_AWAY) prevented team stats JOIN
- **Impact**: 57.8% usage_rate coverage instead of 90%+

See SESSION-SUMMARY.md for full details.
