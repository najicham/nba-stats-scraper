# Session 173 Handoff — Consolidated from Sessions 170-172

**Date:** 2026-02-09
**Context:** Three sessions (170, 171, 172) fixed critical pipeline bugs and added monitoring. This handoff consolidates all pending work for a fresh session.

## What Was Fixed (Sessions 170-172)

### Session 170 — Found and fixed 3 layers of UNDER bias
| Fix | Commit | Impact |
|-----|--------|--------|
| Multi-line dedup bug (+2.0 UNDER bias) | `1a903d38` | Disabled multi-line — dedup always kept base+2 |
| Vegas line NULL from coordinator | `fc1c6aaf` | Fresh `base_line` from odds query instead of stale Phase 3 |
| PVL bias monitoring + avg_pvl in signals | `cd29878b`, `a316df97` | Alert when avg(pred - line) > ±2.0 |
| Model version filter in subset queries | `100ca7e6` | Prevents stale model predictions leaking |

### Session 171 — Pipeline throughput & reliability
| Fix | Commit | Impact |
|-----|--------|--------|
| BACKFILL date guard `>=` → `>` | `75c6218c` | Same-day backfills now allowed |
| Pub/Sub publish delay 0.1s → 0.02s | `75c6218c` | 5x faster (~45s → ~9s for 450 players) |
| `invalid_features` + `quality_too_low` → permanent skip | `75c6218c` | Stops infinite retry loops |
| Stale message ACK (3 code paths) | `75c6218c`, `6e2b3900` | Past-date failures ACK immediately |
| PUBLISH_METRICS structured logging | `6e2b3900` | Visibility into publish rate |
| Recommendation skew Slack alert (>85% one direction) | `9795ea60` | Catches Session 170-style bias instantly |
| Vegas source recovery Slack alert (>30% recovery_median) | `9795ea60` | Catches Session 169-style vegas NULL |
| CONSOLIDATION_METRICS + deactivation timing | `9795ea60` | Consolidation performance visibility |
| Signal calculator 0-rows diagnostic | `9795ea60` | Warns when signals skip despite predictions existing |

### Session 172 — Validated orchestration, added 2 worker hardening items
| Fix | Status | Impact |
|-----|--------|--------|
| Line values type-check in recovery median path | **Pending push** | Prevents crash on non-numeric line_values |
| Recovery median log noise (INFO→DEBUG) | **Pending push** | Reduces production log volume |

**Note:** Session 172 also independently added the same alerts as Session 171 (recommendation skew, vegas source, etc). Our copies are already on main. Session 172's duplicate alert code should be dropped when merging — keep only their 2 unique worker.py items.

---

## Current Production State

- **Model:** `catboost_v9_33features_20260201_011018` (SHA: `5b3a187b`)
- **Deployed commit:** `9795ea60` (via Cloud Build auto-deploy)
- **Multi-line:** Disabled (Session 170)
- **Vegas pipeline:** Fixed (Sessions 168-170)
- **Post-consolidation alerts:** PVL bias + recommendation skew + vegas source (Sessions 170-171)

---

## Pending Work (Prioritized)

### P0: Verify Feb 10 FIRST-run predictions (~6 AM ET)

**This is the first FIRST-run with ALL fixes deployed.** The true validation moment.

```sql
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as vegas_source
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1, 6;
```

| Metric | Target | Feb 9 FIRST (Bad) |
|--------|--------|-------------------|
| avg_pvl | Within ±1.5 | -3.84 |
| OVER % | >25% | 5% |
| UNDER % | >25% | 89% |
| vegas_source | NOT null | null (many) |
| Rows per player | 1.0 | >1 (multi-line) |

Also check `#nba-alerts` in Slack — new alerts should NOT fire if everything is healthy:
- `RECOMMENDATION_SKEW` — fires if >85% one direction
- `VEGAS_SOURCE_RECOVERY_HIGH` — fires if >30% used recovery_median
- `PVL_BIAS_DETECTED` — fires if avg_pvl > ±2.0

### P1: Trigger Feb 9 BACKFILL + Grade Feb 8 and Feb 9

**Feb 9 BACKFILL was blocked** by the same-day date guard (now fixed). Needs re-trigger:
```
POST /start {"game_date":"2026-02-09","prediction_run_mode":"BACKFILL"}
```

**Feb 8** has 53 active BACKFILL predictions (avg_pvl = 0.00) but **0 graded records**. Games are Final.

```sql
-- Check grading status
SELECT game_date, COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-08', '2026-02-09')
GROUP BY 1;

-- Check Feb 9 backfill after trigger
SELECT game_date, prediction_run_mode, is_active, COUNT(*) as cnt,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09'
GROUP BY 1, 2, 3 ORDER BY 1, 2;
```

