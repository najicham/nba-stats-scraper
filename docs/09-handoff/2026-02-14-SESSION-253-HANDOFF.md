# Session 253 Handoff — Comprehensive Model Validation Complete, Rest-of-Season Plan Ready

**Date:** 2026-02-14
**Status:** 52 experiments complete. Best configs identified. Subset redesign planned. Next: ASB retrain + Best Bets implementation.
**Session:** 253

---

## What Was Done This Session

### 1. Code Change: Added Tier/Population Filters to quick_retrain.py

Added 3 new CLI flags for training data filtering:
- `--min-ppg FLOAT` — only train on players with `points_avg_season >= N`
- `--max-ppg FLOAT` — only train on players with `points_avg_season < N`
- `--lines-only-train` — only train on players with prop lines for that game

**File modified:** `ml/experiments/quick_retrain.py`
- Updated `parse_args()` with 3 new arguments
- Updated `load_train_data()` to accept and pass `min_ppg`, `max_ppg`, `lines_only_train`
- Uses `mf.features[OFFSET(2)]` for PPG filtering (index 2 = points_avg_season)
- Uses JOIN with `odds_api_player_points_props` for lines-only filtering
- Updated `main()` to display filters and pass to loader
- Updated dry-run output

### 2. Ran 52 Experiments (5 configs x 8 eval windows x multiple dimensions)

#### Step 1: Multi-Window Baseline (20 experiments, 5 configs x 4 windows)

| Config | Description | W1 (Dec) | W2 (Jan early) | W3 (Jan late) | W4 (Feb) | AVG |
|--------|-------------|----------|---------------|---------------|----------|-----|
| **E: V9 MAE 33f** | Default V9 | **71.3%** (80) | **81.6%** (103) | **93.5%** (46) | 66.7% (6) | **78.3%** |
| **C: V12 MAE RSM50** | 50f, no-vegas, rsm=0.5, depth | 67.3% (104) | 80.3% (122) | **85.9%** (64) | 57.9% (38) | **72.9%** |
| **A: V12 MAE default** | 50f, no-vegas | 61.6% (86) | **88.4%** (103) | 84.1% (63) | 57.1% (21) | **72.8%** |
| D: V12 Q43 | Quantile 0.43 | 59.5% (168) | 74.2% (124) | 62.2% (135) | 58.2% (79) | 63.5% |
| B: V12 Huber RSM50 | Huber:delta=5 | 55.2% (201) | 72.9% (144) | 67.2% (137) | 50.8% (67) | 61.5% |

**Winners:** E (V9 MAE, 78.3% avg) and C (V12 MAE RSM50, 72.9% avg).

#### Step 2: Player Tier Experiments (8 experiments)
- Stars-only (ppg>=25): **FAILED** — only 255 training samples, below minimum
- Starters+ (ppg>=15): **WORSE** — drops HR by 20+ pp vs all-players
- Role only (ppg<15): **MIDDLE** — better than starters+ but worse than all
- **Conclusion: Universal training is best. Don't tier-filter.**

#### Step 3: Lines-Only Training (4 experiments)
- **Inconclusive.** Helps Config C on W4 (+12.7pp) but hurts W2 (-5.6pp)
- Needs more investigation post-ASB

#### Step 4: Staleness Curve (6 experiments, Config C, W4 eval)

| Gap (days) | HR 3+ | N | MAE |
|-----------|-------|---|-----|
| 7 | 57.9% | 38 | 4.89 |
| 14 | 62.9% | 35 | 4.85 |
| 21 | 56.4% | 39 | 4.91 |
| 28 | 66.7% | 36 | 4.84 |
| 42 | 60.9% | 64 | 4.95 |
| 63 | 60.7% | 89 | 5.02 |

**No clear decay within 28 days.** Monthly retraining is sufficient.

#### Step 5: Cross-Season Validation (10 experiments)

Ran E and C on last season's (2024-25) equivalent windows:
- Last season was consistently harder (10-20pp lower HR across all windows)
- **Last season did NOT have a W4 dip** — C went 73.7% → 71.9% (stable)
- This season's W4 dip is trade-deadline-specific, not seasonal
- Cross-season training doesn't help: train on 2024-25, eval on 2025-26 W4 = 58.8%

### 3. Root Cause Analysis: Why W4 is Hard

- **Champion model UNDER-biased**: recommending 343 UNDERs vs 263 OVERs, but 52.5% of actuals went OVER
- **Stale model decay is the cause**: champion edge 5+ went from 82.2% (W2) → 73.6% (W3) → 32.0% (W4)
- **Trade deadline disruption**: 34 players changed teams, roles shifted
- **Lower scoring variance in W4** (std 8.2 vs 8.5-9.0): tighter outcomes = harder to find edge
- **Not a seasonal pattern**: last season's equivalent window was fine

### 4. Production State Assessment

**Current production chaos:** 18 models, 25 subsets, all decaying.

