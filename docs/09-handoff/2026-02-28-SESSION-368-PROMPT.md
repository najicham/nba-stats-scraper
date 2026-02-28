# Session 368 Prompt — Register Winning Model + Deploy

## Context

Session 367 ran 55 grid search experiments across 4 eval windows. The clear winner is:

**v12 + vegas=0.15: 73.0% HR (N=189), all governance gates pass, UNDER 74.8%, OVER 70.3%**

This was trained on Dec 1-31 and evaluated on Jan 1 - Feb 27 (full eval window). It uses the V12 feature set (WITH vegas features) but with vegas category weight dampened to 0.15x.

Session 367 also deployed filter relaxations (star_under injury-aware, under_edge_7plus V9-only) and fixed the grid_search_weights.py `--force` bug.

Full results: `docs/09-handoff/2026-02-28-SESSION-367-HANDOFF.md`
Grid search CSVs: `results/window_A/`, `results/window_B/`, `results/window_C/`, `results/window_D/`

---

## Phase 1: Register v12+vegas=0.15 Winner (~30 min)

### 1A. Train and Register (with governance gates)

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name v12_vw015 \
    --feature-set v12 \
    --category-weight vegas=0.15 \
    --train-start 2025-12-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-02-27
```

**Do NOT use `--skip-register`.** This will train, run governance gates, and register the model in GCS + manifest.

Expected: All 6 gates should pass (they passed in the grid search). If any fail, investigate before proceeding.

### 1B. Validate Registration

```bash
./bin/model-registry.sh validate
./bin/model-registry.sh sync
python bin/validation/validate_model_registry.py
```

### 1C. Add Model Family to cross_model_subsets.py

The v12+vegas=0.15 model will have a system_id like `catboost_v12_train1201_1231_TIMESTAMP.cbm`. It should be classified under the existing `v12_mae` family in `shared/config/cross_model_subsets.py` (the catch-all for `catboost_v12` prefix). Verify this with:

```python
from shared.config.cross_model_subsets import classify_system_id
print(classify_system_id('catboost_v12_vw015_train1201_1231_TIMESTAMP'))
```

If it returns `None` or wrong family, add a new family entry BEFORE `v12_mae` (which is the catch-all).

### 1D. Update model_direction_affinity.py

If a new family key is needed, add the affinity group mapping in `ml/signals/model_direction_affinity.py:get_affinity_group()`. It should map to `v12_vegas` since it uses the full V12 feature set with vegas.

---

## Phase 2: Train with Longer Window (~30 min)

Session 367 found that 62-day training (Dec 1 - Jan 31) significantly boosts Feb performance. Train a second model:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name v12_vw015_62d \
    --feature-set v12 \
    --category-weight vegas=0.15 \
    --train-start 2025-12-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-27
```

This has a shorter eval window (27 days) so it might fail the N>=50 gate. If it does, check the HR and decide if shadow deployment is warranted anyway based on Session 367's Window D results (72.7% HR on v12+vegas=0.25 with this window).

---

## Phase 3: Deploy to Shadow Fleet (~15 min)

Deploy the prediction-worker if the new model family requires code changes. Otherwise, just add to the model registry.

```bash
./bin/model-registry.sh sync
./bin/deploy-service.sh prediction-worker  # Only if worker changes needed
```

The worker already supports CatBoost with standard V12 features. The `--category-weight` is a training-time parameter (changes feature importance in the model file), so the worker doesn't need special handling.

---

## Phase 4: Monitor Session 367 Filter Changes (~15 min)

Check if the filter relaxations from Session 367 are having the expected effect:

```bash
# Check today's best bets — are UNDER picks passing through?
bq query --use_legacy_sql=false "
SELECT recommendation, COUNT(*) as n,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 1) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE()
  AND algorithm_version = 'v367_star_under_injury_aware_under7plus_v9_only'
GROUP BY 1
"

# Check filter summary from today's coordinator logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-coordinator" AND textPayload:"filter"' --limit=20 --format='value(textPayload)' --project=nba-props-platform
```

---

## Phase 5: Additional Grid Searches (Optional, background)

If time permits, run these additional experiments:

### 5A. v12+vegas=0.15 with 62-day training, full eval
```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --base-args "--feature-set v12" \
    --grid "category-weight=vegas=0.10,vegas=0.15,vegas=0.20" \
    --train-start 2025-12-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-27 \
    --csv results/window_D/vegas_015_zoom.csv
```

### 5B. Recency weighting on v12+vegas=0.15
**Caveat from Session 359**: Recency weighting hurts well-calibrated models. v12+vegas=0.25 went 75%→59% with recency. But 0.15 is a different weight — worth testing.

```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --base-args "--feature-set v12 --category-weight vegas=0.15" \
    --grid "recency-weight=7,14,21,30" \
    --train-start 2025-12-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-02-27 \
    --csv results/window_A/recency_vw015.csv
```

---

## Key Reference Data

### Session 367 Multi-Window Results Summary

**Best configs by window:**
- **Full (Jan+Feb)**: v12+vegas=0.15 — 73.0% HR (N=189) **← REGISTER THIS**
- **Jan only**: v12+vegas=0.20 — 75.8% HR (N=120)
- **Feb only**: v12_noveg — 66.3% HR (N=101) (most decay-resistant)
- **Feb with 62d train**: v12+vegas=0.25 — 72.7% HR (N=44)

**Decay patterns (Jan→Feb):**
- v12_noveg: -4.6pp (most stable)
- v12+vegas=0.15: -12.1pp
- v15: -12.9pp (worst — do NOT deploy V15)
- Tier weighting: marginal benefit, underperforms baseline

**Dead ends confirmed:**
- V13/V15/V16 feature sets all underperform V12_noveg
- Tier weighting underperforms baseline on full eval
- V15 overfits to Jan patterns (75.9%→63.0%)

### Session 367 Commits
```
2d91df4b docs: update Session 367 handoff with multi-window grid search results
d072cf07 feat: multi-window grid search results + tier_top3 template
70b95220 docs: Session 367 handoff + grid search results
229d6773 feat: relax star_under + under_edge_7plus filters, fix grid search --force
```

### Important Notes
- prediction-coordinator trigger only watches `predictions/coordinator/**`, NOT `ml/signals/`. Must manually deploy after signal changes.
- `--no-vegas` flag makes `--category-weight vegas=X` irrelevant — use `--feature-set v12` (not v12_noveg) when testing vegas weights.
- Grid search needs `--force` flag (already added to templates).
