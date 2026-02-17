# Signal Inventory — Complete List

**Last Updated:** 2026-02-16 (Session 275 — Major cleanup)
**Total Active Signals:** 18 (10 removed in Session 275)
**Combo Registry:** 10 entries (8 SYNERGISTIC, 2 ANTI_PATTERN)

---

## Active Signals (18)

### Core Infrastructure (2)

| # | Signal Tag | Description | AVG HR | Status |
|---|------------|-------------|--------|--------|
| 1 | `model_health` | Always fires. Baseline qualifier for 2-signal min. | 52.6% | PRODUCTION |
| 2 | `dual_agree` | V9 + V12 same direction | 45.5% (W4 only) | WATCH |

### Edge & Combo Signals (4)

| # | Signal Tag | Description | AVG HR | Status |
|---|------------|-------------|--------|--------|
| 3 | `high_edge` | Edge >= 5.0 points | 66.7% | Standalone BLOCKED, combo OK |
| 4 | `edge_spread_optimal` | Edge + conf + quality gate | 67.2% | PRODUCTION (anti-pattern detection) |
| 5 | `combo_he_ms` | High edge + minutes surge + OVER | 94.9% | PRODUCTION (best combo) |
| 6 | `combo_3way` | ESO + high edge + minutes surge | 78.1% | PRODUCTION (premium) |

### Bounce & Recovery Signals (3)

| # | Signal Tag | Description | AVG HR | Status |
|---|------------|-------------|--------|--------|
| 7 | `3pt_bounce` | Cold 3PT shooter regression → OVER | 74.9% | CONDITIONAL |
| 8 | `cold_snap` | UNDER 3+ straight → OVER (HOME-ONLY) | N/A (N=0 recent) | CONDITIONAL |
| 9 | `blowout_recovery` | Low mins blowout → OVER (No C, No B2B) | 56.9% | WATCH |

### Volume & Context Signals (3)

| # | Signal Tag | Description | AVG HR | Status |
|---|------------|-------------|--------|--------|
| 10 | `minutes_surge` | Minutes last 3 > season + 3 | 53.7% | WATCH |
| 11 | `rest_advantage_2d` | Player rested 2+ days vs fatigued opp | 64.8% | CONDITIONAL |
| 12 | `model_consensus_v9_v12` | V9 + V12 agree, both edge >= 3 | 45.5% (W4 only) | WATCH |

### Market-Pattern UNDER Signals (6) — Session 274-275

Cross-season validated patterns (2023-2024 historical data). Model-agnostic — fire on player characteristics, not model output.

| # | Signal Tag | Description | AVG HR | Status |
|---|------------|-------------|--------|--------|
| 13 | `bench_under` | Bench player (non-starter) UNDER | **76.9%** | PRODUCTION |
| 14 | `high_ft_under` | High FT volume (FTA >= 7) UNDER | 64.1% | CONDITIONAL |
| 15 | `b2b_fatigue_under` | B2B fatigue + high usage UNDER | **85.7%** | CONDITIONAL (N=14) |
| 16 | `self_creator_under` | Self-creating scorer UNDER | 61.8% | WATCH |
| 17 | `volatile_under` | High variance player (std 10+) UNDER | 60.0% | WATCH |
| 18 | `high_usage_under` | High usage (30%+) player UNDER | 58.7% | WATCH |

---

## Removed Signals (10) — Session 275

### Below Breakeven (actively harmful — gave undeserved 2-signal qualification)

| Signal Tag | AVG HR | Total N | Problem |
|------------|--------|---------|---------|
| `hot_streak_2` | 45.8% | 416 | Fired on 19% of picks, net negative. Biggest false qualifier. |
| `hot_streak_3` | 47.5% | 182 | 2/3 windows below breakeven |
| `cold_continuation_2` | 45.8% | 130 | Never above breakeven in any window |
| `fg_cold_continuation` | 49.6% | 55 | Catastrophic W4 decay (64.7% → 36.8%) |

### Never Fire (dead code — 0 picks across all backtest windows)

| Signal Tag | Notes |
|------------|-------|
| `pace_mismatch` | N=0 all windows |
| `points_surge_3` | N=0 all windows |
| `home_dog` | N=0 all windows |
| `minutes_surge_5` | N=0 all windows |
| `three_pt_volume_surge` | N=0 all windows |
| `scoring_acceleration` | N=0 all windows |

### Previously Removed

| Signal Tag | Session | Reason |
|------------|---------|--------|
| `prop_value_gap_extreme` | 255 | 12.5% HR, -76.1% ROI |
| `triple_stack` | 256 | Meta-signal with broken logic |

