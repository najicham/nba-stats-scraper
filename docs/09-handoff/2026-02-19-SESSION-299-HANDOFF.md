# Session 299 Handoff: Pipeline Monitoring, Low-Vegas Shadow, Historical Odds Testing

**Date:** 2026-02-19
**Focus:** First post-ASB game day monitoring, low-vegas shadow model deployment, historical odds API backfill testing and fixes.

## TL;DR

Games resume today (Feb 19) with a 10-game slate — first live test of the fresh champion model + natural sizing + 12-book odds. Deployed the low-vegas (0.25x) shadow model for live observation. Fixed and tested the historical odds backfill script — confirmed all 12 sportsbooks return data with 141-192 players per book at 18:00 UTC snapshots. Pipeline was in early stages at session end (Phase 3 1/5 complete, predictions pending).

## What's Deployed

### Low-Vegas Shadow Model (NEW)
- **Model:** `catboost_v9_low_vegas_train0106_0205`
- **GCS:** `gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_wt_train20260106-20260205_20260218_231928.cbm`
- **SHA256:** `aacdc7e038c6d9b3e0be3dbe573071c582c0ac0b0e1230953f7c0a3436517d67`
- **Training:** Jan 6 → Feb 5 (same window as champion, different vegas weight)
- **MAE:** 5.06 (vs 4.83 champion)
- **Edge 3+ HR:** 56.3% (N=48) — generates **5x more edge picks** than champion
- **UNDER HR:** 61.1% — strong UNDER performance
- **Registered in:** model_registry (enabled=TRUE), MONTHLY_MODELS fallback, cross_model_subsets
- **Family:** `v9_low_vegas` (prefix match: `catboost_v9_low_vegas_*`)
- **Subsets:** 4 created — `low_vegas_all_picks`, `low_vegas_high_edge`, `low_vegas_under_all`, `low_vegas_all_predictions`

### Historical Odds Backfill Fixes
- Fixed group name: `file` → `dev` (was causing events output to not be written)
- Increased subprocess timeout: 120s → 300s (SES secret lookup causes delays)
- Changed default snapshot time: 04:00 → 18:00 UTC (2 PM ET = peak market coverage)
- Added `--snapshot-time` CLI argument for flexibility

## Key Findings

### Odds API 12-Book Historical Coverage

**Test 1: Feb 12 at 04:00 UTC (midnight ET)**
- 7 events found, all scraped successfully
- Only 6 books returned data (too early for most books)
- SAS@GSW had 16 unique players (best), others had 5-13

**Test 2: Feb 11 at 18:00 UTC (2 PM ET)**
- 14 events found, all scraped successfully
- **ALL 12 books returned data**
- Per-book coverage: 141-192 unique players
- Total: 8,324 lines across all books

| Bookmaker | Players | Lines |
|-----------|---------|-------|
| betmgm | 192 | 1,076 |
| fliff | 182 | 364 |
| fanduel | 181 | 1,461 |
| draftkings | 180 | 1,427 |
| williamhill_us | 178 | 1,013 |
| betonlineag | 170 | 340 |
| betrivers | 168 | 1,097 |
| espnbet | 166 | 332 |
| hardrockbet | 165 | 330 |
| bovada | 160 | 320 |
| ballybet | 141 | 282 |
| betparx | 141 | 282 |

**Line spread across books (DAL@LAL example):**
- Austin Reaves: 23.5 - 28.5 (5.0 point spread!)
- LeBron James: 23.5 - 27.5 (4.0 spread)
- This makes `multi_book_line_std` (feature f50) much more informative

### Player Coverage Is Same, Price Discovery Is Better
- All 12 books offer props for the **same ~10-12 starters/key rotation players** per game
- Bovada adds alt lines (73 outcomes), ESPN adds alternates (33 outcomes)
- The real value is **price diversity** (12 opinions on each line), not more players
- Exception: Some books like FanDuel/BetMGM also cover deeper bench players

## Pipeline Status at Session End

