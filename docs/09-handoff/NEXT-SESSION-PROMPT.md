# Session 142 Prompt - Validate Zero Tolerance & Historical Backfill

Copy-paste this into the next Claude Code session.

---

## Context

Session 141 implemented **zero tolerance for default features** -- the prediction system now refuses to predict for any player whose ML feature vector contains defaulted values (`default_feature_count > 0`). Default values are lies (e.g. `avg_points=10.0` for a 27 PPG player). We prefer nulls to know data wasn't available, even during bootstrap.

A backfill was also run to populate quality visibility fields for all 50,099 historical records across 292 game dates (2024-11-06 through 2026-02-06).

**Your primary job: Validate everything is working correctly and that historical data has 100% quality field coverage. Fix any gaps.**

## What Was Changed (Session 141)

### Code Changes (commits `4381dca1`, `23f6cfa7`)

1. **`data_processors/precompute/ml_feature_store/quality_scorer.py`**
   - `is_quality_ready` now requires `default_count == 0` (line ~408)
   - Alert level yellow threshold: `default_count > 0` (was `> 10`) (line ~368)

2. **`predictions/coordinator/quality_gate.py`**
   - New constant: `HARD_FLOOR_MAX_DEFAULTS = 0` (line ~53)
   - `default_feature_count` added to quality query SELECT + `_quality_details` dict
   - New Rule 2b: hard floor blocks `default_feature_count > HARD_FLOOR_MAX_DEFAULTS` for ALL modes (FIRST, RETRY, FINAL_RETRY, LAST_CALL, BACKFILL)
   - Reason string: `zero_tolerance_defaults_N`

3. **`predictions/worker/worker.py`**
   - Defense-in-depth: `is_actionable = False` when `default_feature_count > 0` (after line ~2124)
   - Filter reason: `has_default_features`
   - Writes `default_feature_count` to prediction record (line ~2258)

4. **`schemas/bigquery/predictions/01_player_prop_predictions.sql`**
   - Added `default_feature_count INT64` column (already applied to BigQuery)

5. **`tests/unit/prediction_tests/coordinator/test_quality_gate.py`**
   - New `TestZeroTolerance` class with 6 tests (0 defaults passes, 3 defaults blocked, BACKFILL blocked, LAST_CALL blocked, mixed batch)
   - All 38 tests pass

6. **`CLAUDE.md`** - Updated Core Principles ("Zero tolerance for defaults"), Quality section, Common Issues, Queries

### Deployments (all verified at `4381dca1`)
- `nba-phase4-precompute-processors` - deployed 2026-02-06 12:36 ET
- `prediction-coordinator` - deployed 2026-02-06 12:26 ET
- `prediction-worker` - deployed 2026-02-06 12:32 ET

### Historical Backfill (completed by background agent)
- **50,099 records** across **292 game dates**
- Date range: 2024-11-06 through 2026-02-06
- Zero failed dates
- All quality visibility fields populated (quality_alert_level, default_feature_count, is_quality_ready, matchup_quality_pct, quality_tier, etc.)

## Validation Tasks (DO ALL OF THESE)

### 1. Verify Zero Tolerance Is Enforced

```sql
-- MUST return 0 rows. If any rows exist, is_quality_ready logic is broken.
SELECT default_feature_count, is_quality_ready, COUNT(*) as cnt
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
  AND is_quality_ready = true
  AND default_feature_count > 0
GROUP BY 1, 2;
```

### 2. Validate Historical Backfill Completeness (CRITICAL)

