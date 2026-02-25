# Session 342 Handoff — Model Health Diagnosis & Morning Operations

**Date:** 2026-02-25
**Focus:** Morning operations checklist, model portfolio analysis, model health root cause diagnosis, trends-tonight automation.

---

## What Was Done

### 1. Morning Operations (All Passed)

- **minScale:** All 5 critical services confirmed at minScale=1 (cloudbuild fix survived overnight auto-deploys)
- **Deployment drift:** All 16 services up to date, zero drift
- **status.json:** healthy - No games currently active
- **phase6-export BUILD_COMMIT:** d939884 (latest commit)

### 2. Daily Steering Report

**Model Health (as of 2026-02-24):**
- Only 2 models in WATCH (v12_train1102: 57.1%, v12_noveg_train1102: 55.6%)
- 1 DEGRADING (v9_low_vegas: 53.8%)
- Everything else BLOCKED
- **V12 base edge 5+ HR: 37.5% — actively losing money at high edge**
- v9_low_vegas carrying best bets at edge 5+ (64.7% HR, N=17)

**Best Bets:** 66.7% 7d, 65.3% 30d (32-17) — still strong despite model issues

**Market Regime:** GREEN — edges expanding post All-Star, 1.223 compression ratio

**Signals:** 1 HOT (blowout_recovery), 2 COLD (3pt_bounce, rest_advantage_2d)

### 3. Reconciliation — Feb 24

- 11/11 games processed, all final
- Cross-model: All 19 models at 144 predictions (perfect parity)
- Enrichment: 100% enriched
- Feature quality: 38.3% ready (low — post All-Star break, expected to normalize)
- **Best bets: 1-1 (50%)** — Embiid UNDER WIN, Zion UNDER LOSS. Only 2 picks for 11-game slate.

### 4. Model Portfolio Analysis — CRITICAL FINDING

**Registry vs Reality:**
- **6 models** registered and enabled in model registry
- **19 system_ids** actively producing predictions
- **13 zombie models** not managed by registry, still running from old deployments

**Best bets pick sourcing (30d):** Only 4 families have sourced picks: v12_mae (3), v9_low_vegas (1), v12_q45 (1), v12_q43 (1). The v9 quantile models (v9_q43, v9_q45) have contributed **zero** best bets picks.

### 5. Code Changes (Uncommitted)

| File | Change | Status |
|------|--------|--------|
| `orchestration/cloud_functions/phase5_to_phase6/main.py` | Added `'trends-tonight'` to TONIGHT_EXPORT_TYPES | Ready to commit |
| `data_processors/publishing/best_bets_all_exporter.py` | Changed `ultra_tier` → `is_ultra` field (bool normalization) | From prior session, review needed |
| `orchestration/cloud_functions/post_grading_export/main.py` | Added best-bets/all.json re-export after grading | From prior session, review needed |

**Only the phase5_to_phase6 change is from this session.** The other two appear to be from a prior session (Session 342 diagnosis work).

### 6. Model Health Diagnosis Document

Created `docs/08-projects/current/model-health-diagnosis-session-342/00-DIAGNOSIS.md` with comprehensive root cause analysis:

**Root Cause:** Structural UNDER bias. All models predict 1.0–1.6 pts below Vegas. 77-89% of predictions are below Vegas → nearly all edge 3+ picks are UNDER recommendations.

**Key Findings:**
- CatBoost MAE/Huber loss creates mean-regression bias (structural, not a bug)
- Vegas is more accurate than our model (lower MAE every week for 6 weeks)
- `noveg` and `low_vegas` variants outperform because they don't anchor on Vegas
- Q43 quantile models make bias **worse** (predicting even lower)

---

## What Was NOT Done (Action Items for Next Session)

### Priority 1: Decommission Zombie Models
13 unmanaged system_ids producing predictions but not in registry. These pollute cross-model scoring and waste compute. Need to:
1. Identify which system_ids are zombies in the prediction worker config
2. Remove them from the model manifest or disable in registry
3. Verify cross-model scorer only uses registered models

**Key question:** Are zombies contributing to best bets via the multi-model query? The `supplemental_data.py` query (lines 87-140) selects the highest-edge prediction per player across ALL CatBoost families. If a zombie model has the highest edge, it gets selected.

### Priority 2: Retrain v9_low_vegas
- Currently DEGRADING at 53.8% 7d HR, 19d stale
- **This is the best-bets workhorse** — 64.7% edge 5+ HR (N=17)
- Training window should end ~Feb 24 (42-day rolling)
- Use `/model-experiment` to retrain

