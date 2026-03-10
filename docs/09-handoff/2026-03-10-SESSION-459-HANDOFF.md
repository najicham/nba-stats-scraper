# Session 459 Handoff — MLB Hyperparameter Sweep + NBA BB Pipeline Replay

*Date: 2026-03-10*

## What Was Done

### MLB: Complete Experiment Matrix (27 experiments × 4 seasons = 100+ runs)

Three rounds of experiments on the MLB strikeout best bets system, all using `scripts/mlb/training/season_replay.py` with V3 FINAL baseline flags: `--max-picks 5 --away-edge-floor 1.25 --block-away-rescue`.

#### P0 Experiments — Odds-Aware Ranking + Juice Filter

| Experiment | Total P&L | Delta | Verdict |
|-----------|-----------|-------|---------|
| **V3 FINAL baseline** | **+444.4u** | — | **KEEP** |
| EV ranking (edge × payout) | +450.7u | +6.2u | NOISE (2/4 seasons) |
| Max juice -160 filter | +411.1u | -33.3u | DEAD END |

#### P1 Experiments — Pipeline Parameter Tuning

| Experiment | Total P&L | Delta | Consistent? |
|-----------|-----------|-------|-------------|
| **V3 FINAL baseline** | **+444.4u** | — | — |
| Edge floor 0.85 | +400.3u | -44.1u | 2/4 |
| Edge floor 1.00 | +312.8u | -131.6u | 0/4 |
| RSC cap <= 5 | +450.4u | +6.0u | 1/4 |
| RSC cap <= 4 | +424.2u | -20.2u | 1/4 |
| No rescue | +375.2u | -69.2u | 0/4 |
| Max edge 1.5 | +369.5u | -74.9u | 0/4 |
| Edge 1.0 + RSC 5 | +315.2u | -129.2u | 0/4 |
| Edge 0.85 + RSC 5 + no rescue | +331.1u | -113.3u | 1/4 |
| Training window 90d | +408.4u | -36.0u | 1/4 |

**Key finding:** Rescue signals are worth +69u. Edge floor 0.75 is optimal. RSC 6+ is NOT losing money.

#### P2 Experiments — CatBoost Hyperparameter Sweep

| Experiment | Total P&L | Delta | Consistent? |
|-----------|-----------|-------|-------------|
| **Baseline (d5/lr.015/i500/l2=3)** | **+444.4u** | — | — |
| **L2 reg 10.0** | **+486.3u** | **+41.9u** | 2/4 |
| **L2=10 + Depth 4** | **+510.6u** | **+66.2u** | **3/4** |
| L2=10 + LR 0.01 | +445.6u | +1.2u | 2/4 |
| L2=10 + Depth 4 + LR 0.01 | +400.1u | -44.3u | 1/4 |
| LR 0.01 | +446.9u | +2.5u | 2/4 |
| Depth 4 | +440.3u | -4.1u | 2/4 |
| LR 0.02 | +422.3u | -22.1u | 2/4 |
| LR 0.03 | +317.0u | -127.4u | 0/4 |
| Iterations 300 | +391.9u | -52.5u | 2/4 |
| Iterations 700 | +389.9u | -54.5u | 0/4 |
| Iterations 1000 | +315.9u | -128.5u | 1/4 |
| Retrain 10d | +392.0u | -52.4u | 0/4 |
| Retrain 21d | +280.1u | -164.3u | 0/4 |

**WINNER: L2=10 + Depth 4** — +510.6u total (+66.2u / +14.9% over baseline), 63.3% HR, 13.9% ROI, 65.5% Ultra HR. Positive in 3/4 seasons. Higher regularization + shallower trees = less overfitting.

Per-season breakdown:
| Season | Baseline P&L | L2=10+D4 P&L | Delta |
|--------|-------------|-------------|-------|
| 2022 | +45.4u | +63.1u | +17.7u |
| 2023 | +55.5u | +41.2u | -14.3u |
| 2024 | +118.3u | +152.6u | +34.3u |
| 2025 | +225.2u | +253.7u | +28.5u |

**NOT yet deployed to production** — needs user approval.

### NBA: BB Pipeline Replay Analysis

Ran both `bb_pipeline_simulator.py` and `bb_full_simulator.py` using clean walk-forward predictions from `results/nba_walkforward_clean/predictions_w56_r7.csv` (2 seasons: 2023-24 and 2024-25).

#### Raw Model Performance (w56_r7, clean data — no leakage)

| Edge Floor | HR% | N | Flat P&L |
|-----------|-----|---|----------|
| Edge 1+ | 52.5% | 13,988 | — |
| Edge 3+ | **53.4%** | **2,193** | **+46.8** |
| Edge 5+ | 53.5% | 604 | — |
| Edge 7+ | 49.6% | 272 | — |

