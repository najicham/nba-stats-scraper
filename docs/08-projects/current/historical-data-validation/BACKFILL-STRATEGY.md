# Historical Prediction Backfill Strategy

**Created:** 2026-01-23
**Status:** Active
**Priority:** P1

---

## Executive Summary

Historical predictions (2021-2025) have NULL sportsbook data because they were created before line source tracking was implemented. With the new sportsbook-priority fallback system, we can re-run predictions to get real DraftKings/FanDuel lines from BettingPros.

### Current State

| Season | Total Predictions | With Sportsbook | Using Estimates | BettingPros Available |
|--------|------------------|-----------------|-----------------|----------------------|
| 2021-22 | 117,246 | 0 (0%) | ~103K | 213 dates (full) |
| 2022-23 | 108,205 | 0 (0%) | ~94K | 212 dates (full) |
| 2023-24 | 109,035 | 0 (0%) | ~95K | 197 dates |
| 2024-25 | 108,272 | 0 (0%) | ~83K | 213 dates (full) |
| 2025-26 | 97,199 | 29,300 (30%) | 50K | 29 dates |

### Expected After Backfill

| Season | Estimated DK/FD Lines | Improvement |
|--------|----------------------|-------------|
| 2021-22 | ~100K | Real lines instead of VEGAS_BACKFILL |
| 2022-23 | ~100K | Real lines instead of VEGAS_BACKFILL |
| 2023-24 | ~100K | Real lines instead of VEGAS_BACKFILL |
| 2024-25 | ~100K | Real lines instead of VEGAS_BACKFILL |

---

## Backfill Phases

### Phase 1: Current Season (2025-26) - Immediate

**Goal:** Fix ESTIMATED lines that could be real lines

**Dates:** 2025-10-22 to present (dates with ESTIMATED lines)

**Approach:**
1. Identify dates where predictions have ESTIMATED line_source
2. Re-run coordinator for those dates
3. New fallback will pull BettingPros DK/FD lines

**Command:**
```bash
# Get dates with high ESTIMATED usage
bq query --use_legacy_sql=false "
SELECT game_date,
       COUNTIF(line_source_api = 'ESTIMATED') as estimated,
       COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE AND game_date >= '2025-10-22'
GROUP BY 1
HAVING estimated > total * 0.3
ORDER BY 1"

# Re-run for each date
COORD_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -X POST "https://prediction-coordinator-...run.app/start" \
    -H "X-API-Key: $COORD_KEY" \
    -d '{"game_date": "2025-XX-XX", "force": true}'
```

**Risk:** Low - only affects future predictions, not graded data
**Duration:** ~1 hour for all dates

---

### Phase 2: 2024-25 Season - High Priority

**Goal:** Get real DK/FD lines for most recent full season

**Dates:** 2024-10-22 to 2025-06-22 (213 dates)

**Approach:**
1. Re-run predictions for each date
2. BettingPros has full DK/FD coverage
3. Re-grade predictions after

**Estimation:**
- ~500 players per date × 213 dates = ~106,500 predictions
- BettingPros DK/FD coverage: ~95%+

**Commands:**
```bash
# Batch re-run script
for date in $(seq -f "2024-10-%02g" 22 31) $(seq -f "2024-11-%02g" 1 30) ...; do
    curl -X POST "https://prediction-coordinator-.../start" \
        -H "X-API-Key: $COORD_KEY" \
        -d "{\"game_date\": \"$date\", \"force\": true}"
    sleep 60  # Rate limit
done

# Re-grade after predictions complete
python -m data_processors.grading.prediction_accuracy.prediction_accuracy_processor \
    --start-date 2024-10-22 --end-date 2025-06-22
```

**Risk:** Medium - will update grading metrics
**Duration:** ~4 hours for predictions, ~2 hours for grading

---

### Phase 3: 2023-24 Season - Medium Priority

**Goal:** Improve ML training data quality

**Dates:** 2023-10-24 to 2024-06-17 (207 dates)

**BettingPros Coverage:**
- 197 dates (95% coverage)
- DraftKings: 41,200 rows
- FanDuel: 56,410 rows

**Approach:** Same as Phase 2

**Risk:** Medium
**Duration:** ~4 hours

---

### Phase 4: 2022-23 Season - Lower Priority

**Goal:** Complete historical dataset

**Dates:** 2022-10-18 to 2023-06-12 (212 dates)

**BettingPros Coverage:**
- 212 dates (full coverage)
- DraftKings: 41,200 rows
- FanDuel: 56,410 rows

**Risk:** Low - older data, less critical
**Duration:** ~4 hours

---

### Phase 5: 2021-22 Season - Lowest Priority

**Goal:** Complete historical dataset

**Dates:** 2021-10-19 to 2022-06-16 (213 dates)

**BettingPros Coverage:**
- 213 dates (full coverage)
- DraftKings: 1,464 rows (limited)
- FanDuel: 35,102 rows (good)

**Note:** DraftKings coverage is limited for this season, but FanDuel is available.

**Risk:** Low
**Duration:** ~4 hours

---