---

## Combo Registry (10 entries)

### SYNERGISTIC (8)

| Combo ID | Signals | Direction | HR | Score Weight | Status |
|----------|---------|-----------|----|-------------|--------|
| `edge_spread_optimal+high_edge+minutes_surge` | ESO + HE + MS | BOTH | 88.9% | 2.5 | PRODUCTION |
| `high_edge+minutes_surge` | HE + MS | OVER_ONLY | 79.4% | 2.0 | PRODUCTION |
| `bench_under` | bench_under | UNDER_ONLY | **76.9%** | 1.5 | PRODUCTION |
| `cold_snap` | cold_snap (home) | OVER_ONLY | 93.3% | 1.5 | CONDITIONAL |
| `b2b_fatigue_under` | b2b_fatigue_under | UNDER_ONLY | **85.7%** | 1.0 | CONDITIONAL |
| `3pt_bounce` | 3pt_bounce (guards) | OVER_ONLY | 74.9% | 1.0 | CONDITIONAL |
| `high_ft_under` | high_ft_under | UNDER_ONLY | 64.1% | 0.5 | CONDITIONAL |
| `blowout_recovery` | blowout_recovery | OVER_ONLY | 56.9% | 0.5 | WATCH |

### ANTI_PATTERN (2)

| Combo ID | Signals | HR | Score Weight | Status |
|----------|---------|-----|-------------|--------|
| `edge_spread_optimal+high_edge` | ESO + HE (redundancy trap) | 31.3% | -2.0 | BLOCKED |
| `high_edge` | HE standalone | 43.8% | -1.0 | BLOCKED |

---

## Post-Cleanup Backtest Results (Session 275)

### Aggregator Simulation (Top 5 picks/day)

| Window | Picks | HR | ROI |
|--------|-------|----|-----|
| W2 (Jan 5-18) | 50 | **80.0%** | +52.7% |
| W3 (Jan 19-31) | 65 | **78.5%** | +49.8% |
| W4 (Feb 1-13) | 57 | **63.2%** | +20.6% |
| **AVG** | — | **73.9%** | — |

**Improvement:** 73.9% AVG HR (up from 60.3% pre-cleanup)

### Key Overlap Combos (N >= 10)

| Combo | N | HR | ROI |
|-------|---|----|-----|
| `bench_under+model_health` | 129 | **76.7%** | +46.5% |
| `combo_3way+...+rest_advantage_2d` (7-way) | 20 | **95.0%** | +81.4% |
| `high_edge+model_health+rest_advantage_2d` | 20 | **85.0%** | +62.3% |
| `3pt_bounce+model_health` | 13 | 69.2% | +32.2% |
| `high_usage_under+model_health+self_creator_under` | 13 | 69.2% | +32.2% |

---

## Direction Balance (Post-Cleanup)

| Direction | Signals | Notes |
|-----------|---------|-------|
| OVER_ONLY | 5 (combo_he_ms, combo_3way, 3pt_bounce, cold_snap, blowout_recovery) | Original core |
| UNDER_ONLY | 6 (bench_under, high_ft_under, b2b_fatigue_under, self_creator_under, volatile_under, high_usage_under) | **New market patterns** |
| BOTH | 7 (model_health, high_edge, ESO, dual_agree, minutes_surge, rest_advantage_2d, model_consensus_v9_v12) | Includes infrastructure |

**OVER bias resolved.** Previously 5 OVER vs 0 UNDER dedicated signals. Now 5 OVER vs 6 UNDER.

---

## Production Readiness Criteria

For a signal to be promoted to production:

- **Performance:** AVG HR >= 60% across eval windows
- **Coverage:** N >= 20 picks total (statistical significance)
- **Stability:** Doesn't crash catastrophically in W4 (decay resilience)
- **Overlap Value:** Boosts existing signals or provides unique coverage
- **Technical:** No data quality issues, runs without errors

---

## Next Steps

1. **Monitor post-Feb-19 performance** — Validate cleanup on live out-of-sample data
2. **Re-evaluate WATCH signals** after 2+ weeks of live data
3. **Consider promoting** `self_creator_under` and `volatile_under` if they stabilize above 60%
4. **Implement Batch 3** (Rest/Fatigue) signals if coverage gaps identified
5. **Multi-model aggregation** — Route UNDER signals to Q43/Q45 for model-aware scoring

---

**Last Updated:** 2026-02-16, Session 275
**Next Review:** After 2+ weeks post-cleanup live data (early March 2026)