| Check | Status | Details |
|-------|--------|---------|
| Cloud Builds | ✅ | All 8 builds SUCCESS (auto-deploy from push) |
| prediction-worker | ✅ | Rev 249, new champion model confirmed |
| prediction-coordinator | ✅ | Rev 256, deployed 07:23 UTC |
| Phase 3 | ⏳ | 1/5 processors (UPCG: 350 players, 10 games) |
| Phase 4-5 | ⏳ | Waiting on Phase 3 completion |
| Odds API (today) | ✅ | 5 of 12 books reporting, filling in |
| Scheduler | ⚠️ | 104/112 OK, 4 PERMISSION_DENIED, 4 DEADLINE_EXCEEDED |

## Next Session Priorities

### P0: Verify Today's Pipeline Completed
```bash
# 1. Check predictions generated
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as total,
  COUNTIF(is_active = TRUE AND ABS(predicted_points - current_points_line) >= 3) as edge_3_plus,
  COUNTIF(is_active = TRUE AND ABS(predicted_points - current_points_line) >= 5) as edge_5_plus
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-19'
GROUP BY 1 ORDER BY 1"

# 2. Verify algorithm_version = 'v298_natural_sizing'
bq query --use_legacy_sql=false "
SELECT algorithm_version, COUNT(*) as picks, ROUND(AVG(edge), 1) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-02-19'
GROUP BY 1"

# 3. Check low-vegas shadow is generating predictions
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-19' AND system_id LIKE 'catboost_v9_low_vegas%'
GROUP BY 1"

# 4. Verify odds from >2 books
bq query --use_legacy_sql=false "
SELECT bookmaker, COUNT(DISTINCT player_lookup) as players
FROM nba_raw.odds_api_player_points_props
WHERE game_date = '2026-02-19' AND points_line IS NOT NULL
GROUP BY 1 ORDER BY players DESC"
```

### P1: Run Historical Odds Backfill (Full Season)
The backfill script is fixed and tested. Run for the full season with 18:00 UTC snapshots:

```bash
export ODDS_API_KEY=$(gcloud secrets versions access latest --secret=ODDS_API_KEY --project=nba-props-platform)

# Full season backfill (Nov 2025 - Feb 2026)
# ~113 game dates × ~7 games/day × 1 API call/event = ~825 API calls
# Quota cost: ~8,300 units (0.2% of 4.99M remaining)
PYTHONPATH=. python scripts/backfill_historical_props.py \
  --start-date 2025-11-01 \
  --end-date 2026-02-12 \
  --snapshot-time 18:00:00Z \
  --delay 1.0

# Then load to BigQuery:
PYTHONPATH=. python scripts/backfill_odds_api_props.py \
  --start-date 2025-11-01 \
  --end-date 2026-02-12 \
  --historical
```

**After backfill, validate:**
```sql
-- Check coverage improvement across season
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(DISTINCT bookmaker) as avg_books,
  COUNT(DISTINCT player_lookup) as total_players,
  COUNT(*) as total_lines
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2025-11-01' AND points_line IS NOT NULL
GROUP BY 1 ORDER BY 1
```

**Research opportunity:** With 12 books of historical data, analyze:
1. **Line movement velocity** — how fast books converge before tip-off
2. **Sharp money detection** — which book moves first (leading indicator)
3. **Cross-book spread vs hit rate** — does high line disagreement predict model accuracy?
4. **Opening vs closing lines** — if multi-snapshot data available

### P2: Fix PERMISSION_DENIED Scheduler Jobs
4 jobs failing with code 7 (PERMISSION_DENIED):
- `daily-reconciliation`
- `validate-freshness-check`
- `validation-pre-game-final`
- `nba-grading-gap-detector`

Fix:
```bash
# For each job, check what service it targets and fix IAM
gcloud scheduler jobs describe <JOB_NAME> --location=us-west2 --project=nba-props-platform --format="yaml(httpTarget.uri)"

# Then add invoker role to target service
gcloud run services add-iam-policy-binding <SERVICE_NAME> \
  --region=us-west2 \
  --member='serviceAccount:756957797294-compute@developer.gserviceaccount.com' \
  --role='roles/run.invoker' \
  --project=nba-props-platform
```

