# Session 493 Handoff — Duplicate Picks Root Cause + Long-term Fix Plan

**Date:** 2026-03-26
**Previous session:** Session 492 (GCP cost optimizations)

---

## What Happened

Users saw duplicate picks in the best bets UI for March 25 — every pick appeared 2-3x. Root cause investigation by 9 parallel agents (5 Opus + 4 Sonnet) produced a complete picture of the bug, its scope, and the correct long-term solution.

---

## What Was Fixed This Session

### Immediate fix (already deployed, commit `0b7c4a88`)

Added `AND pa.recommendation = b.recommendation AND pa.line_value = b.line_value` to both LEFT JOINs in `data_processors/publishing/best_bets_all_exporter.py` (lines 274 and 315). Prevents JOIN fan-out when `prediction_accuracy` has multiple rows per `(player_lookup, game_date, system_id)`.

`best-bets/all.json` was manually re-exported immediately after the fix. March 25 now shows 7 picks (was 12). The fix is self-healing for history — every regeneration of `all.json` applies the fixed JOIN retroactively.

**Historical scope:** Only 2 dates were affected — 2026-03-25 (4 of 7 picks duplicated) and 2026-02-02 (1 of 2 picks). No manual backfill needed.

---

## Root Cause (Full Analysis)

### Primary bug: grading processor dedup partition includes `line_value`

**File:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` ~line 570

```sql
-- CURRENT (broken): keeps one row per player/game/system/line
PARTITION BY player_lookup, game_id, system_id, CAST(line_value AS STRING)

-- NEEDED: keep one row per player/game/system (latest line wins)
PARTITION BY player_lookup, game_id, system_id
```

The prediction worker runs multiple times daily as lines move. When Austin Reaves's line goes 23.5 → 24.5 during the day, both predictions are `is_active=TRUE` at some point, and both survive the dedup, producing two rows in `prediction_accuracy`.

### Secondary bug: EXISTS rescue clause too broad (v5.3 fix, ~line 544)

```sql
-- CURRENT (broken): matches all line versions when any BB pick exists
OR EXISTS (
  SELECT 1 FROM signal_best_bets_picks bb
  WHERE bb.player_lookup = p.player_lookup
    AND bb.system_id = p.system_id
    -- missing: AND bb.line_value = p.current_points_line
)
```

When a player has a BB pick for a model, ALL historical inactive line versions of that player/model pass the EXISTS check. Norman Powell had lines 18.5, 19.5, and 20.5 — all three passed → 3 rows in `prediction_accuracy`.

### Why this only affected some players

Players without BB picks: only `is_active=TRUE` rows pass → no duplication.
Players WITH BB picks: all line versions pass the EXISTS → duplicates.

### Key data points from agent analysis

- 854 duplicate groups in `prediction_accuracy` this season (76,748 rows vs 74,514 unique by 3-way key)
- 813 of 854 (95%) are from Nov 2025 – Jan 2026 (grading was worse then)
- March 2026 has only 6 duplicate groups — the v5.0 dedup improved things
- All duplicates for a given date come from a **single grading batch** (identical `graded_at`) — no race condition
- **+6.9pp HR inflation risk** in duplicate groups: `any_correct` HR = 62.6% vs `latest_line` HR = 55.7%
- `is_superseded_prediction` column exists in schema but is 100% NULL — never populated by any code

---

## Scope: All Vulnerable JOIN Locations

22 locations across the codebase JOIN `prediction_accuracy` without `recommendation` + `line_value`.

### HIGH Severity (user-facing outputs — affect W-L record displayed on site)

| File | Lines | Fix |
|------|-------|-----|
| `best_bets_record_exporter.py` | 83-86, 210-213, 308-311 | Add `AND pa.recommendation = b.recommendation AND pa.line_value = b.line_value` |
| `today_best_bets_exporter.py` | 144-147 | Same |
| `admin_dashboard_exporter.py` | 370-373 | Same |
| `admin_picks_exporter.py` | 200-203 | Same |
| `predictions_exporter.py` | 97-101 | Same (uses `current_points_line` alias) |

`best_bets_record_exporter.py` is the most critical — it feeds `best-bets/record.json` (public W-L record and streak). Duplicate rows double-count wins and losses.

### MEDIUM Severity (automated decisions — drive model management)

| File | Lines | Impact |
|------|-------|--------|
| `orchestration/cloud_functions/decay_detection/main.py` | 272, 425, 537 | **Auto-disables models based on inflated/deflated HR** |
| `ml/signals/regime_context.py` | 75 | **TIGHT/LOOSE gates → OVER edge floor** |
| `ml/signals/signal_health.py` | 303, 398 | **HOT/COLD signal weights** |
| `ml/analysis/model_performance.py` | 259, 482 | `model_performance_daily` table |
| `ml/analysis/league_macro.py` | 242 | Has `recommendation` but missing `line_value` |
| `ml/analysis/model_profile.py` | 147, 166 | Model profiling |
| `ml/calibration/edge_calibrator.py` | 195 | Edge calibration |
| `bin/model_family_dashboard.py` | 75 | Model family reporting |
| `bin/replay_per_model_pipeline.py` | 142 | Partial mitigation but still vulnerable |
| `data_processors/ml_feedback/scoring_tier_processor.py` | 264 | MAE calibration |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 1689 | **Most underspecified — missing `system_id` entirely; affects features 55+56** |
| `schemas/bigquery/nba_predictions/v_signal_performance.sql` | 26 | Signal performance BQ view |
| `schemas/bigquery/nba_predictions/v_signal_combo_performance.sql` | 23 | Combo performance BQ view |

### Already correct (reference pattern)
- `best_bets_all_exporter.py` — fixed this session ✓
- `ml/analysis/mlb_league_macro.py` — has `recommendation` (MLB is fine)
- `ml/experiments/quick_retrain.py` and `ml/signals/supplemental_data.py` — already use `ROW_NUMBER` dedup ✓

---

## Long-term Fix Plan

### Layer 1 — Fix the source (grading processor)
**File:** `prediction_accuracy_processor.py`

Two changes:
1. Change dedup partition from `(player_lookup, game_id, system_id, line_value)` to `(player_lookup, game_id, system_id)` in the `deduped` CTE (~line 570)
2. Add `AND bb.line_value = p.current_points_line` to the EXISTS rescue clause (~line 544)
3. Update `_check_for_duplicates` business key to match new dedup semantics

This prevents all future duplicates at the source. After this, only one row per `(player_lookup, game_date, system_id)` ever reaches `prediction_accuracy`.

### Layer 2 — Create `prediction_accuracy_deduped` view
Self-heals historical data, fixes all 854 existing duplicate groups, removes the +6.9pp HR inflation:

```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.prediction_accuracy_deduped` AS
SELECT * EXCEPT(rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date, system_id
      ORDER BY
        CASE WHEN recommendation IN ('OVER','UNDER') THEN 0 ELSE 1 END,
        CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END,
        graded_at DESC
    ) AS rn
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
) WHERE rn = 1
```