## Backfill Script

### Full Backfill Runner

```bash
#!/bin/bash
# backfill_predictions_with_real_lines.sh

COORD_URL="https://prediction-coordinator-756957797294.us-west2.run.app"
COORD_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)

# Function to run predictions for a date
run_predictions() {
    local game_date=$1
    echo "$(date): Running predictions for $game_date"

    response=$(curl -s -X POST "$COORD_URL/start" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: $COORD_KEY" \
        -d "{\"game_date\": \"$game_date\", \"force\": true}")

    if echo "$response" | grep -q "started"; then
        echo "  SUCCESS: $response"
    else
        echo "  ERROR: $response"
    fi

    # Rate limit
    sleep 30
}

# Phase 1: Current season dates with ESTIMATED lines
echo "=== Phase 1: 2025-26 ESTIMATED fixes ==="
# Add specific dates here after querying

# Phase 2: 2024-25 Season
echo "=== Phase 2: 2024-25 Season ==="
for month in 10 11 12; do
    for day in $(seq 1 31); do
        game_date=$(printf "2024-%02d-%02d" $month $day)
        run_predictions $game_date
    done
done
for month in 01 02 03 04 05 06; do
    for day in $(seq 1 31); do
        game_date=$(printf "2025-%02d-%02d" $month $day)
        run_predictions $game_date
    done
done

echo "=== Backfill Complete ==="
```

---

## Validation After Backfill

### Check Line Source Distribution

```sql
-- After backfill, verify sportsbook distribution
SELECT
  CASE
    WHEN game_date >= '2024-10-22' AND game_date <= '2025-06-30' THEN '2024-25'
    ELSE 'other'
  END as season,
  sportsbook,
  line_source_api,
  COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE
  AND game_date >= '2024-10-22'
GROUP BY 1, 2, 3
ORDER BY 1, 4 DESC;
```

### Expected Results

```
| season  | sportsbook  | line_source_api | count |
|---------|-------------|-----------------|-------|
| 2024-25 | DRAFTKINGS  | ODDS_API        | 30000 |
| 2024-25 | DRAFTKINGS  | BETTINGPROS     | 50000 |
| 2024-25 | FANDUEL     | BETTINGPROS     | 20000 |
| 2024-25 | BETMGM      | ODDS_API        | 5000  |
| ...     | ...         | ...             | ...   |
```

### Grading Verification

```sql
-- Check grading accuracy after backfill
SELECT
  system_id,
  COUNT(*) as total,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as accuracy_pct,
  COUNTIF(line_source_api = 'BETTINGPROS') as bettingpros_lines,
  COUNTIF(line_source_api = 'ODDS_API') as odds_api_lines
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2024-10-22' AND game_date <= '2025-06-22'
GROUP BY 1
ORDER BY 1;
```

---

## Risk Mitigation

### Before Backfill

1. **Backup current predictions:**
   ```bash
   bq cp nba_predictions.player_prop_predictions \
       nba_predictions.player_prop_predictions_backup_20260123
   ```

2. **Backup current grading:**
   ```bash
   bq cp nba_predictions.prediction_accuracy \
       nba_predictions.prediction_accuracy_backup_20260123
   ```

### During Backfill

1. **Monitor coordinator health:**
   - Check Cloud Run logs for errors
   - Monitor BigQuery slot usage

2. **Rate limiting:**
   - 30-60 second delay between dates
   - Avoid peak hours (game time)

### After Backfill

1. **Verify prediction counts match expected**
2. **Check for NULL sportsbook (should be minimal)**
3. **Re-grade and compare accuracy**
4. **Update performance dashboards**

---

## Timeline

| Phase | Season | Dates | Duration | Priority | Status |
|-------|--------|-------|----------|----------|--------|
| 0 | Code deployment | - | 30 min | P0 | DONE |
| 1 | 2025-26 fixes | ~30 dates | 1 hour | P1 | Pending |
| 2 | 2024-25 | 213 dates | 4 hours | P1 | Pending |
| 3 | 2023-24 | 207 dates | 4 hours | P2 | Pending |
| 4 | 2022-23 | 212 dates | 4 hours | P3 | Pending |
| 5 | 2021-22 | 213 dates | 4 hours | P3 | Pending |

**Total estimated time:** ~17 hours (can be parallelized)

---

## Success Metrics

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Predictions with real sportsbook | 30% (2025-26 only) | 80%+ | Backfill all seasons |
| DraftKings/FanDuel coverage | ~29K | ~400K | Use BettingPros fallback |
| ESTIMATED line_source | 50% (2025-26) | <10% | Proper fallback |
| NULL sportsbook (historical) | 100% | <5% | Re-run predictions |

---

## Next Steps

1. [ ] Deploy code changes to Cloud Run
2. [ ] Backup current predictions and grading tables
3. [ ] Run Phase 1 (2025-26 ESTIMATED fixes)
4. [ ] Validate Phase 1 results
5. [ ] Run Phase 2 (2024-25 full backfill)
6. [ ] Re-grade 2024-25 predictions
7. [ ] Continue with remaining phases
