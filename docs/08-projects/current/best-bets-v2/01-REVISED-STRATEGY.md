# Best Bets V2: Revised Strategy

**Session:** 306 (review of Session 304 plan)
**Status:** APPROVED — Phase A ready to implement
**Goal:** Surface the best pick per player from any CatBoost model, not just the champion

---

## Review Summary

Session 304 proposed a three-phase plan (multi-source candidates, trust-weighted scoring, quality gates). After data validation with fresh post-ASB numbers, the revised strategy is:

| Phase | Original | Revised | Reason |
|-------|----------|---------|--------|
| **A: Multi-source candidates** | Complex "best offer" dedup with direction voting | **Simplified: highest edge wins** | Direction voting is unnecessary — edge IS the signal |
| **B: Trust-weighted scoring** | Bayesian credibility x staleness → effective_edge | **Deferred 60+ days** | Direction-blind, would zero out V9 during cold streaks |
| **C: Quality gates** | 60% expected HR lookup table | **Simplified: existing negative filters + direction-aware edge** | Lookup table too noisy with small samples |

---

## The Data That Drives Everything

### Edge x Direction is the whole story

| Edge | OVER HR | OVER N | UNDER HR | UNDER N |
|------|---------|--------|----------|---------|
| 3-5 | 54.5% | 176 | 50.0% | 210 |
| 5-7 | **69.4%** | 49 | **59.3%** | 59 |
| 7+ | **84.5%** | 58 | **40.7%** | 27 |

Three clear rules emerge:
1. **Edge 5+ is the floor.** Below that, both directions are marginal.
2. **OVER at any edge 5+ is strong.** 69-85% HR.
3. **UNDER at edge 5-7 is profitable (59.3%).** UNDER at 7+ is catastrophic (already blocked).

### V9-only is leaving money on the table

Post-ASB (Feb 19):
- V9 at edge 5+: **0 picks**
- All CatBoost models at edge 5+: **13 unique players** across 7 models

Pre-ASB daily averages:

| Date | V9 Edge 5+ | Multi-Model Unique Players |
|------|------------|---------------------------|
| Feb 7 | 8 | 30 |
| Feb 8 | 3 | 9 |
| Feb 9 | 2 | 8 |
| Feb 10 | 2 | 4 |
| Feb 11 | 6 | 28 |
| Feb 12 | 1 | 3 |
| Feb 19 | **0** | **13** |

Multi-model roughly 3-4x more candidates. After negative filters, we'll still get more surviving picks on weak V9 days.

### Post-ASB model performance (edge 3+)

| Model | Graded | HR |
|-------|--------|----|
| catboost_v9 | 95 | 47.4% |
| catboost_v12 | 25 | **56.0%** |
| catboost_v9_q43 | 37 | **54.1%** |
| catboost_v9_q45 | 25 | **60.0%** |
| ensemble_v1 | 167 | 26.3% |
| similarity_balanced | 173 | **6.4%** |

V12 and quantile models are outperforming V9 right now. Ensembles and similarity are catastrophic — must be excluded.

### Signals have genuine independent value (corrected from initial review)

Session 295 audit found signals add +9.2pp HR over pure edge. Our fresh data confirms:

| Edge Tier | With Real Signal | Without Signal | Lift |
|-----------|-----------------|---------------|------|
| **edge 5+** | **72.9%** (N=96) | 58.4% (N=101) | **+14.5pp** |
| edge 3-5 | 56.8% (N=88) | 50.3% (N=300) | +6.5pp |
| edge below 3 | 49.8% (N=273) | 24.4% (N=2706) | +25.4pp (but still < breakeven) |

**Signals are NOT just annotation — they identify which edge 5+ picks are the best.**

Controlling for edge bucket, specific signals add massive value:

| Signal | Edge 5-7 HR | No-signal 5-7 HR | Lift | N |
|--------|-------------|------------------|------|---|
| **combo_he_ms** | **85.0%** | 57.1% | **+27.9pp** | 20 |
| **minutes_surge** | **85.0%** | 57.1% | **+27.9pp** | 20 |
| **combo_3way** | **75.0%** | 57.8% | **+17.2pp** | 28 |
| blowout_recovery | 37.5% | 64.1% | -26.6pp | 8 (noise) |

At edge 7+, signals don't help — edge dominates (69% regardless). But at **edge 5-7, the sweet spot, signals separate 85% picks from 57% picks.**

Strong signal count matters:

| Edge | 2+ Strong Signals | 1 Strong Signal | No Strong Signal |
|------|-------------------|-----------------|-----------------|
| 5-7 | **85.0%** (N=20) | 50.0% (N=10) | 58.0% (N=81) |
| 7+ | 69.2% (N=13) | - | 69.0% (N=71) |
| 3-5 | - | 62.5% (N=8) | 51.6% (N=380) |

**Key: the edge 3-5 + 1 strong signal = 62.5% (N=8) is promising but N is too small.** If this holds with more data, it could justify lowering the edge floor for signal-qualified picks. Monitor this.

### Signals only have V9 data

Current signal grading data is V9-only. No other model has enough signal-tagged graded picks to evaluate. **This is a critical gap for Phase A** — when we include V12/quantile picks, we don't yet know if the same signals work on those models' predictions. Supplemental data is player-level (not model-level), so the signals themselves should fire the same way, but whether they're predictive of outcomes when paired with non-V9 edges is unknown.

