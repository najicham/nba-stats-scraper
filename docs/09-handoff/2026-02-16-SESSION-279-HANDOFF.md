# Session 279 Handoff — Pick Provenance + Season Replay Study

**Date:** 2026-02-16
**Focus:** (1) Implement qualifying_subsets + algorithm_version per best bet, (2) Study season replay with subset picks
**Result:** Pick provenance DEPLOYED. Season replay study completed with 3 approaches identified.

---

## What Was Done

### 1. Pick Provenance — qualifying_subsets (DEPLOYED)

Each best bet now includes which Level 1/2 subsets the player-game already appeared in. This makes the 3-layer architecture truly hierarchical — Layer 3 (best bets) now has awareness of Layer 1/2 (per-model and cross-model subsets).

**New file:** `ml/signals/subset_membership_lookup.py`
- Queries `current_subset_picks` for the current materialization version
- Returns dict mapping `player_lookup::game_id` → list of `{subset_id, system_id}`
- Filters out `subset_id='best_bets'` to avoid circular reference

**Modified files:**

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Accepts `qualifying_subsets` dict, attaches to scored picks. Added `ALGORITHM_VERSION` constant. |
| `ml/signals/pick_angle_builder.py` | New angle priority 2: "Appears in N subsets: Top Pick, High Edge All, ..." (fires when 2+ subsets) |
| `data_processors/publishing/signal_best_bets_exporter.py` | Calls lookup, passes to aggregator, writes to JSON + BQ |
| `data_processors/publishing/signal_annotator.py` | Same pattern in `_bridge_signal_picks()` |
| `backfill_jobs/publishing/daily_export.py` | Passes `mat_version_id` to signal best bets exporter |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | 3 new columns |
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | 3 new columns |

**BQ columns added (both tables):**
- `qualifying_subsets STRING` — JSON array of `{subset_id, system_id}`
- `qualifying_subset_count INT64` — count for easy filtering
- `algorithm_version STRING` — e.g., `v279_qualifying_subsets`

**Phase 1:** Observation only — store and display, don't score on subset membership. Phase 2 (after 30 days of data): backtest qualifying_subset_count vs hit rate.

### 2. Season Replay with Biweekly Retraining — Study (DOCUMENTED)

**Location:** `docs/08-projects/current/multi-model-best-bets/03-SEASON-REPLAY-STUDY.md`

Studied how to replay the season (and last season) with biweekly retraining + subset pick generation. Three approaches identified:

| Approach | What | Effort | Result |
|----------|------|--------|--------|
| **A: Extend walkforward (Recommended)** | Add subset filters to `season_walkforward.py` | 2-3 hours | Trains model every 14d, applies all subset definitions, tracks per-subset performance |
| **B: Full pipeline orchestrator** | New tool running real materializer + grading per date | 8-12 hours | Tests real pipeline, but slow + expensive ($10-20/run) |
| **C: Query existing data** | SQL queries against `subset_grading_results` | 30 min | Immediate answers for current season only |

**Recommendation:** Start with C (immediate), then implement A (2-3 hours). A extends the existing `season_walkforward.py` with in-memory subset filtering — no new BQ queries needed.

**Key insight:** The walkforward simulator already bulk-loads all training + eval data in 2 BQ queries, then runs everything in-memory. Adding subset simulation is just applying the same filter definitions (min_edge, direction, top_n) to each cycle's predictions — pure Python, no BQ.

---

## Verification

### Pick provenance
```sql
-- After Feb 19 game day:
SELECT player_name, recommendation, edge,
       qualifying_subsets, qualifying_subset_count,
       algorithm_version, pick_angles
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-02-19'
ORDER BY rank;
```

### Subset performance (Approach C)
```bash
/subset-performance
```

### Walkforward (Approach A — after implementation)
```bash
PYTHONPATH=. python ml/experiments/season_walkforward.py \
    --season-start 2025-11-02 --season-end 2026-02-12 \
    --cadences 14 --window-type expanding
```

---

## Files Created/Modified

| File | Action | Part |
|------|--------|------|
| `ml/signals/subset_membership_lookup.py` | CREATED | Pick provenance |
| `ml/signals/aggregator.py` | MODIFIED | Pick provenance |
| `ml/signals/pick_angle_builder.py` | MODIFIED | Pick provenance |
| `data_processors/publishing/signal_best_bets_exporter.py` | MODIFIED | Pick provenance |
| `data_processors/publishing/signal_annotator.py` | MODIFIED | Pick provenance |
| `backfill_jobs/publishing/daily_export.py` | MODIFIED | Pick provenance |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | MODIFIED | Pick provenance |
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | MODIFIED | Pick provenance |
| `CLAUDE.md` | MODIFIED | Docs |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | MODIFIED | Docs |
| `docs/08-projects/current/multi-model-best-bets/02-SESSION-279-PLAN.md` | MODIFIED (→DONE) | Docs |
| `docs/08-projects/current/multi-model-best-bets/03-SEASON-REPLAY-STUDY.md` | CREATED | Study |

---

## Next Steps

1. **Feb 19:** Validate qualifying_subsets appear in signal-best-bets JSON
2. **Run `/subset-performance`** for immediate current-season subset data
3. **Implement Approach A:** Extend walkforward with subset simulation (~2-3 hours)
4. **Check last season data:** Query feature store coverage for 2024-25
5. **After 30 days:** Backtest qualifying_subset_count vs hit rate for Phase 2 scoring
