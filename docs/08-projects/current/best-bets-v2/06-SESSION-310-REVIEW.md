# Session 310 Review — Best Bets System Health + Model Transition Strategy

**Date:** 2026-02-19
**Type:** Research & Analysis (no code changes)
**Scope:** End-to-end best bets review, model transition strategy, filter transferability, cross-model subsets, signal system assessment

---

## 1. System Health Check

### Overall Assessment: SOUND WITH GAPS

The best bets pipeline architecture is solid. The edge-first selection (Session 297), 8 negative filters, multi-model candidate generation (Session 307), and 18-signal annotation system work together coherently. However, the review found **4 code bugs**, **1 data gap**, and **several operational concerns**.

### Code Bugs Found

#### Bug 1: Feature Quality Score = 0 Bypasses Filter (MEDIUM)
**File:** `ml/signals/aggregator.py` ~line 136
**Issue:** The quality filter checks `if quality > 0 and quality < 85:` — meaning quality=0 (missing/uncomputed) passes through without triggering the block. A player with no quality data gets treated as passing.
**Impact:** Picks with missing quality data could slip into best bets. Low impact in practice since the feature store usually computes quality, but a defensive hole.
**Fix:** Change to `if quality is None or quality == 0 or (quality > 0 and quality < 85):`

#### Bug 2: Non-Deterministic Multi-Model Tie-Breaking (LOW)
**File:** `ml/signals/supplemental_data.py` ~line 131-134
**Issue:** `ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id ORDER BY ABS(edge) DESC)` has no secondary sort. If two models have the same highest edge for a player, BigQuery picks arbitrarily. Results could differ on retry.
**Fix:** Add `ORDER BY ABS(edge) DESC, system_id DESC` as tiebreaker.

#### Bug 3: Combo Direction Filters Not Applied (LOW)
**File:** `ml/signals/combo_registry.py` + `aggregator.py`
**Issue:** Some combos have `direction_filter='OVER_ONLY'` or `'UNDER_ONLY'`, but the aggregator only checks `combo_classification` (SYNERGISTIC/ANTI_PATTERN), not the direction filter. A combo meant to fire only on OVER picks could match an UNDER pick.
**Impact:** Low — all ANTI_PATTERN combos are direction-agnostic, so no incorrect blocking occurs today. But future direction-specific combos would be silently ignored.

#### Bug 4: Retrain Script Non-Deterministic Model Lookup (LOW)
**File:** `bin/retrain.sh` ~line 328
**Issue:** Latest model query sorts by `created_at DESC` without secondary sort. If two models share the same created_at timestamp, selection is arbitrary.
**Fix:** Add `ORDER BY created_at DESC, model_id DESC LIMIT 1`.

### Data Gap: Cross-Model Subsets Not Materialized

The `xm_*` cross-model observation subsets (`xm_consensus_3plus`, `xm_consensus_4plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement`) returned **zero rows** in BigQuery since December 2025. Either:
- The `CrossModelSubsetMaterializer` is not being called in production, or
- The materializer runs but no picks match the criteria (unlikely given 4+ active models), or
- Results are written to a different table/partition

**This means Layer 2 cross-model subsets are effectively dead.** They cannot graduate to active filtering because there's no grading data. Needs investigation.

### Operational Concerns

#### Sparse Post-ASB Best Bets
February 2026 best bets output is concerning:
- Feb 1-2: 5 picks/day, **80% HR** (excellent)
- Feb 5-11: 1-2 picks/day, mostly ungraded
- Feb 12-18: No data (ASB break, then retrain)

The system is producing far fewer than target 5 picks/day. Root cause: the pre-retrain model decay (V9 at 31-44% 7d HR) combined with MIN_SIGNAL_COUNT=2 and edge 5+ threshold created a very narrow funnel.

#### V12 Invisible Post-ASB
On Feb 18, V12 shows `INSUFFICIENT_DATA` with 0 graded 7d picks. The Session 308 fix for V12 MAE pattern mismatch (`catboost_v12` catch-all) may not have deployed yet, or the monthly V12 model (`catboost_v12_noveg_train1102_0205`) isn't generating predictions post-ASB.

### Filter Bypass Analysis

**Can a pick bypass negative filters?** No. The aggregator applies all 8 filters sequentially with no early returns that skip subsequent checks. The only way to bypass is:
1. Missing enrichment data (games_vs_opponent fails → avoid-familiar is disabled)
2. Quality score = 0 (Bug 1 above)
3. Prediction dict missing expected keys (handled by `.get()` with defaults)

These are defensive gaps, not architectural holes. The pipeline is fundamentally sound.

