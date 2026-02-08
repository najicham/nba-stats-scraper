# Session 162 Handoff

**Date:** 2026-02-08
**Status:** All fixes pushed to main (4 commits), all 12 auto-deploys succeeded. Past-seasons Phase 4 backfill running in background.

---

## Quick Start for Next Session

```bash
# 1. Check if past-seasons Phase 4 backfill finished (PID 3789597)
ps -p 3789597 -o pid,etime --no-headers 2>/dev/null || echo "Finished"

# 2. If finished, check quality improvement
./bin/monitoring/check_training_data_quality.sh --recent

# 3. IMPORTANT: The backfill started BEFORE the validation fix (Commit 4).
#    ~3,604 defense zone records were blocked by the old ±0.30 rule.
#    After backfill finishes, re-run JUST defense zone for affected dates:
#    ./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 --end-date 2025-06-22 --processor team_defense_zone_analysis

# 4. Run daily validation (now uses correct season_avg bias methodology)
/validate-daily

# 5. Verify Phase 2→3 orchestrator triggers on next game day
#    Check Firestore: phase2_completion/<date> should show _triggered=True
```

---

## What Session 162 Did

### The Theme: Cross-Layer Synchronization Failures

Every bug this session was a **mismatch between two components that should agree**:
- A method returns `List[Dict]` but the caller unpacks it as a tuple
- Validation expects ±0.30 (fractions) but the processor outputs ±15.0 (percentage points)
- `next()` assumes a query always returns rows, but sometimes it doesn't
- `--set-env-vars` wipes all env vars, should be `--update-env-vars`
- Bias queries tier by `actual_points` (what happened) instead of `season_avg` (what the player is)

---

### Commit 1: `c9a02f4e` — Two fixes

**Bug 1: UpcomingTeamGameContextProcessor crash**
- `save_analytics()` line 1579: `valid_records, invalid_records = self._validate_before_write(...)`
- But `_validate_before_write()` (in `bigquery_save_ops.py`) returns **one value** (`List[Dict]`), not a tuple
- Python tried to unpack the list's elements as `(valid_records, invalid_records)` → `ValueError: too many values to unpack`
- **Impact:** UpcomingTeamGameContext failed on EVERY run. Phase 3 was incomplete (4/5) for Feb 7.
- **Fix:** `valid_records = self._validate_before_write(...)` — single assignment
- **Why only this processor?** Other callers (line 208, line 2559) already used single assignment. This was the only processor with a custom `save_analytics()` that had the bug.

**Bug 2: Model bias queries used wrong methodology**
- `/validate-daily` skill had 4 SQL queries that tiered players by `actual_points` (survivorship bias)
- Changed all 4 to use `season_avg` tiers — see "Model Bias: Why It Was Circular Reasoning" section below
- Files: `.claude/skills/validate-daily/SKILL.md` (Phases 0.466, 0.55, Player Tier Breakdown)

### Commit 2: `ee68ce7a` — Service reliability (4 fixes)

**Fix 1: Error visibility in processor API responses**
- When `processor.run()` returns `False`, the HTTP response was just `{"status": "error"}` with **no error message**
- Debugging required searching Cloud Logging (often delayed 10+ min)
- Now returns `{"status": "error", "error": "actual error message"}`
- Added `self.last_error = e` in `analytics_base.py` exception handler
- Files: `async_orchestration.py`, `main_analytics_service.py`, `analytics_base.py`

**Fix 2: Protected `next()` calls in `_validate_after_write`**
- `bigquery_save_ops.py` had 3 bare `next(query_result)` calls (lines 1019, 1091, 1145)
- If a BigQuery COUNT/NULL/anomaly query returned 0 rows → `StopIteration` crash
- **This was the SECOND bug** hiding behind Bug 1. Fixing the unpack bug let the code reach `_validate_after_write` for the first time, which then crashed.
- Changed to `next(query_result, None)` with graceful fallbacks
- File: `bigquery_save_ops.py`

**Fix 3: Deploy-time import validation for Cloud Functions**
- Added Step 1 to `cloudbuild-functions.yaml`: installs requirements, runs `python -c "import main"`
- Would have caught Session 161's PyYAML crash before deploying
- File: `cloudbuild-functions.yaml`

**Fix 4: `--set-env-vars` → `--update-env-vars`**
- `cloudbuild-functions.yaml` used `--set-env-vars` which **wipes ALL existing env vars** on every deploy
- CLAUDE.md already warned about this: "NEVER use `--set-env-vars`"
- Changed to `--update-env-vars` (adds/updates without wiping)
- File: `cloudbuild-functions.yaml`

