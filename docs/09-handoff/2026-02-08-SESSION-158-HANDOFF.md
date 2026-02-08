# Session 158 Handoff — Quality Prevention + Schema Fix + Phase 6 Exports

**Date:** 2026-02-08
**Focus:** Training data quality prevention, schema mismatch fix, consolidated Phase 6 exports
**Status:** Committed + pushed. Schema fixed in BQ. Backfill from processor 3 still running.

## CRITICAL: Immediate Actions for Next Session

### 1. Verify Predictions Are Working Again

We discovered a **schema mismatch** that broke ALL prediction writes since Feb 8 03:36 UTC. The `player_prop_predictions` table was missing `vegas_line_source` and `required_default_count` columns. We added them and redeployed the worker. **Verify predictions are landing:**

```bash
python3 << 'PYEOF'
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
q = """
SELECT game_date, COUNT(*) as total, COUNTIF(is_actionable) as actionable
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-07'
GROUP BY 1 ORDER BY 1
"""
for r in client.query(q).result():
    print(f"  {r.game_date}: {r.total} total, {r.actionable} actionable")
PYEOF
```

If no predictions for Feb 8, trigger manually:
```bash
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
curl -X POST "$COORDINATOR_URL/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date":"2026-02-08","prediction_run_mode":"BACKFILL"}'
```

If coordinator says "already_running", the old stuck batch needs to expire or be cleaned up. Check Firestore for the batch lock.

### 2. Also trigger predictions for Feb 7 (missed entirely)

Yesterday (Feb 7) had 10 games and **zero predictions**. Backfill it:
```bash
curl -X POST "$COORDINATOR_URL/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date":"2026-02-07","prediction_run_mode":"BACKFILL"}'
```

### 3. Check Backfill (Processors 3-5) Status

A backfill running processors 3 (composite_factors), 4 (daily_cache), 5 (ml_feature_store) was started for the full current season (Nov 2 - Feb 7):

```bash
# Check if still running
ps -p 3453211 -o pid,etime --no-headers 2>/dev/null || echo "Finished"

# Check progress
grep -E "Processing game date|✓|✗|Running #" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/b9e9d67e-7be2-43ae-b51d-8f89c7a40db8/scratchpad/backfill_p3_5.log | tail -10

# After completion, check contamination
./bin/monitoring/check_training_data_quality.sh --recent
```

Note: Processors 1-2 (team_defense_zone, player_shot_zone) already completed for all 96 dates. The initial backfill only completed those because processor 2 had Firestore connectivity errors that set `FAILED=1`, causing the sequential phase to be skipped.

### 4. Schema Validation Prevention

**Root cause of the schema mismatch:** Code changes added `vegas_line_source` to worker output (Session 64) and `required_default_count` (Session 141), but the `ALTER TABLE ADD COLUMN` migrations were in SQL files that never got executed against the production table.

**How to prevent this:**
- Create a pre-deploy schema validation that checks every field the worker writes exists in the target BQ table
- Or: add a startup check to the worker that validates its output fields against the BQ schema
- Search for: `predictions/shared/batch_staging_writer.py` line 229 `_get_main_table_schema()` — this is where the schema is fetched. A validation step here could log warnings for missing fields.

**The pre-commit hook `validate_schema_fields.py` exists** but only validates schema SQL files, not runtime BQ table state. We need a deploy-time or startup-time check.

---

## What Was Done in Session 158

### Part A: Training Data Quality Prevention
1. **Post-write validation** in `ml_feature_store_processor.py` — logs quality summary after every write, Slack alert if >30% defaults
2. **Phase 4→5 quality gate** extended in `phase4_to_phase5/main.py` — warns if quality-ready <40%
3. **Three-tier contamination monitor** `bin/monitoring/check_training_data_quality.sh` (v2):
   - Tier 1: Required-feature defaults (blocks predictions)
   - Tier 2: Optional-feature defaults (vegas — expected)
   - Tier 3: Per-feature breakdown (pinpoints problems)
   - Threshold: exits 1 if required contamination >15%
   - `--recent` flag for last 14 days only
