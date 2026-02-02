# Trade Deadline Playbook - February 6, 2026

**Purpose**: Operational procedures for NBA trade deadline day
**Last Updated**: February 2, 2026
**Next Trade Deadline**: February 6, 2026 at 3:00 PM ET

---

## Overview

The NBA trade deadline is when the most player movement happens in a single day. Our system must capture all trades, roster changes, and player list updates in real-time.

### System Status

| Component | Status | Automation Level |
|-----------|--------|------------------|
| Player Movement | ✅ Fully Automated | Runs 8 AM & 2 PM ET daily |
| Player List | ✅ Working | Manual trigger available |
| BR Rosters | ✅ Working | Manual trigger available |
| ESPN Rosters | ⚠️ Needs Refresh | Manual trigger available |

---

## Pre-Deadline Checklist (Feb 5 - Day Before)

### 1. Verify Automated Systems (30 min)

**Player Movement Scraper**:
```bash
# Check scheduler is enabled
gcloud scheduler jobs describe nbac-player-movement-daily \
  --location=us-west2 \
  --format="value(state, schedule)"
# Expected: ENABLED, 0 8,14 * * *

# Check recent successful runs
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND resource.labels.job_id="nbac-player-movement-daily"' \
  --limit=3 --freshness=48h --format="table(timestamp, httpRequest.status)"
# Expected: Recent 200 status codes
```

**Player Movement Processor**:
```bash
# Verify recent data
bq query --use_legacy_sql=false "
  SELECT MAX(transaction_date) as latest_trade,
         MAX(scrape_timestamp) as latest_scrape,
         COUNT(*) as recent_transactions
  FROM nba_raw.nbac_player_movement
  WHERE transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)"
# Expected: Recent dates, some transactions
```

**Player List**:
```bash
# Check data is current
bq query --use_legacy_sql=false "
  SELECT MAX(processed_at) as latest_update,
         COUNT(DISTINCT player_lookup) as total_players,
         MAX(source_file_date) as latest_file_date
  FROM nba_raw.nbac_player_list_current"
# Expected: Recent timestamp, 625+ players, recent date
```

### 2. Test Manual Triggers (15 min)

Practice the manual workflows you'll use on trade deadline day:

```bash
# Player list refresh (PRACTICE - verify command works)
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_list","group":"prod"}'
# Expected: {"status":"success", "season":"2025", "records_found":546+}
```

### 3. Check Service Health (10 min)

```bash
# Scraper service
gcloud run services describe nba-scrapers --region=us-west2 \
  --format="value(status.conditions[0].status, status.latestReadyRevisionName)"
# Expected: True, nba-scrapers-00114-6jc (or later)

# Phase 2 processor service
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.conditions[0].status)"
# Expected: True
```

### 4. Review Recent Handoffs (5 min)

```bash
ls -lh docs/09-handoff/ | tail -3
cat docs/09-handoff/2026-02-02-SESSION-72-HANDOFF.md  # Player list fix
cat docs/09-handoff/2026-02-02-SESSION-71-FINAL-HANDOFF.md  # Player movement automation
```

---

## Trade Deadline Day - February 6, 2026

### Timeline

| Time (ET) | Event | Action |
|-----------|-------|--------|
| **8:00 AM** | Morning scraper run | Monitor automated run |
| **2:00 PM** | Afternoon scraper run | Monitor automated run |
| **3:00 PM** | Trade deadline | Peak monitoring period |
| **3:30 PM** | Post-deadline | Manual refresh if needed |
| **4:00 PM** | Verification | Confirm all trades captured |

---

### 8:00 AM ET - Morning Automated Run

**What Happens**:
- Cloud Scheduler triggers player movement scraper
- Scraper fetches NBA.com transaction data
- Publishes to Pub/Sub
- Processor auto-triggers and loads to BigQuery

**Monitoring**:
```bash
# Watch scheduler execution (around 8:00 AM ET / 13:00 UTC)
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND resource.labels.job_id="nbac-player-movement-daily"' \
  --limit=1 --freshness=5m

# Check scraper logs
gcloud logging read 'resource.labels.service_name="nba-scrapers"
  AND jsonPayload.scraper_name="nbac_player_movement"' \
  --limit=5 --freshness=10m

# Verify data appeared
bq query --use_legacy_sql=false "
  SELECT transaction_date, player_slug, team_abbr, transaction_type
  FROM nba_raw.nbac_player_movement
  WHERE scrape_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  ORDER BY transaction_date DESC, player_slug
  LIMIT 20"
```

