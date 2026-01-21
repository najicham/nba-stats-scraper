# Tomorrow's Plan - January 21, 2026 (Day 1)
**Created**: January 20, 2026 (night)
**Purpose**: Complete execution plan for Day 1 monitoring

---

## TONIGHT'S ORCHESTRATION STATUS: ✅ HEALTHY

### NBA Games Tonight (Jan 20)
All 7 games completed successfully:
- PHX@PHI - Final ✅
- LAC@CHI - Final ✅
- SAS@HOU - Final ✅
- MIN@UTA - Final ✅
- LAL@DEN - Final ✅
- TOR@GSW - Final ✅
- MIA@SAC - Final ✅

### Cloud Run Services Status
All services showing **True** (healthy):
- ✅ analytics-processor
- ✅ prediction-coordinator
- ✅ daily-health-check
- ✅ grading-readiness-monitor
- ✅ All other services (14 checked)

### Recent Activity
- `prediction-coordinator` running scheduled `/check-stalled` every 15 minutes ✅
- Last successful run: 06:15:02 UTC (200 OK, 910ms)

### Minor Issue Noted
- `nba-phase3-analytics-processors`: Gunicorn import error on cold start
- Impact: Service still shows healthy, may just be container scaling issue
- Action: Monitor tomorrow, not blocking

---

## PART 1: DAY 1 MONITORING PLAN (10-15 minutes)

### Step 1: Run Primary Health Check (5 min)
```bash
./bin/monitoring/week_1_daily_checks.sh
```

**Expected Results:**
- Service health: `{"status":"healthy"}` ✅
- Consistency mismatches: 0
- Subcollection errors: 0
- Recent errors: 0

### Step 2: Check Slack Channel (1 min)
- Open: `#week-1-consistency-monitoring`
- Expected: **No messages** (silence = good!)
- If alerts present: Investigate immediately

### Step 3: Verify Dual-Write (3 min)
```bash
# Quick Firestore check for recent batches
gcloud firestore documents list \
  --collection=prediction_batches \
  --limit=3 \
  --project=nba-props-platform 2>/dev/null | head -20
```

### Step 4: Document Results (2 min)
Update: `docs/09-handoff/week-1-monitoring-log.md`

```markdown
### Day 1 - January 21, 2026

**Time**: [HH:MM UTC]
**Checks Run**: `./bin/monitoring/week_1_daily_checks.sh`

**Results**:
- [ ] Service health: [PASS/FAIL]
- [ ] Consistency mismatches: [0]
- [ ] Subcollection errors: [0]

**Status**: ✅ Pass

**Notes**: [Any observations]
```

---

## PART 2: BACKFILL STATUS CHECKING PLAN

### A. PAST MONTH (Last 30 Days)

```bash
# Check Phase 4 coverage for last 30 days
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as records
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30'
```

**Expected:** ~20-30 dates with 200-400 players each

```bash
# Check prediction coverage for last 30 days
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30'
```

### B. CURRENT SEASON (2024-25)

```bash
# Season coverage check (Oct 22, 2024 - present)
bq query --use_legacy_sql=false '
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= "2024-10-22"
GROUP BY week
ORDER BY week DESC
LIMIT 15'
```

```bash
# Season prediction stats
bq query --use_legacy_sql=false '
SELECT
  CASE
    WHEN game_date >= "2024-10-22" THEN "2024-25 Season"
  END as season,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= "2024-10-22"
GROUP BY season'
```

### C. PAST 4 SEASONS

```bash
# Full historical coverage by season
bq query --use_legacy_sql=false '
SELECT
  CASE
    WHEN game_date >= "2024-10-22" THEN "2024-25"
    WHEN game_date >= "2023-10-24" THEN "2023-24"
    WHEN game_date >= "2022-10-18" THEN "2022-23"
    WHEN game_date >= "2021-10-19" THEN "2021-22"
    ELSE "Pre-2021"
  END as season,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= "2021-10-19"
GROUP BY season
ORDER BY season DESC'
```

**Expected per season:**
- Regular season: ~170-180 game dates
- Playoffs: ~40-50 additional dates
- Players per date: 200-400

### D. COMPREHENSIVE VALIDATION SCRIPT

```bash
# Full validation for a date range
python scripts/validate_backfill_coverage.py \
  --start-date 2024-10-22 --end-date 2025-01-20 --details
```

**Status Codes:**
- `OK` - Records present ✅
- `Skipped` - Expected (bootstrap/insufficient data)
- `DepsMiss` - Upstream missing (run upstream first)
- `Untracked` - ⚠️ INVESTIGATE
- `NO_GAMES` - No games on this date

