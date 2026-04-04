# Session 511 Deep Dive Handoff — System Evaluation & Improvement

**Context:** Session 511 completed the GCP cost reduction plan (Sessions 509-511: ~$340-370/mo saved
from $886/mo baseline). This handoff is for a deep-dive session focused on evaluating both the NBA
and MLB prediction systems and identifying concrete improvements.

**Date:** 2026-04-04. NBA regular season ends ~April 12 (8 game days, 72 games remaining).

---

## Part 1: NBA System — Current State

### Season Record: 104-70 (59.8%) — Above 55% Target

| Metric | Value | Assessment |
|--------|-------|------------|
| Season HR | 59.8% (104-70) | GOOD — above 55% breakeven, profitable |
| OVER | 63-38 (62.4%) | Strong |
| UNDER | 41-32 (56.2%) | Solid |
| Edge 5+ | 81-42 (65.9%) | Excellent — this is where the money lives |
| Edge 7+ | 27-7 (79.4%) | Exceptional |
| Edge 3-5 | 19-25 (43.2%) | **BLEEDING MONEY** — below breakeven |

### Monthly Trajectory: Declining

| Month | W-L | HR | Assessment |
|-------|-----|----|------------|
| Jan 2026 | 49-18 | 73.1% | Exceptional |
| Feb 2026 | 27-21 | 56.3% | Above target |
| Mar 2026 | 27-30 | **47.4%** | **Below breakeven — lost money** |
| Apr 2026 | 1-1 | 50.0% | Too small (N=2) |

### Critical Issues

#### Issue 1: March Collapse (47.4% HR)
- **Root cause:** Models trained on Jan-Mar windows include ~41% March data (load management,
  lower scoring variance). This compresses predicted edge to 1.2-1.3 avg, far below the
  OVER edge floor of 5.0.
- **Feature 53 (`line_vs_season_avg`)** converges to near-zero in March as lines normalize
  to season averages. This is a permanent architectural issue flagged in Session 476.
- **Evidence:** Both `*_train0126_0323` models have avg edge 1.21-1.30. BLOCKED in decay state machine.

#### Issue 2: Both Primary Models BLOCKED
- `catboost_v12_noveg_train0126_0323` — BLOCKED, 47.8% HR 7d
- `lgbm_v12_noveg_train0126_0323` — BLOCKED, 51.5% HR 7d
- Both trained through March 23, 2026. Days since train: 11.

**Fix applied this session:** Enabled two Feb-anchored models:
- `lgbm_v12_noveg_train1227_0221` (Dec 27 - Feb 21) — 71% HR @ edge 3+ at eval
- `catboost_v12_noveg_train1227_0221` (Dec 27 - Feb 21) — 72% HR @ edge 3+ at eval
- Model cache refreshed. These should produce picks starting April 5.

#### Issue 3: Severe Pick Drought
- **13 picks in 14 days.** 9 zero-pick days. Healthy = 5-15 picks/day.
- Caused by edge compression from March-trained models + both models BLOCKED.
- Feb-anchored models should resolve this if they have better edge distribution.

#### Issue 4: Edge 3-5 is Net Negative (43.2%)
- 44 picks at edge 3-5 with 43.2% HR = roughly -8 to -9 units lost.
- This matches 5-season simulator findings: OVER at edge 3-5 is net-negative in 4/5 seasons.
- OVER edge floor is 5.0 (correct), but UNDER picks and signal-rescue picks at edge 3-5 leak through.
- **Question:** Should UNDER also have an edge floor, or should signal rescue be restricted at edge 3-5?

#### Issue 5: DNP Picks Not Voided on Site
- KAT (Apr 3), Bilal Coulibaly (Mar 30), Grayson Allen (Mar 30) — all DNP, showing as ungraded.
- These players were active when picks were generated but sat out.
- The site shows them as pending/ungraded rather than "no result" or voided.
- **Question:** Should the frontend or export pipeline handle DNP picks differently?

### Signal System Health
- **Combo signals still healthy:** `combo_3way` and `combo_he_ms` at 62.5% HR 30d, NORMAL regime.
- **`high_scoring_environment_over`** is a standout at 77.5% HR (N=40).
- Several OVER signals in COLD regime: `consistent_scorer_over`, `self_creation_over`, `over_trend_over`.
- UNDER signals: `home_under` at 41.4% HR (N=29) — possibly variance, health multiplier (0.5x COLD) already handles it.
- Market regime: NORMAL/LOOSE (vegas_mae 5.0-5.9) — favorable for edge generation.

