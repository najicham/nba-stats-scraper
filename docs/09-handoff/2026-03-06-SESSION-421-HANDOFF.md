# Session 421 Handoff — Edge Overconfidence Mitigations (Observation Mode)

**Date:** 2026-03-06
**Type:** Signal system, risk mitigation
**Key Insight:** Edge-HR inversion during toxic window (Jan 30-Feb 25) has three root causes: roster volatility, overconfidence amplification (error scales 3.4→5.9→8.8 with edge), and player-tier concentration (bench edge 7+ = 34.1% HR). Three observation-mode mitigations deployed to gather data for next toxic window.

---

## What This Session Did

### 1. Edge Overconfidence Investigation

Deep analysis of pre-ASB vs post-ASB edge performance revealed:

| Period | Edge 3-5 HR | Edge 5-7 HR | Edge 7+ HR |
|--------|-------------|-------------|------------|
| Pre-ASB (Jan 30-Feb 20) | 43.0% | 42.0% | 38.4% |
| Post-ASB (Feb 21+) | 67.0% | 72.0% | 83.0% |

**Root causes:**
1. **Trade deadline roster volatility** — model features become stale as players change teams/roles
2. **Overconfidence amplification** — prediction error scales linearly with edge
3. **Player-tier concentration** — bench at edge 7+ = 34.1% HR (N=91) vs starters 63.2% (N=57)

### 2. Mitigation A: Player-Tier Edge Caps (Observation)

Classifies each pick by player tier based on line value, computes what composite_score WOULD be if capped. Data stored on picks but ranking unchanged.

| Tier | Line Range | Cap | Why |
|------|-----------|-----|-----|
| Bench | < 12 | 5.0 | 34.1% HR at edge 7+ (N=91) |
| Role | 12-17.5 | 6.0 | 43.1% HR at edge 7+ (N=72) |
| Starter | 18-24.5 | uncapped | 63.2% HR |
| Star | 25+ | uncapped | — |

BQ columns added: `player_tier`, `tier_edge_cap_delta`, `capped_composite_score`.

### 3. Mitigation B: Market Compression Detector

New `get_market_compression()` in `regime_context.py`. Compares 7d vs 30d P90 edge at edge 3+ to classify:
- **RED** (< 0.70): severe compression, edge 5+ unreliable
- **YELLOW** (0.70-0.85): moderate compression
- **GREEN** (> 0.85): normal edge distribution

BQ columns added: `compression_ratio`, `compression_scaled_edge`.

### 4. Mitigation C: Feature-Based Unreliable Edge

Two observation filters based on feature fingerprints of wrong predictions during toxic window:
- `unreliable_over_low_mins_obs`: OVER + edge 5+ + minutes_load_7d < 45 (wrong OVERs had avg 42.8 vs 54.7 correct)
- `unreliable_under_flat_trend_obs`: UNDER + edge 5+ + minutes_load > 58 + flat trend (-0.3 to 0.3)

Both log to `filtered_picks` for counterfactual grading but do NOT block picks.

### 5. Documentation Updates

- `SIGNAL-INVENTORY.md` updated with Sessions 413-421: mean_reversion_under (active), bounce_back_over + over_streak_reversion_under (shadow), flat_trend_under + under_after_streak (active filters), line_jumped_under demoted to obs, observation mechanics section added
- Signal counts updated: 28 active, 22 shadow, 21 active filters, 5 obs filters

---

## Commits

```
(pending commit — all changes in working tree)
```

## Files Changed

| File | Changes |
|------|---------|
| `ml/signals/aggregator.py` | TIER_EDGE_CAPS constant, tier classification + cap observation, feature-based unreliable edge obs, compression logging, new filter_counts, algorithm bump |
| `ml/signals/regime_context.py` | New `get_market_compression()` function |
| `data_processors/publishing/signal_best_bets_exporter.py` | Wire compression into regime_ctx |
| `tests/unit/signals/test_aggregator.py` | New filter keys in expected_keys |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | Sessions 413-421 updates |

## BQ Schema Changes

```sql
ALTER TABLE signal_best_bets_picks ADD COLUMN IF NOT EXISTS:
  player_tier STRING, tier_edge_cap_delta FLOAT64, capped_composite_score FLOAT64,
  compression_ratio FLOAT64, compression_scaled_edge FLOAT64
```

---

## Verification (After First Daily Run)

```sql
-- 1. Tier caps observation
SELECT player_tier, COUNT(*) as n,
  COUNTIF(tier_edge_cap_delta > 0) as would_cap,
  ROUND(AVG(tier_edge_cap_delta), 2) as avg_delta
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 1 AND player_tier IS NOT NULL
GROUP BY 1;

-- 2. Unreliable edge observations
SELECT filter_reason, COUNT(*) as n
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason LIKE 'unreliable_%' AND game_date >= CURRENT_DATE() - 1
GROUP BY 1;

-- 3. Compression ratio
SELECT DISTINCT compression_ratio
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 1 AND compression_ratio IS NOT NULL;
```

---

## Activation Criteria (Future Sessions)

| Mitigation | When to Activate | Change Required |
|-----------|-----------------|----------------|
| Tier caps | 2+ weeks, capped picks HR < 50% at N >= 20 | Use `capped_composite_score` for ranking |
| Compression | 30+ days, RED edge 5+ HR < 50% at N >= 30 | Multiply composite by compression_ratio |
| Feature reliability | 2+ weeks, flagged HR < 45% at N >= 15 | Promote to active filter with `continue` |

---

## Model-Level Finding (Informational)

Low-vegas-weight model (`v9_low_vegas`) was most robust during toxic window: 64.7% HR at edge 5+ (N=17) vs fleet avg 38%. Less reliant on market lines that are also disrupted. Consider for future retrain strategy.

---

## Priority Actions for Next Session

### P1: Verify Observation Data Flowing (Tomorrow)
Run verification queries above after first daily run to confirm tier caps, compression, and feature reliability data are populating.

### P2: Monitor v422 Filter Rebalance
Algorithm was bumped to `v422_filter_rebalance` during this session (blowout_recovery and starter_under demoted to BASE_SIGNALS). Monitor slate size and HR.

### P3: Compression Detector Validation (Mar 20+)
Need 14+ days of data spanning different market conditions to validate compression ratio thresholds.

---

## Key Context

- **Algorithm version:** `v422_filter_rebalance` (was v421, bumped externally)
- **All mitigations are observation-only** — zero impact on current picks
- **Market regime:** GREEN (compression ratio 1.0) — good time to collect baseline data
- **63 unit tests pass** after changes
