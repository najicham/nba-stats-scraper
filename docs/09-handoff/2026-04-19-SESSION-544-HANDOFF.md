# Session 544 Handoff — OIDC full sweep + canary playoff mode

**Date:** 2026-04-19 (end of S544)
**Prior sessions:** S542 fixed 8 bugs (Apr 17 MLB outage). S543 did OIDC audit + canary playoff mode.

> **Read first:** [S543](./2026-04-18-SESSION-543-HANDOFF.md) for S542/S543 context.

---

## TL;DR

S544 completed the full OIDC sweep (57 jobs fixed), paused a noisy failing scheduler, and added playoff mode to the canary. The canary should drop from 13→2 failures once it picks up the new image. Four Part 1 jobs still need their first successful run to clear.

---

## What was done this session

### 1. OIDC — full sweep complete (57 jobs)

S542 fixed 4 jobs. S543 fixed 18 MLB jobs. S544 fixed 39 non-MLB jobs.

**Final state: ALL CLEAR.** Zero enabled, HTTP-target, ever-run schedulers without OIDC.

Groups fixed this session:
- 13 Cloud Functions (`analytics-quality-check-morning`, `daily-health-check-8am-et`, `data-source-health-canary-daily`, `grading-delay-alert-job`, `line-quality-self-heal-job`, `live-export-evening`, `live-freshness-monitor`, `missing-prediction-check`, `news-fetcher`, `prediction-health-alert-job`, `shadow-performance-report-job`, `signal-decay-monitor-daily`, `source-block-alert-scheduler`)
- 14 Cloud Run Services (`bigquery-daily-backup`, `daily-health-summary-job`, `data-quality-alerts-job`, `dlq-monitor-job`, `enrichment-daily`, `live-export-late-night`, `nba-daily-summary-prod`, `nba-grading-alerts-daily`, `nba-monitoring-alerts`, `phase4-timeout-check-job`, `pipeline-health-monitor-job`, `pipeline-reconciliation-job`, `stale-running-cleanup-job`, `stalled-batch-cleanup`)
- 12 Cloud Run Jobs API + scrapers (`ar-weekly-cleanup`, `nba-auto-batch-cleanup-trigger`, `nba-confidence-drift-monitor`, `nba-deployment-drift-alerter-trigger`, `nba-feature-staleness-monitor`, `nba-pipeline-canary-routine-trigger`, `nba-pipeline-canary-trigger`, `nba-q43-performance-monitor-trigger`, `player-movement-registry-afternoon`, `player-movement-registry-morning`, `trigger-health-check`, `espn-projections-daily`)

**Verified working:** `mlb-overnight-results` (200, 119 records). `mlb-weekly-hr-check` (reached slack-reminder service, Pushover 400 = app-level, not auth).

### 2. Paused `same-day-predictions-tomorrow`

Root cause: coordinator returns 503 every night during playoffs — `DATA COMPLETENESS GATE: 76% < 80%`. Correct behavior, but scheduler marks it failed. **Paused until next season.**

Logs confirmed: `TOMORROW` resolves to Apr 19, coordinator starts, hits coverage gate immediately, returns 503. Retries 3x, final code 14 (UNAVAILABLE).

### 3. Canary playoff mode (commit `f87795b8`)

**Root cause of 13 canary failures:** `is_break_window` returns `False` during playoffs (because `004%` games exist), so all prediction checks ran and failed on expected zeroes.

**Changes to `bin/monitoring/pipeline_canary_queries.py`:**