**Success Criteria**:
- ✅ Scheduler shows status 200
- ✅ Scraper logs show "completed successfully"
- ✅ BigQuery has new records with recent scrape_timestamp
- ✅ Transaction dates are current

**If Fails**: See [Troubleshooting](#troubleshooting-8-am-run-fails) below

---

### 2:00 PM ET - Afternoon Automated Run

**What Happens**:
Same as morning run - automated scraper execution.

**Monitoring**:
```bash
# Same monitoring commands as 8 AM run
# Watch for 2:00 PM ET / 19:00 UTC execution
```

**Important**: This run happens 1 hour before the trade deadline (3 PM ET), so it captures early trades.

---

### 3:00 PM ET - Trade Deadline ⚠️ PEAK MONITORING

**What to Watch**:
- Trades announced on social media/news before official NBA.com updates
- Multiple trades happening simultaneously
- Player list changes (teams, jersey numbers)

**Actions**:

**Every 15 Minutes** (3:00 PM - 4:00 PM ET):
```bash
# Check latest transactions
bq query --use_legacy_sql=false "
  SELECT transaction_date,
         player_slug,
         team_abbr,
         transaction_type,
         scrape_timestamp
  FROM nba_raw.nbac_player_movement
  WHERE transaction_date = CURRENT_DATE()
  ORDER BY scrape_timestamp DESC
  LIMIT 30"
```

**If trades are announced but not appearing**:
→ Proceed to [Manual Trigger Procedures](#manual-trigger-procedures)

---

### 3:30 PM ET - Post-Deadline Manual Refresh

**When**: 30 minutes after deadline to ensure all trades are captured

**Procedure**:

**1. Manual Player Movement Scrape**:
```bash
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_movement","year":"2026","group":"prod"}'
```

**2. Wait 2-3 minutes, then verify**:
```bash
bq query --use_legacy_sql=false "
  SELECT COUNT(*) as trades_today,
         COUNT(DISTINCT player_slug) as players_moved,
         MAX(scrape_timestamp) as latest_scrape
  FROM nba_raw.nbac_player_movement
  WHERE transaction_date = CURRENT_DATE()"
```

**3. Manual Player List Refresh** (updates team assignments):
```bash
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_list","group":"prod"}'
```

**4. Wait 2-3 minutes, verify player list processor ran**:
```bash
bq query --use_legacy_sql=false "
  SELECT MAX(processed_at) as latest_update,
         COUNT(DISTINCT player_lookup) as total_players
  FROM nba_raw.nbac_player_list_current"
# Should show timestamp within last 5 minutes
```

**5. Optional: Roster Refresh**:
```bash
# BR rosters (if roster accuracy matters for downstream)
gcloud run jobs execute br-rosters-backfill --region=us-west2

# Wait 2-3 minutes, then processor
PYTHONPATH=. GCP_PROJECT_ID=nba-props-platform \
python backfill_jobs/raw/br_roster_processor/br_roster_processor_raw_backfill.py \
  --season 2024 --teams all
```

---

### 4:00 PM ET - Verification & Reporting

**Final Checks**:

**1. Count Trades**:
```bash
bq query --use_legacy_sql=false "
  SELECT
    transaction_type,
    COUNT(*) as count,
    COUNT(DISTINCT player_slug) as unique_players
  FROM nba_raw.nbac_player_movement
  WHERE transaction_date = CURRENT_DATE()
  GROUP BY transaction_type
  ORDER BY count DESC"
```

**2. List Major Trades**:
```bash
bq query --use_legacy_sql=false "
  SELECT
    player_slug,
    team_abbr,
    transaction_type,
    transaction_description
  FROM nba_raw.nbac_player_movement
  WHERE transaction_date = CURRENT_DATE()
    AND transaction_type = 'Trade'
  ORDER BY player_slug"
```

**3. Check Player List Updates**:
```bash
bq query --use_legacy_sql=false "
  SELECT
    player_lookup,
    team_abbr,
    position,
    jersey_number
  FROM nba_raw.nbac_player_list_current
  WHERE player_lookup IN (
    -- Players who were traded today
    SELECT DISTINCT player_slug
    FROM nba_raw.nbac_player_movement
    WHERE transaction_date = CURRENT_DATE()
      AND transaction_type = 'Trade'
  )
  ORDER BY player_lookup"
```

**4. Verify Schedule Data** (check affected games):
```bash
bq query --use_legacy_sql=false "
  SELECT
    game_date,
    away_team_tricode,
    home_team_tricode,
    game_status
  FROM nba_reference.nba_schedule
  WHERE game_date >= CURRENT_DATE()
    AND game_date <= DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
  ORDER BY game_date, game_id"
```

---

## Manual Trigger Procedures

### When to Use Manual Triggers

Use manual triggers if:
- Trades are announced but not appearing in BigQuery within 15 minutes
- Automated runs fail (status code != 200)
- Need immediate refresh for downstream systems
- Post-deadline comprehensive refresh (recommended)

### Player Movement (Trades)

```bash
# Trigger scraper
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_movement","year":"2026","group":"prod"}'

# Expected response (within 20-30 seconds):
# {"status":"success","scraper":"nbac_player_movement","run_id":"...","message":"..."}

# Processor auto-triggers via Pub/Sub (no manual action needed)
# Wait 2-3 minutes, then verify:
bq query --use_legacy_sql=false "
  SELECT MAX(scrape_timestamp), COUNT(*)
  FROM nba_raw.nbac_player_movement
  WHERE scrape_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)"
```

### Player List (Team Assignments)

```bash
# Trigger scraper
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_list","group":"prod"}'

# Expected response:
# {"status":"success","season":"2025","records_found":546+,"run_id":"..."}

# Processor auto-triggers via Pub/Sub
# Wait 2-3 minutes, verify:
bq query --use_legacy_sql=false "
  SELECT MAX(processed_at), COUNT(*)
  FROM nba_raw.nbac_player_list_current"
```

### BR Rosters (Optional)

```bash
# Step 1: Run scraper job (all 30 teams, ~2 minutes)
gcloud run jobs execute br-rosters-backfill --region=us-west2

# Step 2: Wait 2-3 minutes, run processor
PYTHONPATH=. GCP_PROJECT_ID=nba-props-platform \
python backfill_jobs/raw/br_roster_processor/br_roster_processor_raw_backfill.py \
  --season 2024 --teams all

# Step 3: Verify
bq query --use_legacy_sql=false "
  SELECT team_abbrev, COUNT(*) as players, MAX(processed_at) as last_update
  FROM nba_raw.br_rosters_current
  GROUP BY team_abbrev
  ORDER BY team_abbrev"
```

---

## Troubleshooting

### 8 AM Run Fails

**Symptom**: Scheduler shows status code != 200

**Check**:
```bash
# Get error details
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND resource.labels.job_id="nbac-player-movement-daily"' \
  --limit=1 --format=json | jq '.[0].httpRequest'
```

**Solutions**:

**Status 404**: Endpoint URL wrong
```bash
# Verify scheduler configuration
gcloud scheduler jobs describe nbac-player-movement-daily --location=us-west2
# Check: uri should be https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape
```

**Status 500**: Scraper internal error
```bash
# Check scraper logs
gcloud logging read 'resource.labels.service_name="nba-scrapers"
  AND severity>=ERROR' --limit=10 --freshness=1h

# Manual trigger to test
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_movement","year":"2026","group":"prod"}'
```

**Status 503**: Service unavailable (cold start timeout)
- Wait 1-2 minutes and automated retry will trigger
- Or manually trigger as above

---

### Processor Not Running

**Symptom**: Scraper succeeds but no data in BigQuery

**Check**:
```bash
# Check Pub/Sub subscription
gcloud pubsub subscriptions describe nba-phase2-raw-complete-sub \
  --format="value(ackDeadlineSeconds, messageRetentionDuration)"

# Check processor logs
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=10 --freshness=30m
```

**Solution**:
Manual processor trigger is NOT supported. Processor only runs via Pub/Sub.

If processor failed:
1. Check logs for error
2. Fix error
3. Re-run scraper (triggers new Pub/Sub message)

---

### Data Missing from BigQuery

**Symptom**: Processor ran successfully but 0 rows inserted

**Check**:
```bash
# Check processor stats in logs
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND jsonPayload.processor="NbacPlayerMovementProcessor"' \
  --limit=1 --format=json | jq '.[0].jsonPayload.stats'
```

**Causes**:
1. **No new transactions**: NBA.com had no new data (normal)
2. **Type casting error**: Similar to Session 72 player list bug
3. **Schema mismatch**: Processor trying to write invalid fields

**Solution**:
Check processor logs for errors. If schema issue, see Session 58 handoff for fix procedure.

---

### Player Showing Wrong Team

**Symptom**: Trade happened but player still shows old team in player_list

**Cause**: Player list hasn't been refreshed since trade

**Solution**:
```bash
# Manual player list refresh
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_player_list","group":"prod"}'

# Wait 2-3 min, verify specific player
bq query --use_legacy_sql=false "
  SELECT player_lookup, team_abbr, position, processed_at
  FROM nba_raw.nbac_player_list_current
  WHERE player_lookup = 'player-name-here'"
```

---

## Communication Templates

### Slack Update (If Used)

**Morning Check-in** (8:30 AM ET):
```
:white_check_mark: Trade deadline systems operational
- 8 AM player movement run: SUCCESS
- Transactions captured: [X] trades, [Y] total transactions
- All systems green
Next check: 2:30 PM ET
```

**Post-Deadline Report** (4:00 PM ET):
```
:trophy: Trade deadline capture complete
- Total trades today: [X]
- Players moved: [Y]
- Last data refresh: 3:30 PM ET
- All systems operational

Top trades:
- [Player A] → [Team B]
- [Player C] → [Team D]

Data ready for downstream processing
```

---

## Post-Deadline Follow-up

### Next Day (Feb 7)

**1. Verify Data Quality**:
```bash
# Check for duplicate transactions
bq query --use_legacy_sql=false "
  SELECT player_slug, team_abbr, transaction_type, COUNT(*) as cnt
  FROM nba_raw.nbac_player_movement
  WHERE transaction_date = '2026-02-06'
  GROUP BY player_slug, team_abbr, transaction_type
  HAVING cnt > 1"
# Should return 0 rows
```

**2. Update Documentation**:
- Record actual number of trades in this playbook
- Note any issues encountered
- Update troubleshooting section with new learnings

**3. Create Session Handoff**:
- Document any manual interventions needed
- Record system performance
- Identify improvements for next year

---

## Reference Information

### Key URLs

| Service | URL |
|---------|-----|
| Scraper Service | https://nba-scrapers-f7p3g7f6ya-wl.a.run.app |
| Unified Dashboard | https://unified-dashboard-f7p3g7f6ya-wl.a.run.app |
| BigQuery Console | https://console.cloud.google.com/bigquery?project=nba-props-platform |

### Key Tables

| Table | Purpose |
|-------|---------|
| `nba_raw.nbac_player_movement` | All player transactions (trades, waivers, signings) |
| `nba_raw.nbac_player_list_current` | Current player-team assignments |
| `nba_raw.br_rosters_current` | Basketball Reference roster data |
| `nba_reference.nba_schedule` | Game schedule (for affected games) |

### Data Flow

```
Trade Announced
    ↓
NBA.com API updates (within 5-30 minutes)
    ↓
Our Scraper runs (8 AM, 2 PM automated, or manual trigger)
    ↓
Saves to GCS: gs://nba-scraped-data/nba-com/player-movement/[date]/
    ↓
Publishes Pub/Sub event
    ↓
Processor auto-triggers
    ↓
Loads to BigQuery: nba_raw.nbac_player_movement
    ↓
Data available for queries/downstream
```

### Scheduler Configuration

```bash
# View full configuration
gcloud scheduler jobs describe nbac-player-movement-daily \
  --location=us-west2

# Key settings:
# Schedule: 0 8,14 * * * (8 AM & 2 PM ET / 13:00 & 19:00 UTC)
# URI: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape
# Body: {"scraper":"nbac_player_movement","year":"2026","group":"prod"}
# Method: POST
# Headers: Content-Type: application/json
```

---

## Historical Trade Deadline Data

| Year | Date | Trades | Notes |
|------|------|--------|-------|
| 2026 | Feb 6 | TBD | This year |
| 2025 | Feb 8 | ~8-12 | [Add after Feb 6, 2026] |
| 2024 | Feb 8 | ~8-12 | Typical year |

---

## Contact & Escalation

**For Issues**:
1. Check this playbook troubleshooting section
2. Check recent session handoffs in `docs/09-handoff/`
3. Check `docs/02-operations/troubleshooting-matrix.md`
4. If critical: Manual triggers work as fallback

**Documentation**:
- Trade deadline playbook: `docs/02-operations/runbooks/trade-deadline-playbook.md` (this file)
- Player movement automation: `docs/09-handoff/2026-02-02-SESSION-71-FINAL-HANDOFF.md`
- Player list fix: `docs/09-handoff/2026-02-02-SESSION-72-HANDOFF.md`
- System architecture: `docs/01-architecture/`

---

**Last Updated**: February 2, 2026
**Next Review**: February 7, 2026 (post-trade deadline)
**Maintained By**: Claude Code Sessions
