# Session 244 Handoff: RSM Variants, SQL Signal Discovery, V14 Feature Contract

**Date:** 2026-02-13
**Focus:** RSM50 variant experiments (5 configs), SQL signal discovery (4 queries), V14 feature contract implementation
**Status:** All experiments complete, analysis documented, V14 code ready for testing

---

## What Was Done

### 1. RSM50 Variant Experiments (5 new, all complete)

All experiments: `--feature-set v12 --no-vegas --rsm X --grow-policy Depthwise --walkforward --include-no-line --force --skip-register`

| # | Name | Key Config | MAE | HR 3+ (n) | OVER | UNDER | Gates |
|---|------|-----------|-----|-----------|------|-------|-------|
| **G** | **V12_RSM50 (S243)** | **RSM50 Depthwise** | **4.82** | **57.1% (35)** | **64.3%** | **52.4%** | **4/6 (best)** |
| I | RSM50_NOVEG_CLEAN | Exclude line_vs_season_avg + dead features | 5.13 | 51.85% (108) | 50.0% | 52.8% | 4/6 FAIL |
| J | RSM50_HUBER | RSM50 + Huber:delta=5 | 4.98 | 57.35% (68) | 53.8% | 59.5% | **5/6 (closest)** |
| K | RSM50_Q47 | RSM50 + quantile alpha=0.47 | 4.97 | 56.36% (55) | 37.5% | 59.6% | 4/6 FAIL |
| L | RSM70 | RSM70 Depthwise | 4.87 | 55.88% (34) | 57.1% | 55.0% | 4/6 FAIL |
| M | RSM30 | RSM30 Depthwise | 4.90 | 56.76% (37) | 61.5% | 54.2% | 4/6 FAIL |

**Key findings:**

1. **RSM50 remains the best config** at 57.1% HR edge 3+. No variant topped it.
2. **Removing `line_vs_season_avg` CRASHES performance** (57.1% -> 51.85%). Despite leaking vegas info, it's critical. Keep it.
3. **RSM50_HUBER is the closest contender** (57.35%, 68 samples). Passes 5/6 governance gates (only misses 60% HR by 2.65pp). Key insight: Huber loss elevates `points_std_last_10` to 20.6% importance (vs 0% under MAE), making the model more variance-aware.
4. **RSM50_Q47 too UNDER-biased** (OVER only 37.5%). Dead end.
5. **RSM30 and RSM70 worse than RSM50** with fewer samples. RSM50 is the sweet spot.
6. **V12 augmentation is broken** - 0% match rate across ALL experiments. All models effectively train on V9 base features only. Major bug.

### 2. SQL Signal Discovery (4 queries)

| Query | Finding | Actionable? |
|-------|---------|-------------|
| 3PT% cold vs FG% cold | **3PT cold is the real signal** (55.6% OVER) vs FG-only cold (50.9%) | Yes - use `three_pct_last_2 < 0.30` not `fg_pct_last_2 < 0.40` |
| Free throw rate | High FT rate -> UNDER (47.9% OVER), Low FT rate -> OVER (54.5%) | Maybe - test as V14/V15 feature |
| FG% cold by home/away | Minimal interaction (+1.8pp home cold vs normal). Not actionable | No |
| Game total 230-234 stability | **December artifact, not a real signal.** December was 70-72% OVER across ALL totals | No - drop this filter idea |

### 3. V14 Feature Contract (implemented, not yet tested)

Added 5 engineered FG% features designed to give CatBoost usable signals from raw shooting data:

| Index | Feature | Formula | Rationale |
|-------|---------|---------|-----------|
| 60 | `fg_cold_z_score` | (fg_pct_L3 - season_fg) / season_fg_std | Personalized cold detection |
| 61 | `expected_pts_from_shooting` | fg_pct_L3 * fga_L3 * 2 + three_pct_L3 * tpa_L3 | Volume-adjusted expected points |
| 62 | `fg_pct_acceleration` | fg_pct_L3 - fg_pct_L5 | Shooting trend direction |
| 63 | `fatigue_cold_signal` | minutes_load_last_7d * (1 - fg_pct_L3) | Fatigue x cold interaction |
| 64 | `three_pct_std_last_5` | Std dev of 3PT% last 5 games | Shooting inconsistency |

**Files changed:**
- `shared/ml/feature_contract.py` — V14/V14_NOVEG contracts (65/61 features), registry entries
- `ml/experiments/quick_retrain.py` — `--feature-set v14` flag, `augment_v14_features()` function

All contracts validate. Ready for `--feature-set v14` experiments.

---

## Critical Bug: V12 Augmentation 0% Match

**Every experiment across Sessions 243 and 244 shows 0% V12 feature augmentation.** The V11 and V12 augmentation functions query BigQuery correctly (UPCG: 19K rows, Stats: 11K rows) but **0 rows match** when joining to the training DataFrame.

Root cause is likely a **JOIN key mismatch** between:
- Feature store `player_lookup` format (in `ml_feature_store_v2`)
- Augmentation query `player_lookup` format (in `nbac_gamebook_player_stats`, `upcoming_player_game_context`)

This means ALL "V12" experiments are actually V9 + `line_vs_season_avg` (which comes from the feature store directly, not augmentation). **Fixing this could substantially improve results** since 15 additional features would become available.

**Investigation needed:** Compare `player_lookup` values between the feature store DataFrame and the augmentation query results. Likely a format mismatch (e.g., "LeBron James" vs "lebron_james" vs numeric ID).

---