**Action:** After Phase A deploys, track signal HR separately for V9-sourced vs non-V9-sourced picks.

### Player tier is a major untapped dimension

Line value serves as a proxy for player importance. The model performs very differently across tiers:

| Tier | Direction | Edge 5+ HR | N | Verdict |
|------|-----------|-----------|---|---------|
| **bench** (line < 12) | **OVER** | **85.7%** | **77** | **Best cell in the entire system** |
| **star** (line >= 25) | **UNDER** | **69.6%** | 23 | Strong — stars have off nights |
| role (line 12-18) | UNDER | 57.1% | 21 | Marginal |
| role (line 12-18) | OVER | 55.0% | 20 | Marginal |
| starter (line 18-25) | UNDER | 51.4% | 35 | **Barely breakeven — problem cell** |

The story: **the model excels at two specific scenarios:**
1. **Bench players going OVER** (85.7%) — they get unexpected minutes/opportunity, market underprices them
2. **Star players going UNDER** (69.6%) — stars rest, have off nights, market overprices their lines

The model struggles with **starters** — the most competitive tier where market efficiency is highest. Starter UNDER at edge 5+ is only 51.4% (N=35), barely breakeven.

**Implication for best bets:** Player tier should influence pick priority. At the same edge level:
- bench OVER > role OVER > starter OVER (85.7% vs 55% vs 54.5%)
- star UNDER > role UNDER >> starter UNDER (69.6% vs 57.1% vs 51.4%)
- bench UNDER at edge 3-5 is 45.9% → already blocked by bench UNDER filter (line < 12)

**Action:** Track player tier in weekly report card. Consider using tier as a tiebreaker within same edge level after sufficient validation (N >= 100 per cell at edge 5+).

### Confidence scores are dead for V9

V9 confidence distribution:

| Decile | N | HR | Avg Edge |
|--------|------|------|----------|
| 9 | 2,392 | 33.6% | 2.0 |
| 10 | 1,151 | 28.1% | 1.4 |
| 6-8 | 21 | 0.0% | 3.2 |

Almost all V9 predictions cluster in deciles 9-10 with terrible HR. **Confidence does not separate good picks from bad for V9.** Edge does. The model's confidence calibration doesn't map to real-world accuracy — a 95% confidence pick at edge 2.0 loses money while a 95% confidence pick at edge 6.0 wins at 70%+.

**Do NOT use confidence_score or confidence_decile for V9 filtering.** The existing soft floor (`MIN_CONFIDENCE`) is harmless but provides no value. Edge is the only meaningful confidence proxy.

### Complete dimension inventory

| Dimension | Predictive? | Currently Used? | Action |
|-----------|------------|-----------------|--------|
| **Edge (5+ vs 7+)** | YES — primary driver | YES (floor + ranking) | Keep as-is |
| **Direction (OVER vs UNDER)** | YES — 12pp gap | Partially (UNDER blocks) | Track in report card |
| **Player tier (bench/role/star)** | YES — 30pp spread | NO | Add to monitoring, future tiebreaker |
| **Signal presence (2+ strong)** | YES — +27pp at edge 5-7 | NO (annotation only) | Graduate when N >= 50 |
| **Model source** | YES — V12 beating V9 | NO (V9-only) | Phase A implements this |
| **Line movement (prop_line_delta)** | YES — UNDER blocks | YES (negative filter) | Keep at 2.0 threshold |
| **Neg +/- streak** | YES — 13% HR UNDER | YES (negative filter) | Keep |
| **Feature quality** | YES — 24% HR when low | YES (floor at 85) | Keep |
| **Games vs opponent** | Weak | YES (6+ blocked) | Keep |
| Confidence score | **NO** — doesn't separate | Soft floor (harmless) | **Do not invest** |

---

## Season Lifecycle: How Best Bets Work at Every Stage

The system's behavior should adapt based on how much grading data is available. A fresh model in October needs different rules than a battle-tested model in January.

### Phase 0: Cold Start (first 2 weeks of season or post-retrain)

**Situation:** < 50 graded edge 3+ picks. Any HR estimate is noise. Signals have no performance history on this model version.

**Strategy: Maximum conservatism — only the highest-conviction picks.**

| Parameter | Cold Start Value | Steady State Value |
|-----------|-----------------|-------------------|
| Edge floor | **7.0** | 5.0 |
| Signal gate (MIN_SIGNAL_COUNT) | **0** (disabled) | 2 |
| Trust weighting | **None** | Direction-aware Bayesian |
| Player tier filtering | **None** | Tiebreaker |
| Multi-model candidates | **Champion only** | All CatBoost |
| Negative filters | **Active** (pattern-based, no history needed) | Active |

**Why edge 7+ only:** At edge 7+ OVER, HR is 84.5% across the full season — this holds even during model cold periods. At edge 5-7, HR depends on model calibration which hasn't been validated yet.

**Why no signal gate:** Signals need history to validate. Requiring MIN_SIGNAL_COUNT = 2 on a fresh model might block good picks because the signal system hasn't established patterns yet.