### Key NBA Questions for Deep Dive

1. **Should the March-trained models (`*_train0126_0323`) be disabled?** They're BLOCKED and diluting the fleet. The Feb-anchored models should handle predictions. But the auto-disable system (`decay-detection` CF) should handle this automatically if `AUTO_DISABLE_ENABLED=true`.

2. **Edge 3-5 leakage fix:** 43.2% HR at edge 3-5 is losing money. Options:
   - Raise UNDER edge floor from 3.0 to 5.0 (matches OVER)
   - Restrict signal rescue to edge 4+ or 5+
   - Tighten `real_sc` gate for low-edge picks (require real_sc >= 3 at edge 3-5)
   - Analysis: run `scripts/nba/training/bb_enriched_simulator.py` with edge 5+ floor for UNDER

3. **Is the declining trajectory seasonal or structural?** Jan→Feb→Mar decline (73%→56%→47%) could be:
   - Seasonal: Market adjusts, late-season load management, line sharpening
   - Structural: Model training window includes increasingly stale data
   - Feature decay: `line_vs_season_avg` converges to zero late in season
   - Walk-forward analysis across prior seasons would clarify this

4. **Feb-anchored model performance:** These models were trained Dec 27 - Feb 21. Now being asked to predict on April data (6+ weeks out of window). How quickly will they decay?

5. **End-of-season strategy:** With 8 game days left:
   - Should we be more conservative (higher edge floors)?
   - Load management will increase — more DNPs
   - Some teams have locked playoff seeds and will rest starters

---

## Part 2: MLB System — Current State

### System Overview
- **Launched:** Session 501 (2026-03-28), 5 live predictions written March 28
- **Model:** CatBoost Regressor, 36 features, pitcher strikeout predictions
- **Strategy:** OVER-only, edge 0.75 (home) / 1.25 (away), top-5/day
- **4-season replay:** 63.4% HR, +470.7u, 12.8% ROI

### Pipeline Architecture
```
Phase 1 (scrapers) → Phase 2 (raw) → Phase 3 (analytics) → Phase 4 (precompute) → Phase 5 (predictions) → Phase 6 (grading)
```

### Known Issues (from prior sessions)
- `mlb-phase1-scrapers` NOT auto-deployed — manual `./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`
- MLB worker NOT auto-deployed — manual `gcloud builds submit --config cloudbuild-mlb-worker.yaml`
- `bp_mlb_player_props` super() crash was fixed Session 507
- `mlb_lineups` scraper reads from `gameData.teams.away.abbreviation` (fixed Session 501)
- MLB schedulers were `4-10` (April only) → fixed to `3-10` (March-October)

### Key MLB Questions for Deep Dive

1. **Is the pipeline actually producing predictions daily?** Check:
   ```sql
   SELECT game_date, COUNT(*) as predictions
   FROM mlb_predictions.player_prop_predictions
   WHERE game_date >= '2026-03-28'
   GROUP BY 1 ORDER BY 1
   ```

2. **Is grading working?** Are March 28+ predictions being graded?

3. **Data pipeline completeness:** Are all MLB scrapers running? Check:
   - `mlb_schedule` — daily schedule scraper
   - `mlb_lineups` / `mlb_lineup_batters` — lineup data
   - `statcast_pitcher_game_stats` — pitcher stats (historical + current season)
   - `bp_mlb_player_props` — BettingPros lines for grading
   - `mlb_events` — game results for grading

4. **Feature store health:** Is `mlb_predictions.ml_feature_store` populated?

5. **Model registry:** Is the MLB model registered and enabled?

6. **Best bets pipeline:** Does MLB have a best bets equivalent, or is it raw predictions only?

7. **Site integration:** Are MLB predictions showing on playerprops.io?

---

## Part 3: Cost Status (Reference)

| Bucket | Savings | Status |
|--------|---------|--------|
| Sessions 509-511 total | ~$340-370/mo | ✅ Deployed |
| Projected monthly bill | ~$516-546/mo | from $886/mo |
| Daily rate (Apr 4) | ~$22-24/day | trending down |

**Remaining optional:** Orchestrator min-instances ($13-20/mo, HIGH RISK), scheduler audit ($5-10/mo).

---

## Part 4: Fleet Status

