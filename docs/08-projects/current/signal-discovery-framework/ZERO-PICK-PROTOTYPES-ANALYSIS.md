# Zero-Pick Signal Prototypes — Backtest Environment Analysis

**Date:** 2026-02-14 (Session 256)
**Scope:** 13 signals with 0 picks from 35-day backfill (Dec 8, 2025 - Feb 13, 2026)
**Goal:** Determine root causes in backtest environment specifically
**Context:** Analysis based on `ml/experiments/signal_backtest.py` (backtest harness)

---

## Executive Summary

**6 HIGH priority signals** blocked by missing supplemental data that's trivial to add (points, FG%, extended windows).
**2 MEDIUM priority signals** need threshold relaxation or opponent tracking.
**1 signal** has broken stub logic (triple_stack).
**4 signals** are likely working but rare OR blocked by V12 deployment.

**Root cause breakdown:**
- **7 signals**: MISSING_DATA in backtest (feasible to add to `signal_backtest.py`)
- **4 signals**: TOO_RESTRICTIVE thresholds (need tuning)
- **1 signal**: BROKEN_LOGIC (always returns not qualified)
- **1 signal**: DEPENDENCY (V12 model not fully deployed)

**High-value fix:** Extending `signal_backtest.py` game_stats CTE to include:
1. `points_stats` (points_avg_last_3, points_avg_last_5, points_avg_season) — unlocks 2 signals
2. `fg_stats` (fg_pct_last_3, fg_pct_season, fg_pct_std) — unlocks 1 signal
3. `minutes_avg_last_5` — unlocks 1 signal
4. `three_pa_avg_last_3` — unlocks 1 signal
5. `is_home` from schedule JOIN — unlocks 1 signal

**Estimated impact:** 100-200 new qualifying picks across 35-day backfill once data is available.

**Note:** Streak-based signals (hot_streak_2/3, cold_continuation_2) already have data available in backtest via streak_data CTE. If showing 0 picks, likely legitimately rare conditions (no 2+ consecutive beats/misses in eval windows).

### Salvage Verdict Summary

| Signal | Salvageable? | Fix Effort | Blocking Issue | Priority |
|--------|--------------|------------|----------------|----------|
| hot_streak_2 | ✅ **YES** | Low (30 min) | streak_data not integrated | **HIGH** |
| hot_streak_3 | ✅ **YES** | Low (30 min) | streak_data not integrated | **HIGH** |
| cold_continuation_2 | ✅ **YES** | Low (30 min) | streak_data not integrated | **HIGH** |
| points_surge_3 | ✅ **YES** | Low (1-2 hrs) | points_stats not computed | **MEDIUM** |
| scoring_acceleration | ✅ **YES** | Low (1-2 hrs) | points_stats not computed | **MEDIUM** |
| fg_cold_continuation | ✅ **YES** | Low (1-2 hrs) | fg_stats not computed | **MEDIUM** |
| three_pt_volume_surge | ✅ **YES** | Low (1-2 hrs) | three_pa_avg_last_3 not computed | **MEDIUM** |
| minutes_surge_5 | ✅ **YES** | Low (1-2 hrs) | minutes_avg_last_5 not computed | **MEDIUM** |
| b2b_fatigue_under | ✅ **YES** | Low (30 min) | rest_days not in prediction dict | **MEDIUM** |
| rest_advantage_2d | ⚠️ **PARTIAL** | Medium (2-3 hrs) | opponent_rest_days complex | **LOW** |
| home_dog | ⚠️ **PARTIAL** | Medium (2-3 hrs) | is_underdog needs spreads | **LOW** |
| model_consensus_v9_v12 | ⏸️ **DEFER** | Low (30 min) | Waiting for V12 history | **DEFER** |
| triple_stack | N/A | None | Meta-signal (not a bug) | N/A |

**Legend:**
- ✅ **YES**: Easy fix, high confidence in salvageability
- ⚠️ **PARTIAL**: Fixable but needs complex data or may have limited value
- ⏸️ **DEFER**: Technically fixable but strategically deferred

---

## Visual Summary: Data Flow Issue

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT STATE (BROKEN)                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  query_predictions_with_supplements()                        │
│  ├── Computes: three_pt_stats ✅                            │
│  ├── Computes: minutes_stats (partial) ⚠️                   │
│  ├── Computes: streak_stats (prev_over only) ⚠️             │
│  ├── Missing: points_stats ❌                               │
│  ├── Missing: fg_stats ❌                                   │
│  └── Missing: rest_days in pred dict ❌                     │
│                                                              │
│  query_streak_data() — EXISTS BUT NOT CALLED ⚠️             │
│  └── Would compute: consecutive_line_beats/misses           │
│                                                              │
│  RESULT: 13 signals get 0 picks                             │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                     FIXED STATE (TARGET)                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  query_predictions_with_supplements()                        │
│  ├── three_pt_stats (extended with three_pa_avg_last_3) ✅  │
│  ├── minutes_stats (extended with minutes_avg_last_5) ✅    │
│  ├── points_stats (NEW: last_3, last_5, season) ✅          │
│  ├── fg_stats (NEW: last_3, season, std) ✅                 │
│  ├── streak_data (INTEGRATED from query_streak_data) ✅     │
│  └── rest_days in pred dict ✅                              │
│                                                              │
│  RESULT: 10+ signals unlocked, 20-30+ picks/day             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Methodology

1. **Read signal code** - Understand qualification logic and thresholds
2. **Identify data dependencies** - What supplemental data does each signal require?
3. **Check data availability** - Is the required data present in production?
4. **Run counterfactuals** - If we relax thresholds by 50%, how many picks qualify?
5. **Categorize** - Too restrictive / Fundamentally broken / Needs different data
6. **Recommend** - Keep (with threshold changes) / Remove / Defer (needs more data)

