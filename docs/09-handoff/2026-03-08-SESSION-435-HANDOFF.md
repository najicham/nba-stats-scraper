# Session 435 Handoff — League Macro Monitor + OVER Edge Floor + Overconfidence Analysis

**Date:** 2026-03-08
**Session:** 435
**Status:** Complete. 1 new monitor, 1 filter change, 3 deploys, deep overconfidence analysis.

---

## What Was Done

### 1. League Macro Daily Monitor (NEW)

Built a daily league-level trend monitor that tracks market efficiency, scoring environment, and system health.

**Files created (2):**
- `ml/analysis/league_macro.py` — Computation script (3 metric groups: MAE, scoring, BB HR)
- `schemas/bigquery/nba_predictions/league_macro_daily.sql` — BQ table schema

**Files modified (3):**
- `orchestration/cloud_functions/post_grading_export/main.py` — Auto-computes after grading (step 5c)
- `.claude/skills/daily-steering/SKILL.md` — New "League Macro Trends" section (Step 2.5a)
- `CLAUDE.md` — Added table reference, monitoring script, query example

**BQ table:** `nba_predictions.league_macro_daily` — 45 rows backfilled (Jan 15 - Mar 7)

**Metrics tracked:**

| Metric | What It Tells You |
|--------|------------------|
| `vegas_mae_7d` | Market tightness (< 4.5 = TIGHT) |
| `model_mae_7d` / `mae_gap_7d` | Model vs Vegas accuracy gap |
| `league_avg_ppg_7d` | Scoring environment |
| `avg_edge_7d` | Edge supply (shrinking = fewer opportunities) |
| `bb_hr_7d` / `bb_n_7d` | Best bets rolling performance |
| `market_regime` | TIGHT / NORMAL / LOOSE |

**Key trend finding:** Vegas MAE dropped from 5.2 to 4.6 (approaching TIGHT threshold) while model edge grew from 2.3 to 3.15 — model is diverging from lines but not converting. Training window artifact, self-correcting by mid-March.

### 2. OVER Edge Floor Raised 3.0 → 4.0

**Root cause:** BB OVER edge 3-4 was **33.3% HR (4-12)** — catastrophic. 8 of 12 were signal-rescued picks that bypassed the floor and lost.

**Analysis (3 agents validated):**
- Floor at 4.0: 68.3% HR (N=60) — **+5.8pp improvement**
- Floor at 5.0: 68.5% HR (N=54) — only +0.2pp more but kills volume to ~1 pick/day
- Edge 3-4 OVER was never profitable at BB level since introduced (Feb-Mar: 4-12)
- Raw predictions at edge 3-4 were 58% HR — the BB signal/rescue stack was selecting the worst candidates

**File:** `ml/signals/aggregator.py` — changed `over_floor = 3.0` to `over_floor = 4.0`, updated log message

### 3. Model Overconfidence Investigation (Research, No Code Changes)

Three agents analyzed the model bias from multiple angles:

**Finding 1: Model predicts below Vegas lines (gap = -2.26 in March)**
- Model-vs-line went from +0.17 (Jan) to -2.26 (Mar) — steady deterioration
- 75% of all predictions are UNDER (was 43% in January)
- This is a **training window artifact** — 56-day window includes ASB scoring dip

**Finding 2: UNDER edge is flat at ~54% (edge 3-7)**
- Raw UNDER HR bounces 51.9-57.3% across all edge buckets — no calibration
- At 7.0+: 88.2% HR but N=17 (too small to act on)
- In BB: signal/filter stack adds +10-18pp → UNDER ranking by signal quality is validated

**Finding 3: Residual bias is asymmetric but not unidirectional**
- OVER residual: +2.24 (model over-predicts OVER candidates)
- UNDER residual: -2.64 (model under-predicts UNDER candidates)
- Calibration spread problem, not simple under-prediction

**Recommendation:** Monitor — the 56-day window will slide past ASB by mid-March. If model-vs-line gap doesn't narrow below -1.0 by March 22, investigate retrain with higher Vegas weight (0.25x) or shorter window (42d).

### 4. Deployments

| Service | Status | Purpose |
|---------|--------|---------|
| nba-scrapers | Deployed | ESPN projections scraper (first run 14:45 UTC Mar 8) |
| nba-grading-service | Deployed | Stale deploy refreshed (BDL retirement + champion model) |
| validation-runner | Skipped | Cloud Function, not Cloud Run |

### 5. BB HR Query Fix (Discovery)

