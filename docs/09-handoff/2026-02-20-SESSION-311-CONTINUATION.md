# Session 311 Continuation — Architecture Questions, Frontend Grouping, Layer Strategy

**Date:** 2026-02-20
**Context:** Session 311 deployed P0 quality fix, signal subsets, filter validation, decay-gated promotion. This document captures open architecture questions for the next session to explore and resolve.
**Project docs:** `docs/08-projects/current/best-bets-v2/`

---

## What Was Deployed (Session 311)

1. **P0 FIX:** `feature_quality_score` added to supplemental data query — best bets were completely blocked since Feb 19 due to Session 310's quality filter change. Now fixed and deployed.
2. **Signal Subsets (Layer 3):** 4 curated signal subsets (`signal_combo_he_ms`, `signal_combo_3way`, `signal_bench_under`, `signal_high_count`) via new `SignalSubsetMaterializer`. Writes to `current_subset_picks`.
3. **Filter Validation:** `--validate-filters` flag in `retrain.sh` checks model-specific filters against eval window.
4. **Decay-Gated Promotion:** `retrain.sh --promote` now checks champion decay state.
5. **xm_* confirmed working:** Cross-model subsets producing rows (7 families discovered).
6. **Phase A verified:** Multi-model sourcing works. V9 champion wins highest-edge for only 1/74 players. Non-V9 models unlock all edge 5+ picks.

**All changes deployed via Cloud Build (3 successful builds at 16:33-16:34 UTC).**

---

## Open Architecture Questions (Explore in Next Session)

### QUESTION 1: DB Table Naming Consistency

**Current state:**
- `model_performance_daily` — model decay tracking (HR, state machine)
- `signal_health_daily` — signal regime tracking (HOT/NORMAL/COLD)

**The inconsistency:** "model_performance" vs "signal_health" — different naming patterns for the same concept (rolling performance tracking).

**Options:**
1. **Rename `signal_health_daily` → `signal_performance_daily`** — matches model_performance_daily pattern
2. **Rename both to a common pattern** — e.g., `daily_model_performance` + `daily_signal_performance`
3. **Leave as-is** — they serve different purposes (model tracks decay states, signal tracks regimes). The naming reflects the semantic difference.

**Recommendation:** Rename `signal_health_daily` → `signal_performance_daily` for consistency. Both track rolling hit rates by timeframe. The "health" vs "performance" distinction is artificial.

**Impact:** Need to update: `ml/signals/signal_health.py`, `ml/analysis/model_performance.py`, `orchestration/cloud_functions/decay_detection/main.py`, `validate-daily` skill, CLAUDE.md references. Views and downstream consumers need migration.

### QUESTION 2: What Is Layer 3?

**Current confusion:** The handoff said "Layer 3 = best bets." But we also just created signal subsets. Where do they fit?

**Proposed clarification of layers:**

| Layer | What It Is | System ID | Source |
|-------|-----------|-----------|--------|
| **Layer 1** | Per-model subsets (edge/confidence/direction filters) | Specific model (e.g., `catboost_v9`) | `SubsetMaterializer` reading `dynamic_subset_definitions` |
| **Layer 2** | Cross-model observation subsets (consensus patterns) | `cross_model` | `CrossModelSubsetMaterializer` |
| **Layer 3** | Signal subsets (pick-level signal patterns) | Specific model (from prediction) | `SignalSubsetMaterializer` |
| **Output** | Best Bets (the final curated picks for users) | Champion model | `SignalBestBetsExporter` → `signal_best_bets_picks` |

**Key distinction:** Best Bets is NOT a layer — it's the **output** that draws from all layers. The 3 layers are observation/tracking systems that feed into grading. Best Bets is the user-facing product.

**Signal subsets (Layer 3) are observation-only for now.** They track which picks had specific signals fire, get graded, and accumulate HR data. The graduation path (N>=50, HR>=65%) would eventually let a signal subset directly produce best bets picks (bypassing the normal aggregator flow).

### QUESTION 3: Layer 2 Definition & Strategy

**What defines Layer 2:** Cross-model agreement patterns. These are computed by comparing predictions ACROSS model families (V9 MAE, V12 MAE, V9 Q43, etc.) for the same player-game. The question: "Do multiple independent models agree on the same bet?"

**Current 5 xm_* subsets:**
- `xm_consensus_3plus` — 3+ models agree on direction, edge >= 3
- `xm_consensus_4plus` — 4+ models agree
- `xm_quantile_agreement_under` — all quantile models agree UNDER
- `xm_mae_plus_quantile_over` — MAE + any quantile confirm OVER
- `xm_diverse_agreement` — V9 + V12 (different feature sets) agree

**Yesterday's results (Feb 19):**
- `xm_consensus_4plus`: 3-0 (100% HR)
- `xm_diverse_agreement`: 3-0 (100% HR)

