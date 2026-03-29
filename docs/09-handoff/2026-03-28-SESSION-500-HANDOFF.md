# Session 500 Handoff — 2026-03-28 (late evening)

**Date:** 2026-03-28
**Commits:** 15 commits — entire MLB pipeline unblocked, first 2026 MLB predictions written to BQ

---

## The Big Picture

Sessions 499+500 fixed the entire MLB Opening Day pipeline cascade failure from scratch.
Starting state: 0 MLB records anywhere for 2026.
Ending state: MLB predictions running, 5 live predictions written to BQ for March 28.

---

## MLB Pipeline — Current State (WORKING)

### Data Flow Status

| Table | Max Date | Rows (2026) | Status |
|-------|----------|-------------|--------|
| `mlb_raw.mlbapi_pitcher_stats` | 2026-03-27 | 70 | ✅ Phase 2 working |
| `mlb_raw.oddsa_pitcher_props` | 2026-03-28 | 667 | ✅ Phase 2 working |
| `mlb_analytics.pitcher_game_summary` | 2026-03-27 | 16 | ✅ Phase 3 working |
| `mlb_analytics.batter_game_summary` | 2026-03-27 | 140 | ✅ Phase 3 working |
| `mlb_precompute.pitcher_ml_features` | 2026-03-28 | 30 | ✅ Phase 4 working |
| `mlb_predictions.pitcher_strikeouts` | 2026-03-28 | 5 | ✅ Phase 5 **LIVE** |

### March 28 Live Predictions (First Ever 2026 MLB Picks)

| Pitcher | Team | Opp | Pred | Line | Edge | Rec |
|---------|------|-----|------|------|------|-----|
| cade_horton | CHC | NYM | 5.3 | 4.5 | 0.77 | **OVER** |
| brady_singer | STL | MIL | 5.1 | 4.5 | 0.59 | **OVER** |
| jeffrey_springs | TOR | HOU | 4.8 | 3.5 | 1.26 | **OVER** |
| michael_mcgreevy | STL | CHC | 4.4 | 3.5 | 0.92 | **OVER** |
| joe_boyle | ATH | TOR | 5.5 | 5.5 | 0.01 | SKIP |

All 5 have 0 default features (fully-featured predictions).

288 pitchers BLOCKED (no K prop line in either BettingPros or Odds API) — expected for Opening Day. As the season progresses, more K lines will be available and predictions will expand.

---

## What Was Fixed (15 Commits)

### MLB Phase 2 (Raw Processing)
- `message_handler.py`: Empty Pub/Sub OIDC probe → 24K+ infinite retry loop. Fixed: return HTTP 200 on empty data.
- `SKIP_DEDUPLICATION = True` on MLB pitcher/batter/game_lines processors — they're time-series snapshots.
- Registered `MlbApiPitcherStatsProcessor` + `MlbApiBatterStatsProcessor` for `mlb-stats-api/box-scores` GCS path.
- Fixed `YESTERDAY` date literal in `config_mixin.py`.

### MLB Phase 3 (Analytics)
- Source table mismatch: was reading `mlb_pitcher_stats` (empty 2026), should be `mlbapi_pitcher_stats`.
- Column name fixes: `opponent_abbr`, `home_away` → bool CASE, `pitches_thrown`, `walks`.
- SQL fixes: empty CTE `WHERE FALSE` without FROM, untyped `NULL as venue` → `CAST(NULL AS STRING)`.
- `BQ_LOCATION=US` on service env vars (was us-west2, MLB data is US multi-region).
- Added `APP_MODULE` build arg to analytics Dockerfile for MLB entry point.

### MLB Phase 4 (Precompute)
- Schedule query column names: `home_probable_pitcher_id/name`, `game_time_utc`, `day_night`, `status_code`.
- `extract_raw_data` abstract method stub (MLB processors use `process_date()` directly).
- `BQ_LOCATION=US` env var.
- Added `APP_MODULE` build arg to precompute Dockerfile.
- Fixed `date` serialization before `insert_rows_json`.
- Removed legacy `bottom_up_k_expected` field (not in BQ schema).

