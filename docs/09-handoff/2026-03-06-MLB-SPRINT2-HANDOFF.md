# MLB Sprint 2 Handoff -- Signal System & Best Bets

**Date:** 2026-03-06
**Session Focus:** MLB Pitcher Strikeouts -- Sprint 2 of 4-sprint plan
**MLB Season Start:** 2026-03-27 (21 days)

---

## What Was Done

### Blocking Issues Fixed (4/4)

**1. Zero-tolerance default features**
- Removed silent `FEATURE_DEFAULTS` substitution from `v1_baseline_predictor.py` and `v1_6_rolling_predictor.py`
- `prepare_features()` now returns `(feature_vector, default_feature_count, default_features)` tuple
- Predictions with `default_feature_count > 0` return `recommendation: 'BLOCKED'`
- `ensemble_v1.py` updated to handle BLOCKED state (falls back to single working system, or blocks if both blocked)
- This matches NBA's zero-tolerance pattern that was the single most impactful quality improvement

**2. Training data contamination fixed**
- Replaced `X.fillna(X.median())` with `X.dropna()` in `walk_forward_validation.py`
- Removed ALL `COALESCE(col, default)` from the SQL query -- NULLs propagate to Python where rows are dropped
- This prevents fabricated feature values from contaminating the training signal

**3. Grading void logic + batch DML**
- Complete rewrite of `mlb_prediction_grading_processor.py`
- **Void logic:** Rain-shortened (pitcher IP < 4.0), postponed, suspended games
- **MLB IP notation:** `parse_mlb_innings_pitched()` converts "6.1" to 6.333 (6 1/3), not 6.1
- **Batch writes:** MERGE statement replaces row-by-row UPDATE (prevents DML locks during catch-up)
- **Dual-table write:** Graded records go to `prediction_accuracy` table AND update source `pitcher_strikeouts`
- **Source fallback:** Tries `mlbapi_pitcher_stats` first, falls back to `mlb_pitcher_stats` (BDL)

**4. Statcast backfill** -- Script ready, not executed (needs pybaseball on machine with network access)

### Signal System Built (18 signals)

Created `ml/signals/mlb/` package with 5 files:

| File | Contents |
|------|----------|
| `base_signal.py` | `BaseMLBSignal` + `MLBSignalResult` -- MLB-specific base class |
| `signals.py` | All 18 signal implementations |
| `registry.py` | `MLBSignalRegistry` + `build_mlb_registry()` |
| `best_bets_exporter.py` | Full best bets pipeline |
| `__init__.py` | Package init |

**8 Active Signals:**
- `high_edge` -- Edge >= 1.0 K (both directions)
- `swstr_surge` -- SwStr% last 3 > season + 2% (OVER)
- `velocity_drop_under` -- FB velocity down 1.5+ mph (UNDER)
- `opponent_k_prone` -- Team K-rate >= 24% (OVER)
- `short_rest_under` -- < 4 days rest (UNDER)
- `high_variance_under` -- K std > 3.5 last 10 (UNDER)
- `ballpark_k_boost` -- Park K-factor > 1.05 (OVER)
- `umpire_k_friendly` -- Umpire K-rate >= 22% (OVER)

**6 Shadow Signals:** line_movement_over, weather_cold_under, platoon_advantage, ace_pitcher_over, catcher_framing_over, pitch_count_limit_under

**4 Negative Filters:** bullpen_game_skip (IP avg < 4.0), il_return_skip, pitch_count_cap_skip (blocks OVER when cap <= 85), insufficient_data_skip (< 3 starts)

### Best Bets Pipeline Built

`ml/signals/mlb/best_bets_exporter.py` -- Full port of NBA pattern:

```
Predictions -> Edge floor (1.0 K) -> Negative filters (4) -> Signal rescue ->
Signal count gate (>= 2 real) -> Rank (OVER=edge, UNDER=signal quality) ->
Pick angles -> BQ write (signal_best_bets_picks + filter audit)
```

- Signal rescue: `swstr_surge`, `opponent_k_prone`, `ballpark_k_boost` can bypass edge floor
- UNDER ranking uses weighted signal quality (velocity_drop=2.0, short_rest=1.5, high_variance=1.5, pitch_count_limit=2.0)
- Scoped DELETE (only refreshed pitchers, not all picks for the day)
- Pick angle builder generates human-readable reasoning per pick

### Walk-Forward Simulation Built

`scripts/mlb/training/walk_forward_simulation.py`:

```bash
PYTHONPATH=. python scripts/mlb/training/walk_forward_simulation.py \
  --start-date 2025-04-01 \
  --end-date 2025-09-28 \
  --training-windows 42,56,90,120 \
  --edge-thresholds 0.5,0.75,1.0,1.5,2.0 \
  --retrain-interval 14 \
  --output-dir results/mlb_walkforward_2025/
```

