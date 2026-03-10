# Session 465 Start Prompt

**Date:** 2026-03-10
**Previous:** Session 464 (MLB L2=10+D4 deploy + signal expansion)

## Current State

Everything is deployed and committed. Clean working tree (no uncommitted changes).

### MLB System Status
- **Model:** `catboost_mlb_v2_regressor_40f_20250928.cbm` — depth=4, l2=10, 69.2% HR at edge >= 0.75
- **Worker:** `mlb-prediction-worker` rev 00018-rzf, deployed 2026-03-10, serving 100% traffic
- **Signals:** 18 active + 22 shadow + 6 filters + 2 observation = 48 total
- **4-season replay:** 63.4% HR, +470.7u P&L, 12.8% ROI (4/4 seasons profitable)
- **MLB season opens:** March 27 (17 days away)

### Recent Sessions (460-464) — MLB Focus
| Session | What |
|---------|------|
| 460 | Hyperparameter sweep — L2=10+D4 winner (+14.9% over baseline) |
| 461 | BB simulator 5-season cross-validation, NBA signal findings |
| 462 | NBA cold shooting filters promoted, signal inventory update |
| 463 | 3 MLB signals promoted (high_csw, elite_peripherals, pitch_efficiency_depth), 11 shadows added |
| 464 | L2=10+D4 deployed, 2 more promoted (pitcher_on_roll, day_game), 10 shadows added, model trained+deployed |

## Priority Tasks

### P0 — Paper Trade Readiness (Before March 27)
- [ ] Verify MLB worker loads new model correctly (check logs for signal count)
- [ ] Test end-to-end: supplemental loader → signals → exporter → picks
- [ ] Confirm game context data (moneyline, game total) flows through

### P1 — Experiments to Run
- [ ] **Replay C — Dynamic blacklist:** Test walk-forward blacklist vs static 28 pitchers
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/mlb/training/season_replay.py \
    --start-date 2025-03-27 --end-date 2025-09-28 \
    --output-dir results/mlb_season_replay/2025_s465_dynamic_bl/ \
    --max-picks 5 --away-edge-floor 1.25 --block-away-rescue \
    --dynamic-blacklist --bl-min-n 10 --bl-max-hr 0.45
  ```
- [ ] **Replay D — Away edge floor sensitivity:** Test 1.0 vs 1.25 vs 1.5
- [ ] **RSC gate tuning:** RSC=2 is 57.8% HR (marginal). Consider raising min RSC from 2 to 3

### P2 — New Signal Research
**Highest priority (data already in features):**
1. **chase_rate_over** — Already implemented as shadow. O-Swing% >= 35% (f70, 4.14% feature importance). Needs production data to validate.
2. **contact_specialist_under** — Already implemented as shadow. Z-Contact% >= 85% (f71). UNDER signals need UNDER enabled.
3. **XFIP regression** — FanGraphs xFIP available. When ERA >> xFIP, K rate reverts to true talent.
4. **Whiff rate surge** — Statcast whiff_pct (differentiated from SwStr%). Not currently in features.

**Promising shadows to watch (from 4-season replay):**
| Signal | Total HR | N | Notes |
|--------|---------|---|-------|
| k_rate_bounce_over | 76.1% | 46 | Exciting but N too low. Need 30+ more data points |
| low_era_high_k_combo_over | 61.6% | 450 | Good total but 2023 collapsed to 47%. Inconsistent |
| pitcher_on_roll_over | 63.2% | 1,473 | **Already promoted** |
| day_game_shadow_over | 61.6% | 895 | **Already promoted** |

**Signal pair combos worth exploring as combo signals:**
| Pair | HR | N |
|------|-----|---|
| day_game + high_csw | 73.3% | 131 |
| day_game + elite_peripherals | 72.6% | 190 |
| high_csw + low_era_high_k | 71.0% | 169 |

### P3 — Infrastructure
- [ ] Deploy catcher framing scraper (`scrapers/mlb/external/mlb_catcher_framing.py`) — run weekly
- [ ] Create BQ table: `schemas/bigquery/mlb_raw/catcher_framing_tables.sql`
- [ ] Add humidity/wind data to supplemental loader for humidity_over signal
- [ ] Historical umpire assignment data for umpire_csw_combo_over in replays

## Key Files
| File | Purpose |
|------|---------|
| `ml/signals/mlb/signals.py` | All signal classes (1,800+ lines) |
| `ml/signals/mlb/registry.py` | Signal registration |
| `ml/signals/mlb/best_bets_exporter.py` | BB pipeline + pick angles |
| `scripts/mlb/training/season_replay.py` | Walk-forward replay simulator |
| `scripts/mlb/training/train_regressor_v2.py` | Model training script |
| `predictions/mlb/supplemental_loader.py` | Umpire, weather, game context data |
| `docs/08-projects/current/mlb-session-464/EXPERIMENT-PLAN.md` | Full experiment results |

## What NOT to Do
- Don't change the 18 active signals without replay validation
- Don't relax the edge floor (0.75 K) — validated sweet spot
- Don't add features to the model — V12_noveg pattern: adding features hurts
- Don't enable UNDER in production yet — UNDER signals are accumulating shadow data
- Don't retrain with window < 56 days or retrain cadence > 7 days
