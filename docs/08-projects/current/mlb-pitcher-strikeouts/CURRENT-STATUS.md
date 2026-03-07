# MLB Pitcher Strikeouts - Current Status

**Last Updated**: 2026-03-07 (Sprint 4 — fully deployed)
**Project Phase**: Sprint 4: Deploy + Launch Prep (98% complete — retrain before opening day)
**Season Start**: 2026-03-27 (20 days)

---

## What's Done (Sprints 1-3)

### Sprint 1: Data Foundation (Complete)
- MLB Stats API box score scraper (replaces BDL)
- Statcast daily pitcher scraper (pybaseball)
- Reddit discussion scraper
- 3 new data processors (statcast, pitcher stats, batter stats)
- BQ schemas for all new tables

### Sprint 2: Signal & Best Bets Architecture (Complete)
- 8 active signals + 6 shadow + 4 negative filters
- Best bets exporter with UNDER signal-quality ranking
- Grading processor with void logic (rain-shortened, postponed, IP conversion)
- Multi-system prediction support (CatBoost V1, V1.6 Rolling, Ensemble V1)

### Sprint 3: Walk-Forward + Model Training (Complete)
- Full 2025 season walk-forward: 8 configs, 6,112 samples, 31 features
- **CatBoost 120d wins**: 54.2% HR at edge 1.0+ (N=1,183)
- CatBoost V1 model trained, all 5 governance gates passed
- XGBoost V1 shadow model registered
- Quick retrain script with governance gates
- Feature contract fix: pitcher_loader now provides all 31 CatBoost features

### Sprint 4: Deploy + Launch (In Progress)
- Dockerfile fixed (libgomp1 for CatBoost)
- Main scraper registry synced with MLB-specific registry
- Pitcher loader feature gap fixed (season_swstr_pct, season_csw_pct, k_avg_vs_line, over_implied_prob, velocity_change)
- urllib3==2.6.3 pinned (fixes circular import in Cloud Run)
- CatBoost V1 enabled in BQ model registry (enabled=TRUE, is_production=TRUE)
- MLB worker deployed and serving: catboost_v1, v1_6_rolling, ensemble_v1 all loading
- cloudbuild-mlb-worker.yaml Dockerfile path fixed
- Scheduler script updated: mlb_statcast_daily (3 AM), mlb_reddit (11 AM), overnight uses MLB API

---

## What's Left (Sprint 4: Deploy + Launch)

### Critical Path (Must do before Mar 27)

| Task | Status | Effort | Notes |
|------|--------|--------|-------|
| Enable CatBoost V1 in BQ registry | DONE | - | enabled=TRUE, is_production=TRUE |
| Deploy MLB worker with CatBoost | DONE | - | All 3 systems loading (catboost_v1, v1_6_rolling, ensemble_v1) |
| Cloud Scheduler script updated | DONE | - | statcast_daily, reddit, mlbapi box scores |
| E2E local tests pass | DONE | - | Model loads (31 features), signals (18), exporter OK |
| Create scheduler jobs in GCP | DONE | - | 22 total MLB jobs, all paused. Resume Mar 24-25. |
| Verify scraper credentials | DONE | - | ODDS_API_KEY configured via secret |
| Batter analytics BDL→mlbapi migration | DONE | - | UNION of bdl_batter_stats + mlbapi_batter_stats |
| Test Slack notifications | DONE | - | notify_info sends successfully |
| Retrain CatBoost on freshest data | TODO | 30 min | Do Mar 24-25. No new data beyond Sep 2025 (off-season). |

### Nice to Have (First 2 weeks of season)

| Task | Effort | Notes |
|------|--------|-------|
| Statcast raw backfill (Jul-Sep 2025) | 15 min | `scripts/mlb/backfill_statcast.py` ready |
| Odds API 2023 historical backfill | $290 | 29K API credits, deferred |
| Monitor July drift pattern | Ongoing | Walk-forward showed July dip |
| Signal promotion after 30 days | Ongoing | 6 shadow signals accumulating |
| BDL injury source replacement | 1 hr | `bdl_injuries` has fail-safe fallback. Need mlbapi source eventually. |

---

## Key Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Training window | 120 days | Monotonic improvement 42->120d. ~24 starts per pitcher |
| Edge threshold | 1.0 K | Balance of sample size (~1200) and HR improvement |
| Production model | CatBoost V1 | 54.2% walk-forward HR, 62.2% eval HR at edge 1+ |
| Shadow model | XGBoost V1 | Better UNDER (51.9%) but failed 60% edge1+ gate |
| UNDER gate | Relaxed to 48% | MLB UNDER structurally harder. Signal system compensates |
| Retrain cadence | Every 14 days | Walk-forward validated |
| Model type | Binary classifier | Over/under probability, not strikeout count regression |
| UNDER ranking | Signal-quality based | Same as NBA — UNDER edge is flat |

---

## Models

| Model | Type | HR (edge 1+) | Status | GCS Path |
|-------|------|-------------|--------|----------|
| CatBoost V1 | Classifier | 62.2% (N=164) | Production (pending enable) | `gs://nba-props-platform-ml-models/mlb/catboost_mlb_v1_31f_train20250430_20250828_*.cbm` |
| XGBoost V1 | Classifier | 57.6% (N=288) | Shadow | `gs://nba-props-platform-ml-models/mlb/xgboost_mlb_v1_31f_train20250430_20250828_*.json` |
| V1.6 Rolling | Regressor | Legacy | Active (ensemble) | GCS legacy path |
| Ensemble V1 | Weighted avg | Legacy | Active | V1 30% + V1.6 50% |

---

## Signal System

**8 Active**: high_edge, swstr_surge, velocity_drop_under, opponent_k_prone, short_rest_under, high_variance_under, ballpark_k_boost, umpire_k_friendly

**6 Shadow**: line_movement_over, weather_cold_under, platoon_advantage, ace_pitcher_over, catcher_framing_over, pitch_count_limit_under

**4 Negative Filters**: bullpen_game_skip, il_return_skip, pitch_count_cap_skip, insufficient_data_skip

---

## Key Files

| File | Purpose |
|------|---------|
| `predictions/mlb/prediction_systems/catboost_v1_predictor.py` | CatBoost V1 predictor (31 features) |
| `predictions/mlb/worker.py` | Multi-system prediction worker |
| `predictions/mlb/pitcher_loader.py` | Shared feature loader (all 31 features) |
| `ml/training/mlb/quick_retrain_mlb.py` | Governance-gated retrain |
| `ml/signals/mlb/registry.py` | Signal registry (8+6+4) |
| `ml/signals/mlb/best_bets_exporter.py` | Best bets pipeline |
| `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | Grading with void logic |
| `scripts/mlb/training/walk_forward_simulation.py` | Walk-forward sim |
| `scripts/mlb/backfill_statcast.py` | Statcast backfill script |