- Added `_is_playoff_window(client)`: queries last 14 days, returns True if `004%` games exist and regular season (`002%`) ended 3+ days ago
- Added `is_nba_offseason = is_break or is_playoff`
- Added `PLAYOFF_SKIP_PHASES`: skips `phase1_scrapers`, `phase2_raw_processing`, `phase5_predictions`, `phase5_shadow_coverage`, `phase6_publishing` during playoffs
- Changed 8 dynamic `not is_break` gates → `not is_nba_offseason` (bb_pick_drought, bb_filter_audit, live_grading_content, shadow auto-heal, bb_candidates_today, edge_collapse_alert, new_model_no_predictions, Phase 3 auto-heal)
- Fixed 3 SQL queries to exclude `004%` playoff games from `expected_games` counts: `phase3_gap_detection`, `phase3_partial_coverage`, `phase5_prediction_gap`

**New image built and pushed:** `us-west2-docker.pkg.dev/nba-props-platform/nba-props/pipeline-canary:latest` (build `4128bbc5`, SUCCESS, ~05:27 UTC Apr 19)

**Expected result:** Canary drops from 13 failures → ~2 when it next runs:
- `mlb-live-boxscores` (PAUSED, BDL 401) — still counts
- `scheduler_health` passing at 1-2 jobs (within threshold of 3)

**Note on playoff detection timing:** The `_is_playoff_window` check uses `date.today()`. Today (Apr 19 UTC) the check will see Apr 18's `004%` games + Apr 12's last `002%` games (7 days ago ≥ 3) → `is_playoff = True`. Correctly activates.

### 4. Part 3 (BDL) — confirmed, no action

Key has MLB data access (`/mlb/v1/teams` = 200), but `/mlb/v1/box_scores/live` = 401 (higher tier). `mlb_game_feed` is NOT a replacement (requires `game_pk`, pitch-by-play only). Keep `mlb-live-boxscores` PAUSED — we have no live betting system.

### 5. Never-run schedulers — all intentional

8 ENABLED jobs with no `lastAttemptTime`. All are future-dated seasonal jobs:

| Job | Next run | Purpose |
|-----|----------|---------|
| `mlb-asb-prep` | Jul 14, 2026 | MLB All-Star Break prep |
| `mlb-blacklist-review-jun` | Jun 1, 2026 | Mid-season blacklist review |
| `mlb-monthly-fangraphs-refresh` | May 1, 2026 | Monthly FanGraphs data |
| `mlb-resume-reminder-mar24` | Mar 24, 2027 | Annual season-start reminder |
| `mlb-retrain-reminder-mar18` | Mar 18, 2027 | Annual retrain reminder |
| `mlb-signal-promotion-review` | May 15, 2026 | Signal promotion review |
| `mlb-under-decision` | May 1, 2026 | UNDER strategy decision |
| `nba-playoffs-shadow-review` | May 1, 2026 | NBA playoff shadow review |

No action needed.

### 6. MLB pipeline health

- Apr 18: 28 preds, 1 BB pick (Sandy Alcantara OVER), grading pending (runs ~10 AM ET)
- Season to date (Apr 1-17): **71/130 = 54.6% HR** — above 50%, but below the 63.4% 4-season replay benchmark. Early season variance likely.
- Notable bad days: Apr 16 = 25% (3/12), Apr 13 = 33.3% (3/9). Investigate.

---

## Part 1 — 4 self-heal jobs (STILL PENDING)

These fired their last runs before the S542 fixes. All now have OIDC. Check after their scheduled times Apr 19:

| Job | Fix | Expected clear |
|-----|-----|----------------|
| `mlb-game-lines-morning` | `date`→`game_date` param | ~10:30 AM ET |
| `mlb-props-morning` | OIDC added S542 | ~10:30 AM ET |
| `mlb-umpire-assignments` | `decoded_data` fix + OIDC | ~11:30 AM ET |
| `mlb-props-pregame` | OIDC added S542 | ~12:30 PM ET |

```bash
# Check after 1 PM ET Apr 19
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="json" | python3 -c "
import json,sys
jobs = json.load(sys.stdin)
targets = ['mlb-game-lines-morning','mlb-umpire-assignments','mlb-props-morning','mlb-props-pregame']
for j in jobs:
    name = j['name'].split('/')[-1]
    if name in targets:
        code = j.get('status',{}).get('code','OK')
        last = j.get('lastAttemptTime','never')[:19]
        print(f'{name}: code={code} last={last}')
"
```