---

## 2. Model Transition Recommendation

### Recommendation: Strategy D (Edge-Conditional) with Modifications

After reviewing the decay state data, retrain script, and model performance history, **Strategy D** is the best fit — but modified to be simpler than originally proposed.

### The Data That Drives This Decision

**Pre-retrain decay was severe:**
| Date | V9 7d HR | V9 State | V9_Q43 7d HR | V9_Q45 7d HR |
|------|----------|----------|--------------|--------------|
| Feb 6 | 31.1% | BLOCKED | — | — |
| Feb 7 | 35.7% | BLOCKED | — | — |
| Feb 8 | 33.1% | BLOCKED | 66.7% | 60.0% |
| Feb 9 | 38.9% | BLOCKED | 60.0% | 60.0% |
| Feb 10 | 44.4% | BLOCKED | 53.8% | 42.9% |
| Feb 11 | 43.6% | BLOCKED | 45.2% | 50.0% |
| Feb 12 | 44.1% | BLOCKED | 51.3% | 60.0% |

The champion was losing money for 14 straight days while quantile models maintained 50-67% HR through much of it. This is the core problem: **a decaying champion bleeds money while perfectly good shadow models sit idle.**

**Post-retrain recovery was immediate:**
| Date | V9 7d HR | V9 State | V9_Q43 7d HR | V9_Q45 7d HR |
|------|----------|----------|--------------|--------------|
| Feb 18 | 60.0% | HEALTHY | 75.0% | 85.7% |

But N=5-8 per model — too small to confirm the retrain fixed things.

### Modified Strategy D: Decay-Gated Transition

```
IF old_model.state IN (HEALTHY, WATCH):
    → Shadow new model 3-5 days before promoting
    → Rationale: Old model is still profitable, no rush

IF old_model.state IN (DEGRADING, BLOCKED):
    → Promote new model immediately after gates pass
    → Rationale: Old model is losing money, every day of delay costs real dollars
    → Additionally: During the BLOCKED period BEFORE retrain completes,
      use highest-edge from ANY active model (multi-model already does this)
```

### Why Not the Other Strategies?

**A. Instant switch (current):** Acceptable when model is decaying, wasteful when model is healthy. The Feb 6-12 period proves that fast switching matters during decay. But when V9 is at 63% HR, there's no urgency to swap in an untested replacement.

**B. Shadow period (always):** Would have cost real money during the 14-day BLOCKED period. If the old model is at 31-44% HR, waiting 3-5 more days for shadow validation means 3-5 more days of losses.

**C. Hybrid/gradual:** Over-engineered. The edge threshold is already 5+, and splitting by edge 5-7 vs 7+ creates too many code paths for minimal benefit.

**D (original). Always use decay state:** Close to our recommendation, but the original proposal didn't account for the "bridge" — what happens during the days between decay detection and retrain completion.

### The Bridge Problem (Critical Insight)

The real gap is NOT the transition moment (old → new model). It's the **bridge period** — the days between when the champion enters BLOCKED and when the retrain completes and deploys. During Feb 6-12:
- V9 was BLOCKED (31-44% HR)
- Retrain hadn't happened yet (ASB break)
- Best bets continued using V9 as primary source
- Quantile models were profitable but not prioritized

**Solution:** The multi-model candidate generation (Session 307 Phase A) already solves this — it picks the highest-edge prediction across ALL models. If V9's predictions have low edge during decay, the system automatically shifts to whichever model has higher edge. **No code change needed for the bridge**, just verification that Phase A is working in production.

### Implementation Plan

1. **Add decay state to retrain decision** — `retrain.sh` should check `model_performance_daily` and adjust behavior:
   - If champion is HEALTHY/WATCH: `--promote` flag requires 3-day shadow (add `--shadow-days 3`)
   - If champion is DEGRADING/BLOCKED: `--promote` promotes immediately (current behavior)
2. **Verify Phase A multi-model is active** — Check that non-V9 models are sourcing best bets during V9 decay
3. **Add retrain urgency to Slack alerts** — decay-detection CF already sends alerts; add "RETRAIN RECOMMENDED" to BLOCKED state alerts

### Interaction with Weekly Retraining

With 7-day cadence and 42-day rolling window (Session 284), the maximum time a champion can be in BLOCKED before retrain is ~7 days (next scheduled retrain). The retrain-reminder CF sends Slack+SMS at 7 days. This is tight enough that the "instant switch when BLOCKED" approach limits downside to at most one retrain cycle.

---

## 3. Filter Transferability Analysis

### Current Negative Filters (8 active in aggregator.py)

