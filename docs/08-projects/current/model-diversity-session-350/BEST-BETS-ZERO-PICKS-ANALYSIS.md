# Best Bets Zero-Picks Analysis — Feb 27, 2026

## Problem

Best bets exported **0 picks** on Feb 27 despite 704 active predictions across 11 models and 5 games. This is a systemic issue, not a one-day anomaly — the filter pipeline will produce 0 picks on most days while all models remain BLOCKED.

## Filter Pipeline Trace (from JSON metadata)

```
50 multi-model candidates (highest edge per player, after dedup)
  │
  ├─ edge_floor (≥ 5.0):     49 BLOCKED  ← primary bottleneck
  │                            1 passes (Jokic UNDER 28.5, edge 9.7)
  │
  ├─ signal_density:           1 BLOCKED  ← Jokic only has base signals
  │
  └─ Result: 0 picks
```

**Every other filter rejected 0 candidates** — blacklist, affinity, quality, bench_under, line delta, neg_pm_streak, anti-pattern all passed. The problem is exclusively edge_floor + signal_density.

## Root Cause: Cascading Signal Desert

When all models are BLOCKED, a cascading failure prevents ANY picks from being generated:

```
Models BLOCKED (all below 52.4% breakeven)
    │
    ├─ Fewer high-edge predictions generated (models miscalibrated)
    │   └─ Only 1 of 50 candidates has edge ≥ 5.0
    │
    ├─ high_edge signal doesn't fire for edge < 5 picks
    │
    ├─ model_health fires (always-on) but is a BASE signal
    │
    ├─ Contextual signals are rare (depend on game conditions)
    │   └─ Only 1 of 21 edge 3+ candidates has ANY contextual signal
    │
    └─ Result: edge 5+ picks fail signal_density (only base signals)
              edge 3-4 picks fail signal_count (only 1 signal: model_health)
```

## Data: Today's Candidate Pool

### After multi-model dedup (13 unique players, edge ≥ 3)

| Player | Model | Direction | Edge | Line | Signals (Phase 5) | Blocked By |
|--------|-------|-----------|------|------|--------------------|------------|
| Jokic | V12 | UNDER | 9.7 | 28.5 | high_edge, edge_spread_optimal | signal_density |
| J. Brown | V12_noveg_q43 | UNDER | 4.3 | 27.5 | none | edge_floor + signal_count |
| C. Holmgren | V12 | UNDER | 4.2 | 16.5 | none | edge_floor + signal_count |
| B. Williams | V12_noveg_q43 | UNDER | 4.1 | 17.5 | none | edge_floor + signal_count |
| J. Brunson | V12_noveg_q43 | UNDER | 4.0 | 26.5 | none | edge_floor + signal_count |
| S. Hauser | V12 | OVER | 3.8 | 9.5 | none | edge_floor + signal_count |
| I. Hartenstein | V12 | UNDER | 3.6 | 9.5 | none | edge_floor + signal_count |
| KAT | V12 | UNDER | 3.6 | 19.5 | none | edge_floor + signal_count |
| **I. Joe** | **v9_low_vegas** | **OVER** | **3.4** | **9.5** | **prop_line_drop_over** | **edge_floor only** |
| GG Jackson | V12 | UNDER | 3.4 | 16.5 | none | edge_floor + signal_count |
| J. Duren | V12 | UNDER | 3.2 | 18.5 | none | edge_floor + signal_count |
| B. Portis | v9_low_vegas | OVER | 3.1 | 9.5 | none | edge_floor + signal_count |
| C. Cunningham | V12 | UNDER | 3.1 | 25.5 | none | edge_floor + signal_count |

**Key observation:** Only Isaiah Joe has a non-base contextual signal. He's the only candidate that would pass all filters if the edge floor were lowered to 3.0.

### Directional concentration

88.9% UNDER for V12 edge 3+ picks (8 UNDER, 1 OVER). Near the >90% critical threshold. Every model is showing RED (UNDER_HEAVY) signal today.

## Data: V12 Edge-Performance Is Inverted

The edge floor at 5.0 assumes higher edge = better performance. **Over the last 45 days, V12 shows the opposite:**

