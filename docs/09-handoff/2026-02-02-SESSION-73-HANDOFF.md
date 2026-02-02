# Session 73 Handoff - February 2, 2026

## Session Summary

Created evening analytics scheduler jobs to reduce the 6-18 hour gap in game processing. Discovered that schedulers depend on gamebook data which only becomes available the next morning. Performed early validation on the one completed Feb 1 game.

---

## Accomplishments

### 1. Evening Schedulers Created

| Job | Schedule | Purpose |
|-----|----------|---------|
| `evening-analytics-6pm-et` | Sat/Sun 6 PM ET | Weekend matinees |
| `evening-analytics-10pm-et` | Daily 10 PM ET | 7 PM games |
| `evening-analytics-1am-et` | Daily 1 AM ET | West Coast games |
| `morning-analytics-catchup-9am-et` | Daily 9 AM ET | Safety net |

**Verification:**
```bash
gcloud scheduler jobs list --location=us-west2 | grep -E "evening|catchup"
```

### 2. Service Account Fix

Fixed the scheduler script to use the correct service account (`756957797294-compute@developer.gserviceaccount.com`) matching existing analytics jobs.

### 3. Early Signal Validation (MIL@BOS only)

| Metric | Value | Notes |
|--------|-------|-------|
| Total picks | 7 | One complete game |
| Hit rate | 57.1% | 4/7 correct |
| High-edge picks | 1 | Edge = 5.2 |
| High-edge hit rate | 0% | 0/1 (missed by 0.5 pts) |

**Notable:** Jaylen Brown - predicted UNDER 29.5, actual 30. Missed by half a point.

---

## Key Finding: Gamebook Data Dependency

### The Problem

The evening schedulers trigger `PlayerGameSummaryProcessor`, but it requires `nbac_gamebook_player_stats` as its PRIMARY data source.

| Data Source | Feb 1 Status | Availability |
|-------------|--------------|--------------|
| `nbac_player_boxscores` | 152 records | Available during games |
| `nbac_gamebook_player_stats` | 0 records | Only available next morning |

### Why This Matters

1. Boxscores are scraped every 3 minutes during games
2. Gamebook data (from PDF parsing) is only processed overnight
3. Evening schedulers can't process analytics until gamebook exists

### Implication

**The evening schedulers will work once gamebook data is available**, but they won't enable same-day processing. The real fix requires either:

1. Running gamebook scraper after each game completes
2. Making PlayerGameSummaryProcessor fall back to boxscores
3. Creating a separate "quick grading" processor using boxscores

---

## Feb 1 Game Status (as of 11:15 PM ET)

| Status | Count | Games |
|--------|-------|-------|
| Final | 1 | MIL@BOS |
| In Progress | 4 | CHI@MIA, BKN@DET, UTA@TOR, SAC@WAS |
| Scheduled | 5 | OKC@DEN, LAL@NYK, CLE@POR, LAC@PHX, ORL@SAS |

---

## Feb 1 Signal Status

| Model | pct_over | Signal |
|-------|----------|--------|
| catboost_v9 | 10.6% | RED |
| catboost_v8 | 0.0% | RED |
| ensemble_v1 | 0.6% | RED |
| zone_matchup_v1 | 10.1% | RED |

All models show RED signal for Feb 1.

---

## Feb 2 Predictions

| Status | Value |
|--------|-------|
| Games | 4 (NOP@CHA, HOU@IND, PHI@LAC, MIN@MEM) |
| Predictions | 59 per model |
| Vegas lines | 0 (scraped at 7 AM ET) |
| Signals | Not yet calculated |

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| 52e2ee8d | fix: Use correct service account for evening analytics schedulers |

---

## Next Session Priorities

### 1. Validate Full Feb 1 Signal (HIGH)

Once gamebook data is available (~6 AM ET), validate RED signal hit rates:

```sql
SELECT
  CASE WHEN ABS(p.predicted_points - p.current_points_line) >= 5 THEN 'High Edge' ELSE 'Other' END as tier,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.game_date = DATE('2026-02-01')
  AND p.system_id = 'catboost_v9'
  AND p.current_points_line IS NOT NULL
  AND p.recommendation != 'PASS'
GROUP BY 1
```

Expected: 50-65% overall hit rate for RED signal day.

### 2. Verify Feb 2 Vegas Lines (After 7 AM ET)

```sql
SELECT system_id, COUNT(*) as predictions,
  COUNTIF(current_points_line IS NOT NULL) as has_lines
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-02')
GROUP BY system_id
```

### 3. Investigate Gamebook Scraper Automation

For same-day analytics processing, explore:
1. When does gamebook PDF become available after game completion?
2. Can we trigger gamebook scraper on game_status = 3?
3. Alternative: Create boxscore-based "quick grading" processor

See: `docs/08-projects/current/evening-analytics-processing/`

### 4. Check Evening Scheduler Execution

Verify the schedulers run correctly:

```bash
# Check job runs
gcloud scheduler jobs describe evening-analytics-10pm-et --location=us-west2 \
  --format="value(status.lastAttemptTime)"

# Check logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="nba-phase3-analytics-processors"
  AND timestamp>="2026-02-02T03:00:00Z"' --limit=20
```

---

## Verification Commands

```bash
# Check scheduler jobs
gcloud scheduler jobs list --location=us-west2 | grep -E "evening|catchup"

# Check Feb 1 data status
bq query --use_legacy_sql=false "
SELECT
  'boxscores' as src, COUNT(*) as records
FROM nba_raw.nbac_player_boxscores WHERE game_date = DATE('2026-02-01')
UNION ALL
SELECT
  'gamebook' as src, COUNT(*) as records
FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = DATE('2026-02-01')
UNION ALL
SELECT
  'player_game_summary' as src, COUNT(*) as records
FROM nba_analytics.player_game_summary WHERE game_date = DATE('2026-02-01')"

# Check game completion status
bq query --use_legacy_sql=false "
SELECT game_status,
  CASE game_status WHEN 1 THEN 'Scheduled' WHEN 2 THEN 'In Progress' WHEN 3 THEN 'Final' END as status,
  COUNT(*) as games
FROM nba_reference.nba_schedule
WHERE game_date = DATE('2026-02-01')
GROUP BY game_status"
```

---

## Key Files Modified

| File | Change |
|------|--------|
| `bin/orchestrators/setup_evening_analytics_schedulers.sh` | Fixed service account |

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