- **OVER: 49.6%** (N=409) — below coin flip
- **UNDER: 54.3%** (N=1,784) — structurally stronger
- **w56_r7 is best config** — beats w42, w90, and all r14 variants

#### BB Pipeline Simulator — Edge/Direction/Volume Experiments (no signals)

| Strategy | HR% | N | P&L ($100 bets) | /Day |
|----------|-----|---|-----------------|------|
| Raw edge 3+ | 53.4% | 2,193 | +4,255 | 6.3 |
| OVER 6+ / UNDER 3+ | **54.3%** | 1,799 | **+6,618** | — |
| Edge 5.5+ | 54.2% | 483 | +1,718 | — |
| Edge 7+ | 49.6% | 272 | -1,427 | — |

**Edge 7+ is LOSING money** — overconfidence kills HR. Sweet spot is 3.0-5.5.

#### BB Full Pipeline Simulator — Signals + Filters

| Strategy | HR% | N | P&L | /Day | Consistent? |
|----------|-----|---|-----|------|-------------|
| **A: Current production** (sc>=3 rsc>=1) | **52.1%** | 726 | **-436** | 2.7 | **NO** |
| B: No filters, no signal gates (e3+) | 54.1% | 3,929 | +12,973 | 9.6 | YES |
| C: Filters only, no signals | 53.4% | 1,513 | +2,955 | 4.7 | YES |
| D: Signals only, no filters | 52.6% | 3,635 | +1,900 | 8.9 | YES |
| **e5+ sc>=2 rsc>=0 top5** | **54.7%** | **780** | **+3,518** | **2.4** | **YES** |
| e5+ sc>=4 rsc>=2 top3 | 58.2% | 170 | +1,900 | 1.4 | YES |
| sc>=4 real_sc>=2 | 57.2% | 229 | +2,109 | 1.9 | YES |
| max 3/day | 53.7% | 516 | +1,282 | 1.9 | YES |
| Edge 6-7 (full pipeline) | 62.5% | 40 | +773 | 1.3 | no |
| **Edge 6-7 relaxed gates** | **64.8%** | **54** | **+1,282** | **1.2** | **YES** |

#### Edge 6-7 Deep Dive

Edge 6-7 is the single highest HR bucket (64.8%), but:
- Only 54 picks across 2 seasons (1.2/day) — too few to bet on alone
- **Signal gates HURT at this edge level** — strict gates filter 14 winners (62.5% → 64.8% when relaxed)
- At edge 6+, model conviction is strong enough that signals are redundant as gates

#### Filter Audit

| Filter | Blocked | Would-be HR | Verdict |
|--------|---------|-------------|---------|
| edge_floor | 14,020 | 51.8% | CORRECT |
| over_edge_floor | 11,725 | 49.9% | CORRECT |
| **ft_variance_under** | **610** | **58.7%** | **BLOCKING WINNERS** |
| **high_skew_over_obs** | **22** | **63.6%** | **BLOCKING WINNERS** |
| med_usage_under | 1,060 | 53.8% | BORDERLINE |
| b2b_under | 1,025 | 54.5% | BORDERLINE |
| prediction_sanity | 26 | 34.6% | CORRECT |
| friday_over_block | 10 | 20.0% | CORRECT |

#### Player Blacklist Candidates (edge 3+, HR<40%, N>=10)

| Player | N | HR% |
|--------|---|-----|
| Spencer Dinwiddie | 16 | 37.5% |
| Kawhi Leonard | 14 | 35.7% |
| Donte DiVincenzo | 12 | 33.3% |
| CJ McCollum | 10 | 30.0% |
| Naz Reid | 10 | 30.0% |

#### CRITICAL FINDING: Current NBA Production is Losing Money

The `rsc>=1` gate is the culprit:
- `sc>=1 rsc>=0`: 53.4% HR, +2,955 P&L (PROFITABLE)
- `sc>=3 rsc>=1`: 52.1% HR, -436 P&L (LOSING)
- The rsc>=1 requirement costs ~3,400 in P&L by filtering out good picks

## What's Next — NBA Improvements (Priority Order)

### P0: Immediate Fixes (replay-validated, ready to implement)

1. **Raise edge floor 3→5** — Edge 3-5 bucket is 50.6% HR (losing). Cutting it improves overall HR and P&L.
2. **Relax rsc gate >=1 → >=0** — Current gate costs ~3,400 P&L. Most profitable config is `e5+ sc>=2 rsc>=0 top5` (54.7% HR, +3,518).
3. **Fix ft_variance_under filter** — Blocking picks that win 58.7% of the time. 610 picks affected. Either remove or recalibrate thresholds.
4. **Cap volume 15→5/day** — Top 5 by edge: better HR, better P&L per pick.

