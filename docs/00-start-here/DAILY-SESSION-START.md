# Daily Session Start Guide

**Purpose:** Quick validation checklist for incoming Claude Code sessions.
**Time:** 5-10 minutes to validate, then proceed with any issues found.

---

## Step 1: Get Context (30 seconds)

Read the most recent handoff document:
```bash
ls -t docs/09-handoff/*.md | head -3
```

The handoff will tell you:
- What was done in the last session
- Known issues to monitor
- Pending verifications

---

## Step 2: Quick Health Check (2 minutes)

Run these commands to assess system health:

```bash
# Service health
curl -s https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health | jq '.status'

# Recent errors (last 2 hours)
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=2h 2>/dev/null | head -20

# Current revision
gcloud run revisions list --service=nba-phase1-scrapers --region=us-west2 --limit=3 2>/dev/null
```

**Expected:** Status "healthy", minimal errors, recent revision active.

---

## Step 3: Data Freshness Check (3 minutes)

```bash
# Raw data freshness (expect yesterday's date for box scores/gamebooks)
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'BDL Boxscores' as source, MAX(game_date) as latest
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\` WHERE game_date >= '2026-01-01'
UNION ALL
SELECT 'Gamebooks', MAX(game_date)
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\` WHERE game_date >= '2026-01-01'
UNION ALL
SELECT 'ESPN Rosters', MAX(roster_date)
FROM \`nba-props-platform.nba_raw.espn_team_rosters\` WHERE roster_date >= '2026-01-01'
ORDER BY source"

# Predictions for today (if games scheduled)
bq query --use_legacy_sql=false --format=pretty "
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= CURRENT_DATE() - 1 GROUP BY 1 ORDER BY 1"

# BettingPros props (key input for predictions)
bq query --use_legacy_sql=false --format=pretty "
SELECT game_date, COUNT(*) as props
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date >= CURRENT_DATE() - 2 GROUP BY 1 ORDER BY 1"
```

---

## Step 4: Decision Matrix

| Check | Expected | If Different | Action |
|-------|----------|--------------|--------|
| Service health | "healthy" | unhealthy/error | Check Cloud Run logs |
| BDL/Gamebook date | Yesterday | 2+ days old | Check post_game workflows |
| ESPN Rosters | Today | Yesterday or older | Check ESPN scraper logs |
| BettingPros props | >5000 per game day | <1000 | Run `scripts/betting_props_recovery.py` |
| Predictions | >100 for today | 0 or very low | Check Phase 4→5 pipeline |

---

## Step 5: If Issues Found

### Common Issues & Fixes

**BettingPros props missing:**
```bash
PYTHONPATH=. python scripts/betting_props_recovery.py --date YYYY-MM-DD
```

**Gamebooks missing:**
```bash
PYTHONPATH=. python scripts/backfill_gamebooks.py --date YYYY-MM-DD
```

**Check data completeness:**
```bash
PYTHONPATH=. python scripts/check_data_completeness.py --date YYYY-MM-DD
```

---

## Deep Dive Documentation

| Topic | Document |
|-------|----------|
| Full validation checklist | `docs/02-operations/daily-validation-checklist.md` |
| Troubleshooting matrix | `docs/02-operations/troubleshooting-matrix.md` |
| Orchestration monitoring | `docs/02-operations/orchestrator-monitoring.md` |
| Current projects | `docs/08-projects/current/` |
| Historical backfill audit | `docs/08-projects/current/historical-backfill-audit/STATUS.md` |

---

## Known Issues Register

Check for active issues that may affect today's operations:

| Issue | Status | Impact | Tracking |
|-------|--------|--------|----------|
| BettingPros proxy timeouts | **Fixed (pending deploy)** | Props may fail | `docs/08-projects/current/bettingpros-reliability/` |
| ESPN roster reliability | **Fixed (rev 00100)** | 30/30 teams now | Session 26 handoff |
| BDL west coast gap | **Fixed (rev 00099)** | All games captured | Session 25 handoff |

*Update this table each session as issues are found/resolved.*

---

## Workflow Schedule (ET)

| Time | Workflow | What It Does |
|------|----------|--------------|
| 7:00 AM | morning_operations | Schedule, injuries, referees |
| 10:30 AM | same-day-phase3 | Today's player context |
| 11:00 AM | same-day-phase4 | Today's ML features |
| 11:30 AM | same-day-predictions | Today's predictions |
| 1:00 PM | betting_lines | BettingPros props |
| 4:00 PM | betting_lines | BettingPros props (update) |
| 7:00 PM | betting_lines | BettingPros props (update) |
| 4:00 AM | post_game_window_3 | Yesterday's box scores, gamebooks |

---

## Quick Contacts

- **Slack Channel:** #nba-platform-alerts (if configured)
- **Service URL:** https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app
- **Project:** nba-props-platform (GCP)
- **Region:** us-west2

---

---

## Maintaining This Documentation

**When you find something during daily checks:**

| What Happened | Where to Document |
|---------------|-------------------|
| Found a new issue | Add to `docs/08-projects/current/daily-orchestration-tracking/ISSUES-LOG.md` |
| Discovered a useful query | Add to `docs/08-projects/current/daily-orchestration-tracking/VALIDATION-IMPROVEMENTS.md` |
| See a recurring pattern | Add to `docs/08-projects/current/daily-orchestration-tracking/PATTERNS.md` |
| Fixed an issue | Update Known Issues Register above |

**When to update this guide:**
- Add new commands to Step 2/3 if you find better checks
- Update Decision Matrix if thresholds change
- Update Known Issues Register when issues are found/resolved

**Canonical validation source:** `docs/02-operations/daily-validation-checklist.md` (full 765-line reference)

---

*Last Updated: January 13, 2026 (Session 27)*
