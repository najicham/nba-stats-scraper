# Prediction Pipeline Runbook

**Last Updated:** December 26, 2025

This runbook covers the prediction pipeline from Phase 3 through Phase 6.

---

## Pipeline Overview

```
Schedule/Roster Data → Phase 3 (Analytics) → Phase 4 (Precompute) → Phase 5 (Predictions) → Phase 6 (Export)
```

### Two Processing Modes

1. **Same-Day (Pre-Game)**: Generate predictions for TODAY's games
   - Runs: 10:30 AM - 11:30 AM ET
   - Uses: `UpcomingPlayerGameContextProcessor` + `MLFeatureStoreProcessor` (same-day mode)
   - Output: Predictions ready by noon for tonight's games

2. **Overnight (Post-Game)**: Process YESTERDAY's game results
   - Runs: 11:00 PM - 11:30 PM PT
   - Uses: `PlayerGameSummaryProcessor` + full precompute pipeline
   - Output: Historical data for analytics and model training

---

## Daily Schedule (All Times ET)

| Time | Scheduler | What Happens |
|------|-----------|--------------|
| 10:30 AM | `same-day-phase3` | Phase 3: UpcomingPlayerGameContext for TODAY |
| 11:00 AM | `same-day-phase4` | Phase 4: MLFeatureStore for TODAY (same-day) |
| 11:30 AM | `same-day-predictions` | Phase 5: Generate predictions for TODAY |
| 1:00 PM | `phase6-tonight-picks` | Phase 6: Export tonight's predictions |
| 7-11 PM | `live-export-evening` | Phase 6: Live scores (every 3 min) |
| 2:00 AM | `ml-feature-store-daily` | Phase 4: Process YESTERDAY's data |

---

## Manual Prediction Generation

### For Today's Games (Same-Day)

```bash
TOKEN=$(gcloud auth print-identity-token)

# Step 1: Phase 3 - Get expected players
curl -s -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "TODAY",
    "end_date": "TODAY",
    "processors": ["UpcomingPlayerGameContextProcessor"],
    "backfill_mode": true
  }'

# Wait 30 seconds for Phase 3 to complete

# Step 2: Phase 4 - Generate ML features
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "TODAY",
    "processors": ["MLFeatureStoreProcessor"],
    "backfill_mode": false,
    "strict_mode": false,
    "skip_dependency_check": true
  }'

# Wait 60 seconds for Phase 4 to complete

# Step 3: Phase 5 - Generate predictions
curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force": true}'
```

### For a Specific Date

Replace "TODAY" with the date (e.g., "2025-12-27"):

```bash
DATE="2025-12-27"
TOKEN=$(gcloud auth print-identity-token)

# Step 1: Phase 3
curl -s -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"start_date\": \"$DATE\",
    \"end_date\": \"$DATE\",
    \"processors\": [\"UpcomingPlayerGameContextProcessor\"],
    \"backfill_mode\": true
  }"

# Step 2: Phase 4
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"analysis_date\": \"$DATE\",
    \"processors\": [\"MLFeatureStoreProcessor\"],
    \"backfill_mode\": false,
    \"strict_mode\": false,
    \"skip_dependency_check\": true
  }"

# Step 3: Phase 5
curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"game_date\": \"$DATE\", \"force\": true}"
```

---

## Backfilling Historical Predictions

For games that have already been played, use the full backfill mode:

```bash
DATE="2025-12-25"
TOKEN=$(gcloud auth print-identity-token)

# Step 1: Phase 3 - PlayerGameSummary (uses gamebook data for who actually played)
curl -s -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"start_date\": \"$DATE\",
    \"end_date\": \"$DATE\",
    \"processors\": [\"PlayerGameSummaryProcessor\"],
    \"backfill_mode\": true
  }"

# Step 2: Phase 4 - Full backfill mode
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"analysis_date\": \"$DATE\",
    \"processors\": [\"MLFeatureStoreProcessor\"],
    \"backfill_mode\": true
  }"

# Step 3: Phase 5
curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"game_date\": \"$DATE\", \"force\": true}"
```

---

## Checking Prediction Status

### Are predictions being generated?

```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions, MAX(created_at) as last_created
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'ensemble_v1' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date DESC LIMIT 7"
```

### Check prediction coordinator status

```bash
# If you have a batch_id from starting predictions:
curl -s "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status?batch_id=<BATCH_ID>" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Check Phase 4 completion in Firestore

```bash
# View Phase 4 completion for a date
gcloud firestore documents get \
  projects/nba-props-platform/databases/\(default\)/documents/phase4_completion/2025-12-26 \
  --format=json | jq .
```

---

## Troubleshooting

### "Missing critical dependencies"

**Cause:** Phase 4 defensive checks failing

**Solution:** Use same-day mode flags:
```json
{
  "strict_mode": false,
  "skip_dependency_check": true
}
```

### "Batch already in progress" (409)

**Cause:** A prediction batch is already running

**Solution:** Wait for completion or use `force: true`:
```json
{"force": true}
```

### Phase 4 timeout when calling prediction coordinator

**Cause:** Orchestrator has 30s timeout

**Impact:** Minimal - Pub/Sub message was still sent, coordinator will process eventually

### No predictions for today

1. Check if games exist for today:
```bash
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | jq '.scoreboard.games | length'
```

2. Check if Phase 3 ran:
```bash
bq query --use_legacy_sql=false "
SELECT * FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE()
LIMIT 5"
```

3. Check if Phase 4 ran:
```bash
bq query --use_legacy_sql=false "
SELECT * FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
LIMIT 5"
```

---

## Phase Parameters Reference

### Phase 3 `/process-date-range`

| Parameter | Type | Description |
|-----------|------|-------------|
| `start_date` | string | Start date or "TODAY" |
| `end_date` | string | End date or "TODAY" |
| `processors` | array | Processor names to run |
| `backfill_mode` | bool | Bypass dependency checks |

### Phase 4 `/process-date`

| Parameter | Type | Description |
|-----------|------|-------------|
| `analysis_date` | string | Date, "TODAY", or "AUTO" (yesterday) |
| `processors` | array | Processor names to run |
| `backfill_mode` | bool | Use historical data mode |
| `strict_mode` | bool | Enable/disable defensive gap checks |
| `skip_dependency_check` | bool | Skip Phase 4 dependency validation |

### Prediction Coordinator `/start`

| Parameter | Type | Description |
|-----------|------|-------------|
| `game_date` | string | Date (defaults to today) |
| `force` | bool | Force even if batch running |
| `min_minutes` | int | Minimum projected minutes (default 15) |
| `use_multiple_lines` | bool | Generate multiple line variants |

---

## Related Files

- `data_processors/analytics/main_analytics_service.py` - Phase 3 service
- `data_processors/precompute/main_precompute_service.py` - Phase 4 service
- `predictions/coordinator/coordinator.py` - Phase 5 coordinator
- `bin/orchestrators/setup_same_day_schedulers.sh` - Scheduler setup script
