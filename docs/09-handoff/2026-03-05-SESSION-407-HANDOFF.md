# Session 407 Handoff — Worker Crash Fix + Single-Source Projections

**Date:** 2026-03-05
**Type:** Bug fix (P0), data source cleanup, verification
**Commit:** `8f52e279` — `fix: worker NoneType crash + single-source projection mode`

---

## What This Session Did

### 1. Found & Fixed P0 Worker Crash (ALL predictions blocked)

**Bug:** `worker.py:1790` — `pred.get('filter_reason', '').startswith(...)` crashes when `filter_reason=None`.
- `dict.get(key, default)` returns `None` (not default) when key exists with value `None`
- The `filter_reason` field defaults to `None` for unfiltered predictions (line 1881)
- When the new models (train0107_0219) were added to the model cache, their predictions triggered this code path
- The crash happens in `process_player_predictions()` BEFORE returning results, so NO predictions are written to BQ

**Impact:** Mar 5 had **0 predictions** across ALL models. The crash affected every player request via Pub/Sub retry loops.

**Fix:** `(pred.get('filter_reason') or '').startswith(...)` — handles both missing key and explicit `None`.

### 2. Diagnosed Projection Source Status

| Source | Verdict | Detail |
|--------|---------|--------|
| NumberFire | WORKING (120 rows/day) | FanDuel Research GraphQL, valid per-game pts |
| FantasyPros | DEAD | Playwright timeout, wrong data type (DFS season totals) |
| Dimers | NOT VIABLE | Page shows generic projections, NOT game-date-specific. SGA/Maxey/Brown had values but weren't playing that day. Angular SPA with no discoverable API. |
| DFF | Already excluded | DFS fantasy points only |

### 3. Switched to Single-Source Projection Mode

With only NumberFire viable, changed projection consensus to single-source:
- **`supplemental_data.py`**: Removed FP and Dimers CTEs from projection query. NumberFire only.
- **`projection_consensus.py`**: MIN_SOURCES_ABOVE/BELOW: 2 → 1. Confidence lowered (0.75→0.70 OVER, 0.70→0.65 UNDER).
- **Disagreement filter**: Requires 2+ sources, so effectively disabled until second source added.

### 4. Fixed Dimers Player Name Concatenation

`_clean_concatenated_name()` was only called for `player_lookup`, not `player_name`. Fixed to clean before returning the record.

### 5. Morning Verification Results

| Check | Result |
|-------|--------|
| Mar 5 predictions | **0** — worker crash (now fixed) |
| New models (train0107_0219) | 0 predictions — crash prevented writes |
| Shadow signals (today) | 0 fires — no predictions to signal on |
| Combo signals (3way/he_ms) | 88.2% HR (15-2) but stopped Feb 11 — edge compression |
| predicted_pace_over | 2 fires Mar 4, awaiting grading |
| Pick volume | 2/day (critically low) |
| Deployment drift | Only legacy nba-phase1-scrapers (expected) |

---

## What Still Needs Investigation (Next Session)

### P0: Verify Worker Fix Works
After deployment completes, verify:
```sql
-- Check Mar 5 predictions exist (run after morning pipeline ~10 AM ET)
SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY 1 ORDER BY 2 DESC

-- Specifically check new models
SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id LIKE '%train0107%'
GROUP BY 1
```

### P1: Why Combo Signals Stopped (88.2% HR!)
`combo_3way` and `combo_he_ms` have **88.2% HR (15-2)** but stopped firing after Feb 11. Even with MIN_EDGE lowered to 3.0, they haven't resumed. Mar 4 had 11 OVER predictions with edge 3+, but combo requires ALL of:
- edge >= 3 ✅ (11 predictions qualify)
- minutes_surge >= 3 (last_3 - season avg minutes) — **UNKNOWN how many qualify**
- confidence >= 0.70 AND not in 88-90% tier — **UNKNOWN**

**Investigation needed:**
```sql
-- Check how many OVER edge 3+ predictions have minutes_surge >= 3
-- This requires checking gamebook data (minutes_avg_last_3 - minutes_avg_season)
-- against the prediction data
```

Or add logging to the combo signal evaluation to see WHY it's not qualifying.

### P1: Projection Consensus Signal Verification
After worker fix deploys:
```sql
SELECT t as signal_tag, COUNT(*) as fires
FROM nba_predictions.signal_best_bets_picks, UNNEST(signal_tags) t
WHERE t LIKE 'projection_consensus%' AND game_date = CURRENT_DATE()
GROUP BY 1
```
With NumberFire providing 120 players and MIN_SOURCES=1, the signal should fire for any player where NumberFire agrees with the model direction.

### P2: Find Second Projection Source
NumberFire-only is fine but fragile. If NumberFire/FanDuel changes their API, we lose the signal entirely. Options:
1. **BettingPros implied totals** — we already scrape `bettingpros_player_points_props`. Check if `line_value` can serve as an implicit "projection" (market-implied expected points).
2. **ESPN Player Props** — may have projections embedded in their props pages.
3. **PrizePicks/Underdog Fantasy** — DFS platforms with player projections.
4. **Action Network** — Has projections but may require auth.

### P2: Sharp Money / DVP / CLV Signals Not Firing
- **sharp_money**: Depends on VSiN data + supplemental_data.py `sharp_lean_map`. VSiN has 14 rows in BQ but signal hasn't fired.
- **dvp_favorable**: DVP data has 510 rows, rank is computed. Signal might need specific rank thresholds.
- **CLV signals**: Table `nba_raw.odds_api_player_props` doesn't exist. Need to find correct table name or check if closing snapshot data is flowing.

### P3: Fleet Diversity Problem
All 145 model pairs have r >= 0.95 (REDUNDANT). The fleet offers zero prediction diversity. This is a fundamental limit — all models trained on same features converge to same predictions.

### P3: Edge Compression Recovery
OVER avg edge: 1.67-2.08 (far below the 3.0 combo floor). UNDER avg edge: 2.91-4.00. Edge compression is post-ASB and may recover as regular season settles. Monitor weekly.

### P3: Experiment Feature Table (from Session 407 plan)
The experiment feature table plan from the previous 407 attempt is still valid:
- Create `ml_feature_store_experiment` in BQ
- Populate with daily-varying features (projection delta, sharp money divergence)
- Need 30+ days of accumulation before testing

---

## Files Changed

| File | Change |
|------|--------|
| `predictions/worker/worker.py:1790` | Fixed NoneType crash: `(x or '').startswith(...)` |
| `ml/signals/supplemental_data.py` | Removed FP/Dimers CTEs, NumberFire-only query |
| `ml/signals/projection_consensus.py` | MIN_SOURCES 2→1, updated docstring |
| `scrapers/projections/dimers_projections.py` | Clean player_name before return |

---

## Key Numbers

| Metric | Value | Notes |
|--------|-------|-------|
| Mar 5 predictions | 0 (pre-fix) | Worker crash blocked everything |
| Mar 4 predictions | 1,078 (11 models) | Normal before new model cache |
| OVER edge 3+ (Mar 4) | 11 predictions | Combo signal should fire on some |
| combo_3way HR | 88.2% (15-2) | Best signal, not firing since Feb 11 |
| Pick volume | 2/day | Target: 4-8/day |
| NumberFire projections | 120 valid/day | Only working projection source |

---

## Don't Do

- Don't remove Dimers/FantasyPros scrapers — they still run but data is excluded from signals
- Don't promote shadow signals — need N >= 30 graded
- Don't relax edge floor below 3.0 — edge 2-3 historically ~52% HR
- Don't add features to production feature store — use experiment table
- Don't remove negative filters — they add +13.7pp value
