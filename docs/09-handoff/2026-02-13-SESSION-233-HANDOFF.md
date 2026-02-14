# Session 233 Handoff — Live Export Fix + Grading Backfill

**Date:** 2026-02-13
**Status:** All work committed, deployed, verified
**Context:** All-Star break (no games Feb 13+, last games Feb 12)

---

## What Was Done

### 1. Verified Session 232 Changes (Already Committed)

Session 232's multi-source live grading + display confidence changes were already committed (`54b0a5fc`) and pushed before this session started. Cloud Build auto-deployed `live-export` and `phase6-export` functions.

### 2. Fixed Live Export Timeout Bug (Critical)

**Bug:** Triggering live-export for Feb 12 (all games final) returned `upstream request timeout`. The live-grading JSON showed 0/32 graded with 0 games_final.

**Root Cause:** `run_live_export()` runs `LiveScoresExporter` first, which calls BDL API unconditionally. BDL returns 401 (no API key in CF env) and the retry decorator has 60s base delay × 5 attempts = burns entire 120s CF timeout. `LiveGradingExporter` (which has BigQuery fallback for final games) never gets to run.

**Fix (commit `fb0f583f`):**
- `main.py`: Added `_check_games_in_progress()` — queries schedule, skips `LiveScoresExporter` entirely when no games are in-progress
- `live_scores_exporter.py`: Reduced retry params from `base_delay=60, max_attempts=5` to `base_delay=2, max_attempts=3`
- `live_grading_exporter.py`: Removed outer `@retry_with_jitter` decorator, reduced inner retry to `base_delay=2, max_attempts=3, max_delay=15`

**Result:** Live export for final-game dates now completes in ~9-16 seconds (was timing out at 120s).

### 3. Backfilled Live Grading (Feb 7-12)

After deploying the fix, triggered live-export for all dates with broken grading:

| Date | Before | After |
|------|--------|-------|
| Feb 7 | 0/0 graded | 153/165 graded, 47.9% WR |
| Feb 8 | 53/53 (was OK) | 53/53, 63.2% WR |
| Feb 9 | 82/82 (was OK) | 82/82, 71.4% WR |
| Feb 10 | 0/29 graded | 26/29 graded, 39.1% WR |
| Feb 11 | 191/196 (was OK) | 191/196, 47.6% WR |
| Feb 12 | 0/32 graded | 25/32 graded, 60.0% WR |

### 4. Ran Daily Validation

- **No games today** — All-Star break. No predictions, no feature store data needed.
- **Core services up to date** — coordinator, worker, Phase 3/4, scrapers all current.
- **5 stale deployments** — see below.

---

## Files Changed

| File | Commit | What |
|------|--------|------|
| `orchestration/cloud_functions/live_export/main.py` | `fb0f583f` | Skip LiveScoresExporter when no in-progress games |
| `data_processors/publishing/live_scores_exporter.py` | `fb0f583f` | Reduce BDL retry delays (60s→2s base, 5→3 attempts) |
| `data_processors/publishing/live_grading_exporter.py` | `fb0f583f` | Remove outer retry decorator, reduce inner retry delays |

---

## What's NOT Done

### 1. Stale Deployments (5 services)

| Service | Priority | Why |
|---------|----------|-----|
| `phase5b-grading` | **P2 — deploy before games resume** | Missing `8454ccb4` (remove minimum prediction threshold from grading) |
| `nba-grading-service` | P2 | 4 commits behind (V12 shadow mode + grading fix) |
| `validation-runner` | P3 | 4 commits behind (V12 additions, non-critical) |
| `reconcile` | P3 | 1 commit (f-string syntax fix) |
| `validate-freshness` | P3 | 1 commit (f-string syntax fix) |

**Deploy `phase5b-grading` before games resume:**
```bash
./bin/deploy-service.sh phase5b-grading
# OR if it's a Cloud Function:
# It auto-deploys via Cloud Build, but verify with:
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=3 --filter="substitutions._FUNCTION_NAME=phase5b-grading"
```

### 2. Champion Model Decay (Ongoing)

| Metric | Value | Status |
|--------|-------|--------|
| 7-day edge 3+ HR | 47.4% (95 picks) | Below 52.4% breakeven |
| 14-day edge 3+ HR | 40.6% (224 picks) | Well below breakeven |
| Training end date | 2026-01-08 | 36 days stale |

**Shadow model comparison (7-day):**

| Model | Edge 3+ Picks | HR | vs Champion |
|-------|--------------|-----|-------------|
| Q45 | 25 | 60.0% | +12.6pp |
| Q43 | 37 | 54.1% | +6.7pp |
| Champion | 95 | 47.4% | baseline |

Neither Q43 nor Q45 has 50+ edge 3+ graded picks yet (the promotion threshold). The All-Star break will pause accumulation.

**Options:**
1. **Fresh retrain** with data through Feb 12: `PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V9_FEB_RETRAIN" --train-start 2025-11-02 --train-end 2026-02-12`
2. **Promote Q45** if 60% holds with more volume post-break
3. **Deploy V12** (Vegas-free model from Session 228-230) — see `docs/08-projects/current/model-improvement-analysis/`

### 3. BDL API Key in Cloud Functions

The `live-export` Cloud Function doesn't have `BDL_API_KEY` in its env vars. The BDL live endpoint returns 401 without auth. This doesn't matter for final-game backfills (BigQuery fallback works), but will fail for real-time in-progress scoring.

**Fix:** Add BDL API key to `cloudbuild-functions.yaml` or via Secret Manager:
```bash
gcloud functions deploy live-export --region=us-west2 \
  --update-env-vars="BDL_API_KEY=$(gcloud secrets versions access latest --secret=bdl-api-key)"
```

### 4. Frontend Confidence Meter Thresholds

Session 232's display confidence formula changed the scale. Frontend needs updated thresholds:
- High: 70+
- Medium: 50-69
- Low: <50
- PASS picks capped at 40

---

## Architecture Note

### Live Export Function Flow (After Fix)

```
HTTP POST → main()
  ├─ _check_games_in_progress(target_date)  ← NEW: BQ schedule check
  │   └─ If no in-progress games → skip LiveScoresExporter
  ├─ LiveScoresExporter (BDL only) — only when games live
  ├─ LiveGradingExporter (multi-source) — always runs
  │   ├─ BigQuery for final games (authoritative)
  │   └─ BDL for in-progress games (real-time fallback)
  ├─ TonightAllPlayersExporter (non-critical)
  └─ StatusExporter (non-critical)
```

### Key Retry Parameters (Post-Fix)

| Exporter | Base Delay | Max Delay | Attempts |
|----------|-----------|-----------|----------|
| LiveScoresExporter | 2s | 15s | 3 |
| LiveGradingExporter (inner) | 2s | 15s | 3 |

Previously both were 60s base / 1800s max / 5 attempts — designed for long-running scrapers, not 120s Cloud Functions.

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
# 2. Check when games resume
bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as games FROM nba_reference.nba_schedule WHERE game_date > CURRENT_DATE() AND game_date <= CURRENT_DATE() + 7 GROUP BY 1 ORDER BY 1"

# 3. Deploy stale grading service before games resume
./bin/deploy-service.sh phase5b-grading

# 4. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 5. Consider model retrain during break
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V9_FEB_RETRAIN" --train-start 2025-11-02 --train-end 2026-02-12

# 6. Run daily validation when games resume
/validate-daily
```
