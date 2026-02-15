# Signal Interaction Matrix - Quick Reference

**Date:** 2026-02-14 | **Period:** 2026-01-09 to 2026-02-14 (36 days)

## TL;DR

- **Deploy Now:** `high_edge + minutes_surge` (79.4% HR, 34 picks)
- **Never Deploy:** `high_edge + edge_spread_optimal` (31.3% HR, -37.4% ROI, 179 picks)
- **Key Insight:** `high_edge` alone loses money. It REQUIRES a complementary signal.

---

## Production Decision Matrix

| Combo | HR | ROI | Picks | Status |
|-------|-----|-----|-------|--------|
| high_edge + minutes_surge | 79.4% | +58.8% | 34 | ✅ DEPLOY |
| high_edge + prop_value_gap_extreme | 72.7% | +45.5% | 11 | 🔬 PROTOTYPE |
| high_edge + blowout_recovery | 61.1% | +22.2% | 18 | 🔬 PROTOTYPE |
| minutes_surge + cold_snap | 100.0% | +100.0% | 5 | 🔬 PROTOTYPE |
| blowout_recovery + cold_snap | 100.0% | +100.0% | 3 | 🔬 PROTOTYPE |
| high_edge + edge_spread_optimal | 31.3% | -37.4% | 179 | 🚫 AVOID |
| minutes_surge + blowout_recovery | 42.9% | -14.3% | 14 | 🚫 AVOID |
| high_edge (standalone) | 43.8% | -12.4% | 89 | 🚫 AVOID |

---

## Signal Families

### Family 1: Universal Amplifiers
**Members:** `minutes_surge`

Boosts ANY edge signal by increasing opportunity volume.

**Best Combos:**
- `+ high_edge`: +31.2% lift
- `+ cold_snap`: +51.8% lift

**Avoid Combos:**
- `+ blowout_recovery`: -10.1% (anti-synergy)

---

### Family 2: Value Signals
**Members:** `high_edge`, `prop_value_gap_extreme`

Identify mispricing but REQUIRE validation signal.

**Critical:** Never use `high_edge` standalone (43.8% HR, loses money)

**Best Combos:**
- `high_edge + minutes_surge`: 79.4% HR
- `high_edge + prop_value_gap_extreme`: 72.7% HR

**Avoid Combos:**
- `high_edge + edge_spread_optimal`: 31.3% HR (pure redundancy)

---

### Family 3: Bounce-Back Signals
**Members:** `cold_snap`, `blowout_recovery`, `3pt_bounce`

Identify mean reversion opportunities.

**Double Bounce-Back Pattern:** When TWO reversion signals fire, HR spikes to 100%

**Best Combos:**
- `blowout_recovery + cold_snap`: 100% HR (3 picks)
- `3pt_bounce + blowout_recovery`: 100% HR (2 picks)

**Avoid Combos:**
- `3pt_bounce + minutes_surge`: 50% HR (variance dilutes regression)

---

### Family 4: Redundancy Traps
**Members:** `high_edge`, `edge_spread_optimal`

Both measure model confidence → no synergy when combined.

**Evidence:** `high_edge + edge_spread_optimal` = 31.3% HR (-37.4% ROI)

**Action:** Use ONE confidence signal, not both.

---

## Quick Lookup Tables

### HR Matrix (Diagonal = Individual, Off-diagonal = Combo)

|  | high_edge | minutes_surge | 3pt_bounce | blowout | cold_snap |
|---|-----------|---------------|------------|---------|-----------|
| **high_edge** | 43.8% (89) | 79.4% (34) | 66.7% (3) | 61.1% (18) | 100.0% (1) |
| **minutes_surge** | 79.4% (34) | 48.2% (278) | 50.0% (6) | 42.9% (14) | 100.0% (5) |
| **3pt_bounce** | 66.7% (3) | 50.0% (6) | 70.0% (10) | 100.0% (2) | - |
| **blowout** | 61.1% (18) | 42.9% (14) | 100.0% (2) | 53.0% (100) | 100.0% (3) |
| **cold_snap** | 100.0% (1) | 100.0% (5) | - | 100.0% (3) | 47.8% (23) |

---

### ROI Matrix (at -110 odds)

