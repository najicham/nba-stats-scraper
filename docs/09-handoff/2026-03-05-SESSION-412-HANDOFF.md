# Session 412 Handoff — True Pick Locking + Loss Analysis

**Date:** 2026-03-05
**Type:** Bug fix, data integrity, research
**Key Insight:** Published picks were being destroyed by re-exports. Fixed with scoped DELETE. Loss analysis found a strong blowout/spread signal for OVER picks.

---

## What This Session Did

### 1. True Pick Locking Implementation

**Problem:** `SignalBestBetsExporter._write_to_bigquery()` deleted ALL rows for a game date on every re-export, then re-inserted only picks from the current signal run. 19 exports ran for Mar 4 with 3 different algorithm versions. KAT UNDER 17.5 was published at 1:16 PM, dropped at 6:46 PM, scored 17 (WIN) but was never graded.

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

### 2. Mar 4 Backfill

Re-inserted 2 lost picks into `signal_best_bets_picks` via BQ INSERT:
- **KAT UNDER 17.5** (scored 17 = WIN) — `lgbm_v12_noveg_vw015_train1215_0208`
- **Jalen Johnson OVER 21.5** (scored 20 = LOSS) — `xgb_v12_noveg_s999_train1215_0208`

Updated their `best_bets_published_picks` status from 'dropped' to 'active'.
Mar 4 final record: **4-4** (+1 void Deni Avdija). All 9 picks now in both tables.

### 3. Mar 4 Loss Analysis — Three Agent Deep Dive

Analyzed the 4 losses (Isaiah Joe, Brice Sensabaugh, Scoot Henderson, Jalen Johnson — all OVER). Three parallel agents investigated CV volatility, signal rescue performance, and blowout risk.

#### Finding 1: CV > 30 Filter — FALSE LEAD
- **Original hypothesis:** feature_31 > 30 = volatile scorers with 53.8% HR
- **Agent discovery:** Feature 31 is `minutes_avg_last_10`, NOT coefficient of variation
- The minutes 30-35 bucket's bad HR is entirely a **toxic window artifact** (Feb: 30%, Jan: 70%)
- At raw prediction level (N=10,144), zero correlation between minutes and HR
- **Verdict: DO NOT implement.** Existing CV signals (`consistent_scorer_over`, `volatile_scoring_over`) already cover scoring volatility correctly.

#### Finding 2: Signal Rescue — TOO EARLY TO ACT (N=6)
- Every rescued pick is OVER (bypassing the OVER edge 5.0 floor)
- Rescued: 3-3 (50% HR) vs non-rescued: 80-40 (66.7% HR)
- N=6 is statistically meaningless — can't distinguish from 65% true rate
- Strongest rescue signals (`sharp_book_lean_over`, `high_scoring_environment_over`) haven't failed — losses from `low_line_over` (0-1) and `signal_stack_2plus` (0-1)
- 7 more rescued picks from Mar 5 grading tonight
- **Verdict: Wait for N=25-30 (~2 weeks).** If rescue HR stays below 55%, consider removing `low_line_over` and `volatile_scoring_over` from rescue set (weakest justification: 66.7% at N=6).

#### Finding 3: Blowout/Spread Filter — ACTIONABLE (strongest finding)

| Pre-game Spread | OVER HR | N |
|----------------|---------|---|
| Spread <= 7 | **74.1%** | 58 |
| Spread > 7 | **44.4%** | 18 |

**29.7pp difference.** Corroborated by post-game margin analysis:

| Actual Margin | OVER HR | N |
|--------------|---------|---|
| Normal (<=15) | **73.7%** | 57 |
| Blowout (15+) | **47.6%** | 21 |

Feature `spread_magnitude` (f41) is already in the feature store. Two of the Mar 4 losers (Scoot Henderson spread 9.5, Brice Sensabaugh spread 7.5) would have been caught.

**Caveat:** N=18 for spread>7 OVER is small, but effect size is enormous (29.7pp) and confirmed from two independent angles (pre-game spread + post-game margin).

**Verdict: Implement as negative filter or observation-mode counter.** See next session tasks below.

---

## Status: CODE NOT YET COMMITTED

The pick locking code changes are staged but **not committed or pushed**. Next session must:

