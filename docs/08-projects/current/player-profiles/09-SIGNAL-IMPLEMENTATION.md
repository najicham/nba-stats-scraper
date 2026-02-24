# Player Profiles — Signal Implementation (Session 336)

## V15 Model Experiment Results

**Conclusion:** Model approach failed. `ft_rate_season` and `starter_rate_season` had <1% feature importance as CatBoost features. The model can't learn tier-specific directional interactions from global features.

**Pivot:** Post-model signal/filter approach instead.

## Validated Finding

Controlled analysis (N=1,548, 58 players, controlling for edge):

| Segment | HR | Edge | N |
|---------|-----|------|---|
| Bench OVER + High FT rate (>= 0.30) | 72.5% | 5.2 | ~774 |
| Bench OVER + Low FT rate (< 0.30) | 66.9% | 5.2 | ~774 |

**5.6pp gradient at same edge** — real signal, not confounded by edge differences.

Since 66.9% is still above breakeven, this is a **positive signal** (annotates), not a negative filter (blocks).

## Implementation

### Signal: `ft_rate_bench_over`

- **File:** `ml/signals/ft_rate_bench_over.py`
- **Status:** WATCH (confidence 0.80) — needs live validation before promotion
- **Fires when:** OVER + line < 15 (bench) + ft_rate_season >= 0.30
- **Registered in:** `ml/signals/registry.py`, `ml/signals/signal_health.py` (ACTIVE_SIGNALS)
- **Pick angle:** "Bench OVER + high FT rate: 72.5% HR historically (WATCH)"

### Supplemental Data

Added to `ml/signals/supplemental_data.py`:
- `ft_rate_season`: FTA/FGA ratio, season-to-date (point-in-time window function)
- `starter_rate_season`: % games started, season-to-date (point-in-time)

Both available in `player_profile` supplemental dict AND copied to prediction dict for direct signal access.

### Signal Subset: `signal_ft_rate_bench_over`

- **Subset ID:** 40 (in `shared/config/subset_public_names.py`)
- **Config:** `required_signals={'ft_rate_bench_over'}`, `min_edge=5.0`, `direction='OVER'`
- **Auto-graded** by existing `SubsetGradingProcessor`
- **Auto-exported** to `v1/subsets/performance.json`

## Monitoring Plan

1. **Signal health:** `signal_health_daily` tracks 7d/14d/30d/season HR automatically
2. **Subset performance:** Graded daily, exported to API
3. **Expected volume:** ~8-15 qualifying picks per day on typical slates
4. **Promotion criteria:** Live HR >= 65% over 50+ graded picks → promote to PRODUCTION

## What Was NOT Done

- No negative filter added (66.9% low-FT-rate bench OVER is still profitable)
- No changes to `validate-daily` skill (WATCH status, not PRODUCTION)
- `starter_rate_season` data is available but no signal uses it yet — available for future signals
