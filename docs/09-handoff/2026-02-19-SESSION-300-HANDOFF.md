# Session 300 Handoff: Pipeline Debugging, Phase 4→5 Fix, Historical Backfill, Scheduler IAM

**Date:** 2026-02-19
**Focus:** First post-ASB pipeline debugging, critical Phase 4→5 publish fix, historical odds backfill running, scheduler job IAM fixes.

## TL;DR

Investigated why only 6 predictions generated for tonight's 10-game slate. Found **two critical pipeline issues**: (1) Phase 4→5 Pub/Sub publish was broken (key mismatch: `data_date` vs `analysis_date`), preventing predictions from being triggered; (2) Game lines batch lock stuck on 1 game, leaving 9/10 games without vegas features. Fixed the publish bug and deployed. Fixed 4 PERMISSION_DENIED scheduler jobs (wrong Gen1 URLs + missing OIDC). Started full-season historical odds backfill (103 dates, Nov 2-Feb 12) — running in background.

## Critical Fix: Phase 4→5 Pub/Sub Publish Bug

**Root cause:** `precompute_base.py` line 622 looked for `self.opts.get('data_date')` or `self.opts.get('end_date')` but the actual key is `analysis_date`. This caused `game_date=None` → validation failure → "Missing required field: game_date" → Phase 5 never triggered.

**Fix:** Added `analysis_date` as first lookup: `self.opts.get('analysis_date') or self.opts.get('data_date') or self.opts.get('end_date')`

**Impact:** This bug has likely been silently preventing Phase 4→5 Pub/Sub triggering. Phase 5 was only running via the backup Cloud Scheduler (`nba-props-pregame` at 4 PM ET), not via the Phase 4 orchestrator. With the fix, Phase 5 should trigger immediately after Phase 4 completes.

**File:** `data_processors/precompute/base/precompute_base.py:622`

## Pipeline State (Feb 19, First Post-ASB)

| Component | Status | Details |
|-----------|--------|---------|
| Schedule | ✅ | 10 games, all status=1 (Scheduled) |
| Phase 3 UPCG | ✅ | 153 players across 10 games |
| Feature Store | ⚠️ | 153 records, 0 clean (all have defaults), 6 quality_ready (IND@WAS only) |
| Predictions | ⚠️ | Only 6 per model (IND@WAS), 12 systems × 6 = 72 total |
| Game Lines BQ | ❌ | 1/10 games (batch lock issue) |
| Game Lines GCS | ✅ | All 10 games scraped at 15:06 UTC |
| Odds API Props | ✅ | 5 books, 12 players |
| Best Bets | ❌ | Not yet generated (waiting on predictions) |

### Why Only 6 Predictions

1. **Game lines batch lock**: Phase 2 OddsAPI batch handler acquired lock for IND@WAS, then all 9 other games were rejected with "already being processed by another instance". Only IND@WAS has game_total/spread/implied_team_total in BQ.
2. **Feature defaults**: Without game lines, features 38 (game_total_line), 41 (spread_magnitude), 42 (implied_team_total) default for 9 games → players don't pass quality gates.
3. **Feature 39 (days_rest)**: Defaults for ALL players due to ASB gap (7+ days since last game). IND@WAS players with only this 1 default still pass quality_ready.
4. **Phase 4→5 publish broken**: Even if features were complete, Phase 5 wouldn't have been triggered by Phase 4 (only by backup scheduler).

### Expected Resolution

The next game lines scrape cycle will produce fresh GCS files → fresh Pub/Sub messages → bypass stale batch lock → Phase 2 processes all 10 games → Phase 3/4/5 chain runs. The Phase 4→5 fix is deployed, so the chain should complete automatically.

## Scheduler Jobs Fixed (4 PERMISSION_DENIED)

All 4 jobs had wrong URLs (Gen1 `cloudfunctions.net` instead of Gen2 `*.a.run.app`) and missing OIDC tokens.

| Job | Old URL | New URL | Status |
|-----|---------|---------|--------|
| `daily-reconciliation` | `cloudfunctions.net/reconcile` | `reconcile-f7p3g7f6ya-wl.a.run.app` | ✅ Fixed + tested |
| `validate-freshness-check` | `cloudfunctions.net/validate-freshness` | `validate-freshness-f7p3g7f6ya-wl.a.run.app` | ✅ Fixed |
| `nba-grading-gap-detector` | `cloudfunctions.net/grading-gap-detector` | `grading-gap-detector-f7p3g7f6ya-wl.a.run.app` | ✅ Fixed + tested |
| `validation-pre-game-final` | (URL was correct) | Added OIDC token only | ✅ Fixed |

All use service account `756957797294-compute@developer.gserviceaccount.com`.

Note: `daily-reconciliation` test run found "146 missing predictions" (expected — pipeline still processing) and has a `ModuleNotFoundError: No module named 'shared'` for Slack alerts (non-blocking).