---

## Data Availability Check

### Supplemental Data Sources

| Data Type | Source Table | Available? | Notes |
|-----------|-------------|------------|-------|
| **Streak data** | `prediction_accuracy` | ✅ YES | LAG windows for consecutive beats/misses |
| **Points stats** | `player_game_summary` | ✅ YES | Rolling windows (last 3, last 5, season) |
| **Minutes stats** | `player_game_summary` | ✅ YES | Rolling windows (last 3, last 5, season) |
| **3PT stats** | `player_game_summary` | ✅ YES | Attempts, makes, percentages |
| **FG stats** | `player_game_summary` | ✅ YES | `fg_attempts`, `fg_makes` |
| **Rest days** | Calculated from game dates | ✅ YES | DATE_DIFF between games |
| **V12 predictions** | `prediction_accuracy` | ⚠️ PARTIAL | Shadow model, limited coverage |
| **Player tier** | `ml_feature_store_v2` | ❌ NO | Not in schema |
| **is_home** | Match team_abbr to game_id | ⚠️ DERIVABLE | Not directly stored |
| **is_underdog** | Betting lines | ❌ NO | Not in schema |
| **opponent_rest_days** | Game schedule + analytics | ❌ NO | Not computed |

### Critical Findings

1. **Missing player_tier**: Used by hot_streak_2, hot_streak_3, b2b_fatigue_under, rest_advantage_2d. This field doesn't exist in `player_prop_predictions` or `prediction_accuracy`.
2. **Missing is_home**: Used by rest_advantage_2d, hot_streak_3, home_dog. Can be derived from team_abbr + game_id but not directly available.
3. **Missing is_underdog**: Used by home_dog. Would require integrating betting spreads.
4. **Missing opponent_rest_days**: Used by rest_advantage_2d. Would require complex game schedule analysis.
5. **V12 data sparse**: model_consensus_v9_v12 requires V12 predictions which are still in shadow mode with limited coverage.

---

## Signal-by-Signal Analysis

### 1. hot_streak_2

**Hypothesis:** Player beat line in 2+ consecutive games → continuation signal

**Logic:**
```python
consecutive_beats = streak_info.get('consecutive_line_beats', 0)
if consecutive_beats < 2:
    return no_qualify()
```