**Expected:** All show `code=OK` (blank) with `last=` today's date.

---

## New investigations for next session

### Priority 1 — Verify things this session changed

**1a. Run canary to confirm playoff mode works**
```bash
gcloud run jobs execute nba-pipeline-canary --region=us-west2 --project=nba-props-platform --wait
gcloud logging read 'resource.labels.job_name="nba-pipeline-canary"' \
  --project=nba-props-platform --limit=30 --format="json" --freshness=5m 2>&1 | python3 -c "
import json,sys; logs=json.load(sys.stdin)
for l in reversed(logs):
    msg=l.get('textPayload','')
    if any(k in msg for k in ['Found','FAIL','PASS','playoff','Playoff','failing_jobs','SKIPPED']):
        print(l['timestamp'][:19], msg[:200])
"
```
**Expected:** `Playoff mode detected`, `SKIPPED (playoff mode)` for phase5/phase6, `failing_jobs: ≤3`.

**1b. Verify MLB grading OIDC fix (after ~10 AM ET Apr 19)**
```bash
bq query --use_legacy_sql=false --location=US --format=pretty \
'SELECT game_date, COUNT(*) as graded, COUNTIF(prediction_correct IS NOT NULL) as fully_graded
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date >= DATE("2026-04-17") AND game_date >= DATE("2026-04-01")
GROUP BY 1 ORDER BY 1 DESC'
```
**Expected:** Apr 18 gains graded records after `mlb-grading-daily` fires.

**1c. Spot-check 2 more newly OIDC'd NBA schedulers**
```bash
# Verify nba-deployment-drift-alerter-trigger works with OIDC
gcloud scheduler jobs run nba-deployment-drift-alerter-trigger \
  --location=us-west2 --project=nba-props-platform
# Check logs 30s later
gcloud logging read 'resource.labels.job_name="nba-deployment-drift-alerter"' \
  --project=nba-props-platform --limit=5 --freshness=3m \
  --format="value(timestamp,textPayload)" 2>&1 | head -10
```

### Priority 2 — MLB season performance analysis

**2a. Investigate Apr 13 (33%) and Apr 16 (25%) bad days**
```bash
bq query --use_legacy_sql=false --location=US --format=pretty \
'SELECT game_date, player_name, recommendation, line_value, predicted_points,
  actual_points, prediction_correct
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date IN ("2026-04-13", "2026-04-16")
  AND game_date >= DATE("2026-04-01")
ORDER BY game_date, prediction_correct'
```
Are the misses systematic (e.g., all UNDERs? all rain games? specific pitchers)?

**2b. MLB season HR by week**
```bash
bq query --use_legacy_sql=false --location=US --format=pretty \
'SELECT DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as graded, COUNTIF(prediction_correct = TRUE) as correct,
  ROUND(COUNTIF(prediction_correct=TRUE)*100.0/NULLIF(COUNT(*),0),1) as hr_pct
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date >= DATE("2026-04-01") AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1'
```

### Priority 3 — Future-dated scheduler readiness

**3a. `nba-playoffs-shadow-review` (May 1)** — what does this do? Is it properly configured?
```bash
gcloud scheduler jobs describe nba-playoffs-shadow-review \
  --location=us-west2 --project=nba-props-platform --format=json | python3 -c "
import json,sys,base64; j=json.load(sys.stdin)
http=j.get('httpTarget',{})
body=http.get('body','')
if body: print('Body:', base64.b64decode(body).decode())
print('URI:', http.get('uri',''))
print('Has OIDC:', 'oidcToken' in http)
"
```

**3b. `mlb-signal-promotion-review` (May 15)** — which signals are candidates for promotion?

