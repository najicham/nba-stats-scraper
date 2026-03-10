# Session 455 Handoff — MLB Vig-Adjusted P&L, Retrain Optimization, Away Filters

*Date: 2026-03-09*

## What Was Done

### 1. P0: Fixed P&L to Use Actual Odds (CRITICAL)
Added `compute_pnl()` — real American odds payouts per pick. The `over_odds` column was loaded but ignored.

**The juice is devastating:** Median odds are **-130 to -138**. Only 20% of picks at standard -110.

| Season | HR | Flat P&L | Vig P&L | ROI | Vig/Flat |
|--------|-----|----------|---------|-----|----------|
| 2022 | 59.5% | +169u | +36u | 3.8% | 21% |
| 2023 | 57.3% | +90u | +27u | 5.6% | 30% |
| 2024 | 58.8% | +174u | +43u | 4.6% | 25% |
| 2025 | 63.6% | +358u | +193u | 16.0% | 54% |

### 2. P1: Retrain Config (all vig-adjusted, 4 seasons)
120d/7d was "clear winner" on 2023+2024 only. Full 4-season test reverses this:

| Config | 2022 | 2023 | 2024 | 2025 | Total P&L | ROI |
|--------|------|------|------|------|-----------|-----|
| **120d/14d** | 59.5%/+36u | 57.3%/+27u | 58.8%/+43u | 63.6%/+193u | **+299u** | **8.4%** |
| 120d/7d | 58.5%/+13u | 59.2%/+37u | 62.2%/+78u | 59.7%/+108u | +235u | 6.8% |
| 60d/7d | — | 57.9%/+23u | 61.8%/+90u | — | — | — |

**120d/14d wins.** 7d retraining adds instability in strong seasons (2025: 63.6%→59.7%).

### 3. P2: Away Pitcher Fixes
Added `--away-edge-floor 1.25 --block-away-rescue`:
- Away OVER picks need edge >= 1.25 (vs 0.75 default)
- Away rescued picks blocked (coin-flip at 51%)

### 4. P3: Final Combined Config (V3 FINAL)

| Season | HR | P&L (vig) | ROI | Ultra HR (N) | $ at $100/u |
|--------|-----|-----------|-----|-------------|-------------|
| 2022 | 57.3% | +18u | 2.4% | 57.9% (366) | +$1,800 |
| 2023 | 60.4% | +44u | 10.3% | 64.0% (150) | +$4,400 |
| 2024 | 61.8% | +98u | 9.8% | 60.2% (322) | +$9,800 |
| 2025 | 64.3% | +217u | 12.1% | 66.9% (453) | +$21,700 |
| **TOTAL** | **61.5%** | **+377u** | **10.2%** | | **+$37,700** |

**Average per season: ~$9,400. Worst case (2022) still +$1,800.**

### 5. Signal & Filter Deep Dive (2,402 picks, 4 seasons)

**Signal quality:**
| Signal | HR | P&L | N | Status |
|--------|-----|-----|---|--------|
| `recent_k_above_line` | 62.6% | +290u | 1732 | Strong |
| `high_edge` | 62.9% | +243u | 1289 | Strong |
| `regressor_proj_agrees` | 62.3% | +316u | 1827 | Strong |
| `opponent_k_prone` | 62.6% | +164u | 1024 | Strong |
| `ballpark_k_boost` | 63.7% | +56u | 336 | Strong |
| `long_rest_over` | 55.4% | -36u | 258 | **DEMOTED** |
| `k_trending_over` | 55.6% | -18u | 489 | Tracking-only |

**Key findings:**
- rsc=3-4 is sweet spot (63-64% HR). rsc=6+ loses money.
- Rescued picks: 63.3% HR (+73u) — strong after away filter
- -150 to -130 odds: profit center (+117u)
- Edge 0.75-1.00: weakest bucket (57.1% HR)
- Rank 5 still profitable (58.4%/+32u) — confirms 5/day

## V3 FINAL Deploy Config

```
Training: 120d window, 14d retrains
Edge floor: 0.75 K (home), 1.25 K (away)
Away rescue: BLOCKED
Volume: 5 picks/day
Signals: long_rest_over → TRACKING_ONLY
Ultra: Home + Projection agrees + edge >= 0.5 + not rescued
Staking: 1u BB, 2u Ultra
Blacklist: OFF
```

## Results Location
All in `results/mlb_season_replay_cross/`:
- `{season}_v2_vig/` — V2 with vig P&L (120d/14d)
- `{season}_tw120_rt7_vig/` — 120d/7d experiment
- `{season}_tw60_rt7/` — 60d/7d experiment
- `{season}_v2_away/` — 120d/14d + away, 3/day
- `{season}_v3_final/` — Final config, 5/day
- `{season}_v3_final_v2/` — Final + long_rest demoted

## What's Next

### Before Opening Day (March 25)
1. **Wire V3 config into production** — away edge floor, away rescue block, 5/day, long_rest tracking
2. **Paper trade weeks 1-2** — 50% unit size for April cold start
3. **Odds-aware ranking** — weight by EV instead of raw edge

### Post-Launch
4. **Dynamic blacklist** — walk-forward pitcher suppression (< 45% HR at N >= 10)
5. **Lineup K rate feature** — already computed, not in feature vector
6. **Umpire zone features** — orthogonal signal
7. **Max juice filter** — block -160+ odds? Cross-season inconsistent, needs study

## Files Modified
| File | Change |
|------|--------|
| `scripts/mlb/training/season_replay.py` | `compute_pnl()`, away flags, `long_rest_over` → TRACKING, home/away reporting, odds in picks, ROI on staked |
