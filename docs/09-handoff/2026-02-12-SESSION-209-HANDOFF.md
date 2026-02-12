# Session 209 Handoff — Shadow Model Coverage Gap & Cross-Model Validation

**Date:** 2026-02-12
**Previous:** Session 208 (Phase 3 tracking investigation)
**Priority:** P1 — Shadow models silently missing predictions, no monitoring catches it

---

## Executive Summary

Session 209 discovered that QUANT shadow models (Q43/Q45) produced **zero predictions** on Feb 8-9 and only **2 predictions** on Feb 10, while the champion (catboost_v9) produced 110, 220, and 20 respectively. This went undetected because **no validation skill compares prediction counts across models**. The root cause (Session 192 quality gate bug) is fixed, but we need to:

1. **Backfill** Feb 8-10 QUANT predictions (feature store data exists, predictions don't)
2. **Add cross-model parity validation** so this is caught immediately next time
3. **Make it automated/visible** — gaps should be flagged with exact backfill commands

---

## What Was Accomplished in Session 209

### Pipeline Validation (All Healthy)
- Deployment drift: OK (all services up to date)
- Heartbeats: OK (31 docs, 0 bad)
- IAM permissions: OK (all 3 orchestrators)
- Feature quality: OK (75.8% ready, matchup 100%)
- Signal: GREEN (192 picks, 6 high-edge, 34.4% pct_over)
- 14 games on Feb 11 — first real QUANT evaluation day

### Phase 6 Export Improvements (Deployed & Verified)
- **DNP games now visible** in last-10 data: `null` in sparkline arrays, `"DNP"` in result arrays
- `last_10_results` (vs line) now available for ALL players (was only `has_line` players)
- `last_10_vs_avg` (vs season average) handles DNP with `"DNP"` markers
- `is_dnp` field added to player detail `recent_form` entries
- Commit: `18d1183a`, auto-deployed via Cloud Build, export re-triggered and verified
- 356 of 481 players have at least one DNP visible in their last-10 data

### Discovery: Shadow Model Coverage Gap

| Date | Champion | Q43 | Q45 | Other Shadows |
|------|----------|-----|-----|---------------|
| Feb 8 | 110 | **0** | **0** | 54 each |
| Feb 9 | 220 | **0** | **0** | 59 each |
| Feb 10 | 20 | **2** | **2** | 18-20 each |
| Feb 11 | 196 | 196 | 196 | 196 each |

**Root cause:** Session 192 quality gate bug — gate was hardcoded to champion `system_id`, blocking shadow models. Fixed and deployed Feb 11. Verified working (196 predictions each on Feb 11).

**Why it wasn't caught:** No validation skill compares prediction counts across models. Total count looked fine because champion was producing normally.

---

## Your Job — Three Work Items

### Work Item 1: Backfill QUANT Predictions for Feb 8-10

**Feature store data exists** for all three dates:

| Date | Feature Store Rows | Quality Ready | Games |
|------|-------------------|---------------|-------|
| Feb 8 | 145 | 110 | 4 |
| Feb 9 | 341 | 162 | 10 |
| Feb 10 | 137 | 59 | 4 |

Q43/Q45 have no existing predictions for Feb 8-9 (and only 2 each on Feb 10), so no superseding needed.

**Approach:** Use `/start` with `BACKFILL` mode. Quality gate skips models that already have predictions (champion), generates new ones for models that don't (Q43/Q45).

```bash
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)

# Backfill each date — wait for batch completion between dates
for DATE in 2026-02-08 2026-02-09 2026-02-10; do
  echo "=== Backfilling $DATE ==="
  curl -X POST "${COORDINATOR_URL}/start" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
      \"game_date\": \"$DATE\",
      \"prediction_run_mode\": \"BACKFILL\",
      \"skip_completeness_check\": true
    }"
  echo ""
  # Check status before moving to next date
  echo "Waiting for batch..."
  sleep 60
  curl -s "${COORDINATOR_URL}/status" -H "Authorization: Bearer ${TOKEN}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Status: {d.get(\"status\", \"unknown\")}')" 2>/dev/null
  echo ""
done
```

**Verify after backfill:**
```sql
SELECT system_id, game_date, COUNT(*) as predictions,
  COUNTIF(is_active = TRUE) as active,
  COUNTIF(is_actionable = TRUE) as actionable
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_q4%'
  AND game_date BETWEEN '2026-02-08' AND '2026-02-10'
GROUP BY 1, 2 ORDER BY 2, 1
```

**Expected:** Q43 and Q45 should each have counts close to the champion (roughly 110, 220, 20 for the respective dates).

**If batch stalls:** Check `/status`, then `/reset` and retry. See Common Issues in CLAUDE.md.

**Important:** Don't use `/regenerate-with-supersede` — that supersedes existing champion predictions unnecessarily.

---

### Work Item 2: Add Cross-Model Coverage Parity Check

This is the core monitoring gap. Neither `reconcile-yesterday` nor `validate-daily` compares prediction counts across models.

**The query to add:**
```sql
-- Cross-model prediction coverage parity for @target_date
WITH model_counts AS (
  SELECT system_id, COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = @target_date
    AND system_id LIKE 'catboost_v9%'
    AND is_active = TRUE
  GROUP BY 1
),
champion AS (
  SELECT predictions as champion_count
  FROM model_counts
  WHERE system_id = 'catboost_v9'
)
SELECT
  m.system_id,
  m.predictions,
  c.champion_count,
  ROUND(100.0 * m.predictions / NULLIF(c.champion_count, 0), 1) as pct_of_champion,
  CASE
    WHEN m.predictions = 0 THEN 'CRITICAL — Zero predictions'
    WHEN 100.0 * m.predictions / NULLIF(c.champion_count, 0) < 50 THEN 'CRITICAL — Below 50%'
    WHEN 100.0 * m.predictions / NULLIF(c.champion_count, 0) < 80 THEN 'WARNING — Below 80%'
    ELSE 'OK'
  END as status
FROM model_counts m
CROSS JOIN champion c
ORDER BY pct_of_champion ASC
```

**Where to add (do BOTH):**

#### A. Update `reconcile-yesterday` skill
- Location: `.claude/skills/reconcile-yesterday/SKILL.md`
- Add as new **Phase 9: Cross-Model Prediction Coverage**
- Runs next-day, detects gaps for yesterday's games
- When gap found: output exact backfill curl command
- This is the primary detection layer

#### B. Update `validate-daily` skill
- Location: `.claude/skills/validate-daily/SKILL.md`
- Add near the existing "Phase 0.45: Edge Filter Verification" section (around prediction checks)
- Runs pre-game, catches same-day gaps before they compound
- This is the early warning layer

**Output format when gap detected:**
```
### Cross-Model Coverage Check — 2026-02-08

| Model | Predictions | vs Champion | Status |
|-------|-------------|-------------|--------|
| catboost_v9 (champion) | 110 | — | OK |
| catboost_v9_train1102_0108 | 54 | 49.1% | CRITICAL |
| catboost_v9_q43_train1102_0131 | 0 | 0.0% | CRITICAL |
| catboost_v9_q45_train1102_0131 | 0 | 0.0% | CRITICAL |

CRITICAL: 2 model(s) have zero predictions

Backfill command:
  COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
  TOKEN=$(gcloud auth print-identity-token)
  curl -X POST "${COORDINATOR_URL}/start" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"game_date":"2026-02-08","prediction_run_mode":"BACKFILL","skip_completeness_check":true}'
```

---

### Work Item 3: Consider a Standalone Validation Skill

If the cross-model check feels too heavy for reconcile-yesterday, consider a new skill:

**`/validate-shadow-models`** — dedicated skill that:
1. Compares prediction counts across all enabled shadow models vs champion
2. Checks the last N days (default 3) for coverage gaps
3. Validates QUANT-specific metrics (UNDER bias present, edge distribution)
4. Outputs backfill commands for any gaps found
5. Can optionally auto-trigger backfills with `--fix` flag

This could also be useful as a pre-promotion check when considering promoting Q43 to champion.

---

## Architecture Context

### How Shadow Predictions Work
1. **Coordinator** dispatches eligible players to Pub/Sub (one message per player)
2. **Worker** receives message, runs ALL enabled models from `MONTHLY_MODELS` dict in `predictions/worker/prediction_systems/catboost_monthly.py`
3. Each model's `system_id` is preserved through the entire flow
4. Quality gate (Session 192 fix) runs **per-system** — checks each model independently

### Why `/start` BACKFILL Works Without Superseding
- Coordinator checks what already exists per `system_id`
- Champion already has predictions → quality gate skips it (not regenerated)
- Q43/Q45 have no predictions → quality gate allows them → generated fresh
- No risk to existing champion data

### QUANT Model Behavior (Verified Feb 11)
- Q43 (alpha=0.43) predicts ~2 points lower than champion (avg 11.6 vs 13.6)
- Q45 (alpha=0.45) predicts ~1.6 points lower (avg 12.0 vs 13.6)
- This is designed behavior — creates UNDER bias for edge
- Fewer actionable picks (14 and 9 vs champion's 33) but theoretically higher hit rate

### Enabled Shadow Models
```
catboost_v9                        — CHAMPION (production)
catboost_v9_train1102_0108         — Shadow (Jan 8 cutoff, defaults)
catboost_v9_train1102_0131_tuned   — Shadow (Jan 31, tuned hyperparams)
catboost_v9_q43_train1102_0131     — Shadow (quantile alpha=0.43)
catboost_v9_q45_train1102_0131     — Shadow (quantile alpha=0.45)
```

### Key Files
| File | Purpose |
|------|---------|
| `predictions/coordinator/coordinator.py` | `/start`, `/status`, `/reset`, `/regenerate-with-supersede` |
| `predictions/coordinator/quality_gate.py` | Per-system quality gate (Session 192 fix) |
| `predictions/worker/prediction_systems/catboost_monthly.py` | `MONTHLY_MODELS` config |
| `.claude/skills/reconcile-yesterday/SKILL.md` | Reconciliation skill to update |
| `.claude/skills/validate-daily/SKILL.md` | Daily validation skill to update |

### Key URLs
```bash
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
```

---

## Verification Queries

### After backfill — confirm QUANT predictions exist
```sql
SELECT system_id, game_date,
  COUNT(*) as total,
  COUNTIF(is_active = TRUE) as active,
  COUNTIF(is_actionable = TRUE) as actionable
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_q4%'
  AND game_date BETWEEN '2026-02-08' AND '2026-02-10'
GROUP BY 1, 2 ORDER BY 2, 1
```

### After Feb 11 games grade — evaluate QUANT performance
```sql
SELECT system_id,
  COUNT(*) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL) as edge3_total,
  ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) /
    NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct IS NOT NULL), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v9_q43_train1102_0131', 'catboost_v9_q45_train1102_0131')
  AND game_date >= '2026-02-08'
  AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
```

### Daily cross-model parity (add to morning checks)
```sql
-- Returns only models with <80% coverage vs the max
SELECT system_id,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNT(*) / MAX(COUNT(*)) OVER(), 1) as pct_of_max
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() - 1
  AND system_id LIKE 'catboost_v9%'
  AND is_active = TRUE
GROUP BY 1
HAVING COUNT(*) < 0.8 * (SELECT MAX(c) FROM (SELECT COUNT(*) as c FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE() - 1 AND system_id LIKE 'catboost_v9%' AND is_active = TRUE GROUP BY system_id))
ORDER BY predictions ASC
```

---

## What NOT to Do

- **Don't use `/regenerate-with-supersede`** for Feb 8-10 — supersedes existing champion predictions
- **Don't disable shadow models** before backfill — all models run, quality gate handles dedup
- **Don't hardcode model names** in validation — use `LIKE 'catboost_v9_%'` to auto-discover
- **Don't wait for grading** before backfilling — more data = better QUANT evaluation

---

## Priority Order

1. **Backfill Feb 8-10** (~15 min) — get the QUANT predictions generated
2. **Update `reconcile-yesterday`** (~30 min) — add Phase 9 cross-model coverage
3. **Update `validate-daily`** (~15 min) — add same check to pre-game validation
4. **Verify Feb 11 grading** (check morning after) — first 196-prediction evaluation
5. **Run `/compare-models`** once 50+ edge 3+ graded predictions exist

---

## Champion Model Status

Continuing decay: 41.7% (Feb 8), 45.7% (Feb 9), 25.0% (Feb 10). 33+ days stale, below breakeven. QUANT evaluation is the #1 priority — if Q43 validates, it's the replacement path.

---

## Session 209 Commits

- `18d1183a` — feat: Show DNP games as visible gaps in last-10 data and expose all metrics to all players

---

**Session 209 Complete**
