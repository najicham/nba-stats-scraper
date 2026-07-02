# Session Handoff — MLB Validation Findings + Cross-System Audit

**Date:** 2026-05-02
**Trigger:** Daily validation surfaced 5 silent failures + 1 frontend bug. Five investigation agents run in parallel produced a consolidated triage spanning cost waste, signal calibration, JSON convention drift, observability gaps, and tech debt.
**Outcome:** One fix shipped (`f2f76198`). Comprehensive backlog defined. Next session can execute most quick wins in a single sitting.

---

## TL;DR

Tonight's MLB monitoring uncovered:
1. **MLB Best Bets `pct` field shipping as 0–1 fraction** since launch — frontend rendered "0.5%" instead of "52.9%". **FIXED, deployed.**
2. **MLB Tonight page is empty for every date** because no MLB-side Tonight JSON has ever been built. This is a feature gap, not a daily failure.
3. **`weekly-retrain-trigger` is PAUSED, has never fired.** CLAUDE.md and MEMORY both claim Monday-5am autopilot. NBA models aging without governance. `mlb-biweekly-retrain` is a Slack reminder, not a real CF — so neither sport has working auto-retrain.
4. **Session 524 MLB retrain was never deployed** (handoff fiction). Production serves Sept-2025-only model with no April training data — explains the +0.73K over-prediction bias and Apr 25 18.8% HR.
5. **~$5/day in zombie/runaway processes** in the cost data: phase4 backfill loop, mlb-phase2 retry storm, idle prediction-coordinator min=1, oversized orchestrator memory.
6. **The pct-bug is systemic** — same shape in 6 NBA exporters (`results_exporter`, `live_grading_exporter`, `system_performance_exporter`, `player_profile_exporter`, `tonight_trend_plays_exporter`, `whos_hot_cold_exporter`).

---

## What was changed in this session

### 1. MLB Best Bets `pct` convention fix (committed, pushed, auto-deploying)

**Commit:** `f2f76198 fix(mlb): emit best_bets pct as 0-100 percentage to match NBA convention`

**File:** `data_processors/publishing/mlb/mlb_best_bets_exporter.py:240-251` — `_compute_record()` now returns `round(100.0 * wins / total, 1)` instead of `round(wins / total, 3)`. Same helper feeds season/month/week/last_10 plus every nested `weeks[].record.pct` and `weeks[].days[].record.pct`, so this single change fixes all MLB BB record cards.

**Deploy path:** `deploy-phase6-export` Cloud Build trigger watches `data_processors/publishing/**` → rebuilds the `phase6_export` Cloud Function on push → next phase6 run regenerates `gs://nba-props-platform-api/v1/mlb/best-bets/all.json` and `{date}.json`.

**Verify:** within ~10 min of push, `gcloud builds list --region=us-west2 --limit=3 --filter='deploy-phase6-export'` should show success; then `gsutil cp gs://nba-props-platform-api/v1/mlb/best-bets/all.json /tmp/x.json && python -c "import json; d=json.load(open('/tmp/x.json')); print(d['record']['season']['pct'])"` should print `52.9` (not `0.529`).

### 2. Pre-existing drift-alerter improvements still uncommitted

`bin/monitoring/deployment_drift_alerter.py` and `_cloudrun.py` have local edits adding `EXPECTED_MIN_INSTANCES` config-drift detection (work from the Apr 27 follow-up). Not yet pushed. Decide before the next session whether to ship these.

---

## Critical findings — sorted by blast radius

### 🚨 HIGH — silent landmines / live waste

#### A. `weekly-retrain-trigger` is PAUSED, NEVER fired

- **Reality:** `gcloud scheduler jobs describe weekly-retrain-trigger --location=us-west2` shows `state: PAUSED`, `lastAttemptTime: <empty>`. Schedule is `0 5 * * 1`.
- **Documentation:** CLAUDE.md:154 states "weekly-retrain CF fires every Monday 5 AM ET — auto-retrains all enabled families." MEMORY makes the same claim.
- **Impact:** NBA models aging silently. Operators trust autopilot that doesn't exist.
- **Decision needed:** enable it (and accept governance gates may fail-block during off-season) or update docs to say "manual via `./bin/retrain.sh`".

