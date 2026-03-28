# Session 499 Handoff — 2026-03-28

**Date:** 2026-03-28 (afternoon ET)
**Commits:** 10 commits — all MLB pipeline bugs, NBA aggregator fix, infrastructure

---

## What Was Accomplished

This session fixed the entire MLB Opening Day pipeline cascade failure. Starting from 0 records
in any 2026 MLB table, we worked through each layer of bugs systematically.

### MLB Pipeline: Fixed End-to-End (Phases 1-4)

**Phase 2 — Raw Processing:**
- Fixed infinite retry loop: `mlb-phase2-raw-sub` was stuck retrying 24K+ times/day due to empty
  Pub/Sub OIDC probe messages. Added empty-data guard in `message_handler.py` → returns HTTP 200.
- Fixed `SKIP_DEDUPLICATION = True` on `MlbPitcherPropsProcessor`, `MlbBatterPropsProcessor`,
  `MlbGameLinesProcessor` — they write time-series snapshots, dedup by date was skipping all but first.
- **Result:** `mlb_raw.oddsa_pitcher_props` now has 667 rows through 2026-03-28.
- **Result:** `mlb_raw.mlbapi_pitcher_stats` now has 70 rows for 2026-03-27.

**Phase 3 — Analytics:**
- Fixed source table mismatch: processor read `mlb_pitcher_stats` but Phase 2 writes `mlbapi_pitcher_stats`.
- Fixed column name differences: `opponent_abbr` (not `opponent_team_abbr`), `home_away` string (not
  `is_home` bool), `pitches_thrown` (not `pitch_count`), `walks` (not `walks_allowed`).