**Strategy confidence:** HIGH for observation. The cross-model consensus data is extremely valuable — yesterday's perfect 3-0 on both consensus subsets validates the concept. However, the CLAUDE.md warns that V9+V12 agreement is anti-correlated with winning for OVER picks. This needs more data to resolve.

**Potential improvement:** The xm_* subsets currently use `min_edge >= 3`. Consider raising to `min_edge >= 5` to align with the best bets edge floor, which would give us apples-to-apples comparison with best bets.

### QUESTION 4: Multiple V9 Models / Family Handling

**Current active V9 models (Feb 20):**

| system_id | Family | Role |
|-----------|--------|------|
| `catboost_v9` | v9_mae | **Champion** (production) |
| `catboost_v9_train1102_0205` | v9_mae (fallback) | Shadow (prior retrain) |
| `catboost_v9_q43_train1102_0125` | v9_q43 | Shadow (quantile) |
| `catboost_v9_q45_train1102_0125` | v9_q45 | Shadow (quantile) |
| `catboost_v9_low_vegas_train0106_0205` | v9_low_vegas | Shadow (variant) |

**The "all_picks" question:** The `all_picks` subset uses `system_id = 'catboost_v9'` (champion only). The shadow model `catboost_v9_train1102_0205` does NOT produce duplicate `all_picks` rows. Each model family has its own subset prefix (e.g., `q43_*`, `q45_*`, `low_vegas_*`).

**Problem found:** The `dynamic_subset_definitions` table has stale system_id references:
- Definitions reference `catboost_v9_q43_train1102_0131` (old)
- Predictions use `catboost_v9_q43_train1102_0125` (current)
- This means Q43/Q45 subsets may not be materializing correctly

**Action needed:** Update `dynamic_subset_definitions` to match current system_ids, OR make the subset materializer do prefix-based matching (like `classify_system_id`) instead of exact matching.

**Handling multiple models from same family:**
- Currently: Only the exact `system_id` match gets subsets. Shadow models with different names get separate subsets.
- Better approach: The `dynamic_subset_definitions` could support pattern matching (e.g., `system_id LIKE 'catboost_v9_q43_%'`) so subsets survive retrains automatically.
- Or: A lookup from family → current active system_id, applied during materialization.

### QUESTION 5: Frontend Grouping Strategy

**Current frontend:**
- **End users:** See only Best Bets picks (simple, clean)
- **Admin page:** Shows all subsets grouped somehow

**Proposed grouping for admin page:**

```
MODEL VIEW (Tab 1)
├── V9 Champion (catboost_v9)
│   ├── Top Pick / Top 3 / Top 5
│   ├── High Edge All / High Edge OVER
│   ├── Ultra High Edge / Green Light
│   └── All Picks
├── V9 Q43 (catboost_v9_q43_*)
│   ├── Q43 UNDER Top 3 / Q43 UNDER All
│   └── Q43 All Picks
├── V9 Q45 (catboost_v9_q45_*)
│   ├── Q45 UNDER Top 3
│   └── Q45 All Picks
├── V12 Nova (catboost_v12*)
│   ├── Nova Top Pick / Top 3 / Top 5
│   ├── Nova High Edge All / OVER
│   └── Nova All Picks
└── V12 Quantile (v12q43, v12q45)
    └── V12 Q43/Q45 subsets

CROSS-MODEL VIEW (Tab 2)
├── Consensus (agreement-based)
│   ├── xm_consensus_3plus
│   └── xm_consensus_4plus
├── Strategy (loss-type agreement)
│   ├── xm_quantile_agreement_under
│   └── xm_mae_plus_quantile_over
└── Diversity (feature-set agreement)
    └── xm_diverse_agreement

SIGNAL VIEW (Tab 3)
├── Combo Signals
│   ├── signal_combo_he_ms (94.9% HR)
│   └── signal_combo_3way (95.5% HR)
├── Pattern Signals
│   └── signal_bench_under (76.9% HR)
└── Multi-Signal
    └── signal_high_count (4+ signals, 85.7% HR)
```

**Layer 2 duplication concern:** Cross-model subsets show players that appear across multiple model subsets. Two options:
1. **Separate tab (recommended):** Cross-model is its own view. No duplication — the xm_* subsets are a DIFFERENT lens (consensus) vs per-model subsets (individual model confidence).
2. **Inline with models:** Show xm_* picks under each contributing model. This duplicates display but shows "this pick also has cross-model consensus." Adds visual noise.

**Recommendation:** Separate tabs/sections. Layer 1 = "By Model", Layer 2 = "Cross-Model Consensus", Layer 3 = "Signal Patterns". Each is a different analytical lens. A pick might appear in all 3, and that's a GOOD signal — it means the pick has model confidence + cross-model consensus + signal pattern support.

**Enhancement idea:** On each pick card, show badges for which layers it appears in:
- "V9 Top 3" (Layer 1)
- "4+ Model Consensus" (Layer 2)
- "HE+MS Combo" (Layer 3)

