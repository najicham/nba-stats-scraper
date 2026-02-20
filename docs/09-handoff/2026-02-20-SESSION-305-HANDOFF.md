# Session 305 Handoff - Late Snapshot Backfill, Sweep Fix, Signal Audit

**Date:** 2026-02-20
**Focus:** Backfill missing odds snapshots, fix root cause, assess historical data, line movement research, prop_line_drop_over audit

## What Was Done

### 1. Backfill Missing Late-Snapshot Odds Data

**Problem:** Phase 2 batch processor ran once per date when the first file arrived, missing late snapshots (snap-19xx, snap-22xx, snap-00xx) that arrived hours later.

**Script:** `bin/backfill_daily_props_snapshots.py`
- Compares GCS files vs BQ `snapshot_tag` values per date
- Reuses `OddsApiPropsProcessor.transform_data()` for all normalization
- Supports `--dry-run`, `--start-date`, `--end-date`

**Results (Jan 25 - Feb 12):**
- 380 files loaded, 0 failures
- 10,524 rows added to `nba_raw.odds_api_player_points_props`
- 19 new snapshot tags across 17 dates
- Most dates now have 7-14 snapshots (was 2-3)

### 2. Root Cause Fix: `/sweep-odds` Endpoint + Nightly Scheduler

**Root cause:** Phase 2 batch processor uses Firestore locks. First file arrival triggers batch, loads all files at that moment. Later files sometimes trigger re-processing (lock delete + re-run), but this is intermittent due to Pub/Sub dedup and Cloud Run cold starts.

**Key insight:** All snap tags are UTC, not ET. snap-2205 = 5:05 PM ET, snap-0006 = 7:06 PM ET. All within the 5 AM - 8 PM ET workflow window. The scraper IS running at the right times; Phase 2 just doesn't reliably re-process.

**Fix:**
- Added `/sweep-odds` endpoint to `data_processors/raw/main_processor_service.py`
- Clears completed Firestore batch locks, then re-runs batch processor
- Cloud Scheduler job `odds-sweep-nightly` runs at 6 UTC (1 AM ET) daily
- Catches any files orphaned during the day

### 3. Historical Odds Data Assessment

**Result: No scraping needed for 2024-25 season.**

| Season | Day Coverage | Bookmakers | Rows/Day |
|--------|-------------|------------|----------|
| 2023-24 | 207/209 (100%) | 2 (DK, FD) | ~289 |
| 2024-25 | 213/213 (100%) | 2 (DK, FD) | ~282 |
| 2025-26 | 116 dates | 12 (all major) | ~2,780 |

- Only gap: bookmaker depth (2 vs 12 books). Multi-book features like `f50 multi_book_line_std` only work for 2025-26 data.
- All-Star Weekend gaps (2024-02-16, 2024-02-18) are non-issues (no regular season games).

### 4. Line Movement Analysis (Intraday)

Analyzed opening→closing DraftKings line movement using multi-snapshot data.

| Movement Bucket | N | OVER% vs Close | OVER% vs Open |
|----------------|---|----------------|---------------|
| Dropped big (< -1.5) | 101 | 46.5% | 26.7% |
| Dropped small | 307 | 47.2% | 41.7% |
| Unchanged | 660 | 48.0% | 48.0% |
| Raised small | 299 | 48.5% | 55.2% |
| Raised big (> +1.5) | 148 | 49.3% | 76.4% |

**Key finding:** Closing line is extremely efficient (~48% OVER across all buckets). Intraday line drops do NOT predict OVERs.

**Important distinction:** Intraday movement (opening→closing within same game day) is different from the `prop_line_drop_over` signal which measures inter-game movement (today's line vs previous game's line).

### 5. `prop_line_drop_over` Signal Audit

**Discovery:** Signal had **zero graded production picks** — the 3.0pt threshold was too restrictive. Only ~1.2% of predictions qualify at 3.0pt, and with the OVER-only filter, essentially nothing fires.

**Threshold analysis (OVER + line dropped, full season):**