## Historical Odds Backfill (In Progress)

**Script:** `scripts/backfill_historical_props_direct.py` — new lean script that calls Odds API directly (no subprocess, no SES, no scraper overhead). 10x faster than the original.

**Status at session end:** Running in background, date 12/103 (Nov 13). ~2 min per date, ~3 hours total.

**Config:**
- Date range: Nov 2, 2025 → Feb 12, 2026 (103 dates)
- Snapshot time: 18:00 UTC (2 PM ET — peak market coverage)
- All 12 sportsbooks
- Quota: started at 4.99M, ~1,300 used so far

**After backfill completes:**
```bash
# Load GCS files to BigQuery
PYTHONPATH=. python scripts/backfill_odds_api_props.py \
  --start-date 2025-11-02 --end-date 2026-02-12 --historical

# Verify coverage
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT DATE_TRUNC(game_date, WEEK) as week,
  COUNT(DISTINCT bookmaker) as avg_books,
  COUNT(DISTINCT player_lookup) as total_players,
  COUNT(*) as total_lines
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2025-11-02' AND points_line IS NOT NULL
GROUP BY 1 ORDER BY 1"
```

**If backfill crashed (check output):**
```bash
# Check progress
tail -30 /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b46e42b.output

# Resume from a specific date
export ODDS_API_KEY=$(gcloud secrets versions access latest --secret=ODDS_API_KEY --project=nba-props-platform)
PYTHONPATH=. python scripts/backfill_historical_props_direct.py \
  --start-date 2025-11-02 --end-date 2026-02-12 \
  --snapshot-time 18:00:00Z --skip-to-date YYYY-MM-DD --delay 1.0
```

## Commits This Session

```
27c173cd fix: Phase 4→5 publish bug — use analysis_date key, add direct backfill script
```

(Session 299 commits also on main: 471c1546, 0a9523f8, 0aca6caa, 113b6d61, c9746fa8)

## Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/base/precompute_base.py` | Fixed Phase 4→5 publish key mismatch (`analysis_date`) |
| `scripts/backfill_historical_props_direct.py` | NEW: Lean direct-API backfill script |
| `scripts/backfill_historical_props.py` | Increased events timeout to 300s |

## Next Session Priorities

### P0: Verify Pipeline Recovery
```bash
# 1. Check game lines loaded for all 10 games
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT COUNT(DISTINCT game_id) as games FROM nba_raw.odds_api_game_lines
WHERE game_date = '2026-02-19'"

# 2. Check predictions count increased
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT system_id, COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9'
GROUP BY 1"

# 3. Check best bets generated with natural sizing
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT algorithm_version, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-02-19'
GROUP BY 1"

# 4. Check low-vegas shadow generating predictions
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-19' AND system_id LIKE 'catboost_v9_low_vegas%'
GROUP BY 1"
```

### P1: Check/Complete Historical Odds Backfill
```bash
# Check if still running
tail -30 /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b46e42b.output

# If completed, load to BQ:
PYTHONPATH=. python scripts/backfill_odds_api_props.py \
  --start-date 2025-11-02 --end-date 2026-02-12 --historical
```

### P2: Grade Feb 19 Games
After tonight's games finish:
- Check grading ran for all models (champion + low-vegas shadow + other shadows)
- Verify `model_performance_daily` updates with fresh model data
- First real performance data for the new champion model

### P3: Investigate Game Lines Batch Lock
The OddsAPI batch handler lock prevented 9/10 games from processing. Check:
- Is this a recurring issue?
- Does the lock timeout properly?
- Should the batch handler be changed to per-game locking instead of per-date?

### P4: Investigate `daily-reconciliation` Shared Module Error
`ModuleNotFoundError: No module named 'shared'` in the reconcile Cloud Function. Non-blocking (Slack alerts only) but should be fixed for monitoring coverage.

### P5: Retrain Shadow Models
Wait for 2-3 days of post-ASB graded data. V12, Q43, Q45 are all stale/BLOCKED.
```bash
./bin/retrain.sh --all
```

## Infrastructure Notes

- **Batch lock pattern**: OddsAPI game lines use a date-level batch lock. If one instance processes even 1 game for a date, all other games for that date are rejected. This is fragile — should consider per-game locking.
- **Phase 4→5 was always broken**: The `data_date`/`end_date` keys were never set in opts for precompute processors. Phase 5 has been running ONLY via the backup `nba-props-pregame` scheduler (4 PM ET), not via the Phase 4→5 orchestrator. This means there was always a delay between Phase 4 completion and Phase 5 start.
- **Feature 39 (days_rest) defaults for all players post-ASB**: This is expected — 7+ days rest breaks the calculation. The quality_ready check allows 1 default, so players with ONLY days_rest defaulting still get predictions.
