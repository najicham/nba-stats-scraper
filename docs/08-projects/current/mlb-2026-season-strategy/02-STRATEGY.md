# MLB 2026 — The Strategy

## Model

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Algorithm | CatBoost Regressor | +5pp over classifier. Real K-unit edges. |
| Hyperparameters | Defaults (depth 5, lr 0.015, 500 iters) | Sweep confirmed: defaults optimal |
| Training window | 120 days | Sweet spot (90-365d within noise) |
| Retrain cadence | Fixed 14-day | 7d = noise, 21d = -1.7pp cliff |
| Features | 41 (remove 5 dead/dupes for 36) | Top 5 drive 90%+ of importance |
| Loss function | RMSE | MAE, Quantile, Huber all worse |

## 2-Tier Pick System

### Tier 1: Best Bets

```
Criteria:
  - Direction: OVER only
  - Line type: half-line only (X.5) — whole-number lines blocked
  - Pitcher: not on blacklist (18 pitchers)
  - Edge: 0.75K - 2.0K
  - Ranking: pure edge (highest first)
  - Selection: top-3 per day
  - Staking: 1 unit per pick
```

**Walk-forward: 64.6% HR, N=746, 2.4 picks/day, +174u, 23.3% ROI**

### Tier 2: Ultra

```
Criteria (all Best Bet criteria PLUS):
  - Edge: >= 1.0K (tighter floor)
  - Location: home pitcher
  - Projection: projection_value > strikeouts_line
  - Selection: all qualifying (no daily cap)
  - Staking: 2 units per pick
```

**Walk-forward: 72.9% HR, N=221, 1.4 picks/day, +173u at 2u, 39.1% ROI**

88% of Ultra picks are already in BB top-3. Ultra is a staking overlay, not a separate pick list.

### Combined Portfolio

```
Daily flow:
  1. Generate all OVER predictions from regressor
  2. Filter: half-line only, not blacklisted, edge 0.75-2.0
  3. Rank by edge, take top-3 → Best Bets (1u each)
  4. Tag any BB pick that is also home + proj agrees + edge >= 1.0 → Ultra (2u instead of 1u)
  5. Ultra picks NOT in top-3 still get published and staked at 2u

Expected: ~3-4 picks/day, ~270u/season profit, 27.3% ROI
```

## Negative Filters (6 active)

| # | Filter | Mechanism | Evidence |
|---|--------|-----------|----------|
| 1 | `whole_line_over` | Block OVER on X.0 lines | 49% vs 58.6% HR, p<0.001, 17.3% push rate |
| 2 | `pitcher_blacklist` | Block 18 named pitchers | 37.5% HR blocked, +3.1pp lift |
| 3 | `overconfidence_cap` | Block edge > 2.0 | 42.9% HR at extreme edges |
| 4 | `bullpen_game_skip` | Block openers/bullpen | IP avg < 4.0 |
| 5 | `il_return_skip` | Block first IL start | Unpredictable pitch count |
| 6 | `insufficient_data_skip` | Block < 3 starts | Not enough history |

### Pitcher Blacklist (18)

Kept: tanner_bibee, mitchell_parker, casey_mize, mitch_keller

Added (Session 443): logan_webb (37.5%), jose_berrios (38.1%), logan_gilbert (38.5%), logan_allen (36.2%), jake_irvin (33.3%), george_kirby (40%), mackenzie_gore (40.9%), bailey_ober (40%), zach_eflin (30%), ryne_nelson (30.8%), jameson_taillon (33.3%), ryan_feltner (33.3%), luis_severino (42.1%), randy_vasquez (27.8%)

Removed (now profitable): freddy_peralta, tyler_glasnow, paul_skenes, hunter_greene, yusei_kikuchi, jose_soriano

**Review cadence:** Re-evaluate blacklist monthly after 50+ picks per pitcher.

## Observation Filters (2 — log only, don't block)

| Filter | Status | Reason |
|--------|--------|--------|
| `bad_opponent_over_obs` | Observation | Cross-season r=-0.29. KC improved 40%→51%. |
| `bad_venue_over_obs` | Observation | Confounded with team (eta²=0.006, p=0.13). |

## Active Signals (14)

8 original + 3 walk-forward validated + 3 regressor-transition. Used for signal count gate (min 2 real signals for OVER).

## UNDER Strategy (Deferred)

Enable after 2-3 weeks of live OVER data confirms the system is working.

```
UNDER gate:
  - edge >= 1.5K
  - projection_value < strikeouts_line
  - cold_form (k_avg_last_5 - line <= -1.0) OR high_line (line >= 6.0)
  - Max 1 per day
  - Staking: 1u
```

Walk-forward: 62.6% HR (N=115). Mixed portfolio (3 OVER + 1 UNDER) improves both HR and ROI.

## What We Explicitly Rejected

See [05-DEAD-ENDS.md](05-DEAD-ENDS.md) for the full list. Key rejections:

- Composite scoring (fails cross-season)
- Ensemble models (CatBoost solo wins)
- Static opponent/venue filters (anti-correlated cross-season)
- Seasonal phases (unified is better)
- Hyperparameter tuning (defaults optimal)
- Day-of-week filters (noise)
- Derived features (all noise)
