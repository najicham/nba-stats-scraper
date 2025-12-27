# Daily Orchestration Validation Checklist

**Purpose:** Comprehensive checklist for validating daily pipeline health. Run this each morning to ensure the pipeline is working correctly.

**When to Run:**
- Morning after game nights (check overnight processing)
- Around noon on game days (check same-day predictions)
- Anytime you suspect issues

**Time Required:** 5-10 minutes for routine check

---

## Recommended: Comprehensive Validation Script

**Best option for thorough validation:**

```bash
# Run full pipeline validation for yesterday
PYTHONPATH=. python3 bin/validate_pipeline.py $(date -d 'yesterday' +%Y-%m-%d)

# Or for a specific date with detailed output
PYTHONPATH=. python3 bin/validate_pipeline.py 2025-12-26 --legacy-view

# JSON output for programmatic use
PYTHONPATH=. python3 bin/validate_pipeline.py 2025-12-26 --format json
```

This script validates all 5 phases, checks chain completeness, and identifies missing data.

---

## Quick Summary Commands

Run these first for a quick health overview:

```bash
# 1. Check for errors in last 2 hours
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=2h

# 2. Check today's game schedule
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | \
  jq '{total_games: (.scoreboard.games | length), games: [.scoreboard.games[] | {away: .awayTeam.teamTricode, home: .homeTeam.teamTricode, status: .gameStatusText}]}'

# 3. Check prediction counts for recent dates
bq query --use_legacy_sql=false --format=pretty "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY) AND is_active = TRUE
GROUP BY game_date ORDER BY game_date DESC"

# 4. Check all services healthy
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  echo -n "$svc: "
  STATUS=$(curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" -H "Authorization: Bearer $(gcloud auth print-identity-token)" 2>/dev/null | jq -r '.status' 2>/dev/null)
  echo "${STATUS:-FAILED}"
done

# 5. Check orchestrator functions healthy
for fn in phase2-to-phase3-orchestrator phase3-to-phase4-orchestrator phase4-to-phase5-orchestrator; do
  echo -n "$fn: "
  STATE=$(gcloud functions describe $fn --region=us-west2 --gen2 --format="value(state)" 2>/dev/null)
  echo "${STATE:-NOT_FOUND}"
done
```

---

## Detailed Validation Steps

### Step 1: Check Overnight Processing (Run morning after game night)

#### 1.1 Verify Yesterday's Games Were Processed

```bash
# Get yesterday's date
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
echo "Checking data for: $YESTERDAY"

# Check boxscores
bq query --use_legacy_sql=false --format=pretty "
SELECT 'BDL Boxscores' as source, COUNT(DISTINCT game_id) as games, COUNT(*) as players
FROM nba_raw.bdl_player_boxscores WHERE game_date = '$YESTERDAY'"

# Check gamebooks
bq query --use_legacy_sql=false --format=pretty "
SELECT 'Gamebooks' as source, COUNT(DISTINCT game_id) as games, COUNT(*) as players
FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = '$YESTERDAY'"
```

