# Session 360 Handoff — V17 Feature Set + Infrastructure

**Date:** 2026-02-27
**Previous:** Session 359 — Vegas weight experiment matrix, 2 shadow models deployed

## What Session 360 Did

### 1. Implemented V17 Feature Set (6 files)

Added 3 "opportunity risk" features to the full pipeline:
- `blowout_minutes_risk` (57): Fraction of team's L10 games with 15+ margin
- `minutes_volatility_last_10` (58): Stdev of player minutes over L10
- `opponent_pace_mismatch` (59): team_pace - opponent_pace

Feature store bumped from `v2_57features` → `v2_60features`. BQ ALTER TABLE DDL executed to add columns.

### 2. Trained and Evaluated V17 Models

| Config | Edge 3+ HR | N | OVER | UNDER | Verdict |
|--------|-----------|---|------|-------|---------|
| V17 noveg | 56.7% | 30 | 72.7% | 47.4% | Dead end |
| V17 vegas=0.25 | 58.1% | 31 | 66.7% | 50.0% | Dead end |

All 3 V17 features landed **below 1% importance**. The model finds no signal in opportunity risk.

### 3. Documented V17 as Dead End

Added to CLAUDE.md dead ends list and project docs at `docs/08-projects/current/v17-opportunity-risk-experiment/`.

---

## What Changed

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | V17/V17_NOVEG contracts (59/55 features), defaults, source maps |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | V17 batch extraction + accessor |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | V17 feature computation (57-59) |
| `ml/experiments/quick_retrain.py` | `--feature-set v17/v17_noveg`, `--v17-features` flag |
| `predictions/worker/prediction_systems/catboost_monthly.py` | `v17_noveg` feature vector (55f) |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Migration DDL for features 55-59 |
| BQ table `ml_feature_store_v2` | Columns added via ALTER TABLE |
| `CLAUDE.md` | V17 added to dead ends |

---

## What NOT to Do

- **Don't retrain V17** — all 3 features < 1% importance, confirmed dead end
- **Don't revert the code** — the infrastructure (contract, extractor, processor, worker) is reusable for future features
- **Don't add more "context" features** (pace mismatch, blowout risk) — CatBoost already captures these via tree splits on the underlying features

---

## Open Questions for Future Sessions

### 1. Front-Load Detection (Not Built Yet)

We track `rolling_hr_7d` / `rolling_hr_14d` / `rolling_hr_30d` in `model_performance_daily`, and `--walkforward` gives per-week breakdown during training. But there's **no automated alert** for front-loaded models (7d HR << 14d HR declining over time).

**Suggestion:** Add to `decay-detection` CF: flag if `rolling_hr_7d < rolling_hr_14d - 5%` for 3+ consecutive days. Small change to `orchestration/cloud_functions/decay_detection/main.py`.

### 2. Feature Discovery: What Might Actually Work

V17 tried team-level and variance features — the model ignores them. What might work:

- **Player-level matchup features** — how does THIS player perform against THIS defense position archetype? (e.g., point guards vs drop coverage teams). Requires play-by-play data aggregation.
- **Line movement momentum** — not just `prop_line_delta` (single game) but trend of line moves across last 3-5 games. If books keep raising a player's line, that's a signal.
- **Teammate scoring distribution** — when teammate X is out, does THIS player absorb their shots? Currently `star_teammates_out` is a count, not a redistribution signal.
- **Referee tendencies** — some refs call more fouls → more FTs → more points for high-FT-rate players. Data available from NBA.com.

### 3. Model Architecture Experiments Still Worth Trying

- **Ensemble of V12 vegas=0.25 + V16 noveg rec14** — the two best models from Session 359. Simple average or stacked.
- **Longer training window for vegas=0.25** — currently Dec 1 start. Try Nov 1 with vegas=0.25 weight (92-day window was bad for noveg, but dampened vegas might handle it).
- **Per-direction models** — train separate OVER and UNDER models. UNDER has been the persistent weakness. A model trained only on UNDER outcomes with different hyperparameters might find different signal.

### 4. Shadow Fleet Status (Check These)

Models deployed and accumulating data — check `model_performance_daily` for updated HRs:
- `v9_low_vegas_train0106_0205`: Was best at 51.9% 7d (n=52)
- `v16_noveg_train1201_0215`: First V16 predictions expected Feb 28
- `catboost_v12_train1201_0215`: V12 vegas=0.25 (Session 359)
- `catboost_v16_noveg_rec14_train1201_0215`: V16 noveg + recency (Session 359)
- 2 LightGBM models: Accumulating data

---

## Commits

```
a559702f feat: implement V17 feature set — opportunity risk features
d4202814 docs: add V17 opportunity risk features to dead ends list
```
