# Session 390 Prompt — Fix 4 Issues from Daily Validation

## Context

Session 389 ran `/validate-daily` on 2026-03-02 (pre-game check, 4-game slate). Found 4 actionable issues. All are code/config bugs — no architectural changes needed.

## Issue 1: Phase 3 Timing Race — Boxscore Data Arrives After Trigger (P2)

### Problem

The `evening-analytics-1am-et` Cloud Scheduler trigger fires at exactly 06:00 UTC. The boxscore scraper (`nbac_player_boxscores`) finished writing data at 06:07 UTC — **7 minutes after** the trigger. The `player_game_summary` processor found 0 records and failed with `ValueError: No data extracted`.

The next trigger at 6 AM ET (11:00 UTC) catches it, so it self-heals. But this creates a 5-hour gap in analytics data.

### Evidence

```
# Boxscore data arrival:
game_id              | first_written
20260302_BOS_MIL     | 2026-03-03 06:07:39
20260302_DEN_UTA     | 2026-03-03 06:07:39
20260302_HOU_WAS     | 2026-03-03 06:07:39
20260302_LAC_GSW     | 2026-03-03 06:07:39

# Phase 3 processor ran at 03:00 UTC and 06:00 UTC — both before data arrived
# Log: "No source data available: both nbac_gamebook_player_stats (0 records)
#        and nbac_player_boxscores (0 Final games) have no data for 2026-03-02"
```

### Fix Options (pick one)

**Option A (simplest):** Shift `evening-analytics-1am-et` scheduler from `0 1 * * *` ET to `15 1 * * *` ET (1:15 AM = 06:15 UTC). Gives 15-min buffer.

```bash
gcloud scheduler jobs update http evening-analytics-1am-et \
  --location=us-west2 --project=nba-props-platform \
  --schedule="15 1 * * *" \
  --time-zone="America/New_York"
```

**Option B (better):** Add a retry in `player_game_summary_processor.py` when no data found — wait 10 min and re-check before failing. The processor already has circuit breaker logic (`get_upstream_data_check_query` at line 589), but it doesn't retry within a single invocation.

**Option C (best, more work):** Make Phase 3 event-driven — trigger when Phase 2 writes boxscore data (Pub/Sub from `nba-phase2-raw-complete` topic). Phase 2→3 already has a direct Pub/Sub path (`nba-phase3-analytics-sub`), so verify the boxscore scraper publishes to `nba-phase2-raw-complete` after writing.

### Key Files

- Scheduler: `evening-analytics-1am-et` (Cloud Scheduler, us-west2)
- Processor: `data_processors/analytics/player_game_summary/player_game_summary_processor.py` (lines 530-587: source data check)
- Boxscore fallback: Line 553-570 — `USE_NBAC_BOXSCORES_FALLBACK = True` (line 99)

---

## Issue 2: `monthly-retrain-job` Missing `db-dtypes` Dependency (P3)

### Problem

The `monthly-retrain` Cloud Run service crashes with:
```
ModuleNotFoundError: No module named 'db_dtypes'
```

`client.query(query).to_dataframe()` requires `db-dtypes` for BigQuery → pandas conversion. The package is missing from the service's requirements.

### Fix

Find the requirements file for the `monthly-retrain` service and add `db-dtypes`:

```bash
# Find the service's source
find . -path "*/monthly*retrain*" -name "requirements*" -o -path "*/monthly*retrain*" -name "Dockerfile" 2>/dev/null
```

Add `db-dtypes>=1.1.0` to the requirements file and redeploy.

### Verification

```bash
gcloud scheduler jobs run monthly-retrain-job --location=us-west2 --project=nba-props-platform
# Then check logs:
gcloud logging read 'resource.labels.service_name="monthly-retrain"' --limit=10 --freshness=1h --project=nba-props-platform
```

---

## Issue 3: `self-heal-predictions` Missing Partition Filter + Timeout (P3)

### Problem

Two bugs in the self-heal-predictions Cloud Run service:

