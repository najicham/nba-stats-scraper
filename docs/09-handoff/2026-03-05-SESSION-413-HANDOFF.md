# Session 413 Handoff — Filters, Regime Fix, Pick Quality Audit

**Date:** 2026-03-05
**Type:** Feature, bug fix, deployment, operations
**Key Insight:** Regime context (Session 412) nuked 10/12 picks on first re-export. Fixed to observation-only. Also added spread observation filter, plumbed spread_magnitude through pipeline, fixed str-to-date bug, and ran deep pick quality audit.

---

## What This Session Did

### 1. Verified Pick Locking Deployment (Session 412)
- Commit `232daf14` already pushed, all Cloud Build triggers SUCCESS
- Pick locking working: `best_bets_published_picks` shows all `signal_status='active'`, no `dropped`
- 15 published picks for Mar 5, locked rows preserved across re-exports

### 2. Implemented `high_spread_over` Observation Filter
**Commit:** `4f2cb0c8`

OVER picks in games with spread > 7 hit 44.4% (N=18) vs 74.1% (spread <= 7) — 29.7pp gap.

- `supplemental_data.py`: Added `feature_41_value AS spread_magnitude` to book_stats CTE, JOIN select, and pred dict enrichment
- `aggregator.py`: Added `high_spread_over_would_block` observation counter — logs + records to `best_bets_filtered_picks`, does NOT block
- **Note:** Filter is duplicated (inline at ~L593 + post-scored at ~L935). Cosmetic issue — double-counts but doesn't affect picks. Clean up next session.

### 3. Fixed `regime_context.py` str-to-date Bug
**Commit:** `b22f773e`

Phase 6 export crashed with `unsupported operand type(s) for -: 'str' and 'datetime.timedelta'`. The `target_date` arrives as string from Pub/Sub but `regime_context.py` assumed a `date` object for `target_date - timedelta(days=1)`.

**Fix:** Added `if isinstance(target_date, str): target_date = date.fromisoformat(target_date)`.

### 4. Regime Context → Observation-Only (CRITICAL FIX)
**Commit:** `ef07eb95`

After fixing the str bug and re-triggering Phase 6, the regime context classified today as "cautious" (yesterday 4-4 = 50% but grading JOIN saw 3-4 = 42.9%), which:
- Disabled ALL OVER signal rescue → killed 8 OVER picks
- Raised OVER edge floor 5.0→6.0 → killed 1 more
- Combined with `flat_trend_under` blocking 3 UNDER → **only 2 of 12 picks survived**
- Degradation guard caught it: "picks_dropped_50pct (12 -> 2)", backed up old JSON

**Fix:** Both regime effects now observation-only:
- `regime_rescue_blocked`: Still logs + records to `filtered_picks`, but does NOT disable rescue
- `regime_over_floor`: Still logs what WOULD be blocked, but floor stays at 5.0 (no delta)

**After fix:** Re-export produced 9 picks (7 OVER + 2 UNDER). 3 blocked by `flat_trend_under`.

**Root cause lesson:** The regime triggers on yesterday's BB HR with MIN_N=5. On small slates (N=7), a single loss swings the regime. Combined with other active filters, the cascading effect is devastating. Regime needs much more data (N=30+) before trusting it as an active filter.

### 5. Fixed Scraper Deployment Drift
Deployed `nba-scrapers` service — was stale at `69d06c97`.

### 6. Daily Steering Report

| Metric | Value | Status |
|--------|-------|--------|
| Fleet | 4 HEALTHY, 1 WATCH, 2 DEGRADING, 19 BLOCKED | All BLOCKED auto-disabled |
| Market compression | 0.596 | RED |
| 7d avg max edge | 6.95 (was 11.67 30d) | Severe drop post-ASB |
| BB HR 7d / 14d / 30d | 46.7% / 55.6% / 53.8% | YELLOW |
| OVER 14d / UNDER 14d | 50.0% / 66.7% | UNDER carrying |
| Signal rescue | 3-3 (50%) N=6 | Too early |

### 7. Deep Pick Quality Audit