| # | Filter | Current Data | Classification | Transfer? |
|---|--------|-------------|----------------|-----------|
| 1 | **Player blacklist** (<40% HR, N>=8, edge 3+) | 5 players at 0%, 15 more at <18% HR | **MODEL-SPECIFIC** | Recompute after retrain |
| 2 | **Avoid familiar** (6+ games vs opponent) | Not directly queried | **MARKET-STRUCTURAL** | Transfers |
| 3 | **Edge floor** (edge < 5.0) | Edge 5+ = 60.3% HR, below 5 loses money | **MARKET-STRUCTURAL** | Transfers |
| 4 | **UNDER edge 7+ block** | V9-specific: **37.9% HR** (N=29); all-model: 57.8% (N=993) | **MODEL-SPECIFIC** | Re-validate per champion |
| 5 | **Feature quality floor** (< 85) | Previously 24% HR when quality low | **MODEL-SPECIFIC** | Re-validate threshold |
| 6 | **Bench UNDER block** (line < 12) | 53.9% HR (N=760) — marginal | **MARKET-STRUCTURAL** | Transfers |
| 7 | **UNDER + line jumped 2+** | Originally 38.2% HR | **MARKET-STRUCTURAL** | Transfers |
| 8 | **UNDER + line dropped 2+** | Originally 35.2% HR | **MARKET-STRUCTURAL** | Transfers |

### UNDER Edge 7+ Block: Confirmed Model-Specific

The all-model data initially showed 57.8% HR (N=993) for UNDER edge 7+, suggesting the filter might be wrong. But **V9-specific data tells a different story:**

| Edge Bucket | Direction | N | HR | Source |
|-------------|-----------|---|-----|--------|
| edge_7plus | OVER | 62 | **79.0%** | V9 only |
| edge_7plus | UNDER | 29 | **37.9%** | V9 only |
| edge_7plus | UNDER | 993 | 57.8% | All models |

The V9 champion at 37.9% HR (N=29) confirms the filter is justified. The all-model 57.8% was misleading because other models (Q43, Q45, V12) don't have this failure mode — they handle extreme UNDER edges better. This makes the filter **model-specific, not market-structural**.

**Recommendation:** Keep the filter for V9. After each retrain, re-validate: run champion-specific UNDER edge 7+ query on the eval window. If the new champion's UNDER edge 7+ HR is above 52.4%, the filter can be removed for that model version. **Every retrain should trigger a filter validation check.**

### Filter Classification Rules

After this analysis, here's the framework for future retrains:

**Market-Structural Filters (carry forward automatically):**
- Edge floor (5.0) — fundamental to profitability
- Line movement UNDER blocks — market information asymmetry
- Avoid familiar — market efficiency for frequently-played matchups
- Bench UNDER block — structural market pricing pattern

**Model-Specific Filters (recompute after each retrain):**
- Player blacklist — different models predict differently for same players
- Feature quality threshold — model sensitivity to feature quality varies
- UNDER edge 7+ block — appears to be model/time-specific, not structural

**Revalidation Protocol (run after each retrain):**
```sql
-- Run against eval window predictions for NEW model
-- For each model-specific filter, check if the pattern holds
-- If HR for filtered group > 52.4% (breakeven), filter is no longer justified
```

---

## 4. Cross-Model Subset Assessment

### Status: NOT WORKING

The 5 cross-model observation subsets (`xm_consensus_3plus`, `xm_consensus_4plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement`) returned **zero rows** from `current_subset_picks` since December 2025.

### Likely Root Cause

The `CrossModelSubsetMaterializer` (in `data_processors/publishing/cross_model_subset_materializer.py`) needs to be called as part of the daily pipeline. Based on code review:
1. It's called from the best bets export flow
2. It depends on `discover_models()` finding active models
3. It writes with `system_id='cross_model'`

Possible failure points:
- The materializer may be failing silently (non-blocking try/except in the exporter)
- The model discovery may not find enough models to satisfy subset criteria (e.g., `xm_consensus_3plus` needs 3+ models agreeing)
- The subset criteria may be too strict (all quantile models must agree, both V9 and V12 must be present)

### Assessment of Subset Definitions

Even without grading data, the subset definitions can be evaluated on logic:

| Subset | Criteria | Assessment |
|--------|----------|------------|
| `xm_consensus_3plus` | 3+ models agree, edge >= 3 | **REASONABLE** — basic consensus |
| `xm_consensus_4plus` | 4+ models agree, top 5 | **TOO STRICT** — rarely fires with 4 active models |
| `xm_quantile_agreement_under` | All quantile models UNDER | **INTERESTING** — quantile models specialize in tails |
| `xm_mae_plus_quantile_over` | MAE + quantile OVER | **REASONABLE** — cross-loss agreement |
| `xm_diverse_agreement` | V9 + V12 agree, edge >= 3 | **ANTI-CORRELATED** — Session 297 found V9+V12 agreement hurts HR |

