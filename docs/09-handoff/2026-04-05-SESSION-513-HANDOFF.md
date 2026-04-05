# Session 513 Handoff — Fixes, DNP Voiding, 8-Agent Brainstorm

**Date:** 2026-04-05
**Focus:** Filter demotions, signal cleanup, DNP voiding, MLB backfill, brainstorm for end-of-season strategy
**Commits:** `8f200196` (main fixes), `29ef9804` (all.json voiding)

---

## What Was Done This Session

### 1. NBA Signal/Filter Fixes
- **`friday_over_block` demoted** — wrote to `filter_overrides` table. CF HR 85.7% (12/14 winners blocked since March 1). 30-day expiry.
- **`extended_rest_under` moved to SHADOW_SIGNALS** — 28.6% season HR (N=7), 25% 7d HR. Was inflating `real_sc` on bad UNDER picks.
- **Reviewed blacklist** — 78.6% CF HR but low volume (14 picks). Stars being blacklisted (Brunson, Mitchell, KAT, Bam) are actually profitable full-season. No structural change needed — low impact.

### 2. DNP Voiding Added to Best Bets
- Added `is_voided BOOLEAN` and `void_reason STRING` columns to `signal_best_bets_picks` table
- Added third pass in `backfill_signal_best_bets()` (post_grading_export) — detects DNP via `player_game_summary.is_dnp` and voids picks
- Fixed `best_bets_all_exporter.py` to COALESCE voiding from both `prediction_accuracy` (PA JOIN) and `signal_best_bets_picks` (direct) — handles cases where PA JOIN fails due to recommendation/line mismatch
- Backfilled all 14 historical DNP picks (KAT, Holmgren, Cunningham, Embiid, Anunoby, etc.)
- KAT Apr 3 now shows `result=VOID, reason=DNP` on frontend

### 3. BB Grading Gap Investigated
Found the root cause of ungraded BB picks:
- **Line movers:** When line moves after BB pick, grading dedup (`ORDER BY created_at DESC`) keeps the latest prediction (different line/recommendation). The BB pick's JOIN keys don't match. Fixed by the existing second-pass fallback in `backfill_signal_best_bets()` which grades directly from `player_game_summary`.
- **DNP:** Players who didn't play have `points IS NULL` so the fallback can't grade them. Fixed by the new third-pass DNP voiding.
- 13 played-but-ungraded picks were already correctly handled by the fallback (6-7 record). Only the 14 DNP picks needed the new voiding pass.

### 4. MLB Pipeline Fixes
- **`bp_events.py` NoneType crash fixed** — guard on `check_download_status()` when `raw_response is None`. Raises `DownloadDataException` (caught by retry in `bp_mlb_player_props.py`).
- **MLB path extractor fixed** — `MLBStatsAPIExtractor.PATTERN` now matches `box-scores` and `umpire-assignments`.
- **MLB pitcher stats backfilled** — Scraped 8 dates (Mar 28–Apr 4) via Cloud Run, processed 833 records directly to `mlb_raw.mlbapi_pitcher_stats`.
- **MLB Phase 2 registry mystery**: `mlb-stats-api/box-scores` exists in code (line 205 of `main_processor_service.py`) but NOT in the deployed container. Cloud Build trigger `deploy-nba-phase2-raw-processors` hasn't fired since March 28. Manually rebuilt the image from HEAD — still missing. **Unresolved.** Worked around by processing directly via Python.

### 5. System Review (5 parallel agents)
- All 4 NBA models producing predictions but avg edge 1.13-1.54 (need 3+)
- 0 BB picks for April 5 despite 11-game slate
- Both March-trained models BLOCKED by decay detection
- Feb-anchored models also producing compressed edges (not the fix we hoped)
- MLB: pitcher stats backfilled, bp_events still crashing on BettingPros API returning None
- All Cloud Run services healthy, zero deployment drift
- `filter_overrides` table was empty before our friday_over_block demotion

---

## Current System State