- Fixed SQL: `venue_k_factors` empty CTE used `WHERE FALSE` without FROM (invalid BigQuery).
- Fixed SQL: `NULL as venue` untyped → `CAST(NULL AS STRING)` for JOIN compatibility.
- Fixed `BQ_LOCATION=US` on service env vars (was defaulting to `us-west2`, MLB data is in US multi-region).
- Deployed MLB Phase 3 as correct image with `mlb.main_mlb_analytics_service:app` entry point
  (vs NBA's `main_analytics_service:app`). Added `APP_MODULE` build arg to analytics Dockerfile.
- **Result:** `mlb_analytics.pitcher_game_summary` = 16 pitchers, March 27. Avg 5.4 Ks.
- **Result:** `mlb_analytics.batter_game_summary` = 140 batters, March 27.

**Phase 4 — Precompute:**
- Fixed schedule query column names: `home_probable_pitcher_id/name` (not `home_pitcher_id/name`),
  `game_time_utc` (not `game_datetime`), `day_night` + CASE (not `is_day_game`), `status_code` (not `status`).
- Fixed `extract_raw_data` abstract method stub (MLB processors use `process_date()` directly).
- Fixed `BQ_LOCATION=US` on service env vars.
- Added `APP_MODULE` build arg to precompute Dockerfile. Deployed MLB Phase 4 correctly.
- Fixed `date` serialization before `insert_rows_json` (Python date objects are not JSON-serializable).
- Fixed legacy `bottom_up_k_expected` field in feature dict (not in BQ schema; `f25_bottom_up_k_expected` is).
- **Result:** `mlb_precompute.pitcher_ml_features` = 30 pitchers for 2026-03-28.

**Phase 5 — Predictions:**
- Worker runs and finds 14 pitchers for March 28.
- All 14 BLOCKED: model expects features `f30_k_avg_vs_line`, `f32_line_level`, `f40_bp_projection`,
  `f44_over_implied_prob` — NONE of these are in the feature store (which only has `f30_velocity_trend`
  through `f34_matchup_edge`, 35 features total).
- **This is a feature store / model schema mismatch that predates this session.**

### NBA Fixes
- Fixed `fta_avg`/`fta_cv` NameError in `aggregator.py` — `ft_anomaly_over_block` was silently disabled.

### Infrastructure Fixes
- Disabled `mlb-live-boxscores` Cloud Scheduler (was sending requests missing `game_pk` to `mlb_game_feed` scraper → 100% failure rate every 5 min)
- Granted `mlb-monitoring-sa` `roles/run.invoker` (was getting PERMISSION_DENIED on 6 monitoring schedulers)
- Created missing `mlb_orchestration` tables: `scraper_output_validation`, `pipeline_event_log`, `failed_processor_queue`
- Added `SLACK_WEBHOOK_URL` to `weekly-retrain` Cloud Run service (was missing → silent retrain)
- Purged 24K+ stuck messages from `mlb-phase2-raw-sub` subscription

---

## Critical Issue for Next Session

### MLB Feature Store / Model Mismatch (HIGH PRIORITY)

**Symptom:** All 14 March 28 predictions are BLOCKED. Default features:
- `f05_season_k_per_9` — IS in feature store but missing (why?)
- `f30_k_avg_vs_line` — NOT in feature store (has `f30_velocity_trend`)
- `f32_line_level` — NOT in feature store (has `f32_put_away_rate`)
- `f40_bp_projection` — NOT in feature store (only has f00-f34)
- `f44_over_implied_prob` — NOT in feature store (only has f00-f34)

**What the model expects:** 36+ features including `f30_k_avg_vs_line`, `f40_bp_projection`, `f44_over_implied_prob`
**What the feature store provides:** 35 features f00-f34 (`FEATURE_VERSION = "v2_35features"`)

**Investigation:**
```bash
# Check what features the model actually expects
gcloud run services describe mlb-prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --format="yaml(spec.template.spec.containers[0].env)"

# Check if there's a feature mapping file
find predictions/mlb -name "*.py" | xargs grep -l "f30_k_avg_vs_line\|feature_names" 2>/dev/null

# What feature version does the model use?
find predictions/mlb -name "*.py" | xargs grep -l "FEATURE_VERSION\|35features\|feature_map" 2>/dev/null
```

**Resolution options:**
1. Update Phase 4 to produce the features the model expects (requires understanding feature definitions)
2. Retrain the model on the current 35-feature set

---

## Pipeline State as of 2026-03-28

| Table | Max Date | Records |
|-------|----------|---------|
| `mlb_raw.mlbapi_pitcher_stats` | 2026-03-27 | 70 |
| `mlb_raw.oddsa_pitcher_props` | 2026-03-28 | 667 |
| `mlb_analytics.pitcher_game_summary` | 2026-03-27 | 16 |
| `mlb_analytics.batter_game_summary` | 2026-03-27 | 140 |
| `mlb_precompute.pitcher_ml_features` | 2026-03-28 | 30 |
| `mlb_predictions.pitcher_predictions` | 2025-09-28 | (no 2026 data yet) |

---

## MLB Service Deployment Notes

MLB analytics/precompute services do NOT auto-deploy. They use a separate build process:

```bash
# Build MLB analytics (Phase 3)
cat > /tmp/mlb-analytics-mlb-build.yaml <<'EOF'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'data_processors/analytics/Dockerfile',
           '--build-arg', 'APP_MODULE=mlb.main_mlb_analytics_service:app',
           '-t', 'us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors:latest', '.']
images: ['us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors:latest']
EOF
gcloud builds submit --region=us-west2 --project=nba-props-platform --config=/tmp/mlb-analytics-mlb-build.yaml .

# Build MLB precompute (Phase 4)
cat > /tmp/mlb-precompute-build.yaml <<'EOF'
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'data_processors/precompute/Dockerfile',
           '--build-arg', 'APP_MODULE=mlb.main_mlb_precompute_service:app',
           '-t', 'us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-precompute-processors:latest', '.']
images: ['us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-precompute-processors:latest']
EOF
gcloud builds submit --region=us-west2 --project=nba-props-platform --config=/tmp/mlb-precompute-build.yaml .

# Deploy after build (get digest first)
DIGEST=$(gcloud artifacts docker images describe \
  "us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors:latest" \
  --format="value(image_summary.digest)")
gcloud run services update mlb-phase3-analytics-processors \
  --region=us-west2 --project=nba-props-platform \
  --image="us-west2-docker.pkg.dev/nba-props-platform/nba-props/mlb-analytics-processors@${DIGEST}" \
  --args=""
```

**IMPORTANT:** After deploying, route traffic to the new revision:
```bash
NEW_REV=$(gcloud run services describe SERVICE --region=us-west2 --project=nba-props-platform \
  --format="value(status.latestCreatedRevisionName)")
gcloud run services update-traffic SERVICE --region=us-west2 --project=nba-props-platform \
  --to-revisions="${NEW_REV}=100"
```

---

## Monday Retrain (March 30, 5 AM ET) — Still Critical

- Scheduler `weekly-retrain-trigger` is ENABLED and READY
- TIGHT cap will fire: train window = Jan 9 – Mar 7
- **Now has SLACK_WEBHOOK_URL** — Slack alerts will fire on completion
- After retrain: `./bin/model-registry.sh sync && ./bin/refresh-model-cache.sh --verify`

---

## NBA Status

- Season record: 103-68 (60.2%) — unchanged, 0 picks March 28 (thin slate, all models degraded)
- Fleet: catboost_0118_0315 likely auto-disables tomorrow (N=13, needs 2 more to cross N=15 gate)
- Monday retrain critical to restore fleet health

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `1735647c` | MLB Phase 2 empty probe + aggregator fta_avg fix |
| `aef959d7` | MLB Phase 2 box score processor registration + YESTERDAY fix |
| `e69055cd` | MLB Phase 3: read mlbapi_pitcher_stats (not mlb_pitcher_stats) |
| `dbe4b446` | MLB Phase 3: empty CTE syntax + APP_MODULE Dockerfile arg |
| `06d9850b` | MLB Phase 3: NULL venue cast to STRING |
| `6791a929` | MLB Phase 4: schedule column name fixes |
| `7b7a3eee` | MLB Phase 4: APP_MODULE build arg for precompute Dockerfile |
| `99bc7a6a` | MLB Phase 4: extract_raw_data abstract method stub |
| `ed7c7b91` | MLB Phase 4: serialize date objects for insert_rows_json |
| `ca93aa40` | MLB Phase 4: remove legacy bottom_up_k_expected field |
