# New Chat Handoff — 2026-03-22 (Post Session 481)

**Date:** 2026-03-22 (Sunday)
**Latest commit:** `cadba8d0` — docs: Session 481 handoff

---

## System State: HEALTHY

### NBA Fleet (as of 2026-03-21)
| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | HEALTHY | 60.0% (N=20) | Primary — Feb 27 training end |
| `lgbm_v12_noveg_train1215_0214` | HEALTHY | 60.0% (N=15) | Mar 21 enabled — watch for N≥30 |

**Today (Mar 22):** 0 picks — correct. Both models RED signal (0-1.5% OVER, tight 5-game slate). Normal behavior.

### Today's Schedule
```
Mar 22 (today):   5 games  ← light, 0 picks expected
Mar 23:          10 games
Mar 24:           4 games  ← mlb-resume-reminder fires 8 AM ET
Mar 25:          12 games  ← target day, biggest pick volume this week
Mar 27:          10 games  ← MLB Opening Day
```

---

## What Was Done This Session

### 1. Full NBA Validation — All Healthy
- Pipeline, deployment drift, feature store, betting lines, analytics quality all checked
- MAE gap 0.74 (was 0.97, improving). Vegas MAE 5.43 — retrain gate still blocked (needs <5.0)
- Keep `weekly-retrain` CF paused

### 2. Site Bug Fixes
**KD Mar 16 (ungraded pick):**
- XGB model was BLOCKED → its predictions marked `is_active=FALSE` → grading skipped it
- Fixed: reactivated KD XGB prediction, ran grading backfill, regenerated `best-bets/all.json`
- KD UNDER 25.5, actual=18, now shows **WIN** ✅

**Zion Mar 19 (2 picks showing):**
- `prediction_accuracy` had duplicate rows (lines 21.5 and 20.5) from same model — JOIN doubled it
- Fixed: deleted stale 21.5 row, regenerated `best-bets/all.json`
- Zion UNDER 20.5, actual=15, now shows **1 pick, WIN** ✅

### 3. MLB Opening Day Prep (March 27 — 5 days away)

**Bugs fixed and deployed:**
- `predictions/mlb/worker.py`: `/predict-batch` NOW resolves `'TODAY'` literal (was crashing all prediction schedulers)
- `data_processors/grading/mlb/mlb_prediction_grading_processor.py` + `mlb_shadow_grading_processor.py`: `'YESTERDAY'`/`'TODAY'` literals now resolved (were causing `Could not cast literal "YESTERDAY" to type DATE` SQL errors)
- Created `data_processors/grading/mlb/Dockerfile` + `requirements.txt` (missing — grading service was stuck on Jan 7 image)

**Infrastructure:**
- `mlb_orchestration.scraper_execution_log` BQ table created (was 404)
- MLB prediction worker: revision `00022-mlg` at 100% traffic ✅
- MLB grading service: revision `00003-56h` at 100% traffic ✅

**MLB model ready:** `catboost_mlb_v2_regressor_36f_20250928` — enabled, is_production, 70% HR, trained through Sep 2025

---

## Immediate Next Steps

### Mar 24 (2 days away)
- `mlb-resume-reminder-mar24` Slack alert fires 8 AM ET
- Execute: `./bin/mlb-season-resume.sh` (mostly verifies state since all jobs already ENABLED)
- Verify pitcher props scrapers are operational

### Mar 25 (3 days away)
- 12-game NBA slate — biggest volume day this week, watch picks carefully
- `lgbm_v12_noveg_train1215_0214` decision point: deactivate if HR drops below 52.4% by today

### Mar 27 (MLB Opening Day)
- Verify `mlb-predictions-generate` scheduler fires and `mlb_predictions.pitcher_strikeout_predictions` has rows
- `mlb-pitcher-props-validator-4hourly` restricted to Apr-Oct — may need manual trigger on Mar 27
- Watch BDL live box scores: was returning 401 pre-season. Verify it works when games start.

### NBA Ongoing
- MAE gap normalizing day-over-day — retrain gate will clear soon once Vegas MAE < 5.0
- Do NOT lower OVER floor to 4.5
- Do NOT re-enable `catboost_v9_low_vegas` (DEGRADING → BLOCKED)
- `nba-props-evening-closing` + `self-heal-predictions`: both DEADLINE_EXCEEDED at 900s. Low priority fix: `gcloud scheduler jobs update {job} --location=us-west2 --attempt-deadline=1800s`

---

## Known Constraints
- `weekly-retrain` CF: **KEEP PAUSED** — Vegas MAE gate 5.0, current 5.43
- OVER floor: **KEEP AT 5.0** — do not lower
- `catboost_v9_low_vegas`: **DO NOT RE-ENABLE** (DEGRADING)

---

## Morning Checks (START keyword)
```bash
/daily-steering          # Model health, signal health, macro trends
/validate-daily          # Full pipeline validation
./bin/check-deployment-drift.sh --verbose
/best-bets-config        # BB thresholds, models, signals
```

---

## Key Gotchas Learned This Session

**NEVER trigger `signal-best-bets` export for historical dates.**
It re-runs the BB aggregator (produces 0 picks for past dates), overwrites the GCS file with 0 picks, AND the scoped DELETE removes player picks from `signal_best_bets_picks`. For historical fixes, use:
```bash
PYTHONPATH=. .venv/bin/python3 backfill_jobs/publishing/daily_export.py \
  --date $(date +%Y-%m-%d) --only best-bets-all
```
Always use TODAY's date — using a historical date only shows history through that date.

**MLB Cloud Run traffic doesn't auto-route after builds.**
After `gcloud run deploy`, always check: `gcloud run services describe SERVICE --region=us-west2 --format="yaml(status.traffic)"` and manually route if needed: `gcloud run services update-traffic SERVICE --to-revisions=REVISION=100`

**MLB grading Dockerfile requires `predictions/shared/`.**
`data_processors/grading/__init__.py` imports NBA processors at load time, which import `predictions.shared.distributed_lock`. Always include:
```dockerfile
COPY predictions/__init__.py ./predictions/__init__.py
COPY predictions/shared/ ./predictions/shared/
```

**Grading an inactive prediction.**
When a model is BLOCKED, its `player_prop_predictions` get `is_active=FALSE`. Grading skips inactive predictions. To backfill a published pick from a BLOCKED model: reactivate the specific prediction row, run `/grade-date?date=YYYY-MM-DD` on the grading service, then clean up.

---

## GCS / Site Files
- History view: `gs://nba-props-platform-api/v1/best-bets/all.json`
- Today's picks: `gs://nba-props-platform-api/v1/signal-best-bets/{date}.json`
- `all.json` reads from `signal_best_bets_picks` + `best_bets_published_picks` (fallback) with `prediction_accuracy` grades joined

---

## Deployed Services (current)
| Service | Revision | Status |
|---------|----------|--------|
| prediction-worker | latest (commit 6b631ac) | 100% ✅ |
| prediction-coordinator | latest (commit 6b631ac) | 100% ✅ |
| nba-grading-service | latest (commit e30fe7c7) | 100% ✅ |
| mlb-prediction-worker | 00022-mlg (TODAY fix) | 100% ✅ |
| mlb-phase6-grading | 00003-56h (YESTERDAY fix) | 100% ✅ |
| nba-phase1-scrapers | STALE (12 commits, MLB features) | LOW priority |
