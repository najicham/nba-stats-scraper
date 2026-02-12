---
name: reconcile-yesterday
description: Check yesterday's pipeline for gaps, compare who played vs who was predicted, and trigger targeted backfills
---

# Yesterday's Pipeline Reconciliation

You are performing next-day reconciliation for the NBA prediction pipeline. This skill checks if yesterday's data made it through all 6 phases and identifies gaps that need backfill.

## Your Mission

After games finish, boxscores arrive overnight. This skill checks:
1. Did all games get boxscores?
2. Were all players cached correctly?
3. Did the feature store cover all players?
4. Were predictions generated for all eligible players?
5. Were there any cache misses (fallback used)?

Then suggest or trigger targeted backfills for any gaps found.

## When to Use

- **Morning after game day** - Run as part of daily check to catch overnight pipeline gaps
- **After validate-daily** - As a follow-up to dig into data completeness
- **Before grading** - Ensure predictions exist for grading

## Target Date Logic

By default, reconcile **yesterday's date** (the most recent game day). The user can override with a specific date.

---

## Phase 1: Determine Target Date

```bash
# Default to yesterday, or use user-provided date
RECON_DATE=$(date -d "yesterday" +%Y-%m-%d)
echo "Reconciling: $RECON_DATE"

# Check if games were scheduled
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as games_scheduled,
  COUNTIF(game_status = 3) as games_final,
  COUNTIF(game_status != 3) as games_not_final
FROM nba_reference.nba_schedule
WHERE game_date = '${RECON_DATE}'
GROUP BY 1
"
```

**If no games scheduled**: Report "No games on $RECON_DATE" and exit.
**If games not final**: Warning - boxscores may be incomplete.

---

## Phase 2: Boxscore Arrival Check

**NOTE**: Schedule uses numeric game_id (`0022500775`), analytics uses date format (`20260211_MIL_ORL`). Join on team pairs, not game_id (Session 216 fix).

```bash
bq query --use_legacy_sql=false "
-- Check: Did boxscores arrive for all games?
-- Uses team pair matching (not game_id which has format mismatch)
WITH scheduled AS (
  SELECT game_id, away_team_tricode, home_team_tricode
  FROM nba_reference.nba_schedule
  WHERE game_date = '${RECON_DATE}' AND game_status = 3
),
boxscored AS (
  SELECT DISTINCT
    SPLIT(game_id, '_')[SAFE_OFFSET(1)] as away_team,
    SPLIT(game_id, '_')[SAFE_OFFSET(2)] as home_team
  FROM nba_analytics.player_game_summary
  WHERE game_date = '${RECON_DATE}'
)
SELECT
  COUNT(DISTINCT s.game_id) as games_scheduled,
  COUNTIF(b.away_team IS NOT NULL) as games_with_analytics,
  COUNTIF(b.away_team IS NULL) as games_missing_analytics,
  ARRAY_AGG(
    CASE WHEN b.away_team IS NULL
    THEN CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode)
    END IGNORE NULLS
  ) as missing_games
FROM scheduled s
LEFT JOIN boxscored b
  ON s.away_team_tricode = b.away_team
  AND s.home_team_tricode = b.home_team
"
```

**Expected**: 0 games missing analytics.
**If missing**: Phase 2/3 pipeline failed for those games. Check if boxscore fallback was available (Phase 0.477 in validate-daily).

---

## Phase 3: Player Coverage - Who Played vs Who Was Predicted

```bash
bq query --use_legacy_sql=false "
-- Core reconciliation: played vs cached vs featured vs predicted
WITH played AS (
  SELECT DISTINCT player_lookup, game_id
  FROM nba_analytics.player_game_summary
  WHERE game_date = '${RECON_DATE}' AND is_dnp = FALSE
),
cached AS (
  SELECT DISTINCT player_lookup
  FROM nba_precompute.player_daily_cache
  WHERE cache_date = '${RECON_DATE}'
),
featured AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '${RECON_DATE}'
),
predicted AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '${RECON_DATE}' AND is_active = TRUE
)
SELECT
  (SELECT COUNT(*) FROM played) as players_played,
  (SELECT COUNT(*) FROM cached) as players_cached,
  (SELECT COUNT(*) FROM featured) as players_featured,
  (SELECT COUNT(*) FROM predicted) as players_predicted,
  -- Gap analysis
  (SELECT COUNT(*) FROM played p LEFT JOIN cached c ON p.player_lookup = c.player_lookup WHERE c.player_lookup IS NULL) as played_not_cached,
  (SELECT COUNT(*) FROM played p LEFT JOIN featured f ON p.player_lookup = f.player_lookup WHERE f.player_lookup IS NULL) as played_not_featured,
  (SELECT COUNT(*) FROM played p LEFT JOIN predicted pr ON p.player_lookup = pr.player_lookup WHERE pr.player_lookup IS NULL) as played_not_predicted,
  -- Reverse: predicted but didn't play (DNP, scratched)
  (SELECT COUNT(*) FROM predicted pr LEFT JOIN played p ON pr.player_lookup = p.player_lookup WHERE p.player_lookup IS NULL) as predicted_not_played
"
```