- Tests 4 training windows x 5 edge thresholds = 20 configurations
- Retrains every N days (default 14)
- Outputs: cross-window comparison table, monthly breakdown, CSV per config
- Zero-tolerance: drops NaN rows in training AND test

### BQ Tables Created (9)

All 9 tables from Sprint 1 schemas created successfully via `bq query`:
- `mlb_predictions`: prediction_accuracy, model_registry, model_performance_daily, signal_health_daily, signal_best_bets_picks, best_bets_filter_audit
- `mlb_raw`: mlbapi_pitcher_stats, mlbapi_batter_stats, statcast_pitcher_daily

---

## Files Changed

### Modified (5)
```
predictions/mlb/prediction_systems/v1_baseline_predictor.py     # Zero-tolerance defaults
predictions/mlb/prediction_systems/v1_6_rolling_predictor.py    # Zero-tolerance defaults
predictions/mlb/prediction_systems/ensemble_v1.py               # BLOCKED handling
scripts/mlb/training/walk_forward_validation.py                 # Drop NaN, remove COALESCE
data_processors/grading/mlb/mlb_prediction_grading_processor.py # Void logic + batch DML
```

### Created (6)
```
ml/signals/mlb/__init__.py
ml/signals/mlb/base_signal.py              # MLBSignalResult, BaseMLBSignal
ml/signals/mlb/signals.py                  # 8 active + 6 shadow + 4 filters
ml/signals/mlb/registry.py                 # MLBSignalRegistry, build_mlb_registry()
ml/signals/mlb/best_bets_exporter.py       # MLBBestBetsExporter
scripts/mlb/training/walk_forward_simulation.py  # Multi-window walk-forward
```

---

## Sprint 3 Plan (Next Session)

### Sprint 3a: Backfill & Simulation (2-3 hours)

1. **Backfill Statcast Jul-Sep 2025** -- Run mlb_statcast_daily scraper for each day. Process through MlbStatcastDailyProcessor.
2. **Run walk-forward simulation** -- Execute `walk_forward_simulation.py` on 2025 season data
3. **Analyze results** -- Which training window? Which edge threshold? Monthly drift patterns?

### Sprint 3b: Model Training (2-3 hours)

4. **Train CatBoost V1** -- Port `quick_retrain.py` for MLB, train on 2024-2025 data
5. **Compare XGBoost V1.6 vs CatBoost V1** -- Use simulation results to determine champion
6. **Register models** -- Insert to `model_registry`, upload to GCS

### Sprint 3c: Deployment (1-2 hours)

7. **Deploy prediction worker** -- Update with zero-tolerance code
8. **Resume scheduler jobs** -- `gcloud scheduler jobs resume mlb-*`
9. **E2E pipeline test** -- Run full pipeline on most recent data
10. **Verify monitoring** -- Pipeline canaries, deployment drift cover MLB

---

## Key Decisions for Sprint 3

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Training window | 42/56/90/120d | Wait for simulation results |
| Edge threshold | 0.5-2.0 K | Wait for simulation results |
| Model type | XGBoost vs CatBoost | Train both, compare in simulation |
| Retrain cadence | 14d vs 28d vs decay | Start with 14d, adjust |
| Signal rescue | Keep or disable | Keep -- NBA lesson shows it rescues good OVER picks |

---

## Quick Reference

```bash
# Run Statcast backfill (one day at a time)
PYTHONPATH=. python scrapers/mlb/statcast/mlb_statcast_daily.py --date 2025-07-01

# Run walk-forward simulation
PYTHONPATH=. python scripts/mlb/training/walk_forward_simulation.py \
  --start-date 2025-04-01 --end-date 2025-09-28

# Test signal registry
PYTHONPATH=. python -c "
from ml.signals.mlb.registry import build_mlb_registry
r = build_mlb_registry()
print(f'Active: {len(r.active_signals())}')
print(f'Shadow: {len(r.shadow_signals())}')
print(f'Filters: {len(r.negative_filters())}')
print(f'Tags: {r.tags()}')
"

# Test best bets exporter (dry run)
PYTHONPATH=. python -c "
from ml.signals.mlb.best_bets_exporter import MLBBestBetsExporter
e = MLBBestBetsExporter()
print('Exporter initialized, registry loaded')
print(f'Registry: {len(e.registry.all())} signals')
"

# Master plan
cat docs/08-projects/current/mlb-pitcher-strikeouts/2026-03-MLB-MASTER-PLAN.md
```
