# Session 326 Handoff — Signal Study, Ultra Bets Investigation, Best Bets Backfill

**Date:** 2026-02-22
**Focus:** Deploy Session 325 models, backfill best bets, comprehensive signal/filter/Ultra Bets analysis

## Summary

1. Committed and pushed Session 325 changes (V12 backfill support + 5 new MONTHLY_MODELS)
2. Cloud Build deployed prediction-worker successfully (build `968d9f2e`)
3. Materialized best bets backfill: **100 picks, 66.0% HR, $2,680 P&L** (Jan 9 - Feb 21)
4. Comprehensive signal effectiveness study — **4 harmful signals identified**
5. Ultra Bets investigation — **V12+vegas edge 6+ is 100% HR (N=26)**
6. Negative filter audit — all filters validated, UNDER edge 7+ needs model-awareness

## Key Findings

### Signal Effectiveness (16 signals evaluated)

**Strong signals (above 65% HR):**
- `book_disagreement`: 100.0% (N=6)
- `combo_he_ms` / `combo_3way`: 88.2% (N=17)
- `rest_advantage_2d`: 74.0% (N=50) — best signal with meaningful sample

**4 harmful signals (below breakeven 52.4%):**
- `volatile_under`: 33.3% (N=3)
- `high_ft_under`: 33.3% (N=6)
- `self_creator_under`: 36.4% (N=11)
- `high_usage_under`: 40.0% (N=10)

**V12 MAE outperforms V9 MAE on best bets:** 70.4% vs 64.6% HR.

**Signal count sweet spot:** 4-7 signals (64-83% HR). Count=3 underperforms (59.1%).

**Zero-pick days:** 5 of 39 days (12.8%) had no picks. On 3 of those, available edge 5+ candidates won at 100%.

### Ultra Bets — V12+vegas Dominance

| Criteria | N | HR% | Notes |
|----------|--:|----:|-------|
| V12+vegas edge 6+ | 26 | **100.0%** | Zero losses |
| V12+vegas OVER edge 5+ | 18 | **100.0%** | Perfect on OVER direction |
| V12+vegas edge 5+ | 40 | **82.5%** | Both directions |
| V12+vegas edge 4.5+ | 57 | **77.2%** | All above 75% target |
| Multi-model consensus 3+ edge 5+ | 18 | **78.9%** | 3+ CatBoost models agree |

**V12+vegas edge gradient is monotonically increasing:**
- edge 3+: 68.0% (N=203)
- edge 4+: 74.1% (N=81)
- edge 5+: 82.5% (N=40)
- edge 6+: 100.0% (N=26)

### Filter Audit — All Validated

| Filter | N | HR% | Verdict |
|--------|--:|----:|---------|
| quality_below_85 + edge 5+ | 95 | 18.9% | CRITICAL — keep |
| edge_3_to_5 (all models) | 3,552 | 40.4% | GOOD — keep edge floor 5.0 |
| bench_under + edge 5+ | 372 | 45.2% | GOOD — keep |
| UNDER edge 7+ (V9) | 28 | 39.3% | GOOD for V9 |
| **UNDER edge 7+ (V12+vegas)** | **8** | **100.0%** | **HARMFUL for V12 — make model-aware** |

**Blacklisted players confirmed:**
- jarenjacksonjr: 11.8% HR (N=34)
- jabarismithjr: 21.9% HR (N=32), 0/12 at edge 5+
- treymurphyiii: 30.9% HR (N=55)
- lukadoncic: 45.1% HR (N=51)

## Files Modified/Created

| File | Change |
|------|--------|
| `bin/backfill-challenger-predictions.py` | V12/V12_NOVEG contract support (committed) |
| `predictions/worker/prediction_systems/catboost_monthly.py` | +5 MONTHLY_MODELS entries (committed) |
| `docs/08-projects/current/session-326-analysis/01-SIGNAL-FILTER-ULTRA-ANALYSIS.md` | Full analysis report |
| `docs/09-handoff/2026-02-22-SESSION-326-HANDOFF.md` | This handoff |