### Recommendation

1. **Fix the materializer** — Investigate why no xm_* rows are being written. Check logs for silent failures.
2. **Drop `xm_diverse_agreement`** — V9+V12 agreement is known anti-correlated (33.3% OVER HR when both agree, per Session 297). Tracking this subset only confirms a known bad pattern.
3. **Rename `xm_consensus_4plus` to `xm_consensus_5plus`** — With 6 models, 5+ agreement is a stronger signal than 4+.
4. **Add `xm_quantile_under_high_edge`** — Quantile UNDER agreement at edge 5+ specifically. Quantile models showed 60-86% 7d HR post-retrain.
5. **Do not graduate any subset** until at least 50 graded observations exist.

---

## 5. Signal System Assessment

### The Dual Role: Annotation + Gate

Signals currently serve two roles:
1. **Annotation** — Each pick gets `pick_angles` explaining why it was selected (transparency)
2. **Gate** — `MIN_SIGNAL_COUNT = 2` requires every best bet to have at least 2 qualifying signals (model_health + 1 real signal)

### Is MIN_SIGNAL_COUNT = 2 Correct?

**BQ data confirms it's the right floor:**

| Signal Count | N Picks | HR |
|-------------|---------|-----|
| 2 | 89 | 55.1% |
| 3 | 11 | 63.6% |
| 4 | 7 | 85.7% |
| 6 | 9 | 77.8% |
| 7 | 3 | 100.0% |

The relationship is **monotonically increasing** — more signals = higher HR. However:
- Signal count = 2 is still profitable (55.1% > 52.4% breakeven)
- Raising the floor to 3 would eliminate 89/(89+11+7+9+3+2+2) = 72% of best bets picks
- The volume loss from raising to MIN_SIGNAL_COUNT=3 would be devastating

**Verdict:** MIN_SIGNAL_COUNT = 2 is correct as a floor. Signal count should be used as a **tiebreaker** when ranking picks at the same edge level, not as a harder gate.

### Does the Annotation-Only Approach Work?

The Session 297 shift from signal-scored to edge-first was correct (71.1% vs 59.8%). But the data shows signals DO have independent predictive value:
- Edge 5+ with real signal: 72.9% HR (from doc analysis)
- Edge 5+ without signal: 58.4% HR
- Lift: **+14.5 percentage points**

This suggests signals should evolve from pure annotation toward a **secondary ranking factor**. The path:
1. **Now:** Edge ranks, signals annotate (current)
2. **Next:** At equal edge, prefer picks with more/stronger signals (tiebreaker)
3. **Future:** At edge 5-7 (the sweet spot where signal lift is highest), signals influence ranking

### Signal Graduation Status

From the documentation analysis, only two signals are close to graduation:

| Signal | Edge 5+ HR | Edge 5+ N | Independent Lift | Temporal | Cross-Model | Ready? |
|--------|-----------|-----------|-----------------|----------|-------------|--------|
| combo_he_ms | 78.8% | 33 | +27.9pp | 1 window | V9 only | **NO** (N < 50) |
| combo_3way | 73.8% | 42 | +17.2pp | 1 window | V9 only | **NO** (N < 50) |
| bench_under | 76.9% | — | Not measured at 5+ | — | — | **NO** (no edge 5+ data) |

**None ready to graduate.** All need more sample size and cross-model validation.

### Proposed Signal Evolution (Conservative)

**Phase 1 (Now):** Keep annotation-only + MIN_SIGNAL_COUNT=2. No changes.

**Phase 2 (When combo_he_ms hits N=50 at edge 5+):** Add signal_count as tiebreaker to `composite_score`:
```python
composite_score = edge + (0.01 * signal_count)  # Negligible tiebreaker
```
This preserves edge-first while breaking ties in favor of better-signaled picks.

**Phase 3 (When 3+ signals hit graduation gates):** Build a signal-aware bucket for edge 5-7 specifically:
```python
if 5 <= edge < 7 and signal_count >= 3:
    composite_score = edge + 0.5  # Priority boost within 5-7 band
```
This lets strong signals lift edge 5-7 picks above weak edge 5-7 picks, without disrupting edge 7+ rankings.

---

## 6. Concrete Next Steps (Ordered)

### Immediate (This Week)