### Priority 3: Implement Diagnosis Recommendations
From the diagnosis doc, in priority order:

1. **Direction-aware filter** (config change, immediate):
   - Block UNDER edge 3-4 picks
   - Only allow UNDER edge 5+
   - Allow OVER edge 3+ (rare but 60-67% HR when they exist)
   - Location: `ml/signals/aggregator.py` edge floor logic

2. **Fresh retrain of all families** through Feb 24

3. **Train Q55/Q57 quantile models** — counteract UNDER bias by predicting above median instead of Q43 (which makes bias worse)

4. **Evaluate noveg as default architecture** — `noveg` variants consistently outperform full-Vegas variants

### Priority 4: Fix Scheduler Jobs (P3)
- `self-heal-predictions`: DEADLINE_EXCEEDED at 900s. Service exists, IAM correct. Coordinator takes too long.
- `analytics-quality-check-morning`: INTERNAL error in function code. Investigate logs.

### Priority 5: tonight.json Build Commit
- Currently shows `build_commit: local` — the automated trigger hasn't run yet
- The `trends-tonight` addition to TONIGHT_EXPORT_TYPES (uncommitted) will fix this once deployed
- Commit and push the phase5_to_phase6 change

---

## Key Architecture Context for Best Bets

**Selection pipeline** (for understanding which models matter):
1. `supplemental_data.py` queries ALL CatBoost families, selects highest-edge prediction per player
2. `aggregator.py` filters: edge >= 5.0, negative filters, min 2 signals
3. Ranks by edge DESC, returns all qualifying picks
4. Picks stored in `nba_predictions.signal_best_bets_picks`

**Critical insight:** The multi-model query picks the model with the HIGHEST EDGE for each player. Zombie models participate in this selection. A zombie with a bad prediction but high edge could source a losing best bet.

**Model family classification:** `shared/config/cross_model_subsets.py` (lines 28-115) maps system_id → family

---

## Decisions Pending (User Direction Needed)

1. **V9 Q43/Q45 (30d stale, BLOCKED, 0 best bets picks):** Decommission entirely? They contribute nothing to best bets.
2. **V12 base at 37.5% edge 5+ HR:** Exclude from multi-model selection? It's actively harmful.
3. **Direction-aware filter:** Should UNDER edge 3-4 be blocked? Data supports it (OVER 60-67% HR, UNDER ~37-43% at those edges).
4. **Q55/Q57 models:** Worth training to counteract UNDER bias? Diagnosis doc recommends it.

---

## Quick Start for Next Session

```bash
# 1. Commit the trends-tonight change
git add orchestration/cloud_functions/phase5_to_phase6/main.py
git commit -m "feat: add trends-tonight to TONIGHT_EXPORT_TYPES for automated export"

# 2. Review and commit the other 2 modified files if they look correct
git diff data_processors/publishing/best_bets_all_exporter.py
git diff orchestration/cloud_functions/post_grading_export/main.py

# 3. Push to deploy
git push origin main

# 4. Read the diagnosis doc
cat docs/08-projects/current/model-health-diagnosis-session-342/00-DIAGNOSIS.md

# 5. Start retrain cycle
/model-experiment  # retrain v9_low_vegas first

# 6. Investigate zombie models
bq query --use_legacy_sql=false --project_id=nba-props-platform <<'EOF'
SELECT system_id, 'REGISTERED' as status FROM `nba-props-platform.nba_predictions.model_registry` WHERE enabled = TRUE
UNION ALL
SELECT DISTINCT system_id, 'PREDICTING' FROM `nba-props-platform.nba_predictions.player_prop_predictions` WHERE game_date >= CURRENT_DATE() - 3
ORDER BY system_id
EOF
```

---

## Files Modified This Session

| File | Lines | Description |
|------|-------|-------------|
| `orchestration/cloud_functions/phase5_to_phase6/main.py:82` | +1 | Added `'trends-tonight'` to export types |

## Files to Reference

| File | Why |
|------|-----|
| `docs/08-projects/current/model-health-diagnosis-session-342/00-DIAGNOSIS.md` | Full root cause analysis of model health crisis |
| `ml/signals/aggregator.py` | Best bets selection logic, edge floor at line 87 |
| `ml/signals/supplemental_data.py:87-140` | Multi-model query — selects highest edge per player |
| `shared/config/cross_model_subsets.py:28-115` | Model family classification |
| `data_processors/publishing/signal_best_bets_exporter.py` | Main best bets exporter |