### P3: Retrain Shadow Models
Wait for 2-3 days of post-ASB graded data, then:
```bash
./bin/retrain.sh --all
```
V12 MAE, Q43, Q45, V12-Q43, V12-Q45 are all stale/BLOCKED.

### P4: Grade Feb 19 Games and Monitor Fresh Model
After tonight's games finish:
- Check grading ran for all models (champion + low-vegas shadow + other shadows)
- Verify `model_performance_daily` updates with fresh model data
- Compare low-vegas edge distribution vs champion
- Track: does low-vegas produce more edge 3+ picks as expected?

### P5: Research — Scoring Distribution Analysis
Deferred from Session 298. With post-ASB data flowing:
- Compute team-level scoring concentration (HHI/Gini) by month
- Check if model errors correlate with scoring redistribution
- If significant: add `team_scoring_concentration` feature

## Commits This Session
```
471c1546 fix: historical props backfill — correct group name, increase timeout, add snapshot-time arg
0a9523f8 feat: deploy low-vegas (0.25x) shadow model, add v9_low_vegas family
0aca6caa feat: break-day awareness sweep — suppress false alerts on non-game days
113b6d61 feat: add duplicate detection canary for player_game_summary
c9746fa8 fix: dedup player_game_summary in last-10 query, guard negative days_rest
```

All pushed to main, auto-deploying via Cloud Build.

## Files Changed

| File | Change |
|------|--------|
| `predictions/worker/prediction_systems/catboost_monthly.py` | Added low-vegas shadow to MONTHLY_MODELS fallback |
| `shared/config/cross_model_subsets.py` | Added `v9_low_vegas` family pattern |
| `scripts/backfill_historical_props.py` | Fixed group name, timeout, snapshot-time arg |
| `data_processors/publishing/tonight_all_players_exporter.py` | Dedup CTE fix, days_rest guard |
| `bin/monitoring/pipeline_canary_queries.py` | Duplicate detection canary |
| `shared/utils/schedule_guard.py` | Break-day awareness utility |
| `scrapers/*/` | Break-day suppression for false alerts |

## Model Registry State

| Model | Family | Status | HR 3+ | Notes |
|-------|--------|--------|-------|-------|
| `catboost_v9` (champion) | v9_mae | PRODUCTION | Fresh (retrained Feb 18) | MAE 4.83 |
| `catboost_v9_low_vegas_train0106_0205` | v9_low_vegas | SHADOW (NEW) | 56.3% (N=48) | 5x more edge picks |
| `catboost_v12_noveg_train1102_0205` | v12_mae | SHADOW | 69.2% | STALE |
| `catboost_v9_q43_train1102_0125` | v9_q43 | SHADOW | 62.6% | STALE |
| `catboost_v9_q45_train1102_0125` | v9_q45 | SHADOW | 62.9% | STALE |
| `catboost_v12_noveg_q43_train1102_0125` | v12_q43 | SHADOW | 61.6% | STALE |
| `catboost_v12_noveg_q45_train1102_0125` | v12_q45 | SHADOW | 61.2% | STALE |

## Infrastructure Notes

- **ODDS_API_KEY** is in Secret Manager, not env var locally. Backfill script loads via scraper's auth_utils. For direct curl tests: `export ODDS_API_KEY=$(gcloud secrets versions access latest --secret=ODDS_API_KEY --project=nba-props-platform)`
- **SES secret timeout** causes slow scraper runs locally (504 on aws-ses-access-key-id). Not an issue in Cloud Run. Backfill timeout increased to 300s to accommodate.
- **Snapshot time matters hugely** for historical API. 04:00 UTC gets 5-6 books. 18:00 UTC gets all 12. Always use `--snapshot-time 18:00:00Z` for backfills.
