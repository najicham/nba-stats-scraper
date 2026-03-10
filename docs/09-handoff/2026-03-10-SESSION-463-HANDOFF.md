# Session 463 Handoff — MLB Signal Expansion (14 New Signals)

**Date:** 2026-03-10
**Focus:** Research-backed MLB K prop signal expansion + cross-season validation
**Previous:** Session 462 (BB simulator validated signals), Session 460 (MLB hyperparameter sweep)

## What Changed

### 3 Signals PROMOTED to Active (cross-season validated)

| Signal | HR (4 seasons) | N | Consistency | Mechanism |
|--------|---------------|---|-------------|-----------|
| `high_csw_over` | 63.9% | 432 | 4/4 (56-70%) | Elite CSW% >= 30% — best single K predictor |
| `elite_peripherals_over` | 66.2% | 589 | 4/4 (59-74%) | FIP < 3.5 + K/9 >= 9.0 — ace peripherals |
| `pitch_efficiency_depth_over` | 64.5% | 681 | 3/4 (46-71%) | IP avg >= 6.0 — deeper outings |

**Impact:** +0.3pp HR, +5-8u P&L per season. Brings active signal count to 17.

### 11 New Shadow Signals (accumulating data)

| Signal | Direction | Mechanism | Data Source |
|--------|-----------|-----------|-------------|
| `cold_weather_k_over` | OVER | Temp < 60°F, not dome — barrel difficulty | Weather scraper |
| `lineup_k_spike_over` | OVER | Today's lineup K% >= 26% vs pitcher hand | pitcher_loader |
| `short_starter_under` | UNDER | IP avg < 5.0 — caps K upside | Features |
| `game_total_low_over` | OVER | Game total <= 7.5 — deeper outings | Odds API |
| `heavy_favorite_over` | OVER | Team ML <= -180 — starter stays in | Odds API |
| `bottom_up_agrees_over` | OVER | Bottom-up K estimate > line | pitcher_loader |
| `catcher_framing_poor_under` | UNDER | Poor catcher framing runs <= -3.0 | New scraper |
| `day_game_shadow_over` | OVER | Day game visibility disadvantage | Features |
| `rematch_familiarity_under` | UNDER | 3+ games vs opponent this season | Features |
| `cumulative_arm_stress_under` | UNDER | Pitch avg >= 100 + 6+ games in 30d | Features |
| `taxed_bullpen_over` | OVER | 10+ bullpen IP last 3 games | Supplemental |

### Signal Replay Results (day_game_shadow_over — only new signal with 4-season data)

| Season | HR | N | vs Baseline |
|--------|-----|-----|-------------|
| 2022 | 58% | 220 | -2.9pp |
| 2023 | 61% | 178 | +0.6pp |
| 2024 | 62% | 259 | -1.2pp |
| 2025 | 60% | 281 | -5.6pp |
| **Total** | **60.1%** | **938** | Below baseline 3/4 seasons |

**Verdict:** day_game_shadow_over fires at 60.1% but consistently underperforms non-day picks. Keep as shadow — NOT ready for promotion.

### Bug Fix

- `best_bets_exporter.py`: Shadow signals were counting toward `real_signal_count`. Fixed by adding `not signal.is_shadow` check. Pre-existing issue.

### Supplemental Loader Enhancement

- Added `_load_game_context()` — loads moneyline + game total from `oddsa_game_lines` per game_pk
- Per-pitcher supplemental now includes `team_moneyline` and `game_total_line`
- Prioritizes DraftKings → FanDuel → BetMGM

### New Infrastructure

| File | Purpose |
|------|---------|
| `scrapers/mlb/external/mlb_catcher_framing.py` | Baseball Savant catcher framing scraper |
| `schemas/bigquery/mlb_raw/catcher_framing_tables.sql` | BQ schema for framing data |

## Files Modified

| File | Change |
|------|--------|
| `ml/signals/mlb/signals.py` | +542 lines — 14 new signal classes |
| `ml/signals/mlb/registry.py` | Register all new signals, updated counts |
| `ml/signals/mlb/best_bets_exporter.py` | Pick angles for new signals + shadow exclusion fix |
| `predictions/mlb/supplemental_loader.py` | Game context loader (moneyline, game total) |
| `scripts/mlb/training/season_replay.py` | Weather/game context SQL + signal evaluations |

## Current Signal Count

- **Active:** 17 (was 14)
- **Shadow:** 17 (was 8)
- **Observation:** 2
- **Negative filters:** 6
- **Total:** 42

## Season Replay Summary (with promoted signals)

| Season | Picks | HR% | P&L | ROI% |
|--------|-------|-----|-----|------|
| 2022 | 601 | 59.6% | +49.7u | 7.5% |
| 2023 | 386 | 60.4% | +53.2u | 12.5% |
| 2024 | 805 | 62.6% | +153.5u | 17.3% |
| 2025 | 835 | 63.8% | +200.0u | 21.8% |

## Tests

54 tests passing (supplemental loader, exporter, shadow picks).

## Next Steps

### P0 — Before MLB Season (March 25)
- [ ] Deploy L2=10+D4 hyperparameter config (Session 459 finding)
- [ ] Train fresh model with new hyperparams
- [ ] Deploy MLB worker
- [ ] Paper trade April 1-14

### P1 — Signal Data Collection
- [ ] Deploy catcher framing scraper (run weekly)
- [ ] Create BQ table for catcher framing data
- [ ] Monitor shadow signals for first 2 weeks of season
- [ ] Evaluate cold_weather, game_total, short_starter after 100+ data points

### P2 — Signal Promotion Pipeline
- [ ] Promote day_game_shadow_over IF it improves after 2026 data
- [ ] Evaluate UNDER signals once UNDER picks are enabled
- [ ] Target: 20+ active signals by mid-April