### NBA Pick Drought (Day 6)
- **April 1–5:** 0, 2, 2, 0, 0 picks. Season going silent.
- **Season record:** 104-70 (59.8%). Jan 73.1%, Feb 56.3%, Mar 47.4%.
- **Root cause:** All 4 models produce avg edge 1.3-1.5. Even Feb-anchored models are compressed.
- **Edge distribution today (Apr 5):** 660 predictions, 39 at edge 3+, 1 at edge 5+.

### Enabled Models
| Model | Train Window | Avg Edge | Edge 3+ | Decay State |
|-------|-------------|----------|---------|-------------|
| catboost_v12_noveg_train0126_0323 | Jan 26–Mar 23 | 1.32 | 9 | BLOCKED |
| lgbm_v12_noveg_train0126_0323 | Jan 26–Mar 23 | 1.31 | 11 | BLOCKED |
| catboost_v12_noveg_train1227_0221 | Dec 27–Feb 21 | 1.13 | 4 | New (no state) |
| lgbm_v12_noveg_train1227_0221 | Dec 27–Feb 21 | 1.54 | 15 | New (no state) |

### Edge HR by Bucket (March–April)
| Edge Bucket | Actionable | HR | Verdict |
|-------------|-----------|-----|---------|
| 5+ | 733 | 50.5% | Barely profitable |
| 3-5 | 2,049 | 52.7% | Marginal |
| 2-3 | 797 | 46.7% | **Losing money** |
| 1-2 | 1,377 | 49.2% | Coin flip |

