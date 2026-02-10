# Session 173 Handoff — Grading Catchup, Multi-line Contamination Discovery, Performance Decline

**Date:** 2026-02-09
**Duration:** Single session
**Commits:** 1 (docs only — `5082e355`)

## Executive Summary

Session 173 caught up Feb 8 grading, discovered that **all Feb 5-8 BACKFILL predictions are contaminated** by the multi-line dedup bug (generated before Session 170 fix), and identified a **multi-week model performance decline** from 71.2% to ~50% on edge 3+ picks. The contamination only affects non-actionable predictions (edge < 3), so the performance decline is genuine, not a data artifact.

## What Was Done

### 1. Committed Session 172 Handoff + Cloudbuild Configs
- Pushed `5082e355` with handoff doc and 3 cloudbuild YAML files
- All Session 172 code changes were already in commit `9795ea60` (pushed as part of Session 171)
- Worker.py fixes (line values type-check, log level change) already deployed

### 2. Triggered Feb 8 Grading
- Published to `nba-grading-trigger` for `2026-02-08`
- Result: **52 graded, MAE 4.37, 38.5% overall, 33.3% edge 3+**

### 3. Discovered Multi-line Bug Contamination in Feb 5-8 Predictions

All active BACKFILL predictions for Feb 5-8 were generated BEFORE Session 170's multi-line fix:

| Date | Pre-fix | Post-fix | Wrong UNDER % |
|------|---------|----------|---------------|
| Feb 5 | 104 | 0 | 16.3% |
| Feb 6 | 73 | 0 | 17.8% |
| Feb 7 | 137 | 0 | 16.1% |
| Feb 8 | 40 | 13 | 9.4% |

~16% have UNDER recommendation despite positive PVL. The model's `_generate_recommendation()` used inflated multi-line betting_line (base+2), while `current_points_line` stores the real prop line.

**Key finding: ZERO contamination in edge >= 3 tier.** All contaminated predictions are low-edge (0-2 points) non-actionable. Actionable grading is clean.

### 4. Attempted Re-BACKFILL (Won't Work)
- BACKFILL only fills gaps — doesn't regenerate existing predictions
- `/regenerate-with-supersede` would work but Vegas data is stale (0% coverage for Feb 5)
- Old predictions are stuck. Edge 3+ tier is clean regardless.

### 5. Resolved OddsAPI Investigation (from Session 171)

| Date | Raw OddsAPI Records | OddsAPI % in Predictions |
|------|---------------------|-------------------------|
| Feb 7 | 23 (1 game) | 3.6% |
| Feb 8 | 706 (4 games) | 83.0% |
| Feb 9 | 1,087 (10 games) | 23.3% |

- Feb 7: Genuinely low scrape volume (1 game)
- Feb 9: Raw data fine, but FIRST-run happened before scrape completed → BettingPros fallback
- No bug — fallback working as designed

### 6. Model Performance Decline Identified

**Weekly edge 3+ hit rate:**

| Week | Picks | Hit Rate | Edge 5+ Hit |
|------|-------|----------|-------------|
| Jan 11 | 146 | **71.2%** | **82.3%** |
| Jan 18 | 111 | **66.7%** | **85.2%** |
| Jan 25 | 101 | 55.4% | 65.4% |
| Feb 1 | 73 | 53.4% | 65.0% |
| Feb 8 | 9 | 33.3% | 33.3% |

**Feb 1-8 aggregate:** 82 edge 3+ picks, **51.2% hit rate**. Edge 5+: 23 picks, 60.9%.

Model trained Nov 2 - Jan 8. Performance steadily declining since late January — likely concept drift from trade deadline, rotation changes, schedule pattern shifts.

---

## Grading Status

| Date | Games | Status | Graded | Edge 3+ Hit |
|------|-------|--------|--------|-------------|
| Feb 5 | 8 | Final | 101 | 37.5% (8) |
| Feb 6 | 4 | Final | 69 | 30.0% (10) |
| Feb 7 | 8 | Final | 131 | 66.7% (21) |
| Feb 8 | 4 | Final | 52 | 33.3% (9) |
| Feb 9 | 10 | Scheduled | — | — |
| Feb 10 | 4 | Scheduled | — | — |

---

## Current State

- **Model:** `catboost_v9_33features_20260201_011018` (SHA: `5b3a187b`)
- **Deployed commit:** `5082e355` (via Cloud Build auto-deploy)
- **Multi-line:** Disabled (Session 170)
- **Vegas pipeline:** Fixed (Sessions 168-170)
- **Post-consolidation alerts:** Deployed (Session 172 code in commit `9795ea60`)
- **Performance:** Declining — 51.2% edge 3+ (Feb 1-8) vs 71.2% holdout

---

## NEXT SESSION PROMPT

### Session 174 — Validate Feb 10 FIRST-run + Performance Decision

**Context:** Session 173 confirmed all pipeline fixes are deployed and grading is caught up through Feb 8. Discovered model performance declining from 71.2% to 51.2% on edge 3+ (genuine, not data artifact). Feb 10 is the first FIRST-run with all fixes.

**Read:** `docs/09-handoff/2026-02-09-SESSION-173-HANDOFF.md`

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

**Target:** avg_pvl within +/- 1.5, balanced OVER/UNDER (>25% each). Feb 9 FIRST was -3.84 avg_pvl / 95% UNDER — that should be gone.

Check `#nba-alerts` for new alerts (RECOMMENDATION_SKEW, VEGAS_SOURCE_RECOVERY_HIGH, PVL_BIAS_DETECTED). None should fire if pipeline is healthy.

### P1: Grade Feb 9 (after games complete)

```bash
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-02-09"}' --project=nba-props-platform
```

Note: Feb 9 FIRST-run predictions have -3.84 avg_pvl bias (pre-fix). BACKFILL will be clean.

### P2: Evaluate model retraining

Edge 3+ hit rate dropped from 71.2% (Jan 11-17) to 51.2% (Feb 1-8). If Feb 10 also underperforms:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_FEB_RETRAIN_EVAL" \
    --train-start 2025-11-02 \
    --train-end 2026-02-08
```

**CRITICAL:** Session 163 showed better MAE doesn't mean better betting. Follow ALL governance gates. Never deploy without passing gates + user approval.

### P3: Clean up stalled batches (low priority)

3 stalled Feb 9 batches at 0/1 in coordinator. If they block future batches:
```bash
TOKEN=$(gcloud auth print-identity-token) && curl -X POST \
  "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/reset" \
  -H "Authorization: Bearer $TOKEN"
```
