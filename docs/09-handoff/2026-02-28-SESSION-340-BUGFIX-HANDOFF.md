# Session 340 Bugfix Handoff — Pick Locking Code Review + Fixes

**Date:** 2026-02-28
**Commits:** `6cee7ca5`, `4b5e66a2`, `95d31a29`, `c8078271`, `261cee47`, `9c504ced`
**Prior Session:** 340 (commit `8b9fb503` — initial pick locking implementation)
**Status:** All pushed, all Cloud Functions deployed successfully

---

## Context

Session 340 implemented a pick locking system to prevent best bets picks from disappearing mid-day when the signal pipeline re-ran. Three new BQ tables (`best_bets_published_picks`, `best_bets_manual_picks`, `best_bets_export_audit`) and a manual pick CLI (`scripts/nba/add_manual_pick.py`) were added.

This session performed a thorough code review of that implementation and fixed 8 bugs + 1 regression found during testing.

---

## Bugs Found and Fixed

### Bug 1: Race condition — DELETE+INSERT (FIXED: `4b5e66a2`)
**File:** `best_bets_all_exporter.py`
- `_write_published_picks()` used DELETE then INSERT — concurrent exports could create duplicates or lose data.
- **Fix:** Replaced with atomic `WRITE_TRUNCATE` on a partition decorator (`table$YYYYMMDD`). Single load job replaces the entire partition atomically. No race window.

### Bug 2: Manual pick source attribution lost (FIXED: `6cee7ca5`)
**File:** `best_bets_all_exporter.py`
- Manual picks written to `signal_best_bets_picks` by CLI were captured by `_query_all_picks()` first, entering the merge as `source='algorithm'`. The manual picks query was then skipped (`key not in merged`).
- **Fix:** Added `manual_by_key` index. All three merge paths (Step 1+2 locked, Step 3 new signal, Step 4 manual) now cross-reference it to set correct source. Stats recount uses `_source` value instead of `_in_signal` flag.
- Also added `source` field to `_format_today()` output so frontend `BestBetsPick.source` is populated.

### Bug 3: remove_pick didn't clean signal table (FIXED: `6cee7ca5`)
**File:** `add_manual_pick.py`
- `remove_pick()` only soft-deleted from `best_bets_manual_picks`. The `manual_override` row in `signal_best_bets_picks` persisted, making picks un-removable.
- **Fix:** Added DELETE from `signal_best_bets_picks` WHERE `system_id = 'manual_override'`.
- Later also added DELETE from `best_bets_published_picks` WHERE `source = 'manual'` (`4b5e66a2`) to prevent the locking system from resurrecting removed manual picks.

### Bug 4: Latent datetime serialization crash (FIXED: `6cee7ca5`)
**File:** `best_bets_all_exporter.py`
- `query_to_list()` returns `datetime` objects for TIMESTAMP columns. On second export of the day, `first_published_at` from BQ was passed raw to `load_table_from_json` — not JSON-serializable.
- **Fix:** Added `_to_iso()` static helper that safely handles datetime, date, string, and None.

### Bug 5: `_format_today` missing source field (FIXED: `6cee7ca5`)
**File:** `best_bets_all_exporter.py`
- Frontend type `BestBetsPick.source?: "algorithm" | "manual"` was never populated.
- **Fix:** Added `source` to formatted output (omitted for algorithm picks to keep payload lean).

### Bug 6: No duplicate protection in CLI (FIXED: `4b5e66a2`)
**File:** `add_manual_pick.py`
- Running `add_manual_pick.py` twice created duplicate rows (WRITE_APPEND).
- **Fix:** Added check for existing active manual pick before inserting. Exits with error if duplicate found.

### Bug 7: Load schema missing REQUIRED mode (FIXED: `6cee7ca5`)
**File:** `best_bets_all_exporter.py`
- DDL declared NOT NULL on `player_lookup`, `game_id`, `game_date`, `source`, `first_published_at`, `export_id` but load schemas used default NULLABLE. BQ rejected the loads with "mode changed from REQUIRED to NULLABLE".
- **Fix:** Added `mode='REQUIRED'` to match DDL for both `_write_published_picks` and `_write_export_audit`.