### Filter CF HRs (Top Winners-Blocked, Since March 1)
| Filter | CF HR | N | Status |
|--------|-------|---|--------|
| `friday_over_block` | 85.7% | 14 | **DEMOTED this session** |
| `high_skew_over_block_obs` | 88.9% | 9 | Observation (don't promote) |
| `bench_under_obs` | 81.3% | 32 | Observation (don't promote) |
| `blacklist` | 78.6% | 14 | Dynamic, low volume |
| `high_spread_over_would_block` | 63.6% | 33 | Getting worse |
| `over_edge_floor` | 54.2% | 107 | Borderline — 5-season says keep |

---

## 8-Agent Brainstorm Summary

### Immediate Actions (Do First)

1. **Revert `under_low_rsc` from ≥3 back to ≥2 at edge<5**
   - Session 512 tightened based on N=7 from one catastrophic day (March 8)
   - 5-season simulator shows UNDER at edge 3-5 is 56-58% HR
   - This is the single biggest UNDER volume blocker right now
   - File: `ml/signals/aggregator.py` line ~1295
   - Risk: Medium. The March 8 data was cherry-picked.

2. **Add signal rescue exemption for solo high-conviction UNDER signals**
   - At edge 5+, allow `real_sc == 1` if the signal is `volatile_starter_under`, `hot_3pt_under`, or `sharp_line_drop_under`
   - These are cross-season validated (62.5%, 62.5%, 87.5% HR)
   - Mirrors what signal rescue already does for OVER (HSE bypass)
   - File: `ml/signals/aggregator.py` in the `under_low_rsc` block

3. **Promote `high_spread_over_would_block` to hard block**
   - Spread ≥ 7 OVER = 47% HR. Blowout rate 38.5% in April.
   - Already wired in aggregator, just needs the observation guard removed
   - File: `ml/signals/aggregator.py` lines 923-931

### This Week (Model/Market Alternatives)

4. **Quantile regression models** (highest-potential alternative)
   - Train CatBoost with `loss_function='Quantile:alpha=0.25/0.50/0.75'`
   - Edge = "entire IQR on one side of line" — structurally immune to mean convergence
   - Same features, same pipeline, new scoring logic
   - Use `/model-experiment` skill to test

5. **Market-consensus UNDER signal** (model-independent)
   - `line_dropped ≥ 1.5 AND multi_book_std < 0.5` = sharp money + book agreement
   - Pure market signal, doesn't depend on model accuracy
   - `sharp_line_drop_under` is already 72.4% HR — conditioning on low std should improve it

6. **Stale line fade** (market exploitation)
   - Identify soft-book outliers in multi-book data (BettingPros)
   - Bet WITH sharp consensus, against the laggard book
   - `book_disagreement` at 93% HR may be this pattern already

7. **Season-phase walk-forward** (diagnostic)
   - Slice 5-season data by early/mid/late/endgame phases
   - Quantify exactly when the model breaks and by how much
   - Uses existing `data_loader.py` infrastructure, ~100 lines
   - **Do this first** — it validates/refutes all other ideas

### Strategic Decision

8. **Go dormant or pivot to playoffs/MLB**
   - Protect the 59.8% season record — publishing 0-1 picks/day at 41% HR destroys it
   - Add "System paused for end of regular season" to frontend
   - Redirect engineering to playoff-specific strategy (rotations tighten, no load management)
   - Run NBA pipeline in shadow mode for data collection
   - MLB pipeline is launching — redirect user attention

### Next Season Architecture

9. **Auto training anchor** — `cap_to_pre_late_season()` in `quick_retrain.py`
   - Prevents future March-data contamination automatically
   - Pattern: copy `cap_to_last_loose_market_date()`, add season-end awareness

10. **Playoff seeding pressure features** (f57/f58)
    - `games_back`, `clinched_playoff`, `eliminated` from standings API
    - Captures load management motivation directly
    - Only informative in final 30 days — test on endgame-phase data specifically

11. **RotoWire `play_probability` as late-game DNP gate**
    - Data already scraped but not consumed downstream
    - 4:30 PM re-export with confirmed lineups catches last-minute rest decisions

12. **Classification model** — predict P(OVER) directly instead of points→compare to line

---

## Monday April 6 Risks

- **`weekly-retrain` CF fires at 5 AM ET.** Does `cap_to_last_loose_market_date()` prevent training through March? If not, manually retrain with `--train-end 2026-02-28`.
- **March-trained models still BLOCKED** — `decay-detection` CF should handle, but verify.
- **MLB schedulers:** `mlb-box-scores-daily` fires for first time at 8 AM ET. Verify YESTERDAY resolution works.

---

## Quick Start for Next Session

```bash
# 1. Check if any picks were generated overnight
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT game_date, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1 ORDER BY 1"

# 2. Check model edge distribution
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT system_id, ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,
       COUNTIF(ABS(predicted_points - current_points_line) >= 3) as edge3plus
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY 1 ORDER BY 1"

# 3. Check if Monday retrain produced good models
./bin/model-registry.sh list

# 4. Implement immediate fixes (items 1-3 from brainstorm)
# See aggregator.py lines ~1295 (under_low_rsc), ~923 (high_spread_over)
```

---

## Key Files

| Purpose | File |
|---------|------|
| BB aggregator (all filter/signal logic) | `ml/signals/aggregator.py` |
| Post-grading backfill (DNP voiding) | `orchestration/cloud_functions/post_grading_export/main.py` |
| All.json exporter (frontend data) | `data_processors/publishing/best_bets_all_exporter.py` |
| BB picks schema | `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` |
| bp_events scraper (MLB fix) | `scrapers/bettingpros/bp_events.py` |
| MLB path extractor | `data_processors/raw/path_extractors/mlb_extractors.py` |
| Quick retrain | `predictions/training/quick_retrain.py` |
| 5-season simulator | `scripts/nba/training/bb_enriched_simulator.py` |
| Discovery tools | `scripts/nba/training/discovery/` |

---

## Reference
- **Session 512 handoff (deep dive):** `docs/09-handoff/2026-04-04-SESSION-512-HANDOFF.md`
- **Session 508 (pick drought):** memory `session-508.md`
- **Model dead ends:** `docs/06-reference/model-dead-ends.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **BB simulator findings:** memory `bb-simulator-findings.md`