1. **Fix feature quality score = 0 bypass** — One-line fix in `aggregator.py`. Bug 1 from Section 1.
2. **Investigate xm_* materialization failure** — Check exporter logs for CrossModelSubsetMaterializer errors. The entire Layer 2 cross-model system is non-functional.
3. **Verify Phase A multi-model is active** — Run query against `signal_best_bets_picks` for `source_model_family != 'v9_mae'`. Current data shows only v9_mae sourcing picks.

### Short-Term (Next 1-2 Sessions)

4. **Re-validate UNDER edge 7+ block** — Run champion-specific (not all-model) query. If V9-specific UNDER edge 7+ HR > 52.4%, remove the filter. Current all-model data shows 57.8%.
5. **Add non-deterministic tiebreaker** — Fix Bug 2 (supplemental_data.py ROW_NUMBER) and Bug 4 (retrain.sh model lookup).
6. **Implement decay-gated promotion** — Modify `retrain.sh` to check `model_performance_daily` state. BLOCKED/DEGRADING → instant promote. HEALTHY/WATCH → 3-day shadow.

### Medium-Term (Next 2-4 Weeks)

7. **Build filter revalidation protocol** — After each retrain, auto-run a filter validation query against the eval window. Flag model-specific filters that no longer justify their threshold.
8. **Add signal_count as tiebreaker** — Add `0.01 * signal_count` to composite_score. Minimal change, preserves edge-first, breaks ties meaningfully.
9. **Drop xm_diverse_agreement subset** — V9+V12 agreement is anti-correlated. Replace with `xm_quantile_under_high_edge`.

### Longer-Term (1+ Month)

10. **Build weekly report card** — Performance cube across model x direction x edge bucket x player tier x signal tier. Automated weekly, replaces ad-hoc session analysis.
11. **Signal graduation tracking** — BQ table updated weekly with each signal's N, HR, lift at edge 5+. Auto-flags when graduation gates are met.
12. **Direction-aware model trust** — When sufficient multi-model data exists (30+ graded OVER and UNDER per model), implement Bayesian direction-specific trust multiplier for edge ranking.

---

## Appendix: Key Data Tables

### Direction x Edge Performance (All Models, Since Dec 2025)

| Direction | Edge 5-7 HR | Edge 7+ HR | Total N |
|-----------|------------|------------|---------|
| OVER | 60.3% (N=620) | 68.9% (N=769) | 1,389 |
| UNDER | 56.2% (N=1,354) | 57.8% (N=993) | 2,347 |

### Player Tier x Direction (All Models, Edge 5+, Since Dec 2025)

| Tier (Line) | OVER HR | OVER N | UNDER HR | UNDER N |
|-------------|---------|--------|----------|---------|
| Bench (<12) | **75.5%** | 699 | 53.9% | 760 |
| Mid (12-18) | 58.6% | 362 | 58.0% | 796 |
| Starter (18+) | 50.0% | 328 | 58.5% | 791 |

**Key insight:** Bench OVER (75.5%) is the best cell. Starter OVER (50.0%) is breakeven — the model's OVER predictions on high-line players are no better than coin flip.

### Model Decay Timeline (Feb 2026)

| Date | V9 State | V9 7d HR | V12 State | Q43 State | Q45 State |
|------|----------|----------|-----------|-----------|-----------|
| Feb 6 | BLOCKED | 31.1% | DEGRADING | — | — |
| Feb 8 | BLOCKED | 33.1% | BLOCKED | HEALTHY | HEALTHY |
| Feb 9 | BLOCKED | 38.9% | WATCH | HEALTHY | HEALTHY |
| Feb 12 | BLOCKED | 44.1% | BLOCKED | BLOCKED | HEALTHY |
| Feb 18 | HEALTHY | 60.0% | INSUFF | HEALTHY | HEALTHY |

### Player Blacklist (Top 10 by Volume, Edge 3+, Since Dec 2025)

| Player | N | HR | Should Block? |
|--------|---|-----|---------------|
| rjbarrett | 43 | 14.0% | **YES** |
| austinreaves | 33 | 12.1% | **YES** |
| franzwagner | 26 | 15.4% | **YES** |
| domantassabonis | 23 | 17.4% | **YES** |
| deanthonymelton | 22 | 13.6% | **YES** |
| jalengreen | 20 | 15.0% | **YES** |
| willriley | 19 | 15.8% | **YES** |
| kobesanders | 19 | 15.8% | **YES** |
| yanickonanniederhauser | 18 | 16.7% | **YES** |
| kenrichwilliams | 17 | 5.9% | **YES** |

Note: These are **model-specific** — a retrained model may predict differently for these players. The blacklist must be recomputed after each retrain.
