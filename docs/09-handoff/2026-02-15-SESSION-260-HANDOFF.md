# Session 260 Handoff — Adaptive Prediction System Phase 1

**Date:** 2026-02-15
**Status:** Code complete, committed. Deploy pending.
**Depends on:** Session 259 DDLs + deploy (if not already done)

---

## What Was Done

### 1A. Configurable Model Selection

**New file:** `shared/config/model_selection.py`
- `get_best_bets_model_id()` — reads `BEST_BETS_MODEL_ID` env var, defaults to `catboost_v9`
- `get_champion_model_id()` — always returns `catboost_v9` (for baseline comparisons)

**Removed hardcoded `SYSTEM_ID = 'catboost_v9'` from 3 files:**
- `ml/signals/supplemental_data.py` — all query functions now accept optional `system_id`
- `data_processors/publishing/signal_best_bets_exporter.py` — uses `get_best_bets_model_id()`
- `data_processors/publishing/signal_annotator.py` — uses `get_best_bets_model_id()`

### 1B. Signal Health Weighting (LIVE in Aggregator)

**Modified:** `ml/signals/aggregator.py`
- `BestBetsAggregator` now accepts `signal_health` dict
- HOT regime signals contribute 1.2x to effective signal count
- COLD regime signals contribute 0.5x (demoted, not blocked)
- NORMAL/unknown = 1.0x (identical to Session 259 behavior)
- Both exporter and annotator pass signal health to aggregator

**Fail-safe:** If `signal_health_daily` table is empty or missing, the aggregator operates identically to Session 259 (all signals 1.0x).

---

## What Needs to Be Done (Next Session)

### Priority 1: Session 259 Prerequisites (if not already done)

Run BQ DDLs, push, backfill — see `docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md`

### Priority 2: Push Session 260 Changes

```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

### Priority 3: Evaluate Which Model to Use for Best Bets

```sql
-- Check challenger performance with latest data
SELECT
  system_id,
  COUNT(*) AS graded,
  COUNTIF(ABS(predicted_points - line_value) >= 3.0) AS edge3_total,
  COUNTIF(ABS(predicted_points - line_value) >= 3.0 AND prediction_correct) AS edge3_wins,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3.0 AND prediction_correct)
    / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3.0), 0), 1) AS hr_edge3
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND prediction_correct IS NOT NULL
  AND is_voided IS NOT TRUE
GROUP BY system_id
HAVING edge3_total >= 10
ORDER BY hr_edge3 DESC
```

If a model clears 52.4% HR with N >= 50:
```bash
gcloud run services update <phase6-service> --region=us-west2 \
  --update-env-vars="BEST_BETS_MODEL_ID=<chosen_model_system_id>"
```

### Priority 4: Backfill Q43/Q45 for Feb 1-7 (Optional, increases sample size)

Trigger BACKFILL for challenger models to add graded data for model evaluation.

### Priority 5: Verify Signal Health Weighting

```bash
# After next game day with signal health data:
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/latest.json | python3 -m json.tool | head -30
# signal_health should appear with regime data
# picks (if any) should reflect weighted scoring
```

---

## Key Decisions

1. **Model selection is an env var, not a code change.** Switching models requires zero deploys — just update the env var. Rollback = remove env var.

2. **Signal health weighting is LIVE, not observation-only.** Session 259 concluded health is informational. Session 260 promotes it to active scoring. The multipliers are conservative (0.5x-1.2x range) and fail-safe to 1.0x.

3. **`signal_health.py` still uses hardcoded `catboost_v9`.** Signal health is computed against the champion's prediction accuracy, which is the historical baseline. This is intentional — signal health should track absolute performance, not relative to whatever model currently drives best bets.

---

## Files Changed

| File | Action |
|------|--------|
| `shared/config/model_selection.py` | NEW |
| `ml/signals/aggregator.py` | MODIFY — health weighting |
| `ml/signals/supplemental_data.py` | MODIFY — configurable system_id |
| `data_processors/publishing/signal_best_bets_exporter.py` | MODIFY — configurable model + health pass-through |
| `data_processors/publishing/signal_annotator.py` | MODIFY — configurable model + health pass-through |
| `docs/08-projects/current/signal-discovery-framework/SESSION-260-ADAPTIVE-PREDICTION-SYSTEM.md` | NEW |

---

## Phase 2 Roadmap (Future Session)

- `model_performance_daily` BQ table
- Automated decay + challenger-beats-champion Slack alerts
- Weekly combo registry stat refresh
- `validate-daily` Phase 0.58