Subset collapse in Feb vs Jan:
- Top 3: 88.5% → 27.3% (-61pp)
- Green Light: 85.5% → 41.7% (-44pp)
- All Picks: 65.8% → 44.4% (-21pp)

**Root cause: 100% model staleness.** Subset logic is fine.

### 5. Created Rest-of-Season Plan

See `docs/08-projects/current/model-validation-experiment/02-REST-OF-SEASON-PLAN.md`

Key points:
- Retrain 2 models (E sniper + C workhorse) after ASB (Feb 18)
- 3-week retrain cadence (monthly is fine, emergency if HR < 52.4% for 5 days)
- Dual-model deployment: picks where both agree = highest confidence

### 6. Created Subset Redesign Plan

See `docs/08-projects/current/model-validation-experiment/03-SUBSET-REDESIGN-PLAN.md`

Key points:
- **"Best Bets" meta-subset**: 3-5 curated picks/day from multiple sources, one clean W/L record
- **Source tags**: `high_edge`, `dual_agree`, `3pt_bounce` — track where each pick came from
- **3PT% bounce-back signal**: players shooting cold → regression + model OVER = high confidence
- **Retire 20+ old subsets**, keep 3 models (primary, secondary, legacy)

---

## What Needs to Happen Next Session

### Priority 1: ASB Retrain (Feb 18, day before games resume)

```bash
# Config E (V9 MAE 33f sniper)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V9_ASB_RETRAIN" \
  --train-start 2025-11-02 --train-end 2026-02-13 \
  --force

# Config C (V12 MAE RSM50 workhorse)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM50_ASB_RETRAIN" \
  --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
  --train-start 2025-11-02 --train-end 2026-02-13 \
  --force
```

Both must pass governance gates. Shadow Feb 19-20, promote Feb 21.

### Priority 2: 3PT% Bounce-Back Investigation

**Open questions to resolve:**
- Is 3PT bounce a **signal** (flag on existing predictions) or an **independent system**?
  - Recommendation: **Signal/overlay**, not its own model. It modifies confidence on existing OVER picks.
- Where does it run? Phase 5 (prediction time) vs Phase 6 (export time)?
  - Recommendation: Phase 6 — it's a post-prediction filter, doesn't need its own model
- What data sources? V13 features have `fg3_pct_last_3` and `fg3_pct_std_last_5`. Need season 3PT% baseline.

**Experiments to run:**
1. Backtest 3PT bounce signal on W1-W4 to measure standalone hit rate
2. Test different z-score thresholds (-1.0, -1.5, -2.0)
3. Test minimum 3PA volume thresholds (4, 5, 6 per game)
4. Measure overlap with existing high-edge picks (is it additive or redundant?)

### Priority 3: Best Bets Implementation

1. Create `best_bets_picks` table in BigQuery
2. Build selection logic (query both models, apply source rules, rank by confidence)
3. Integrate with Phase 6 export to `v1/best-bets/`
4. Add provenance tracking (`source_tag`, `source_models`)

### Priority 4: Production Cleanup

1. Disable 15 stale/unused models (keep v9, v12_rsm50, legacy v9)
2. Deactivate 20+ old subset definitions
3. Update website to point at Best Bets as primary display

---

## Key Files Modified

| File | Change |
|------|--------|
| `ml/experiments/quick_retrain.py` | Added `--min-ppg`, `--max-ppg`, `--lines-only-train` flags |

## Key Files Created

| File | Content |
|------|---------|
| `docs/08-projects/current/model-validation-experiment/01-COMPREHENSIVE-RESULTS.md` | Full 52-experiment results |
| `docs/08-projects/current/model-validation-experiment/02-REST-OF-SEASON-PLAN.md` | Rest-of-season model plan |
| `docs/08-projects/current/model-validation-experiment/03-SUBSET-REDESIGN-PLAN.md` | Subset redesign + Best Bets + 3PT bounce |

---

## Critical Context for Next Session

1. **Games resume Feb 19.** Retrain must happen Feb 18.
2. **Champion is at 32% HR edge 5+ in Feb.** Every day without a fresh model loses money.
3. **Don't use multi-season training data.** Current-season only (Nov 2 → latest) works best.
4. **Config E (V9 MAE) = sniper, Config C (V12 MAE RSM50 no-vegas) = workhorse.** Deploy both.
5. **"Best Bets" meta-subset is the north star** — one simple record for the website.
6. **3PT bounce is a signal/overlay, not a new model.** It feeds into Best Bets as a source.
7. **All experiment model files were cleaned up** — no disk bloat.

---

## Dead Ends (Don't Revisit)

- **Tier-filtered training** (stars-only, starters-only): always worse than universal
- **Huber loss** (Config B): consistently underperforms MAE across all windows
- **Multi-season training**: patterns don't transfer across seasons (Session 252 + confirmed here)
- **Cross-season models**: training on 2024-25 doesn't help predict 2025-26 (58.8% HR)
