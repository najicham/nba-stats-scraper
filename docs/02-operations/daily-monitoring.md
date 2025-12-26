# Daily Pipeline Monitoring Guide

**Created:** 2025-12-25
**Last Updated:** 2025-12-25
**Purpose:** Quick reference for daily pipeline health checks and common issues

---

## Quick Health Check

Run the automated health check script:

```bash
bin/monitoring/quick_pipeline_check.sh
```

This checks:
- Recent errors (last hour)
- Today's data counts (boxscores, props, gamebooks)
- Service health (Phase 1, Phase 2)
- Data freshness across all key tables

---

## Manual Health Check Commands

### 1. Check for Recent Errors

```bash
# All errors in last hour
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=20 --format="table(timestamp,textPayload)" --freshness=1h

# Phase 1 Scrapers errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND severity>=ERROR' \
  --limit=10 --freshness=2h

# Phase 2 Processors errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase2-raw-processors" AND severity>=ERROR' \
  --limit=10 --freshness=2h
```

### 2. Check Data Freshness

```bash
# Run data freshness check
PYTHONPATH=. python scripts/check_data_freshness.py --json | jq '.'

# Or check specific tables
bq query --use_legacy_sql=false "
SELECT
  'BDL Boxscores' as source,
  MAX(game_date) as latest,
  DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) as days_old
FROM nba_raw.bdl_player_boxscores
UNION ALL
SELECT 'Gamebooks', MAX(game_date), DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
FROM nba_raw.nbac_gamebook_player_stats
UNION ALL
SELECT 'BettingPros', MAX(game_date), DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY)
FROM nba_raw.bettingpros_player_points_props
"
```

### 3. Check Today's Data

```bash
# Count today's data
bq query --use_legacy_sql=false "
SELECT
  'BDL Boxscores' as source, COUNT(DISTINCT game_id) as games, COUNT(*) as rows
FROM nba_raw.bdl_player_boxscores WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'BettingPros Props', 0, COUNT(*) FROM nba_raw.bettingpros_player_points_props WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT 'Gamebooks', COUNT(DISTINCT game_id), COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = CURRENT_DATE()
"
```

### 4. Check Service Health

```bash
# Phase 1 Scrapers
curl -s "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health" | jq '.status'

# Phase 2 Processors
curl -s "https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/health" | jq '.status'
```

### 5. Check Game Status (NBA API)

```bash
# Today's games
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | \
  jq '.scoreboard.games[] | {gameId, gameStatusText, away: .awayTeam.teamTricode, home: .homeTeam.teamTricode}'
```

---

## Common Issues & Fixes

### Issue: "No recipients for CRITICAL alert"

**Cause:** Email alerting env vars not configured on service.

**Check:**
```bash
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep -i email
```

**Fix:**
```bash
source .env
gcloud run services update nba-phase1-scrapers --region=us-west2 \
  --update-env-vars="EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO},EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO},BREVO_SMTP_HOST=smtp-relay.brevo.com,BREVO_SMTP_PORT=587,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME},BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD},BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
```

### Issue: 403 Proxy Errors

**Cause:** ProxyFuel returning 403s (rate limiting or blocked).

**Check:**
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND "403"' --limit=10 --freshness=1h
```

**Mitigation:** Errors are automatically retried. If persistent, check proxy account status.

### Issue: "No processor found" Spam

**Cause:** Files in GCS that don't have processors (e.g., `odds-api/events`).

**Fix:** Add path to `SKIP_PROCESSING_PATHS` in `data_processors/raw/main_processor_service.py`:
```python
SKIP_PROCESSING_PATHS = [
    'odds-api/events',
    'bettingpros/events',
]
```

### Issue: Hash Field Missing Errors

**Cause:** Processor's `HASH_FIELDS` includes a field not in the data.

**Example:** `is_active` not found in BDL Active Players.

**Fix:** Update the processor's `HASH_FIELDS` to match actual data fields.

### Issue: Injury Report Stale

**Check if expected:**
```bash
# Check if scraper ran but PDF unavailable
gcloud logging read 'resource.type="cloud_run_revision" AND "injury" AND "pdf_unavailable"' --limit=5 --freshness=24h
```

If `pdf_unavailable` appears, this is expected (NBA hasn't published the PDF yet).

---

## Deployment Status Check

```bash
# Check latest revision for each service
for svc in nba-phase1-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  echo "=== $svc ==="
  gcloud run services describe $svc --region=us-west2 --format="value(status.latestReadyRevisionName)" 2>/dev/null || echo "Not found"
done
```

---

## Cloud Scheduler Jobs

```bash
# List all scheduler jobs
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,state)"

# Check specific job
gcloud scheduler jobs describe execute-workflows --location=us-west2
```

---

## Existing Automated Monitoring

| Job | Schedule | Purpose |
|-----|----------|---------|
| `daily-pipeline-health-summary` | 6 AM PT | Email summary of yesterday's pipeline health |
| `execute-workflows` | Hourly (5 min past) | Triggers scraper workflows |
| `cleanup-processor` | Every 15 min | Republishes stuck files |
| `master-controller-hourly` | Hourly | Orchestrates dependent workflows |

---

## When to Escalate

Escalate if:
1. Multiple phases failing simultaneously
2. Data missing for >24 hours
3. Services returning unhealthy
4. Email alerts not working after fix attempts
5. Proxy failures lasting >1 hour

---

## Quick Reference - Deploy Scripts

```bash
# Phase 1 Scrapers
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Phase 2 Raw Processors
./bin/raw/deploy/deploy_processors_simple.sh

# Phase 3 Analytics
./bin/analytics/deploy/deploy_analytics_processors.sh

# Phase 4 Precompute
./bin/precompute/deploy/deploy_precompute_processors.sh
```

---

*Last Updated: December 25, 2025 - Session 168*
