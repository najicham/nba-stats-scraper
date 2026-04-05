# Session 514 Handoff — Off-Season Plan, MLB Pipeline Fixes, Season Analysis

**Date:** 2026-04-05
**Focus:** Comprehensive off-season plan (3-agent reviewed), MLB pipeline resurrection, season-phase walk-forward analysis, aggregator improvements
**Commits:** `dea0c66d` (aggregator + cost + plan), `a4be0d7d` (MLB fixes + training anchor)

---

## What Was Done This Session

### 1. NBA Aggregator Improvements

- **Reverted `under_low_rsc` from ≥3 to ≥2** at edge<5 — Session 512's tightening was based on N=7 from one catastrophic day
- **Added solo high-conviction UNDER rescue** at edge 5+ — `volatile_starter_under`, `hot_3pt_under`, `sharp_line_drop_under` can stand alone with real_sc=1
- **Graduated `book_disagree_over`** from SHADOW_SIGNALS — 79.6% HR (N=211) 5-season. N=1 BB after 5 months; too rare to wait for N≥30 live
- **Graduated `sharp_consensus_under`** from SHADOW_SIGNALS + added to UNDER_SIGNAL_WEIGHTS (weight 2.0) — 69.3% HR (N=205) 5-season, consistent 64-73%
- **Algorithm version:** `v514_rsc_revert_solo_under_rescue`

### 2. Off-Season Plan (3-Agent Reviewed)

Created comprehensive plan at `docs/08-projects/current/2026-offseason-plan/00-SEASON-RETROSPECTIVE-AND-NEXT-SEASON-PLAN.md`

**Research phase (3 agents):** NBA season learnings catalog, MLB system audit, infrastructure/ops review
**Review phase (3 agents):** Strategy critic, technical feasibility, data/evidence audit

**Key corrections from review:**
- Quantile regression demoted from "highest promise" to Option 5 (failed 6 prior times)
- Classification model removed (AUC 0.507 = infeasible)
- Season record: 108-76 (58.7%) not 104-70
- MLB ROI: 12.8% not 36.2% (model version mix-up)
- Signal/filter system (+13.7pp) promoted as primary investment target

### 3. Season-Phase Walk-Forward Analysis (CRITICAL FINDING)

**Late-season degradation is NOT universal across seasons.**

| Season | Mid HR | Late HR | Endgame HR | Late Avg Edge |
|--------|--------|---------|------------|---------------|
| 2021-22 | 63.4% | 63.9% | 64.2% | 4.14 |
| 2022-23 | 62.2% | 63.5% | 65.9% | 4.16 |
| 2023-24 | 63.2% | 61.7% | 62.2% | 4.04 |
| 2024-25 | 63.3% | 61.9% | 61.5% | 4.09 |
| **2025-26** | **55.6%** | **51.3%** | **52.8%** | **2.46** |

Prior seasons: 62-64% HR through April. Edge actually INCREASES late season. **2025-26 was broken from day one** (Early = 55.9% vs historical 68-70%).

**Implications:**
- No architecture overhaul needed (quantile regression, classification)
- Auto training anchor + edge-based auto-halt is the right fix
- Seasonal dormancy as permanent rule is unnecessary

### 4. Dormancy ROI Analysis

- **Peak P/L: +31.07 units (Feb 22)**. March erased 25.6% of it.
- **Optimal auto-halt trigger:** 7-day avg edge < 5.0 AND edge-5+ pick rate < 50%
- In normal seasons: trigger never fires. In 2025-26: fires late Feb → saves +8 units.

### 5. Auto Training Anchor

Added `cap_to_pre_late_season()` to `weekly_retrain/main.py`:
- Caps training window at Feb 28 to prevent March data contamination
- Composes with existing TIGHT market cap: `min(late_cap, tight_cap)`
- Deployed to `weekly-retrain` CF via push (auto-deploy trigger)

### 6. Cost Optimization (P0)

- **BQ partition filters fixed** on `streaks_exporter.py` (180-day bound) and `player_season_exporter.py` (proper date bounds instead of EXTRACT)
- **Tiered canary monitoring** — added `--tier critical|routine|all` argument. 14 critical (15-min), 15 routine (60-min). ~48% fewer BQ queries.
- Schedulers already wired: `CANARY_TIER=critical` (15min) and `CANARY_TIER=routine` (60min)

### 7. MLB Pipeline Resurrection (Was Dead 9 Days)

**5 cascading failures found and fixed:**

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| 98.4% predictions BLOCKED | `player_lookup` format mismatch (underscore vs concatenated) | `_normalize_lookup()` in `pitcher_loader.py` |
| Phase 3 analytics dead since Mar 27 | Wrong trigger mapping keys (`mlb_pitcher_stats` vs `mlbapi_pitcher_stats`) | Fixed keys in `main_mlb_analytics_service.py` |
| Phase 4 never triggered | No Phase 3 completion notification | Added `publish_phase3_completion()` |
| Grading silently failing | `game_pk` vs `game_id` column mismatch + type mismatch for void detection | Fixed column names + CAST in grading processor |
| Events scraper failing | Parameter name `date` vs `game_date` + broken deploy scripts | Fixed deploy scripts, scraper works with `game_date` |