### Commit 3: `344b0378` — Validation unit mismatch

**Bug: Defense zone validation blocked 100% of records**
- `pre_write_validator.py` rules for `team_defense_zone_analysis`:
  - `paint_defense_vs_league_avg`: must be ±0.30
  - `mid_range_defense_vs_league_avg`: must be ±0.30
  - `three_pt_defense_vs_league_avg`: must be ±0.30
- But the processor calculates: `(zone_pct - league_avg) * 100` → **percentage points** (e.g., 4.0 = "4pp worse")
- Schema docs say "Range: -10.00 to +10.00", tests expect ±15.0
- The comment ON THE SAME LINE said "typically -20 to +20" — only the rule had the wrong units
- **Impact:** ALL 30/30 team records blocked per game date. ~3,604 records blocked in the running backfill.
- **Fix:** Changed thresholds from ±0.30 to ±15.0
- File: `shared/validation/pre_write_validator.py`

### Commit 4: `cd12ef3b` — Documentation

- Session handoff and project overview docs

---

## Model Bias: Why It Was Circular Reasoning

**This has confused Sessions 101, 102, 124, 161, and 162. DO NOT SKIP THIS SECTION.**

### The Wrong Query (what 4+ sessions ran)

```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN 'Stars'
    WHEN actual_points >= 15 THEN 'Starters'
    WHEN actual_points >= 5 THEN 'Role'
    ELSE 'Bench'
  END as tier,
  AVG(predicted_points - actual_points) as bias
FROM prediction_accuracy ...
```

**Result:** Stars show -10.1 bias. Bench shows +5.2 bias. "The model is terrible!"

### Why This Is Wrong

This query selects players **AFTER seeing their actual score**, then checks if the model predicted correctly. That's backwards.

**Think of it this way:**
1. You pick everyone who scored 30+ points in a game
2. You check what the model predicted for them
3. Of course the model predicted lower — **you selected the games where they scored unusually high**

A player averaging 20 PPG who explodes for 35 points enters the "Stars (25+)" tier. The model predicted ~20 (reasonable!), but the query says that's a -15 "bias." It's not bias — it's **selecting for outlier performances and blaming the model for not predicting outliers.**

The same logic works in reverse for "Bench (<5)": a player averaging 12 PPG who has a bad 3-point game enters the "Bench" tier. The model predicted ~12 (correct!), but the query says that's +9 "over-prediction."

### The Correct Query

```sql
WITH player_avgs AS (
  SELECT player_lookup, AVG(actual_points) as season_avg
  FROM prediction_accuracy
  WHERE system_id = 'catboost_v9' AND game_date >= '2025-11-01'
  GROUP BY 1
)
SELECT
  CASE
    WHEN pa.season_avg >= 25 THEN 'Stars'    -- Players who ARE stars
    WHEN pa.season_avg >= 15 THEN 'Starters'
    WHEN pa.season_avg >= 8 THEN 'Role'
    ELSE 'Bench'
  END as tier,
  AVG(p.predicted_points - p.actual_points) as bias
FROM prediction_accuracy p
JOIN player_avgs pa USING (player_lookup) ...
```

**Result:** Stars show **-0.3 bias**. The model is well-calibrated.

### Why the Difference Is So Large

| Tier Method | Stars Bias | What It Measures |
|-------------|-----------|------------------|
| `actual_points >= 25` | -10.1 | "When someone scores 25+, did we predict 25+?" (measures outlier prediction) |
| `season_avg >= 25` | -0.3 | "For players who average 25+, are we systematically wrong?" (measures real bias) |

The -10.1 is measuring **variance**, not **bias**. Any regression model will show this pattern because it predicts the expected value, not the outcome of a single game.

### Where This Is Now Enforced

- `/validate-daily` skill: All 4 bias queries updated (Phase 0.466, Phase 0.55, bias trend, tier breakdown)
- `CLAUDE.md`: Explains the correct methodology in the "Critical Context" section
- `docs/08-projects/current/session-161-model-eval-and-subsets/00-PROJECT-OVERVIEW.md`: Full analysis
- `docs/08-projects/current/session-124-model-naming-refresh/TIER-BIAS-METHODOLOGY.md`: Reference doc

**Rule for future sessions:** If you see "star player bias > 3pts", check which tier methodology the query uses. If it uses `actual_points`, the result is meaningless.

---

## Current State

### Phase 3 (Feb 7-8)
- **Feb 7:** 5/5 processors complete. UpcomingTeamGameContext succeeded after both fixes (unpack + next()).
- **Feb 8:** Games were in progress during session. Will process via normal pipeline when Phase 2 completes.

