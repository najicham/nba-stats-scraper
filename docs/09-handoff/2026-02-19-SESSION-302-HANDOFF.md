# Session 302 Handoff: Post-ASB Pipeline Recovery, Batch Lock Fix, Historical Backfill

**Date:** 2026-02-19
**Focus:** Getting Feb 19 predictions live before games (P0), fixing OddsAPI batch lock root cause, Phase 6 export chain fix, historical 12-book odds backfill.

## TL;DR

Recovered the full pipeline for Feb 19 (first night back from All-Star break, 10 games). Root cause: Firestore batch lock on game lines blocked 9/10 games from loading into BQ, which cascaded to NULL features → quality gate → only 6 predictions. Cleared locks, loaded all data, re-ran Phase 4 + Phase 5, got **81 predictions per model** (972 total). Fixed the batch lock re-entry bug so it won't recur. Also fixed Phase 6 export (missing `status` field in Pub/Sub message) and restarted historical odds backfill.

## Critical Fix: OddsAPI Batch Lock Re-Entry

- **File:** `data_processors/raw/handlers/oddsapi_batch_handler.py`
- **Bug:** Firestore batch lock (`batch_processing_locks/oddsapi_{type}_batch_{date}`) was created via atomic `create()` and updated to `status: complete` after processing, but **never deleted**. Subsequent scrape cycles for the same date saw the existing document and skipped processing — even though new game files had arrived in GCS.
- **Impact:** On Feb 19, the first scrape at 07:01 UTC processed IND@WAS (only game in GCS at that time). All 9 later games were blocked by the completed lock. Only 1/10 games had game lines in BQ → features f38/f41/f42 NULL for 140 players → quality gate blocked 147/153 → only 6 predictions.
- **Fix:** When lock `create()` fails with `AlreadyExistsError`, check the existing lock's status. If terminal (`complete`/`failed`/`timeout`/`error`), delete it and retry once. Active `processing` locks still respected. `_is_retry` flag prevents infinite recursion.
- **Commit:** `dda7851c`

## Pipeline Recovery Steps (for reference if needed again)

1. **Clear Firestore locks:**
```python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
db.collection('batch_processing_locks').document('oddsapi_game-lines_batch_2026-02-19').delete()
db.collection('batch_processing_locks').document('oddsapi_player-props_batch_2026-02-19').delete()
```

2. **Run batch processors locally:**
```python
PYTHONPATH=. python3 -c "
from data_processors.raw.oddsapi.oddsapi_batch_processor import OddsApiGameLinesBatchProcessor
processor = OddsApiGameLinesBatchProcessor()
processor.run({'bucket': 'nba-scraped-data', 'project_id': 'nba-props-platform', 'game_date': '2026-02-19'})
"
# Same for OddsApiPropsBatchProcessor
```

3. **Re-run Phase 4 (feature store only — UPCG already had data):**
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-02-19", "processors": ["MLFeatureStoreProcessor"], "skip_dependency_check": true}'
```

4. **Reset coordinator stale batch and start new:**
```bash
curl -X POST ".../reset" -H "Authorization: Bearer $TOKEN" -d '{"game_date": "2026-02-19"}'
curl -X POST ".../start" -H "Authorization: Bearer $TOKEN" -d '{"game_date": "2026-02-19"}'
```

5. **Trigger Phase 6 export (must include `status: success`):**
```bash
gcloud pubsub topics publish nba-phase5-predictions-complete --project=nba-props-platform \
  --message='{"processor_name":"PredictionCoordinator","phase":"phase_5_predictions","execution_id":"manual","correlation_id":"manual","game_date":"2026-02-19","output_table":"player_prop_predictions","output_dataset":"nba_predictions","status":"success","record_count":81}'
