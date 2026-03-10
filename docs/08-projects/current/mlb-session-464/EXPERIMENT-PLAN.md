# Session 464 — MLB Experiment & Replay Plan

## Changes Made

### 1. Hyperparameter Update (L2=10+D4)
- `train_regressor_v2.py`: depth 5→4, l2_leaf_reg 3→10
- `season_replay.py`: defaults updated to match
- **Source:** Session 459 walk-forward sweep (+66.2u / +14.9% over baseline, 3/4 seasons)

### 2. Six New Shadow Signals Added
All use data already available in features — no new scrapers needed.

| Signal | Direction | Mechanism | Features Used |
|--------|-----------|-----------|---------------|
| `k_rate_reversion_under` | UNDER | K hot streak → regression | f00, f05, f04 |
| `k_rate_bounce_over` | OVER | K cold streak → bounce-back | f00, f05, f04 |
| `umpire_csw_combo_over` | OVER | K-friendly ump + high CSW | f19b + supplemental |
| `rest_workload_stress_under` | UNDER | Short rest × high workload | f20, f21 |
| `low_era_high_k_combo_over` | OVER | ERA < 3.0 + K/9 >= 8.5 | f06, f05 |
| `pitcher_on_roll_over` | OVER | K avg L3 AND L5 > line | f00, f01, line |

### 3. Files Modified
- `ml/signals/mlb/signals.py` — 6 new signal classes
- `ml/signals/mlb/registry.py` — Register new signals
- `ml/signals/mlb/best_bets_exporter.py` — Pick angles + tracking-only list
- `scripts/mlb/training/season_replay.py` — Signal evaluation + defaults
- `scripts/mlb/training/train_regressor_v2.py` — Hyperparameters

---

## Replay Commands

### Replay A: Combined Validation (L2=10+D4 + Promoted Signals)
Validate that L2=10+D4 hyperparams + 3 promoted signals (high_csw, elite_peripherals, pitch_efficiency_depth) work together across all 4 seasons.

```bash
# 2022 (earliest season)
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2022-04-07 --end-date 2022-10-05 \
  --output-dir results/mlb_season_replay/2022_s464_combined/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue

# 2023
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2023-03-30 --end-date 2023-10-01 \
  --output-dir results/mlb_season_replay/2023_s464_combined/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue

# 2024
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2024-03-28 --end-date 2024-09-29 \
  --output-dir results/mlb_season_replay/2024_s464_combined/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue

# 2025
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay/2025_s464_combined/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue
```

**Success criteria:** +15% P&L improvement over Session 459 baseline, 3/4 seasons positive.

### Replay B: Shadow Signal Evaluation
After Replay A completes, analyze the shadow signal fire rates and HR from the `best_bets_picks.csv` output. Each pick records all signal tags — filter by shadow signal presence.

**Signals with replay data (evaluate from Replay A output):**
- `k_rate_bounce_over` — fires when K avg L3 is 2+ below season expected
- `k_rate_reversion_under` — fires when K avg L3 is 2+ above season expected
- `low_era_high_k_combo_over` — fires when ERA < 3.0 + K/9 >= 8.5
- `pitcher_on_roll_over` — fires when both L3 and L5 K avg > line
- `rest_workload_stress_under` — fires when rest <= 5d AND games/30d >= 6

**Signals without replay data (production-only):**
- `umpire_csw_combo_over` — needs umpire_k_rate from supplemental

**Promotion criteria:** HR >= 60% + N >= 30 across 4 seasons → promote to active.

### Replay C: Blacklist Refresh
Check if all 28 blacklisted pitchers still warrant suppression with L2=10+D4 model.

```bash
# Run Replay A with --dynamic-blacklist instead of static
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay/2025_s464_dynamic_bl/ \
  --max-picks 5 --away-edge-floor 1.25 --block-away-rescue \
  --dynamic-blacklist --bl-min-n 10 --bl-max-hr 0.45
```

### Replay D: Away Edge Floor Sensitivity
Test if L2=10+D4's better generalization relaxes the away edge penalty.

```bash
# Away floor 1.0 (relaxed from 1.25)
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay/2025_s464_away_1.0/ \
  --max-picks 5 --away-edge-floor 1.0 --block-away-rescue

# Away floor 1.5 (tighter)
PYTHONPATH=. python scripts/mlb/training/season_replay.py \
  --start-date 2025-03-27 --end-date 2025-09-28 \
  --output-dir results/mlb_season_replay/2025_s464_away_1.5/ \
  --max-picks 5 --away-edge-floor 1.5 --block-away-rescue
```

