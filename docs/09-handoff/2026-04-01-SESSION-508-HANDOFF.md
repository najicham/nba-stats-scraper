# Session 508 Handoff — 2026-04-01 (Wednesday afternoon)

**Context:** Session 508 opened with 5 Explore agents studying the Session 507 open items,
then discovered a pick drought (0 picks March 30–April 1), diagnosed the root cause across
4 more agents (2 Opus + 2 Sonnet), executed a `weekly_retrain` CF deploy, and ran an ad-hoc
retrain anchored to Feb 28 that produced two governance-passing models awaiting user approval.

---

## What Happened This Session

### 1. `weekly_retrain` CF Deployed

The Session 507 TIGHT cap fix was in code but `weekly_retrain` is NOT in `cloudbuild-functions.yaml`
— it has its own `deploy.sh`. Without this session, Monday April 6 retrain would have fired with
the old blind-spot code.

- Deployed via `orchestration/cloud_functions/weekly_retrain/deploy.sh`
- Updated at `2026-04-01T14:53:04 UTC`, commit `fa22759`
- Verified `allTrafficOnLatestRevision: true`

### 2. Signal Graduation Blocked — N=1 at BB Level

Ran BQ queries for `book_disagree_over` and `sharp_consensus_under`. Both have **N=1 BB pick
all season** (not N≥30). The 5-season N=211/205 figures came from the BB simulator, not live
picks. Cannot graduate either signal until they accumulate 30+ live best-bets picks.

### 3. Pick Drought Diagnosed — 0 Picks March 30, 31, April 1

**8-agent investigation (5 explore + 4 strategy)** traced the drought to two compounding causes:

#### Root Cause A: Fresh models trained on March data (structural)
Models `lgbm_v12_noveg_train0126_0323` and `catboost_v12_noveg_train0126_0323` (Jan 26–Mar 23
training window) include 41% March data. March NBA data has lower outcome variance (load
management, tanking, stable rotations). This compresses predictions toward the mean, producing:
- Avg edge 1.21-1.30 vs 1.44-1.57 for prior models
- Only 7 predictions at edge 3+ per model (out of 144)
- 0 OVER picks at edge 5+, only 2 UNDER picks at edge 5+ (Brunson 5.6, Embiid 5.1)

Secondary contributor: `line_vs_season_avg` (feature 53) converges near zero in March as the
market becomes efficient, teaching the model to predict near the line. Flagged as architectural
issue in Session 476.

#### Root Cause B: No real signals fire for any edge pick
Investigated Brunson UNDER (edge 5.6, LGBM) specifically:
- `volatile_starter_under`: needs `points_std_last_10 > 8.0` — Brunson's is **6.58**. Fails.
- `line_drifted_down_under`: needs BettingPros movement [-0.5, -0.1) — `prop_line_delta = 0.0`. Fails.
- `extended_rest_under`: needs ≥ 4 rest days — NYK played March 31 (yesterday). 0 rest days. Fails.
- `home_under`: NYK is AWAY at Memphis today — Brunson is NOT at home. Fails.
- Result: `real_sc = 0` for Brunson. System is working correctly. The picks are legitimately not qualifying.

**Quality was NOT the issue** — all 302 predictions have `feature_quality_score = 96+` (well above
the 85 threshold). The Sonnet 2 agent incorrectly hypothesized quality_floor; BQ data confirmed all
clean AND dirty players have quality 96.7-96.8.

### 4. Ad-hoc Retrain: Both Models Passed Governance

Ran `./bin/retrain.sh --all --no-production-lines --train-end 2026-02-28` anchored to Feb 28.
Training window: Dec 27–Feb 21 (pure winter data, zero March). Eval window: Feb 22–28.

| Model | HR (all) | HR (edge 3+) | HR (edge 5+) | Vegas Bias | Result |
|-------|----------|--------------|--------------|------------|--------|
| `lgbm_v12_noveg_train1227_0221` | 59.95% | 71.29% (N=101) | 77.27% (N=22) | +0.30 | ✅ ALL PASS |
| `catboost_v12_noveg_train1227_0221` | 62.39% | 72.06% (N=68) | 88.89% (N=18) | +0.35 | ✅ ALL PASS |

Both registered in `model_registry` with `enabled=FALSE`. **Session ended without user approval
to enable** — the handoff doc is where this session stopped.

---

## Current System State

### NBA Fleet

| Model | State | Enabled | Training Window |
|-------|-------|---------|-----------------|
| `lgbm_v12_noveg_train0126_0323` | active | YES | Jan 26–Mar 23 (compressed, causing drought) |
| `catboost_v12_noveg_train0126_0323` | active | YES | Jan 26–Mar 23 (compressed, causing drought) |
| `lgbm_v12_noveg_train1227_0221` | active | **NO** | Dec 27–Feb 21 (clean winter, ready to enable) |
| `catboost_v12_noveg_train1227_0221` | active | **NO** | Dec 27–Feb 21 (clean winter, ready to enable) |

### Season Record (as of 2026-03-31)
- **Season: 108-76 (58.7%)**
- **March drought: 0 picks March 30–April 1** (3 consecutive days)
- **Edge 5+: 82-44 (65.1%)**

---

## Open Items (Priority Order)

### 1. IMMEDIATE: Enable New Models, Disable Old Ones (USER APPROVAL REQUIRED)

**Both new models passed all governance gates.** Enable to end the pick drought:

```bash
# Enable new models
bq query --project_id=nba-props-platform --use_legacy_sql=false \
  "UPDATE nba_predictions.model_registry SET enabled=TRUE WHERE model_id IN ('lgbm_v12_noveg_train1227_0221', 'catboost_v12_noveg_train1227_0221')"

# Disable old models (cascade disable)
python bin/deactivate_model.py lgbm_v12_noveg_train0126_0323 --dry-run
python bin/deactivate_model.py catboost_v12_noveg_train0126_0323 --dry-run
# Run without --dry-run if dry run looks correct

# Refresh worker model cache immediately (worker auto-refreshes every 4h)
./bin/refresh-model-cache.sh --verify

# Re-trigger Phase 5 + Phase 6 to generate picks with new models
# (Or wait for evening pipeline run)
```

**After enabling:** Verify picks appear for today (April 1) or tomorrow (April 2) by checking:
```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-04-01' GROUP BY 1,2 ORDER BY 1,2"
```

### 2. April 3 (Friday): `friday_over_block` Decision

Check CF HR after grading on Friday April 3. Demote if ≥ 55%:

```sql
SELECT filter_name, game_date, ROUND(cf_hr*100,1) as cf_hr_pct, n_graded
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date = '2026-04-03' AND filter_name = 'friday_over_block'
```

If CF HR ≥ 55% (N ≥ 5), manually write demotion to `filter_overrides`:
```sql
INSERT INTO `nba-props-platform.nba_predictions.filter_overrides`
  (filter_name, override_type, reason, cf_hr_7d, n_7d, triggered_at, triggered_by, active, demote_start_date, re_eval_date)
VALUES
  ('friday_over_block', 'demote_to_observation',
   'April 3 CF HR >= 55% — blocking profitable OVER picks',
   <cf_hr>, <n>, CURRENT_TIMESTAMP(), 'manual', TRUE, CURRENT_DATE(), DATE_ADD(CURRENT_DATE(), INTERVAL 14 DAY));
```

Previous CF HR was 87.5% (N=8) on March 27. Historical basis was 37.5%. Small-N contradiction.

### 3. April 6 (Monday): weekly_retrain Verification

CF deployed with TIGHT cap fix (commit `fa22759`, updated 14:53 UTC April 1). Should fire
automatically at 5 AM ET. Verify it ran:

```bash
gcloud functions logs read weekly-retrain --gen2 --region us-west2 \
  --project nba-props-platform --limit 30
```

Note: Monday's retrain will train Jan 25–Mar 22 (nearly identical to the drought models).
The Feb 28 anchor models we trained today are better — if they're enabled and performing,
consider whether Monday's retrain should also use a Feb 28 anchor (via manual override).

### 4. `home_under` — Watch Only, Do NOT Demote

41.4% HR (N=29) as of March 31 — variance. Health multiplier at 0.5x (COLD) is already
limiting its weight. Demoting to BASE_SIGNALS would cost 5-10 UNDER picks/day.
Session 483 demotion caused a 12-day drought. Zero structural failure modes.

### 5. Signal Graduation — Keep Accumulating

`book_disagree_over`: N=1 BB pick (need N≥30, HR≥60%). Keep in SHADOW.
`sharp_consensus_under`: N=1 BB pick (need N≥30, HR≥60%). Keep in SHADOW.

---

## Key Audit Findings This Session

| Finding | Implication |
|---------|-------------|
| `weekly_retrain` CF is NOT auto-deployed | Has own `deploy.sh`. Push to main does NOT update it. Must be manually deployed after code changes. |
| March training data compresses edge distribution | Any retrain with >30% March data will produce avg edge 1.21-1.30 — too low for picks. Use Feb 28 cutoff until post-season. |
| `line_vs_season_avg` (feature 53) survives v12_noveg | Flagged Session 476 as architectural issue — CatBoost reconstructs Vegas line via this feature. Post-season fix. |
| Quality floor NOT the drought cause | All predictions have quality 96+. Sonnet 2 agent misdiagnosed. The real issue is real_sc = 0 (no signals firing). |
| Brunson UNDER was away, not home | NYK is away_team_tricode in game 0022501003. `home_under` doesn't fire. real_sc = 0. |
| Signal graduation N from simulator ≠ BB-level N | `book_disagree_over` 5-season N=211 is from simulator. Live BB picks = 1. Graduation threshold is BB-level. |
| Monday retrain window barely changes | Apr 6 retrain → train Jan 25–Mar 22. Same March-heavy window. Same edge compression problem. Manual `--train-end 2026-02-28` override needed. |

---

## Session 508 Actions

| Action | Status |
|--------|--------|
| Deploy `weekly_retrain` CF with TIGHT cap fix | ✅ Done (14:53 UTC) |
| Diagnose pick drought | ✅ Done (8-agent investigation) |
| Ad-hoc retrain with Feb 28 anchor | ✅ Done — both models pass governance |
| Enable new models / disable old models | ⏳ Awaiting user approval |
| Signal graduation queries | ✅ Done — N=1, blocked |

---

## Quick Start for Next Session

```bash
# 1. Enable new models (USER MUST APPROVE FIRST)
bq query --project_id=nba-props-platform --use_legacy_sql=false \
  "UPDATE nba_predictions.model_registry SET enabled=TRUE WHERE model_id IN ('lgbm_v12_noveg_train1227_0221', 'catboost_v12_noveg_train1227_0221')"

# 2. Disable old drought models
python bin/deactivate_model.py lgbm_v12_noveg_train0126_0323
python bin/deactivate_model.py catboost_v12_noveg_train0126_0323

# 3. Refresh model cache
./bin/refresh-model-cache.sh --verify

# 4. Check picks flowing
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT game_date, recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 1 GROUP BY 1,2 ORDER BY 1,2"

# 5. Morning steering
/daily-steering
```