| Threshold | Any Edge N | Any Edge HR | Edge 3+ N | Edge 3+ HR | Edge 5+ N | Edge 5+ HR |
|-----------|-----------|-------------|-----------|------------|-----------|------------|
| 0.5 | 424 | 54.5% | 158 | 65.8% | 73 | 82.2% |
| 1.0 | 347 | 55.0% | 143 | 67.8% | 72 | 81.9% |
| 1.5 | 252 | 59.5% | 118 | 70.3% | 70 | 81.4% |
| **2.0** | **210** | **60.5%** | **109** | **71.6%** | **68** | **80.9%** |
| 2.5 | 152 | 64.5% | 91 | 76.9% | 65 | 83.1% |
| 3.0 | 138 | 67.4% | 86 | 77.9% | 63 | 84.1% |
| 4.0 | 93 | 76.3% | 71 | 81.7% | 56 | 85.7% |
| 5.0 | 73 | 75.3% | 62 | 80.6% | 52 | 84.6% |

**Decision:** Lowered threshold from 3.0 → 2.0.
- Edge 3+: 71.6% HR (N=109) vs 77.9% (N=86) — trades 6 HR pts for 27% more picks
- Edge 5+: 80.9% HR (N=68) — barely changes
- Key insight: **edge filter matters more than drop threshold** (at edge 5+, even 0.5pt drop = 82.2% HR)

**How the signal works (for future reference):**
- Measures inter-game line delta (today's line vs player's most recent previous game line)
- OVER only — line drops after bad games create mean-reversion value
- Aggregator also blocks UNDER + dropped 3+ (41.0% HR) and UNDER + jumped 3+ (47.4% HR)
- Data source: `supplemental_data.py` → `prev_prop_lines` CTE (14-day lookback)

## Files Changed

| File | Change |
|------|--------|
| `bin/backfill_daily_props_snapshots.py` | **NEW** — one-off backfill script |
| `data_processors/raw/main_processor_service.py` | Added `/sweep-odds` endpoint |
| `ml/signals/prop_line_drop_over.py` | MIN_LINE_DROP 3.0→2.0, updated description |
| `ml/signals/combo_registry.py` | Updated HR 79.1→71.6, sample_size 67→109 |
| `CLAUDE.md` | Updated signal table entry |

## Infrastructure Changes

| Resource | Change |
|----------|--------|
| Cloud Scheduler: `odds-sweep-nightly` | **NEW** — 6 UTC daily, calls `/sweep-odds` on Phase 2 service |
| BQ: `signal_combo_registry` | Updated prop_line_drop_over entry |

## Follow-Up Items

1. **Monitor `odds-sweep-nightly` scheduler** — verify it works after Phase 2 deploys (first run: 2026-02-20 06:00 UTC)
2. **Monitor `prop_line_drop_over` at 2.0 threshold** — watch for actual production firings over the next week. If still too few, consider 1.5.
3. **Consider multi-book historical backfill** — test one Odds API historical call for a 2024-25 date to see if more than 2 bookmakers are returned. If so, could enrich training data depth.
4. **Aggregator UNDER blocks still at 3.0** — may want to align to 2.0 for consistency, but they serve a different purpose (blocking bad UNDER picks) and are working correctly.

## Verification

```bash
# Check sweep scheduler
gcloud scheduler jobs describe odds-sweep-nightly --location=us-west2 --project=nba-props-platform

# Check Phase 2 deployed with sweep endpoint
curl -s https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/health | jq .

# Verify backfill data
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT snapshot_tag) as tags, COUNT(*) as rows
FROM nba_raw.odds_api_player_points_props
WHERE game_date BETWEEN '2026-01-25' AND '2026-02-12'
GROUP BY 1 ORDER BY 1"

# Check signal fires with new threshold
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as firings
FROM nba_predictions.pick_signal_tags
WHERE signal_tag = 'prop_line_drop_over'
  AND game_date >= '2026-02-20'
GROUP BY 1 ORDER BY 1"
```
