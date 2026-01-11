# Oct 22 - Nov 13 Gap Recovery Plan

**Created:** January 11, 2026
**Status:** Planning
**Priority:** P1 - High

---

## Executive Summary

A 23-day gap (Oct 22 - Nov 13, 2025) was discovered where:
1. **Prop data was never scraped** to GCS from Odds API
2. **Phase 4 precompute has significant gaps** affecting rolling averages
3. **Predictions during the gap** either don't exist or have `has_prop_line = false`

This document outlines the full scope and recovery plan.

---

## Gap Analysis

### What Ran Successfully

| Phase | Table | Status | Notes |
|-------|-------|--------|-------|
| Phase 1 | Raw box scores | ✅ Complete | 23 dates, 168 games |
| Phase 3 | player_game_summary | ✅ Complete | 23 dates, 6,298 records |

### What Has Gaps

| Phase | Table | Gap Period | Impact |
|-------|-------|------------|--------|
| Phase 2 | odds_api_player_points_props | Oct 22 - Nov 13 | No Vegas lines for predictions |
| Phase 4 | player_daily_cache | Oct 22 - Nov 3 | Rolling averages missing games |
| Phase 4 | player_shot_zone_analysis | Oct 22 - Nov 6 | Zone analysis incomplete |
| Phase 4 | team_defense_zone_analysis | Oct 22 - Nov 15 | Defense metrics incomplete |
| Phase 5 | player_prop_predictions | Oct 22 - Nov 3 | No predictions (blocked by Phase 4) |
| Phase 5 | player_prop_predictions | Nov 4 - Nov 13 | 2,212 predictions, ALL `has_prop_line = false` |

### Downstream Effects

#### Rolling Averages (Critical)
The `player_daily_cache` table contains rolling statistics like:
- `points_avg_last_10` - Average points over last 10 games
- `points_avg_season` - Season average

**Impact:** If Oct 22 - Nov 3 games were missing from the rolling calculations, averages for Nov 4+ would be slightly incorrect. However, looking at the data:
- Nov 4 averages look reasonable (10-11 pts avg)
- Season avg equals last_10 avg early on (expected)

**Assessment:** Likely minimal impact since Phase 3 data existed and Phase 4 processors may have calculated averages correctly. Need to verify.

#### Zone Analysis
- `player_shot_zone_analysis`: Missing Oct 22 - Nov 6
- `team_defense_zone_analysis`: Missing Oct 22 - Nov 15

**Impact:** Zone-based predictions (CatBoost V8 uses these features) would have less historical data to work with.

---

## Recovery Options

### Option A: Full Historical Recovery (Recommended)

**Steps:**
1. **Scrape Historical Prop Data from Odds API**
   - Use `scrapers/oddsapi/oddsa_player_props_his.py`
   - Requires: Event IDs from `oddsa_events_his.py`
   - Cost: ~23 API requests × multiple events/day = ~200-500 requests
   - Odds API historical endpoint has usage limits

2. **Reprocess Phase 4 Precompute**
   - Run Phase 4 backfill for Oct 22 - Nov 20
   - This fixes rolling averages and zone analysis
   - Command: `python backfill_jobs/precompute/player_daily_cache_backfill.py --start-date 2025-10-22 --end-date 2025-11-20`

3. **Regenerate Predictions**
   - Run predictions backfill with `--force` for Nov 4 - Nov 13
   - Now has correct Phase 4 data + prop lines
   - Command: `python backfill_jobs/prediction/player_prop_predictions_backfill.py --start-date 2025-11-04 --end-date 2025-11-13 --force`

4. **Regrade Predictions**
   - Run grading backfill for Nov 4 - Nov 13
   - Command: `python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date 2025-11-04 --end-date 2025-11-13`

**Pros:**
- Complete data recovery
- Accurate rolling averages
- Full historical performance analysis possible

**Cons:**
- Requires Odds API historical access (may have cost/quota)
- Time-intensive (several hours)
- Complex multi-step process

### Option B: Partial Recovery (Skip Historical Props)

**Steps:**
1. Skip Odds API historical scraping
2. Reprocess Phase 4 for Oct 22 - Nov 20 (fixes rolling averages)
3. Keep existing predictions (still `has_prop_line = false`)
4. Accept that Oct 22 - Nov 13 predictions are "model-only" without Vegas lines

**Pros:**
- No Odds API cost
- Fixes rolling average issues
- Faster to execute

**Cons:**
- Can't analyze prediction accuracy vs Vegas lines for this period
- Historical performance metrics exclude this period

### Option C: Accept Gap (Minimal Action)

**Steps:**
1. Document the gap
2. Exclude Oct 22 - Nov 13 from performance analysis
3. Ensure monitoring prevents future gaps

**Pros:**
- No work required
- Gap is documented