| Edge Band | OVER HR | OVER N | UNDER HR | UNDER N |
|-----------|---------|--------|----------|---------|
| **3-4** | **66.7%** | **15** | **55.2%** | **67** |
| 4-5 | 50.0% | 4 | 44.8% | 29 |
| 5-7 | 33.3% | 3 | 47.6% | 21 |
| 7+ | — | 0 | 100.0% | 1 |

Edge 3-4 is the **best-performing band** for V12 right now. The edge floor at 5.0 is filtering OUT the most profitable picks.

### All-model aggregate (45 days)

| Edge Band | OVER HR | OVER N | UNDER HR | UNDER N |
|-----------|---------|--------|----------|---------|
| 3-4 | 52.1% | 453 | 51.4% | 842 |
| 4-5 | 52.1% | 215 | 51.7% | 449 |
| 5-7 | 44.1% | 186 | 51.1% | 393 |
| 7+ | 55.9% | 111 | 52.4% | 191 |

All-model shows a flat profile — edge is NOT predictive of accuracy in the current regime. Edge 5-7 OVER is the worst band at 44.1%.

### Model-direction affinity data (from JSON)

| Group | Direction | Edge Band | HR | N |
|-------|-----------|-----------|-----|---|
| **v12_vegas OVER** | **OVER** | **3-5** | **63.5%** | **104** |
| v9 OVER | OVER | 7+ | 70.8% | 24 |
| v9_low_vegas | UNDER | 3-5 | 55.2% | 29 |
| v12_vegas | UNDER | 3-5 | 54.3% | 243 |
| v9 OVER | OVER | 3-5 | 54.1% | 183 |
| v12_noveg | OVER | 3-5 | 52.9% | 17 |
| v12_noveg | UNDER | 3-5 | 49.4% | 160 |
| v12_vegas | UNDER | 5-7 | 47.7% | 44 |

**v12_vegas OVER at edge 3-5 is the single best combo at 63.5% HR (N=104).** Today's Sam Hauser OVER 9.5 (edge 3.8) from V12 falls into this exact combo but is blocked by the edge floor.

## Options Evaluated

### Option A: Edge ≥7 bypasses signal density

**What:** Skip signal_density filter for picks with edge ≥ 7.0.

**Impact today:** +1 pick (Jokic UNDER 28.5 at edge 9.7 from V12)

**Data for:**
- All-model edge 7+ OVER = 55.9% (N=111), UNDER = 52.4% (N=191) — both above breakeven
- At extreme edge, the conviction itself is informative — requiring additional contextual signals may be over-filtering
- Very rare picks (1-2 per day max), minimal risk of flooding

**Data against:**
- V12 is BLOCKED at 48.1% 7d HR — the model generating this pick is broken
- Jokic prediction of 18.8 vs 28.5 line — predicting a 28+ PPG player to score 18.8 suggests model miscalibration
- V12 edge 5-7 UNDER = 47.6% (N=21) — below breakeven for this model at high edge
- The signal density filter may be accidentally protecting us from a miscalibrated model

**Verdict:** Low-risk structural change (very few picks affected), but today's specific pick (Jokic) looks like miscalibration rather than genuine signal. **Marginal.**

**Code change:** `ml/signals/aggregator.py` line ~270:
```python
# Signal density filter — bypass for extreme edge (≥ 7)
tag_set = frozenset(tags)
if tag_set and tag_set.issubset(BASE_SIGNALS) and pred_edge < 7.0:
    filter_counts['signal_density'] += 1
    continue
```

### Option B: Lower edge floor from 5.0 → 3.0

**What:** Reduce MIN_EDGE from 5.0 to 3.0.

**Impact today:** +0 picks. 12 more candidates enter the filter chain, but all except Isaiah Joe fail signal_count (only have model_health = 1 signal, need 2). Isaiah Joe OVER 9.5 from v9_low_vegas would pass (has prop_line_drop_over).

**Data for:**
- V12 edge 3-4 is the best-performing band: OVER 66.7% (N=15), UNDER 55.2% (N=67)
- The 5.0 floor was calibrated when models were healthy; it's now counterproductive
- Other filters (signal_count, signal_density, affinity) provide quality gates

**Data against:**
- All-model edge 3-4 aggregate is marginal: OVER 52.1%, UNDER 51.4%
- Isaiah Joe's specific combo (v9_low_vegas OVER 3-4) = 33.3% HR (N=6) — terrible, though tiny sample
- Lowering alone has near-zero impact without also relaxing signal requirements