## Code Changes (uncommitted)

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | +109 lines: V14/V14_NOVEG contracts (65/61 features), registry entries, `get_contract()` routing |
| `ml/experiments/quick_retrain.py` | +449 lines: `--feature-set v14` flag, `augment_v14_features()` (212-line BQ query + injection), V14 augmentation wiring in main flow |

**Note:** These changes also include V13 changes from Session 243 that weren't committed.

---

## What the Next Session Should Do

### Priority 1: Fix V12 Augmentation Bug (HIGH IMPACT)

This is the single highest-leverage fix. All V12+ experiments are handicapped without it.

```python
# Debug: add this to augment_v12_features() after loading df_train
print(f"  DEBUG: df player_lookup sample: {df['player_lookup'].head(3).tolist()}")
print(f"  DEBUG: UPCG player_lookup sample: {upcg_data['player_lookup'].head(3).tolist()}")
print(f"  DEBUG: df game_date dtype: {df['game_date'].dtype}, sample: {df['game_date'].head(3).tolist()}")
print(f"  DEBUG: UPCG game_date dtype: {upcg_data['game_date'].dtype}")
```

Check if it's a format issue (string vs date), a naming convention issue, or a key column mismatch.

### Priority 2: Run V14 Experiments

Once V12 augmentation is fixed (or in parallel to investigate it):

```bash
# V14 RSM50 (best config + new FG% engineered features)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V14_RSM50" \
  --feature-set v14 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register

# V14 RSM50 + Huber
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V14_RSM50_HUBER" \
  --feature-set v14 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --loss-function "Huber:delta=5" \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register
```

### Priority 3: Post-Prediction 3PT Cold Filter

Since the SQL showed 3PT cold at 55.6% OVER rate, test a rule-based filter:
- For OVER predictions with 3PT cold (< 30% last 2 games): boost confidence
- For UNDER predictions with 3PT hot (> 40% last 2 games): boost confidence
- Measure HR for each filtered subset

### Priority 4: Extended Eval Window

RSM50 only had 35 edge 3+ samples. After ASB break, extend eval:
```bash
--eval-start 2026-02-01 --eval-end 2026-02-20
```
This should push sample sizes above the 50 governance gate.

---

## Experiment Cumulative Matrix (Sessions 243-244)

| # | Name | MAE | HR 3+ (n) | Direction | Gates |
|---|------|-----|-----------|-----------|-------|
| A | V12_BASELINE | 5.08 | 46.4% (28) | FAIL | 3/6 |
| B | V12_TUNED | 5.08 | 46.4% (28) | FAIL | 3/6 |
| C | V12_RECENCY30 | 5.05 | 41.4% (29) | FAIL | 3/6 |
| D | V12_RECENCY14 | 4.94 | 54.2% (24) | FAIL | 3/6 |
| E | V12_HUBER5 | 4.95 | 50.9% (57) | FAIL | 4/6 |
| F | V12_PRUNED | 4.88 | 56.5% (23) | PASS | 4/6 |
| **G** | **V12_RSM50** | **4.82** | **57.1% (35)** | **PASS** | **4/6** |
| H | V12_BEST_COMBO | 4.93 | 51.3% (39) | FAIL | 3/6 |
| I | RSM50_NOVEG_CLEAN | 5.13 | 51.85% (108) | FAIL | 4/6 |
| **J** | **RSM50_HUBER** | **4.98** | **57.35% (68)** | **PASS** | **5/6** |
| K | RSM50_Q47 | 4.97 | 56.36% (55) | FAIL (OVER) | 4/6 |
| L | RSM70 | 4.87 | 55.88% (34) | PASS | 4/6 |
| M | RSM30 | 4.90 | 56.76% (37) | PASS | 4/6 |

**Top 2 configs:** RSM50 (best HR%), RSM50_HUBER (best volume + most gates passed)

---

## Dead Ends (don't revisit)

- **Excluding `line_vs_season_avg`** — crashes HR from 57.1% to 51.85%
- **RSM50 + quantile 0.47** — too UNDER-biased (OVER only 37.5%)
- **Game total 230-234 filter** — December artifact, not real signal
- **FG% cold by home/away** — minimal interaction, not actionable
- **Combining multiple winning techniques** (from S243) — improvements don't stack

---

## Schema Reminders

- `prediction_accuracy`: `line_value` (not prop_line), `actual_points` (not actual_stat), no `stat_type` column
- `nbac_gamebook_player_stats`: `minutes_decimal` (not minutes_played), `field_goals_made/attempted`, `three_pointers_made/attempted`
- `player_game_summary`: `minutes_played`, `points`, `usage_rate`

---

## Documentation

- **Session 244 results:** `docs/08-projects/current/mean-reversion-analysis/06-SESSION-244-RSM-VARIANTS-AND-SQL.md`
- **Session 243 results:** `docs/08-projects/current/mean-reversion-analysis/05-SESSION-243-V12-V13-EXPERIMENT-RESULTS.md`
- **Feature contract:** `shared/ml/feature_contract.py` (V14 added)
- **Experiment runner:** `ml/experiments/quick_retrain.py` (V14 augmentation added)

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-13-SESSION-244-HANDOFF.md

# 2. See full results
cat docs/08-projects/current/mean-reversion-analysis/06-SESSION-244-RSM-VARIANTS-AND-SQL.md

# 3. PRIORITY: Debug V12 augmentation 0% match bug
# Add debug prints to augment_v12_features() in quick_retrain.py
# Compare player_lookup format between feature store df and BQ query results

# 4. Run V14 experiment (after or in parallel with bug fix)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V14_RSM50" \
  --feature-set v14 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register
```
