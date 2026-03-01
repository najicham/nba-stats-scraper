# Session 340 - Pick Locking, Audit Trail & Manual Push

**Date:** 2026-02-28
**Session Type:** Feature — Publishing Layer
**Status:** Complete

---

## Executive Summary

Picks can disappear mid-day when the signal pipeline re-runs with updated lines/filters. This erodes user trust and leaves no audit trail. This session adds:

1. **Pick locking** — once published, a pick never disappears from the export
2. **Export audit trail** — every export is snapshotted with source attribution
3. **Manual push CLI** — add or remove picks via command line

---

## Architecture

Locking happens at the **publishing layer** (`best_bets_all_exporter.py`), not the signal pipeline. The signal table (`signal_best_bets_picks`) stays volatile. The exporter merges three sources:

```
signal_best_bets_picks (volatile, latest algo output)
  + best_bets_published_picks (locked picks from prior exports)
  + best_bets_manual_picks (manual overrides via CLI)
  = merged today[] in all.json
```

**Key guarantee:** A pick in `best_bets_published_picks` ALWAYS appears in the export, even if the signal pipeline dropped it.

---

## What Changed

### 1. Three New BigQuery Tables

| Table | Purpose |
|-------|---------|
| `best_bets_published_picks` | Locked picks. Once published, always exported. |
| `best_bets_manual_picks` | Manual overrides via CLI. Soft-delete via `is_active`. |
| `best_bets_export_audit` | Snapshot of every export with source counts + full pick list. |

All partitioned by `game_date`, require partition filter.

**Schemas:** `schemas/bigquery/nba_predictions/best_bets_{published_picks,manual_picks,export_audit}.sql`

### 2. Exporter Locking Logic (`data_processors/publishing/best_bets_all_exporter.py`)

New methods:
- `_query_published_picks(target_date)` — read locked picks
- `_query_manual_picks(target_date)` — read active manual picks
- `_merge_and_lock_picks(signal, published, manual)` — core merge (5-step)
- `_write_published_picks(target_date, picks)` — delete+insert to published table
- `_write_export_audit(target_date, picks, stats)` — append audit row

**Merge steps:**
1. Start with published (locked) picks as baseline
2. Overlay signal data on locked picks (update edge/rank/angles)
3. Add new signal picks not yet published
4. Add manual picks not already present
5. Re-rank: active signal first, then locked-but-dropped, then manual

`export()` now accepts `trigger_source` kwarg (`scheduled`, `manual`, `post_grading`).

### 3. Manual Push CLI (`scripts/nba/add_manual_pick.py`)

```bash
# Add a pick
python scripts/nba/add_manual_pick.py \
  --player guisantos --team GSW --opponent LAL \
  --direction OVER --line 13.5 --date 2026-02-28 \
  --edge 5.2 --notes "reason" [--export]

# Remove (soft-delete)
python scripts/nba/add_manual_pick.py \
  --remove --player guisantos --date 2026-02-28
```

Writes to both `best_bets_manual_picks` AND `signal_best_bets_picks` (system_id=`manual_override`) so the grading pipeline grades it.

### 4. Daily Export Passthrough (`backfill_jobs/publishing/daily_export.py`)

Passes `trigger_source='scheduled'` to `BestBetsAllExporter.export()`.

### 5. Frontend Type (`props-web/src/lib/best-bets-types.ts`)

Added `source?: "algorithm" | "manual"` to `BestBetsPick`. No UI changes yet.

---

## Tables Created

All 3 tables were created in BigQuery on 2026-02-28.

---

## Verification Done

- Gui Santos OVER 13.5 (GSW vs LAL, 2026-02-28) added as first manual pick
- Pick written to `best_bets_manual_picks` and `signal_best_bets_picks`
- Display name corrected to "Gui Santos" in both tables

---

## Next Steps

1. **Run a full export** to verify locking end-to-end:
   ```bash
   .venv/bin/python backfill_jobs/publishing/daily_export.py --date 2026-02-28 --only best-bets-all
   ```
2. **Verify** `best_bets_published_picks` and `best_bets_export_audit` have data after export
3. **Test drop scenario:** delete a row from `signal_best_bets_picks`, re-export, verify pick persists
4. **Admin dashboard:** surface `source` field to show manual vs algorithm picks
5. **Grading check:** after games complete, verify manual picks get graded

---

## Files Modified

**nba-stats-scraper:**
- `schemas/bigquery/nba_predictions/best_bets_published_picks.sql` — NEW
- `schemas/bigquery/nba_predictions/best_bets_manual_picks.sql` — NEW
- `schemas/bigquery/nba_predictions/best_bets_export_audit.sql` — NEW
- `data_processors/publishing/best_bets_all_exporter.py` — Locking + audit logic
- `scripts/nba/add_manual_pick.py` — NEW CLI script
- `backfill_jobs/publishing/daily_export.py` — Pass trigger_source

**props-web:**
- `src/lib/best-bets-types.ts` — Optional source field
