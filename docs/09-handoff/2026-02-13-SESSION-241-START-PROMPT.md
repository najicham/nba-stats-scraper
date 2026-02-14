Read the handoff at `docs/09-handoff/2026-02-13-SESSION-240-HANDOFF.md`.

## Goal

Rethink and fix the prediction pipeline so we predict ALL players, not just those with prop lines. Currently only ~30-40% of quality-ready players get predictions because the coordinator filters to players with lines.

## Context

- The model predicts POINTS — it doesn't need a prop line. The line is only for the over/under recommendation.
- The OVERNIGHT run mode (pre-Feb 8) used to include all players. Around Feb 8, the system switched to FIRST+LAST_CALL+RETRY modes that only predict players with lines.
- The enrichment trigger at 18:40 UTC already updates predictions with lines when they appear later — it sets `current_points_line`, recalculates recommendation, etc.
- V12 is vegas-free so it doesn't even use the line as a feature. V9 does use vegas features.

## Tasks

1. **Investigate the scheduler change**: Why did prediction runs switch from OVERNIGHT to FIRST+LAST_CALL around Feb 8? Check Cloud Scheduler jobs and coordinator deploy history. Find what payload each scheduler job sends (especially `require_real_lines` and `prediction_run_mode`).

2. **Fix the pipeline**: Make all prediction runs include ALL quality-ready players from the feature store, not just those with lines. Players without lines should get `line_source='NO_PROP_LINE'` and `recommendation='NO_LINE'`. The enrichment trigger will fill in lines later.

3. **Consider re-prediction**: When a line arrives via enrichment, should we re-run the prediction? For V12 (vegas-free), no — the prediction doesn't change. For V9, the line is a major feature (~30% importance), so re-predicting with the line would improve accuracy. Think about whether this is worth implementing or if enrichment-only (just updating recommendation/edge) is good enough.

4. **Grading for MAE**: Currently NO_PROP_LINE predictions are excluded from grading. We should grade them for MAE (predicted vs actual points) even without a line. Hit rate grading still needs a line. Check how the grading system filters and whether we need changes.

## Key files

- `predictions/coordinator/coordinator.py` — /start endpoint, run modes
- `predictions/coordinator/player_loader.py` — player filtering, `require_real_lines`
- `data_processors/enrichment/prediction_line_enrichment/` — enrichment processor
- `orchestration/cloud_functions/enrichment_trigger/main.py` — enrichment scheduling

## Quick start

```bash
# Check scheduler jobs
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep -i predict

# Check what LAST_CALL sends
gcloud scheduler jobs describe <job-name> --location=us-west2 --project=nba-props-platform --format=json | jq '.httpTarget.body' | base64 -d

# Check current run mode distribution
bq query --use_legacy_sql=false "
SELECT game_date, prediction_run_mode, COUNT(*) as cnt,
  COUNTIF(line_source = 'NO_PROP_LINE') as no_prop
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-05'
GROUP BY 1, 2 ORDER BY 1, 2"
```
