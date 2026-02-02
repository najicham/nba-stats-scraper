# Session 75 Handoff - February 2, 2026

## Session Summary

Implemented earlier prediction timing from Session 73 design. Predictions can now run at 2:30 AM ET with REAL_LINES_ONLY mode, generating predictions for ~140 players with real betting lines as soon as Vegas lines become available.

---

## Accomplishments

### 1. REQUIRE_REAL_LINES Mode ✅

Added `require_real_lines` parameter to the coordinator:

| File | Change |
|------|--------|
| `predictions/coordinator/player_loader.py` | Added `require_real_lines` parameter to `create_prediction_requests()` |
| `predictions/coordinator/coordinator.py` | Accept and pass `require_real_lines` from /start endpoint |

**How it works:**
- When `require_real_lines=True`, players with `line_source='NO_PROP_LINE'` are filtered out
- Only players with real betting lines get predictions
- Results in higher quality predictions without estimated lines

**Usage:**
```bash
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "require_real_lines": true, "force": true}'
```

### 2. Early Prediction Scheduler ✅

Created `predictions-early` scheduler at 2:30 AM ET:

```bash
# Setup script
bin/orchestrators/setup_early_predictions_scheduler.sh
```

| Scheduler | Time (ET) | Mode | Expected Players |
|-----------|-----------|------|-----------------|
| `predictions-early` | 2:30 AM | REAL_LINES_ONLY | ~140 |
| `overnight-predictions` | 7:00 AM | ALL_PLAYERS | ~200 |
| `same-day-predictions` | 11:30 AM | ALL_PLAYERS | Catch stragglers |

### 3. Documentation Updated ✅

- Updated `docs/08-projects/current/prediction-timing-improvement/DESIGN.md` with implementation status
- Added "Early Prediction Timing (Session 74)" section to `CLAUDE.md`

### 4. Coordinator Deployed ✅

Deployed prediction-coordinator with new `require_real_lines` support:
- Revision: `prediction-coordinator-00128-stk`
- Commit: `fdc66f1d`

---

## Key Data Points

### Line Availability (Feb 1 Example)

| Time (ET) | Players with Lines | Source |
|-----------|-------------------|--------|
| 2:05 AM | 144 | BettingPros |
| 7:00 AM | ~150 | Minor additions |
| Game time | 177 | Final count |

**Insight:** Most lines available by 2:05 AM ET, 5 hours before previous 7 AM run.

### Feb 2 State (as of session end ~10 PM PST / 1 AM ET)

- 4 games scheduled: NOP@CHA, HOU@IND, MIN@MEM, PHI@LAC
- Lines not yet available (scraper runs at 2 AM ET)
- `predictions-early` will run at 2:30 AM ET when lines are available

---

## Verification Commands

```bash
# Check early scheduler exists
gcloud scheduler jobs describe predictions-early --location=us-west2

# Check line availability for today (after 2:15 AM ET)
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_lookup) as players_with_lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL"

# Check predictions with real lines
bq query --use_legacy_sql=false "
SELECT system_id, line_source, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-02')
GROUP BY 1, 2
ORDER BY 1, 2"

# Test early scheduler manually (after lines available)
gcloud scheduler jobs run predictions-early --location=us-west2
```

---

## Files Modified

| File | Change |
|------|--------|
| `predictions/coordinator/player_loader.py` | Added `require_real_lines` parameter |
| `predictions/coordinator/coordinator.py` | Accept and pass `require_real_lines` |
| `bin/orchestrators/setup_early_predictions_scheduler.sh` | New scheduler setup script |
| `docs/08-projects/current/prediction-timing-improvement/DESIGN.md` | Updated with implementation status |
| `CLAUDE.md` | Added "Early Prediction Timing" section |

---

## Next Session Priorities

### 1. Validate Early Predictions Work (After 2:30 AM ET Feb 2)

```sql
-- Check predictions were generated with real lines
SELECT system_id, line_source, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-02')
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 2. Monitor Feb 2 Hit Rate (After games complete)

```sql
SELECT
  'Feb 2' as date,
  COUNT(*) as total,
  COUNTIF(prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id = 'catboost_v9';
```

### 3. Optional Enhancements

- Add Slack notification when early predictions complete
- Create midday refresh scheduler for newly-added lines
- Add monitoring dashboard for early vs morning prediction coverage

---

## Technical Notes

### Why 2:30 AM Not 2:00 AM

- Props scraper runs at 7 AM UTC = 2 AM ET
- Takes ~15 min to complete and load to BigQuery
- 2:30 AM gives 15 min buffer for data availability

### Line Source Tracking

Already implemented in schema:
- `line_source`: 'ACTUAL_PROP', 'NO_PROP_LINE', 'ESTIMATED_AVG'
- `line_source_api`: 'ODDS_API', 'BETTINGPROS', NULL
- `sportsbook`: 'DRAFTKINGS', 'FANDUEL', etc.

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
