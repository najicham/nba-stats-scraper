# Session 467 Handoff

**Date:** 2026-03-11
**Previous:** Session 466 (rescue restriction, signal promotions, retrain fix, discovery system)

## Current State

### Fleet Status (7 enabled models, all fresh)
| Model | Family | Days Stale |
|-------|--------|-----------|
| catboost_v12_noveg_train0113_0310 | v12_noveg_mae | 1d |
| catboost_v9_train0112_0309 | v9_mae | 2d |
| catboost_v16_noveg_train0112_0309 | v16_noveg_mae | 2d |
| catboost_v12_noveg_train0112_0309 | v12_mae | 2d |
| catboost_v12_train0112_0309 | v12_mae | 2d |
| lgbm_v12_noveg_train0112_0223 | lgbm_v12_noveg | 16d |
| xgb_v12_noveg_train0112_0223 | xgb_v12_noveg | 16d |

### Algorithm: `v466_rescue_restrict_signal_promote`
- OVER rescue restricted to HSE only (was 6 signals — combo_3way, combo_he_ms, volatile_scoring, etc. all removed for OVER)
- UNDER rescue kept broad (combo_3way, combo_he_ms, home_under, hot_3pt_under, line_drifted_down_under)
- 3 signals PROMOTED from shadow: hot_3pt_under (62.5%), cold_3pt_over (60.2%), line_drifted_down_under (59.8%)
- Retrain CF fixed: min_n_graded 25→15, MAX_FAMILIES_PER_RUN 5→10

### Blacklist Fix (Session 466)
Player blacklist now uses family-expanded model query (includes predecessors of enabled models). Without this fix, blacklist was blind after fleet swap (0 players blocked). Now catches 7 chronic losers: KAT (18.2%), Jamal Murray (23.1%), Donovan Mitchell (27.3%), Evan Mobley (0%), etc.

### Deployment Status
- All services deployed and up-to-date (3 stale services fixed: validation-runner, nba-scrapers, grading-service)
- Worker cache refreshed with latest models
- Zero deployment drift

### Performance Crisis Context
- Jan 73.1% → Feb 57.1% → Mar 41.5% HR
- Root causes: model staleness (FIXED), edge compression 7.2→4.3 (models now fresh), rescued OVER losers (FIXED — HSE only)
- Mar 7: 35.7%, Mar 8: 22.2%, Mar 9: 0% — catastrophic stretch before fixes

## Signal Discovery System (NEW — Session 466)

### Tools Built
Located at `scripts/nba/training/discovery/`:

1. **`feature_scanner.py`** — Scans features × thresholds × directions. 5-layer validation: binomial test + BH FDR + cross-season consistency + effect size + block bootstrap.
2. **`combo_tester.py`** — Tests 2-way and 3-way signal interactions. Classifies as SYNERGISTIC/ADDITIVE/REDUNDANT.
3. **`data_loader.py`** — Loads 79K predictions across 5 seasons (2021-2026), joins with 99 columns of features.
4. **`stats_utils.py`** — BH FDR correction, block bootstrap by game-date, cross-season consistency.

### How to Run
```bash
# Feature scanner (edge 3+, 5 seasons)
PYTHONPATH=. python scripts/nba/training/discovery/feature_scanner.py --verbose --reset --min-edge 3.0

# Combo tester
PYTHONPATH=. python scripts/nba/training/discovery/combo_tester.py --verbose --min-edge 3.0

# Full population scan (for filter discovery)
PYTHONPATH=. python scripts/nba/training/discovery/feature_scanner.py --verbose --reset --min-edge 0
```

### 5-Season Discovery Results (79K predictions)

**Top Individual Signals (all NEW, validated 5 seasons):**
| Signal | Direction | HR | N | Effect | Status |
|--------|-----------|-----|---|--------|--------|
| book_disagree_over (book_std >= 1.0) | OVER | 79.6% | 211 | +22pp | NOT yet implemented direction-specific |
| hot_3pt_under (3PT diff >= 10%) | UNDER | 74.4% | 250 | +17pp | PROMOTED in v466 ✓ |
| cold_fg_under_block (FG diff <= -10%) | UNDER | 28.6% | 217 | filter | ACTIVE filter ✓ |
| star_away_under (line >= 25 + away) | UNDER | 58.7% | 1,279 | +1.0pp | NOT implemented |
| Monday UNDER | UNDER | 59.9% | 750 | +2.2pp | NOT implemented |
| BP dropped heavy UNDER | UNDER | 59.1% | 325 | +1.4pp | Validates line_drifted_down ✓ |
| BP drifted down UNDER | UNDER | 58.6% | 616 | +0.9pp | PROMOTED in v466 ✓ |

**Top Combos (5-season):**
| Combo | HR | N | Synergy |
|-------|-----|---|---------|
| book_disagree + high_edge + low_line OVER | 89.4% | 113 | +9.8pp above best individual |
| book_disagree + high_edge OVER | 88.7% | 133 | +9.1pp |
| book_disagree + low_line OVER | 82.2% | 169 | +2.6pp |
| low_line + edge 7+ OVER | 81.5% | 200 | +19.9pp |
| hot_3pt + away UNDER | 80.3% | 137 | +5.9pp |
| hot_3pt + away + rest_adv UNDER | 79.8% | 109 | +5.4pp |
| low_line + high_edge OVER | 72.3% | 437 | +10.8pp |

