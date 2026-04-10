# Session 517 Handoff — MLB Pipeline Unblocked

**Date:** 2026-04-08 to 2026-04-09
**Focus:** Fixed MLB prediction pipeline (99.3% BLOCKED → should be largely unblocked), verified all Session 516 fixes
**Commits:** `fe90a7d8`

---

## What Was Done This Session

### 1. Session 516 P0 Verification — All 8 Fixes Confirmed Working

| Check | Result |
|-------|--------|
| Traffic routing | All services routing to latest |
| Phase 3 amplification loop | Fixed — errors were old revision's final gasps |
| Scraper BQ BadRequest | Fixed — zero errors since new revision took traffic |
| Cleanup processor republishes | Fixed — 1 republish (schedule_api, expected) vs 36 before |
| Coordinator timedelta | Fixed — zero errors |

### 2. MLB Pipeline Fix — 3 Cascading Failures Resolved

**Root cause:** 99.3% of MLB predictions BLOCKED due to missing line features (f30, f32, f44). Three failures:

**Fix 1: BettingPros ExportMode case mismatch** (`fe90a7d8`)
- `bp_mlb_player_props.py` exporters used uppercase `"DATA"`, `"RAW"`, `"DECODED"`
- `ExportMode` enum expects lowercase `"data"`, `"raw"`, `"decoded"`
- Every export crashed with `ValueError` since Sep 2025 — zero BP line data for 2026 season
- Fix: Changed all 5 export_mode strings to lowercase

**Fix 2: Created Odds API pitcher props schedulers**
- `mlb_pitcher_props` scraper worked perfectly but had NO Cloud Scheduler jobs
- Created `mlb-oddsa-pitcher-props-morning` (10:30 UTC) and `mlb-oddsa-pitcher-props-pregame` (12:30 UTC)
- Test run: 248 rows, 10 pitchers, 6/6 events succeeded

**Fix 3: Fixed 4 stale MLB scheduler URLs**
- `mlb-events-pregame`, `mlb-schedule-daily`, `mlb-statcast-daily`, `mlb-lineups-morning`
- Updated from `756957797294.us-west2.run.app` to `f7p3g7f6ya-wl.a.run.app`

**Bonus:** Added OIDC auth to `mlb-bp-props-morning` and `mlb-bp-props-pregame` (were missing it)

### 3. Test Results

- BP props scraper: HTTP 200, found 6 events, 0 props (lines not posted yet at midnight ET — expected)
- Odds API props: HTTP 200, 6/6 events, 248 rows, 10 pitchers
- BQ data: 116 rows for Apr 9 in `oddsa_pitcher_props`

---

## Current System State

### MLB Pipeline
- **Code fix deployed** to `mlb-phase1-scrapers` (revision 00014-nmb, routing 100%)
- **6 scheduler jobs now properly configured** (2 new Odds API + 4 fixed URLs)
- **First full automated run:** Morning schedulers fire ~10:30 UTC (6:30 AM ET)
- **Expected outcome:** Line features populated → predictions unblocked for pitchers with coverage

### NBA
- Same as Session 516 — auto-halt active, season 415-235 (63.8%)
- Regular season ends ~Apr 13

---

## Tomorrow's Verification Plan

### P0: Verify MLB Pipeline Unblocked (morning after schedulers fire)

```bash
# 1. Check BP props scraper ran successfully (should have data after 10:45 UTC)
gcloud logging read \
  'resource.labels.service_name="mlb-phase1-scrapers" AND textPayload:"bp_mlb_player_props completed" AND timestamp>="2026-04-09T10:00:00Z"' \
  --project=nba-props-platform --limit=5 --format='table(timestamp,textPayload)'

# 2. Check Odds API props ran successfully
gcloud logging read \
  'resource.labels.service_name="mlb-phase1-scrapers" AND textPayload:"mlb_pitcher_props" AND textPayload:"succeeded" AND timestamp>="2026-04-09T10:00:00Z"' \
  --project=nba-props-platform --limit=5 --format='table(timestamp,textPayload)'

# 3. Check line data landed in BQ
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT 'oddsa' as source, COUNT(*) as cnt, COUNT(DISTINCT player_name) as pitchers
FROM mlb_raw.oddsa_pitcher_props WHERE game_date = '2026-04-09'
UNION ALL
SELECT 'bp' as source, COUNT(*) as cnt, COUNT(DISTINCT player_name) as pitchers
FROM mlb_raw.bp_pitcher_props WHERE game_date >= '2026-04-09'"

# 4. Check prediction BLOCKED rate dropped
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT game_date,
  COUNTIF(status = 'BLOCKED') as blocked,
  COUNTIF(status != 'BLOCKED') as unblocked,
  ROUND(COUNTIF(status = 'BLOCKED') * 100.0 / COUNT(*), 1) as blocked_pct
FROM mlb_predictions.pitcher_predictions
WHERE game_date >= '2026-04-08'
GROUP BY 1 ORDER BY 1 DESC"

# 5. Check the 4 fixed schedulers ran without errors
for job in mlb-events-pregame mlb-schedule-daily mlb-statcast-daily mlb-lineups-morning; do
  echo "=== $job ==="
  gcloud scheduler jobs describe $job --project=nba-props-platform --location=us-west2 --format='value(status,lastAttemptTime)' 2>&1
done
```

### P1: MLB Pipeline Depth Check

- **If BLOCKED rate still high:** Check which pitchers have lines vs which are in predictions. Coverage gap might be Odds API only covering ~10 of 30 pitchers. BP props need to actually return data (may need games to be closer to start time).
- **If BP props still 0:** The API may not post pitcher strikeout lines until closer to game time. Check if the pregame run (12:30 UTC / 8:30 AM ET) has better luck.

### P2: Ongoing Priorities (from Session 516)

| Priority | Task | Notes |
|----------|------|-------|
| P1 | Consider disabling cleanup processor | Has never worked correctly. Now down to 1 republish but still unnecessary. |
| P1 | Verify Phase 3 Pub/Sub push endpoint URL | Agent updated in Session 516, verify it persisted |
| P2 | Fix Phase 2 source_file_path tracking | Most write "unknown" |
| P2 | Recalibrate sharp_consensus_under by book source | Separate thresholds for Odds API vs BettingPros |
| P2 | NBA playoffs research | Do models/signals apply to playoff basketball? Season ends ~Apr 13 |
| P2 | Fix validation-runner deployment drift | Stale commit (12b9f65 vs 04b0a3b0) |

---

## Key Files Changed

| Purpose | File |
|---------|------|
| ExportMode case fix | `scrapers/bettingpros/bp_mlb_player_props.py` |

## Infrastructure Changes (not in code)

| Change | Details |
|--------|---------|
| New scheduler: `mlb-oddsa-pitcher-props-morning` | 10:30 UTC, `mlb_pitcher_props`, OIDC auth |
| New scheduler: `mlb-oddsa-pitcher-props-pregame` | 12:30 UTC, `mlb_pitcher_props`, OIDC auth |
| Fixed URL: `mlb-events-pregame` | `756957797294` → `f7p3g7f6ya-wl.a.run.app` |
| Fixed URL: `mlb-schedule-daily` | `756957797294` → `f7p3g7f6ya-wl.a.run.app` |
| Fixed URL: `mlb-statcast-daily` | `756957797294` → `f7p3g7f6ya-wl.a.run.app` |
| Fixed URL: `mlb-lineups-morning` | `756957797294` → `f7p3g7f6ya-wl.a.run.app` |
| Added OIDC: `mlb-bp-props-morning` | Was missing auth token |
| Added OIDC: `mlb-bp-props-pregame` | Was missing auth token |