## Recommendations for Next Session

### Immediate Actions

1. **Remove 4 harmful UNDER signals:** `high_ft_under`, `self_creator_under`, `volatile_under`, `high_usage_under` — these drag down signal count for good UNDER picks

2. **Make UNDER edge 7+ filter model-aware:** Allow V12+vegas UNDER edge 7+ (100% HR), keep blocking V9 (39.3% HR)

3. **Implement Ultra Bets tier:**
   - Primary criteria: V12+vegas edge 6+ (100% HR, N=26)
   - Secondary: multi-model consensus 3+ at edge 5+ (78.9%, N=18)
   - Add as new subset in `shared/config/dynamic_subsets.py`
   - Export to `v1/ultra-bets/{date}.json`

4. **Consider zero-pick-day fallback:** When 0 signal-qualified picks, take highest-edge V12+vegas pick (missed 7 wins on zero-pick days)

### Model Strategy

5. **V12+vegas promotion path:** 68.0% HR at edge 3+ vs V9's 51.7% — massive outperformance. Need live shadow data accumulation (2+ weeks) before promotion, but the walk-forward evidence is overwhelming.

6. **Weekly retrain all families:** Extend `retrain.sh` to include V12+vegas alongside V9 (same rolling 42-day window)

### Architecture Questions for Ultra Bets

- Should Ultra Bets be a separate JSON export or a `tier: "ultra"` flag on best bets picks?
- Should it require its own algorithm version string?
- Expected volume: 1-3 picks per game day (some days 0)
- Target audience: users wanting fewer but higher-confidence picks

## Active Models Inventory (13 shadows + 1 champion)

| System ID | Feature Set | Window | HR 3+ | Purpose |
|-----------|-------------|--------|-------|---------|
| catboost_v9 (champion) | v9 (33f) | Nov 2 - Feb 5 | 48.3% | PRODUCTION |
| catboost_v9_train1225_0205 | v9 (33f) | Dec 25 - Feb 5 | 60.0% | Fresh shadow |
| catboost_v12_train1102_1225 | v12 (54f) | Nov 2 - Dec 25 | 65.9% | Replay (Jan) |
| catboost_v12_train1102_0125 | v12 (54f) | Nov 2 - Jan 25 | 71.1% | Replay (late Jan) |
| catboost_v12_train1225_0205 | v12 (54f) | Dec 25 - Feb 5 | 75.0% | Session 324 shadow |
| catboost_v12_train1225_0205_feb22 | v12 (54f) | Dec 25 - Feb 5 | 64.7% | Fresh shadow |
| catboost_v12_q43_train1225_0205 | v12 (54f) | Dec 25 - Feb 5 | 70.6% | Session 324 Q43 |
| catboost_v12_q43_train1225_0205_feb22 | v12 (54f) | Dec 25 - Feb 5 | 59.0% | Fresh Q43 |
| + 5 other existing shadows | various | various | various | Existing |

## Commands for Next Session

```bash
# 1. Check model health + daily steering
/daily-steering

# 2. Remove harmful signals
# Edit ml/signals/registry.py to remove: high_ft_under, self_creator_under, volatile_under, high_usage_under

# 3. Make UNDER edge 7+ filter model-aware
# Edit ml/signals/aggregator.py — check source_model_family before applying under_edge_7plus block

# 4. Implement Ultra Bets
# Define criteria in shared/config/dynamic_subsets.py
# Add Ultra Bets selection in data_processors/publishing/signal_best_bets_exporter.py
# Create export endpoint v1/ultra-bets/{date}.json

# 5. Monitor best bets source_model_id distribution
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
for r in client.query('''
  SELECT source_model_family, COUNT(*) as n
  FROM nba_predictions.signal_best_bets_picks
  WHERE game_date >= '2026-02-22'
  GROUP BY 1 ORDER BY 2 DESC
''').result():
    print(f'{r.source_model_family}: {r.n}')
"
```
