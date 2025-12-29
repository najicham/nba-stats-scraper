# Morning Pipeline Health Checklist - Dec 29, 2025

**Session 185 deployed Phase 5 with MERGE fix for prediction duplicates at ~10 PM ET Dec 28**

---

## 1. Verify Prediction Duplicates Fix

The MERGE fix was deployed but hasn't processed new data yet. Check if Dec 29 predictions have duplicates:

```bash
# Check Dec 29 predictions - should show 1.0 copies per player (no duplicates)
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as total_rows,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(COUNT(*) / COUNT(DISTINCT player_lookup), 2) as avg_copies_per_player
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-29'
  AND is_active = TRUE
GROUP BY game_date
"
```

**Expected:** `avg_copies_per_player` should be 1.0 (or close to 1.0 for multiple prop types)

If still showing duplicates, check prediction worker logs:
```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"MERGE"' --limit=10 --freshness=12h
```

---

## 2. Verify All Services Are Healthy

```bash
# Check all 4 pipeline services
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-worker; do
  echo -n "$svc: "
  curl -s "$(gcloud run services describe $svc --region=us-west2 --format='get(status.url)')/health" 2>/dev/null || echo "FAILED"
done
```

---

## 3. Check Tonight's API Data (Dec 29 games)

```bash
# Check if tonight's predictions are exported
gsutil cat "gs://nba-props-platform-api/v1/tonight/all-players.json" | head -c 500

# Check file freshness
gsutil stat "gs://nba-props-platform-api/v1/tonight/all-players.json" | grep Updated
```

**Expected:** File should contain Dec 29 game data, updated after 2 PM ET today

---

## 4. Check Scheduler Jobs Ran Successfully

```bash
# List scheduler jobs and their last run times
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,state,lastAttemptTime)"
```

Key jobs to verify:
- `same-day-phase3` - 1:30 PM ET
- `same-day-phase4` - 1:35 PM ET
- `same-day-predictions` - 1:45 PM ET
- `phase6-tonight-picks` - 2:00 PM ET

---

## 5. Check Circuit Breakers

```bash
# Check if any circuit breakers are currently tripped
bq query --use_legacy_sql=false --format=pretty "
SELECT processor_name, COUNT(*) as tripped_count
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
GROUP BY processor_name
ORDER BY tripped_count DESC
"
```

**Expected:** Empty result or very few entries (24-hour lockout should auto-clear)

---

## 6. Check Boxscore Data Completeness

```bash
# Check if overnight boxscore collection worked (runs at 4 AM ET)
# Should have data for Dec 28 games
bq query --use_legacy_sql=false --format=pretty "
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.bdl_boxscores
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
GROUP BY game_date
ORDER BY game_date DESC
"
```

---

## 7. Check for Errors in Logs

```bash
# Check for any errors across all services in last 12 hours
gcloud logging read 'severity=ERROR AND resource.type="cloud_run_revision"' \
  --limit=20 --format="table(timestamp,resource.labels.service_name,textPayload)" --freshness=12h
```

---

## 8. Quick Full Pipeline Status

```bash
# Run the quick pipeline check script
/home/naji/code/nba-stats-scraper/bin/monitoring/quick_pipeline_check.sh
```

---

## Summary of Session 185 Changes

1. **Fixed Phase 5 deploy script** - Changed default from `dev` to `prod`
2. **Deployed prediction-worker `00007-xlr`** - Contains MERGE fix for duplicates
3. **All 4 pipeline phases now deployed** with Session 184 robustness improvements:
   - 24-hour circuit breaker lockout (was 7 days)
   - MERGE for prediction deduplication
   - Auto-reset circuit breakers on data availability

---

## If Something Is Wrong

### No predictions for today:
```bash
# Check Phase 4 logs
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors"' --limit=20 --freshness=6h

# Manually trigger same-day predictions
gcloud scheduler jobs run same-day-predictions --location=us-west2
```

### API file not updated:
```bash
# Manually trigger tonight export
gcloud scheduler jobs run phase6-tonight-picks --location=us-west2
```

### Circuit breakers blocking players:
```bash
# Clear all circuit breakers for today
bq query --use_legacy_sql=false "
UPDATE nba_orchestration.reprocess_attempts
SET circuit_breaker_tripped = FALSE
WHERE circuit_breaker_until > CURRENT_TIMESTAMP()
"
```