Check current shadow signal HRs to identify which should be promoted by May:
```bash
bq query --use_legacy_sql=false --location=US --format=pretty \
'SELECT signal_name, regime, signal_count, hit_rate_7d, hit_rate_30d
FROM `nba-props-platform.mlb_predictions.signal_health_daily`
WHERE game_date = (SELECT MAX(game_date) FROM `nba-props-platform.mlb_predictions.signal_health_daily`)
ORDER BY hit_rate_30d DESC NULLS LAST
LIMIT 20'
```

### Priority 4 — Investigate `mlb-live-boxscores` replacement

If live in-game data ever matters for MLB, the path is the MLB Stats API, which is already in the codebase (`mlb_game_feed.py`). A wrapper that:
1. Queries today's game schedule
2. Iterates over in-progress games to get live box scores per `game_pk`

This is a ~1-2 hour implementation. Scope it before committing. Key question: do we actually need live scoring for any current feature?

### Priority 5 — Off-season planning

NBA playoffs run through ~June 22. Off-season: June 23 - October 2026.

Questions to answer before off-season:
- Which schedulers should be paused during NBA off-season? (NBA scrapers, NBA grading, NBA predictions)
- Which should keep running? (MLB pipeline runs through September)
- Should we add an `OFF_SEASON_MODE` env var to suppress all NBA Slack alerts?
- When should the weekly NBA retrain CF be paused? (Models stale after 10+ days)

---

## State at session end (S544)

- **`nba-stats-scraper` main:** `f87795b8` (playoff mode canary)
- **Commits this session:** `f87795b8` (canary playoff mode)
- **Canary image:** rebuilt, pushed at ~05:27 UTC Apr 19 (build `4128bbc5`)
- **OIDC:** ALL CLEAR — 57 jobs fixed across S542/S543/S544
- **`same-day-predictions-tomorrow`:** PAUSED (coordinator 503 during playoffs)
- **Part 1 jobs:** 4 still pending first successful run (by 12:30 PM ET Apr 19)
- **MLB pipeline:** healthy, 54.6% HR (Apr 1-17, N=130)
- **NBA pipeline:** playoffs, auto-halted, 0 picks expected. All models BLOCKED.

### Paused schedulers (DO NOT unpause without reason)
- `mlb-live-boxscores` — BDL tier 401, no live betting system yet
- `nba-playoffs-shadow-activate` — annual (Apr 14 only), re-enable before Apr 14, 2027
- `same-day-predictions-tomorrow` — coordinator 503 (coverage gate) during playoffs, re-enable Oct 2026

---

## Quick start for next session

```bash
# 1. Verify 4 Part 1 jobs self-healed (after 1 PM ET)
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="json" | python3 -c "
import json,sys
jobs = json.load(sys.stdin)
for j in jobs:
    name = j['name'].split('/')[-1]
    if name in ['mlb-game-lines-morning','mlb-umpire-assignments','mlb-props-morning','mlb-props-pregame']:
        code = j.get('status',{}).get('code','OK')
        print(f'{name}: {code}')
"

# 2. Run canary and verify playoff mode + failure count
gcloud run jobs execute nba-pipeline-canary --region=us-west2 --project=nba-props-platform --wait
gcloud logging read 'resource.labels.job_name="nba-pipeline-canary"' \
  --project=nba-props-platform --limit=20 --format="json" --freshness=5m 2>&1 | python3 -c "
import json,sys; logs=json.load(sys.stdin)
for l in reversed(logs):
    msg=l.get('textPayload','')
    if any(k in msg for k in ['Found','FAIL','PASS','playoff','failing_jobs','SKIPPED']):
        print(l['timestamp'][:19], msg[:200])
"

# 3. Check MLB grading (Apr 18 should now be graded)
bq query --use_legacy_sql=false --location=US --format=pretty \
'SELECT game_date, COUNT(*) as graded FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date >= DATE("2026-04-17") AND game_date >= DATE("2026-04-01")
GROUP BY 1 ORDER BY 1 DESC'
```
