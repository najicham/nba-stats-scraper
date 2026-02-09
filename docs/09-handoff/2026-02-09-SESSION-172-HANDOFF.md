# Session 172 Handoff -- Alert Hardening & Edge Case Fixes

**Date:** 2026-02-09
**Duration:** Single session
**Commits:** Pending push

## Executive Summary

Session 172 hardened the Session 170 UNDER-bias fixes with **6 alerting/logging improvements** across 4 files (~150 lines). These changes ensure that if a Session 169-style bias recurrence happens, it gets detected within minutes rather than hours. Also documented what went wrong on Feb 9 and what to watch for tomorrow.

## What Was Done

### Code Changes

| # | Change | File | Risk |
|---|--------|------|------|
| 1 | **Recommendation skew alert** — fires when OVER <15% or UNDER <15% | `coordinator.py`, `quality_alerts.py` | LOW |
| 2 | **Empty PVL warning** — logs when no predictions have lines (silent pass prevention) | `coordinator.py` | LOW |
| 3 | **Vegas source monitoring** — alerts when >30% of predictions used recovery_median | `coordinator.py`, `quality_alerts.py` | LOW |
| 4 | **Signal calc skip warning** — logs when threshold blocks signal despite predictions existing | `signal_calculator.py` | LOW |
| 5 | **Line values validation** — type-checks line_values before median calc in recovery path | `worker.py` | LOW |
| 6 | **Recovery median log noise reduction** — per-prediction INFO→DEBUG, batch summary via coordinator | `worker.py` | LOW |

### New Alert Functions

Two new Slack alert functions added to `quality_alerts.py`:
- `send_recommendation_skew_alert()` — detects 89%-UNDER-style distribution even if avg_pvl is within ±2.0
- `send_vegas_source_alert()` — detects when too many predictions fell through to recovery_median path

Both follow existing patterns: `QualityAlert` dataclass, `#nba-alerts` channel, WARNING/CRITICAL severity.

### Both `publish_batch_summary` Functions Updated

The coordinator has two batch summary functions (Firestore-based and ProgressTracker-based). Both now have identical post-consolidation quality checks:
1. PVL bias check (existing, from Session 170)
2. Empty PVL results warning (new)
3. Recommendation skew check (new)
4. Vegas source distribution check (new)

All wrapped in the existing `try/except` block — failures are non-fatal.

## Files Modified

| File | Lines Changed | Details |
|------|---------------|---------|
| `predictions/coordinator/coordinator.py` | ~90 lines added | Items 1, 2, 3 in both batch summary functions |
| `predictions/coordinator/quality_alerts.py` | ~100 lines added | `send_recommendation_skew_alert()`, `send_vegas_source_alert()` |
| `predictions/coordinator/signal_calculator.py` | ~12 lines added | Item 4 — warning when signal calc skipped |
| `predictions/worker/worker.py` | ~8 lines changed | Items 5, 6 — validation + log level change |

---

## What Went Wrong on Feb 9 — Full Root Cause Analysis

### Timeline

| Time (ET) | Event | Impact |
|-----------|-------|--------|
| ~6 AM | FIRST-run predictions generated | 42 predictions with avg_pvl = **-3.84** (89% UNDER) |
| ~8 AM | Session 169 deployed (Vegas recovery fix) | Fix deployed 8 hours after damage done |
| ~1 PM | Session 170 discovered multi-line dedup bug | Additional +2.0 UNDER bias identified |
| Afternoon | Sessions 170-171 fixes deployed | All 3 layers fixed, but Feb 9 FIRST predictions still active |

### Three Compounding Root Causes

**Layer 1: Multi-line dedup bug (+2.0 UNDER bias)**
- FIRST-run generates 5 predictions per player at lines: base-2, base-1, base, base+1, base+2
- Dedup in `batch_staging_writer.py:583` keeps latest `created_at`
- Since predictions insert sequentially, **base+2 (highest line) always wins**
- Model predicts against inflated line → systematic UNDER bias
- **Fix:** `use_multiple_lines_default = False` (Session 170, commit 1a903d38)

**Layer 2: Vegas line NULL from coordinator (-1.5 to -2.0 UNDER bias)**
- Coordinator loads `actual_prop_line` from Phase 3's stale table (often NULL for pre-game)
- Worker depends on `actual_prop_line` for Vegas override
- Without it, model runs without feature #25 (vegas_points_line) — its most important feature
- Missing Vegas → conservative predictions → UNDER bias
- **Fix:** Worker recovers Vegas from median of `line_values` (Session 169, commit 0fb76d06)

**Layer 3: Feature store Vegas overwrite (Session 168)**
- Worker unconditionally overwrote feature store Vegas data with coordinator's (stale/NULL) data
- Good Phase 4 data replaced with NULL
- **Fix:** Preserve feature store values when coordinator has no line (Session 168, deployed before Feb 9)

### Why BACKFILL Was Fine

