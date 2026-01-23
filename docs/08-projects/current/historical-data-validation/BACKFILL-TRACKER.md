# Prediction Backfill Tracker

**Last Updated:** 2026-01-23
**Status:** Active

---

## Summary

| Season | Missing Dates | Has Odds? | Backfill Priority | Status |
|--------|--------------|-----------|-------------------|--------|
| 2021-22 | 14 | No | P3 (Low) | Not Planned |
| 2022-23 | 14 | Partial | P3 (Low) | Not Planned |
| 2023-24 | 14 | Yes | P2 (Medium) | Pending |
| 2024-25 | 14 | Yes | P1 (High) | **Ready** |

---

## 2024-25 Season Backfill (P1)

**Status:** Ready to Execute

### Missing Dates
```
2024-10-22  2024-10-23  2024-10-24  2024-10-25  2024-10-26
2024-10-27  2024-10-28  2024-10-29  2024-10-30  2024-10-31
2024-11-01  2024-11-02  2024-11-03  2024-11-04
```

### Prerequisites
- [x] Analytics data exists for all dates
- [x] Odds API data exists for all dates
- [ ] Feature store populated for these dates
- [ ] Prediction coordinator ready

### Backfill Commands

```bash
# For each missing date:
COORD_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)

# Oct 22, 2024
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $COORD_KEY" \
    -d '{"game_date": "2024-10-22", "force": true}'

# Repeat for each date...
```

### Validation Query

```sql
-- Verify backfill completed
SELECT game_date, COUNT(*) as predictions
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE
  AND game_date >= '2024-10-22'
  AND game_date <= '2024-11-04'
GROUP BY 1
ORDER BY 1;
```

---

## 2023-24 Season Backfill (P2)

**Status:** Pending Investigation

### Missing Dates
```
2023-10-24  2023-10-25  2023-10-26  2023-10-27  2023-10-28
2023-10-29  2023-10-30  2023-10-31  2023-11-01  2023-11-02
2023-11-03  2023-11-04  2023-11-05  2023-11-06
```

### Prerequisites
- [x] Analytics data exists
- [x] Odds API data exists
- [ ] Verify feature store compatibility with historical dates
- [ ] Test backfill on single date first

### Notes
- Lower priority as historical data
- May need feature store regeneration first

---

## 2022-23 Season Backfill (P3)

**Status:** Not Planned

### Missing Dates
```
2022-10-18 through 2022-10-31 (14 dates)
```

### Blockers
- Minimal Odds API data (only playoffs: May-June 2023)
- Would need historical Odds API scrape
- Limited value for ML training

### Decision
Defer unless specifically needed for analysis.

---

## 2021-22 Season Backfill (P3)

**Status:** Not Planned

### Missing Dates
```
2021-10-19 through 2021-11-01 (14 dates)
```

### Blockers
- No Odds API data for this season
- Historical Odds API may not have data this far back
- Limited value for ML training

### Decision
Defer - predictions would use estimated lines only.

---

## Backfill Execution Log

| Date | Season | Start Time | End Time | Status | Predictions | Notes |
|------|--------|------------|----------|--------|-------------|-------|
| - | - | - | - | - | - | No backfills executed yet |

---

## Post-Backfill Validation Checklist

After each backfill:

1. [ ] Verify prediction count matches expected
2. [ ] Check for placeholder lines (should be 0%)
3. [ ] Run grading processor for the date
4. [ ] Verify grading accuracy in expected range
5. [ ] Update this tracker with results

---

## API Rate Limit Tracking

**Odds API Historical Endpoint:**
- Limit: 500 requests/month
- Used this month: ~20 (estimated)
- Remaining: ~480

**Cost per date backfill:**
- 1 request for events
- ~10 requests for player props (1 per game)
- Total: ~11 requests per date

**Budget for backfills:**
- 480 / 11 = ~43 dates possible this month
