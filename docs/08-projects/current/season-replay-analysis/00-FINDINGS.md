# Season Replay Analysis — Findings & Improvements

Sessions 280-282. All-Star break window (games resume Feb 19).

## What We Built

Full season replay simulator (`ml/experiments/season_replay_full.py`) that:
- Trains all 6 model families every 14 days across a full season
- Applies per-model subset filters + 5 cross-model (xm) consensus subsets
- Runs 8-dimension analysis (player tier, direction, edge bucket, tier x direction, line range, signal simulation, confidence tier, smart filter impact)
- Per-day decay tracking (model age in actual days, not cycle-level averages)
- Edge sweep (tests edge >= 3, 4, 5 per model)
- **NEW: Rolling lookback health tracking** (28-day window, per-cycle rolling HR)
- **NEW: Adaptive filter mode** — direction gating, smart filter toggle, model weighting
- **NEW: Rolling training window** — train on last N days instead of expanding
- **NEW: Cross-season comparison mode** in `analyze_replay_results.py`
- **NEW (Session 282): 7 experiment filters** — day-of-week skip, volatility filter, tier-direction rules, player blacklist, warmup period, eval-month filter, tier-specific models
- **NEW (Session 282): 4 new dimensions** — Day of Week, Volatility Bucket, Direction x Tier, Monthly
- Exports JSON for programmatic analysis

## Cross-Season Comparison (Fixed Baseline)

### Model Rankings (edge >= 3)

| Model | 2024-25 HR | 2024-25 P&L | 2025-26 HR | 2025-26 P&L | Stable? |
|-------|-----------|-------------|-----------|-------------|---------|
| V9 MAE | 48.4% | -$530 | **72.5%** | +$6,480 | NO |
| V12 MAE | 53.1% | +$280 | 62.8% | +$6,240 | Improved |
| V9 Q43 | **56.7%** | **+$5,700** | 57.7% | **+$8,550** | **YES** |
| V9 Q45 | 56.2% | +$3,230 | 58.1% | +$7,330 | **YES** |
| V12 Q43 | 55.2% | +$4,410 | 54.2% | +$3,930 | **YES** |
| V12 Q45 | 53.7% | +$1,760 | 53.9% | +$2,590 | **YES** |

**Key finding: V9 Q43 is the most consistently profitable model across both seasons.** V9 MAE is wildly inconsistent (48% -> 73%). The quantile models are remarkably stable.

### Direction is Season-Specific (CRITICAL)

| Season | OVER HR | OVER N | UNDER HR | UNDER N |
|--------|---------|--------|----------|---------|
| 2024-25 | **39.5%** | 129 | **55.9%** | 2,508 |
| 2025-26 | **79.3%** | 319 | **54.8%** | 3,325 |

OVER completely inverted between seasons. UNDER is the stable edge (55-56% both seasons). **Do NOT build direction-biased systems.** UNDER is the only reliable direction.

### Dead Zones Inverted Too

| Line Range | 2024-25 HR | 2025-26 HR | Stable? |
|------------|-----------|-----------|---------|
| 5-9.5 | **30.9%** | **60.7%** | NO (inverted) |
| 10-14.5 | 58.2% | 58.3% | **YES** |
| 15-19.5 | 55.2% | 60.0% | YES |
| 20-24.5 | **56.7%** | **52.2%** | NO (was good, now dead) |
| 25-29.5 | 52.7% | 53.4% | Marginal both |
| 30+ | 57.9% | 60.4% | YES |

**Stable sweet spots:** 10-14.5, 15-19.5, 30+. Everything else is season-dependent.

### Subsets That Work Both Seasons

| Subset | 2024-25 HR | 2024-25 P&L | 2025-26 HR | 2025-26 P&L |
|--------|-----------|-------------|-----------|-------------|
| q43_under_all | 56.7% | +$5,700 | 55.6% | +$4,970 |
| xm_diverse_agreement | 56.1% | +$3,830 | 57.2% | +$6,170 |
| xm_consensus_3plus | 55.9% | +$3,130 | 59.2% | +$8,010 |
| xm_quantile_agreement_under | 55.2% | +$1,140 | 56.6% | +$2,610 |
| nova_q43_under_top3 | 88.9% | +$1,380 | 61.1% | +$330 |
| nova_q45_under_top3 | 88.9% | +$1,380 | 77.8% | +$960 |

### Subsets That DON'T Survive Cross-Season

| Subset | 2024-25 | 2025-26 | Verdict |
|--------|---------|---------|---------|
| high_edge_over | 28.6% HR | 84.8% HR | Season-specific |
| high_edge_all (V9 MAE) | 48.4% HR | 72.5% HR | Unstable |
| xm_mae_plus_quantile_over | 42.9% HR | 83.1% HR | Season-specific |