**Why champion only:** New shadow models have zero history. Only the champion (just retrained) should produce picks until shadows accumulate grading data.

**Output:** Expect 0-3 picks per day. Some days will have 0 picks. This is correct — better to output nothing than gamble on unvalidated predictions.

**Exit criteria:** 50+ graded edge 3+ picks with HR tracked. Typically 10-14 days.

### Phase 1: Warm-up (weeks 2-4, N = 50-150 graded edge 3+)

**Situation:** Enough data to compute basic HR but too noisy for fine-grained analysis. Direction splits are starting to emerge.

**Strategy: Expand to edge 5+ with basic filtering.**

| Parameter | Warm-up Value |
|-----------|--------------|
| Edge floor | **5.0** |
| Signal gate | **2** (re-enabled) |
| Trust weighting | None |
| Player tier | Observation only |
| Multi-model | Champion + any shadow with 30+ graded picks |
| Negative filters | All active |

**What changes from cold start:**
- Edge floor drops from 7.0 → 5.0 (model has proven baseline viability at edge 3+ via governance gates)
- Signal gate re-enabled (signal patterns have enough context to be meaningful)
- Shadow models with 30+ graded picks can contribute to multi-model candidates

**What we start tracking:**
- Direction split (OVER vs UNDER HR) — first real data on direction bias
- Signal firing rates and preliminary HR per signal
- Player tier distribution of picks

**Exit criteria:** 150+ graded edge 3+ picks. Typically weeks 3-4.

### Phase 2: Steady State (week 4+, N = 150-500 graded)

**Situation:** Rich enough data for direction splits, signal evaluation, and multi-model comparison. This is where most of the season operates.

**Strategy: Full filtering suite with signal awareness and multi-model candidates.**

| Parameter | Steady State Value |
|-----------|-------------------|
| Edge floor | 5.0 |
| Signal gate | 2 |
| Trust weighting | None (defer until Phase 3) |
| Player tier | **Tiebreaker** (bench OVER priority if validated) |
| Multi-model | All CatBoost with 50+ graded picks |
| Negative filters | All active |
| Signal selection | **Graduated signals influence priority** (if any pass gates) |

**What changes from warm-up:**
- Player tier used as tiebreaker within same edge level
- Graduated signals (if any hit N >= 50, HR >= 65%, +10pp lift) influence ranking
- Weekly report card running with full performance cube
- All CatBoost models contributing to multi-model candidates

**Weekly report card dimensions:**
- Model x Direction x Edge bucket x Player tier x Signal tier
- Signal graduation progress
- Negative filter effectiveness audit
- Player tier splits

### Phase 3: Mature (week 8+, N = 500+)

**Situation:** Deep history across all dimensions. Enough data for per-cell expected HR estimates. Trust weighting becomes viable.

**Strategy: Full optimization with trust-weighted scoring and expected HR gates.**

| Parameter | Mature Value |
|-----------|-------------|
| Edge floor | 5.0 (or direction-specific if data supports) |
| Signal gate | 2 |
| Trust weighting | **Direction-aware Bayesian** |
| Player tier | **Active filter** (starter UNDER gated if still < 55%) |
| Multi-model | All CatBoost, trust-weighted |
| Negative filters | All active, thresholds tuned from data |
| Signal selection | Graduated signals rank picks |
| Expected HR gate | **55% floor** on cells with N >= 50 |