### Bug 8: Manual pick can't override algorithm direction (FIXED: `261cee47`)
**File:** `best_bets_all_exporter.py`
- If algorithm already selected a player, a manual pick for the same player (different direction/line) was silently dropped in Step 4.
- **Fix:** Step 4 now overrides algorithm picks when a manual pick exists for the same player. Grading fields are preserved from the algorithm pick. Logged as "Manual override".

### Regression: ultra_tier bool("false") coercion (FIXED: `95d31a29`, `c8078271`)
**File:** `best_bets_all_exporter.py`
- `ultra_tier` is BOOLEAN in `signal_best_bets_picks` but STRING in `best_bets_published_picks`. On subsequent exports, picks from published_picks had `ultra_tier="false"` (string), and `bool("false")` is `True` in Python — all locked picks appeared as ultra.
- **Fix:** Added `_is_ultra()` static helper for consistent normalization. All 5 usage sites use it.
- Also added **ultra gate**: ultra_tier cannot be added to a pick whose game has started (`game_status >= 2`). New `_query_started_games()` method. Blocked changes logged as warnings.

### Name lookup fix (FIXED: `9c504ced`)
**File:** `add_manual_pick.py`
- `lookup_player_name` only searched `signal_best_bets_picks`. After `remove_pick` deleted the signal row, re-adding the same player fell back to the raw lookup key ("guisantos" instead of "Gui Santos").
- Fallback to `player_game_summary` used wrong column (`player_name` vs `player_full_name`).
- **Fix:** Fixed column name. Lookup chain: `signal_best_bets_picks` → `player_game_summary` → raw key.

---

## Files Changed

| File | Changes |
|------|---------|
| `data_processors/publishing/best_bets_all_exporter.py` | Merge logic, atomic writes, ultra gate, `_is_ultra()`, `_to_iso()`, source attribution, REQUIRED modes |
| `scripts/nba/add_manual_pick.py` | Remove cleanup (3 tables), duplicate guard, name lookup fallback |

---

## Current State

- **6 picks live** for 2026-02-28: 5 algorithm + 1 manual (Gui Santos OVER 13.5, edge 5.2)
- **Pick locking working**: Picks persist across re-exports. Locked picks update edge/rank/angles from signal but never disappear.
- **Audit trail working**: Each export writes to `best_bets_export_audit` with source counts and full pick snapshot.
- **Ultra gate active**: ultra_tier cannot be added after game start.
- **All Cloud Functions deployed** (phase6-export, post-grading-export, live-export).

---

## Deployment Notes

- All changes auto-deployed via Cloud Build push triggers
- `validation-runner` has pre-existing drift from prior session (not from this work)
- `add_manual_pick.py` is a local CLI script — no deployment needed
- prediction-coordinator trigger only watches `predictions/coordinator/**`, NOT `data_processors/publishing/` or `ml/signals/` — manual deploy needed if those paths change coordinator behavior

---

## Remaining Issues (Not Addressed)

None from the original review. All 8 bugs + the ultra regression + the name lookup issue are fixed.

---

## Key Architectural Decisions

1. **Atomic partition write** (`WRITE_TRUNCATE` on `table$YYYYMMDD`): Simpler than MERGE, no ARRAY<STRING> complexity, BQ load jobs are inherently atomic per-partition. Last writer wins with correct data.
2. **Manual picks override algorithm picks**: If both exist for same player, manual wins. Grading fields preserved from algorithm pick.
3. **Ultra gate uses game_status from schedule**: Queries `nbac_schedule` for `game_status >= 2`. Separate from game_times query (different concern).
4. **Three-table cleanup on remove**: `remove_pick` now cleans `best_bets_manual_picks` (soft delete), `signal_best_bets_picks` (hard delete), and `best_bets_published_picks` (hard delete, source='manual' only).