**Verdict:** Conceptually correct (edge floor is too high for degraded models), but **ineffective alone** because signal checks block everything anyway.

### Option C: Lower MIN_SIGNAL_COUNT from 2 → 1

**What:** Allow picks with just 1 qualifying signal (instead of requiring model_health + 1 contextual).

**Impact today (if combined with B):** Several picks would pass with only model_health as their signal. This effectively removes signal filtering since model_health always fires.

**Data for:**
- The 2-signal minimum was designed assuming model_health provides a "free" baseline + you need 1 contextual signal. When models are BLOCKED, the bar stays the same but contextual signals are rare.
- Reduces the dead zone during model degradation periods

**Data against:**
- model_health always fires → MIN_SIGNAL_COUNT = 1 means EVERY prediction with edge ≥ floor passes
- This removes the entire signal quality layer
- Session 259 added min 2 specifically because 1-signal picks underperformed

**Verdict:** **Too aggressive.** Removes the quality gate entirely.

### Option D: Lower edge floor to 3.0 + edge ≥7 signal density bypass (A + B)

**Impact today:** +1 pick — Jokic UNDER 28.5 (from signal density bypass). Isaiah Joe OVER 9.5 would also pass (edge 3.4, has contextual signal).

**Verdict:** Most balanced option. Gets 1-2 picks on sparse days without dismantling the signal quality framework.

### Option E (not recommended): Remove signal density filter entirely

**Data:** Session 348 showed base-only picks = 57.1% HR vs 4+ signals = 77.8% HR (gap: +20.7pp). This filter adds significant value.

**Verdict:** **Never.** The data strongly supports keeping this filter.

## The Real Fix: Model Retraining

All of these filter adjustments are band-aids. The systemic problem is:

1. **All models are BLOCKED** — V12 at 48.1% 7d, V9 at 36.8% 7d
2. **Degraded models produce fewer high-edge picks** (edge distribution collapses)
3. **Edge-performance inverts** (higher edge ≠ better when model is miscalibrated)
4. **Signal desert follows** (fewer qualifying picks = fewer signal-rich picks)

Fresh models → better edge calibration → more edge 5+ picks → more signal diversity → more best bets. This is the only sustainable path.

## Recommendation

### Short-term (can implement now)

**Option D: Lower edge floor to 3.0 + edge ≥7 signal density bypass.**

Two changes:
1. `ml/signals/aggregator.py`: `MIN_EDGE = 3.0` (was 5.0)
2. `ml/signals/aggregator.py` signal density block: add `and pred_edge < 7.0` condition

**Expected impact:** 1-3 picks on sparse days instead of 0. Signal quality framework remains intact — signal_count (min 2) and signal_density (need non-base signal) still filter weak picks. Only picks with genuine contextual signals pass at lower edge.

**Risk:** Low. The edge floor was the outermost filter and is now redundant with the signal checks. Any pick that passes signal_count + signal_density at edge 3+ has already demonstrated quality. The edge ≥7 bypass affects 1-2 picks per week maximum.

### Medium-term (priority)

**Deploy fresh models.** The Session 348 retrains and LightGBM models from Session 350 are in shadow. Once graded and validated, promote the best performer to replace the BLOCKED champion. This naturally fixes the edge distribution and restores signal health.

## Files to Modify

| File | Change | Lines |
|------|--------|-------|
| `ml/signals/aggregator.py` | `MIN_EDGE = 3.0` | ~88 |
| `ml/signals/aggregator.py` | Add `and pred_edge < 7.0` to signal density check | ~270-273 |

## Validation Plan

After implementing:
1. Re-run Phase 6 export for today: `PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-27 --only signal-best-bets`
2. Check filter_summary in output JSON — verify edge_floor rejects fewer, signal checks still active
3. Monitor next 7 days of best bets volume and HR
4. If HR drops below 55% on the new picks, revert edge floor to 4.0 (compromise)

## Key Data References

- Filter summary: `gs://nba-props-platform-api/v1/signal-best-bets/2026-02-27.json`
- Model affinity data: Same JSON, `model_direction_affinity` section
- Edge-performance query: See "V12 Edge-Performance Is Inverted" section above
- Signal density Session 348 analysis: `docs/09-handoff/2026-02-24-SESSION-348-HANDOFF.md`