**Expected Coverage**:
- `played_not_cached`: 0-5 (some late additions/trades)
- `played_not_featured`: 0-10 (similar + data gaps)
- `played_not_predicted`: 15-40 (bench/low-minutes players without prop lines - normal)
- `predicted_not_played`: 0-5 (DNP/scratches after prediction - normal)

---

## Phase 4: Cache Miss Rate

```bash
bq query --use_legacy_sql=false "
-- Session 147: Cache miss tracking
SELECT
  game_date,
  COUNTIF(cache_miss_fallback_used) as cache_misses,
  COUNT(*) as total,
  ROUND(COUNTIF(cache_miss_fallback_used) / COUNT(*) * 100, 1) as miss_rate_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '${RECON_DATE}'
GROUP BY 1
"
```

**Expected**: 0% for daily predictions, 5-15% for backfill dates.
**If >0% for daily**: Check `upcoming_player_game_context` had correct player list.

---

## Phase 5: Feature Quality Summary

```bash
bq query --use_legacy_sql=false "
-- Feature quality for the reconciled date
SELECT
  COUNTIF(is_quality_ready) as quality_ready,
  COUNT(*) as total,
  ROUND(COUNTIF(is_quality_ready) / COUNT(*) * 100, 1) as ready_pct,
  ROUND(AVG(default_feature_count), 1) as avg_defaults,
  COUNTIF(default_feature_count = 0) as zero_defaults,
  ROUND(COUNTIF(default_feature_count = 0) / COUNT(*) * 100, 1) as zero_default_pct,
  COUNTIF(quality_alert_level = 'red') as red_alerts
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '${RECON_DATE}'
"
```

---

## Phase 6: Prediction Accuracy Readiness

```bash
bq query --use_legacy_sql=false "
-- Check if predictions are ready for grading
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(is_active) as active_predictions,
  COUNTIF(predicted_points IS NOT NULL) as has_prediction,
  COUNTIF(current_points_line IS NOT NULL) as has_line,
  COUNTIF(is_actionable) as actionable,
  COUNT(DISTINCT game_id) as games_covered
FROM nba_predictions.player_prop_predictions
WHERE game_date = '${RECON_DATE}'
"
```

**Key metric**: `has_line` vs `active_predictions`. If `has_line` is much lower than `active_predictions`, enrichment may have failed.

---

## Phase 6.5: Enrichment Completeness (Session 217)

**Purpose**: Verify predictions were enriched with actual prop lines after props were scraped. Enrichment runs at 18:40 UTC daily.

```bash
bq query --use_legacy_sql=false "
-- Check enrichment: how many active predictions got prop lines?
SELECT
  COUNTIF(is_active) as active_predictions,
  COUNTIF(is_active AND current_points_line IS NOT NULL) as enriched,
  COUNTIF(is_active AND current_points_line IS NULL) as not_enriched,
  ROUND(COUNTIF(is_active AND current_points_line IS NOT NULL) * 100.0 /
    NULLIF(COUNTIF(is_active), 0), 1) as enrichment_pct,
  COUNTIF(line_source = 'ACTUAL_PROP') as actual_prop,
  COUNTIF(line_source = 'ODDS_API') as odds_api,
  COUNTIF(line_source = 'NO_PROP_LINE') as no_prop
FROM nba_predictions.player_prop_predictions
WHERE game_date = '${RECON_DATE}'
"
```

**Expected**: `enrichment_pct >= 60%` on a normal game day.
**If < 40%**: Enrichment pipeline likely failed. Check `enrichment-trigger` Cloud Function logs and scheduler.
**If 0%**: CRITICAL — enrichment has not run at all. Manual trigger:
```
curl -s "https://enrichment-trigger-f7p3g7f6ya-wl.a.run.app/?date=${RECON_DATE}" | python3 -m json.tool
```

---

## Phase 7: Gap Identification - Who Was Missed?

**Only run this if Phase 3 shows gaps > expected thresholds.**

```bash
bq query --use_legacy_sql=false "
-- Identify specific players who played but weren't predicted
WITH played AS (
  SELECT DISTINCT p.player_lookup,
    p.points as actual_points,
    s.away_team_tricode || ' @ ' || s.home_team_tricode as matchup
  FROM nba_analytics.player_game_summary p
  JOIN nba_reference.nba_schedule s ON p.game_id = s.game_id
  WHERE p.game_date = '${RECON_DATE}' AND p.is_dnp = FALSE
),
predicted AS (
  SELECT DISTINCT player_lookup
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '${RECON_DATE}' AND is_active = TRUE
)
SELECT
  p.player_lookup,
  p.actual_points,
  p.matchup,
  CASE
    WHEN p.actual_points >= 20 THEN 'HIGH_IMPACT'
    WHEN p.actual_points >= 10 THEN 'MEDIUM'
    ELSE 'LOW'
  END as impact
FROM played p
LEFT JOIN predicted pr ON p.player_lookup = pr.player_lookup
WHERE pr.player_lookup IS NULL
ORDER BY p.actual_points DESC
LIMIT 20
"
```

