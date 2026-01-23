# Historical Odds API Backfill Plan - Jan 19-22, 2026

**Created:** 2026-01-23
**Status:** Ready to Execute
**Priority:** P2

---

## Problem Statement

Jan 19-22, 2026 have **zero odds_api player props data** in BigQuery. Only bettingpros data exists for these dates, and bettingpros is currently blocked (403).

**Current State:**
| Date | odds_api records | bettingpros records |
|------|------------------|---------------------|
| Jan 19 | 0 | ??? |
| Jan 20 | 0 | ??? |
| Jan 21 | 720 (partial) | ??? |
| Jan 22 | 0 | ??? |

---

## Solution Overview

Use the Odds API **historical endpoint** to scrape past player props data.

**Two-Phase Process:**
1. **Scrape** - Get historical events and player props from Odds API → GCS
2. **Load** - Process GCS files → BigQuery via Phase 2 processor

---

## Step-by-Step Execution Plan

### Pre-Flight Checks

```bash
cd /home/naji/code/nba-stats-scraper

# 1. Verify Odds API key is configured
gcloud secrets versions access latest --secret=ODDS_API_KEY | head -c 10
# Should show first 10 chars of key

# 2. Verify GCS bucket access
gsutil ls gs://nba-scraped-data/odds-api/ | head -5

# 3. Verify BigQuery table exists
bq show nba_raw.odds_api_player_points_props
```

### Phase 1: Dry Run (Zero API Calls)

```bash
# See what events would be scraped - NO API calls made
python scripts/backfill_historical_props.py \
    --start-date 2026-01-19 \
    --end-date 2026-01-22 \
    --dry-run
```

**Expected Output:**
```
Processing 4 dates from 2026-01-19 to 2026-01-22
=====================================
Processing date 1/4: 2026-01-19
=====================================
Fetching events for 2026-01-19...
Found 13 events for 2026-01-19
DRY RUN: Would scrape 13 events
...
```

### Phase 2: Execute Scraping

**IMPORTANT:** This makes actual API calls and uses API quota.

```bash
# Full scrape with 1-second delay between requests
# Estimated time: 5-15 minutes for 4 days (~52 events)
python scripts/backfill_historical_props.py \
    --start-date 2026-01-19 \
    --end-date 2026-01-22 \
    --delay 1.0
```

**What Happens:**
1. For each date, fetches historical events (game IDs) at 04:00:00Z UTC
2. For each event, fetches player_points props from DraftKings/FanDuel
3. Saves JSON files to GCS: `gs://nba-scraped-data/odds-api/player-props-history/{date}/{event}/{timestamp}.json`

### Phase 3: Verify GCS Files

```bash
# Check files were written
for date in 2026-01-19 2026-01-20 2026-01-21 2026-01-22; do
  count=$(gsutil ls -r gs://nba-scraped-data/odds-api/player-props-history/$date/ 2>/dev/null | grep -c .json || echo 0)
  echo "$date: $count files"
done
```

**Expected:** ~13 files per day, ~52 total

### Phase 4: Load to BigQuery

```bash
# Process all GCS files and load to BigQuery
python scripts/backfill_odds_api_props.py \
    --start-date 2026-01-19 \
    --end-date 2026-01-22 \
    --historical \
    --parallel 5 \
    --verbose
```

**What Happens:**
1. Lists all JSON files in `odds-api/player-props-history/` for each date
2. Sends each file to Phase 2 processor endpoint
3. Phase 2 transforms and loads to `nba_raw.odds_api_player_points_props`

### Phase 5: Validate Results

```bash
# Query BigQuery to verify data loaded
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(*) as total_rows,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT bookmaker_key) as bookmakers
FROM `nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN "2026-01-19" AND "2026-01-22"
GROUP BY 1
ORDER BY 1'
```

**Expected Output:**
```
+--------------+------------+-------+---------+------------+
| game_date    | total_rows | games | players | bookmakers |
+--------------+------------+-------+---------+------------+
| 2026-01-19   | ~300-500   | ~13   | ~100    | 2-5        |
| 2026-01-20   | ~300-500   | ~13   | ~100    | 2-5        |
| 2026-01-21   | ~800-1000  | ~13   | ~100    | 2-5        |
| 2026-01-22   | ~300-500   | ~13   | ~100    | 2-5        |
+--------------+------------+-------+---------+------------+
```

---

## API Quota Analysis

| Metric | Value |
|--------|-------|
| Days to backfill | 4 |
| Avg games/day | 13 |
| Total events | ~52 |
| API calls for events | 4 (one per day) |
| API calls for props | ~52 (one per event) |
| **Total API calls** | **~56** |
| Typical monthly quota | 1000+ |
| **Quota usage** | **<6%** |

**Safe to proceed** - minimal quota impact.

---

## Troubleshooting Guide

### Problem: 404 Errors on Props Scraping

**Cause:** Snapshot timestamp is too late - events disappeared when games started.

**Solution:** The script uses 04:00:00Z by default (early morning). If 404s occur:
```bash
# Try earlier timestamp
python scripts/backfill_historical_props.py \
    --start-date 2026-01-19 \
    --end-date 2026-01-19 \
    --snapshot-time "02:00:00Z"
```

### Problem: "No events found" for a Date

**Possible Causes:**
1. No NBA games on that date
2. Timestamp too early (props not yet published)
3. API rate limiting

**Solution:** Check NBA schedule for that date and try different timestamp.

### Problem: Phase 2 Processor Errors

**Check logs:**
```bash
gcloud logging read 'resource.type="cloud_run_revision" resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=20 --format="table(timestamp,textPayload)"
```

### Problem: Resuming Interrupted Backfill

```bash
# Skip to specific date
python scripts/backfill_historical_props.py \
    --start-date 2026-01-19 \
    --end-date 2026-01-22 \
    --skip-to-date 2026-01-21
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `scripts/backfill_historical_props.py` | Phase 1 orchestrator - scrapes events + props |
| `scripts/backfill_odds_api_props.py` | Phase 2 orchestrator - GCS → BigQuery |
| `scrapers/oddsapi/oddsa_events_his.py` | Historical events scraper |
| `scrapers/oddsapi/oddsa_player_props_his.py` | Historical player props scraper |
| `data_processors/raw/oddsapi/odds_api_props_processor.py` | BigQuery transform logic |

---

## Success Criteria

- [ ] Pre-flight checks pass
- [ ] Dry run shows ~52 events across 4 dates
- [ ] Scraping completes with <10% 404 rate
- [ ] GCS has ~52 JSON files
- [ ] BigQuery has 1500+ new rows for Jan 19-22
- [ ] Validation query shows data for all 4 dates

---

## Estimated Timeline

| Phase | Duration |
|-------|----------|
| Pre-flight checks | 2 min |
| Dry run | 1 min |
| Scraping (4 dates) | 10-15 min |
| GCS verification | 1 min |
| BigQuery load | 5-10 min |
| Validation | 1 min |
| **Total** | **~25-35 min** |

---

**Author:** Claude Code Session
**Date:** 2026-01-23