### Phase 4 Past-Seasons Backfill (PID 3789597)
- **Status:** Running since ~19:15 UTC Feb 8
- **Range:** 2021-10-19 to 2025-06-22 (~853 game dates, 7-9 hours)
- **Known Issue:** ~3,604 defense zone records blocked by old ±0.30 validation (fix pushed after start)
- **Action needed:** After completion, re-run `team_defense_zone_analysis` processor for blocked dates

### Phase 2→3 Orchestrator
- Healthy (PyYAML fix from Session 161 deployed and verified at 18:37 UTC)
- Loaded 5 expected processors, startup probe succeeded
- Will trigger on next Phase 2 completion (monitoring-only role; actual Phase 3 trigger is via direct Pub/Sub)

### Training Data Quality
- 24.6% of rows still have required feature defaults (unchanged — cache backfill improves future predictions, not existing feature store rows)
- Top defaulted: Vegas features (25-27) at 51.3%, shot zone (18-20) at ~20%

### Subset Picks
- 1,246 rows across 28 days (Jan 9 - Feb 6), all from backfill
- No data for Feb 7-8 yet (SubsetMaterializer runs via Phase 5→6, which hasn't fired for these dates)
- `subset-picks` IS in `TONIGHT_EXPORT_TYPES` — should work next time Phase 5→6 runs

### V9 Retrain
- User confirmed **not worth it** even with better data. No retrain planned.

---

## Prevention Mechanisms Added This Session

| What | Prevents | File |
|------|----------|------|
| Deploy-time `python -c "import main"` | Missing dependencies (PyYAML-type) | `cloudbuild-functions.yaml` |
| Error messages in `{"status":"error"}` responses | Blind debugging through Cloud Logging | `async_orchestration.py`, `main_analytics_service.py` |
| `next(iter, None)` pattern | StopIteration crashes on empty results | `bigquery_save_ops.py` |
| `--update-env-vars` (not `--set-env-vars`) | Env var wipe on deploy | `cloudbuild-functions.yaml` |
| `season_avg` tier queries | Survivorship bias in model evaluation | `.claude/skills/validate-daily/SKILL.md` |

---

## Remaining Work for Future Sessions

1. **Re-run defense zone backfill** after current backfill completes (~3,604 blocked records)
2. **Audit all validation rules** in `pre_write_validator.py` against actual processor output — the unit mismatch pattern could exist elsewhere
3. **Search for unprotected `next()` calls** outside analytics (`grep -rn "next(" --include="*.py" | grep -v "next("` to find bare calls without default)
4. **Audit Cloud Function env vars** — `--set-env-vars` may have wiped important vars in past deploys
5. **OVER-only strategy evaluation** — OVER direction is strongest subset filter (82.8% vs 67.6% at same edge). Worth evaluating for production use.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` | Fixed `_validate_before_write` tuple unpack bug |
| `.claude/skills/validate-daily/SKILL.md` | Updated 4 bias queries to use `season_avg` tiers |
| `data_processors/analytics/async_orchestration.py` | Added error message to "status: error" responses |
| `data_processors/analytics/main_analytics_service.py` | Added error message to "status: error" responses |
| `data_processors/analytics/analytics_base.py` | Store `self.last_error` on exception |
| `data_processors/analytics/operations/bigquery_save_ops.py` | Protected 3 `next()` calls with default `None` |
| `cloudbuild-functions.yaml` | Added import validation step, fixed `--set-env-vars` → `--update-env-vars` |
| `shared/validation/pre_write_validator.py` | Fixed defense zone validation from ±0.30 to ±15.0 |
| `docs/08-projects/current/session-162-service-reliability/00-PROJECT-OVERVIEW.md` | NEW — full reliability audit |
| `docs/09-handoff/2026-02-08-SESSION-162-HANDOFF.md` | NEW (this file) |

---

## Debugging Timeline (for reference)

The UpcomingTeamGameContext fix required 5 retries to resolve because two bugs were stacked:

1. **First run:** `_validate_before_write` unpack crash (Bug 1)
2. **Deploy commit `c9a02f4e`** (unpack fix)
3. **Retries 2-3:** Still errored — old Cloud Run instance serving, or new code reached `_validate_after_write` which had Bug 2 (`next()` crash)
4. **Deploy commit `ee68ce7a`** (next() fix)
5. **Retry 4:** `status: success` in 18.76s

**Lesson:** When fixing a crash that prevents downstream code from running, expect the downstream code to have its own bugs. Fix #1 unmasked Fix #2.

---
*Session 162 — Co-Authored-By: Claude Opus 4.6*