#### B. Session 524 MLB model retrain is fiction

- **Reality:** `mlb-prediction-worker` revision `00069-zfm` (not `00055-pv8` as handoff claims), env `MLB_CATBOOST_V2_MODEL_PATH=gs://...catboost_mlb_v2_regressor_40f_20250928.cbm` (Sept 2025, no April months).
- **Impact:** the +1.15 K OVER bias the handoff claimed was fixed is still live. Explains tonight's calibration audit finding that the model over-predicts by +0.73 K on April pitchers, and the Apr 25 18.8% HR day.
- **Action:** actually run `scripts/mlb/training/train_regressor_v2.py --training-start 2024-04-01 --training-end 2026-04-30`, upload to GCS, INSERT into `mlb_predictions.model_registry` with `is_production=TRUE` (demote prior), update env-var on `mlb-prediction-worker`, verify `update-traffic --to-latest`.
- **Decision needed:** do you want this self-driven, or stop at "trained + uploaded + registry row inserted" for human deploy approval?

#### C. MLB has no working auto-retrain

- `mlb-biweekly-retrain` scheduler is a Slack reminder posting to `slack-reminder-...`, NOT a Cloud Function that runs `train_regressor_v2.py`.
- **Action:** mirror the (currently paused) NBA `weekly-retrain` CF pattern; trigger HTTP function that runs the training script, writes registry row, updates env, gates on governance. ~6h dev time.

#### D. ~$5/day in cost waste (cost agent confirmed)

| # | Resource | Issue | $/day |
|---|---|---|---|
| 1 | **Phase4 zombie backfill loop** | 2 stale Cloud Run job executions hammering 2023 dates 24/7 | **$1.40** |
| 2 | **`mlb-phase2` retry storm** | Two bugs: `TODAY/` literal in GCS path + `raw_data.get()` AttributeError on lists | **$2.00** |
| 3 | **`prediction-coordinator min=1` while NBA halted** | 0 requests/24h | **$1.14** |
| 4 | **3 orchestrators bumped 512→1024MiB Apr 9** | Idle warmup overhead | **$0.45** |

Total reversible: $5.00/day. All four have specific gcloud commands defined in the cost-audit report (see "Quick Wins Commands" appendix below).

#### E. MLB Tonight page is empty for every date

- **Root cause:** there is **no MLB Tonight JSON published**. `gsutil ls gs://nba-props-platform-api/v1/mlb/` shows only `best-bets/` and `pitchers/`. There is no `mlb/tonight/`. The frontend Tonight page reads from the NBA path `tonight/{date}.json` which is NBA-only.
- **NBA Tonight files for Apr 28 → May 1 are tiny (~1.2 KB each, empty content)** — that's NBA halt working as designed.
- **Memory note `mlb-frontend-discipline.md`** says "No model/prediction content on MLB non-best-bets pages (tonight grid, leaderboards, TonightStrip)." So this may be intentional architecture — but the user expects functional MLB Tonight content during MLB season.
- **Decision needed:** is MLB Tonight supposed to render today's pitching matchups + lines (no model content), or full game-card cards with predictions? Once decided, build `data_processors/publishing/mlb/mlb_tonight_exporter.py` and a `phase6_export` MLB tonight branch.

### 🔴 SYSTEMIC — pct bug is not unique (6 more exporters)

The bug fixed tonight in `mlb_best_bets_exporter.py` exists in identical shape across:

| File | Endpoint | Sites |
|---|---|---|
| `results_exporter.py:237,241,243,362,406` | `results/{date}.json` | 5 |
| `live_grading_exporter.py:743,764` | `live-grading/{date}.json` | 2 |
| `system_performance_exporter.py:158,169,177,182,183,186,187,192,286` | `systems/performance.json` | 9 |
| `player_profile_exporter.py` (multiple SQL `ROUND(.../...,3)`) | `players/{lookup}.json` | 11 |
| `tonight_trend_plays_exporter.py:213,240` | `tonight/trend-plays.json` | 2 |
| `whos_hot_cold_exporter.py:140,179,265` | `whos-hot-cold.json` | 3 |

**Plus a separate MLB streak bug:** `mlb_best_bets_exporter.py:287` reads `is_correct` (column doesn't exist; rows have `prediction_correct`) → `streak.type` is stuck at `"L"`. One-character fix.

**Recommended approach:**
1. Add `compute_pct(wins, total)` helper in `data_processors/publishing/exporter_utils.py` (returns 0–100, 1 decimal, never null — uses 0.0).
2. Replace every ad-hoc `round(100.0 * w / t, 1) if t > 0 else …` and every `ROUND(... / COUNT(*), 3)` SQL fragment.
3. Add a JSON contract test in `tests/unit/publishing/` that asserts every field matching `r"_(pct|rate)$"|^pct$` is in `[0, 100]`.

### 🟡 MLB Calibration — IMPORTANT REVISION

The earlier framing in this conversation ("rescue is broken / `edge_floor` blocks 70% of winners / `recent_k_above_line` 46.7% HR") **does not reproduce on the April 2026 window** with current grading state. Fresh audit (38 picks, 33 graded):

| Field | Briefed | April 2026 Reality |
|---|---|---|
| `recent_k_above_line` HR | 46.7% (bad) | **55.6%** (N=18) |
| `edge_floor` CF HR | 70% (blocking winners) | **36.2%** (doing its job) |
| Rescue net effect | Negative | **Positive** (57.9% rescued vs 42.9% non-rescued) |

**The actual bias is in the model, not the pipeline.** The model over-predicts strikeouts by +0.73 K vs actuals (lines are well-calibrated), so high edge becomes anti-signal in April:
- Edge ≥ 1.0: 33% HR
- Edge 0.5–0.75: 86% HR

**Real demote candidates** (durable, validated):
- `chase_rate_over` — 15.4% HR (N=13)
- `high_csw_over` — 25.0% HR (N=12, also fires on stale `season_csw_pct=NULL` April pitchers)

**Simulated impact** if both demoted to `TRACKING_ONLY_SIGNALS`: HR 51.5% → **72.2%**, volume −45%. Adding a temporary edge ≥1.0 cap → 76.9% but volume −61%. **Cap is a band-aid; durable fix is item B (retrain + deploy April-inclusive model).**

May 1 zero-pick day: max home OVER edge was 0.75 (3 candidates at edge 0.26–0.45 below floor). No tweak short of dropping edge floor below 0.3 would have produced picks; that would gut HR. Accept zero-pick days during model-bias regime.

### 🟢 Pre-commit / monitor backlog

The 5 incidents from the past 16 days (Apr 17 drift alerter death, Apr 27 cost regression, Session 524 fiction, May 1 pct bug, May 1 ungraded predictions) would have been caught by:

| # | Check | Catches | Effort |
|---|---|---|---|
| 1 | `validate_pct_convention.py` pre-commit — scan `data_processors/publishing/**` for `*pct*\|*rate*` keys missing `100 *` multiplier | pct bug class | 2h |
| 2 | JSON contract test in CI — load yesterday's exports, assert every `*_pct`/`*_rate` is in `[0, 100]` | pct + null-vs-missing | 2h |
| 3 | Cloud Build `_MIN_INSTANCES` substitution ↔ `bin/deploy-service.sh` `get_min_instances()` parity check | Apr 27 cost regression | 2h |
| 4 | Scheduler health canary — alert on 401/403 within 1h | Apr 17 drift alerter death | 3h |
| 5 | Post-deploy assertion — service `model.id` matches GCS env-var basename | Session 524 fiction | 3h |
| 6 | `bin/monitoring/setup_*_scheduler.sh` pre-commit grep for `oidcToken` against Run Admin API URIs | drift alerter auth class | 30m |
| 7 | Pre-commit: any one-shot scheduler must self-disable in handler, OR be in a documented one-shot list | Sleeping reminder schedulers | 1h |
| 8 | MLB services to `validate_dockerfiles.py` `SERVICE_DOCKERFILE_MAP` | wrong-Dockerfile-deployed class | 30m |

### 🟠 Tech debt (lower urgency, but easy wins)

- **`compute_win_rate()` in `exporter_utils.py:328`** returns 0–1 fraction (footgun for any future caller). Rename to `compute_win_rate_fraction` and add `compute_win_rate_pct` returning 0–100.
- **`mlb-monthly-fangraphs-refresh` cron is `0 10 1 4-10 *`** (April–October). Other MLB schedulers were fixed to `3-10` for late-March opening day but this one was missed.
- **`predictions/mlb/requirements.txt` has no `requirements-lock.txt`** — NBA worker is locked, MLB floats. Generate and commit lock file.
- **Two retrain scripts side-by-side**: `ml/training/mlb/quick_retrain_mlb.py` (v1 classifier) and `scripts/mlb/training/train_regressor_v2.py` (v2 regressor). MEMORY warns to use v2; v1 has no `DeprecationWarning` in the file itself. Add deprecation banner or rename.
- **Stale `setup_*_scheduler.sh` scripts** in `bin/monitoring/` (Mar 17 mtime; mixed `oauth`/`oidc`; one references the wrong `deployment_drift_alerter.py` variant). Move to `docs/archive/` with a README, or update each.
- **CLAUDE.md "DEPRECATED" `monthly-retrain` CF still has an active build trigger**. Delete one or the other.
- **`prediction_grades` table tagged DEPRECATED** but no pre-commit blocks queries. Easy SQL deny-list addition.

---

## Action plan — recommended ordering

### Tonight / tomorrow morning (~30 min, $5/day saved, all reversible)

```bash
# Q1: Stop phase4 zombie backfill loop
gcloud run jobs executions cancel nba-gamebook-backfill-ptvn6 --region=us-west2 --project=nba-props-platform
gcloud run jobs executions cancel nba-odds-api-season-backfill-xq8pp --region=us-west2 --project=nba-props-platform

# Q2: Drop prediction-coordinator min-instances during NBA halt (RE-ENABLE Sept 25!)
gcloud run services update prediction-coordinator --region=us-west2 --project=nba-props-platform --min-instances=0

# Q3: Quarantine bad mlb-phase2 retry-storm files + replay subscription cursor
gsutil -m mv "gs://nba-scraped-data/mlb-odds-api/game-lines/TODAY/*" gs://nba-scraped-data/mlb-odds-api/game-lines/_quarantine/
gcloud pubsub subscriptions seek mlb-phase2-raw-sub --time=$(date -u +%Y-%m-%dT%H:%M:%SZ) --project=nba-props-platform

# Q4: Revert orchestrator memory bump
for cf in phase3-to-phase4-orchestrator phase4-to-phase5-orchestrator phase5-to-phase6-orchestrator; do
  gcloud functions deploy "$cf" --region=us-west2 --memory=512Mi --no-source --project=nba-props-platform
done
```

Plus the one-line MLB streak bug fix in `mlb_best_bets_exporter.py:287` (`is_correct` → `prediction_correct`).

### This week (decisions + small code)

1. **Decide:** enable `weekly-retrain-trigger` or correct CLAUDE.md to "manual only"? Pick one.
2. **Decide:** MLB Tonight page architecture — pure schedule/lines (no model content) or full pick cards? Determines exporter scope.
3. **Decide:** for the MLB regressor retrain, do you want me to stop at "trained + uploaded + registry row inserted" (you flip env-var) or auto-deploy after gates pass?
4. Demote `chase_rate_over` + `high_csw_over` to `TRACKING_ONLY_SIGNALS` in `ml/signals/mlb/best_bets_exporter.py` (lines ~93–106). Expected HR: 51.5% → 72.2%. Volume −45%.
5. Add `compute_pct(wins, total)` helper to `data_processors/publishing/exporter_utils.py` and migrate the 6 systemic-bug exporters in one PR (one logical change, identical pattern).
6. Add JSON contract test in CI.
7. Add MLB services to `validate_dockerfiles.py`.

### Next 1–2 weeks (durable infrastructure)

8. **Actually retrain and deploy MLB regressor** with April-inclusive training (this is the durable fix for the calibration findings; the signal demotes are a band-aid).
9. **Build `mlb-weekly-retrain` CF** — mirror NBA pattern, trigger HTTP function that runs `train_regressor_v2.py`, writes registry row, updates `mlb-prediction-worker` env, gates on governance.
10. **Build MLB Tonight exporter + `mlb/tonight/{date}.json` endpoint** (pending architectural decision in #2).
11. **Generate `predictions/mlb/requirements-lock.txt`**, update Dockerfile to use it.
12. Build `bin/mlb-model-registry.sh validate|production` (mirror NBA `model-registry.sh`).

### Defer / discuss

- Saturday-block from the calibration sim was variance (N=4); don't ship.
- Edge ≥1.0 cap is the band-aid; only worth shipping if model retrain (#8) is going to take more than 7 days.
- Cost canary build (Apr 27 follow-up item) — still queued but lower priority than items 1–4.
- October NBA re-enablement validator — build in early September per Apr 27 handoff.

---

## Open decisions for the user

1. **Auto-retrain on/off?** Re-enable `weekly-retrain-trigger` or update CLAUDE.md to admit it's manual.
2. **Deploy authority?** For the MLB regressor retrain — autonomous after gates pass, or stop at upload+registry for human flip.
3. **OVER-only enforcement?** Aggregator currently allows UNDER picks (55 in Apr 22–30 at 39.6% HR) despite "OVER-only" docs. Strategy doc bug or code bug? `MLB_UNDER_ENABLED` env var controls it.
4. **MLB Tonight page scope?** Schedule/lines only (per `mlb-frontend-discipline.md`) or full pick cards? Architectural — gates the exporter design.

---

## Files referenced

- **Fix shipped:** `data_processors/publishing/mlb/mlb_best_bets_exporter.py`
- **Pending streak bug fix:** `data_processors/publishing/mlb/mlb_best_bets_exporter.py:287`
- **Drift alerter (uncommitted):** `bin/monitoring/deployment_drift_alerter.py`, `bin/monitoring/deployment_drift_alerter_cloudrun.py`
- **Systemic pct bug:** `data_processors/publishing/{results_exporter,live_grading_exporter,system_performance_exporter,player_profile_exporter,tonight_trend_plays_exporter,whos_hot_cold_exporter}.py`
- **Calibration:** `ml/signals/mlb/best_bets_exporter.py:88-116` (BASE/RESCUE/TRACKING_ONLY tags)
- **Model deploy:** `cloudbuild-mlb-worker.yaml`, `gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_40f_20250928.cbm` (offending), `mlb_predictions.model_registry`
- **Retrain script:** `scripts/mlb/training/train_regressor_v2.py` (use this; NOT `ml/training/mlb/quick_retrain_mlb.py`)
- **Memory updated this session:** `~/.claude/projects/-home-naji-code-nba-stats-scraper/memory/exporter-pct-convention.md` + MEMORY.md index entry

---

## Glossary

- **CF HR (counterfactual hit rate):** Of the picks a filter blocked, what fraction would have hit if not blocked. Low (≤45%) = filter doing its job. High (≥55%) = filter blocking winners; demotion candidate.
- **Real signal count (`real_sc`):** Number of non-base, non-tracking signals firing on a pick. Used for rescue-eligibility gates.
- **TRACKING_ONLY signals:** Recorded for analysis but excluded from `real_sc`. Demoting a signal here is reversible.
