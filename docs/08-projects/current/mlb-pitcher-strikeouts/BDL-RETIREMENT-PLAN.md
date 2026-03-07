# BDL Retirement Plan — Cancel Subscription

**Created:** 2026-03-07
**Status:** RETIRE. All 3 BDL MLB tables are unreliable. Replacements ready or in progress.

---

## Why BDL Must Go

### Table 1: `bdl_pitcher_stats` — DEAD
- **15 rows total** (last data: Oct 2024)
- Already migrated to `mlb_pitcher_stats` from MLB Stats API (42,125 rows)
- Pitcher analytics processor updated months ago

### Table 2: `bdl_batter_stats` — UNRELIABLE
- **97,679 rows** but zero game-level granularity
- Every batter on a date has `game_id = "YYYY-MM-DD_UNK_UNK"` — BDL doesn't track which game each batter played in
- This breaks any game-level analysis (e.g., "which batters faced this pitcher?")
- 31 distinct teams on most days (MLB has 30) — team abbreviation inconsistencies
- **Replacement:** `mlbapi_batter_stats` backfill running (MLB Stats API, proper `game_pk` per game)

### Table 3: `bdl_injuries` — USELESS
- **222 rows from a single date** (Jan 15, 2026)
- Zero historical coverage, zero ongoing collection
- Prediction code already has fail-safe fallback (returns empty set on failure)
- **Replacement needed:** MLB Stats API transactions endpoint or ESPN injury feed

---

## Data Quality Evidence

```sql
-- BDL game_id is not a real game identifier
SELECT DISTINCT game_id, game_date, COUNT(*) as batters
FROM mlb_raw.bdl_batter_stats
WHERE game_date = '2025-09-28'
GROUP BY game_id, game_date;
-- Returns: "2025-09-28_UNK_UNK" | 313 batters (ALL in one fake game_id)

-- BDL pitcher stats = effectively dead
SELECT COUNT(*) FROM mlb_raw.bdl_pitcher_stats;  -- 15 rows

-- BDL injuries = single snapshot
SELECT COUNT(*), MIN(snapshot_date), MAX(snapshot_date)
FROM mlb_raw.bdl_injuries;  -- 222 rows, all from 2026-01-15
```

---

## Replacement Status

| BDL Table | Replacement | Source | Status |
|-----------|-------------|--------|--------|
| `bdl_pitcher_stats` | `mlb_pitcher_stats` | MLB Stats API | DONE — 42K rows, fully migrated |
| `bdl_batter_stats` | `mlbapi_batter_stats` | MLB Stats API | BACKFILLING — `scripts/mlb/backfill_batter_stats.py` running |
| `bdl_injuries` | TBD | MLB Stats API `/transactions` or ESPN | NOT STARTED — fail-safe in place |

### After Backfill Completes

1. Verify `mlbapi_batter_stats` coverage >= BDL (97K rows, 365 dates)
2. Switch `batter_game_summary_processor.py` to mlbapi-only (remove BDL from UNION)
3. Disable BDL scrapers in registry (if not already)
4. Cancel BDL subscription

---

## Injury Replacement Options

The only remaining BDL dependency is injury data in `base_predictor.py` and `pitcher_strikeouts_predictor.py`. Both have fail-safe fallbacks that return empty sets on failure, so this is non-blocking.

**Option A: MLB Stats API Transactions** (recommended)
- Endpoint: `https://statsapi.mlb.com/api/v1/transactions?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`
- Free, no auth. Contains IL placements, activations, DFA, trades.
- Parse for `typeCode` in ('IL', 'DI', 'ASG') to find injured pitchers.
- Write to `mlb_raw.mlbapi_injuries`.

**Option B: ESPN Injury Feed**
- Less structured but includes expected return dates.
- Would need a new scraper.

**Option C: Skip injuries entirely**
- The model doesn't use injury data as a feature.
- Injuries are only used to filter out IL pitchers from predictions.
- If a pitcher is on the IL, they won't have a prop line anyway — the odds API won't return K lines for them.
- This means the filter is redundant. We could just rely on "no prop line = no prediction."

**Recommendation:** Option C. The injury filter is defense-in-depth but the prop line check already handles it. Remove the IL query entirely and save the API calls.

---

## Code References

| File | BDL Reference | Action |
|------|--------------|--------|
| `data_processors/analytics/mlb/batter_game_summary_processor.py` | UNION of bdl + mlbapi | Switch to mlbapi-only after backfill |
| `data_processors/analytics/mlb/main_mlb_analytics_service.py` | `bdl_batter_stats` trigger | Remove bdl trigger after migration |
| `predictions/mlb/base_predictor.py:119` | `bdl_injuries` query | Remove or replace with Option C |
| `predictions/mlb/pitcher_strikeouts_predictor.py:245` | `bdl_injuries` query | Remove or replace with Option C |
| `scrapers/registry.py` | BDL scrapers registered | Disable/remove |

---

## Timeline

- **Now:** Backfill running, batter processor uses UNION (both sources)
- **After backfill:** Switch to mlbapi-only, remove BDL from UNION
- **Before season (Mar 27):** Cancel BDL subscription
- **Optional:** Remove IL queries from predictors (Option C)