Check that ALL historical records have quality fields populated -- zero NULLs:

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as total_records,
  COUNTIF(quality_alert_level IS NULL) as null_alert_level,
  COUNTIF(default_feature_count IS NULL) as null_default_count,
  COUNTIF(is_quality_ready IS NULL) as null_quality_ready,
  COUNTIF(feature_quality_score IS NULL) as null_quality_score,
  COUNTIF(matchup_quality_pct IS NULL) as null_matchup_pct,
  COUNTIF(quality_tier IS NULL) as null_quality_tier
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-11-01'
GROUP BY 1
ORDER BY 1;
```

**Expected:** All `null_*` columns should be 0 for every month. If any are non-zero, those records need re-backfilling. Report the exact months and counts.

### 3. Validate Per-Feature Quality Coverage (37 features)

Ensure all 37 per-feature quality AND source columns are populated:

```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as total,
  COUNTIF(feature_0_quality IS NULL) as null_f0_q,
  COUNTIF(feature_0_source IS NULL) as null_f0_s,
  COUNTIF(feature_5_quality IS NULL) as null_f5_q,
  COUNTIF(feature_8_quality IS NULL) as null_f8_q,
  COUNTIF(feature_13_quality IS NULL) as null_f13_q,
  COUNTIF(feature_14_quality IS NULL) as null_f14_q,
  COUNTIF(feature_25_quality IS NULL) as null_f25_q,
  COUNTIF(feature_28_quality IS NULL) as null_f28_q,
  COUNTIF(feature_36_quality IS NULL) as null_f36_q
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-11-01'
GROUP BY 1
ORDER BY 1;
```

### 4. Check Default Distribution (Today)

```sql
SELECT
  default_feature_count,
  COUNT(*) as player_count,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(is_quality_ready) as quality_ready_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY 1
ORDER BY 1;
```

### 5. Verify Prediction Coverage Impact

```sql
-- Recent predictions: expect ~75 actionable (down from ~180)
SELECT game_date, COUNT(*) as total_predictions,
       COUNTIF(is_actionable) as actionable,
       COUNTIF(filter_reason = 'has_default_features') as blocked_by_defaults,
       COUNTIF(filter_reason = 'not_quality_ready') as blocked_not_ready,
       COUNTIF(default_feature_count = 0) as clean_predictions,
       COUNTIF(default_feature_count > 0) as predictions_with_defaults
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3
  AND system_id = 'catboost_v9'
GROUP BY 1
ORDER BY 1 DESC;
```

### 6. Verify Quality Gate Logs

```bash
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"zero.tolerance"' --limit=20 --freshness=24h --project=nba-props-platform
```

### 7. Run All Tests

```bash
PYTHONPATH=. python -m pytest tests/unit/prediction_tests/coordinator/test_quality_gate.py tests/test_quality_system.py -v
```

### 8. Check Deployment Drift

```bash
./bin/check-deployment-drift.sh --verbose
```

## If Backfill Has Gaps

If validation queries show NULL quality fields for any dates:

1. Identify the specific dates with NULLs
2. Re-run the quality visibility backfill for those dates
3. The backfill approach used in Session 141: query feature_sources from ml_feature_store_v2, re-compute quality fields via QualityScorer, UPDATE back
4. See `docs/08-projects/current/zero-tolerance-defaults/00-PROJECT-OVERVIEW.md` for context

## Key Files

| File | Purpose |
|------|---------|
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Quality scoring + `is_quality_ready` + alert level logic |
| `predictions/coordinator/quality_gate.py` | Quality gate enforcement (Rules 1-5, Rule 2b = zero tolerance) |
| `predictions/worker/worker.py` | Defense-in-depth filter + audit trail |
| `predictions/worker/data_loaders.py` | Loads `default_feature_count` from feature store |
| `tests/unit/prediction_tests/coordinator/test_quality_gate.py` | Zero tolerance tests (TestZeroTolerance class) |
| `docs/08-projects/current/zero-tolerance-defaults/00-PROJECT-OVERVIEW.md` | Project overview |
| `docs/09-handoff/2026-02-06-SESSION-141-HANDOFF.md` | Session 141 handoff |

## Design Philosophy

**Defaults are never acceptable.** A default value like `avg_points=10.0` for a 27 PPG player is a lie that poisons the model. Nulls are honest -- "we don't have this data." Even during bootstrap periods, better to skip a player than predict with fabricated data.

**To increase coverage, fix the data pipeline** (ensure Phase 4 processors run for more players, improve vegas line coverage). Never relax the zero tolerance policy.

## Deployment Note

Session 141 hit repeated TLS handshake timeouts pushing Docker images to Artifact Registry from WSL2. Workaround: push image directly with `docker push`, then deploy with `gcloud run deploy --image`. Consider migrating to Cloud Build in a future session for faster deploys (~4-6 min vs 8-12 min) and eliminating push timeouts.