**Bug A:** Query against `nba_raw.nbac_schedule` without partition filter → 400 error:
```
Cannot query over table 'nba-props-platform.nba_raw.nbac_schedule' without a filter
over column(s) 'game_date' that can be used for partition elimination
```

**Bug B:** After the query fails, it tries to call Phase 4 service which times out → DEADLINE_EXCEEDED (900s limit).

### Evidence

From logs at 2026-03-02T17:45:07Z:
```
Error checking nbac_schedule: 400 Cannot query over table
'nba-props-platform.nba_raw.nbac_schedule' without a filter over column(s)
'game_date' that can be used for partition elimination
```

Also: `Phase 2: bdl_player_boxscores has 0 records for 2026-03-01` — BDL is intentionally disabled, this is a false alarm in self-heal.

### Fix

Find the service source and fix:

```bash
find . -path "*/self-heal*" -name "main.py" -o -path "*/self-heal*" -name "*.py" 2>/dev/null
```

1. Add `WHERE game_date >= CURRENT_DATE() - 1` to the `nbac_schedule` query in `check_phase2_completeness()`
2. Skip `bdl_player_boxscores` check (BDL is intentionally disabled — see CLAUDE.md)
3. Consider increasing timeout or adding error handling for Phase 4 calls

### Verification

```bash
# After deploy, manually trigger:
gcloud scheduler jobs run self-heal-predictions --location=us-west2 --project=nba-props-platform
# Check status goes to code 0:
gcloud scheduler jobs describe self-heal-predictions --location=us-west2 --project=nba-props-platform --format="value(status.code)"
```

---

## Issue 4: Stale Predictions from Disabled Models on Mar 1 (P4, optional)

### Problem

7 disabled models produced 177 predictions each on Mar 1 because the worker cached the old registry at startup. This is already fixed — Mar 2 shows 0 predictions from these models after the worker was redeployed.

However, the Mar 1 orphan predictions are still in the database with `is_active=TRUE`, inflating grading gap metrics.

### Fix (optional cleanup)

```sql
-- Deactivate predictions from disabled models for Mar 1
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET is_active = FALSE, filter_reason = 'model_disabled_cleanup'
WHERE game_date = '2026-03-01'
  AND system_id IN (
    'catboost_v12_train1221_0208',
    'catboost_v12_train0104_0208',
    'catboost_v12_noveg_q5_train0115_0222',
    'catboost_v12_noveg_train1124_0119',
    'catboost_v12_vw015_train1201_1231',
    'xgb_v12_noveg_train1221_0208',
    'catboost_v12_noveg_train1215_0208'
  )
  AND is_active = TRUE
```

Or use the deactivation CLI: `python bin/deactivate_model.py MODEL_ID` for each.

---

## Priority Order

1. **Issue 1** (Phase 3 timing) — Most impactful, causes daily 5-hour analytics gap
2. **Issue 3** (self-heal partition) — Quick fix, improves pipeline resilience
3. **Issue 2** (monthly-retrain dep) — Quick fix, unblocks automated retraining
4. **Issue 4** (stale predictions) — Cosmetic cleanup, optional

## Items NOT to Do

- **Don't change the signal count thresholds** — 0 best bets on Mar 2 was legitimate (4-game slate)
- **Don't change model fleet** — the HEALTHY models (v12_q43, lgbm_noveg) have tiny N, wait for data
- **Don't deploy prediction-worker** — latest revision already correctly filters disabled models
- **Don't change FEATURE_COUNT or feature store** — Session 388 fixes are working

## Quick Reference

| Service | Issue | Severity |
|---------|-------|----------|
| `evening-analytics-1am-et` (scheduler) | 7-min too early for boxscores | P2 |
| `monthly-retrain` (Cloud Run) | Missing `db-dtypes` package | P3 |
| `self-heal-predictions` (Cloud Run) | Missing partition filter on nbac_schedule | P3 |
| `player_prop_predictions` (BQ table) | ~1,200 stale active preds from disabled models | P4 |