BACKFILL runs after games, so Phase 3/4 tables are populated, coordinator has real lines, and feature store has complete data. BACKFILL avg_pvl: -0.03 to -0.24 (healthy).

### The Compounding Math

On Feb 9 FIRST run:
- Bug #1 pushes active line +2.0 above true line
- Bug #2 removes Vegas feature entirely
- Model without Vegas predicts ~3-4 points low
- Combined: predictions average 3.84 points below Vegas → 89% UNDER

---

## What to Watch for Feb 10 (Tomorrow)

**Feb 10 is the first FIRST-run with ALL fixes deployed.** This is the validation moment.

### Success Criteria

```sql
-- Run after Feb 10 FIRST-run completes (~7 AM ET):
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  JSON_EXTRACT_SCALAR(features_snapshot, '$.vegas_source') as vegas_source
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1, 6;
```

| Metric | Target | Feb 9 Actual (Bad) |
|--------|--------|--------------------|
| avg_pvl | Within ±1.5 | -3.84 |
| OVER % | >25% | 5% (3/56) |
| UNDER % | >25% | 89% (50/56) |
| vegas_source | Not null | null (many) |
| Rows per player | 1.0 | >1 (multi-line) |

### Red Flags

| Signal | Meaning | Action |
|--------|---------|--------|
| avg_pvl < -2.0 | UNDER bias persists | Check vegas_source — is recovery_median working? |
| avg_pvl > +1.5 | OVER bias | Check coordinator base_line logic |
| >85% single direction | Skew recurrence | Check Slack for RECOMMENDATION_SKEW alert |
| vegas_source = null or unknown | Vegas features missing | Check Phase 4 processor ran |
| recovery_median > 30% | Coordinator still has NULL actual_prop | Check Phase 3 line population timing |

### New Alerts to Verify

After Feb 10 FIRST-run, check Slack `#nba-alerts` for:
- `RECOMMENDATION_SKEW` — should NOT fire if distribution is balanced
- `VEGAS_SOURCE_RECOVERY_HIGH` — should NOT fire if recovery_median < 30%
- `PVL_BIAS_DETECTED` — should NOT fire if avg_pvl within ±2.0

If any fire, they're catching a real problem. That's the whole point.

### Also Pending from Session 171

- [ ] Grade Feb 8 predictions (games are Final, needs grading trigger)
- [ ] Re-trigger Feb 9 BACKFILL (same-day guard fixed)
- [ ] Investigate OddsAPI line matching failure (18% vs 83% on Feb 8)
- [ ] Check STALE_MESSAGE and PUBLISH_METRICS in Cloud Logging

---

## Current State

### Production
- **Model:** `catboost_v9_33features_20260201_011018` (SHA: `5b3a187b`)
- **Multi-line:** Disabled (Session 170)
- **Vegas pipeline:** Fixed (Sessions 168-170)
- **Post-consolidation alerts:** PVL bias + recommendation skew + vegas source (Session 172)

### Key Insight

**The model is not broken.** The pipeline was feeding it garbage input (no Vegas line, wrong active line). With clean inputs:
- BACKFILL predictions are neutral (avg_pvl ≈ 0)
- OVER picks remain profitable (57.1% hit rate)
- Feb 7 bounced back to 66.7% hit rate with clean data

The Session 172 alerts ensure we catch pipeline issues within minutes, not hours.

---

## NEXT SESSION PROMPT

Copy this into the next session:

---

### Session 173 -- Validate Feb 10 FIRST-run + Grade Backlog

**Context:** Session 172 added 6 post-consolidation quality alerts (recommendation skew, empty PVL, vegas source monitoring, signal calc skip, line validation, log reduction). Session 171 fixed pipeline throughput. Session 170 fixed multi-line dedup + Vegas NULL. All deployed.

**Read:** `docs/09-handoff/2026-02-09-SESSION-172-HANDOFF.md`

### P0: Validate Feb 10 FIRST-run predictions

```sql
SELECT prediction_run_mode, COUNT(*) as preds,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-10' AND system_id = 'catboost_v9' AND is_active = TRUE
GROUP BY 1;
```

**Target:** avg_pvl within ±1.5, balanced OVER/UNDER (>25% each).

### P1: Check new Session 172 alerts in Slack

Check `#nba-alerts` for new alert types:
- `RECOMMENDATION_SKEW` — should NOT fire if balanced
- `VEGAS_SOURCE_RECOVERY_HIGH` — should NOT fire if recovery < 30%
- `PVL_BIAS_DETECTED` — should NOT fire if avg_pvl ±2.0

### P2: Grade Feb 8 + Feb 9

```sql
SELECT game_date, COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9' AND game_date IN ('2026-02-08', '2026-02-09')
GROUP BY 1;
```

### P3: OddsAPI investigation (carried from Session 171)

Feb 9 had only 18% OddsAPI lines vs 83% on Feb 8. Root cause unknown.

---