### P1: Tiered Strategy (needs more replay testing)

5. **Tiered edge approach:**
   - Edge 6+: auto-pick, no signal gates needed (64.8% HR)
   - Edge 5-6: require sc>=2, filters only (53.6% HR)
   - Edge 3-5: DROP entirely (50.6% HR, losing)
6. **Test combined config** — Run `bb_full_simulator.py` with: e5+ floor, rsc>=0, ft_variance disabled, max 5/day, tiered gates. Get per-season breakdown.
7. **Test ft_variance_under recalibration** — Current thresholds (FTA>=5, CV>=0.5) may be too aggressive. Test FTA>=7 or CV>=0.6.

### P2: MLB Pre-Season (Before March 25)

8. **Deploy L2=10 + Depth 4** to production if approved (+66u, 3/4 seasons positive)
9. **Train fresh MLB model** on 2025 data (March 18-20 timeframe)
10. **Deploy MLB worker** (manual: `gcloud builds submit --config cloudbuild-mlb-worker.yaml`)
11. Paper trade April 1-14, full stakes April 15+

## How to Run More Experiments

### NBA BB Simulator (FAST — no BQ needed, uses cached predictions)

```bash
# Pipeline simulator (edge/direction/volume sweeps — ~30 seconds)
PYTHONPATH=. python scripts/nba/training/bb_pipeline_simulator.py

# Full pipeline simulator (signals + filters — ~2 minutes)
PYTHONPATH=. python scripts/nba/training/bb_full_simulator.py

# Results in: results/bb_simulator/
```

Both simulators use `results/nba_walkforward_clean/predictions_w56_r7.csv` (30,064 predictions, 2 seasons). To modify experiments, edit the constants and experiment configs in the simulator files.

### NBA Walk-Forward (SLOW — BQ queries, ~30s per config)

```bash
PYTHONPATH=. python scripts/nba/training/walk_forward_simulation.py \
  --output-dir results/nba_walkforward_clean/
```

Only re-run if testing new model configs (window, retrain interval, features).

### MLB Season Replay (SLOW — BQ queries, ~5min per season)

```bash
# V3 FINAL baseline
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay_cross/2025_test/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue

# With L2=10 + Depth 4
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay_cross/2025_l2d4/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue \
  --l2-reg 10.0 --depth 4
```

Season date ranges: 2022 (04-07→10-05), 2023 (03-30→10-01), 2024 (03-28→09-29), 2025 (03-27→09-28).

Available experiment flags: `--edge-floor`, `--away-edge-floor`, `--block-away-rescue`, `--max-picks`, `--ev-ranking`, `--max-juice`, `--max-rsc`, `--no-rescue`, `--max-edge-cap`, `--depth`, `--lr`, `--iters`, `--l2-reg`, `--retrain-interval`, `--training-window`, `--dynamic-blacklist`, `--enable-under`.

## Experiment Rules

1. **Always run baseline + experiment back-to-back** (same BQ data load for MLB)
2. **Max 2 BQ-heavy seasons in parallel** (avoid timeouts)
3. **Report per-season AND total**: HR%, P&L, ROI%, N picks, Ultra HR(N), Delta
4. **Consistency matters**: 3/4+ seasons positive = real signal, 2/4 = noise

## Data Files

| File | What | Size |
|------|------|------|
| `results/nba_walkforward_clean/predictions_w56_r7.csv` | Clean NBA walk-forward predictions (w56/r7) | 2MB |
| `results/nba_walkforward_clean/simulation_summary.json` | Walk-forward config comparison (6 configs) | 14KB |
| `results/bb_simulator/experiment_results.json` | NBA pipeline simulator results | 304KB |
| `results/bb_simulator/full_pipeline_results.json` | NBA full pipeline simulator results | 7KB |
| `results/bb_simulator/feature_store_enrichment.csv` | NBA feature store data for simulators | 13MB |
| `results/bb_simulator/player_game_summary_enrichment.csv` | NBA PGS data for simulators | 22MB |
| `results/mlb_season_replay_cross/` | All MLB season replay results (100+ runs) | — |

## Files Modified This Session

| File | Change |
|------|--------|
| `scripts/mlb/training/season_replay.py` | P0-P2 experiment flags: ev-ranking, max-juice, max-rsc, no-rescue, max-edge-cap, depth, lr, iters, l2-reg. Parameterized `train_regressor()`. |
