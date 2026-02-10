# Model Strategy Roadmap

**Created:** Session 176 (2026-02-09)
**Status:** Living document — update after each retrain cycle

## A. Monthly Retrain Cadence

**When:** 1st week of each month (after prior month's games are fully graded, typically by the 3rd)

**Training window:** Rolling ~90 days ending last day of previous month
- Example (March retrain): Train Nov 2 – Feb 28, eval Mar 1-14

**Evaluation window:** Last 14 days of training month, held out from training
- Minimum 7 days eval, 14 preferred for statistical reliability

**Always use `--walkforward`** to detect temporal decay within the eval period.

**Decision threshold:** Retrain if trailing 2-week edge 3+ HR < 55% (from `model_diagnose.py`).

**Standard workflow:**
```bash
# 1. Diagnose whether retrain is needed
PYTHONPATH=. python ml/experiments/model_diagnose.py

# 2. Run baseline experiment
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$(date +%b)_MONTHLY" \
    --train-start 2025-11-02 --train-end YYYY-MM-DD \
    --eval-start YYYY-MM-DD --eval-end YYYY-MM-DD \
    --walkforward

# 3. Run tuned experiment for comparison
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$(date +%b)_MONTHLY_FULL" \
    --train-start 2025-11-02 --train-end YYYY-MM-DD \
    --eval-start YYYY-MM-DD --eval-end YYYY-MM-DD \
    --tune --recency-weight 30 --walkforward

# 4. Compare both experiments: HR All, n(edge 3+), walk-forward stability
# 5. Promote only if ALL 6 governance gates pass
```

## B. Next Retrain Plan (Feb/Mar 2026)

**Cannot retrain with Feb eval yet** — need graded data, and Feb 9 games are still pending.

### Option 1: Train through Jan 31
- **Train:** 2025-11-02 – 2026-01-31 (91 days)
- **Eval:** 2026-02-01 – 2026-02-14 (14 days)
- **Available:** ~Feb 17 (once Feb 14 games are graded, typically 2-3 day lag)
- **Pro:** Adds 23 days of new training data vs current production model
- **Con:** Feb 1-14 eval is only 14 days — may be thin for some subsets

### Option 2: Train through Feb 8
- **Train:** 2025-11-02 – 2026-02-08 (99 days)
- **Eval:** 2026-02-09 – 2026-02-21 (13 days)
- **Available:** ~Feb 24 (once Feb 21 games are graded)
- **Pro:** More training data, fully forward-looking eval
- **Con:** Delayed by 1 week vs Option 1

### Experiments to Run (3 configs each)

| Config | Flags | Purpose |
|--------|-------|---------|
| Baseline | `--walkforward` | Default params, temporal stability check |
| Tuned | `--tune --walkforward` | Best hyperparams from grid search |
| Full | `--tune --recency-weight 30 --walkforward` | Tuned + recency emphasis |

## C. Subset Optimization Strategy

### Current State
- 8 subsets defined by edge/confidence/direction/signal thresholds
- Subsets evaluated monthly via `/subset-performance`
- Edge 3+ is the primary production filter

### Problem: Survivorship Bias in Edge Thresholds
Session 176 showed that edge 3+ HR varies by model calibration:
- A conservative model (small avg edge) has high edge 3+ HR on few picks
- An aggressive model (large avg edge) has lower edge 3+ HR on many picks
- Same underlying accuracy, different reported HR at the 3+ threshold

### Recommendations
1. **Report pick volume alongside HR** — n(edge 3+) is as important as the hit rate
2. **Compare subsets monthly** — retire underperforming subsets (< 52.4% HR for 2+ months)
3. **Consider dynamic thresholds** — adjust edge threshold based on model's edge distribution (e.g., use percentile-based thresholds instead of absolute 3+)
4. **Future work:** Dynamic subset thresholds that adjust based on the model's average edge magnitude

### Subset Grading Cadence
- Monthly: Full subset performance review after each month's games graded
- Compare n(picks), HR, ROI for each subset
- Flag subsets with < 52.4% HR or < 30 picks/month as candidates for retirement

## D. V10 Feature Expansion

### V10 Contract (Already Defined)
37 features: V9's 33 + 4 new candidates:
- `dnp_rate` — Recent DNP frequency (load management signal)
- `pts_slope_10g` — 10-game scoring trend (momentum)
- `pts_vs_season_zscore` — How far current scoring is from season average
- `breakout_flag` — Binary breakout classifier output (from V3)

### Zero-Importance Candidates for Removal
Session 176 feature importance consistently shows:
- `injury_risk`: 0% importance across all experiments
- `playoff_game`: 0% importance (always 0 during regular season)

**Recommendation:** Remove from V10 contract. Fewer features = faster inference, simpler model, less overfitting.

**Alternative:** Keep and investigate edge cases:
- `injury_risk` during trade deadline period (Feb) when rosters change
- `playoff_game` only becomes relevant post-April — test with playoff data before removing

### High-Value Additions (from Breakout V3 Research)
- `star_teammate_out` — Star teammates out (injury) → role player opportunity
- `fg_pct_last_game` — Hot shooting rhythm indicator

### Prerequisite
Backfill V10 features across the full training history (~Nov 2, 2025 – present) before V10 model can be trained. Requires updating Phase 4 precompute processors.

## E. Breakout Classifier V3

### Current V2 Status
- **AUC:** 0.5708 (14 features)
- **Critical Issue:** No high-confidence predictions (max probability < 0.6, need 0.769+)
- **Model:** `breakout_shared_v1_20251102_20260205.cbm`

### V3 Plan
Add contextual features that V2's statistical features can't capture:

| Feature | Expected AUC Lift | Data Source |
|---------|-------------------|-------------|
| `star_teammate_out` | +0.04-0.07 | Injury integration module |
| `fg_pct_last_game` | +0.01-0.03 | `player_game_summary` |
| `points_last_4q` | +0.01-0.02 | Play-by-play data |
| `opponent_key_injuries` | +0.02-0.04 | Injury integration module |

### Infrastructure (Ready)
- Shared feature module: `ml/features/breakout_features.py`
- Injury integration: `predictions/shared/injury_integration.py`
- Dual-mode experiment runner: `ml/experiments/breakout_experiment_runner.py`

### Target
- AUC > 0.65 (vs 0.5708 current)
- Predictions above 0.769 confidence threshold (currently none above 0.6)
- 60% precision at the 0.769 threshold

## F. Backtesting vs Production Reality

### The Gap (Session 176 + Reviewer Learning)

| Metric | Backtest | Production | Gap |
|--------|----------|------------|-----|
| HR All | 62.4% | 54.4% | 8pp |
| HR Edge 3+ | 87.0% (n=131) | 65.5% (n=388) | 21.5pp* |

*Edge 3+ gap is mostly survivorship bias (different n), not real performance difference.

### Why Backtest HR Is Always Higher

1. **Pre-computed features:** Backtest uses finalized Phase 4 features; production predicts at 2:30 AM with potentially stale/incomplete features
2. **No timing drift:** Historical features are "perfect" — all processors have already run
3. **No line movement:** Backtest uses the line at prediction time; production's line may have moved by game time
4. **Selection bias:** Production skips players with quality issues (zero tolerance); backtest only sees players that had clean features

### Recommendations

1. **All experiment reports must caveat:** "backtest advantage — expect 3-8pp lower in production"
2. **Investigate the 8pp gap** — if it's structural, governance gates need a "production discount"
3. **Consider tighter governance gates:** Require backtest HR 3+ >= 65% to expect production >= 60%
4. **Track the gap over time:** After each retrain+deploy, compare backtest vs first 14 days of production to calibrate the discount factor

## G. Feature Pruning (Zero-Importance Features)

### Candidates
| Feature | Importance | Reason |
|---------|------------|--------|
| `injury_risk` | 0% | No signal detected across any experiment |
| `playoff_game` | 0% | Always 0 during regular season (Nov-Apr) |

### Recommendation
Remove from V10 feature contract:
- Fewer features = faster inference, simpler model
- Less noise for CatBoost to overfit on
- Reduces feature store computation cost

### Before Removing
- [ ] Check if `injury_risk` has any signal during trade deadline week (Feb)
- [ ] Wait for playoff data (post-April) to test `playoff_game`
- [ ] Run A/B experiment: V9 with 31 features vs V9 with 33 features

### Decision Timeline
Make final call before next retrain (target: Feb 17-24). If not investigated by then, remove by default.

## H. Production Promotion Criteria (Codified)

Every model must pass ALL of the following before production deployment:

### Governance Gates (6 automated)
| # | Gate | Threshold |
|---|------|-----------|
| 1 | MAE improvement | < V9 baseline (5.14) |
| 2 | Hit rate (edge 3+) | >= 60% |
| 3 | Sample size (edge 3+) | >= 50 graded bets |
| 4 | Vegas bias | pred_vs_vegas within +/- 1.5 |
| 5 | No critical tier bias | All tiers < +/- 5 points |
| 6 | Directional balance | Both OVER and UNDER edge 3+ HR >= 52.4% |

### Additional Criteria (manual review)
| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Walk-forward stability | No week below 52.4% HR All | Catches temporal decay |
| Edge 3+ volume | >= 50% of production volume | Prevents conservative models that pass on tiny samples |
| Shadow test duration | >= 2 days | Real-world validation with separate system_id |
| User approval | Explicit at each step | Human-in-the-loop for all deployments |

### Promotion Process
```
1. Train → All 6 gates pass
2. Upload to GCS + register in manifest
3. Shadow test 2+ days (separate system_id)
4. Compare shadow vs production: HR, bias, volume
5. User approves → update CATBOOST_V9_MODEL_PATH
6. Monitor 24h post-promotion
7. Backfill predictions for affected dates
```

## I. Survivorship Bias Warning (New Standard)

### Reporting Requirements

All experiment reports MUST include:

| Metric | Why Required |
|--------|-------------|
| HR All (edge >= 1) | Apples-to-apples across models |
| n(edge 3+) | Shows how many actionable picks the model generates |
| Avg absolute edge | Shows how aggressive/conservative the model is |
| HR Edge 3+ | Standard metric, but context-dependent |

### Flags

- Models with < 50% of production's edge 3+ volume: Flag as "conservative — verify volume is acceptable"
- Models where avg edge < 2.0: Flag as "low-edge — may not generate enough actionable picks"
- All HR 3+ comparisons across models with different edge distributions: Flag as "not directly comparable — see HR All"

---

## Timeline Summary

| Target Date | Action | Dependencies |
|-------------|--------|--------------|
| Feb 17 | Option 1 retrain (train through Jan 31) | Feb 14 games graded |
| Feb 24 | Option 2 retrain (train through Feb 8) | Feb 21 games graded |
| Feb 24 | Feature pruning decision | Edge case investigation |
| Mar 1 | V10 feature backfill planning | Pruning decision |
| Mar 7 | Monthly retrain (Mar) | Feb fully graded |
| Ongoing | Breakout V3 contextual features | V2 baseline established |
