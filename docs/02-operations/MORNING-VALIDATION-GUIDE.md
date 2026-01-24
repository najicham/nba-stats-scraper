# Morning Orchestration Validation Guide

> **For Claude Code sessions** - Use this guide when asked to validate daily orchestration.

---

## Quick Start

**Two validation scenarios:**

| Scenario | What to Validate | Key Question |
|----------|------------------|--------------|
| **Today's orchestration** | Same-day predictions, morning schedulers | Are predictions ready for tonight's games? |
| **Yesterday's orchestration** | Overnight processing, boxscores, Phase 4 | Did last night's games get processed? |

---

## Step 1: Run Health Check First

```bash
./bin/orchestration/quick_health_check.sh
```

**Interpret results:**
- `HEALTHY` - All good, do spot checks below
- `DEGRADED` - Minor issues, investigate warnings
- `UNHEALTHY` - Problems, investigate immediately
- `NO GAMES TODAY` - Expected on off-days

---

## Step 2: Validate Based on Scenario

### Scenario A: Validate TODAY's Orchestration

Check that same-day predictions are ready for tonight's games.

```bash
# 1. Check if there are games today
bq query --use_legacy_sql=false "
SELECT COUNT(*) as games_today
FROM nba_raw.v_nbac_schedule_latest
WHERE game_date = CURRENT_DATE('America/New_York')"

# 2. Check morning schedulers ran (same-day-phase3, same-day-phase4, same-day-predictions)
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id:"same-day"' \
  --limit=5 --freshness=6h --format="table(timestamp,resource.labels.job_id)"

# 3. Check predictions exist for today
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE('America/New_York') AND is_active = TRUE"

# 4. Check Phase 3 analytics ready
bq query --use_legacy_sql=false "
SELECT COUNT(*) as player_contexts
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE('America/New_York')"
```

**Success criteria:**
- Predictions exist for all games
- Player contexts populated
- No scheduler failures in logs

---

### Scenario B: Validate YESTERDAY's Orchestration

Check that overnight processing completed for last night's games.

```bash
# Set yesterday's date
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

# 1. Check boxscores collected
bq query --use_legacy_sql=false "
SELECT 'bdl_boxscores' as source, COUNT(DISTINCT game_id) as games
FROM nba_raw.bdl_player_boxscores WHERE game_date = '$YESTERDAY'
UNION ALL
SELECT 'gamebooks', COUNT(DISTINCT game_id)
FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = '$YESTERDAY'"

# 2. Check Phase 4 overnight schedulers ran
gcloud logging read 'resource.type="cloud_scheduler_job" AND (resource.labels.job_id:"daily" OR resource.labels.job_id:"composite")' \
  --limit=5 --freshness=12h --format="table(timestamp,resource.labels.job_id)"

# 3. Check ML feature store updated
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$YESTERDAY'"

# 4. Check for processing failures
bq query --use_legacy_sql=false "
SELECT processor_name, status, error_message
FROM nba_reference.processor_run_history
WHERE data_date = '$YESTERDAY' AND status != 'success'"

# 5. Check grading completed (if games finished)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as graded_predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '$YESTERDAY' AND actual_value IS NOT NULL"
```

**Success criteria:**
- Boxscores exist for all games played
- Phase 4 data populated
- No processor failures
- Predictions graded with actual values

---

## Step 3: Investigate Issues

### Common Issues & Fixes

| Issue | Check | Fix |
|-------|-------|-----|
| No predictions for today | Scheduler logs | Manually trigger: `gcloud scheduler jobs run same-day-predictions --location=us-west2` |
| Missing boxscores | BDL API status | Wait (can be 45+ hours) or check alternate sources |
| Phase 4 not running | Scheduler logs | Check Cloud Run service health, trigger manually |
| Processor failures | `processor_run_history` | Check error message, may need manual rerun |

### Check Service Health

```bash
# Service URL
SERVICE_URL=$(gcloud run services describe nba-scrapers --region=us-west2 --format="value(status.url)")

# Health endpoint
curl -s "${SERVICE_URL}/health" | jq '.'

# Recent errors
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=10 --freshness=2h
```

---

## Step 4: Report Findings

After validation, summarize:

1. **Overall status**: Healthy / Issues Found
2. **Games processed**: X of Y games
3. **Data completeness**: Boxscores, gamebooks, predictions
4. **Issues found**: List any problems
5. **Actions taken**: Any manual interventions

---

## Key Documentation References

| Topic | Location |
|-------|----------|
| Orchestration overview | `docs/03-phases/phase1-orchestration/README.md` |
| How orchestration works | `docs/03-phases/phase1-orchestration/how-it-works.md` |
| BigQuery table schemas | `docs/03-phases/phase1-orchestration/bigquery-schemas.md` |
| Troubleshooting & endpoints | `docs/03-phases/phase1-orchestration/troubleshooting.md` |
| Daily operations runbook | `docs/02-operations/daily-operations-runbook.md` |
| Validation scripts | `bin/orchestration/README.md` |

---

## Key BigQuery Tables

| Table | Purpose |
|-------|---------|
| `nba_orchestration.daily_expected_schedule` | What should run today |
| `nba_orchestration.workflow_decisions` | RUN/SKIP/ABORT decisions |
| `nba_orchestration.workflow_executions` | Execution results |
| `nba_orchestration.scraper_execution_log` | Individual scraper runs |
| `nba_raw.bdl_player_boxscores` | Box score data |
| `nba_raw.nbac_gamebook_player_stats` | Gamebook data |
| `nba_predictions.player_prop_predictions` | Predictions |
| `nba_reference.processor_run_history` | Processor run tracking |

---

## Updating This Documentation

If you find something missing or incorrect in the orchestration docs:

1. **Small fixes**: Edit the relevant doc directly
2. **New discoveries**: Add to `docs/03-phases/phase1-orchestration/troubleshooting.md`
3. **New validation checks**: Add to this guide
4. **Incidents**: Create postmortem in `docs/02-operations/postmortems/`

**Always update "Last Updated" date when making changes.**

---

**Last Updated:** 2026-01-24
