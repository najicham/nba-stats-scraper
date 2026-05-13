# A2 Post-Deploy Monitor — MAX_EDGE 1.5 → 1.25

**Deployed:** Session 2, 2026-05-13. Algorithm version: `mlb_v9_max_edge_125`.
**Verification date:** 2026-05-20 (7 days post-deploy). Re-run weekly thereafter.

**Stop condition (from roadmap):** OVER HR Wilson lower bound (95%) must NOT regress more than 2pp vs the prior `mlb_v8_s456_v3final_away_5picks` baseline. If it does, revert (set env `MLB_MAX_EDGE=1.5` on `mlb-prediction-worker` and bump algorithm_version back).

## Pre-deploy baseline

Captured from 2026 OVER best bets (March–May 13, 2026), `mlb_v8_s456_v3final_away_5picks`:

| Bucket | N | Hits | HR | Wilson LB |
|---|---|---|---|---|
| a. <0.5 | 24 | 13 | 54.2% | 35.1% |
| b. 0.5-0.99 | 26 | 17 | 65.4% | 46.2% |
| c. 1.0-1.24 | 6 | 3 | 50.0% | 18.8% |
| d. 1.25-1.49 (blocked post-A2) | 7 | 3 | 42.9% | 15.8% |
| e. 1.5+ | 3 | 2 | 66.7% | 20.8% |
| **TOTAL** | **66** | **38** | **57.6%** | **45.6%** |

**Stop threshold:** Wilson LB drops below **43.6%** (45.6% − 2.0pp) → revert.

## Weekly monitor query

```sql
-- A2 monitor — OVER HR + Wilson LB by algorithm_version, partitioned by edge bucket.
-- Stop condition: row for mlb_v9 with Wilson LB < (baseline_wilson_lb - 2.0) for total bucket → revert.
WITH graded AS (
  SELECT
    bb.algorithm_version,
    bb.edge,
    pa.prediction_correct
  FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` bb
  LEFT JOIN `nba-props-platform.mlb_predictions.prediction_accuracy` pa
    USING (pitcher_lookup, game_date, system_id, recommendation, line_value)
  WHERE bb.recommendation = 'OVER'
    AND bb.game_date >= '2026-03-01'
    AND pa.prediction_correct IS NOT NULL
),
bucketed AS (
  SELECT
    algorithm_version,
    CASE
      WHEN edge < 0.5 THEN 'a. <0.5'
      WHEN edge < 1.0 THEN 'b. 0.5-0.99'
      WHEN edge < 1.25 THEN 'c. 1.0-1.24'
      WHEN edge < 1.5 THEN 'd. 1.25-1.49 (post-A2: should be empty)'
      ELSE 'e. 1.5+ (anomaly)'
    END AS edge_bucket,
    prediction_correct
  FROM graded
),
agg AS (
  SELECT
    algorithm_version,
    edge_bucket,
    COUNT(*) AS n,
    COUNTIF(prediction_correct) AS hits
  FROM bucketed
  GROUP BY algorithm_version, edge_bucket

  UNION ALL

  SELECT
    algorithm_version,
    'TOTAL' AS edge_bucket,
    COUNT(*) AS n,
    COUNTIF(prediction_correct) AS hits
  FROM bucketed
  GROUP BY algorithm_version
)
SELECT
  algorithm_version,
  edge_bucket,
  n,
  hits,
  ROUND(100.0 * hits / NULLIF(n, 0), 1) AS hr_pct,
  -- Wilson 95% lower bound on proportion (z=1.96)
  ROUND(100.0 * SAFE_DIVIDE(
    (hits + 1.96 * 1.96 / 2)
    - 1.96 * SQRT(SAFE_DIVIDE(hits * (n - hits), n) + (1.96 * 1.96) / 4),
    n + 1.96 * 1.96
  ), 1) AS wilson_lb_pct
FROM agg
WHERE n > 0
ORDER BY algorithm_version, edge_bucket;
```

## Expected results 7 days out (2026-05-20)

- `mlb_v9_max_edge_125` row in bucket `d. 1.25-1.49` should be **absent or near-zero** (cap blocks edge > 1.25). One or two picks at edge ∈ (1.25, 1.50) slipping through is a bug — check `MLB_MAX_EDGE` env override on `mlb-prediction-worker`.
- `mlb_v9_max_edge_125` TOTAL Wilson LB should be **≥ 43.6%** (baseline 45.6% − 2pp tolerance). Below that → revert.
- Volume drop expected: ~10% of OVER best bets (8 picks/season worth at current pace).

## Revert procedure

If stop condition trips:

```bash
# 1. Set env override to restore 1.5 cap without code change
gcloud run services update mlb-prediction-worker \
  --update-env-vars="MLB_MAX_EDGE=1.5" \
  --region=us-west2 --project=nba-props-platform

# 2. Bump algorithm_version back in code (so provenance is clear)
#    Edit ml/signals/mlb/best_bets_exporter.py:631 → 'mlb_v9_revert_max_edge_15'
#    Commit + push (auto-deploys).

# 3. Verify next /best-bets fire writes new algorithm_version
bq query --use_legacy_sql=false \
  "SELECT DISTINCT algorithm_version FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` \
   WHERE game_date = CURRENT_DATE()"
```

## Saved-query reference

This query is the source-of-truth template. To save as a BQ saved query in the UI: paste the SQL block above, name it `mlb_a2_monitor_max_edge_125`, set the project to `nba-props-platform`.
