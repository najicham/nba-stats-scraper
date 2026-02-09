# Session 171 Prompt

Copy everything below this line into a new chat:

---

## Session 171 — Verify Multi-Line Fix + Vegas Fix, Investigate Hit Rate Decline

**Start by reading:** `docs/09-handoff/2026-02-09-SESSION-170-HANDOFF.md`

**Context:**

Session 170 (Feb 9, 2026) implemented hardening for the Session 169 Vegas line fix, then discovered and fixed a **critical multi-line dedup bug**:

1. **Multi-line dedup bug (Session 170):** When `use_multiple_lines=True`, 5 predictions per player are generated (base ±2). The dedup logic always keeps the highest line (base+2), adding +2.0 systematic UNDER bias. **32/32 players on Feb 9 had active=max_line.** Fix: disabled multi-line (`use_multiple_lines_default = False`).

2. **Vegas line NULL (Session 169-170):** Coordinator sent NULL `actual_prop_line`, worker ran model without feature #25. Fix: recovery_median path + fresh base_line from odds query.

3. **Monitoring added (Session 170):** PVL bias alert (±2.0 threshold), Vegas source tracking in features_snapshot, avg_pvl in daily signals, model_version filter in subsets.

**6 commits deployed:** `cd29878b` through `1a903d38`

### P0: Verify All Fixes Are Working

**Check Feb 10 FIRST-run predictions (~6 AM ET):**
```sql
-- 1. avg_pvl should be within ±1.5, recommendations balanced
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  COUNTIF(recommendation = 'PASS') as passes
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-10' AND is_active = TRUE
GROUP BY 1;

-- 2. Vegas source should NOT be null (should be coordinator_actual or recovery_median)
SELECT JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as source,
  COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1;

-- 3. Multi-line should be disabled (1.0 rows per player)
SELECT prediction_run_mode,
  ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT player_lookup), 1) as rows_per_player
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9'
GROUP BY 1;

-- 4. avg_pvl should appear in daily signals
SELECT game_date, system_id, avg_pvl, daily_signal, pct_over
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= '2026-02-09';
```

**Target:** avg_pvl within ±1.5, OVER/UNDER balance >25% each, vegas_source NOT null, rows_per_player = 1.0.

### P1: Complete Backfills if Needed

Feb 8 and Feb 9 backfills were triggered at end of Session 170 but may not have completed:
```sql
SELECT game_date, prediction_run_mode, is_active, COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-08', '2026-02-09')
GROUP BY 1, 2, 3 ORDER BY 1, 2;
```

If missing active BACKFILL predictions:
```
POST /start {"game_date":"2026-02-08","prediction_run_mode":"BACKFILL"}
POST /start {"game_date":"2026-02-09","prediction_run_mode":"BACKFILL"}
```

### P2: Grade Feb 8 and Re-grade Feb 4

```sql
SELECT game_date, COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-04', '2026-02-08')
GROUP BY 1;
```

### P3: Investigate Hit Rate Decline

Edge 3+ hit rate dropped weekly: 71.7% → 67.3% → 57.1% → 48.1%. Now that multi-line bug is fixed, re-evaluate with clean BACKFILL predictions:

```sql
-- Hit rate on BACKFILL (single-line, clean) predictions only
SELECT pa.game_date,
  COUNT(*) as edge3_total,
  COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNTIF(pa.prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= '2026-02-04'
  AND pa.actual_points IS NOT NULL AND pa.line_value IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
GROUP BY 1 ORDER BY 1;
```

If decline persists with clean predictions, investigate:
1. **Market sharpening** — are Vegas lines getting more accurate?
2. **Feature staleness** — model trained on Nov 2-Jan 8 data, Feb may need different patterns
3. **Consider retraining** — use `/model-experiment` with extended training window through Jan 31
4. **All-Star break / trade deadline** — player rotations shifting

### P4: Investigate OddsAPI Query Failures

On Feb 9, 30 players got BettingPros lines despite OddsAPI having DraftKings data in BigQuery. This means the coordinator's per-player BQ queries either timed out or had a subtle issue.

Check fresh data:
```sql
-- How many players have OddsAPI DK data for today?
SELECT game_date, COUNT(DISTINCT player_lookup)
FROM nba_raw.odds_api_player_props
WHERE game_date = CURRENT_DATE() AND market = 'player_points'
  AND bookmaker_key = 'draftkings'
GROUP BY 1;
```

Compare to prediction line sources:
```sql
SELECT line_source_api, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1;
```

If BettingPros is still dominant despite OddsAPI availability, add logging to `player_loader.py:_query_actual_betting_line()` to track query failures.

### P5: Future Multi-Line Fix (Low Priority)

Multi-line is disabled, not fixed. If re-enabling:
- File: `predictions/shared/batch_staging_writer.py:583`
- Current dedup: `ORDER BY created_at DESC` → always picks highest line
- Option 1: Change PARTITION to include `current_points_line` (keeps one per line)
- Option 2: Select prediction where `current_points_line` = base_line
- Option 3: Leave disabled — questionable value vs complexity

### Production Model
- System: `catboost_v9`
- Model: `catboost_v9_33features_20260201_011018`
- SHA256: `5b3a187b1b6d`
- Version string: `v9_20260201_011018`
- Deployed commit: `1a903d38`
- Edge 3+ hit rate: 71.2% on Jan holdout, declining in Feb (investigate P3)