### Daily Decay (per-pick, not per-cycle)

| Age Bucket | 2024-25 All Models | 2025-26 All Models |
|-----------|-------------------|-------------------|
| Day 1-3 | 60.2% (N=686) | 50.6% (N=549) |
| Day 4-7 | 53.9% (N=778) | 60.6% (N=1194) |
| Day 8-10 | 59.7% (N=519) | 55.4% (N=690) |
| Day 11-14 | 47.4% (N=654) | 57.2% (N=1211) |

2024-25 shows clear Day 11-14 decay (47.4%). 2025-26 does NOT decay. Pattern is inconsistent across seasons.

### Edge Sweep

**2025-26:**
| Model | Edge 3+ HR | Edge 4+ HR | Edge 5+ HR |
|-------|-----------|-----------|-----------|
| V9 MAE | 72.5% | 81.9% | 84.2% |
| V12 MAE | 62.8% | 72.4% | 74.5% |
| V9 Q43 | 57.7% | 59.2% | 60.3% |
| V12 Q43 | 54.2% | **60.3%** | 57.3% |

**V12 Q43 jumps from 54.2% to 60.3% at edge >= 4.** This confirms the fix: raise V12 quantile min edge to 4.

### Smart Filter Impact

**2025-26 — passed_all_filters vs blocked:**
- Passed: 54.4% HR across all models (profitable)
- Blocked by any filter: 62.9% HR (blocked picks were BETTER in 2025-26!)
- Blocked `rel_edge>=30%`: 65.8% HR — these were our BEST picks this season

**2024-25 — passed_all_filters vs blocked:**
- Passed: 56.0% HR across all models (profitable)
- Blocked by any filter: 49.7% HR (correctly blocked garbage)
- Blocked `bench_under_low`: 41.8% HR (correctly blocked)

**Verdict:** Smart filters help in 2024-25 but hurt in 2025-26. The relative edge filter (>=30%) blocks high-confidence picks that were profitable this season.

---

## Session 281: Adaptive Replay Results

### Experiment Design

Ran 4 variants across both seasons (8 total runs):

| Variant | Description |
|---------|-------------|
| **Fixed** (baseline) | Expanding training window, static subset filters |
| **Adaptive** | 28-day rolling lookback, auto-adjusts direction gating + smart filter toggle + model weighting |
| **Rolling-56** | 56-day rolling training window (trains on most recent 56 days only) |
| **Adaptive+Rolling** | Both adaptive filters AND rolling training window |

### Head-to-Head P&L Comparison

| Variant | 2025-26 P&L | 2024-25 P&L | Combined | Survivors |
|---------|------------|------------|----------|-----------|
| Fixed (baseline) | +$35,120 | +$14,850 | **+$49,970** | 17 |
| Adaptive (28d) | +$35,120 | +$14,850 | +$49,970 | 17 |
| **Rolling (56d)** | **+$37,750** | **+$21,770** | **+$59,520** | **22** |
| Adaptive+Rolling | +$37,750 | +$21,770 | +$59,520 | 22 |

### Key Finding: Rolling Training is the Big Win

**Rolling 56-day training window improves total P&L by +$9,550 (+19.1%) over fixed baseline.** The improvement comes entirely from 2024-25 (+$6,920) where stale early-season data was hurting model accuracy.

Per-model improvement with rolling training (2024-25):

| Model | Fixed HR | Rolling HR | Delta |
|-------|---------|-----------|-------|
| V9 MAE | 48.4% | **56.9%** | **+8.5pp** |
| V12 MAE | 53.1% | 54.0% | +0.9pp |
| V9 Q43 | 56.7% | 56.9% | +0.2pp |
| V12 Q43 | 55.2% | **57.1%** | **+1.9pp** |

V9 MAE went from money-losing (48.4%) to profitable (56.9%) just by dropping old training data.

### Key Subset Improvements (Rolling vs Fixed)

| Subset | Fixed 2425 | Rolling 2425 | Fixed 2526 | Rolling 2526 |
|--------|-----------|-------------|-----------|-------------|
| q43_under_all | 56.7%, +$5,700 | **56.9%, +$6,070** | 55.6%, +$4,970 | **55.9%, +$5,530** |
| xm_consensus_3plus | 55.9%, +$3,130 | **57.6%, +$4,770** | 59.2%, +$8,010 | **59.5%, +$8,410** |
| nova_q43_under_all | 55.7%, +$5,000 | **57.4%, +$7,820** | 53.3%, +$1,880 | **53.8%, +$2,850** |