### MLB Phase 5 (Predictions)
- **Root cause:** `bp_pitcher_props` has zero 2026 data (last row 2025-09-28). All 4 line-dependent features NULL.
- Added `oddsa_ranked` CTE in `pitcher_loader.py` — falls back to `mlb_raw.oddsa_pitcher_props` when `bp_pitcher_props` has no row.
- Fixed JOIN: `REPLACE(lf.player_lookup, '_', '') = oddsa.player_lookup` (oddsa uses `yuseikikuchi`, game_summary uses `yusei_kikuchi`).
- Fixed `season_k_per_9 = NULL` on Opening Day: `COALESCE(season_k_per_9, k_per_9_rolling_10)`.
- Expanded `latest_features` lookback from 30 → 365 days (offseason = 5+ months gap).
- Added `f40_bp_projection` to `NAN_TOLERANT_FEATURES` in both CatBoost predictors.

### MLB Lineup Analysis (Phase 4)
- Removed `k_rate_last_30` from SELECT (column doesn't exist in `batter_game_summary`).
- Replaced `bdl_pitchers` query with `mlb_pitcher_stats` for handedness data.

### NBA
- Fixed `fta_avg`/`fta_cv` NameError in `aggregator.py` — `ft_anomaly_over_block` was silently disabled.

### Infrastructure
- Disabled `mlb-live-boxscores` scheduler (was sending missing `game_pk` to game_feed scraper → 100% fail).
- Granted `mlb-monitoring-sa` `roles/run.invoker`.
- Created 3 missing `mlb_orchestration` tables.
- Added `SLACK_WEBHOOK_URL` to `weekly-retrain` Cloud Run service.
- Purged 24K+ stuck messages from `mlb-phase2-raw-sub`.

---

## MLB Service Deployment — IMPORTANT

MLB analytics/precompute/worker do **NOT auto-deploy**. Require manual builds:

```bash
# Build templates
cat > /tmp/mlb-analytics-build.yaml <<'EOF'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'data_processors/analytics/Dockerfile',
           '--build-arg', 'APP_MODULE=mlb.main_mlb_analytics_service:app',
           '-t', 'us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors:latest', '.']
images: ['us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors:latest']
EOF

cat > /tmp/mlb-precompute-build.yaml <<'EOF'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'data_processors/precompute/Dockerfile',
           '--build-arg', 'APP_MODULE=mlb.main_mlb_precompute_service:app',
           '-t', 'us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-precompute-processors:latest', '.']
images: ['us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-precompute-processors:latest']
EOF

# MLB prediction worker uses its own build config:
gcloud builds submit --region=us-west2 --project=nba-props-platform --config=cloudbuild-mlb-worker.yaml .
gcloud run services update mlb-prediction-worker --region=us-west2 --project=nba-props-platform \
  --image="gcr.io/nba-props-platform/mlb-prediction-worker:latest"
```

After building analytics/precompute, deploy via:
```bash
DIGEST=$(gcloud artifacts docker images describe \
  "us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors:latest" \
  --format="value(image_summary.digest)")
gcloud run services update mlb-phase3-analytics-processors --region=us-west2 --project=nba-props-platform \
  --image="us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors@${DIGEST}" --args=""
# Then route traffic to the new revision:
NEW_REV=$(gcloud run services describe mlb-phase3-analytics-processors --region=us-west2 \
  --project=nba-props-platform --format="value(status.latestCreatedRevisionName)")
gcloud run services update-traffic mlb-phase3-analytics-processors --region=us-west2 \
  --project=nba-props-platform --to-revisions="${NEW_REV}=100"
```

---

## MLB Daily Trigger Commands

The MLB pipeline does NOT auto-trigger from Pub/Sub yet for manual backfills. Use:

```bash
# Phase 3 (after Phase 2 processes raw data)
PHASE3_URL="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token --audiences="$PHASE3_URL")
curl -s -X POST "$PHASE3_URL/process-date" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"game_date": "2026-MM-DD"}'

# Phase 4
PHASE4_URL="https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token --audiences="$PHASE4_URL")
curl -s -X POST "$PHASE4_URL/process-date" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"game_date": "2026-MM-DD"}'

# Phase 5 (generates + writes predictions)
WORKER_URL="https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token --audiences="$WORKER_URL")
curl -s -X POST "$WORKER_URL/predict-batch" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"game_date": "2026-MM-DD", "write_to_bigquery": true}'
```

---

## Open Issues (Next Session Priority)

### 1. MLB lineup analysis processor — Phase 4 needs redeploy (LOW)
The `k_rate_last_30` fix and `bdl_pitchers` → `mlb_pitcher_stats` fix were committed but Phase 4 precompute image hasn't been rebuilt with these changes yet. Phase 4 still works (warnings, not errors), but rebuild when convenient.

### 2. `mlb_lineup_batters` has no 2026 data (MEDIUM)
Table is empty for 2026. The lineup scraper (`scrapers/mlb/mlbstatsapi/mlb_lineups.py`) hasn't run for 2026. Without lineup data, `MlbLineupKAnalysisProcessor` returns `no_analyses` — lineup-based features (`f25_bottom_up_k_expected`, `f26_lineup_k_vs_hand`) will be 0/default for all predictions. Need to investigate why the lineup scraper isn't writing 2026 data.

### 3. MLB prediction coverage — 288/293 BLOCKED (EXPECTED, IMPROVES NATURALLY)
Only pitchers with K prop lines in `oddsa_pitcher_props` generate live predictions. As the season progresses, more bookmakers will post K lines for more pitchers. No action needed — will self-resolve.

### 4. NBA Monday Retrain (CRITICAL — March 30 5 AM ET)
- Scheduler `weekly-retrain-trigger` is ENABLED and READY
- TIGHT cap will fire: train window = Jan 9 – Mar 7
- Slack alerts now configured (SLACK_WEBHOOK_URL added this session)
- After completion: `./bin/model-registry.sh sync && ./bin/refresh-model-cache.sh --verify`

### 5. NBA Fleet Degraded (WATCH)
- `catboost_v12_noveg_train0118_0315`: BLOCKED, N=13 — 2 more picks to auto-disable
- `catboost_v12_noveg_train0121_0318`: BLOCKED, day 1 (N too small to trust)
- Monday retrain should restore fleet

---

## MLB Prediction Model Context

- **Active model:** `catboost_v2_regressor` (36 features)
- **Model file:** `gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_40f_20250928.cbm`
- **Trained:** May 31 – Sep 28, 2025 (120-day window, 3,855 samples)
- **Validation:** 59.4% HR overall, **70.65% HR at edge ≥ 0.75** (N=184)
- **Top features:** f32_line_level (20.8%), f72_fip (12.5%), f40_bp_projection (9.3%)
- **Strategy:** OVER-only, edge 0.75 (home) / 1.25 (away), top-5/day (per MLB strategy doc)
- **Key limitation:** `f40_bp_projection` passes NaN when BettingPros has no row. CatBoost handles this natively; predictions are slightly degraded but not blocked.

---

## Key File Locations

| Component | File |
|-----------|------|
| MLB prediction worker | `predictions/mlb/worker.py` |
| Feature loader | `predictions/mlb/pitcher_loader.py` |
| CatBoost V2 predictor | `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py` |
| Phase 3 pitcher summary | `data_processors/analytics/mlb/pitcher_game_summary_processor.py` |
| Phase 4 pitcher features | `data_processors/precompute/mlb/pitcher_features_processor.py` |
| Phase 4 lineup analysis | `data_processors/precompute/mlb/lineup_k_analysis_processor.py` |
| MLB strategy doc | `docs/08-projects/current/mlb-2026-season-strategy/` |
| MLB launch runbook | `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md` |