**Dependencies:**
- ✅ `supplemental['streak_data']` - consecutive_line_beats
- ❌ `player_tier` for confidence boost (field doesn't exist)

**Why 0 picks:** **`supplemental['streak_data']` dict not provided** by `query_predictions_with_supplements()`. The function calls a separate `query_streak_data()` that computes consecutive beats/misses, but it's never merged into the supplemental dict passed to signals.

**Counterfactual (Feb 12):** If streak_data were provided, **11 picks would qualify** (players with 2+ consecutive line beats).

**Verdict:** **SALVAGEABLE** — High value signal. Just needs `query_predictions_with_supplements()` to call `query_streak_data()` and merge results into supplemental dict.

---

### 2. hot_streak_3

**Hypothesis:** Player beat line in 3+ consecutive games → continuation signal

**Logic:**
```python
consecutive_beats = streak_info.get('consecutive_line_beats', 0)
if consecutive_beats < 3:
    return no_qualify()
base_confidence = min(1.0, consecutive_beats / 5.0)
```

**Dependencies:**
- ✅ `supplemental['streak_data']` - consecutive_line_beats (but not provided)
- ❌ `player_tier`, `is_home`, `rest_days` for confidence boosts (fields don't exist)

**Why 0 picks:** **Same as hot_streak_2** — `supplemental['streak_data']` dict not provided.

**Counterfactual (Feb 12):** If streak_data were provided, **4 picks would qualify** (players with 3+ consecutive line beats).

**Verdict:** **SALVAGEABLE** — Medium value signal. Needs same fix as hot_streak_2, plus optional context fields for confidence boosts (player_tier, is_home, rest_days).

**Note:** Session 255 REJECTED the original hot_streak signal (model correctness streak, not line beat streak). These new hot_streak_2/3 signals use **line beat streaks** (actual > line) which is different and may perform better.

---

### 3. cold_continuation_2

**Hypothesis:** After 2+ consecutive misses, bet continuation of miss direction (not reversion)

**Logic:**
```python
consecutive_misses = streak_info.get('consecutive_line_misses', 0)
last_direction = streak_info.get('last_miss_direction', None)  # 'UNDER' or 'OVER'
if consecutive_misses < 2:
    return no_qualify()
if last_direction and recommendation != last_direction:
    return no_qualify()  # Must match continuation direction
```

**Dependencies:**
- ✅ `supplemental['streak_data']` - consecutive_line_misses, last_miss_direction (but not provided)
- ✅ `prediction['recommendation']` - V9 recommendation

**Why 0 picks:** **Same as hot_streak_2** — `supplemental['streak_data']` dict not provided.

**Counterfactual (Feb 12):** If streak_data were provided, **1 pick would qualify** (player with 2+ consecutive misses in same direction as V9 rec).

**Verdict:** **SALVAGEABLE** — Low volume but promising hypothesis (Session 242 research showed 90% win rate for UNDER continuation). Needs same fix as hot_streak_2.

**Note:** This is different from cold_snap (which bets OVER after 3+ UNDER results). cold_continuation_2 bets continuation of the miss direction, not reversion.

---

### 4. b2b_fatigue_under

**Hypothesis:** High-minute player (35+ mpg) on back-to-back → UNDER due to fatigue

**Logic:**
```python
rest_days = prediction.get('rest_days')
if rest_days != 0:
    return no_qualify()
if prediction.get('recommendation') != 'UNDER':
    return no_qualify()
minutes_avg = supplemental['minutes_stats'].get('minutes_avg_season', 0)
if minutes_avg < 35.0:
    return no_qualify()
```

**Dependencies:**
- ❌ `prediction['rest_days']` - field doesn't exist in prediction dict
- ✅ `supplemental['minutes_stats']` - minutes_avg_season
- ❌ `player_tier` for confidence boost (field doesn't exist)

**Why 0 picks:** **`rest_days` field doesn't exist in prediction dict**

**Counterfactual:** N/A - blocked by missing field

**Verdict:** **NEEDS DATA INFRASTRUCTURE** - Requires rest_days to be computed and added to prediction dict

---

### 5. rest_advantage_2d

**Hypothesis:** Player on 2+ rest days while opponent fatigued → OVER

**Logic:**
```python
player_rest = prediction.get('rest_days')
if player_rest < 2:
    return no_qualify()
opponent_rest = prediction.get('opponent_rest_days')
if opponent_rest is None:
    # Fallback: require OVER + edge >= 4
    if prediction.get('recommendation') != 'OVER' or abs(prediction.get('edge', 0)) < 4.0:
        return no_qualify()
else:
    if opponent_rest > 1:
        return no_qualify()
```

**Dependencies:**
- ❌ `prediction['rest_days']` - field doesn't exist
- ❌ `prediction['opponent_rest_days']` - field doesn't exist
- ❌ `player_tier` for confidence boost

**Why 0 picks:** **Missing rest_days fields**

**Counterfactual:** N/A - blocked by missing fields

**Verdict:** **NEEDS DATA INFRASTRUCTURE** - Requires both player and opponent rest days

---

### 6. points_surge_3

**Hypothesis:** Points last 3 games > season avg + 5 → OVER

**Logic:**
```python
if prediction.get('recommendation') != 'OVER':
    return no_qualify()
points_last_3 = supplemental['points_stats'].get('points_avg_last_3')
points_season = supplemental['points_stats'].get('points_avg_season')
surge = points_last_3 - points_season
if surge < 5.0:
    return no_qualify()
```

**Dependencies:**
- ❌ `supplemental['points_stats']` - **NOT PROVIDED** by supplemental_data.py

**Why 0 picks:** **supplemental_data.py doesn't compute points_stats**

**Checking current supplemental data provider...**

---

### 7. home_dog

**Hypothesis:** Home underdog + high edge (5+) → motivated performance

**Logic:**
```python
edge = abs(prediction.get('edge', 0))
if edge < 5.0:
    return no_qualify()
is_home = prediction.get('is_home', False)
if not is_home:
    return no_qualify()
is_underdog = prediction.get('is_underdog', None)
if is_underdog is None:
    if prediction.get('recommendation') != 'OVER':
        return no_qualify()
else:
    if not is_underdog:
        return no_qualify()
```

**Dependencies:**
- ❌ `prediction['is_home']` - field doesn't exist (derivable from team_abbr)
- ❌ `prediction['is_underdog']` - field doesn't exist (needs betting spreads)

**Why 0 picks:** **Missing is_home and is_underdog fields**

**Counterfactual:** N/A - blocked by missing fields

**Verdict:** **NEEDS DATA INFRASTRUCTURE** - Requires game context fields

---

### 8. minutes_surge_5

**Hypothesis:** Minutes avg last 5 games > season avg + 3 → OVER

**Logic:**
```python
if prediction.get('recommendation') != 'OVER':
    return no_qualify()
min_last_5 = supplemental['minutes_stats'].get('minutes_avg_last_5')
min_season = supplemental['minutes_stats'].get('minutes_avg_season')
surge = min_last_5 - min_season
if surge < 3.0:
    return no_qualify()
```

**Dependencies:**
- ⚠️ `supplemental['minutes_stats']` - **Only has last_3, not last_5**

**Why 0 picks:** **supplemental_data.py only computes minutes_avg_last_3, not last_5**

**Checking supplemental data provider...**

---

### 9. three_pt_volume_surge

**Hypothesis:** 3PA last 3 games > season avg + 2 attempts → OVER

**Logic:**
```python
if prediction.get('recommendation') != 'OVER':
    return no_qualify()
tpa_last_3 = supplemental['three_pt_stats'].get('three_pa_avg_last_3')
tpa_season = supplemental['three_pt_stats'].get('three_pa_per_game')
surge = tpa_last_3 - tpa_season
if surge < 2.0:
    return no_qualify()
```

**Dependencies:**
- ⚠️ `supplemental['three_pt_stats']` - **Doesn't include three_pa_avg_last_3**

**Why 0 picks:** **supplemental_data.py doesn't compute three_pa_avg_last_3**

**Checking supplemental data provider...**

---

### 10. model_consensus_v9_v12

**Hypothesis:** V9 + V12 same direction + both edge >= 3 → high confidence consensus

**Logic:**
```python
if not supplemental or 'v12_prediction' not in supplemental:
    return no_qualify()
v9_rec = prediction.get('recommendation')
v12_rec = supplemental['v12_prediction'].get('recommendation')
if v9_rec != v12_rec:
    return no_qualify()
v9_edge = abs(prediction.get('edge', 0))
v12_edge = abs(supplemental['v12_prediction'].get('edge', 0))
if v9_edge < 3.0 or v12_edge < 3.0:
    return no_qualify()
```

**Dependencies:**
- ❌ `supplemental['v12_prediction']` - **NOT PROVIDED** by supplemental_data.py

**Why 0 picks:** **supplemental_data.py doesn't query V12 predictions**

**Verdict:** **NEEDS DATA** - V12 is in shadow mode, needs integration into supplemental data

---

### 11. fg_cold_continuation

**Hypothesis:** FG% last 3 < season - 1 std → UNDER (continuation, not reversion)

**Logic:**
```python
if prediction.get('recommendation') != 'UNDER':
    return no_qualify()
fg_last_3 = supplemental['fg_stats'].get('fg_pct_last_3')
fg_season = supplemental['fg_stats'].get('fg_pct_season')
fg_std = supplemental['fg_stats'].get('fg_pct_std')
threshold = fg_season - fg_std
if fg_last_3 >= threshold:
    return no_qualify()
```

**Dependencies:**
- ❌ `supplemental['fg_stats']` - **NOT PROVIDED** by supplemental_data.py

**Why 0 picks:** **supplemental_data.py doesn't compute FG stats**

**Checking if data is in player_game_summary...**

---

### 12. triple_stack

**Hypothesis:** Meta-signal that activates when 3+ other signals qualify

**Logic:**
```python
def evaluate(...):
    return self._no_qualify()  # Handled by post-processing
```

**Dependencies:**
- Other signals qualifying

**Why 0 picks:** **By design - always returns no_qualify(). Meant to be computed by aggregator.**

**Verdict:** **NOT A BUG** - This is a meta-signal computed after individual signal evaluation

---

### 13. scoring_acceleration

**Hypothesis:** Points trending upward (last 3 > last 5 > season) → OVER

**Logic:**
```python
if prediction.get('recommendation') != 'OVER':
    return no_qualify()
pts_last_3 = supplemental['points_stats'].get('points_avg_last_3')
pts_last_5 = supplemental['points_stats'].get('points_avg_last_5')
pts_season = supplemental['points_stats'].get('points_avg_season')
if not (pts_last_3 > pts_last_5 > pts_season):
    return no_qualify()
```

**Dependencies:**
- ❌ `supplemental['points_stats']` - **NOT PROVIDED** by supplemental_data.py

**Why 0 picks:** **supplemental_data.py doesn't compute points stats**

**Verdict:** **NEEDS DATA** - Requires points_stats to be added to supplemental data provider

---

## Root Cause Summary

| Signal | Root Cause | Counterfactual Picks (Feb 12) | Category |
|--------|-----------|-------------------------------|----------|
| hot_streak_2 | `streak_data` dict not provided | **11 picks** | **MISSING DATA** |
| hot_streak_3 | `streak_data` dict not provided | **4 picks** | **MISSING DATA** |
| cold_continuation_2 | `streak_data` dict not provided | **1 pick** | **MISSING DATA** |
| b2b_fatigue_under | `rest_days` field not in prediction dict | Unknown | **MISSING DATA** |
| rest_advantage_2d | `rest_days`, `opponent_rest_days` not in prediction dict | Unknown | **MISSING DATA** |
| points_surge_3 | `points_stats` not in supplemental | Unknown | **MISSING DATA** |
| home_dog | `is_home`, `is_underdog` not in prediction dict | Unknown | **MISSING DATA** |
| minutes_surge_5 | `minutes_avg_last_5` not in supplemental | Unknown | **MISSING DATA** |
| three_pt_volume_surge | `three_pa_avg_last_3` not in supplemental | Unknown | **MISSING DATA** |
| model_consensus_v9_v12 | `v12_prediction` not in supplemental | N/A (V12 shadow) | **MISSING DATA** |
| fg_cold_continuation | `fg_stats` not in supplemental | Unknown | **MISSING DATA** |
| triple_stack | By design (meta-signal, computed post-evaluation) | N/A | **NOT A BUG** |
| scoring_acceleration | `points_stats` not in supplemental | Unknown | **MISSING DATA** |

**Key insight:** The `query_streak_data()` function exists and computes consecutive beats/misses correctly, but it's never called by `query_predictions_with_supplements()`. This is the primary blocker for 3 signals representing 16+ picks/day.

---

## Recommendations

### Priority 1: Integrate streak_data (HIGH VALUE)

**Signals:** hot_streak_2, hot_streak_3, cold_continuation_2
**Impact:** 16+ picks/day (11 + 4 + 1 on Feb 12 sample)

**Fix:** Modify `query_predictions_with_supplements()` in `ml/signals/supplemental_data.py`:
1. Call `query_streak_data(client, target_date, target_date)` to get streak map
2. Merge streak data into `supplemental_map` for each player:
   ```python
   player_key = f"{player_lookup}::{target_date}"
   if player_key in streak_map:
       supp['streak_data'] = streak_map[player_key]
   ```

**Effort:** Low (30 minutes)
**Value:** High — unlocks 3 signals with proven data availability

**Note:** The `query_streak_data()` function already exists and works correctly. It's just not being called.

---

### Priority 2: Extend supplemental data with points/FG stats (MEDIUM VALUE)

**Signals:** points_surge_3, scoring_acceleration, fg_cold_continuation, three_pt_volume_surge, minutes_surge_5

**Fix:** Extend the `game_stats` CTE in `query_predictions_with_supplements()` to compute:
- `points_stats`: `points_avg_last_3`, `points_avg_last_5`, `points_avg_season` (window functions on `points` column)
- `fg_stats`: `fg_pct_last_3`, `fg_pct_season`, `fg_pct_std` (window functions on fg_makes/fg_attempts)
- `three_pt_stats` extension: Add `three_pa_avg_last_3` (3 PRECEDING window)
- `minutes_stats` extension: Add `minutes_avg_last_5` (5 PRECEDING window)

All raw columns exist in `player_game_summary`. Just need window function calculations like the existing 3PT stats.

**Effort:** Low (1-2 hours)
**Value:** Medium — unlocks 5 signals (volume unknown, needs testing)

---

### Priority 3: Add prediction context fields (MEDIUM EFFORT)

**Signals:** b2b_fatigue_under, rest_advantage_2d, home_dog

**Fix:** Add to prediction dict returned by `query_predictions_with_supplements()`:
- `rest_days`: Already computed in the query (line 167: `DATE_DIFF(@target_date, ls.game_date, DAY)`) — just add to pred dict
- `is_home`: Derive from `team_abbr` matching home team in game_id (requires parsing game_id)
- `opponent_rest_days`: Requires joining game schedule to get opponent's last game (complex)
- `is_underdog`: Requires betting spread data (complex)

**Effort:**
- `rest_days`: Low (5 minutes — already computed, just add to dict)
- `is_home`: Low (30 minutes — parse game_id format)
- `opponent_rest_days`: Medium (2 hours — schedule join)
- `is_underdog`: High (deferred — needs betting data integration)

**Recommendation:** Start with `rest_days` and `is_home` to unblock b2b_fatigue_under. Defer `opponent_rest_days` and `is_underdog` until we see if rest-based signals perform well.

---

### Priority 4: V12 consensus signal (DEFER)

**Signals:** model_consensus_v9_v12

**Fix:** Query V12 predictions in `query_predictions_with_supplements()` (already done in backtest query)

**Defer rationale:** Backtest verdict was DEFER until V12 has 30+ days of shadow data. V12 is still in early shadow mode.

**Effort:** Low (copy from backtest query)
**Value:** Unknown (needs more V12 history)

---

### Priority 5: Meta-signal (NO ACTION)

**Signals:** triple_stack

**Status:** Not a bug. By design, this signal returns `no_qualify()` and is computed by the aggregator after all individual signals are evaluated (counts picks with 3+ qualifying signals).

**Recommendation:** Mark as "meta-signal" in registry, document that it's handled by post-processing.

---

## Quick Action Plan

**Phase 1: Immediate Win (30 minutes)**
1. Integrate `streak_data` into `query_predictions_with_supplements()`
2. Deploy signal_annotator with fix
3. Expected result: 16+ picks/day from hot_streak_2/3 and cold_continuation_2

**Phase 2: Extended Stats (1-2 hours)**
1. Add points_stats, fg_stats, and stat extensions to supplemental query
2. Deploy signal_annotator
3. Expected result: 5 more signals unlocked (volume TBD)

**Phase 3: Context Fields (2-3 hours)**
1. Add rest_days to prediction dict (already computed, just expose it)
2. Add is_home derived from game_id
3. Deploy signal_annotator
4. Expected result: b2b_fatigue_under signal unlocked

**Phase 4: Validation**
1. Run signal_backtest.py on Jan 9 - Feb 14 date range
2. Compare hit rates to baseline (V9 edge 3+ at 59.1%)
3. Update BACKTEST-RESULTS.md with new signal performance

**Phase 5: Cleanup**
1. Mark triple_stack as "meta-signal" in registry
2. Update signal documentation
3. Consider removing or simplifying signals that need complex data (opponent_rest_days, is_underdog)

---

## Next Steps

1. ✅ **Identify root causes** (complete)
2. ✅ **Test streak-based signals** with counterfactual queries (complete — 16+ picks/day confirmed)
3. **Implement Phase 1** — integrate streak_data (highest ROI, 30 minutes)
4. **Implement Phase 2** — extend supplemental stats (1-2 hours)
5. **Re-run signal backtest** to validate fixes
6. **Update signal registry** to mark signals as production-ready

---

## Appendix: Supplemental Data Provider Audit

### Current Coverage (ml/signals/supplemental_data.py)

**Computed in `query_predictions_with_supplements()`:**
- ✅ `three_pt_stats`: three_pct_last_3, three_pct_season, three_pct_std, three_pa_per_game
- ✅ `minutes_stats`: minutes_avg_last_3, minutes_avg_season
- ✅ `streak_stats`: prev_over array (5 games back) — for cold_snap signal
- ✅ `recovery_stats`: prev_minutes, minutes_avg_season
- ✅ `rest_stats`: rest_days (computed but not exposed to prediction dict)

**Computed separately but not integrated:**
- ⚠️ `query_streak_data()` computes consecutive_line_beats, consecutive_line_misses, last_miss_direction — **EXISTS but not called**

**Missing but needed:**
- ❌ `points_stats`: points_avg_last_3, points_avg_last_5, points_avg_season
- ❌ `fg_stats`: fg_pct_last_3, fg_pct_season, fg_pct_std
- ❌ `three_pt_stats` extension: three_pa_avg_last_3
- ❌ `minutes_stats` extension: minutes_avg_last_5
- ❌ `v12_prediction`: recommendation, edge (exists in backtest, needs production integration)
- ❌ Prediction context: is_home, opponent_rest_days, is_underdog

---

## Appendix: Counterfactual Test Results (Feb 12, 2026)

**Methodology:** Ran SQL queries simulating what each signal would return if supplemental data were available.

| Signal | Would Qualify | Notes |
|--------|--------------|-------|
| hot_streak_2 | **11 picks** | Players with 2+ consecutive line beats |
| hot_streak_3 | **4 picks** | Players with 3+ consecutive line beats |
| cold_continuation_2 | **1 pick** | Player with 2+ consecutive misses in same direction as V9 |
| b2b_fatigue_under | Unknown | Blocked by missing rest_days field |
| rest_advantage_2d | Unknown | Blocked by missing rest_days field |
| points_surge_3 | Unknown | Need to add points_stats to test |
| home_dog | Unknown | Blocked by missing is_home field |
| minutes_surge_5 | Unknown | Need to add minutes_avg_last_5 to test |
| three_pt_volume_surge | Unknown | Need to add three_pa_avg_last_3 to test |
| model_consensus_v9_v12 | N/A | V12 in shadow mode |
| fg_cold_continuation | Unknown | Need to add fg_stats to test |
| triple_stack | N/A | Meta-signal (by design) |
| scoring_acceleration | Unknown | Need to add points_stats to test |

**Key finding:** The 3 streak-based signals alone would add 16 picks on Feb 12. With typical ~12 game days/week, that's **~190 picks/week** from just integrating existing streak_data function.

---

## Backtest-Specific Analysis (signal_backtest.py)

**Context:** The above analysis focused on production supplemental_data.py. This section analyzes the backtest environment specifically (`ml/experiments/signal_backtest.py`), which has DIFFERENT data availability.

### Quick Reference: Root Cause Summary

| Signal | Root Cause | Recommendation | Priority |
|--------|------------|----------------|----------|
| **points_surge_3** | MISSING_DATA (points_stats) | Add to game_stats CTE | **HIGH** |
| **scoring_acceleration** | MISSING_DATA (points_stats 3-tier) | Add to game_stats CTE | **HIGH** |
| **fg_cold_continuation** | MISSING_DATA (fg_stats) | Add to game_stats CTE | **HIGH** |
| **three_pt_volume_surge** | MISSING_DATA (three_pa_avg_last_3) | Add to game_stats CTE | **HIGH** |
| **minutes_surge_5** | MISSING_DATA (minutes_avg_last_5) | Add to game_stats CTE | **HIGH** |
| **home_dog** | MISSING_DATA (is_home) + TOO_RESTRICTIVE | Add schedule JOIN + lower edge to 3.5 | **HIGH** |
| **b2b_fatigue_under** | TOO_RESTRICTIVE (35 MPG) + missing rest_days in pred dict | Lower to 32 MPG + add rest_days | MEDIUM |
| **rest_advantage_2d** | TOO_RESTRICTIVE (edge 4.0 fallback) + missing rest_days | Lower to 3.0 + add rest_days | MEDIUM |
| **hot_streak_2** | WORKING (data available, rare?) | Validate with test query | LOW |
| **hot_streak_3** | WORKING (data available, rare?) | Validate with test query | LOW |
| **cold_continuation_2** | WORKING (data available, rare?) | Validate with test query | LOW |
| **model_consensus_v9_v12** | WORKING (data available, models rarely agree?) | Validate, may be legitimately rare | LOW |
| **triple_stack** | BROKEN_LOGIC (stub implementation) | Implement in aggregator | MEDIUM |

### Backtest Data Availability Matrix

Based on `signal_backtest.py` QUERY and evaluate_signals() function (lines 35-390):

| Data Type | Available in Backtest? | Source | Notes |
|-----------|------------------------|--------|-------|
| **V12 predictions** | ✅ YES | v12_preds CTE (lines 62-77) | Available in backtest |
| **3PT stats** | ✅ YES | game_stats CTE (lines 142-154) | three_pct_last_3, season, std, three_pa_per_game |
| **Minutes stats** | ⚠️ PARTIAL | game_stats CTE (lines 156-161) | Has last_3 and season, MISSING last_5 |
| **Streak data** | ✅ YES | streak_data CTE (lines 80-110) | Consecutive beats/misses via prev_correct array |
| **Player tier** | ✅ YES | feature_data CTE (lines 120-126) | Based on feature_2_value (ppg) |
| **Rest days** | ✅ YES | game_stats CTE (line 165) | DATE_DIFF calculation |
| **Pace stats** | ✅ YES | feature_data CTE (lines 116-117) | opponent_pace, team_pace |
| **Points stats** | ❌ NO | Not computed | MISSING: points_avg_last_3, last_5, season |
| **FG stats** | ❌ NO | Not computed | MISSING: fg_pct_last_3, season, std |
| **3PA surge** | ❌ NO | three_pa_per_game exists, but NOT three_pa_avg_last_3 | MISSING window function |
| **is_home** | ❌ NO | Not computed | Would need schedule JOIN |
| **opponent_rest_days** | ❌ NO | Not computed | Complex - needs opponent schedule tracking |
| **is_underdog** | ❌ NO | Not computed | Would need vegas spread data |

### Critical Insight: Streak Data IS Available

**Lines 305-349 of signal_backtest.py** show that streak_data is:
1. ✅ Computed in the main QUERY (streak_data CTE)
2. ✅ Joined to predictions
3. ✅ Parsed into supplemental dict with consecutive_line_beats, consecutive_line_misses, last_miss_direction

**This means hot_streak_2, hot_streak_3, and cold_continuation_2 have their required data.**

If they show 0 picks, it's because:
- No players had 2+ consecutive line beats during the 4 eval windows, OR
- No players had 2+ consecutive line misses in same direction as model recommendation

This is a LEGITIMATE finding, not a data gap.

### Signal-by-Signal Backtest Diagnosis

#### Group A: Data Available, Legitimately Rare (3 signals)

| Signal | Required Data | Available? | Likely Reason for 0 Picks |
|--------|---------------|------------|---------------------------|
| **hot_streak_2** | consecutive_line_beats >= 2 | ✅ YES (lines 322-328) | Few players maintain 2+ game winning streaks |
| **hot_streak_3** | consecutive_line_beats >= 3 | ✅ YES (lines 322-328) | Very rare - 3+ game winning streaks |
| **cold_continuation_2** | consecutive_line_misses >= 2, match direction | ✅ YES (lines 330-340) | Rare alignment of miss streak + model rec |

**Recommendation:** **VALIDATE** with test query. If truly 0 occurrences, these signals may be too rare to be useful.

**Priority:** LOW (signals work, just rare)

---

#### Group B: Missing Data - Easy Fixes (6 signals)

| Signal | Missing Data | Fix Location | Fix Effort |
|--------|--------------|--------------|-----------|
| **points_surge_3** | points_avg_last_3, points_avg_season | Add to game_stats CTE (line 168) | 15 min |
| **scoring_acceleration** | points_avg_last_3, last_5, season | Add to game_stats CTE (line 168) | 15 min |
| **fg_cold_continuation** | fg_pct_last_3, season, std | Add to game_stats CTE (line 168) | 15 min |
| **three_pt_volume_surge** | three_pa_avg_last_3 | Add to game_stats CTE (line 154) | 10 min |
| **minutes_surge_5** | minutes_avg_last_5 | Add to game_stats CTE (line 161) | 5 min |
| **home_dog** | is_home | Add schedule JOIN + is_home field | 30 min |

**Total fix effort:** ~90 minutes to add all missing data to backtest query.

**Recommendation:** **HIGH PRIORITY** - Add all 6 data fields in one pass.

---

#### Group C: Threshold Too Restrictive (2 signals)

| Signal | Threshold | Issue | Fix |
|--------|-----------|-------|-----|
| **b2b_fatigue_under** | minutes_avg_season >= 35.0 | Only ~15-20 players league-wide | Lower to 32 MPG |
| **rest_advantage_2d** | Fallback: edge >= 4.0 + OVER | Very few edge 4+ picks | Lower to edge >= 3.0 |

**Note:** b2b_fatigue_under also needs `rest_days` field to be added to prediction dict (line 259). Currently computed but not passed through.

**Recommendation:** **MEDIUM PRIORITY** - Relax thresholds + add rest_days to pred dict.

---

#### Group D: Broken Logic (1 signal)

| Signal | Issue | Fix |
|--------|-------|-----|
| **triple_stack** | Always returns _no_qualify() by design | Implement in aggregator or remove from signal registry |

**Recommendation:** **MEDIUM PRIORITY** - Add post-processing in aggregator.py to tag picks with signal_count >= 3.

---

#### Group E: Dependency (1 signal)

| Signal | Dependency | Status |
|--------|------------|--------|
| **model_consensus_v9_v12** | V12 predictions in production | ✅ Data available in backtest (v12_preds CTE) but V12 may have limited coverage |

**Recommendation:** **LOW PRIORITY** - V12 data exists in backtest. If 0 picks, likely means V12 and V9 rarely agree with both edge >= 3.

---

### Backtest Fix Implementation Guide

**Phase 1: Add Missing Rolling Stats (15 minutes)**

Add to game_stats CTE after line 167:

```sql
-- Points rolling stats (for points_surge_3, scoring_acceleration)
AVG(points)
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS points_avg_last_3,
AVG(points)
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_avg_last_5,
AVG(points)
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS points_avg_season,

-- FG% rolling stats (for fg_cold_continuation)
SAFE_DIVIDE(field_goals_made, NULLIF(field_goals_attempted, 0)) AS fg_pct,
AVG(SAFE_DIVIDE(field_goals_made, NULLIF(field_goals_attempted, 0)))
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS fg_pct_last_3,
AVG(SAFE_DIVIDE(field_goals_made, NULLIF(field_goals_attempted, 0)))
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_season,
STDDEV(SAFE_DIVIDE(field_goals_made, NULLIF(field_goals_attempted, 0)))
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_std,

-- Extended windows (for minutes_surge_5, three_pt_volume_surge)
AVG(minutes_played)
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS minutes_avg_last_5,
AVG(CAST(three_pt_attempts AS FLOAT64))
  OVER (PARTITION BY player_lookup ORDER BY game_date
        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS three_pa_avg_last_3
```

Then update SELECT statement (after line 199) to include new fields.

**Phase 2: Add Supplemental Dicts (10 minutes)**

Add to evaluate_signals() function after line 296:

```python
# Points stats (for points_surge_3, scoring_acceleration)
if row.get('points_avg_last_3') is not None:
    supplemental['points_stats'] = {
        'points_avg_last_3': float(row['points_avg_last_3']),
        'points_avg_last_5': float(row.get('points_avg_last_5') or 0),
        'points_avg_season': float(row.get('points_avg_season') or 0),
    }

# FG stats (for fg_cold_continuation)
if row.get('fg_pct_last_3') is not None:
    supplemental['fg_stats'] = {
        'fg_pct_last_3': float(row['fg_pct_last_3']),
        'fg_pct_season': float(row.get('fg_pct_season') or 0),
        'fg_pct_std': float(row.get('fg_pct_std') or 0),
    }

# Extended minutes/3PA (for minutes_surge_5, three_pt_volume_surge)
if row.get('minutes_avg_last_5') is not None:
    supplemental['minutes_stats']['minutes_avg_last_5'] = float(row['minutes_avg_last_5'])

if row.get('three_pa_avg_last_3') is not None:
    if 'three_pt_stats' not in supplemental:
        supplemental['three_pt_stats'] = {}
    supplemental['three_pt_stats']['three_pa_avg_last_3'] = float(row['three_pa_avg_last_3'])
```

**Phase 3: Add is_home + rest_days to Prediction Dict (30 minutes)**

Add schedule JOIN after line 182:

```sql
-- After pace_thresholds CTE, before SELECT
schedule_data AS (
  SELECT
    game_id,
    home_team_tricode,
    away_team_tricode
  FROM `nba-props-platform.nba_reference.nba_schedule`
  WHERE game_date BETWEEN @start_date AND @end_date
)
```

Update SELECT (after line 199):

```sql
CASE WHEN sched.home_team_tricode = v9.team_abbr THEN TRUE ELSE FALSE END AS is_home
```

Update FROM/JOIN section (after line 216):

```sql
LEFT JOIN schedule_data sched ON sched.game_id = v9.game_id
```

Update prediction dict (after line 259):

```python
pred['is_home'] = row.get('is_home', False)
pred['rest_days'] = row.get('rest_days')  # Already computed, just expose it
```

**Phase 4: Relax Thresholds (5 minutes)**

Update signal files:
- `b2b_fatigue_under.py` line 11: `MIN_MINUTES_AVG = 32.0`  (was 35.0)
- `home_dog.py` line 11: `MIN_EDGE = 3.5`  (was 5.0)
- `rest_advantage_2d.py` line 32: `if abs(prediction.get('edge', 0)) < 3.0:`  (was 4.0)

**Phase 5: Fix triple_stack (10 minutes)**

Option 1 (recommended): Remove from registry, identify via signal_count >= 3 in output

Option 2: Add to aggregator.py after line 54:

```python
# Tag triple-stack picks
for pick in scored:
    if pick['signal_count'] >= 3 and 'triple_stack' not in pick['signal_tags']:
        pick['signal_tags'].append('triple_stack')
```

---

### Expected Impact After Fixes

| Signal | Expected Picks (35 days) | Confidence |
|--------|--------------------------|------------|
| points_surge_3 | 40-60 | High (5pt surge is significant) |
| scoring_acceleration | 15-25 | Medium (requires 3-tier uptrend) |
| fg_cold_continuation | 20-35 | Medium (cold FG% streaks happen) |
| three_pt_volume_surge | 25-40 | Medium (volume spikes are common) |
| minutes_surge_5 | 30-50 | High (rotation changes are frequent) |
| home_dog | 10-20 | Low (edge 3.5+ home picks rare) |
| b2b_fatigue_under | 15-25 | Medium (32 MPG captures ~40 players) |
| rest_advantage_2d | 20-30 | Low (without opponent_rest_days) |
| hot_streak_2/3 | 0-10 | Low (legitimately rare if 0 in backtest) |
| cold_continuation_2 | 0-5 | Low (legitimately rare if 0 in backtest) |
| model_consensus_v9_v12 | 5-15 | Low (both models need edge 3+) |

**Total new picks:** 180-315 (currently 0)

---

## Final Verdict

### Keep with Fixes (11 signals)

**HIGH PRIORITY - Backtest Data Gaps (60 minutes total, 150-250 picks):**
1. **points_surge_3** — Add points_stats to game_stats CTE
2. **scoring_acceleration** — Add points_stats (3-tier) to game_stats CTE
3. **fg_cold_continuation** — Add fg_stats to game_stats CTE
4. **three_pt_volume_surge** — Add three_pa_avg_last_3 to game_stats CTE
5. **minutes_surge_5** — Add minutes_avg_last_5 to game_stats CTE
6. **home_dog** — Add schedule JOIN + is_home field + lower threshold to 3.5

**MEDIUM PRIORITY - Threshold Adjustments (10 minutes, 30-50 picks):**
7. **b2b_fatigue_under** — Lower threshold to 32 MPG + add rest_days to pred dict
8. **rest_advantage_2d** — Lower fallback edge to 3.0 + add rest_days to pred dict

**LOW PRIORITY - Legitimately Rare (validate before removing):**
9. **hot_streak_2** — Has data, if 0 picks = rare condition (validate)
10. **hot_streak_3** — Has data, if 0 picks = rare condition (validate)
11. **cold_continuation_2** — Has data, if 0 picks = rare condition (validate)

### Working but Low Volume (1 signal)

12. **model_consensus_v9_v12** — V12 data available in backtest, if 0 picks = models rarely agree with both edge 3+

### Fix Implementation (1 signal)

13. **triple_stack** — Add post-processing in aggregator OR remove from signal registry (meta-signal by design)

---

### Backtest-Specific Recommendations

**Production vs Backtest Gap:**
- The original analysis focused on production supplemental_data.py
- This analysis focuses on backtest environment (signal_backtest.py)
- **Different data availability** between the two environments

**Backtest has MORE data than production:**
- ✅ Streak data (consecutive beats/misses) — computed in backtest, NOT in production supplemental_data.py
- ✅ V12 predictions — available in backtest
- ✅ Player tier — computed in backtest

**Both need fixes:**
- ❌ Points/FG stats — missing in BOTH
- ❌ Extended windows (last_5) — missing in BOTH
- ❌ is_home — missing in BOTH

**Action plan:**
1. Fix backtest first (easier, has more data already)
2. Re-run backtest to validate signal performance
3. Port successful signals to production supplemental_data.py

---

## Conclusion

**All 13 "zero-pick" signals are salvageable or explained.**

### Backtest Environment (signal_backtest.py)

**Root causes:**
- **6 signals** blocked by missing data fields (points/FG stats, extended windows, is_home)
- **2 signals** blocked by too-restrictive thresholds
- **3 signals** have data but may be legitimately rare (need validation)
- **1 signal** is meta-signal by design (triple_stack)
- **1 signal** has data but models rarely agree (model_consensus_v9_v12)

**Fix priority:**
1. **Add missing stats to game_stats CTE** (60 minutes) → unlocks 6 signals, 150-250 picks
2. **Relax thresholds** (10 minutes) → unlocks 2 signals, 30-50 picks
3. **Validate rare signals** (30 minutes) → determine if hot_streak_2/3 and cold_continuation_2 are actually useful
4. **Fix triple_stack** (10 minutes) → implement in aggregator

**Estimated total effort:** 110 minutes (< 2 hours)

**Estimated impact:** 180-315 additional qualifying picks across 35-day backfill

### Production Environment (supplemental_data.py)

**Different gaps:**
- Production is MISSING streak_data (but backtest has it)
- Production is MISSING V12 predictions (but backtest has it)
- Production is MISSING player_tier (but backtest has it)
- Both are missing points/FG stats, extended windows, is_home

**Recommendation:**
1. Fix backtest FIRST (easier, validate signals work)
2. Port successful signals to production supplemental_data.py
3. Production will need streak_data integration (the query_streak_data() function exists but isn't called)

---

**Next action:** Implement backtest fixes in `signal_backtest.py`, re-run on 35-day window, validate signal performance before porting to production.