---

## New Signal Hypotheses (Future Sessions)

### Highest Priority (data available, strong mechanism)
1. **Umpire-pitcher interaction** — need umpire assignments in historical data
2. **Bullpen usage correlation** — taxed_bullpen + ace = longer leash (need team bullpen IP in replay SQL)
3. **Wind/weather interaction** — wind direction at specific parks (Wrigley, Fenway)
4. **CLV for K props** — closing line value (need historical line snapshots)

### Medium Priority (need new data sources)
5. **Catcher framing** — Baseball Savant scraper built, needs BQ table + backfill
6. **Lineup stack K-rate** — per-lineup K% vs pitcher hand (need lineup data in analytics)
7. **First-inning K tendency** — some pitchers dominate first time through order (need PBP data)

### Lower Priority (weak mechanism or hard to validate)
8. **Conference/division familiarity** — divisional rematches might reduce K rate
9. **Age × rest interaction** — older pitchers may recover slower
10. **Park × weather interaction** — outdoor parks in cold weather

---

## 4-Season Replay Results

| Season | HR | Record | P&L | ROI |
|--------|-----|--------|-----|-----|
| 2022 | 60.9% | 336-216 | +62.1u | 6.6% |
| 2023 | 61.2% | 178-113 | +41.3u | 9.3% |
| 2024 | 60.8% | 474-305 | +113.2u | 10.4% |
| 2025 | 66.1% | 550-282 | +254.1u | 20.3% |
| **Total** | **63.4%** | **1538-916** | **+470.7u** | **12.8%** |

## Signal Pair Analysis (4 seasons, N=2,454)

### Top Combos (HR >= 67%, N >= 50)
| Pair | HR | N |
|------|-----|---|
| day_game + high_csw | 73.3% | 131 |
| day_game + elite_peripherals | 72.6% | 190 |
| high_csw + low_era_high_k | 71.0% | 169 |
| high_csw + regressor_proj | 69.3% | 238 |
| elite_peripherals + opponent_k_prone | 69.1% | 188 |
| low_era_high_k + regressor_proj | 68.6% | 283 |

### Real Signal Count vs HR
| RSC | HR | N |
|-----|-----|---|
| 2 | 57.8% | 249 |
| 3 | 60.5% | 570 |
| 4 | 64.4% | 725 |
| 5 | 63.1% | 567 |
| 6 | 66.4% | 253 |
| 8 | 73.3% | 30 |

Sweet spot is rsc=4-6 (63-66% HR). RSC=2 is marginal (57.8%).

## Signals Promoted (Session 464)
- **pitcher_on_roll_over**: 63.3% HR, N=1,473 — K avg L3 AND L5 > line
- **day_game_shadow_over**: 61.8% HR, N=895 — day game visibility effect

## Production Model Trained
- `catboost_mlb_v2_regressor_40f_20250928.cbm`
- Hyperparams: depth=4, lr=0.015, iters=500, l2=10
- Validation: 69.2% HR at edge >= 0.75 (N=188)
- Uploaded to GCS, MLB worker deployed

## Next Signal Opportunities (from research)

### Highest Priority (data available, strong mechanism)
1. **Chase rate OVER** — FanGraphs o_swing_pct >= 35% already in features (f70)
2. **Whiff rate surge** — Statcast whiff_pct last 3 vs season (differentiated from SwStr%)
3. **Humidity/wind interaction** — Weather data available, barrel difficulty signal
4. **XFIP regression** — Available in FanGraphs, identifies luck vs skill

### Medium Priority
5. **Umpire consistency** — Available but unused dimension of umpire data
6. **Contact specialist UNDER** — z_contact >= 85% from FanGraphs (f71)
7. **Dynamic blacklist** — Walk-forward pitcher suppression vs static 28 pitchers

## Deployment Timeline

| Step | Action | Status |
|------|--------|--------|
| 1 | Run Replay A (4 seasons) | DONE |
| 2 | Analyze shadow signal HR from replays | DONE |
| 3 | Promote winners to active | DONE (2 promoted) |
| 4 | Train fresh model with L2=10+D4 | DONE (69.2% HR) |
| 5 | Upload to GCS + deploy MLB worker | DONE |
| 6 | Paper trade April 1-14 | Opening day |
| 7 | Live bets April 15+ | After paper trade validates |