### Enabled Models (4 total)
| Model | Train Window | Status | HR | Notes |
|-------|-------------|--------|-----|-------|
| lgbm_v12_noveg_train1227_0221 | Dec 27 – Feb 21 | enabled, NEW | 71% @ eval | Just enabled Session 511 |
| catboost_v12_noveg_train1227_0221 | Dec 27 – Feb 21 | enabled, NEW | 72% @ eval | Just enabled Session 511 |
| lgbm_v12_noveg_train0126_0323 | Jan 26 – Mar 23 | **BLOCKED** | 51.5% 7d | Edge compressed, drought-causing |
| catboost_v12_noveg_train0126_0323 | Jan 26 – Mar 23 | **BLOCKED** | 47.8% 7d | Edge compressed, drought-causing |

### Weekly Retrain CF
- `weekly-retrain` fires every Monday 5 AM ET
- Auto-retrains all enabled families, 56-day rolling window
- Has TIGHT market cap: `cap_to_last_loose_market_date()` auto-caps `train_end` when recent TIGHT days exist
- **Key concern:** If auto-retrain on Monday Apr 6 trains through Mar 30+, it will produce another compressed-edge model. The TIGHT cap should prevent this if recent days had vegas_mae < 4.5.

---

## Part 5: Suggested Deep Dive Agenda

### Priority 1: Fix the Bleeding (Edge 3-5 Leakage)
1. Query the 44 edge 3-5 picks: what direction, what signals, what rescue mechanism let them through?
2. Run the BB simulator with UNDER edge floor = 5.0 to measure impact
3. Decide: raise UNDER floor, restrict rescue, or tighten real_sc gate

### Priority 2: Validate Feb-Anchored Models
1. Check tomorrow (Apr 5): are the new models producing predictions? What's the avg edge?
2. If avg edge is >3.0, the pick drought should resolve
3. Monitor for 2-3 days before concluding

### Priority 3: March-Trained Model Decision
1. Check if `decay-detection` CF will auto-disable them (BLOCKED → auto-disable requires `AUTO_DISABLE_ENABLED=true`)
2. If not auto-disabled, manually disable with `python bin/deactivate_model.py MODEL_ID`
3. Ensure safety floor (3+ models remain enabled) is satisfied with 4→2

### Priority 4: MLB System Audit
1. End-to-end pipeline check: scrapers → raw → analytics → precompute → predictions → grading
2. Verify predictions are flowing daily
3. Check if lines data is available for grading
4. Assess when MLB best bets pipeline should be built

### Priority 5: End-of-Season Strategy
1. Analyze late-season patterns from prior years (load management, resting starters)
2. Consider tighter filters for last 8 game days
3. Plan for playoffs: different dynamics, different model behavior

### Priority 6: Structural Improvements for Next Season
1. Solve the `line_vs_season_avg` convergence problem (feature 53)
2. Training window strategy that avoids March compression
3. Dynamic training windows based on market regime
4. Feature store v3 with better late-season features

---

## Quick Start Commands

```bash
# Check if Feb-anchored models are generating predictions
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT system_id, game_date, COUNT(*) as n, AVG(ABS(predicted_points - current_points_line)) as avg_edge
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1, 2 ORDER BY 1, 2"

# Check edge 3-5 picks breakdown
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT bb.recommendation, bb.signal_count,
       COUNTIF(pa.prediction_correct = TRUE) as wins,
       COUNTIF(pa.prediction_correct = FALSE) as losses
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON pa.player_lookup = bb.player_lookup AND pa.game_date = bb.game_date
  AND pa.system_id = bb.system_id AND pa.recommendation = bb.recommendation
  AND pa.line_value = bb.line_value
WHERE bb.game_date >= '2025-10-28'
  AND ABS(bb.predicted_points - bb.line_value) BETWEEN 3 AND 5
  AND pa.prediction_correct IS NOT NULL AND pa.has_prop_line = TRUE
GROUP BY 1, 2 ORDER BY 1, 2"

# Check MLB pipeline
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT table_id, row_count FROM mlb_predictions.__TABLES__ ORDER BY table_id"

# Fleet health
./bin/model-registry.sh list

# Market regime
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT game_date, vegas_mae_7d, market_regime, bb_hr_7d
FROM nba_predictions.league_macro_daily
WHERE game_date >= CURRENT_DATE() - 7 ORDER BY game_date DESC"
```

---

## Reference

- **Session 511 handoff:** `docs/09-handoff/2026-04-04-SESSION-511-HANDOFF.md`
- **Session 508 (pick drought diagnosis):** `docs/09-handoff/` (search for 508)
- **Model dead ends:** `docs/06-reference/model-dead-ends.md`
- **BB simulator:** `scripts/nba/training/bb_enriched_simulator.py`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **MLB launch runbook:** `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`
- **Cost reduction plan:** `docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md`