**Expected:** Both should show same number of games (matching last night's schedule).

#### 1.2 Check for Processing Failures

```bash
# Check run history for failures
bq query --use_legacy_sql=false --format=pretty "
SELECT processor_name, data_date, status, records_processed, errors
FROM nba_reference.processor_run_history
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND status IN ('failed', 'error')
ORDER BY started_at DESC
LIMIT 10"
```

**Expected:** No failed runs. If failures exist, check the `errors` column for details.

#### 1.3 Check Overnight Scheduler Runs

```bash
# Check if overnight schedulers ran (11 PM - midnight PT)
gcloud logging read 'resource.type="cloud_scheduler_job" AND (resource.labels.job_id="player-composite-factors-daily" OR resource.labels.job_id="player-daily-cache-daily" OR resource.labels.job_id="ml-feature-store-daily")' \
  --limit=10 --format="table(timestamp,resource.labels.job_id)" --freshness=12h
```

---

### Step 2: Check Same-Day Processing (Run around noon on game days)

#### 2.1 Did Morning Schedulers Run?

```bash
# Check same-day schedulers (10:30 AM, 11:00 AM, 11:30 AM ET)
gcloud logging read 'resource.type="cloud_scheduler_job" AND (resource.labels.job_id="same-day-phase3" OR resource.labels.job_id="same-day-phase4" OR resource.labels.job_id="same-day-predictions")' \
  --limit=10 --format="table(timestamp,resource.labels.job_id)" --freshness=6h
```

**Expected:** All three should have run within the last 6 hours.

#### 2.2 Are Today's Predictions Ready?

```bash
TODAY=$(date +%Y-%m-%d)

# Check prediction count
bq query --use_legacy_sql=false --format=pretty "
SELECT COUNT(*) as predictions, COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date = '$TODAY' AND is_active = TRUE"

# Check if we have games today
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | jq '.scoreboard.games | length'
```

**Expected:**
- If games today: predictions count > 0 (typically 100-300 per game)
- If no games: predictions = 0 is fine

#### 2.3 Check Phase 3 Analytics

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT game_date, COUNT(*) as players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE()
GROUP BY game_date"
```

**Expected:** Player count matching expected players for today's games.

---

### Step 3: Check Data Freshness

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'BDL Boxscores' as table_name,
  MAX(game_date) as latest_date,
  DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_stale
FROM nba_raw.bdl_player_boxscores
UNION ALL
SELECT 'Gamebooks', MAX(game_date), DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
FROM nba_raw.nbac_gamebook_player_stats
UNION ALL
SELECT 'BettingPros Props', MAX(game_date), DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
FROM nba_raw.bettingpros_player_points_props
UNION ALL
SELECT 'Schedule', MAX(game_date), DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
FROM nba_reference.nba_schedule
UNION ALL
SELECT 'Predictions', MAX(game_date), DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
FROM nba_predictions.player_prop_predictions WHERE is_active = TRUE
ORDER BY days_stale DESC"
```

**Expected Staleness:**
- BDL Boxscores: 0-1 days (depends on if games yesterday)
- Gamebooks: 0-1 days
- BettingPros Props: 0 days (should be today if games today)
- Schedule: Always 0 (should include future games)
- Predictions: 0 days if games today

---

### Step 4: Check for Error Patterns

```bash
# Get error summary by service
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=50 --format="json" --freshness=24h | \
  jq -r '.[].resource.labels.service_name' | sort | uniq -c | sort -rn

# Check specific error messages
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=20 --format="table(timestamp,resource.labels.service_name,textPayload)" --freshness=6h
```

**Common Issues to Look For:**
- `403` proxy errors - transient, should retry
- `BigQuery permission denied` - IAM issue
- `Missing 'message' field` - malformed Pub/Sub (usually harmless)
- `Already processed` - idempotency working correctly (not an error)

---

### Step 5: Check Live Export (During/After Games)

```bash
# Check latest live export
gsutil cat "gs://nba-props-platform-api/v1/live/today.json" | \
  jq '{updated_at, total_games, games_in_progress, games_final, total_predictions}'

# Check live export function logs
gcloud logging read 'resource.type="cloud_function" AND resource.labels.function_name="live-export"' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=1h
```

---

### Step 6: Check Orchestration State (Firestore)

```bash
# Check if today's orchestration completed
TODAY=$(date +%Y-%m-%d)

python3 << EOF
from google.cloud import firestore
db = firestore.Client()

# Phase 2 completion (monitoring only)
doc = db.collection('phase2_completion').document('$TODAY').get()
if doc.exists:
    data = doc.to_dict()
    count = len([k for k in data if not k.startswith('_')])
    print(f"Phase 2: {count} processors tracked")
else:
    print("Phase 2: No data yet")

# Phase 3 completion
doc = db.collection('phase3_completion').document('$TODAY').get()
if doc.exists:
    data = doc.to_dict()
    count = len([k for k in data if not k.startswith('_')])
    triggered = data.get('_triggered', False)
    print(f"Phase 3: {count}/5 complete, Phase 4 triggered: {triggered}")
else:
    print("Phase 3: No data yet")

# Phase 4 completion
doc = db.collection('phase4_completion').document('$TODAY').get()
if doc.exists:
    data = doc.to_dict()
    triggered = data.get('_triggered', False)
    print(f"Phase 4: Phase 5 triggered: {triggered}")
else:
    print("Phase 4: No data yet")
EOF
```

**Expected:** On game days after noon, Phase 3/4/5 should show triggered.

---

### Step 7: Check Pub/Sub Health

```bash
# Check for message backlog (stuck messages)
echo "=== Pub/Sub Subscription Backlogs ==="
for sub in nba-phase1-scrapers-complete-sub nba-phase2-raw-complete-sub nba-phase3-analytics-sub nba-phase4-trigger-sub; do
  BACKLOG=$(gcloud pubsub subscriptions describe $sub --format="value(numMessagesUndelivered)" 2>/dev/null)
  echo "$sub: ${BACKLOG:-0} undelivered"
done

# Check Dead Letter Queues
echo ""
echo "=== Dead Letter Queue Counts ==="
for dlq in nba-phase1-scrapers-complete-dlq-sub nba-phase2-raw-complete-dlq-sub; do
  COUNT=$(gcloud pubsub subscriptions describe $dlq --format="value(numMessagesUndelivered)" 2>/dev/null)
  if [ -n "$COUNT" ] && [ "$COUNT" -gt 0 ]; then
    echo "⚠️  $dlq: $COUNT messages (needs attention)"
  else
    echo "$dlq: 0 messages"
  fi
done
```

**Expected:** Backlogs should be 0 or very low. DLQ > 0 means messages failed permanently.

---

### Step 8: Check Scraper Execution Log (Phase 1)

```bash
# Recent scraper activity
bq query --use_legacy_sql=false --format=pretty "
SELECT
  scraper_name,
  status,
  FORMAT_TIMESTAMP('%H:%M ET', created_at, 'America/New_York') as run_time,
  CASE WHEN error_message IS NOT NULL THEN 'ERROR' ELSE 'OK' END as has_error
FROM nba_orchestration.scraper_execution_log
WHERE DATE(created_at, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY created_at DESC
LIMIT 15"
```

**Expected:** Recent scrapers should show `status: success` and no errors.

---

## Common Issues & Quick Fixes

### Issue: No predictions for today

**Diagnosis:**
```bash
# Check if Phase 3 ran
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_analytics.upcoming_player_game_context WHERE game_date = CURRENT_DATE()"

# Check if Phase 4 ran
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = CURRENT_DATE()"
```

**Fix - Manually trigger pipeline:**
```bash
# Trigger Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Wait 30 seconds, then trigger Phase 4
sleep 30 && gcloud scheduler jobs run same-day-phase4 --location=us-west2

# Wait 60 seconds, then trigger predictions
sleep 60 && gcloud scheduler jobs run same-day-predictions --location=us-west2
```

### Issue: Yesterday's boxscores missing

**Diagnosis:**
```bash
# Check if file exists in GCS
gsutil ls "gs://nba-scraped-data/ball-dont-lie/boxscores/$(date -d 'yesterday' +%Y-%m-%d)/"

# Check run history
bq query --use_legacy_sql=false "
SELECT * FROM nba_reference.processor_run_history
WHERE processor_name = 'BdlBoxscoresProcessor'
  AND data_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY started_at DESC LIMIT 5"
```

**Fix - Re-trigger processing:**
```bash
# If file exists but 0 rows processed, clear run history and re-trigger
YESTERDAY=$(date -d 'yesterday' +%Y-%m-%d)

# Clear stale run history
bq query --use_legacy_sql=false "
DELETE FROM nba_reference.processor_run_history
WHERE processor_name = 'BdlBoxscoresProcessor'
  AND data_date = '$YESTERDAY'
  AND records_processed = 0"

# Re-trigger via Pub/Sub
GCS_FILE=$(gsutil ls "gs://nba-scraped-data/ball-dont-lie/boxscores/$YESTERDAY/" | tail -1)
TOKEN=$(gcloud auth print-identity-token)
MESSAGE_DATA=$(echo -n "{\"scraper_name\": \"bdl_box_scores_scraper\", \"gcs_path\": \"$GCS_FILE\", \"status\": \"success\"}" | base64 -w0)

curl -X POST "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"message\": {\"data\": \"$MESSAGE_DATA\"}}"
```

### Issue: Gamebooks incomplete

**Fix - Run backfill script:**
```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_gamebooks.py --date $(date -d 'yesterday' +%Y-%m-%d)
```

### Issue: Service returning unhealthy

**Fix - Check logs and restart if needed:**
```bash
# Check service logs
gcloud run services logs read <SERVICE_NAME> --region=us-west2 --limit=50

# Force new revision (picks up any config changes)
./bin/<phase>/deploy/deploy_<service>.sh
```

---

## Scheduler Reference

| Scheduler | Schedule (ET) | Purpose | Critical? |
|-----------|--------------|---------|-----------|
| `same-day-phase3` | 10:30 AM | Today's player context | Yes |
| `same-day-phase4` | 11:00 AM | Today's ML features | Yes |
| `same-day-predictions` | 11:30 AM | Today's predictions | Yes |
| `phase6-tonight-picks` | 1:00 PM | Export predictions | Yes |
| `live-export-evening` | 7-11 PM q3min | Live scores | During games |
| `live-export-late-night` | 12-2 AM q3min | Late game scores | During games |
| `ml-feature-store-daily` | 11:30 PM PT | Yesterday's features | Yes |
| `execute-workflows` | Hourly :05 | Trigger scrapers | Yes |
| `cleanup-processor` | q15min | Republish stuck files | Background |

---

## Red Flags - Escalate If:

1. **Multiple phases failing** - Check Cloud Run quotas, IAM
2. **Data missing > 24 hours** - Major pipeline issue
3. **Services unhealthy for > 30 min** - Deployment issue
4. **Predictions not generating on game days** - Blocks product
5. **BigQuery permission errors** - IAM misconfiguration

---

## Files & Scripts Reference

```bash
# Health check script
bin/monitoring/quick_pipeline_check.sh

# Deploy scripts
./bin/scrapers/deploy/deploy_scrapers_simple.sh      # Phase 1
./bin/raw/deploy/deploy_processors_simple.sh         # Phase 2
./bin/analytics/deploy/deploy_analytics_processors.sh # Phase 3
./bin/precompute/deploy/deploy_precompute_processors.sh # Phase 4

# Backfill scripts
PYTHONPATH=. .venv/bin/python scripts/backfill_gamebooks.py --date YYYY-MM-DD
PYTHONPATH=. .venv/bin/python scripts/backfill_odds_game_lines.py --date YYYY-MM-DD
```

---

## Related Documentation

**Operations:**
- `docs/02-operations/daily-monitoring.md` - Quick reference commands
- `docs/02-operations/runbooks/prediction-pipeline.md` - Prediction pipeline details
- `docs/02-operations/orchestrator-monitoring.md` - Orchestrator specifics
- `docs/02-operations/troubleshooting.md` - Comprehensive troubleshooting

**Monitoring:**
- `docs/07-monitoring/validation-system.md` - Full validation script documentation
- `docs/07-monitoring/observability-gaps.md` - Known monitoring gaps and improvement plan
- `docs/07-monitoring/run-history-guide.md` - Processor run history analysis

**Architecture:**
- `docs/01-architecture/orchestration/orchestrators.md` - How orchestrators work
- `docs/01-architecture/orchestration/firestore-state-management.md` - Completion tracking

---

## Known Observability Gaps

See `docs/07-monitoring/observability-gaps.md` for full details. Key gaps:

| Gap | Impact | Workaround |
|-----|--------|------------|
| **No centralized Phase 2-5 processor log** | Can't query "what ran today" for processors | Check Cloud Logging or run history table |
| **No dependency check log** | Can't see what was missing when processor failed | Search Cloud Logging for "dependency" |
| **Pub/Sub retry attempts invisible** | Don't know which attempt succeeded | Check DLQ for failed messages |
| **30-day Cloud Logging retention** | No historical analysis beyond 30 days | BigQuery run history table has some data |

**Improvement plan:** See `docs/08-projects/current/ORCHESTRATION-IMPROVEMENTS.md`

---

*Created: December 27, 2025*
*Last Updated: December 27, 2025 (Session 174 - added Firestore, Pub/Sub, DLQ checks)*
