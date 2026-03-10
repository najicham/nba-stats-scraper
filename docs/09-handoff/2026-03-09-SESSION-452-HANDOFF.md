# Session 452 Handoff — Multi-Season Cross-Validation & Strategy Optimization

*Date: 2026-03-09*

## What Was Done

### 1. Completed Multi-Season Data Backfill
Finished PGS (pitcher_game_summary) backfill for 2022 and 2023:
- PGS 2022 had DIED (503 error at July 30) — restarted from July 31, completed to Oct 5
- PGS 2023 was still running from Session 449, completed to Oct 1
- All 4 Statcast backfills already COMPLETE from Session 449

**Final PGS counts:**
| Season | Dates | Rows |
|--------|-------|------|
| 2022 | 179 | 5,166 |
| 2023 | 182 | 5,118 |
| 2024 | 183 | 5,085 |
| 2025 | 182 | 5,081 |

### 2. Fixed season_replay.py for Cross-Season Testing
- **Fixed hardcoded `pgs.game_date >= '2024-01-01'`** — now dynamically computed from start_date minus training window
- Changed query from `"""` to `f"""` to interpolate earliest_date
- Added `--no-blacklist` flag (later inverted to `--use-blacklist` with blacklist OFF by default)

### 3. Multi-Season Replay — V1 Baseline (No Blacklist)
Ran all 4 seasons without blacklist. **The core model IS robust — profitable every season:**

| Season | BB HR | Record | P&L | Ultra HR (N) | ROI |
|--------|-------|--------|-----|-------------|-----|
| 2022 | 61.2% | 260-165 | +121u | 58.4% (154) | 28.5% |
| 2023 | 56.8% | 166-126 | +47u | 57.4% (47) | 16.1% |
| 2024 | 61.6% | 298-186 | +166u | 70.1% (134) | 34.3% |
| 2025 | 65.5% | 300-158 | +183u | 81.5% (65) | 39.9% |

**Combined: p = 1.1e-14 (z=7.62), 95% CI [59.4%, 64.0%]**

### 4. Agent-Reviewed Changes (V2 Config — Session 452 Redesign)
Three agents reviewed proposed changes. Approved and implemented:

**Changes to `scripts/mlb/training/season_replay.py`:**
1. **Removed `half_line` from Ultra** — vacuous (all K lines are x.5)
2. **Lowered Ultra edge floor from 1.1 to 0.5** — edge floor was removing best picks in 2022-2023
3. **Added `TRACKING_ONLY_SIGNALS`** — `k_trending_over` demoted (50-56% HR, coin flip)
4. **Blacklist OFF by default** — `--use-blacklist` to opt in (static list is 96% season-specific)
5. **Rescued picks cannot be Ultra** — safety guard against lowest-confidence picks getting 2u
6. **Fixed `check_ultra` blacklist inconsistency** — now respects `--use-blacklist` flag

**V2 Results (all 4 seasons, blacklist off):**
| Season | BB HR | P&L | Ultra HR (N) | Vig-Adj P&L |
|--------|-------|-----|-------------|-------------|
| 2022 | 60.0% | +180u | 59.6% (356) | +143u |
| 2023 | 57.3% | +90u | 64.0% (150) | +71u |
| 2024 | 58.8% | +174u | 60.2% (322) | +136u |
| 2025 | 63.6% | +358u | 66.9% (453) | +316u |

**Total vig-adjusted improvement: +225u across all 4 seasons vs V1.**

### 5. Exhaustive Experiment Battery (5 Parallel Agents)

#### UNDER Bets
- **Result: ZERO UNDER picks survive** in any season
- `UNDER_MIN_SIGNALS = 3` but only 3 UNDER signals exist — effectively impossible
- Raw UNDER at high edge: inconsistent (63.6% in 2023, 51.4% in 2025)

#### Training Windows (tested on 2023 + 2024)
| Config | 2023 HR / P&L | 2024 HR / P&L | Avg HR |
|--------|---------------|---------------|--------|
| 60d / 14d | 56.3% / +75u | 62.4% / +237u | 59.3% |
| 120d / 14d (current) | 57.3% / +90u | 58.8% / +174u | 58.1% |
| **120d / 7d retrain** | **59.2% / +97u** | **62.2% / +205u** | **60.7%** |

**7-day retrain is the clear winner: +2.6pp avg HR.**

#### Picks Per Day
- 1/day: 62.1% HR, 26.4% ROI — does NOT reach 70%
- 3/day: 59.8% HR, 22.9% ROI (current)
- 5/day: 59.4% HR, 21.9% ROI — ROI nearly flat, 67% more profit
- **Ranking function is weak** — top-1 barely better than top-5

#### Feature Importance Stability
- `f32_line_level` is #1 every season (15-19%)
- 10 core stable features (CV < 0.3): line_level, csw_pct, fip, k_avg_vs_line, z_contact_pct, swstr_pct, bp_projection, ip_avg, o_swing_pct, whip
- **Structural break 2023→2024** — Statcast/ballpark features went from 0% to 3-5%
- Pruning candidates: `f25_is_day_game`, `f66_vs_opp_games`

