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

```bash
bq query --use_legacy_sql=false "
-- Check: Did boxscores arrive for all games?
WITH scheduled AS (
  SELECT game_id, away_team_tricode, home_team_tricode
  FROM nba_reference.nba_schedule
  WHERE game_date = '${RECON_DATE}' AND game_status = 3
),
boxscored AS (
  SELECT DISTINCT game_id
  FROM nba_analytics.player_game_summary
  WHERE game_date = '${RECON_DATE}'
)
SELECT
  COUNT(DISTINCT s.game_id) as games_scheduled,
  COUNT(DISTINCT b.game_id) as games_with_boxscores,
  COUNT(DISTINCT s.game_id) - COUNT(DISTINCT b.game_id) as games_missing_boxscores,
  ARRAY_AGG(
    CASE WHEN b.game_id IS NULL
    THEN CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode)
    END IGNORE NULLS
  ) as missing_games
FROM scheduled s
LEFT JOIN boxscored b ON s.game_id = b.game_id
"
```

**Expected**: 0 games missing boxscores.
**If missing**: Phase 2/3 pipeline failed for those games. Check scraper logs.

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