---

## PART 3: BACKFILL EXECUTION PLAN

### Quick Backfill Commands

```bash
# List all available backfill jobs
./bin/run_backfill.sh --list

# Dry run a specific backfill
./bin/run_backfill.sh raw/bdl_boxscores --dry-run --limit 5

# Run Phase 4 backfill for a date range
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2024-12-01 --end-date 2024-12-31 --dry-run
```

### Full Historical Backfill (If Needed)
```bash
# Complete 4-season backfill (6-8 hours)
./bin/backfill/run_complete_historical_backfill.sh --dry-run

# Resume from checkpoint
./bin/backfill/run_complete_historical_backfill.sh
```

### Verify Backfill Range
```bash
python bin/backfill/verify_backfill_range.py \
  --start-date 2024-01-01 --end-date 2024-03-31 --verbose
```

---

## PART 4: BOXSCORES & LIVE GRADING VALIDATION

### Check Tonight's Boxscores (Jan 20 games)
```bash
# Expected: 7 games (PHX, LAC, SAS, MIN, LAL, TOR, MIA)
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_lookup) as players,
  SUM(minutes_played) as total_minutes
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = "2026-01-20"
GROUP BY game_date'
```

**Expected:** 7 games, ~200+ players, significant minutes

### Check Grading Status
```bash
# Grading runs at 6 AM ET, check if ready
gcloud logging read \
  'resource.labels.service_name="grading-readiness-monitor"' \
  --limit=5 --freshness=6h \
  --format="table(timestamp,textPayload)" 2>/dev/null
```

### Check Live Scores API
```bash
# Current day's games
curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" | \
  jq '.scoreboard.games[] | {gameId, status: .gameStatusText, away: .awayTeam.teamTricode, home: .homeTeam.teamTricode}'
```

---

## QUICK REFERENCE: KEY COMMANDS

### Health Checks
```bash
# Primary Week 1 check
./bin/monitoring/week_1_daily_checks.sh

# General pipeline health
./bin/orchestration/automated_daily_health_check.sh

# Orchestration state for a date
python3 bin/monitoring/check_orchestration_state.py 2026-01-21
```

### Error Checking
```bash
# Recent errors (last 2 hours)
gcloud logging read 'severity>=ERROR' --limit=20 --freshness=2h

# Coordinator errors
gcloud logging read 'resource.labels.service_name="prediction-coordinator" severity>=ERROR' --limit=10 --freshness=2h

# Consistency mismatches
gcloud logging read 'severity=WARNING "CONSISTENCY MISMATCH"' --limit=10 --freshness=24h
```

### BigQuery Quick Checks
```bash
# Today's predictions
bq query --use_legacy_sql=false '
SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()'

# Unresolved players
bq query --use_legacy_sql=false '
SELECT player_lookup, COUNT(*) as occurrences
FROM mlb_reference.unresolved_players
WHERE reported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY player_lookup
LIMIT 10'
```

---

## TIMELINE FOR TOMORROW

| Time (PT) | Time (ET) | Action |
|-----------|-----------|--------|
| 4:00 AM | 7:00 AM | Run Week 1 monitoring checks |
| 4:10 AM | 7:10 AM | Check Slack #week-1-consistency-monitoring |
| 4:15 AM | 7:15 AM | Document results in monitoring log |
| 4:30 AM | 7:30 AM | Run backfill status queries (if desired) |
| 5:00 AM | 8:00 AM | Daily health check runs automatically |
| Any time | Any time | Optional: Full historical validation |

---

## SUCCESS CRITERIA FOR DAY 1

### Must Pass ✅
- [ ] Service health: `{"status":"healthy"}`
- [ ] Consistency mismatches: 0
- [ ] Subcollection errors: 0
- [ ] Slack channel: No alerts

### Good to Have 🟢
- [ ] Recent errors: 0
- [ ] Boxscores complete: 7 games
- [ ] Past month coverage: 90%+
- [ ] Current season coverage: 95%+

### Red Flags 🔴
- Consistency mismatches > 2
- Service unhealthy
- Multiple subcollection errors
- Slack channel has alerts

---

## IF ISSUES FOUND

1. **Don't panic** - Document what you see
2. **Check runbook**: `docs/02-operations/robustness-improvements-runbook.md`
3. **Check surrounding logs**: 60 seconds before/after error
4. **If systematic**: Consider rollback (disable feature flags)

---

**Created**: 2026-01-20 23:45 UTC
**Next Review**: Day 1 Morning (Jan 21)