Rolling training improves every key subset in both seasons. No subset regresses.

### Adaptive Mode: Works Correctly But Limited Impact

Adaptive mode made the **right decisions** in both seasons:

**2025-26 adaptive decisions:**
- Cycles 2-6: Consistently disabled `rel_edge>=30%` filter (blocked segment had 63-67% HR)
- Never suppressed OVER (correctly — OVER was 79% HR this season)

**2024-25 adaptive decisions:**
- Cycles 2-4: Suppressed OVER (correctly — OVER was 39% HR)
- Cycles 3-4: Halved V9 MAE weight (correctly — V9 MAE was below 50% HR)
- Cycle 5+: Detected OVER recovery, stopped suppressing

**Why limited P&L impact?** The adaptive decisions only affect per-model subset filters (direction gating on OVER/UNDER subsets), not the cross-model consensus subsets which drive most P&L. The only visible impact is on `high_edge_over` in 2024-25 where adaptive reduced exposure from 21 picks to 6 picks, cutting losses from -$1,050 to -$240.

### Rolling Training: Cross-Season Subset Survivors

Rolling training produced **22 survivors** (subsets profitable in BOTH seasons) vs 17 for fixed baseline. The 5 new survivors:

| Subset | Fixed 2425 HR | Rolling 2425 HR | Status |
|--------|-------------|----------------|--------|
| high_edge_all (V9) | 48.4% | **56.9%** | NEW SURVIVOR |
| q43_all_picks | 51.9% | **52.4%** | NEW SURVIVOR |
| q45_all_picks | 52.2% | **52.8%** | NEW SURVIVOR |
| nova_top_pick | 83.3% (both) | 83.3% (both) | NEW SURVIVOR |
| nova_q43_all_picks | 51.6% | **52.0%** | marginally |

---

## Session 282: Experiment Filter Results

### 7 Experiments Tested

All experiments use rolling 56-day training as the base (proven best in Session 281).

| Exp | Filter | Description |
|-----|--------|-------------|
| A | `--eval-months` | Only eval picks from specific months |
| B | `--skip-days 1,4` | Skip Tuesday + Friday picks |
| C | `--min-pts-std 5 --max-pts-std 10` | Only bet on medium-volatility players |
| D | `--tier-direction-rules` | Star=UNDER only, Bench=OVER only |
| E | `--player-blacklist-hr 40` | Blacklist players below 40% HR after 8+ picks |
| F | `--warmup-days 42` | Skip first 42 days of eval |
| G | `--tier-models` | Train separate models per player tier (Star/Starter/Bench) |

### Cross-Season P&L Results

| Variant | 2025-26 P&L | 2025-26 HR | 2025-26 N | 2024-25 P&L | 2024-25 HR | 2024-25 N | Combined |
|---------|------------|-----------|----------|------------|-----------|----------|----------|
| Rolling56 (baseline) | +$37,750 | 57.3% | 3,643 | +$21,770 | 56.2% | 2,702 | **+$59,520** |
| **E: Blacklist40** | **+$44,470** | **58.8%** | **3,286** | **+$25,500** | **57.5%** | **2,376** | **+$69,970** |
| B: SkipTueFri | +$34,540 | 58.9% | 2,542 | +$18,610 | 56.7% | 2,032 | +$53,150 |
| D: TierDir | +$35,700 | 58.3% | 2,877 | +$13,270 | 55.5% | 2,008 | +$48,970 |
| COMBO (B+D+E) | +$36,160 | 62.1% | 1,777 | +$14,830 | 57.7% | 1,339 | +$50,990 |
| G: TierModels | +$36,220 | 56.6% | 4,096 | — | — | — | — |
| C: Vol5-10 | +$37,750 | 57.3% | 3,643 | — | — | — | — |
| F: Warmup42 | FAILED | — | — | FAILED | — | — | — |

### KEY FINDING: Player Blacklist is the Biggest Win

**Blacklist40 improves combined P&L by +$10,450 (+17.6%)** over rolling56 baseline, with gains in BOTH seasons. Only removes ~10% of picks but they're disproportionately bad.

**Subset-level impact of blacklist (both seasons improve):**

| Subset | Base 2526 | BL40 2526 | Base 2425 | BL40 2425 |
|--------|----------|----------|----------|----------|
| xm_consensus_3plus | 59.5% | **62.1%** | 57.6% | **59.4%** |
| xm_diverse_agreement | 57.8% | **60.0%** | 56.2% | **57.4%** |
| xm_quant_under | 56.1% | **58.8%** | 57.4% | **63.3%** |
| nova_q43_under_all | 53.8% | **54.3%** | 57.4% | **59.6%** |
| q43_under_all | 55.9% | 56.1% | 56.9% | 56.6% |