**Cons:**
- Data integrity issue remains
- Rolling averages may be slightly off

---

## Recommended Approach

**Go with Option A (Full Recovery)** because:
1. CatBoost V8 is your production model - accurate historical performance matters
2. Rolling averages affect predictions going forward
3. Historical props scraper already exists
4. One-time effort with permanent benefit

---

## Implementation Checklist

### Phase 1: Historical Prop Scraping
```bash
# 1. Get event IDs for each date
for date in 2025-10-22 2025-10-23 ... 2025-11-13; do
  python scrapers/oddsapi/oddsa_events_his.py \
    --game_date $date \
    --snapshot_timestamp ${date}T04:00:00Z \
    --output-mode gcs
done

# 2. For each event, scrape player props
# (Need to extract event_ids from step 1 output)
python scrapers/oddsapi/oddsa_player_props_his.py \
  --event_id <EVENT_ID> \
  --game_date <DATE> \
  --snapshot_timestamp <DATE>T04:00:00Z \
  --markets player_points \
  --output-mode gcs
```

### Phase 2: Process Props to BigQuery
```bash
# Load scraped props from GCS to BigQuery
python scripts/backfill_odds_api_props.py \
  --start-date 2025-10-22 \
  --end-date 2025-11-13 \
  --parallel 3
```

### Phase 3: Reprocess Phase 4 Precompute
```bash
# Fix rolling averages and zone analysis
python backfill_jobs/precompute/player_daily_cache_backfill.py \
  --start-date 2025-10-22 \
  --end-date 2025-11-20 \
  --force

python backfill_jobs/precompute/player_shot_zone_analysis_backfill.py \
  --start-date 2025-10-22 \
  --end-date 2025-11-20 \
  --force

python backfill_jobs/precompute/team_defense_zone_analysis_backfill.py \
  --start-date 2025-10-22 \
  --end-date 2025-11-20 \
  --force
```

### Phase 4: Regenerate Predictions
```bash
python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2025-10-22 \
  --end-date 2025-11-13 \
  --force
```

### Phase 5: Regrade Predictions
```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2025-10-22 \
  --end-date 2025-11-13
```

---

## Verification Queries

### After Recovery, Verify:

```sql
-- 1. Props loaded for gap period
SELECT COUNT(DISTINCT game_date) as dates
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date BETWEEN '2025-10-22' AND '2025-11-13';
-- Expected: 23

-- 2. Phase 4 complete
SELECT
  'player_daily_cache' as table_name,
  COUNT(DISTINCT cache_date) as dates
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2025-10-22' AND '2025-11-13'
-- Expected: 23

-- 3. Predictions with prop lines
SELECT
  COUNT(*) as total,
  COUNTIF(has_prop_line = true) as with_lines
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date BETWEEN '2025-10-22' AND '2025-11-13'
  AND system_id = 'catboost_v8';
-- Expected: >2000 predictions, most with lines

-- 4. Graded predictions
SELECT COUNT(DISTINCT game_date) as graded_dates
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2025-10-22' AND '2025-11-13'
  AND system_id = 'catboost_v8';
-- Expected: 23
```

---

## Odds API Considerations

### Historical Endpoint Limitations
- **Cost:** Historical API may have different pricing than live API
- **Quota:** Check your Odds API plan for historical request limits
- **Data Retention:** Verify how far back historical data is available
- **Snapshot Timing:** Must use correct timestamp to avoid 404s

### Best Practices
1. First run `oddsa_events_his` to get event IDs
2. Use early morning timestamps (04:00 UTC) for best coverage
3. Batch requests with delays to respect rate limits
4. Store raw responses in GCS before processing

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Odds API quota exceeded | Medium | High | Check quota before starting |
| Historical data not available | Low | High | Verify with test request first |
| Process takes too long | Medium | Low | Run in background, checkpoint |
| Rolling avg recalc errors | Low | Medium | Verify with spot checks |

---

## Timeline Estimate

| Task | Duration |
|------|----------|
| Historical props scraping | 2-4 hours |
| Process props to BigQuery | 30 min |
| Phase 4 reprocessing | 1-2 hours |
| Predictions regeneration | 30 min |
| Grading | 15 min |
| Verification | 15 min |
| **Total** | **4-8 hours** |

---

## Next Steps

1. [ ] Check Odds API quota/pricing for historical endpoint
2. [ ] Test historical scraper with one date
3. [ ] Execute recovery plan (if approved)
4. [ ] Verify all data recovered
5. [ ] Update monitoring to prevent future gaps

---

## Related Documents

- [2026-01-11-PROP-DATA-GAP-INCIDENT.md](./2026-01-11-PROP-DATA-GAP-INCIDENT.md) - Incident details
- [MASTER-TODO.md](./MASTER-TODO.md) - Project tracking
