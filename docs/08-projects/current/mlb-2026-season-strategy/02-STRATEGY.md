# MLB 2026 — The Strategy

*Updated Session 444: Full season replay validated (Apr-Sep 2025)*

## Model

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Algorithm | CatBoost Regressor | +5pp over classifier. Real K-unit edges. |
| Hyperparameters | Defaults (depth 5, lr 0.015, 500 iters) | Sweep confirmed: defaults optimal |
| Training window | 120 days | Sweet spot (90-365d within noise) |
| Retrain cadence | Fixed 14-day | 7d = noise, 21d = -1.7pp cliff |
| Features | **36** (5 dead/dupes removed Session 444) | Top 5 drive 90%+ of importance |
| Loss function | RMSE | MAE, Quantile, Huber all worse |

**Dead features removed (Session 444):** f17_month_of_season, f18_days_into_season, f24_is_postseason (zero importance), f67_season_starts (duplicate f08), f69_recent_workload_ratio (duplicate f21/6.0). A/B confirmed: cleaned set matches or beats full set.

## 2-Tier Pick System

### Tier 1: Best Bets

```
Criteria:
  - Direction: OVER only
  - Line type: half-line only (X.5) — whole-number lines blocked
  - Pitcher: not on blacklist (23 pitchers)
  - Edge: 0.75K - 2.0K
  - Signal rescue: opponent_k_prone, ballpark_k_boost (swstr_surge REMOVED)
  - Signal gate: >= 2 real signals
  - Ranking: pure edge (highest first)
  - Selection: top-3 per day
  - Staking: 1 unit per pick
```

**Season replay: 63.4% HR, N=470, 2.7 picks/day, +170u, 36.2% ROI**

### Tier 2: Ultra

```
Criteria (all Best Bet criteria PLUS):
  - Edge: >= 1.1K (Session 444: raised from 1.0, edge 1.0-1.1 was 63% HR noise)
  - Location: home pitcher
  - Projection: projection_value > strikeouts_line
  - Selection: all qualifying (no daily cap)
  - Staking: 2 units per pick
```

**Season replay: 81.4% HR, N=70, 0.4/day, +88u at 2u**

Ultra picks NOT in top-3 are still published and staked at 2u.

### Combined Portfolio

```
Daily flow:
  1. Generate all OVER predictions from regressor
  2. Filter: half-line only, not blacklisted, edge 0.75-2.0
  3. Check signal rescue (opponent_k_prone, ballpark_k_boost)
  4. Evaluate signals, gate at 2+ real signals
  5. Rank by edge, take top-3 → Best Bets (1u each)
  6. Tag any pick that is also home + proj agrees + edge >= 1.1 → Ultra (2u instead of 1u)
  7. Ultra picks NOT in top-3 still get published and staked at 2u

Season replay: 2.7 picks/day, +170u season, 36.2% ROI, 64% winning days
```

## Negative Filters (6 active)

| # | Filter | Mechanism | Evidence |
|---|--------|-----------|----------|
| 1 | `whole_line_over` | Block OVER on X.0 lines | 49% vs 58.6% HR, p<0.001, 17.3% push rate |
| 2 | `pitcher_blacklist` | Block **23** named pitchers | +3.1pp lift from blocking <45% HR pitchers |
| 3 | `overconfidence_cap` | Block edge > 2.0 | 42.9% HR at extreme edges |
| 4 | `bullpen_game_skip` | Block openers/bullpen | IP avg < 4.0 |
| 5 | `il_return_skip` | Block first IL start | Unpredictable pitch count |
| 6 | `insufficient_data_skip` | Block < 3 starts | Not enough history |

### Pitcher Blacklist (23)

**Original 4:** tanner_bibee, mitchell_parker, casey_mize, mitch_keller

**Session 443 additions (14):** logan_webb (37.5%), jose_berrios (38.1%), logan_gilbert (38.5%), logan_allen (36.2%), jake_irvin (33.3%), george_kirby (40%), mackenzie_gore (40.9%), bailey_ober (40%), zach_eflin (30%), ryne_nelson (30.8%), jameson_taillon (33.3%), ryan_feltner (33.3%), luis_severino (42.1%), randy_vasquez (27.8%)

**Session 444 additions (5):** adrian_houser (0%), stephen_kolek (0%), dean_kremer (25%), michael_mcgreevy (25%), tyler_mahle (25%)

**Removed (now profitable):** freddy_peralta, tyler_glasnow, paul_skenes, hunter_greene, yusei_kikuchi, jose_soriano

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
