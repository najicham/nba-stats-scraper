# Daily Operations Checklist

Session 319 · 2026-02-21

## What's Automated (No Action Needed)

| System | Frequency | Auto-Heals? | Slack Channel |
|--------|-----------|-------------|---------------|
| Pipeline canary | Every 30min | YES | `#canary-alerts` |
| Deployment drift | Every 2h | No (alert only) | `#deployment-alerts` |
| Grading gap detector | 9 AM ET | YES | `#nba-alerts` |
| Decay detection | 11 AM ET | No (state machine) | `#nba-alerts` |
| Self-heal predictions | Continuous | YES | `#canary-alerts` |
| Post-grading re-export | After grading | YES | None |
| Retrain reminder | Monday 9 AM ET | No (Slack + SMS) | `#nba-alerts` |

## Daily Routine (~5 min, after 11 AM ET)

### Step 1: Slack Scan (30 sec)
- Check `#nba-alerts` and `#deployment-alerts`
- Red flags: `MODEL DECAY`, `MARKET DISRUPTION`, deployment drift >24h

### Step 2: `/daily-steering` (2 min)
- Read the RECOMMENDATION line: `ALL CLEAR` / `WATCH` / `SWITCH` / `RETRAIN` / `BLOCKED`
- If ALL CLEAR or WATCH → done for the day

### Step 3: Only if Issues Flagged
- `/validate-daily` → deep pipeline validation
- `/reconcile-yesterday` → verify yesterday's data through all 6 phases

### Step 4: Weekly (Monday)
- Check retrain reminder in Slack
- If model >= 7 days old: plan retrain session
- `./bin/check-deployment-drift.sh --verbose` for full service audit

## Skills Reference

| Skill | When | Frequency |
|-------|------|-----------|
| `/daily-steering` | First thing, 11 AM ET | Daily |
| `/validate-daily` | If flagged, or spot-check | Daily/weekly |
| `/reconcile-yesterday` | After game nights | Daily |
| `/validate-scraped-data` | Scraper alerts | Weekly |
| `/hit-rate-analysis` | Performance review | Weekly |
| `/subset-performance` | Track subset trends | Weekly |
| `/validate-feature-drift` | After retrain | Monthly |
| `/validate-source-alignment` | After schema changes | Monthly |
| `/spot-check-features` | Before retrain | As needed |
| `/validate-historical` | Data quality audit | Monthly |
