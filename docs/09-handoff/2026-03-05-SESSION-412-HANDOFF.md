# Session 412 Handoff — True Pick Locking + Daily Regime Context

**Date:** 2026-03-05
**Type:** Bug fix, data integrity, new feature
**Key Insight:** Published picks were being destroyed by re-exports. 19 exports ran for Mar 4, and algorithm deploys mid-day caused picks to disappear. Also: BB HR autocorrelation (r=0.43) now drives daily OVER exposure via regime context.

---

## What This Session Did

### 1. Root Cause: Mar 4 Pick Volatility

Investigation revealed:
- **19 exports ran for a single game date** (Mar 4)
- **KAT UNDER 17.5** was published at 1:16 PM, then dropped at 6:46 PM because algorithm v400→v400b re-evaluated the signal pipeline
- **Jalen Johnson OVER 21.5** appeared for only 77 seconds before being dropped
- **3 different algorithm versions deployed mid-day**, each causing full pipeline re-evaluation
- KAT scored 17 (a **WIN** on his 17.5 UNDER) but was never graded because his row was deleted from `signal_best_bets_picks`

### 2. True Pick Locking Implementation

**Problem:** `SignalBestBetsExporter._write_to_bigquery()` deleted ALL rows for a game date on every re-export, then re-inserted only the picks from the current signal run. The "lock" in `best_bets_published_picks` only preserved metadata — it didn't prevent the signal layer from destroying grading data.

**Fix (two files):**

#### `signal_best_bets_exporter.py` — Scoped DELETE
- **Before:** `DELETE FROM signal_best_bets_picks WHERE game_date = @target_date AND game_id NOT IN (started_games)`
- **After:** Added `AND player_lookup IN UNNEST(@player_lookups)` — only deletes rows for players being refreshed
- Picks no longer in signal output are **preserved** in the table for grading
- Added `_query_existing_pick_lookups()` helper + logging for lock behavior

#### `best_bets_all_exporter.py` — True Active Status
- Published picks that drop from signal now get `signal_status='active'` (not 'dropped')
- Only `game_started` and `model_disabled` get special statuses
- Locked picks rank equally with fresh signal picks (no group 0/1 demotion)
- New pick event types: `locked_retained`, `game_started_removal`
- Grading fallback skips `_locked` picks (they're graded via `_query_all_picks` JOIN)

### 3. Mar 4 Backfill

Re-inserted 2 lost picks into `signal_best_bets_picks`:
- **KAT UNDER 17.5** (scored 17 = WIN) — `lgbm_v12_noveg_vw015_train1215_0208`
- **Jalen Johnson OVER 21.5** (scored 20 = LOSS) — `xgb_v12_noveg_s999_train1215_0208`

Updated their `best_bets_published_picks` status from 'dropped' to 'active'.

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/publishing/signal_best_bets_exporter.py` | Scoped DELETE, `_query_existing_pick_lookups`, lock logging, regime context wiring |
| `data_processors/publishing/best_bets_all_exporter.py` | True active status, no group demotion, new event types, grading fix |
| `ml/signals/regime_context.py` | **NEW** — Query yesterday BB HR, classify regime (cautious/normal/confident) |
| `ml/signals/aggregator.py` | Regime-aware OVER floor (+1.0 during cautious), regime rescue gating, toxic observation → filtered_picks |

## Verification Queries

```sql
-- Check pick count is monotonically non-decreasing across exports
SELECT game_date, COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC;

-- Verify no more 'dropped' status in published picks (post-deploy)
SELECT signal_status, COUNT(*)
FROM `nba-props-platform.nba_predictions.best_bets_published_picks`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1;

-- Check Mar 4 backfill
SELECT player_lookup, recommendation, line_value
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = '2026-03-04'
ORDER BY player_lookup;
-- Should show 9 picks (was 7 before backfill)

-- Check locked pick events
SELECT event_type, COUNT(*)
FROM `nba-props-platform.nba_predictions.best_bets_pick_events`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1;
```

## How It Works Now

```
Export 1: Signal produces 8 picks → all written to signal_best_bets_picks
Export 2: Signal produces 6 of the original + 2 new
    → DELETE only the 8 player_lookups in new output
    → INSERT 8 new rows
    → 2 dropped picks STAY in table (locked)
    → Result: 10 picks total (8 new + 2 preserved)
Export 3: Signal produces 5 of the original
    → DELETE only the 5 player_lookups in new output
    → INSERT 5 new rows
    → 5 dropped picks STAY
    → Result: 10 picks total (monotonically non-decreasing)
```

## What Does NOT Change

- Signal pipeline still runs fresh each export (discovers new picks)
- New picks can be added throughout the day
- Edge/rank/angles still refresh for picks in current signal output
- Grading works automatically (picks persist in `signal_best_bets_picks`)
- Ultra tier gating unchanged
- Disabled model filtering unchanged (happens before BQ write)

---

### 4. Daily Regime Context (BB HR Autocorrelation)

**Background (Session 411):** BB HR autocorrelation r=0.43. After a bad day (<50%), next day averages 53.9%. After a great day (75%+), next day averages 72.2%. OVER HR swings 33-67% by regime while UNDER stays 50%+.

**Implementation:**

| Component | What it does |
|-----------|-------------|
| `ml/signals/regime_context.py` | Queries yesterday's BB HR from `signal_best_bets_picks` ⨝ `prediction_accuracy`, classifies regime |
| Aggregator `regime_context` param | Adjusts OVER edge floor and signal rescue based on regime |

**Regime classification:**
- **cautious** (HR <50%, N≥5): OVER floor raised 5→6, OVER signal rescue disabled
- **normal** (50-74% or N<5): no changes
- **confident** (75%+): no changes (don't loosen — confirms calibration)

**Counterfactual tracking:** Regime-suppressed picks use distinct `filter_reason` values (`regime_over_floor`, `regime_rescue_blocked`) and flow through existing `_record_filtered()` → `best_bets_filtered_picks`. Grading fills in `prediction_correct` automatically.

**Also:** Converted calendar toxic observation mode to write to `filtered_picks` (was only incrementing counters). Now `toxic_starter_over_would_block` and `toxic_star_over_would_block` are recorded for counterfactual grading too.

### Counterfactual Evaluation Query

```sql
-- After 7+ days: did regime filters save us or cost us?
SELECT
  filter_reason,
  COUNT(*) as suppressed,
  COUNTIF(prediction_correct) as would_have_won,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as counterfactual_hr
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason LIKE 'regime_%'
  AND prediction_correct IS NOT NULL
  AND game_date >= '2026-03-06'
GROUP BY 1;
-- If counterfactual_hr > 55% → filter is hurting. If < 50% → filter is saving us.
```

## Next Session

- Monitor first game day with true locking deployed
- Verify pick count doesn't decrease across re-exports
- Check grading works for locked picks
- After 7+ days: evaluate regime counterfactual HR (should be <50% if filter helps)
- Check `best_bets_filtered_picks` for `regime_%` and `toxic_%` entries
