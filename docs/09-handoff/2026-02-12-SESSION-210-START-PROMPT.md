# Session 210 Start Prompt

Read the handoff: `docs/09-handoff/2026-02-12-SESSION-209-HANDOFF.md`

## Context

Session 209 discovered QUANT shadow models (Q43/Q45) silently produced **0 predictions** on Feb 8-9 and only 2 on Feb 10, while champion had 110/220/20. Root cause (Session 192 quality gate bug) is fixed — Feb 11 shows 196 predictions for all models. But we have:

1. **Missing QUANT data** for Feb 8-10 that needs backfill
2. **No validation** that catches when shadow models stop producing predictions
3. This should never happen again silently

## Your Job — Execute All Three

### 1. Backfill Feb 8-10 QUANT predictions

```bash
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)

for DATE in 2026-02-08 2026-02-09 2026-02-10; do
  echo "=== Backfilling $DATE ==="
  curl -X POST "${COORDINATOR_URL}/start" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\":\"$DATE\",\"prediction_run_mode\":\"BACKFILL\",\"skip_completeness_check\":true}"
  sleep 60
done
```

Use `/start` NOT `/regenerate-with-supersede` (don't supersede existing champion predictions). Verify with:
```sql
SELECT system_id, game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_q4%' AND game_date BETWEEN '2026-02-08' AND '2026-02-10'
GROUP BY 1, 2 ORDER BY 2, 1
```

### 2. Add cross-model parity check to `reconcile-yesterday` skill

Add as **Phase 9: Cross-Model Prediction Coverage** in `.claude/skills/reconcile-yesterday/SKILL.md`.

Core query compares each shadow model's prediction count vs champion. Alert if any model <80% of champion count. CRITICAL if 0 or <50%. Include the exact backfill curl command in the output when gaps are found.

### 3. Add cross-model parity check to `validate-daily` skill

Add the same check to `.claude/skills/validate-daily/SKILL.md` near the prediction validation sections. This catches same-day gaps before they compound.

### 4. Check Feb 11 QUANT grading (if games are graded by now)

```sql
SELECT system_id, COUNT(*) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_total,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v9_q43_train1102_0131', 'catboost_v9_q45_train1102_0131')
  AND game_date >= '2026-02-08' AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
```

If Q43 has 50+ edge 3+ graded predictions, run `/compare-models` for thorough evaluation.

## Key Facts

- Coordinator URL: `https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app`
- Champion: catboost_v9 (decaying, 41.8% last week)
- Q43/Q45: First real data day was Feb 11 (196 predictions each, 14 games)
- Quality gate fix: Session 192, deployed Feb 11
- Phase 6 DNP gaps feature: deployed Session 209
- Use `LIKE 'catboost_v9_%'` to auto-discover shadow models (don't hardcode names)