**Critical finding:** ALL 16 validated feature scanner results are UNDER direction. Suggests systematic OVER bias in the model that the market doesn't have.

## Priority Tasks

### P0 — Monitor v466 Debut (Mar 11, 6 games)
```bash
# Check picks generated
bq query --use_legacy_sql=false "
SELECT game_date, algorithm_version, COUNT(*) as picks,
  COUNTIF(recommendation = 'OVER') as over_picks,
  COUNTIF(recommendation = 'UNDER') as under_picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-11'
GROUP BY 1, 2"

# Check blacklist fired
# Look for "Player blacklist:" in prediction-coordinator logs
gcloud run services logs read prediction-coordinator --region=us-west2 --limit=50 2>&1 | grep -i blacklist

# After games complete (~11 PM ET), check results
bq query --use_legacy_sql=false "
SELECT bb.game_date, bb.player_lookup, bb.recommendation, bb.edge,
  pa.prediction_correct, bb.algorithm_version
FROM nba_predictions.signal_best_bets_picks bb
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON bb.game_date = pa.game_date AND bb.player_lookup = pa.player_lookup
  AND pa.has_prop_line = TRUE
WHERE bb.game_date = '2026-03-11'
ORDER BY bb.edge DESC"
```

**Decision gate:** HR >= 55% over 2 days → keep iterating. HR < 45% → escalate.

### P1 — Build Archetype Analyzer (Tool 3)
Located at `scripts/nba/training/discovery/archetype_analyzer.py`. Design:
- Cluster players by: usage% bucket (bench/role/starter/star), scoring variance (low/mid/high), line range (low/mid/high/elite), 3PT reliance (low/mid/high)
- Per archetype: compute OVER HR, UNDER HR, model bias (mean predicted - actual)
- Find archetypes where model systematically over/undershoots
- Cross-season stability required (scoring variance r=0.642 is stable dimension)
- Use same `DiscoveryDataset` from data_loader.py
- Output: archetypes where OVER HR < 42% (potential filter) or UNDER HR > 60% (structural signal)

### P2 — Expand Feature Scanner
Current scan only generated 304 hypotheses (many filtered for insufficient data). Expand:
- Add more interaction hypotheses (2-way feature combinations beyond what's in generate_combination_hypotheses)
- Add rolling window features: over_rate_last_10 × direction, margin_vs_line × direction
- Add edge-stratified analysis: does the signal hold at edge 3-5 AND edge 5+?
- Run scanner at min_edge=5.0 separately to find edge 5+ specific signals

### P3 — Implement Discovery Findings
After v466 results confirm recovery:
1. **`book_disagree_over`** — Direction-specific book disagreement signal. 79.6% HR (N=211). Currently `book_disagreement` is direction-neutral. Implement as separate signal or add direction weighting.
2. **`hot_3pt_away_under` combo tag** — 80.3% HR (N=137). Both hot_3pt_under and away already fire independently. Detect co-firing and boost composite score.
3. **`star_away_under`** — 58.7% HR (N=1,279). line >= 25 + away. Could be a new signal or boost to existing home_under weight.

### P4 — Investigate OVER Bias
ALL 16 validated scanner results are UNDER. This means:
- UNDER is consistently profitable across 5 seasons at edge 3+
- OVER is at or below baseline in every tested condition
- The model may have systematic OVER bias the market doesn't
- Consider: should we further restrict OVER picks beyond the rescue restriction?
- Query to investigate:
```sql
SELECT season, recommendation,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE has_prop_line = TRUE AND ABS(predicted_points - line_value) >= 3
GROUP BY 1, 2
ORDER BY 1, 2
```

### P5 — MLB Pre-Season (Before Mar 27)
From Session 465 start prompt:
- Model retrain with data through 2026-03-20
- Resume schedulers on Mar 24 (`./bin/mlb-season-resume.sh`)
- Opening day verification Mar 27

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | Signal/filter/rescue logic (v466 changes) |
| `ml/signals/pipeline_merger.py` | ALGORITHM_VERSION = 'v466_rescue_restrict_signal_promote' |
| `ml/signals/player_blacklist.py` | Family-expanded blacklist (Session 466 fix) |
| `scripts/nba/training/discovery/` | Signal discovery system (4 files) |
| `results/signal_discovery/` | Scan results (CSV + JSON) |
| `orchestration/cloud_functions/weekly_retrain/main.py` | min_n=15, max_families=10 |

## What NOT to Do
- Don't implement discovery findings before v466 results (need baseline)
- Don't relax the OVER rescue restriction (44% rescued OVER was the #1 loss source)
- Don't lower edge floor below 3.0 (edge 3-5 is net-negative across 5 seasons)
- Don't trust single-season scanner results — require 3+ season consistency
- Don't add features to the model (V12_noveg remains optimal, 80+ dead ends)