**Additional fixes:** Null guard on `check_download_status()` in 6 MLB Odds API scrapers.

**Deployed:** MLB scrapers, analytics, grading. MLB prediction worker auto-deploy trigger created.

**Backfilled:** Phase 3 analytics for Mar 28 - Apr 5 (210 pitcher game summaries).

**Cannot backfill:** Historical Odds API events/props (API doesn't serve past data). Tomorrow's pipeline should work end-to-end.

### 8. MLB Auto-Deploy Trigger

Created `deploy-mlb-prediction-worker` Cloud Build trigger:
- Watches `predictions/mlb/**`, `shared/**`, `ml/**`
- Updated `cloudbuild-mlb-worker.yaml` with deploy step, AR migration, SHA tagging

### 9. MLB Daily Performance Script

Created `bin/monitoring/mlb_daily_performance.py` — 5 BQ queries for daily pick volume, graded performance, edge distribution, cumulative totals.

---

## Current System State

### NBA
- **Season: 108-76 (58.7%)**, pick drought Day 6
- **4 models enabled**, all producing avg edge 1.3-1.5 (below 3.0 floor)
- **Auto training anchor deployed** — `weekly-retrain` CF will cap at Feb 28
- **Algorithm v514** — reverted under_low_rsc, solo UNDER rescue, 2 signals graduated

### MLB
- **Pipeline fixed and deployed** — should work end-to-end starting tomorrow
- **Analytics backfilled** (Mar 28 - Apr 5)
- **Historical props unavailable** (Odds API limitation) — live going forward only
- **Events working** for today (5) and tomorrow (12)

---

## Monday April 6 Risks

- **`weekly-retrain` CF fires at 5 AM ET** — now has `cap_to_pre_late_season()`. Will cap training to Feb 28. Verify it produces reasonable models.
- **MLB daily pipeline** — first full end-to-end test with all fixes. Verify: events → props → Phase 2 → Phase 3 → Phase 4 → predictions → grading.
- **Auto-deploy trigger** — first test on next push to main. Verify MLB worker updates.

---

## Quick Start for Next Session

```bash
# 1. Check if MLB pipeline worked overnight
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT game_date, COUNT(*) as predictions,
  COUNTIF(predicted_strikeouts IS NOT NULL) as with_predictions
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= '2026-04-05'
GROUP BY 1 ORDER BY 1"

# 2. Check if NBA retrain produced good models
./bin/model-registry.sh list

# 3. Check events and props data for today
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT table_id, row_count, TIMESTAMP_MILLIS(last_modified_time) as modified
FROM mlb_raw.__TABLES__
WHERE table_id IN ('oddsa_mlb_events', 'oddsa_pitcher_props')
ORDER BY table_id"

# 4. Run MLB daily performance
PYTHONPATH=. python bin/monitoring/mlb_daily_performance.py

# 5. Implement edge-based auto-halt (Week 2 item)
# Trigger: 7d avg edge < 5.0 AND edge-5+ pick rate < 50%
```

---

## Key Files Changed

| Purpose | File |
|---------|------|
| BB aggregator (all signal/filter logic) | `ml/signals/aggregator.py` |
| Algorithm version | `ml/signals/pipeline_merger.py` |
| Auto training anchor | `orchestration/cloud_functions/weekly_retrain/main.py` |
| MLB prediction loader (player_lookup fix) | `predictions/mlb/pitcher_loader.py` |
| MLB Phase 3 analytics (trigger mapping + completion) | `data_processors/analytics/mlb/main_mlb_analytics_service.py` |
| MLB grading (column fixes) | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` |
| MLB auto-deploy | `cloudbuild-mlb-worker.yaml` |
| MLB daily perf monitoring | `bin/monitoring/mlb_daily_performance.py` |
| Tiered canary | `bin/monitoring/pipeline_canary_queries.py` |
| BQ partition fixes | `data_processors/publishing/streaks_exporter.py`, `player_season_exporter.py` |
| MLB deploy scripts | `bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`, `bin/phase6/deploy/mlb/deploy_mlb_grading.sh` |
| MLB scraper null guards | `scrapers/mlb/oddsapi/mlb_*.py` (6 files) |
| Off-season plan | `docs/08-projects/current/2026-offseason-plan/00-SEASON-RETROSPECTIVE-AND-NEXT-SEASON-PLAN.md` |

---

## Strategic Conclusions (from 6-agent analysis)

1. **2025-26 was uniquely broken** — not a seasonal dynamics problem. Prior seasons maintain 62-64% HR through April.
2. **The signal/filter system IS the product** — +13.7pp above raw model. Invest here, not model architecture.
3. **Edge-based auto-halt** (7d avg edge < 5.0) catches the problem without permanent dormancy.
4. **Auto training anchor** prevents March data contamination — the root cause of 2025-26's collapse.
5. **MLB pipeline was silently dead for 9 days** — 5 cascading bugs. All fixed, should work tomorrow.
6. **Quantile regression has failed 6 times** — the IQR approach is untested but only worth pursuing if walk-forward shows consistent late-season degradation (it doesn't).