**Focus on HIGH_IMPACT**: These are meaningful players we missed. LOW impact (< 10 points) are typically bench players without prop lines -- expected and acceptable.

---

## Phase 8: Remediation Recommendations

Based on findings, recommend specific actions:

### If boxscores missing:
```
Remediation: Re-run Phase 2+3 for missing games
  curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"analysis_date": "${RECON_DATE}", "processors": ["PlayerGameSummaryProcessor"]}'
```

### If cache gaps found:
```
Remediation: Regenerate cache for date
  python bin/regenerate_cache_bypass_bootstrap.py ${RECON_DATE}
```

### If feature store incomplete:
```
Remediation: Re-run ML Feature Store for date
  curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "${RECON_DATE}", "backfill_mode": true}'
```

### If predictions missing for key players:
```
Remediation: Backfill predictions for date
  curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"game_date": "${RECON_DATE}", "prediction_run_mode": "BACKFILL"}'
```

---

## Phase 9: Cross-Model Prediction Coverage (Session 210)

**IMPORTANT**: Verify all enabled shadow models produced predictions at the same rate as the champion. Session 209 discovered Q43/Q45 had **zero predictions** for 2 days with no alert.

**Why this matters**: Shadow models share the same pipeline but quality gate bugs or config errors can silently block them. Total prediction count looks fine because the champion is producing normally — only a cross-model comparison catches this.

```bash
bq query --use_legacy_sql=false "
-- Cross-model prediction coverage parity for ${RECON_DATE}
WITH model_counts AS (
  SELECT system_id, COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '${RECON_DATE}'
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
    WHEN m.predictions = 0 THEN 'CRITICAL - Zero predictions'
    WHEN 100.0 * m.predictions / NULLIF(c.champion_count, 0) < 50 THEN 'CRITICAL - Below 50%'
    WHEN 100.0 * m.predictions / NULLIF(c.champion_count, 0) < 80 THEN 'WARNING - Below 80%'
    ELSE 'OK'
  END as status
FROM model_counts m
CROSS JOIN champion c
ORDER BY pct_of_champion ASC
"
```

**Also check for models that are completely absent** (0 rows = not even in model_counts):

```bash
bq query --use_legacy_sql=false "
-- Find enabled models with NO predictions at all for ${RECON_DATE}
-- Uses LIKE 'catboost_v9_%' to auto-discover shadow models from recent days
WITH known_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB('${RECON_DATE}', INTERVAL 7 DAY)
    AND system_id LIKE 'catboost_v9_%'
),
recon_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '${RECON_DATE}'
    AND system_id LIKE 'catboost_v9_%'
)
SELECT k.system_id as missing_model, 'CRITICAL - No predictions at all' as status
FROM known_models k
LEFT JOIN recon_models r ON k.system_id = r.system_id
WHERE r.system_id IS NULL
"
```

**Expected**: All shadow models within 80-100% of champion count. Small variations are normal (quality gate may filter differently per model).

**If CRITICAL or WARNING found**:

Present a table like this:
```
### Cross-Model Coverage Check — ${RECON_DATE}

| Model | Predictions | vs Champion | Status |
|-------|-------------|-------------|--------|
| catboost_v9 (champion) | 110 | — | OK |
| catboost_v9_train1102_0108 | 54 | 49.1% | CRITICAL |
| catboost_v9_q43_train1102_0131 | 0 | 0.0% | CRITICAL |

CRITICAL: N model(s) have zero or low predictions
```

Then provide the backfill command:
```
Backfill command (generates predictions for models that are missing, does NOT supersede existing):
  COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
  TOKEN=$(gcloud auth print-identity-token)
  curl -X POST "${COORDINATOR_URL}/start" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"game_date":"${RECON_DATE}","prediction_run_mode":"BACKFILL","skip_completeness_check":true}'
```

**Do NOT use `/regenerate-with-supersede`** — that would supersede existing champion predictions unnecessarily.

---

## Output Format

Present results as a summary table:

```
Pipeline Reconciliation: ${RECON_DATE}
==========================================
Games:        X scheduled, X final
Boxscores:    [OK/GAP] X/X games
Cache:        [OK/GAP] X players cached, X miss rate
Features:     [OK/GAP] X featured, X% quality-ready
Predictions:  [OK/GAP] X active, X actionable
Enrichment:   [OK/GAP] X% enriched, X actual_prop, X odds_api
Cross-Model:  [OK/GAP] X models checked, X below 80%
==========================================
Gaps Found:   X players played but not predicted
  - HIGH_IMPACT: X (>20 pts scored)
  - MEDIUM: X (10-20 pts scored)
  - LOW: X (<10 pts scored)
==========================================
Action Required: [YES/NO]
  [List specific remediation steps if YES]
```

**If all phases show OK and gaps are within expected ranges**: Report "Pipeline healthy, no backfill needed."

**If gaps found**: Present remediation steps in dependency order (Phase 2 -> 3 -> 4 -> 5) and ask user before executing any backfills.