Deploy this view first, validate it against clean recent dates, then migrate all 22 consumer files to `prediction_accuracy_deduped`.

### Layer 3 — Fix all HIGH severity exporter JOINs
5 files, 8 JOINs. Add `AND pa.recommendation = b.recommendation AND pa.line_value = b.line_value`. Start with `best_bets_record_exporter.py` — it inflates the public W-L record.

### Layer 4 — Fix MEDIUM severity JOINs
Priority order:
1. `decay_detection/main.py` — 3 JOINs driving automated model disable
2. `regime_context.py` — drives OVER edge floor via TIGHT/LOOSE
3. `signal_health.py` — drives HOT/COLD signal weight multipliers
4. `model_performance.py` — `model_performance_daily` table
5. `feature_extractor.py` — add `system_id` AND `recommendation` AND `line_value`; also needs ROW_NUMBER since it joins to `player_game_summary` without system_id at all

For `v_signal_performance.sql` and `v_signal_combo_performance.sql`: `pick_signal_tags` lacks `recommendation`/`line_value` — needs intermediate join to `signal_best_bets_picks` or a QUALIFY dedup.

### Layer 5 — Detection and prevention

**Pre-export dedup safety net** (add to `best_bets_all_exporter.generate_json()` after `_query_all_picks`):
```python
from collections import Counter
keys = [(p.get('player_lookup'), str(p.get('game_date'))) for p in all_picks]
dupes = {k:v for k,v in Counter(keys).items() if v > 1}
if dupes:
    logger.warning(f"DUPLICATE PICKS DETECTED in _query_all_picks: {len(dupes)} player-date combos. Details: {list(dupes.items())[:5]}")
    seen = set(); deduped = []
    for p in all_picks:
        k = (p.get('player_lookup'), str(p.get('game_date')))
        if k not in seen: seen.add(k); deduped.append(p)
    all_picks = deduped
```

