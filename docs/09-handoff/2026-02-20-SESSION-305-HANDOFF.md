# Session 305 Handoff - Late Snapshot Backfill, Nightly Sweep, Line Movement Analysis

**Date:** 2026-02-20
**Focus:** Backfill missing odds snapshots, fix root cause, assess historical data, line movement research

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

### 4. Line Movement Analysis

**Critical finding: Line drops do NOT predict OVERs.**

| Movement Bucket | N | OVER% vs Close | OVER% vs Open |
|----------------|---|----------------|---------------|
| Dropped big (< -1.5) | 101 | 46.5% | 26.7% |
| Dropped small | 307 | 47.2% | 41.7% |
| Unchanged | 660 | 48.0% | 48.0% |
| Raised small | 299 | 48.5% | 55.2% |
| Raised big (> +1.5) | 148 | 49.3% | 76.4% |

- **Closing line is extremely efficient** (~48% OVER across all buckets)
- `prop_line_drop_over` signal shows 79.1% HR in production but raw data shows 46.5% — audit needed
- The signal likely has additional filters (edge threshold, specific conditions) that drive the high HR

## Files Changed

| File | Change |
|------|--------|
| `bin/backfill_daily_props_snapshots.py` | **NEW** — one-off backfill script |
| `data_processors/raw/main_processor_service.py` | Added `/sweep-odds` endpoint |

## Infrastructure Changes

| Resource | Change |
|----------|--------|
| Cloud Scheduler: `odds-sweep-nightly` | **NEW** — 6 UTC daily, calls `/sweep-odds` on Phase 2 service |

## Follow-Up Items

1. **Audit `prop_line_drop_over` signal** — raw line-drop analysis shows sub-breakeven OVER rates, but the signal claims 79.1% HR. Need to understand what additional filters drive the difference.
2. **Monitor `odds-sweep-nightly` scheduler** — verify it works after Phase 2 deploys (auto-deploy from push to main)
3. **Consider multi-book historical backfill** — test one Odds API historical call for a 2024-25 date to see if more than 2 bookmakers are returned. If so, could enrich training data depth.

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
```