**Filter Stack Audit (33 filters):**
- 23 hard blocks + 10 observation-only
- All in correct order, no broken logic
- `flat_trend_under` correctly positioned (filter #23, before signal evaluation)
- All observation filters properly marked (no accidental `continue`)
- One cosmetic issue: `high_spread_over` observation duplicated in two places

**Signal Rescue Analysis:**
- 6 graded rescued picks: 3-3 (50% HR) vs 66.4% non-rescued
- ALL rescued picks are OVER — no UNDER rescues ever generated
- Tonight: 6/9 picks are rescued (67% of slate). Two quality tiers:
  - Strong: Tre Johnson (4 real signals), Coulibaly (4), Cody Williams (5)
  - Thin: Allen (2 real), Barnes (2 real), Santos (2 real)
- **Too early to act at N=6. Need N=30+.**

**flat_trend_under Validation:**
- Blocked 3 UNDER picks tonight: Herro (slope -0.04), KD (slope 0.39), Achiuwa (slope 0.54)
- All 3 had ZERO signal tags — pure model-edge picks with no confirming signals
- Filter is correctly removing low-conviction UNDER picks

**Game Concentration:**
- 3+ picks same game = 81.1% HR (N=37) vs 58.7% single-pick — NOT a risk
- High-spread blowout games with multi-OVER are the one danger (40% HR at 5+ OVERs)
- Tonight: UTA-WAS (3 OVER, spread 3.5 = safe), CHI-PHX (2 OVER, spread 10.5 = flagged)

---

## Files Modified

| File | Change | Commit |
|------|--------|--------|
| `ml/signals/supplemental_data.py` | Added `spread_magnitude` (f41) to feature pipeline | `4f2cb0c8` |
| `ml/signals/aggregator.py` | Spread observation + regime → observation-only | `4f2cb0c8`, `ef07eb95` |
| `ml/signals/regime_context.py` | str-to-date fix for Phase 6 | `b22f773e` |

---

## Current State of Picks (Mar 5)

**9 active picks in JSON** (algorithm `v414_observation_filters`):

| Player | Dir | Line | Edge | Rescued | Spread | Key Signals |
|--------|-----|------|------|---------|--------|-------------|
| Devin Booker | OVER | 24.5 | 5.1 | No | 10.5 | line_rising, self_creation, usage_surge |
| Tre Johnson | OVER | 13.5 | 4.7 | Yes (HSE) | 3.5 | scoring_cold_streak, HSE, consistent_scorer |
| Grayson Allen | OVER | 17.5 | 4.7 | Yes (stack) | 10.5 | consistent_scorer, usage_surge |
| Bilal Coulibaly | OVER | 12.5 | 4.2 | Yes (HSE) | 3.5 | ft_rate_bench, HSE, over_trend |
| Scottie Barnes | OVER | 17.5 | 3.9 | Yes (stack) | 5.5 | line_rising, consistent_scorer |
| Gui Santos | OVER | 12.5 | 3.4 | Yes (combo) | 8.5 | combo_he_ms, combo_3way |
| Cody Williams | OVER | 8.5 | 3.3 | Yes (HSE) | 3.5 | b2b_boost, HSE, low_line, dvp_favorable |
| Austin Reaves | UNDER | 19.5 | 4.3 | No | 5.0 | starter_under, blowout_risk |
| Jalen Duren | UNDER | 18.5 | 3.0 | No | 3.5 | starter_under, projection_consensus, blowout_risk |

**Filtered (observation/blocked):**

| Player | Filter | Edge | Notes |
|--------|--------|------|-------|
| Booker | high_spread_over (obs) | 5.1 | Spread 10.5 — still picked, just flagged |
| Allen | high_spread_over (obs) | 4.7 | Spread 10.5 — still picked, just flagged |
| Santos | high_spread_over (obs) | 3.4 | Spread 8.5 — still picked, just flagged |
| Herro | flat_trend_under | 4.0 | slope -0.04, zero signals |
| KD | flat_trend_under | 3.7 | slope 0.39, zero signals |
| Achiuwa | flat_trend_under | 5.4 | slope 0.54, zero signals |

---

## Monitoring Queries

```sql
-- 1. Grade tonight's picks (run morning of Mar 6)
SELECT b.player_lookup, b.recommendation, b.line_value,
  pa.actual_points, pa.prediction_correct, b.signal_rescued
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
WHERE b.game_date = '2026-03-05' AND b.algorithm_version = 'v414_observation_filters'
ORDER BY b.recommendation, b.player_lookup;

-- 2. Counterfactual: would blocked picks have won?
SELECT filter_reason, player_lookup, recommendation, edge,
  pa.actual_points, pa.prediction_correct
FROM `nba-props-platform.nba_predictions.best_bets_filtered_picks` fp
LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON fp.player_lookup = pa.player_lookup AND fp.game_date = pa.game_date AND fp.system_id = pa.system_id
WHERE fp.game_date = '2026-03-05'
  AND filter_reason IN ('flat_trend_under', 'high_spread_over_would_block',
                         'regime_rescue_blocked', 'regime_over_floor')
ORDER BY filter_reason;

-- 3. Signal rescue cumulative HR (growing N)
SELECT signal_rescued, COUNT(*) as total,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hr
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
WHERE b.game_date >= '2026-01-01' AND pa.prediction_correct IS NOT NULL
GROUP BY 1;

-- 4. Pick locking: count should never decrease for same game_date
SELECT game_date, COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date >= '2026-03-05'
GROUP BY 1;
```

---

## Next Session — Priority Tasks

### 1. Grade Mar 5 Results (FIRST THING)
Run query #1 and #2 above. Key questions:
- **Rescued OVER picks:** Did the 6 rescued picks win? (50% HR at N=6 currently)
- **Spread-flagged picks:** Did Booker/Allen (spread 10.5) lose? Santos (8.5)?
- **flat_trend_under counterfactual:** Did Herro/KD/Achiuwa UNDER hit? If all 3 won, filter is blocking winners.
- **Regime counterfactual:** Would the 8 regime-blocked picks have won? (Logged in filtered_picks)

### 2. Signal Rescue Decision (~Mar 19, N=25-30)
Signal rescue at 50% HR (N=6) — tonight adds 6 more graded. If cumulative HR stays below 55% at N=15+:
- Consider raising `signal_stack_2plus` from 2+ to 3+ real signals (tonight's thin picks had only 2)
- Consider removing `low_line_over` from rescue set (0-1 historically)
- `high_scoring_environment_over` is the most common rescue signal — evaluate separately

### 3. Promote Spread Filter (When Ready, N=50+)
After accumulating observations, if OVER HR stays below 50% at spread > 7:
- Add `continue` to make it an active filter
- Move earlier in filter chain (before signal density)

### 4. Clean Up Duplicate Spread Observation
`high_spread_over_would_block` runs twice (inline ~L593 and post-scored ~L935). Remove the post-scored duplicate to fix double-counting.

### 5. Regime Context: Keep Observation, Collect Data
- Regime is now observation-only — collects counterfactual data in `filtered_picks`
- After 30+ cautious-regime days with graded data, re-evaluate whether regime effects actually improve HR
- The autocorrelation (r=0.43) is real but the effect size (53.9% next-day) is still above breakeven

### 6. Market Compression Watch
- Compression at 0.596 (RED), edges severely compressed post-ASB
- Not fixable by retraining — this is market structure
- If 7d HR stays below 50% for another week, consider pausing or reducing pick count

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `4f2cb0c8` | feat: high_spread_over observation filter + spread_magnitude pipeline |
| `b22f773e` | fix: regime_context str-to-date conversion for Phase 6 |
| `ef07eb95` | fix: regime context to observation-only — was nuking 10/12 picks |

---

## Known Issues

- **Duplicate spread observation filter** in aggregator.py (cosmetic, double-counts)
- **KAT Mar 4 grading gap**: Backfilled pick references system_id whose prediction was HOLD, not UNDER. Grading can't resolve cross-model signal picks via prediction_accuracy JOIN. Structural limitation.
- **Market compression RED**: 7d avg max edge 6.95 vs 30d 11.67. Fewer edge 5+ picks available.