#### Home vs Away
- Home OVER: 62.6% (N=811), Away OVER: 57.4% (N=495), gap +5.3pp
- Home produces **84% of all profit**
- **Away at edge >= 1.25 converges with home** (63.6% vs 66.0%)
- Away rescued picks: 51.0% (coin flip) — should block
- Projection signal adds ~6pp for home but NOTHING for away

### 6. Strategic Agent Reviews (2 Agents)

#### Strategist Recommendations
- Deploy: 120d/7d retrain, 5/day, away edge 1.25, dynamic blacklist
- Expected 2026: 60-62% HR, $6,500-9,500/year at $100 units
- Top experiment: 60d/7d retrain combo

#### Contrarian Blind Spots Found
1. **P&L math doesn't use actual odds** — `over_odds` loaded but ignored. At -110, profits are ~40-60% of reported
2. **Push handling is asymmetric** — pushes count as UNDER wins in backtest
3. **Model is basically "K average vs line"** — CatBoost adds ~3pp over naive heuristic
4. **Survivorship bias** — trains only on pitchers lasting 3+ IP
5. **April cold start** — first model uses June-Sep 2025 data for April 2026 games
6. **Lineup-specific K rates already computed** (`lineup_k_analysis_processor.py`) but NOT in feature vector

## Results Location
All replay results in `results/mlb_season_replay_cross/`:
- `{season}_no_blacklist/` — V1 baseline (no blacklist)
- `{season}_with_blacklist/` — V1 with static blacklist
- `{season}_v2/` — V2 config (Session 452 changes)
- `{season}_edge050/`, `{season}_edge100/` — edge floor experiments
- `{season}_top1/`, `{season}_top2/`, `{season}_top5/` — picks/day experiments
- `{season}_tw60/`, `{season}_tw90/`, `{season}_tw180/`, `{season}_rt7/` — training window experiments
- `{season}_under/` — UNDER enabled experiments

## What's Next (Priority Order)

### P0: Fix P&L to Use Actual Odds (CRITICAL)
The `over_odds` column is already loaded in the replay SQL but the P&L line uses flat `+1/-1`. Must fix to `+stake * (100/abs(odds))` for negative odds. Re-run V2 replays with real odds to get true profitability.

```python
# In run_replay(), change:
pnl = stake if correct else -stake
# To:
if correct:
    odds = pick.get('over_odds', -110)
    pnl = stake * (100 / abs(odds)) if odds < 0 else stake * (odds / 100)
else:
    pnl = -stake
```

### P1: Run 60d / 7d Retrain Experiment
```bash
PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2023-05-01 --end-date 2023-09-28 --training-window 60 --retrain-interval 7 \
    --output-dir results/mlb_season_replay_cross/2023_tw60_rt7/

PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2024-05-01 --end-date 2024-09-28 --training-window 60 --retrain-interval 7 \
    --output-dir results/mlb_season_replay_cross/2024_tw60_rt7/
```

### P2: Implement Away Edge Floor 1.25 + Block Away Rescue
Add to `apply_negative_filters()`:
```python
# Away pitcher: higher edge floor
if recommendation == 'OVER' and not is_home and edge < 1.25:
    return 'away_low_edge'
# Block away rescued picks
if recommendation == 'OVER' and not is_home and was_rescued:
    return 'away_rescue_blocked'
```

### P3: Add Lineup K Rate Feature
Wire `lineup_k_analysis_processor.py`'s `bottom_up_expected_k` into the training SQL and feature vector. This is an orthogonal signal already computed but unused.

### P4: Switch to 5 Picks/Day
Change `MAX_PICKS_PER_DAY = 5` and re-run full 4-season validation.

### P5: Umpire Zone Features
Source umpire assignment data and compute umpire K-rate vs league average. Orthogonal signal the market likely underweights.

### P6: Plan April Cold Start
- Reduce stakes weeks 1-3 of season (50% unit size)
- Consider using 2025 full-season model for first 2 weeks before walk-forward kicks in

## Key Decision Points
1. **After P0 (vig fix):** If vig-adjusted worst season (2023) drops below +$1,000 at $100 units, reconsider $50 units or require 60%+ HR paper trade before going live
2. **After P1 (60d/7d):** If it beats 120d/7d, deploy 60d/7d. If not, deploy 120d/7d
3. **Opening Day config lock:** Must be finalized by March 25 (2 days before March 27 Opening Day)

## Files Modified This Session
| File | Change |
|------|--------|
| `scripts/mlb/training/season_replay.py` | Cross-season support, V2 Ultra redesign, blacklist flag inversion, tracking signals |

## No Code Was Pushed
All changes are local only. The replay script changes should be committed before the next session.