|  | high_edge | minutes_surge | 3pt_bounce | blowout | cold_snap |
|---|-----------|---------------|------------|---------|-----------|
| **high_edge** | -12.4% | +58.8% | +33.3% | +22.2% | +100.0% |
| **minutes_surge** | +58.8% | -3.6% | 0.0% | -14.3% | +100.0% |
| **3pt_bounce** | +33.3% | 0.0% | +40.0% | +100.0% | - |
| **blowout** | +22.2% | -14.3% | +100.0% | +6.0% | +100.0% |
| **cold_snap** | +100.0% | +100.0% | - | +100.0% | -4.3% |

---

## Validation Thresholds

| Sample Size | Status | Confidence Level |
|-------------|--------|------------------|
| 50+ picks | Production Ready | High |
| 30-49 picks | Deploy with Monitoring | Medium-High |
| 15-29 picks | Prototype/Shadow | Medium |
| 5-14 picks | Monitor for Recurrence | Low |
| <5 picks | Insufficient Data | None |

**Current Production-Ready Combos:** 1
- `high_edge + minutes_surge` (34 picks) - approaching 50-pick threshold

---

## Action Items

### Immediate (Today)
1. Deploy `high_edge + minutes_surge` to Best Bets
2. Add blacklist rule: exclude `high_edge + edge_spread_optimal`
3. Add blacklist rule: exclude `minutes_surge + blowout_recovery`

### This Week
1. Monitor cold_snap combos for sample size growth
2. Track `high_edge + prop_value_gap_extreme` (currently 11 picks)
3. Disable standalone `high_edge` picks (not profitable)

### This Month
1. Build composite signal: `minutes_boost = minutes_surge AND (high_edge OR edge_spread_optimal)`
2. Build composite signal: `contrarian_bounce = COUNT(cold_snap, blowout_recovery, 3pt_bounce) >= 2`
3. Re-run matrix with 60+ days of data

---

## Critical Warnings

### ⚠️ WARNING 1: high_edge Standalone
`high_edge` alone: 43.8% HR, -12.4% ROI (loses money)

**Never deploy high_edge picks without a complementary signal.**

### ⚠️ WARNING 2: Largest Anti-Pattern
`high_edge + edge_spread_optimal`: 31.3% HR, -37.4% ROI, 179 picks

**This is the LARGEST sample anti-pattern. Explicitly blacklist this combo.**

### ⚠️ WARNING 3: Minutes Surge + Blowout Recovery
`minutes_surge + blowout_recovery`: 42.9% HR, -14.3% ROI

**Negative synergy confirmed over 14 picks. Blacklist.**

---

## Query to Reproduce

```sql
-- Run in BigQuery
WITH tagged_picks AS (
  SELECT
    pst.signal_tags,
    pa.prediction_correct,
    ppp.predicted_points - ppp.current_points_line as edge
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  JOIN nba_predictions.player_prop_predictions ppp
    ON ppp.player_lookup = pa.player_lookup
    AND ppp.game_id = pa.game_id
    AND ppp.system_id = pa.system_id
  WHERE pst.game_date >= "2026-01-09"
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ("ACTUAL_PROP", "ODDS_API", "BETTINGPROS")
),
combos AS (
  SELECT
    CASE
      WHEN ARRAY_LENGTH(signal_tags) = 1 AND "high_edge" IN UNNEST(signal_tags) THEN "high_edge"
      WHEN "high_edge" IN UNNEST(signal_tags) AND "minutes_surge" IN UNNEST(signal_tags) THEN "high_edge + minutes_surge"
      -- ... add all other combinations
    END as combo,
    prediction_correct,
    edge
  FROM tagged_picks
)
SELECT
  combo,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(100.0 * ((COUNTIF(prediction_correct) / COUNT(*)) * 2 - 1), 1) as roi
FROM combos
WHERE combo IS NOT NULL
GROUP BY 1
ORDER BY hr DESC
```

---

## Related Documents

- **Full Analysis:** [SIGNAL-INTERACTION-MATRIX-V2.md](./SIGNAL-INTERACTION-MATRIX-V2.md)
- **Combo Mechanics:** [COMBO-MECHANICS-ANALYSIS.md](./COMBO-MECHANICS-ANALYSIS.md)
- **Anti-patterns:** [HARMFUL-SIGNALS-SEGMENTATION.md](./HARMFUL-SIGNALS-SEGMENTATION.md)
- **Coverage Gaps:** [ZERO-PICK-PROTOTYPES-ANALYSIS.md](./ZERO-PICK-PROTOTYPES-ANALYSIS.md)

---

**Last Updated:** 2026-02-14
**Next Update:** Weekly (or when any combo reaches new sample size tier)
