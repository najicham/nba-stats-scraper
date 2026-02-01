# Scraper to Scheduler Job Mapping

**Created**: Session 70 (2026-02-01)
**Purpose**: Quick reference for which Cloud Scheduler jobs trigger which scrapers
**Last Updated**: 2026-02-01

---

## Overview

**Total Scrapers**: 35
**With Scheduler Jobs**: 19 (54%)
**Without Schedulers**: 16 (46%)

**Architecture**: Hub-and-spoke model with `execute-workflows` as main orchestrator

---

## Scheduler Jobs → Scrapers

### Main Orchestrator

| Job | Schedule | Triggers |
|-----|----------|----------|
| **execute-workflows** | Every 5 min | nbac_*, bdl_*, bp_events, bigdataball_pbp |

### Betting Data (3x Daily)

| Job | Schedule | Triggers |
|-----|----------|----------|
| **nba-props-morning** | 7:00 AM PT | oddsa_player_props, oddsa_game_lines |
| **nba-props-midday** | 12:00 PM PT | oddsa_player_props, oddsa_game_lines |
| **nba-props-pregame** | 4:00 PM PT | oddsa_player_props, oddsa_game_lines |

### BDL Catchup (3x Daily)

| Job | Schedule | Triggers |
|-----|----------|----------|
| **bdl-catchup-midday** | 10:00 AM ET | bdl_box_scores, bdl_player_box_scores |
| **bdl-catchup-afternoon** | 2:00 PM ET | bdl_box_scores, bdl_player_box_scores |
| **bdl-catchup-evening** | 6:00 PM ET | bdl_box_scores, bdl_player_box_scores |
| **bdl-boxscores-yesterday-catchup** | 7:30 AM ET | bdl_box_scores |

### Live Data (Game Hours)

| Job | Schedule | Triggers |
|-----|----------|----------|
| **bdl-live-boxscores-evening** | Every 3 min (4-10 PM PT) | bdl_live_box_scores |
| **bdl-live-boxscores-late** | Every 3 min (10 PM - 1 AM PT) | bdl_live_box_scores |

### Other Schedulers

| Job | Schedule | Triggers |
|-----|----------|----------|
| **bdl-injuries-hourly** | Every hour | bdl_injuries |
| **br-rosters-batch-daily** | 6:30 AM daily | br_season_roster |
| **espn-roster-processor-daily** | 7:30 AM daily | espn_roster |

---

## Scrapers Without Schedulers (16 total)

### CRITICAL - Need Investigation

| Scraper | Status | Last Data | Action Needed |
|---------|--------|-----------|---------------|
| **nbac_player_movement** | CRITICAL | Aug 2025 (5mo) | ⚠️ CREATE JOB |
| **bdl_games** | CRITICAL | Jan 22 (10d) | Verify if deprecated |
| **bp_player_props** | CRITICAL | Jan 13 (19d) | Verify if deprecated |

### UNKNOWN - May Write to BigQuery Directly

| Scraper | Notes |
|---------|-------|
| nbac_player_list | Check BigQuery timestamp |
| nbac_scoreboard_v2 | Check BigQuery timestamp |
| nbac_roster | Check BigQuery timestamp |
| espn_scoreboard | Check BigQuery timestamp |
| espn_game_boxscore | Check BigQuery timestamp |
| oddsa_team_players | Supporting data - as needed |
| bigdataball_discovery | May be manual/infrequent |

### Historical Only (Manual Backfill)

| Scraper | Purpose |
|---------|---------|
| oddsa_events_his | Historical backfill only |
| oddsa_player_props_his | Historical backfill only |
| oddsa_game_lines_his | Historical backfill only |

---

## Health Status by Scraper

### ✅ HEALTHY (18) - Data within 2 days

```
oddsa_events, oddsa_player_props, oddsa_game_lines (live betting)
oddsa_events_his, oddsa_player_props_his, oddsa_game_lines_his (historical)
bdl_box_scores, bdl_active_players, bdl_standings, bdl_live_box_scores
bp_events, bigdataball_pbp
nbac_injury_report, nbac_play_by_play, nbac_player_boxscore
nbac_gamebook_pdf, nbac_referee_assignments, nbac_team_boxscore
```

### ⚠️ STALE (3) - Data 3-7 days old

| Scraper | Days | Scheduler | Issue |
|---------|------|-----------|-------|
| bigdataball_discovery | 3 | None | May be infrequent by design |
| espn_roster | 3 | ✅ Yes | Job failing |
| bdl_player_box_scores | 7 | ✅ Yes (3x) | Catchup logic broken |

### 🔴 CRITICAL (6) - Data >7 days old

| Scraper | Days | Scheduler | Issue |
|---------|------|-----------|-------|
| br_season_roster | 9 | ✅ Yes | Job failing |
| bdl_games | 10 | None | Possibly deprecated |
| bp_player_props | 19 | None | Possibly deprecated |
| nbac_schedule_* | 79 | None | **FALSE ALARM** - Writes to BQ directly |

### ❓ UNKNOWN (8) - No GCS data

```
bdl_injuries, nbac_player_list, nbac_player_movement, nbac_scoreboard_v2
nbac_roster, espn_scoreboard, espn_game_boxscore, oddsa_team_players
```

---

## Missing Scheduler Jobs (Action Required)

### Priority 1: Create Immediately

```bash
# 1. Player Movement (CRITICAL - 5 months stale)
gcloud scheduler jobs create http nbac-player-movement-daily \
  --location=us-west2 \
  --schedule="0 8,14 * * *" \
  --uri="https://nba-scrapers-<hash>.run.app/nbac_player_movement" \
  --http-method=POST \
  --oidc-service-account-email=<service-account> \
  --description="Player trades/transactions (8 AM + 2 PM ET)"
```

### Priority 2: Investigate Then Decide

**If still needed**:
- Create scheduler jobs for bdl_games, bp_player_props

**If deprecated**:
- Mark as deprecated in registry.py
- Remove from monitoring

### Priority 3: Verify BigQuery-Only Scrapers

Query BigQuery to check if these write directly (bypassing GCS):
- nbac_roster, nbac_player_list, nbac_scoreboard_v2
- espn_scoreboard, espn_game_boxscore
- bdl_injuries

---

## Scheduler Job Monitoring

### Check Job Status

```bash
# List all jobs
gcloud scheduler jobs list --location=us-west2

# Check specific job
gcloud scheduler jobs describe <JOB_NAME> --location=us-west2

# View recent executions
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND resource.labels.job_name="<JOB_NAME>"' \
  --limit=10 \
  --format="table(timestamp, severity, jsonPayload.message)"
```

### Check for Failures

```bash
# All failed jobs in last 24h
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND severity>=ERROR' \
  --limit=20 \
  --freshness=24h \
  --format="table(timestamp, resource.labels.job_name, jsonPayload.message)"
```

---

## Related Documentation

- **Comprehensive Audit**: `docs/08-projects/current/scraper-health-audit/COMPREHENSIVE-AUDIT-2026-02-01.md`
- **Scraper Reference**: `docs/06-reference/scrapers.md`
- **Validation Skill**: `.claude/skills/validate-daily/SKILL.md` (Priority 2H)
- **Full Inventory**: `/tmp/claude-scraper-inventory.md` (256 lines)

---

*Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>*