**GCS canary** (add to `pipeline_canary_queries.py`): Download `best-bets/all.json`, check `today` + last 4 weeks, alert if any `player_lookup` appears 2x on the same day. Zero tolerance.

**BQ canary**: Check `prediction_accuracy` for `(player_lookup, game_date, system_id)` groups with >1 OVER/UNDER row. Threshold 50, alert `#canary-alerts`.

### Layer 6 — Structural exporter fixes (lower urgency)

| Issue | File | Fix |
|-------|------|-----|
| `_write_filtered_picks` uses DELETE+streaming insert | `signal_best_bets_exporter.py` ~line 897 | Replace `insert_rows_json()` with `load_table_from_json()` + WRITE_TRUNCATE partition |
| UNION ALL fallback is date-level, not row-level | `best_bets_all_exporter.py` ~line 315 | Make row-level: include published picks only where player is absent from signal picks |
| DELETE failure swallowed, APPEND continues anyway | `signal_best_bets_exporter.py` ~line 679 | Gate: skip APPEND if DELETE fails |

---

## Recommended Execution Order

**PR 1 (done, commit a0a62bf1):** Layer 1 (grading processor dedup fix) + Layer 3 (HIGH severity exporter JOINs) + Layer 2 (create view, no consumer migration yet)

**PR 2:** Migrate all 22 consumers to `prediction_accuracy_deduped` view (requires BQ DDL deploy first)

**PR 3 (done, commit 68f6ab8d):** Layer 4 (MEDIUM severity — decay_detection x3, regime_context, signal_health x2, model_performance x2, league_macro)

**PR 4:** Layer 5 (canaries) + Layer 6 (structural)

---

## Files Changed This Session

| File | Change | Commit |
|------|--------|--------|
| `data_processors/publishing/best_bets_all_exporter.py` | Added `recommendation`+`line_value` to both PA JOINs | `0b7c4a88` |
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Dedup partition fix + EXISTS rescue fix | `a0a62bf1` |
| `schemas/bigquery/nba_predictions/prediction_accuracy_deduped.sql` | New deduped view (Layer 2) | `a0a62bf1` |
| `data_processors/publishing/best_bets_record_exporter.py` | 3 JOINs fixed | `a0a62bf1` |
| `data_processors/publishing/today_best_bets_exporter.py` | 1 JOIN fixed | `a0a62bf1` |
| `data_processors/publishing/admin_dashboard_exporter.py` | 1 JOIN fixed | `a0a62bf1` |
| `data_processors/publishing/admin_picks_exporter.py` | 1 JOIN fixed | `a0a62bf1` |
| `data_processors/publishing/predictions_exporter.py` | 1 JOIN fixed | `a0a62bf1` |
| `orchestration/cloud_functions/decay_detection/main.py` | 3 JOINs fixed | `68f6ab8d` |
| `ml/signals/regime_context.py` | 1 JOIN fixed | `68f6ab8d` |
| `ml/signals/signal_health.py` | 2 JOINs fixed (deduped_pa CTE for pick_signal_tags path) | `68f6ab8d` |
| `ml/analysis/model_performance.py` | 2 JOINs fixed | `68f6ab8d` |
| `ml/analysis/league_macro.py` | 1 JOIN fixed (already had recommendation, added line_value) | `68f6ab8d` |
| `docs/02-operations/session-learnings.md` | Added full prediction_accuracy JOIN pattern section | `68f6ab8d` |

---

## End of Session Checklist

- [x] Root cause identified and documented
- [x] `best_bets_all_exporter.py` fixed and deployed
- [x] `best-bets/all.json` manually re-exported (March 25 shows 7 picks, not 12)
- [x] 9-agent review complete — full scope mapped
- [x] PR 1: Grading processor fix + HIGH severity exporters + view creation (commit a0a62bf1)
- [x] PR 3: MEDIUM severity JOINs — decay_detection, regime_context, signal_health, model_performance, league_macro (commit 68f6ab8d)
- [x] session-learnings.md updated with prediction_accuracy JOIN pattern
- [ ] Verify `best_bets_record_exporter.py` W-L record is not currently inflated (check record.json)
- [ ] Deploy `prediction_accuracy_deduped` view to BigQuery (run the SQL in schemas/bigquery/nba_predictions/prediction_accuracy_deduped.sql)
- [ ] PR 2: Migrate remaining consumers to `prediction_accuracy_deduped` view
- [ ] PR 4: Layer 5 canaries + Layer 6 structural fixes