### P2: Merge Session 172's 2 unique worker.py fixes

Session 172 has 2 items not yet on main (their push is pending):
1. **Line values type-check** in recovery median path (`worker.py`) — prevents crash on bad data
2. **Recovery median log level** INFO→DEBUG (`worker.py`) — reduces noise

Either cherry-pick their commits or manually apply the changes. Their alert code (skew, vegas source) is duplicate of ours — skip those files.

### P3: Investigate OddsAPI line matching failure

Feb 9 had only **18% OddsAPI lines** vs **83% on Feb 8**, despite 131 players having DraftKings data in BigQuery.

```sql
-- Check line sources by date
SELECT game_date, line_source_api, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date IN ('2026-02-08', '2026-02-09', '2026-02-10')
  AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1, 2 ORDER BY 1, 3 DESC;
```

Possible causes:
- Per-player BQ query timeout (30s sequential)
- Timing mismatch between odds scrape and prediction run
- Query filter mismatch (player_lookup format vs OddsAPI player_name)

Actions:
- Add logging to `player_loader.py:_query_actual_betting_line()` to distinguish "no data" vs "query timeout"
- Check Feb 10 line sources — if still low OddsAPI %, the problem is systemic

### P4: Hit rate investigation — consider model retrain

Edge 3+ hit rate declined over 4 weeks:

| Week | Hit Rate | Sample | MAE |
|------|----------|--------|-----|
| Jan 11 | **71.7%** | 127 | 5.25 |
| Jan 18 | **66.7%** | 111 | 4.64 |
| Jan 25 | **55.4%** | 101 | 4.80 |
| Feb 1 | **48.1%** | 81 | 5.40 |

**Key findings:**
- Market sharpening: **RULED OUT** (Vegas miss from line stable)
- Model MAE: **Degraded** from 4.64 to 5.40 in Feb
- OVER picks: **57.1%** (still profitable)
- UNDER picks: **48.4%** (losing)
- Feb 7 bounced back to **66.7%** — signal isn't dead

Now that bugs are fixed, re-evaluate with clean BACKFILL predictions:
```sql
SELECT DATE_TRUNC(pa.game_date, WEEK) as week,
  COUNT(*) as graded,
  COUNTIF(pa.prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
  ON pa.player_lookup = p.player_lookup AND pa.game_date = p.game_date AND pa.system_id = p.system_id
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= '2026-01-12'
  AND pa.actual_points IS NOT NULL AND pa.line_value IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND p.is_active = TRUE AND p.prediction_run_mode = 'BACKFILL'
GROUP BY 1 ORDER BY 1;
```

If hit rate stays below 55% with clean data, consider `/model-experiment` with extended training window through Jan 31.

### P5: Verify new logging in Cloud Logging

```bash
# Stale messages being cleaned up (should see STALE_MESSAGE logs)
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"STALE_MESSAGE"' \
  --limit=10 --freshness=24h --project=nba-props-platform

# Publish metrics appearing
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"PUBLISH_METRICS"' \
  --limit=5 --freshness=24h --project=nba-props-platform

# Consolidation metrics
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"CONSOLIDATION_METRICS"' \
  --limit=5 --freshness=24h --project=nba-props-platform
```

### P6 (Low): Future improvements

| Improvement | Priority | Notes |
|-------------|----------|-------|
| DLQ queue depth metrics | Next session | Only remaining observability gap |
| Multi-line dedup fix | Low | Currently disabled, not broken. Fix option: keep base_line instead of latest |
| End-to-end trace IDs | Low | Current 8-char UUIDs work, nice-to-have |

---

## Architecture Reference

**Key files modified in Sessions 170-172:**

| File | What It Does |
|------|-------------|
| `predictions/coordinator/coordinator.py` | Orchestrates batches, publishes to Pub/Sub, runs post-consolidation checks |
| `predictions/coordinator/quality_alerts.py` | Slack alert functions for #nba-alerts |
| `predictions/coordinator/signal_calculator.py` | Calculates daily GREEN/YELLOW/RED signals |
| `predictions/coordinator/player_loader.py` | Loads player data + betting lines (OddsAPI/BettingPros) |
| `predictions/worker/worker.py` | Handles individual player predictions via Pub/Sub push |
| `predictions/shared/batch_staging_writer.py` | Staging writes + MERGE consolidation + dedup |
| `shared/config/orchestration_config.py` | `use_multiple_lines_default = False` (Session 170) |

---