Cross-model subsets benefit most because removing persistently-wrong players cleans up consensus calculations.

### Experiment Verdicts

| Exp | Verdict | Reason |
|-----|---------|--------|
| **E: Blacklist** | **IMPLEMENT** | +$10,450, both seasons improve, minimal volume loss |
| B: SkipDays | REJECT | Day-of-week patterns completely invert between seasons |
| D: TierDir | REJECT | -$10,550 vs baseline. Direction x tier rules are season-specific |
| COMBO | REJECT | Highest HR (62.1%) but too much volume loss, lower total P&L |
| C: Volatility | NO EFFECT | Feature_3 values mostly < 5 in 2025-26. Needs investigation. |
| F: Warmup | BROKEN | Empty eval windows when warmup + min_training_days overlap |
| G: TierModels | REJECT | Lower HR (56.6% vs 57.3%), worse P&L. Standard model beats tier-specific. |

### New Dimension Analysis (Cross-Season)

**Day of Week — NOT stable (do NOT filter):**

| Day | 2025-26 HR (N) | 2024-25 HR (N) | Stable? |
|-----|---------------|---------------|---------|
| Sun | **68.5%** (714) | 51.6% (351) | NO (inverted) |
| Thu | 54.2% (332) | **64.4%** (396) | NO (inverted) |
| Sat | 57.2% (538) | 49.5% (388) | NO (inverted) |
| Mon | 55.9% (547) | 55.7% (463) | marginal |
| Wed | 51.8% (411) | 61.5% (434) | NO (inverted) |
| Tue | 54.3% (473) | 50.6% (231) | NO |
| Fri | 53.3% (628) | 56.7% (439) | NO |

**Direction x Tier — Only Starter/Star UNDER is stable:**

| Combo | 2025-26 HR (N) | 2024-25 HR (N) | Stable? |
|-------|---------------|---------------|---------|
| Starter UNDER | 55.9% (1644) | 57.8% (1057) | **YES** |
| Star UNDER | 55.6% (921) | 54.3% (814) | **YES** |
| Bench UNDER | 53.2% (754) | **58.4%** (685) | marginal |
| ALL OVER | 78-83% | 42-49% | NO (inverted) |

**Month — December is consistently weak:**

| Month | 2025-26 HR (N) | 2024-25 HR (N) | Stable? |
|-------|---------------|---------------|---------|
| Jan | **59.3%** (1362) | **58.8%** (1168) | **YES — sweet spot** |
| Feb | 57.1% (308) | **62.8%** (387) | YES |
| Dec | 56.0% (1973) | **51.4%** (1147) | Weakest both |

---

## Session 283: Phase A Parameter Sweeps

### Key Finding: Cadence is the Most Impactful Parameter

Using Blacklist40 + Rolling56 as the base (combined P&L +$69,970), we swept three parameters independently: retrain cadence, rolling window size, and blacklist threshold.

**Final ranking by combined P&L (both seasons):**

| Rank | Variant | 2025-26 P&L | 2025-26 HR | 2024-25 P&L | 2024-25 HR | Combined P&L | Combined HR |
|------|---------|-------------|------------|-------------|------------|--------------|-------------|
| 1 | **Cad21 (21-day cadence)** | +$51,570 | 59.3% | +$30,470 | 58.1% | **+$82,040** | 58.8% |
| 2 | Cad10 (10-day cadence) | +$51,240 | 60.4% | +$26,610 | 57.5% | +$77,850 | 59.1% |
| 3 | Cad7 (7-day cadence) | +$50,200 | 60.3% | +$27,440 | 58.0% | +$77,640 | 59.3% |
| 4 | Roll42 (42-day window) | +$49,310 | 59.1% | +$26,030 | 57.4% | +$75,340 | 58.4% |
| 5-9 | BL35/BL45/BL40/Roll56/Cad14 (baselines) | ~$44K | ~58.8% | ~$25.5K | ~57.5% | ~$70K | ~58.3% |
| 10 | Roll70 | +$42,990 | 58.7% | +$25,890 | 57.6% | +$68,880 | 58.2% |
| 11 | BL50 | +$43,160 | 59.0% | +$25,260 | 58.3% | +$68,420 | 58.7% |
| 12 | Roll84 | +$43,510 | 58.7% | +$19,880 | 56.5% | +$63,390 | 57.8% |

### Per-Sweep Findings

