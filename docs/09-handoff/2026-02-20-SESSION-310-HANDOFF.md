# Session 310 Handoff — Best Bets Review + Bug Fixes + Open Architecture Decisions

**Date:** 2026-02-20
**Focus:** End-to-end best bets system review, 4 bug fixes, model transition strategy, filter transferability analysis, signal/subset architecture clarification
**Project docs:** `docs/08-projects/current/best-bets-v2/`

---

## What Was Done

### 1. Full System Review (3 Parallel Research Agents)

Read all 6 architecture docs, 11 code files, and ran 10 BQ validation queries. Full findings in `docs/08-projects/current/best-bets-v2/06-SESSION-310-REVIEW.md`.

### 2. Bug Fixes (4 changes)

**Bug 1 — Quality score=0 bypass (MEDIUM):**
- **File:** `ml/signals/aggregator.py:137`
- **Was:** `if quality > 0 and quality < 85:` — quality=0 (missing) passed through
- **Now:** `if quality < 85:` — blocks missing quality scores
- **Impact:** Picks with no quality data could have slipped into best bets

**Bug 2 — ROW_NUMBER tiebreaker (LOW):**
- **File:** `ml/signals/supplemental_data.py:133`
- **Was:** `ORDER BY ABS(amp.edge) DESC` — non-deterministic on tied edges
- **Now:** `ORDER BY ABS(amp.edge) DESC, amp.system_id DESC` — deterministic tiebreaking

**Bug 3 — Retrain model lookup tiebreaker (LOW):**
- **File:** `bin/retrain.sh:331`
- **Was:** `ORDER BY created_at DESC LIMIT 1` — non-deterministic on same timestamp
- **Now:** `ORDER BY created_at DESC, model_id DESC LIMIT 1`

**Bug 4 — Silent xm_* exception swallowing:**
- **File:** `backfill_jobs/publishing/daily_export.py:300`
- **Was:** `logger.warning(f"... {e}")` — no traceback
- **Now:** `logger.warning(f"... {e}", exc_info=True)` — full traceback logged

### 3. UNDER Edge 7+ Filter Validated

Ran V9-specific query (not all-model). **V9 UNDER edge 7+ = 37.9% HR (N=29).** The all-model number (57.8%) was misleading because other models handle extreme UNDER edges better. Filter stays. This is a **model-specific** pattern, not market-structural.

### 4. xm_* Materialization Failure Diagnosed

Cross-model subsets have zero rows since Dec 2025. Root cause: `CrossModelSubsetMaterializer.materialize()` throws an exception that was caught and silently ignored. Most likely `discover_models()` finds < 2 families (early return) or fails entirely. The `exc_info=True` fix will surface the actual error in production logs. **Next session needs to check logs and fix the underlying issue.**

---

## Open Architecture Decisions for Next Session

### DECISION 1: Signal Subsets — YES, Create Them

**Context:** We've gone back and forth on this. Session 308 said "signals should NOT be subsets." But the user's intent (confirmed this session) is that **high-performing signals/combos SHOULD have their own subsets** and should be eligible for direct best bets inclusion when HR is very high.

**The case FOR signal subsets:**
- `combo_he_ms`: 78.8% HR at edge 5+, N=33 (approaching graduation N=50)
- `combo_3way`: 73.8% HR at edge 5+, N=42
- `bench_under`: 76.9% HR overall
- Signal count is monotonically predictive: 2 signals=55.1%, 4=85.7%, 7=100%
- These are strong enough to justify direct tracking as subsets

**What to build:**
1. Create signal-based subsets in `dynamic_subset_definitions` for the top signals:
   - `signal_combo_he_ms` — picks where combo_he_ms fires + edge >= 5
   - `signal_combo_3way` — picks where combo_3way fires + edge >= 5
   - `signal_bench_under` — picks where bench_under fires + edge >= 5
   - `signal_high_signal_count` — picks with 4+ qualifying signals + edge >= 5