This gives the admin a quick visual of pick provenance without duplicating rows.

### QUESTION 6: Stale Subset Definitions (Action Item)

The `dynamic_subset_definitions` table has stale system_ids from prior retrains. This needs to be fixed:

```sql
-- Check current stale definitions
SELECT subset_id, system_id
FROM nba_predictions.dynamic_subset_definitions
WHERE system_id LIKE '%_train%'
  AND is_active = TRUE;

-- These need to be updated to match current prediction system_ids
-- OR the materializer needs pattern-based matching
```

**Options:**
1. Manual UPDATE to fix system_ids after each retrain (fragile)
2. Make `SubsetMaterializer._filter_picks_for_subset()` use family-based matching via `classify_system_id()` (robust, survives retrains)
3. Add a `retrain.sh` post-step that auto-updates definitions (automated)

**Recommendation:** Option 2 (family-based matching in materializer) — most robust, zero maintenance.

---

## Backfill Needed

### Signal Subsets (Layer 3)
The `SignalSubsetMaterializer` was just deployed. It runs as part of the `SignalBestBetsExporter` flow. Signal subsets will start populating on the next daily export run. No backfill needed — the subsets need fresh signal evaluation results which aren't stored historically.

### Best Bets Re-Export
`signal_best_bets_picks` table hasn't populated since Feb 11 (quality regression). After the P0 fix deployment, the next daily export should resume. For Feb 19 (games completed), a manual re-export would capture grading data:
```bash
PYTHONPATH=. python -c "
from backfill_jobs.publishing.daily_export import run_daily_export
run_daily_export('2026-02-19', ['signal-best-bets'])
"
```

---

## Current State Summary

### What's Working
- Layer 1 (model subsets): 20 subsets, running daily ✓
- Layer 2 (cross-model): 3 of 5 xm_* subsets firing ✓ (fixed this session)
- Layer 3 (signal subsets): Deployed, awaiting first daily run
- Best bets selection: Edge-first, multi-model sourcing, negative filters ✓
- Model performance tracking: 4 models, 25 dates backfilled ✓
- Signal health tracking: 10 signals, 36 dates backfilled ✓
- Grading: All subsets graded automatically ✓

### What Needs Attention
- **Retrain overdue:** Champion 13 days stale, quantile models 24 days stale (7-day cadence)
- **Stale subset definitions:** Q43/Q45 system_ids don't match current predictions
- **DB naming:** `signal_health_daily` vs `model_performance_daily` inconsistency
- **Feb 19 re-export:** Best bets table has gap from quality regression

### Key Files
| File | Purpose |
|------|---------|
| `data_processors/publishing/subset_materializer.py` | Layer 1 materialization |
| `data_processors/publishing/cross_model_subset_materializer.py` | Layer 2 materialization |
| `data_processors/publishing/signal_subset_materializer.py` | Layer 3 materialization (NEW) |
| `data_processors/publishing/signal_best_bets_exporter.py` | Best bets output (orchestrator) |
| `ml/signals/aggregator.py` | Edge-first selection + negative filters |
| `ml/signals/supplemental_data.py` | Multi-model query (P0 fix here) |
| `shared/config/cross_model_subsets.py` | xm_* definitions + model discovery |
| `shared/config/subset_public_names.py` | All subset IDs → display names |
| `bin/retrain.sh` | Retrain with --validate-filters + decay-gated promotion |

### Performance Data Locations
| Table | Content | Backfill |
|-------|---------|----------|
| `model_performance_daily` | Model HR, state, staleness | Jan 20 → Feb 18, 4 models |
| `signal_health_daily` | Signal HR, regime | Jan 9 → Feb 19, 10 signals |
| `subset_grading_results` | Subset W-L per date | Full season |
| `prediction_accuracy` | Individual prediction grading | Full season, 419K+ rows |
| `signal_best_bets_picks` | Best bets output | Gap Feb 12-18 (ASB), Feb 19+ (quality regression, now fixed) |

---

## Priority Order for Next Session

1. **Verify best bets resumed** — Check `signal_best_bets_picks` has rows for Feb 20 after daily export runs
2. **Re-export Feb 19** — Manual backfill for the missed day
3. **Fix stale subset definitions** — Update Q43/Q45 system_ids OR implement family-based matching
4. **Architecture decisions** — Resolve layer definitions, DB naming, frontend grouping (see questions above)
5. **Retrain** — All models overdue. `./bin/retrain.sh --all --validate-filters`
6. **Frontend grouping implementation** — Based on architecture decisions

---

## What NOT to Do

- Do NOT remove the quality filter in aggregator.py — it's correct now
- Do NOT create per-signal-per-model subsets (108 subsets) — only the 4 curated ones
- Do NOT use consensus_bonus for ranking — V9+V12 OVER agreement is anti-correlated
- Do NOT auto-remove filters based on --validate-filters output — human review required
- Do NOT rename DB tables without a migration plan (views, CFs, monitoring all reference them)