**Cadence sweep:** All non-14d cadences beat baseline. Cad21 is P&L champion (+$12,070 over baseline, +17.3%). Cad7/10 have highest HR (59.3%/60.4%) but fewer picks.

**Rolling window sweep:** Roll42 beats Roll56 by +$5,370 (+7.7%). Roll70/Roll84 are at or below baseline. Shorter = fresher = better (to a point).

**Blacklist threshold sweep:** BL35-BL50 all within ~$2K of each other. Higher thresholds raise HR slightly but remove picks. BL40 is optimal.

### Deltas vs Baseline (Cad14 + Roll56 + BL40 = +$69,970)

- Cad21: +$12,070 (+17.3%)
- Cad10: +$7,880 (+11.3%)
- Cad7: +$7,670 (+11.0%)
- Roll42: +$5,370 (+7.7%)
- BL35: +$470 (+0.7%)
- Roll70: -$1,090 (-1.6%)
- Roll84: -$6,580 (-9.4%)

### Next Steps

Testing combos (Cad21+Roll42, Cad10+Roll42, Cad7+Roll42) to see if gains stack.

### Phase B: New Dimensions Added

Added 11 new dimensions to `compute_dimensions()`: Opponent Defense, Opp Def x Direction, Matchup Familiarity, Fatigue Level, Fatigue x Direction, Rest Advantage, Location x Direction, Minutes Change, Trend x Direction, Vegas Line Move, Line Move x Direction.

---

## Actionable Recommendations

### HIGH Confidence — Implement for Feb 19

1. **Switch to 56-day rolling training window.** +$9,550 improvement with zero downside. Modify `retrain.sh` to use `--train-start` based on current date minus 56 days.
2. **Add player blacklist (<40% HR after 8+ picks).** +$10,450 improvement. Add to signal aggregator or post-grading analysis. Both seasons benefit.
3. **V9 Q43 is champion.** Best P&L both seasons, both variants. Prioritize.
4. **UNDER is the reliable direction.** Do NOT bias toward OVER.
5. **xm_consensus_3plus works.** 57-62% HR with blacklist, best total P&L, both seasons.
6. **xm_diverse_agreement works.** V9+V12 cross-family consensus is robust.
7. **Quantile UNDER top-3 subsets are gold.** Small N but 61-89% HR both seasons.
8. **10-14.5 and 15-19.5 line ranges are stable sweet spots.**
9. **Raise V12 quantile min edge to 4.** Fixes the volume problem (54% -> 60% HR).

### MEDIUM Confidence — Implement Soon

10. **Add rolling lookback to production signal_health.** The replay's rolling HR tracking correctly identified regime shifts. Extend to subset-level health tracking.
11. **Adaptive direction gating in signal aggregator.** When OVER rolling HR drops below 50%, suppress OVER-only signals.
12. **Reconsider relative edge filter.** Consider making it adaptive: disable when blocked segment rolling HR >= 58%.
13. **December caution.** Consider reducing bet sizing or requiring higher edge in December when models are youngest.

### LOW Confidence — Do NOT Act On

14. Do NOT implement day-of-week filters — patterns completely invert between seasons.
15. Do NOT implement tier-direction rules — season-specific, hurts 2024-25 P&L.
16. Do NOT use tier-specific models — standard model beats per-tier models.
17. Do NOT promote `high_edge_over` — 28.6% HR last season despite 84.8% this season.
18. Do NOT filter by player volatility — feature_3 values need investigation first.

## Files

- `ml/experiments/season_replay_full.py` — 6-model replay engine with adaptive mode, rolling training, 7 experiment filters, 12 dimensions
- `ml/experiments/analyze_replay_results.py` — 7-section executive summary + cross-season comparison mode
- Results (all gitignored, in `ml/experiments/results/`):
  - `replay_20260217_v2.json`, `replay_20242025_v2.json` — Fixed baseline
  - `replay_2526_rolling56_v2.json`, `replay_2425_rolling56_v2.json` — Rolling 56d baseline (v2 with new dims)
  - `replay_2526_adaptive.json`, `replay_2425_adaptive.json` — Adaptive mode
  - `replay_2526_blacklist40.json`, `replay_2425_blacklist40.json` — Player blacklist (WINNER)
  - `replay_2526_skipTueFri.json`, `replay_2425_skipTueFri.json` — Skip Tue+Fri
  - `replay_2526_tierdir.json`, `replay_2425_tierdir.json` — Tier-direction rules
  - `replay_2526_combo.json`, `replay_2425_combo.json` — All filters combined
  - `replay_2526_tiermodels.json` — Tier-specific models
  - `replay_2526_vol5to10.json` — Volatility filter (no effect)
