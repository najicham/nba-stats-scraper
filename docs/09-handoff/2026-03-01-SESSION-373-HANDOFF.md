# Session 373 Handoff — Research Synthesis, ITT Signal, B2B Disable, Model Cleanup

**Date:** 2026-03-01
**Commit:** `a2fa6520` (pushed to main, auto-deploying)
**Prior Session:** 372 (commit `2ee018c4`)

---

## What Was Done

### Research Phase (6 parallel agents + 3 validation agents)

Launched 6 research agents covering retrain readiness, signal/filter mining, live performance monitoring, shadow model fleet audit, filter health audit, and P&L trend analysis. Then 3 validation agents cross-checked the top findings.

**Key validated findings:**
1. Near-zero scoring_trend_slope UNDER: 50.4% raw HR but best bets already filters (N=5 at 60%) — NOT worth implementing
2. 2+ star_teammates_out: 48.3% raw HR (N=953) confirmed but best bets N=14 at 60% — too small to act on
3. IND UNDER toxic: 25.3% is Feb-only, overall 50.0% — does NOT meet block threshold
4. B2B UNDER: 39.5% Feb confirmed, b2b_fatigue_under signal fires only 3 times total — backwards logic
5. ITT >= 120 + OVER: 70.2% HR (N=329) confirmed exactly, Feb-resilient at 64.3% (N=28)

### Code Changes

1. **New signal: `high_scoring_environment_over`** (`ml/signals/high_scoring_environment_over.py`)
   - 70.2% HR (N=329), Feb-resilient at 64.3%
   - Fires on OVER + implied_team_total >= 120
   - Piped feature_42 through supplemental_data.py
   - CONDITIONAL status — pending more best bets data (N=8 in best bets)

2. **Disabled: `b2b_fatigue_under` signal**
   - 39.5% Feb HR (N=410), collapsed from 66.7% Dec
   - Only 3 best bets picks total (2-1)
   - Philosophically backwards: encouraged B2B UNDER which is the worst-performing category

3. **Algorithm version:** `v373_itt_signal_b2b_disabled`

4. **Decommissioned 5 models in BQ registry** (set status='disabled'):
   - `catboost_v12_train1102_0125` (33.3% HR)
   - `catboost_v12_q43_train1225_0205` (33.3% HR)
   - `catboost_v12_vegas_q43_train0104_0215` (37.5% HR)
   - `catboost_v12_noveg_mae_train0104_0215` (41.2% HR)
   - `catboost_v9_low_vegas_train1225_0209` (43.5% HR)
   - `similarity_balanced_v1` not in registry — needs manifest cleanup

### Signal Count: Still 16
- Removed: b2b_fatigue_under
- Added: high_scoring_environment_over

---

## Season Performance Summary

| Month | W-L | HR | P&L (units) |
|-------|-----|-----|-------------|
| January | 49-18 | 73.1% | +26.59 |
| February | 26-18 | 59.1% | +5.66 |
| **Season** | **75-36** | **67.6%** | **+32.25** |

- OVER collapsed 80% → 56% (Feb), UNDER stable at 63%
- Rolling 7d HR: 66.7% (recovering from Feb 19-20 trough of 40%)
- Regime: FLAT — profitable but grinding, new ATH on Feb 22 (+33.52)
- Signal count 3 = 57.4%, 4+ = 76.0%, 6+ = 87%

---

## Retrain Status

**13 experiments run.** No model passes ALL 6 governance gates.

**Best candidates saved locally:**
- `v12_vw015_jan04_feb08`: 67.3% HR, N=49, MAE=4.97 — passes all gates except N (by 1!)
- `v12_vw015_jan04_feb10`: 62.5% HR, N=56, MAE=5.15 — passes all except MAE (by 0.008)

**Plan:** Re-run `v12_vw015_jan04_feb08` on Mar 1 after Feb 28 games are graded. Should push N to 50+.

```bash
python bin/quick_retrain.py \
  --feature-set v12 \
  --category-weight vegas=0.15 \
  --train-start 2026-01-04 \
  --train-end 2026-02-08 \
  --force
```

---

## Shadow Model Fleet

### KEEP (7 models)
- `v9_low_vegas_train0106_0205` — **star performer**: 56.7% edge 3+ HR, 3-0 best bets
- `v9_q45_train1102_0125` — 55.9% HR, best raw model
- `v9` (production), `ensemble_v1`, `ensemble_v1_1` — above breakeven
- `v12_noveg_q45_train1102_0125`, `v12_noveg_train1102_0205` — sourcing winning best bets

### TOO NEW (16 models)
- Deployed Feb 26-28, zero graded data. Includes V16, LightGBM, tier-weighted, V13, V15.
- Evaluate after 7 days (by Mar 5-7).

---

## Filter Health Summary

| Filter | Status | Notes |
|--------|--------|-------|
| Player blacklist | HEALTHY | Rejected picks at 15.0% HR — strongest filter |
| AWAY block | HEALTHY | v9 AWAY 28.8%, v12_noveg 41.0% |
| Signal count ≥3 | HEALTHY | Validated |
| line_jumped_under | **SUSPECT** | 55.8% HR on rejected picks — may block winners |
| familiar_matchup | **DATA GAP** | 0 rejections despite BQ showing 729 picks at 49.1% |
| Opponent UNDER block | OK | MIL 26.1% Feb (catastrophic), MIN 46.2% |

---

## What Was NOT Done (Deferred)

1. **Signal count floor 3→4** — wait for new signals to fire 1 week, then evaluate
2. **Investigate familiar_matchup data gap** — `games_vs_opponent` may not be populated
3. **Monitor line_jumped_under filter** — review in 2 weeks (if still >55% HR, raise threshold)
4. **2+ stars_out block** — watch until best bets N reaches 30+
5. **Deploy validation-runner** — pre-existing drift, not critical

---

## Key Files Modified

| File | Change |
|------|--------|
| `ml/signals/high_scoring_environment_over.py` | NEW — 43 lines |
| `ml/signals/registry.py` | Disabled b2b, registered ITT signal |
| `ml/signals/supplemental_data.py` | Piped feature_42 (implied_team_total) |
| `ml/signals/aggregator.py` | Algorithm version bump |
| `ml/signals/pick_angle_builder.py` | Removed b2b angle, added ITT angle |
| `CLAUDE.md` | Signal table, dead ends, signal count |

---

## Deployment Status

- Commit `a2fa6520` pushed, auto-deploying via Cloud Build
- Signal changes take effect via phase6-export Cloud Function
- prediction-coordinator trigger only watches `predictions/coordinator/**`, NOT `ml/signals/` — no coordinator redeploy needed
- v372 changes went live on Mar 1 (phase6-export redeployed); v373 will follow immediately