2. Write these to `current_subset_picks` (same as model subsets)
3. Grade them via existing `SubsetGradingProcessor`
4. **Graduation path:** When a signal subset hits N>=50 and HR>=65% at edge 5+, it becomes eligible to directly produce best bets picks (independent of the aggregator's normal flow)

**Key distinction:** These are NOT "18 signals x 6 models = 108 subsets." They are **4-6 curated signal subsets** for the strongest patterns only. The 18 signals continue to annotate picks; only the proven ones get subset tracking.

**Where to implement:** Either a new `SignalSubsetMaterializer` alongside `CrossModelSubsetMaterializer`, or extend `SubsetMaterializer` to support signal-based subset definitions.

### DECISION 2: Filter Maintenance on Retrain

**The problem:** When we retrain the champion, the negative filters were tuned to the OLD model's behavior. Some filters are market-structural (always transfer), some are model-specific (may not transfer).

**Recommended approach — Inherit + Validate:**

1. **On retrain, inherit ALL filters from predecessor.** Don't start fresh.
2. **Run a filter validation query on the eval window** for each model-specific filter:
   ```sql
   -- For each model-specific filter, check if pattern holds for NEW model
   -- Example: UNDER edge 7+ block
   SELECT ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = '{new_model_id}'
     AND recommendation = 'UNDER'
     AND ABS(predicted_points - line_value) >= 7
     AND game_date BETWEEN '{eval_start}' AND '{eval_end}'
   ```
3. **If a model-specific filter's HR for the NEW model is above breakeven (52.4%)**, flag it for review but don't auto-remove. The filter stays until manually approved for removal.
4. **Player blacklist recomputes dynamically** from recent prediction_accuracy, so it naturally updates as the new model accumulates grading data.

**Filter classification (for reference):**

| Filter | Classification | On Retrain |
|--------|---------------|------------|
| Edge floor (5.0) | Market-structural | Inherit, never change |
| Line movement UNDER blocks | Market-structural | Inherit |
| Bench UNDER block | Market-structural | Inherit |
| Avoid familiar | Market-structural | Inherit |
| UNDER edge 7+ block | **Model-specific** | Inherit, validate on eval window |
| Player blacklist | **Model-specific** | Auto-recomputes from data |
| Feature quality floor (85) | **Model-specific** | Inherit, validate threshold |

**What to build:**
- Add a `--validate-filters` flag to `retrain.sh` that runs the validation queries after training
- Output a report: "Filter X: HR on eval window = Y%. Threshold = 52.4%. Status: CONFIRMED/REVIEW_NEEDED"
- Do NOT auto-remove filters. Human reviews the report and decides.

### DECISION 3: Model Transition Strategy (Decay-Gated)

**Recommended (from review):**
- If old model is HEALTHY/WATCH → shadow new model 3-5 days before promoting
- If old model is DEGRADING/BLOCKED → promote immediately
- Multi-model candidate generation (Phase A) acts as bridge during decay

**What to build:**
- Modify `retrain.sh --promote` to check `model_performance_daily` for champion's current state
- If BLOCKED/DEGRADING: promote immediately (current behavior)
- If HEALTHY/WATCH: register as shadow, add to scheduler for auto-promote in 3 days
- Add "RETRAIN RECOMMENDED" to decay-detection Slack alerts when state = BLOCKED

---

## Key Data Points (For Next Session Reference)

### Model Performance (Feb 18, post-ASB retrain)
| Model | 7d HR | 14d HR | State | N (7d) |
|-------|-------|--------|-------|--------|
| catboost_v9 | 60.0% | 44.3% | HEALTHY | 5 |
| v9_q43 | 75.0% | 51.3% | HEALTHY | 8 |
| v9_q45 | 85.7% | 60.0% | HEALTHY | 7 |
| catboost_v12 | null | 50.0% | INSUFFICIENT | 0 |

### Direction x Edge (V9 only, since Dec 2025)
| Direction | Edge 5-7 | Edge 7+ |
|-----------|----------|---------|
| OVER | 60.7% (N=56) | **79.0%** (N=62) |
| UNDER | 58.3% (N=60) | **37.9%** (N=29) |

### Player Tier x Direction (All models, edge 5+)
| Tier | OVER HR (N) | UNDER HR (N) |
|------|-------------|--------------|
| Bench (<12) | **75.5%** (699) | 53.9% (760) |
| Mid (12-18) | 58.6% (362) | 58.0% (796) |
| Starter (18+) | 50.0% (328) | 58.5% (791) |

### Signal Count on Best Bets
| Signals | N | HR |
|---------|---|-----|
| 2 | 89 | 55.1% |
| 3 | 11 | 63.6% |
| 4 | 7 | 85.7% |
| 6+ | 14 | 84.6% |

### Player Blacklist (worst at edge 3+, N>=8)
Top offenders: isaiahjackson (0%, N=12), devincarter (0%, N=13), baylorscheierman (0%, N=14), austinreaves (12.1%, N=33), rjbarrett (14.0%, N=43), franzwagner (15.4%, N=26), domantassabonis (17.4%, N=23)

---

## Files Changed This Session

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Quality score=0 bypass fix |
| `ml/signals/supplemental_data.py` | ROW_NUMBER tiebreaker |
| `bin/retrain.sh` | Model lookup tiebreaker |
| `backfill_jobs/publishing/daily_export.py` | xm_* exc_info logging |
| `docs/08-projects/current/best-bets-v2/06-SESSION-310-REVIEW.md` | Full review document |
| `docs/09-handoff/2026-02-20-SESSION-310-HANDOFF.md` | This handoff |

---

## Known Issues / Gaps

### CRITICAL: Layer 2 Cross-Model Subsets Are Broken (Zero Data)

The 5 cross-model observation subsets (`xm_consensus_3plus`, `xm_consensus_4plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement`) have **zero rows in BigQuery since December 2025**. This means:
- Layer 2 of the 3-layer multi-model architecture is completely non-functional
- No grading data exists for any cross-model consensus pattern
- We cannot evaluate whether model consensus predicts outcomes
- The `qualifying_subsets` field on best bets picks never includes xm_* entries

**Root cause:** `CrossModelSubsetMaterializer.materialize()` throws an exception during the daily export pipeline. The exception was silently caught and ignored (`non-fatal` handler with no traceback). This session added `exc_info=True` so the actual error will appear in production logs after next deploy.

**Most likely failure point:** `discover_models()` in `shared/config/cross_model_subsets.py` queries `prediction_accuracy` (grading data) for active system_ids. If a model has no graded predictions on a date, it won't be discovered. With < 2 model families found, the materializer returns early with 0 picks (line 63-69 of `cross_model_subset_materializer.py`).

**To fix:**
1. Deploy the exc_info change and check Cloud Logging for the actual exception
2. If it's the family_count < 2 issue, consider querying `player_prop_predictions` (prediction data) instead of `prediction_accuracy` (grading data) for model discovery — predictions exist same-day, grading lags by 1+ days
3. Verify the fix produces xm_* rows, then backfill recent dates

**Code path:** `backfill_jobs/publishing/daily_export.py` (line 285-300) → `data_processors/publishing/cross_model_subset_materializer.py` → `shared/config/cross_model_subsets.py:discover_models()`

---

## Priority Order for Next Session

1. **Fix xm_* materialization (CRITICAL)** — Layer 2 is completely broken. Check production logs for the actual exception now that exc_info=True is deployed. Fix the underlying issue (likely `discover_models()` not finding enough families). See "Known Issues" section above.
2. **Create signal subsets** — Build 4-6 curated signal subsets for top-performing signals. Grade them. This is the long-requested feature.
3. **Add filter validation to retrain.sh** — `--validate-filters` flag that checks model-specific filters against eval window.
4. **Implement decay-gated promotion** — Check champion's decay state before promoting.
5. **Verify Phase A multi-model** — Only v9_mae has sourced best bets picks so far. Check why non-V9 models aren't producing higher-edge picks for any players.

---

## What NOT to Do

- Do NOT remove the UNDER edge 7+ filter — confirmed 37.9% HR for V9 specifically
- Do NOT create 108 signal x model subsets — only create curated subsets for top 4-6 signals
- Do NOT add consensus_bonus back to ranking — V9+V12 agreement is anti-correlated
- Do NOT use confidence_score for filtering — all V9 tiers cluster 28-34% HR