```bash
git add CLAUDE.md \
  data_processors/publishing/signal_best_bets_exporter.py \
  data_processors/publishing/best_bets_all_exporter.py \
  docs/01-architecture/best-bets-and-subsets.md \
  docs/02-operations/session-learnings.md \
  docs/09-handoff/2026-03-05-SESSION-412-HANDOFF.md

git commit -m "feat: true pick locking — scoped DELETE preserves locked picks in signal_best_bets_picks

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git push origin main
```

Also untracked (from prior sessions, include if desired):
- `docs/08-projects/current/signal-discovery-framework/SIGNAL-ENVIRONMENT-CORRELATION.md`

## Files Modified

| File | Change |
|------|--------|
| `data_processors/publishing/signal_best_bets_exporter.py` | Scoped DELETE, `_query_existing_pick_lookups`, lock logging |
| `data_processors/publishing/best_bets_all_exporter.py` | True active status, no group demotion, new event types, grading fix |
| `CLAUDE.md` | Added re-exports issue to Common Issues table |
| `docs/01-architecture/best-bets-and-subsets.md` | Added True Pick Locking section |
| `docs/02-operations/session-learnings.md` | Added "Re-exports Destroy Published Picks" entry |

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

-- Check Mar 4 backfill (should show 9 picks)
SELECT player_lookup, recommendation, line_value
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = '2026-03-04'
ORDER BY player_lookup;

-- Monitor spread filter opportunity (after more data accumulates)
SELECT
  CASE WHEN fs.feature_41_value > 7 THEN 'spread > 7' ELSE 'spread <= 7' END as spread_group,
  b.recommendation,
  COUNT(*) as total,
  COUNTIF(
    (b.recommendation = 'OVER' AND pa.actual_points > b.line_value) OR
    (b.recommendation = 'UNDER' AND pa.actual_points < b.line_value)
  ) as wins,
  ROUND(100.0 * COUNTIF(
    (b.recommendation = 'OVER' AND pa.actual_points > b.line_value) OR
    (b.recommendation = 'UNDER' AND pa.actual_points < b.line_value)
  ) / NULLIF(COUNT(*), 0), 1) as hr_pct
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
  ON b.player_lookup = fs.player_lookup AND b.game_date = fs.game_date
WHERE b.game_date >= '2026-01-01' AND pa.actual_points IS NOT NULL
GROUP BY 1, 2 ORDER BY 2, 1;

-- Monitor signal rescue performance (revisit at N=25-30)
SELECT signal_rescued, COUNT(*) as total,
  COUNTIF(
    (b.recommendation = 'OVER' AND pa.actual_points > b.line_value) OR
    (b.recommendation = 'UNDER' AND pa.actual_points < b.line_value)
  ) as wins
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON b.player_lookup = pa.player_lookup AND b.game_date = pa.game_date AND b.system_id = pa.system_id
WHERE b.game_date >= '2026-01-01' AND pa.actual_points IS NOT NULL
GROUP BY 1;
```

## Next Session — Priority Tasks

### 1. COMMIT AND DEPLOY pick locking (see commands above)
Must deploy before tonight's exports. Monitor first game day with true locking.

### 2. Implement `high_spread_over_block` filter
**Decision needed:** observation-mode (logs only) vs active filter.
- **If observation-mode:** Add counter in `aggregator.py` like `toxic_starter_over_would_block` pattern. Record to `filtered_picks` for counterfactual grading. No picks blocked.
- **If active filter:** Add to the 17 existing negative filters in `aggregator.py`. Condition: `recommendation == 'OVER' AND spread_magnitude > 7.0`. Feature `f41` (`spread_magnitude`) needed in prediction dict — verify it flows through `supplemental_data.py`.
- **Reference:** `ml/signals/aggregator.py` lines 174-211 (filter_counts), lines 277-564 (filter logic)

### 3. Monitor signal rescue at N=25-30
After ~2 weeks of data (around Mar 19), re-run rescue analysis. If HR stays below 55%:
- Remove `low_line_over` and `volatile_scoring_over` from rescue set
- Consider tightening `signal_stack_2plus` from 2+ to 3+ real signals

### 4. Verify pick locking post-deploy
Run verification queries above after first re-export cycle. Key check: pick count never decreases between exports for the same game_date.