**What changes from steady state:**
- Trust-weighted scoring ranks picks by `effective_edge = edge * trust * staleness`
- Expected HR lookup table gates picks from historically bad cells
- Player tier becomes an active filter (block starter UNDER if data confirms it's bad)
- Direction-specific edge floors possible (e.g., UNDER floor at 6.0 if data supports)

### How the system handles retrains mid-season

When a retrain happens (every 7-14 days), the system does NOT reset to Phase 0 for the champion:
- **Champion retrain:** Signal history and supplemental data carry over (they're player-based, not model-based). Negative filters are pattern-based. Only model-specific HR resets. System drops to **Phase 1** (edge floor stays at 5.0, signal gate stays on) and re-enters Phase 2 after ~50 new graded picks.
- **New shadow model:** Starts at Phase 0 (edge 7+ only, no signal gate) until 50+ graded picks accumulate.
- **ASB retrain (like now):** Extended break means all models are stale. System is effectively at Phase 1 for champion, Phase 0 for everything else.

### How the system handles early-season data scarcity

**October (season start):**
- Training data from previous season (expanding window)
- Features may have gaps (new players, traded players, new team compositions)
- Vegas lines not available for first week (preseason → regular season transition)
- **Strategy:** Phase 0 (edge 7+ only) for first 2 weeks, Phase 1 by week 3

**Post-trade-deadline (February):**
- Roster changes affect team compositions and playing time
- Historical features (matchup history, season averages) become partially stale
- **Strategy:** Walk-forward sim found 42-day rolling window handles this naturally — old data drops out

**Injury waves / load management periods:**
- Feature quality may drop (missing players affect team stats)
- **Strategy:** Existing feature quality floor (85) and zero-tolerance defaults handle this. Picks for affected players get blocked automatically.

---

## Phase A: Multi-Source Candidate Generation (Implement Now)

### What changes

```
CURRENT:  V9 predictions → signals → negative filters → rank by edge → output

NEW:      ALL CatBoost predictions → best-per-player dedup → signals → negative filters → rank by edge → output
```

### Best-per-player dedup (simplified from plan)

For each `(player_lookup, game_date)`:
1. Collect all CatBoost model predictions with edge >= 5.0
2. Take the prediction with the **highest edge** (any direction, any model)
3. Record `source_model_id` for attribution
4. If no model has edge >= 5.0 for this player, skip them entirely

No direction voting, no majority rules. The model with the highest conviction wins. This is simple, auditable, and aligned with the core principle that edge IS the signal.

### Model eligibility whitelist

Only CatBoost family models participate:
- `catboost_v9` (champion)
- `catboost_v12` (V12 MAE)
- `catboost_v9_q43_*` (V9 quantile 43)
- `catboost_v9_q45_*` (V9 quantile 45)
- `catboost_v12_noveg_q43_*` (V12 quantile 43)
- `catboost_v12_noveg_q45_*` (V12 quantile 45)
- `catboost_v9_low_vegas_*` (low-vegas variant)

**Excluded forever:** `ensemble_v1*`, `similarity_balanced*`, `moving_average`, `zone_matchup*`, `catboost_v8` (stale). These have 6-35% HR at edge 3+. Including them would poison the candidate pool.

Use pattern matching (like `shared/config/cross_model_subsets.py` family classification) so new retrains auto-qualify.

### All existing negative filters still apply

The "best offer" pick for each player passes through every filter:
1. Player blacklist (<40% HR on 8+ picks)
2. Avoid familiar (6+ games vs opponent)
3. Edge floor 5.0
4. UNDER edge 7+ block (40.7% HR)
5. Feature quality floor (quality < 85)
6. Bench UNDER block (line < 12)
7. UNDER + line jumped 2.0+ (38.2% HR) — Session 306
8. UNDER + line dropped 2.0+ (35.2% HR) — Session 306
9. Neg +/- streak UNDER block (13.1% HR)
10. ANTI_PATTERN combo block
11. MIN_SIGNAL_COUNT = 2 (model_health + 1 real signal)

### Source attribution tracking

Every best bet includes:
- `source_model_id`: which model's prediction was selected
- `source_model_edge`: the edge from that model
- `n_models_eligible`: how many models had edge >= 5.0 for this player
- `champion_edge`: V9's edge for comparison (even if not selected)

This enables post-hoc analysis: are non-V9 picks hitting at comparable rates?

### Files to change

| File | Change |
|------|--------|
| `ml/signals/supplemental_data.py` | Query all CatBoost system_ids, not just champion |
| `ml/signals/aggregator.py` | Accept multi-model candidates, add source attribution fields |
| `data_processors/publishing/signal_best_bets_exporter.py` | Pass multi-model predictions to aggregator |
| `shared/config/model_selection.py` | Add `get_eligible_model_families()` function |

### Validation plan

Deploy and monitor for 2 weeks:
- How many picks come from non-V9 models?
- Do non-V9 picks pass negative filters at the same rate?
- Days where V9 produces 0 picks but other models produce viable ones
- Hit rate BY source model (critical for trust decisions later)

---

## How Signals Should Be Treated

### Signals are a quality multiplier on edge, not a replacement for it

The data is clear on what signals can and cannot do:

| What signals CAN do | What signals CANNOT do |
|---------------------|----------------------|
| Separate 85% picks from 57% picks within edge 5-7 | Rescue low-edge picks (edge < 3 + signal = 49.8%) |
| Block terrible patterns (UNDER+line delta = 35% HR) | Replace edge as the primary ranking signal |
| Add +14.5pp HR at edge 5+ vs no signal | Work independently of a model prediction |
| Explain picks to users (transparency) | Predict which models will be right |

**The formula:** `edge selects the candidates, signals identify the best among them, negative filters remove the worst.`

### Four roles of signals (from most to least impactful)

#### Role 1: Negative Filtering — BLOCKING bad picks (ACTIVE, highest value)

Signals and patterns that identify picks likely to lose. These **block** picks from entering best bets. Blocking a 35% HR pick saves more money than identifying a 70% HR pick.

| Filter | HR | N | What it blocks |
|--------|-----|---|----------------|
| UNDER + line delta 2.0+ | 35-38% | 380 | Line moved significantly, UNDER fails |
| Bench UNDER (line < 12) | 35.1% | - | Low-ceiling players |
| Neg +/- streak UNDER | 13.1% | - | Players in a slump |
| UNDER edge 7+ | 40.7% | 27 | Extreme model predictions going wrong direction |
| ANTI_PATTERN combos | Varies | - | Known-bad signal combinations |
| MIN_SIGNAL_COUNT < 2 | - | - | No signal context on the player |

#### Role 2: Quality Selection — IDENTIFYING the best picks (EMERGING)

At edge 5-7, signals identify which picks are elite vs average. This is real, data-backed value:

| Signal Tier at Edge 5-7 | HR | N | Implication |
|------------------------|-----|---|-------------|
| 2+ strong signals | **85.0%** | 20 | Elite tier — these are the best picks in the system |
| No strong signal | 58.0% | 81 | Average edge 5-7 performance |
| Lift | **+27pp** | | |

**Current status:** Observed but not yet used for ranking. Edge alone determines rank.

**What "using signals for selection" would look like:**
- Within the pool of edge 5+ picks that pass all negative filters, signal-qualified picks (2+ strong signals) could get priority ranking over non-signal picks at the same edge level
- This would NOT change which picks are included (edge 5+ floor stays), only the ORDER when picks have similar edges
- Example: Player A at edge 5.5 with combo_he_ms (85% expected HR) should probably rank above Player B at edge 5.8 with no signals (57% expected HR)

**When to activate:** After N >= 50 for the "2+ strong signals at edge 5-7" cohort AND validated across 2+ time windows. Currently N=20 — need ~30 more graded picks in this category.

#### Role 3: Annotation / Pick Angles — EXPLAINING why (ACTIVE)

Signals attached to picks for frontend display. Builds user trust and transparency.

| Signal | Pick Angle |
|--------|-----------|
| `combo_he_ms` | "High conviction + increased minutes" |
| `prop_line_drop_over` | "Line dropped from last game — mean reversion" |
| `bench_under` | "Bench player with limited ceiling" |
| `3pt_bounce` | "3PT shooter due for regression to mean" |
| `b2b_fatigue_under` | "Back-to-back fatigue expected" |

#### Role 4: Quality Gate — ENSURING signal context exists (ACTIVE)

`MIN_SIGNAL_COUNT = 2` ensures the signal system has context on the player. At edge 5+, picks without any real signal hit 58.4% vs 72.9% with signals. The gate is justified.

### Which signals have proven value?

| Signal | Edge 5+ HR | Overall HR | N (edge 5+) | Independent lift at 5-7? | Status |
|--------|-----------|------------|-------------|--------------------------|--------|
| **combo_he_ms** | **78.8%** | 78.8% | 33 | **+27.9pp** (N=20) | **PROVEN at edge 5-7** |
| **minutes_surge** | **78.8%** | 67.0% | 33 | **+27.9pp** (N=20) | **PROVEN at edge 5-7** (same picks as combo_he_ms) |
| **combo_3way** | **73.8%** | 70.5% | 42 | **+17.2pp** (N=28) | **PROVEN at edge 5-7** |
| edge_spread_optimal | 66.8% | 64.0% | 193 | baseline (always fires at 5+) | Baseline signal |
| high_edge | 66.8% | 64.0% | 193 | baseline (always fires at 5+) | Baseline signal |
| blowout_recovery | 61.9% | 55.6% | 21 | -26.6pp (N=8, noise) | **UNPROVEN** — watch |
| bench_under | - | 76.9% | - | Not measured at 5+ | **PROMISING** — needs edge 5+ data |
| prop_line_drop_over | - | 71.6% | - | Just started firing (Session 305) | **TOO NEW** — accumulating data |

**combo_he_ms and combo_3way are the only signals with proven independent lift at edge 5-7.** Both add 17-28pp controlling for edge. blowout_recovery may be harmful at 5-7 (N=8 is noise, but 37.5% is concerning).

### Signals that should NEVER influence selection

| Anti-pattern | Why it fails | Session |
|-------------|--------------|---------|
| Signal-weighted composite scoring | Dilutes high-edge picks with low-edge signal-heavy picks. 59.8% HR vs 71.1% for edge-first. | 297 |
| Signal fires on edge < 3 pick → include it anyway | 49.8% HR — signals cannot rescue bad predictions | 306 |
| V12 MAE agreement as positive factor | Anti-correlated: OVER+V12 agrees = 33.3% HR | 297 |
| Consensus scoring bonus | diversity_mult rewarded harmful V9+V12 agreement | 297 |

### Signal graduation framework

For a signal to move from annotation → selection influence:

| Gate | Threshold | Purpose |
|------|-----------|---------|
| Sample size | N >= 50 at edge 5+ | Avoid small-sample illusions |
| Hit rate | HR >= 65% at edge 5+ | Must be profitable |
| Independent lift | +10pp vs no-signal at same edge bucket | Proves value beyond edge |
| Temporal consistency | Positive in 2+ independent 30-day windows | Not a hot streak |
| Model coverage | Validated on V9 AND at least 1 other model family | Works across models |

**Current signal graduation status:**

| Signal | N gate | HR gate | Lift gate | Temporal | Model coverage | Ready? |
|--------|--------|---------|-----------|----------|---------------|--------|
| combo_he_ms | 33/50 | 78.8% PASS | +27.9pp PASS | 1 window only | V9 only | **NO — need N and temporal** |
| combo_3way | 42/50 | 73.8% PASS | +17.2pp PASS | 1 window only | V9 only | **NO — need N and temporal** |
| bench_under | ?/50 | ? | ? | ? | V9 only | **NO — need edge 5+ data** |

### Signal monitoring

**validate-daily Phase 0.59** monitors per-signal firing rates. A PRODUCTION signal that fires 0 times across 3+ game days triggers investigation.

**What SHOULD be monitored but isn't yet (see Systematic Monitoring section):**
- Per-signal HR by edge bucket (detect decay per signal)
- Signal x model interactions (validate signals work on non-V9 predictions)
- Signal x direction splits (catch direction-specific failures like combo_3way UNDER)
- Signal graduation progress (track N accumulation toward thresholds)

---

## Systematic Performance Monitoring (New Section)

### The problem

We have rich data across many dimensions — signal, model, direction, edge bucket, time window — but we only monitor aggregates. This means:
- A signal can go from 85% to 40% HR and nobody notices for weeks
- A model can be great on OVER and terrible on UNDER but we only see the blended 52%
- Edge 5-7 picks might be performing differently than 7+ but we lump them together
- The prop_line_drop_over zero-firing problem went undetected for weeks

### Key principle: thresholds are stable, monitoring catches drift

We should **NOT** recompute all filter thresholds daily. The thresholds (edge 5+, UNDER 7+ block, line delta 2.0, etc.) should be stable for weeks. Daily monitoring checks for anomalies. Weekly report card checks if thresholds are still valid. Monthly analysis recalibrates if needed.

### What we should be tracking

**Level 1: Daily automated (in validate-daily) — anomaly detection**

Purpose: catch things that break today. Fast, cheap, runs every morning.

| Check | What it monitors | Alert condition |
|-------|-----------------|-----------------|
| Signal firing rates (Phase 0.59 — DONE) | Per-signal pick count | SILENT for 3+ game days |
| Model HR by direction (extend Phase 0.58) | Per-model OVER HR + UNDER HR at edge 3+ | Either direction < 40% over 7d |
| Best bets source attribution | % picks from each model | > 95% from one model for 7+ days |
| Direction balance | OVER vs UNDER count in best bets | > 90% one direction |
| Negative filter blocking rate | How many picks blocked by each filter | Any filter blocking > 50% of candidates |
| Pick count anomaly | Total best bets output | 0 picks for 3+ consecutive game days |

**Level 2: Weekly report card (new `/weekly-report-card` skill) — performance assessment**

Purpose: evaluate whether the current strategy is working. Runs weekly, produces a summary for human review.

The weekly report computes a **performance cube** across these dimensions:

```
Dimensions (6):
  - Model: V9, V12, V9_Q43, V9_Q45, V12_Q43, V12_Q45
  - Direction: OVER, UNDER
  - Edge bucket: 3-5, 5-7, 7+
  - Player tier: bench, role, starter, star
  - Signal tier: 2+ strong, 1 strong, no strong signal
  - Time window: 7d, 14d, 30d, season

Key metrics per cell:
  - N (sample size)
  - HR (hit rate)
  - HR delta vs same cell last week (trend)
  - P&L at $100 flat bet

Automatic flags:
  - Any cell with N >= 20 drops below 50% HR (losing money)
  - Any cell's HR drops > 15pp vs its 30-day average (sudden degradation)
  - A model's OVER-UNDER spread exceeds 20pp (direction bias developing)
  - A signal's lift (signal HR - no-signal HR at same edge) turns negative
  - A player tier's HR diverges > 15pp from expected (bench OVER stops working?)
  - Negative filter false positive rate: how many blocked picks would have won?

Graduation tracking (updated weekly):
  - Each signal's N, HR, lift at edge 5+ — progress toward graduation gates
  - Each player tier's N, HR by direction — progress toward activation as filter
  - Each model's grading volume — progress toward multi-model inclusion

Example weekly output:
  "This week: V9 OVER at edge 5-7 = 72% (stable). V9 UNDER at edge 5-7 = 43% (↓8pp, watch).
   combo_he_ms now at N=38/50 for graduation (need 12 more graded picks).
   bench OVER 5+ still 84% (N=82, very stable). starter UNDER 5+ dropped to 48% (N=38, flag).
   Phase A source: 65% V9, 20% V12, 15% quantile. Non-V9 HR: 61%."
```

**Level 3: Monthly deep analysis (manual, session work) — strategy recalibration**

Purpose: review whether thresholds, filters, and signals should be adjusted. Quarterly for major changes.

- Full signal graduation review (update N/HR/lift/temporal gates)
- Model family comparison (should any model be promoted/demoted?)
- Edge floor review (should 5.0 be adjusted based on accumulated data?)
- Negative filter effectiveness (are filters still blocking bad picks, or blocking good ones?)
- Cross-model signal validation (do signals work the same on V12 as V9?)
- Player tier threshold review (should starter UNDER be blocked? should bench OVER get priority?)
- Direction-specific edge floor review (should UNDER have a higher floor than OVER?)
- Walk-forward backtest of proposed changes before deploying

### Implementation approach

Don't build a monolithic monitoring system. Instead:

1. **Extend validate-daily** with direction-split model checks (small change to Phase 0.58)
2. **Create a `/weekly-report-card` skill** that runs the performance cube queries and summarizes findings. This replaces ad-hoc session work.
3. **Track signal graduation progress in BQ** — a small table that records each signal's current N, HR, lift at each edge bucket, updated weekly. Alerts when a signal crosses a graduation threshold.
4. **After Phase A ships**, add source-model attribution to the weekly report card.

### What this enables long-term

With systematic monitoring, decisions about signals, models, and filters become **data-driven and automatic**:

- "Should we promote combo_he_ms from annotation to selection?" → Check the graduation table. If all gates pass, yes.
- "Is the V9 cold streak real or variance?" → Check direction-split 14d HR. If OVER is still 65%+, it's an UNDER problem.
- "Should we lower the edge floor for signal-qualified picks?" → Check edge 3-5 + strong signal HR in the weekly cube. If N >= 50 and HR >= 60%, consider it.
- "Is a new model ready for best bets?" → Check model's HR at edge 5+ by direction in the cube. If both OVER and UNDER beat 55%, include it.

---

## Deferred: Trust-Weighted Scoring (60+ Days Out)

### Why defer

The trust formula from the original plan:
```
trust_multiplier = clamp((trust_raw - 52.4) / (70.0 - 52.4), 0.0, 1.0)
effective_edge = raw_edge * trust_multiplier * staleness_factor
```

Problems:
1. **Direction-blind.** V9 OVER = 63.3% HR, UNDER = 51.0%. A blanket trust of 0.3 (based on aggregate 47.4%) would suppress V9 OVER picks that are genuinely strong.
2. **Cold-streak overreaction.** V9 at 47.4% post-ASB could be normal variance on a fresh retrain with 2 weeks of data. Trust = 0.0 at 52.4% means total exclusion.
3. **Insufficient multi-model data.** V12 quantiles have <10 graded edge 3+ picks. Trust estimates are noise.
4. **Phase A gives 80% of the value.** The main win is surfacing non-V9 picks. Trust scoring is a refinement, not a necessity.

### What to build when ready

When we have 60+ days of multi-model grading data:

```
# Direction-aware trust (the key improvement over the original plan)
over_trust = bayesian_shrink(model_14d_over_hr, model_season_over_hr, n_14d_over)
under_trust = bayesian_shrink(model_14d_under_hr, model_season_under_hr, n_14d_under)

# Use the direction-matched trust for this specific pick
if recommendation == 'OVER':
    trust = over_trust
else:
    trust = under_trust

# Staleness factor (same as original plan — this part is good)
staleness = 1.0 if days <= 7 else 0.95 if days <= 10 else 0.85 if days <= 14 else 0.70

effective_edge = raw_edge * trust * staleness
```

**Bayesian shrinkage formula:**
```
credibility = min(n_14d / 30, 1.0)
trust_raw = credibility * observed_hr + (1 - credibility) * prior_hr
trust_multiplier = clamp((trust_raw - 52.4) / (70.0 - 52.4), 0.0, 1.0)
```

This is the original plan's formula but applied per-direction. A model that's cold on UNDER but hot on OVER gets appropriate trust for each pick.

### Prerequisites before implementing

- [ ] 60+ days of Phase A grading data (multi-model source attribution)
- [ ] Each CatBoost model has >= 30 graded OVER edge 3+ picks AND >= 30 graded UNDER edge 3+ picks
- [ ] Backtest on historical data shows trust-weighted ranking beats raw-edge ranking
- [ ] Direction-aware trust validated: does separating OVER/UNDER trust actually improve P&L?

---

## Deferred: Expected HR Quality Gate (6+ Months Out)

### Why defer

The original plan proposed a lookup table bucketed by (edge_bucket, direction, model_family) with a 60% HR floor. The problem: small samples.

Example buckets today:
- `edge 7+ UNDER v9_quantile`: ~3 picks — meaningless
- `edge 5-7 OVER v12_mae`: ~8 picks — noisy
- `edge 5-7 UNDER v9_mae`: ~20 picks — starting to be useful

With 6 edge buckets x 2 directions x 6 model families = 72 cells. Most will have <10 picks for months.

### What to build when ready

When enough data exists (200+ picks per major cell):

1. **Simple lookup table** — updated weekly, stored in BQ
2. **Only gate on cells with N >= 50** — skip the gate for small-sample cells
3. **Floor at 55% expected HR** (not 60%) — we want to filter disasters, not borderline picks
4. **Monitor actual-vs-expected HR drift** — alert if a cell's rolling HR diverges from lookup by > 10 pts

### Alternative: Direction-specific edge floors (simpler)

Instead of a full lookup table, a simpler approach that captures most of the value:

```
OVER:  edge >= 5.0 (current, 69.4% HR at 5-7, 84.5% at 7+)
UNDER: edge >= 5.0 (current, 59.3% HR at 5-7, 40.7% at 7+ → already blocked)
```

The data shows UNDER at edge 5-7 is profitable (59.3%). Raising the UNDER floor to 6.0 would:
- Block ~40% of UNDER 5-7 picks (the lower-edge ones)
- The blocked picks likely have lower HR than 59.3% (edge 5.0-5.5 range)
- But we'd lose some good picks too

**Recommendation:** Keep UNDER floor at 5.0 for now. The existing negative filters (line delta, bench, neg PM streak) already catch the worst UNDER patterns. Only raise if UNDER HR at edge 5-7 drops below 55% over a sustained period.

---

## Consensus: What We Know and Don't Know

### What the data says

| Consensus pattern | HR | N | Verdict |
|-------------------|-----|---|---------|
| V9+V12 agree OVER | 33.3% | - | **ANTI-CORRELATED** — block this |
| V9+V12 agree UNDER | 45.5% | 11 | Anti-correlated but N too small |
| 3+ quantile models agree UNDER | TBD | <10 | **Insufficient data** |
| 4+ models agree same direction | TBD | <10 | **Insufficient data** |

### What to do now

- **V12 MAE agreement stays as a negative signal** (annotation warning, not a block yet)
- **Quantile consensus: observe only.** Track in cross-model subsets. Do not use for selection until N >= 50.
- **Do NOT add consensus bonus to scoring.** Session 297 removed the diversity_mult for good reason.

### When consensus might add value

If after 60+ days of multi-model data:
- `quantile_consensus_under` (3+ quantile models agree UNDER) shows HR >= 65% at edge 5+ with N >= 50 → consider as a positive annotation (not scoring factor)
- `4+ models agree` shows HR >= 60% with N >= 100 → consider as a tiebreaker (not ranking factor)

---

## Long-Term Roadmap

### Implementation timeline

| Timeline | Phase | What | Key Metric |
|----------|-------|------|------------|
| **Now** | A: Multi-source candidates | Query all CatBoost models, highest-edge-per-player | % picks from non-V9 |
| **Now** | Monitoring: validate-daily direction split | Add OVER/UNDER HR to Phase 0.58 model dashboard | Direction-aware visibility |
| **+2 weeks** | A validation | Monitor source attribution, hit rate by model | Non-V9 HR vs V9 HR |
| **+2 weeks** | Monitoring: weekly report card | `/weekly-report-card` skill with performance cube | Automated weekly analysis |
| **+4 weeks** | Signal graduation review | combo_he_ms, combo_3way N check (need N >= 50 at edge 5+) | Signal graduation gates |
| **+4 weeks** | Signal x model validation | Do signals work on V12/quantile picks? | Cross-model signal HR |
| **+4 weeks** | Player tier validation | bench OVER still 85%+ at N >= 100? starter UNDER still < 55%? | Player tier as tiebreaker |
| **+6 weeks** | Signal-aware ranking (if graduated) | 2+ strong signals → priority within edge tier | HR lift from signal ranking |
| **+8 weeks** | B: Trust-weighted scoring | Bayesian direction-aware trust | Backtest P&L improvement |
| **+12 weeks** | B validation | 30-day live comparison | Trust-weighted vs raw-edge P&L |
| **+6 months** | C: Expected HR gate | Per-cell lookup table with 55% floor | Bucket sample sizes |

### Season lifecycle mapping

| Season Point | System Phase | Edge Floor | Signal Gate | Multi-Model | Trust |
|-------------|-------------|------------|-------------|-------------|-------|
| Oct wk 1-2 (season start) | Phase 0: Cold Start | 7.0 | OFF | Champion only | None |
| Oct wk 3-4 | Phase 1: Warm-up | 5.0 | ON (2) | Champion + validated shadows | None |
| Nov-Dec | Phase 2: Steady State | 5.0 | ON (2) | All CatBoost (50+ graded) | None |
| Jan+ | Phase 3: Mature | 5.0 | ON (2) | All CatBoost, trust-weighted | Direction-aware |
| Post-retrain (any time) | Drops to Phase 1 | 5.0 | ON (2) | Champion + existing shadows | Reset for champion |
| Post-ASB (Feb) | Phase 1 | 5.0 | ON (2) | Champion + any validated | Reset |
| Trade deadline (Feb) | Monitor for drift | Unchanged | Unchanged | Watch for feature drift | Watch |
| Playoffs (Apr+) | Phase 2-3 | 5.0 | ON (2) | Same | Same, watch for regime shift |

### Success criteria for each phase

**Phase A succeeds if:**
- Non-V9 picks contribute >= 20% of best bets over 2 weeks
- Non-V9 picks hit at >= 55% at edge 5+
- Zero days with 0 picks (that previously had 0 with V9-only)

**Phase B succeeds if:**
- 30-day backtest shows trust-weighted P&L > raw-edge P&L by >= 5%
- Direction-aware trust prevents V9 OVER suppression during cold UNDER periods
- No model is completely excluded (trust = 0.0) for more than 3 consecutive days

**Phase C succeeds if:**
- Expected HR lookup filters >= 10% of candidates that would have been included
- Filtered candidates' actual HR is < 50% (confirms they were bad picks)
- No reduction in overall best bets HR

---

## Dead Ends (Confirmed)

From Session 297 + Session 306 review:

1. **Signal-weighted composite scoring** — edge-first beats signal-scored (71% vs 60%)
2. **V12 MAE agreement as positive signal** — anti-correlated
3. **Averaging edges across models** — dilutes the best offer
4. **Hard model exclusion by HR** — cliff effects, use smooth trust instead
5. **ELO ratings for models** — over-engineered for this domain
6. **Edge Classifier (Model 2)** — AUC < 0.50 (Session 230)
7. **CHAOS + quantile** — dead end
8. **Residual mode** — dead end
9. **Two-stage pipeline** — dead end
10. **Consensus scoring bonus** — V9+V12 agreement is anti-correlated (Session 297)
11. **Confidence score as filter for V9** — all picks cluster in deciles 9-10, 28-34% HR, no separation (Session 306)
12. **Confidence-weighted ranking** — confidence doesn't correlate with accuracy for V9. Edge is the only meaningful proxy.