```

## Pipeline State (Feb 19, end of session)

| Component | Status | Details |
|-----------|--------|---------|
| Predictions | **81/model** | 12 main models × 81 = 972, all 10 games |
| Feature Quality | **83 avg** | 81 quality-ready, 68 zero-defaults |
| Game Lines | **10/10 games** | 1,920 rows loaded |
| Player Props | **144 players, 12 books** | 6,430 rows loaded |
| Tonight Export | **Live** | `v1/tonight/2026-02-19.json` |
| Batch Lock Fix | **Deployed** | Build `47190b1f` SUCCESS |
| Historical Backfill | **Running** | 12 books through Jan 18, Jan 25+ loading |

### Prediction Quality

- Max edge: 1.88 (Julian Champagnie, 8.4 vs 6.5 line)
- **0 edge 3+ picks** — no actionable bets for tonight
- All 81 predictions have ACTUAL_PROP lines (100% gradable)
- This is the first game back from a 5-day All-Star break; tight lines are expected

## Historical Odds Backfill

### Current Coverage
```
Week         | Books | Status
2025-10-26   |  12   | ✅
...through   |  12   | ✅
2026-01-18   |  12   | ✅
2026-01-25   |   2   | ⏳ loading
2026-02-01   |   2   | ⏳ loading
2026-02-08   |  12   | ✅ (live scraping)
2026-02-15   |  12   | ✅ (live scraping)
```

### Running Processes
Two backfill processes active (safe — uses MERGE):
1. Session 300 process: `--start-date 2025-11-02 --end-date 2026-02-12 --historical` (running since 09:48 UTC)
2. Session 302 process: `--start-date 2026-01-05 --end-date 2026-02-07 --historical` (running since 13:07 UTC)

### Verify completion:
```sql
SELECT DATE_TRUNC(game_date, WEEK) as week, COUNT(DISTINCT bookmaker) as books
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2026-01-18' AND points_line IS NOT NULL
GROUP BY 1 ORDER BY 1;
-- Expected: all weeks at 12 books
```

## Key Learnings

1. **Firestore batch locks need cleanup after completion.** The `create()` pattern is good for deduplication during active processing, but completed locks must allow re-processing. The fix checks lock status before skipping.

2. **Manual Pub/Sub messages must include `status: "success"`.** The Phase 5→6 orchestrator validates this field (line 191-197 of `phase5_to_phase6/main.py`) and silently drops messages without it. This wasted 20 minutes debugging a "missing" export.

3. **Game lines arrive incrementally.** The scraper runs every ~30 min. Early morning only has 1-2 games; by game time all games are available. The batch handler must allow re-processing as new data arrives throughout the day.

4. **Coordinator /status may return stale data.** Cloud Run routes `/status` to any instance, but the active batch state lives in a specific instance's memory. `/status` said "no_active_batch" while another instance was actively processing 334 players.

5. **Phase 4 MLFeatureStoreProcessor reads UPCG, not raw game lines.** Features f38/f41/f42 come from `nba_analytics.upcoming_player_game_context` (Phase 3), not directly from `nba_raw.odds_api_game_lines` (Phase 2). If UPCG already has game_total/game_spread, only Phase 4 needs to re-run — not Phase 3.

## Commits This Session

```
dda7851c fix: OddsAPI batch lock re-entry — allow re-processing after completed batch
```

## Files Changed

| File | Change |
|------|--------|
| `data_processors/raw/handlers/oddsapi_batch_handler.py` | Lock re-entry: check status, delete completed locks, retry once |

## Next Session Priorities

### P1: Verify Historical Backfill Complete
Check that all weeks Jan 25 → Feb 7 have 12 books. If processes died, restart:
```bash
PYTHONPATH=. python scripts/backfill_odds_api_props.py --start-date 2026-01-25 --end-date 2026-02-07 --historical
```

### P2: Grade Feb 19 Games
After tonight's games finish (~11 PM ET), check grading:
```sql
SELECT game_date, COUNT(*) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hit_rate,
  COUNTIF(predicted_margin >= 3) as edge3_n,
  ROUND(100.0 * COUNTIF(predicted_margin >= 3 AND prediction_correct = TRUE) /
    NULLIF(COUNTIF(predicted_margin >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9'
GROUP BY 1;
```
Note: 0 edge 3+ predictions, so edge3_hr will be NULL. Overall hit rate is still informative for first post-ASB performance.

### P3: Multi-Book Line Feature Architecture
With 12 books loaded, research queries can now run:
- Does high line_std correlate with model accuracy?
- Sharp vs soft book signal analysis
- Juice asymmetry vs actual results
See Session 300 handoff for full research query list and proposed `player_line_summary` table design.

### P4: Retrain Shadow Models
Wait for 2-3 days of post-ASB graded data. Current champion (V9) is at 35+ days since training. All shadow models stale/BLOCKED.

### P5: Investigate Coordinator Dual-Batch Issue
The coordinator ran two concurrent batches (`9402bf85` and `b38043de`) — both loaded 334 players but only one produced predictions. The `/status` endpoint showed `no_active_batch` while processing was active. Consider adding Firestore-based batch tracking for cross-instance visibility.

## Infrastructure Notes

- **Feb 20:** 9 games scheduled. Pipeline should auto-run with the batch lock fix deployed. Verify predictions > 6 by 4 PM ET.
- **Enrichment trigger** runs at 18:40 UTC — enriches predictions with prop lines and deactivates injured players.
- **Phase 6 export** depends on coordinator publishing to `nba-phase5-predictions-complete`. If coordinator batch tracking fails, manual publish needed (see recovery steps above).
