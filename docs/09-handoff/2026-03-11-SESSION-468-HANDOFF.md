# Session 468 Handoff — MLB 2026 Pre-Season Prep

**Date:** 2026-03-11
**Focus:** MLB 2026 Opening Day preparation — Phase 1 code, BQ verification, multi-model fleet

## What Was Done

### Phase 1 Code Changes (Committed)

1. **Dockerfile fix (CRITICAL)**: Added `COPY ml/ ./ml/` to `predictions/mlb/Dockerfile`. Without this, the `/best-bets` endpoint would crash with `ModuleNotFoundError: No module named 'ml'` because the worker imports from `ml.signals.mlb.best_bets_exporter`.

2. **Multi-model fleet**: Created LightGBM V1 and XGBoost V1 regressor predictors and training scripts. Same 36-feature contract as CatBoost V2. Registered in worker (opt-in via `MLB_ACTIVE_SYSTEMS`). Added `lightgbm==4.1.0` to requirements.

3. **Umpire tiebreaker**: Instead of counting umpire_k_friendly toward RSC (which inflates it and hurts by -1.7pp/-33u), the signal now adds a +0.01 bonus during ranking — breaking ties between picks with similar edge. Implemented in both exporter and replay.

4. **Replay config sync**: `MAX_PICKS_PER_DAY` was 3 in replay but 5 in production. Fixed.

5. **Training SQL cleanup**: Removed 5 dead features (f17, f18, f24, f67, f69) from SQL query. Fixed feature contract string from `/40` to `/{len(FEATURE_COLS)}`.

6. **Blacklist review script**: `bin/mlb/review_blacklist.py` — queries prediction_accuracy to recommend blacklist additions (HR < 40%, N >= 15) and removals (HR >= 55%, N >= 10). Run after 4-6 weeks of 2026 data.

### BQ Verification (Completed)

All 4 training tables are healthy with data through Sep 2025:
- `pitcher_game_summary`: 5,081 rows, latest 2025-09-28
- `bp_pitcher_props`: 7,355 rows, latest 2025-09-28
- `pitcher_rolling_statcast`: 17,616 rows, latest 2025-10-01
- `fangraphs_pitcher_season_stats`: 3,408 rows, 2025 season

All 3 output tables exist with correct schemas:
- `signal_best_bets_picks`, `best_bets_filter_audit`, `pitcher_strikeouts`

Supplemental tables (umpire_stats, weather, catcher_framing) are empty — expected, fill after season resume.

Training SQL validated successfully via BQ `--dry_run`.

### Doc Updates

- `03-DEPLOY-CHECKLIST.md`: Updated with Phase 1 completion, BQ verification results, multi-model deploy instructions, fixed env vars
- `06-SEASON-PLAN-2026.md`: Updated system state table, added Phase 1 completions, fixed env vars (wrong system name, missing vars, wrong MAX_PICKS), fixed algorithm version
- `05-DEAD-ENDS.md`: Added notes about multi-model re-attempt (different strategy — independent evaluation, not ensembling)

## Key Files Changed

| File | Change |
|------|--------|
| `predictions/mlb/Dockerfile` | Added `COPY ml/` |
| `ml/signals/mlb/best_bets_exporter.py` | Umpire tiebreaker in ranking |
| `predictions/mlb/worker.py` | LightGBM + XGBoost registration |
| `predictions/mlb/requirements.txt` | Added `lightgbm==4.1.0` |
| `scripts/mlb/training/season_replay.py` | MAX_PICKS 3→5, umpire tiebreaker |
| `scripts/mlb/training/train_regressor_v2.py` | SQL cleanup, feature contract fix |
| `predictions/mlb/prediction_systems/lightgbm_v1_regressor_predictor.py` | NEW |
| `predictions/mlb/prediction_systems/xgboost_v1_regressor_predictor.py` | NEW |
| `scripts/mlb/training/train_lightgbm_v1.py` | NEW |
| `scripts/mlb/training/train_xgboost_v1.py` | NEW |
| `bin/mlb/review_blacklist.py` | NEW |

## What's Next

### Phase 2 — Mar 18-24 (Pre-Opening Day)

| When | Task | Details |
|------|------|---------|
| Mar 18-20 | Retrain CatBoost V2 | `--training-end 2026-03-20 --window 120` |
| Mar 18-20 | (Optional) Train LightGBM/XGBoost | Same window, for fleet diversity |
| Mar 20-23 | Upload models to GCS | `gsutil cp models/mlb/*.cbm gs://...` |
| Mar 20-23 | Deploy MLB worker | `gcloud builds submit --config cloudbuild-mlb-worker.yaml` |
| Mar 20-23 | Route traffic | `gcloud run services update-traffic --to-latest` |
| Mar 20-23 | Set env vars | See deploy checklist Step 5 |
| Mar 24 | Resume schedulers | `./bin/mlb-season-resume.sh` |
| Mar 25-26 | Verify scrapers fire | Check BQ mlb_raw tables for new data |
| Mar 27 | Opening day | Verify predictions + best bets in BQ |

### Phase 3 — Apr-May (Paper Trading)

| Task | When | Tool |
|------|------|------|
| Blacklist refresh | May (4-6 weeks of data) | `bin/mlb/review_blacklist.py` |
| Shadow signal promotion | May (HR >= 60%, N >= 30) | Review `best_bets_filter_audit` |
| UNDER enablement | May 1 (if OVER HR >= 58%) | Set `MLB_UNDER_ENABLED=true` |
| Multi-model evaluation | After 3 weeks | Compare live HR across models |

## Warnings

- **MLB worker is NOT auto-deployed** — must manually `gcloud builds submit --config cloudbuild-mlb-worker.yaml`
- **Cloud Run traffic gotcha** — new revisions may NOT auto-route. Always verify and use `update-traffic --to-latest`
- **NEVER use `--set-env-vars`** — it wipes ALL existing vars. Always `--update-env-vars`
- **2026 schedule is empty** — fills after schedule scraper fires post-resume (Mar 24)
- **Feature count is 36**, not 40 — docs/comments that say 40 are stale (5 dead features removed Session 444)