Found that `signal_best_bets_picks.system_id` is the sourcing model (e.g., `lgbm_v12_noveg_vw015_train1215_0208`), NOT `catboost_v12`. All BB HR queries must join on `bb.system_id = pa.system_id`, not hardcode `catboost_v12`. This was causing BB HR queries to return 0 matches for recent dates.

---

## Commits

```
4f7fb25a docs: Session 435b handoff — league macro + post_grading integration + docs
9a6891bc fix: OVER edge floor raised 3.0 → 4.0 — BB OVER 3-4 was 33.3% HR
```

---

## Files Changed

```
# League Macro Monitor (new)
ml/analysis/league_macro.py                              — NEW: Computation script
schemas/bigquery/nba_predictions/league_macro_daily.sql   — NEW: BQ table schema

# Integration
orchestration/cloud_functions/post_grading_export/main.py — Step 5c: league macro computation
.claude/skills/daily-steering/SKILL.md                    — Step 2.5a: League Macro Trends section
CLAUDE.md                                                 — Table reference, query, monitoring script

# OVER Edge Floor
ml/signals/aggregator.py                                  — over_floor 3.0 → 4.0
```

---

## System State

| Item | Status |
|------|--------|
| Fleet | 5 HEALTHY, 1 WATCH, 1 DEGRADING, 7 BLOCKED |
| BB HR (7d) | 56.0% (N=25) — recovering |
| Market Regime | NORMAL (Vegas MAE 4.77, approaching TIGHT) |
| Prediction Volume | Mar 7: 75 players. Mar 8 will be first test of quality fixes (~150+ expected) |
| OVER Edge Floor | 4.0 (raised from 3.0) |
| ESPN Scraper | Deployed, scheduler active, first run Mar 8 14:45 UTC |
| League Macro | 45 dates backfilled, auto-populates post-grading |
| Auto-disable | lgbm_vw015 + xgb_s42 will be disabled at 11 AM ET (both BLOCKED) |
| Tests | 70 aggregator tests pass |

---

## What to Do Next

### Priority 1: Verify Mar 8 Prediction Volume
Both quality fixes (required_default_count + FEATURE_COUNT cap) deployed. Expect ~150+ players.
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-08' AND system_id = 'catboost_v12'
GROUP BY 1
```

### Priority 2: Monitor OVER Edge Floor 4.0 Impact
First pipeline run with the new floor. Check if OVER picks are higher quality:
```sql
SELECT game_date, recommendation, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-08'
GROUP BY 1, 2 ORDER BY 1, 2
```

### Priority 3: Verify ESPN Scraper First Run
Expected: ~365 player rows at 14:45 UTC.
```sql
SELECT game_date, COUNT(*) as players
FROM nba_raw.espn_projections WHERE game_date >= '2026-03-08'
GROUP BY 1
```

### Priority 4: Monitor Model-vs-Line Gap
Check `league_macro_daily` — if `mae_gap_7d` doesn't trend toward 0 by Mar 15, consider retrain.
```sql
SELECT game_date, mae_gap_7d, avg_edge_7d, bb_hr_7d, market_regime
FROM nba_predictions.league_macro_daily
WHERE game_date >= '2026-03-08' ORDER BY game_date
```

### Priority 5: Retrain Experiment (When Ready)
If model-vs-line gap persists, experiment with:
- Higher Vegas weight (0.25x vs current 0.15x)
- Shorter training window (42d vs current 56d)
- Use `/model-experiment` to train as shadow

### Priority 6: Future Work
- **Pick up retrain `catboost_v9_low_vegas`** — 27d stale, approaching 30d
- **Monitor blowout_risk_under filter** — now active, check if blocking bad UNDER picks
- **Raise `MIN_SOURCES` to 2** after ESPN validated (~1 week shadow)
- **catboost_v12 edge 5+ investigation** — 47.6% HR at edge 5+ (N=21)

---

## Key Learnings

1. **BB HR queries must join on `bb.system_id = pa.system_id`** — not hardcode `catboost_v12`. Multi-model BB picks come from various models.

2. **OVER edge floor lowering (Session 419) was premature.** Raw edge 3-4 OVER predictions are 58% HR, but the BB signal/rescue stack selects the worst candidates (33% HR). The fix is raising the floor, not fixing signal selection.

3. **Model-vs-Vegas divergence is the real health metric,** not raw MAE. The model's absolute accuracy was OK, but its divergence from lines (-2.26) caused extreme UNDER tilt and overconfidence.

4. **Training window composition matters more than window length.** The 56-day window including 23% ASB data is causing systematic bias that a longer/shorter window wouldn't fix — only time (sliding past ASB) resolves it.