4. Updated `/validate-daily` (Phase 0.487) and `/spot-check-features` (Check #28)

### Part B: Phase 6 Export Redesign
5. **Consolidated per-day export** `picks/{date}.json` now includes:
   - `signal` at top level (favorable/neutral/challenging)
   - `record` per subset (season/month/week W-L)
   - Replaced old `stats` field (breaking change for frontend!)
6. **Season file exporter** `season_subset_picks_exporter.py` — full season in one JSON (~1MB):
   - `gs://nba-props-platform-api/v1/subsets/season.json`
   - Per-pick `actual` and `result` (hit/miss/push/null)
   - Dates newest-first within each subset tab
7. **Wired into orchestration** — `season-subsets` added to `TONIGHT_EXPORT_TYPES` in phase5→6

### Part C: Schema Fix (Discovered Mid-Session)
8. **Added missing columns** to `player_prop_predictions`:
   - `vegas_line_source STRING` (was in worker code since Session 64)
   - `required_default_count INT64` (was in worker code since Session 141)
9. **Redeployed prediction-worker** to pick up new schema

### Part D: Investigation Findings

**Why contamination appears high (40.79%) but actual required-feature impact is ~24%:**
- Vegas features (25-27) inflate `default_feature_count` but don't block predictions (optional)
- `required_default_count` properly excludes vegas
- The three-tier monitor now separates these clearly

**Why predictions were missing for Feb 7-8:**
- PredictionCoordinator getting stuck in `running` state → cleaned up after 4 hours
- Root cause: `PlayerDailyCacheProcessor` fails when Phase 3 hasn't completed yet (timing)
- This triggers cascade: DailyCache fails → CompositeFactors can't run → FeatureStore can't run → Coordinator can't run
- Deeper root cause: staging write error from schema mismatch (field `vegas_line_source` missing from BQ table)

**Phase 4 processor failure rates (last 2 days):**
| Processor | Success | Failed | Failure Rate |
|-----------|---------|--------|-------------|
| MLFeatureStoreProcessor | 15 | 18 | 55% |
| PlayerCompositeFactorsProcessor | 8 | 12 | 60% |
| PlayerDailyCacheProcessor | 5 | 9 | 64% |
| PlayerShotZoneAnalysisProcessor | 5 | 5 | 50% |
| TeamDefenseZoneAnalysisProcessor | 7 | 5 | 42% |

Many "failures" are `stale_running_cleanup` (stuck 4+ hours) or `DependencyError` (upstream not ready).

---

## Files Changed (All Committed + Pushed)

| File | Change |
|------|--------|
| `bin/backfill/run_phase4_backfill.sh` | Python-based pre-flight check |
| `bin/monitoring/check_training_data_quality.sh` | **NEW** — three-tier contamination monitor v2 |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Post-write validation + Slack alerts |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Quality metrics in verify_phase4_data_ready |
| `orchestration/cloud_functions/phase5_to_phase6/main.py` | Added `season-subsets` to export types |
| `data_processors/publishing/all_subsets_picks_exporter.py` | `stats` → `record` (W-L), added `signal` |
| `data_processors/publishing/season_subset_picks_exporter.py` | **NEW** — full-season subset picks file |
| `backfill_jobs/publishing/daily_export.py` | Registered `season-subsets` export type |
| `.claude/skills/validate-daily/SKILL.md` | Phase 0.487 training contamination check |
| `.claude/skills/spot-check-features/SKILL.md` | Check #28 training contamination |
| `docs/08-projects/current/training-data-quality-prevention/00-PROJECT-OVERVIEW.md` | **NEW** — project docs |

**BQ changes (applied directly, not in code):**
- `ALTER TABLE nba_predictions.player_prop_predictions ADD COLUMN vegas_line_source STRING`
- `ALTER TABLE nba_predictions.player_prop_predictions ADD COLUMN required_default_count INT64`

---

## Next Session Priorities

1. **Verify predictions are working** (schema fix + worker redeploy should have fixed it)
2. **Backfill predictions for Feb 7** (10 games, zero predictions)
3. **Verify backfill (processors 3-5)** completed and check contamination improvement
4. **Build schema validation** to prevent this class of bug:
   - Worker startup check that validates output fields against BQ schema
   - Or pre-deploy script that compares code field names with BQ table columns
5. **Export season subset picks** once backfill is done: `PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-08 --only season-subsets`
6. **Start past-seasons backfill** (2021-2025) once current-season processors 3-5 complete
7. **Investigate PredictionCoordinator stuck-in-running pattern** — may need a force-reset endpoint or shorter timeout

---

## Research Not Yet Implemented

### Phase 2 Data Completeness for L5/L10 Averages
`StatsAggregator.aggregate()` blindly does `played_games.head(5)` without verifying all games are present. Infrastructure exists (`shared/validation/window_completeness.py`) but isn't wired into Phase 4 cache. Medium-sized project.

---

*Session 158 — Co-Authored-By: Claude Opus 4.6*
