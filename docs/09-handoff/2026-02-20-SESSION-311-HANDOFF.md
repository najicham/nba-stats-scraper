# Session 311 Handoff — P0 Quality Fix, Signal Subsets, Retrain Infrastructure

**Date:** 2026-02-20
**Focus:** Fix P0 quality regression blocking all best bets, signal subset tracking, retrain filter validation, decay-gated promotion, Phase A verification
**Project docs:** `docs/08-projects/current/best-bets-v2/`

---

## What Was Done

### 1. P0 FIX: Quality Filter Regression (CRITICAL)

**Bug:** Session 310 changed `aggregator.py` quality filter from `if quality > 0 and quality < 85:` to `if quality < 85:`, but `feature_quality_score` was NEVER in the supplemental data query. Result: quality=None->0, 0<85=True -> ALL picks blocked. Zero best bets since Feb 19.

**Fix:** Added `feature_quality_score` to:
- Multi-model CTE in `supplemental_data.py` (line 97)
- Single-model CTE in `supplemental_data.py` (line 152)
- Prediction dict construction (line 417)

**Impact:** Best bets pipeline was completely broken for 2 game days. Fix restores normal operation.

### 2. Signal Subsets (4 curated subsets, NEW)

Created `SignalSubsetMaterializer` — filters on pick-level signal tags (not market-level daily_signal). Writes to `current_subset_picks` for grading by existing `SubsetGradingProcessor`.

| Subset ID | Signal Required | Edge | Direction | Historical HR |
|-----------|----------------|------|-----------|---------------|
| `signal_combo_he_ms` | combo_he_ms | >=5 | ANY | 94.9% |
| `signal_combo_3way` | combo_3way | >=5 | OVER | 95.5% |
| `signal_bench_under` | bench_under | >=5 | UNDER | 76.9% |
| `signal_high_count` | 4+ signals | >=5 | ANY | 85.7% |

**Graduation path:** N>=50 and HR>=65% at edge 5+ -> eligible for direct best bets inclusion.

### 3. Filter Validation (`--validate-filters`)

Added to `retrain.sh`. Runs after training, checks model-specific filters against eval window:
- UNDER edge 7+ block: Query HR for new model on eval data
- Quality < 85 block: Same
- Market-structural filters: Always inherited (no validation)
- Player blacklist: Auto-recomputes

Output: CONFIRMED (pattern holds) or REVIEW_NEEDED (investigate).

### 4. Decay-Gated Promotion

Modified `retrain.sh --promote` to query `model_performance_daily` for champion's state. All states promote immediately (champion is either healthy and we're upgrading, or degrading and we urgently need a replacement). Added `--force-promote` flag.

### 5. Phase A Multi-Model Verified

Multi-model sourcing works correctly. V9 champion wins highest-edge for only 1/74 players on Feb 19. Multi-model unlocks ALL 6 edge-5+ picks. Zero best bets was caused by quality regression, not multi-model.

### 6. xm_* Materialization Confirmed

Cross-model subsets producing rows for Feb 19 (7 families discovered). Session 310 classify_system_id fallback working.

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/supplemental_data.py` | Add feature_quality_score to query CTEs + pred dict (P0 fix) |
| `data_processors/publishing/signal_subset_materializer.py` | NEW — signal-based subset materialization |
| `data_processors/publishing/signal_best_bets_exporter.py` | Integrate signal subset materializer after signal eval |
| `shared/config/subset_public_names.py` | Add 4 signal subset public names (IDs 36-39) |
| `bin/retrain.sh` | --validate-filters, --force-promote, decay-gated promotion |
| `docs/08-projects/current/best-bets-v2/07-SESSION-311-CHANGES.md` | Session project doc |
| `docs/09-handoff/2026-02-20-SESSION-311-HANDOFF.md` | This handoff |

---

## Known Issues / Gaps

### Best Bets Need Re-Export for Feb 19-20

After deploying the quality fix, the best bets for Feb 19 and Feb 20 need to be re-exported. Run:
```bash
# Re-export for Feb 19 (games completed)
PYTHONPATH=. python -c "
from backfill_jobs.publishing.daily_export import run_daily_export
run_daily_export('2026-02-19', ['signal-best-bets'])
"
```

### Signal Subsets Need Grading Data Accumulation

The 4 new signal subsets start with zero graded data. They need 2-4 weeks of daily operation to accumulate enough picks for meaningful grading. The graduation threshold is N>=50.

### Retrain Due

Current champion (`catboost_v9_33f_train20260106-20260205`) was trained Feb 18. With 7-day cadence, next retrain is due around Feb 25. Use:
```bash
./bin/retrain.sh --promote --validate-filters
```

---

## Priority Order for Next Session

1. **Deploy and verify** — Push to main, verify Cloud Build, confirm best bets generate for Feb 20 games
2. **Re-export Feb 19 best bets** — Games already completed, grading data available
3. **Monitor signal subset accumulation** — Check `current_subset_picks` for signal_* subset_ids
4. **Weekly retrain (Feb 25)** — Use new `--validate-filters` flag
5. **Signal subset graduation tracking** — Build a query to check N and HR per signal subset

---

## What NOT to Do

- Do NOT remove the quality filter in aggregator.py — it's correct now that feature_quality_score flows through
- Do NOT create per-signal-per-model subsets (108 subsets) — only the 4 curated ones
- Do NOT use consensus_bonus for ranking — V9+V12 agreement is anti-correlated
- Do NOT auto-remove filters based on --validate-filters output — human review required
