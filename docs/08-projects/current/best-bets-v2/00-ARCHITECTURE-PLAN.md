# Best Bets V2: Multi-Source, Performance-Aware Selection System

**Session:** 304
**Status:** REVIEWED — See `01-REVISED-STRATEGY.md` for approved plan (Session 306 review)
**Goal:** Replace champion-only, edge-ranked best bets with a multi-model, performance-aware system that dynamically adapts to what's working

---

## Why This Matters

The current best bets system has a critical flaw: **it only uses the champion model (catboost_v9).** When the champion has a weak day (like Feb 19 — avg edge 0.8, zero edge 5+ picks), best bets outputs nothing. Meanwhile, other models have actionable high-edge picks that never surface.

The system also ignores rich performance data that already exists — model health, signal regimes, direction splits, staleness — using only negative filters and raw edge for selection.

---

## What the Data Tells Us

### Edge is king (confirmed)
| Edge Bucket | V9 HR | N |
|-------------|-------|---|
| 3-5 | 47.7% | 421 |
| 5-7 | **58.0%** | 119 |
| 7+ | **65.2%** | 92 |

Session 297's edge-first insight is validated. Do not revert to signal-composite scoring.

### OVER >> UNDER for V9 (10-point spread)
| Direction | V9 HR (edge 3+) | N |
|-----------|-----------------|---|
| OVER | **57.4%** | 312 |
| UNDER | 47.2% | 320 |

UNDER is below breakeven for V9. Strong UNDER picks need additional evidence (signals, quantile consensus) to be trusted.

### Cross-model V9+V12 agreement HURTS
| Scenario | HR | N |
|----------|-----|---|
| V9 only, OVER | **56.0%** | 323 |
| 2 models agree, UNDER | 45.5% | 11 |

V12 MAE agreement is anti-correlated with winning (Session 297 confirmed). Do NOT use V12 MAE agreement as a positive signal.

### Signals add value as filters (not selectors)
| Signal | HR | N |
|--------|-----|---|
| `combo_he_ms` | **77.5%** | 102 |
| `combo_3way` | **67.0%** | 100 |
| `3pt_bounce` | 65.1% | 86 |
| `high_edge` | 56.8% | 916 |
| `minutes_surge` | 52.4% | 1,125 |

Combos are genuinely strong. Volume signals (`minutes_surge`, `blowout_recovery`) are marginal.

### V9 is currently cold
| Window | HR | N |
|--------|-----|---|
| Last 14d | 44.1% | 102 |
| Last 30d | 45.2% | 387 |
| Season | 52.2% | 632 |

An 8-point drop from season average. The ASB retrain just landed — needs time to prove itself.

### CRITICAL GAP: Quantile models have almost no grading data
The 4 quantile models (`v9_q43`, `v9_q45`, `v12_q43`, `v12_q45`) did NOT appear in any of the historical queries — they have fewer than 10 graded edge 3+ picks each. **We cannot evaluate multi-model consensus until quantile grading volume exists.** This is the biggest blocker.

### Monitoring infrastructure exists but is unused
| Data Source | What It Tracks | Used by Aggregator? |
|-------------|---------------|---------------------|
| `model_performance_daily` | Rolling HR per model, state machine, staleness | NO |
| `signal_health_daily` | Per-signal HOT/NORMAL/COLD regime | NO |
| `signal_combo_registry` | 13 validated combos with HR | Only for ANTI_PATTERN blocking |
| `player_blacklist` | Per-player chronic failure | YES |
| Direction health | OVER vs UNDER rolling HR | NO |
| `subset_grading_results` | Per-subset daily performance | NO |

The aggregator uses only negative filters + edge ranking. All the positive intelligence is ignored.

---

## Design Principles

1. **Edge remains the primary ranking signal.** Session 297 proved this. Do not revert.
2. **Expand the candidate pool, not the scoring complexity.** The biggest win is surfacing picks from models other than V9 when V9 is weak.
3. **Use performance data for trust weighting, not hard cutoffs.** Binary thresholds create cliff effects. Smooth trust scores degrade gracefully.
4. **Never force picks.** Zero picks on a weak day is the correct output. The system's credibility depends on it.
5. **Track attribution.** Every pick records which model sourced it, what trust score it had, and why it was selected. Without this, we can't improve the system.
6. **Implement in stages.** Each phase is independently valuable and independently reversible.

---

## Architecture: Three-Phase Implementation

### Phase A: Multi-Source Candidate Generation

**Goal:** Surface picks from ALL active models, not just the champion.

**Current flow:**
```
V9 predictions → signals → negative filters → rank by edge → output
```

**New flow:**
```
ALL model predictions → "best offer" per player → signals → negative filters → rank by edge → output
```

**"Best Offer" dedup logic:** For each (player_lookup, game_id):
1. Collect all model predictions with edge >= 3.0
2. Group by direction (OVER/UNDER)
3. Pick the majority direction (ties: higher max edge wins)
4. Within winning direction, select the prediction with highest edge
5. Record: `source_model_id`, `n_models_agreeing`, `direction_conflict`

**Example (today's data):**
- Jalen Green: V9 UNDER edge 0.8, Q43 UNDER edge 6.1 → Best offer: Q43 UNDER at 6.1 (V9 agrees on direction but below edge 3 threshold, so only Q43 counts)
- Alperen Sengun: V9 UNDER edge 0.4, V12_Q45 UNDER edge 5.5, V12_Q43 UNDER edge 5.3 → Best offer: V12_Q45 UNDER at 5.5 (3 quantile models agree)

**Guard rails:**
- A model must have edge >= 3.0 to count as "agreeing" (below that is noise)
- Supplemental data (3PT stats, minutes, streaks) depends on player_lookup, not system_id — works regardless of source model
- All existing negative filters still apply to the "best offer" pick
- `source_model_id` tracked in `signal_best_bets_picks` for grading attribution

**Files changed:**
- `ml/signals/supplemental_data.py` — query all model families instead of champion only
- `ml/signals/aggregator.py` — accept multi-source candidates
- `data_processors/publishing/signal_best_bets_exporter.py` — pass multi-model data to aggregator

**Validation:** Deploy and monitor for 2 weeks. Questions to answer:
- How many picks come from non-V9 models?
- Do non-V9 picks pass negative filters at the same rate?
- Are there days where V9 produces 0 picks but other models produce viable ones?

---

### Phase B: Trust-Weighted Scoring

**Goal:** Down-weight picks from cold/stale models, up-weight picks from hot/fresh models.

**Trust formula per model (computed once daily at aggregator startup):**
```
observed_hr = model's 14d rolling HR on edge 3+ picks (from model_performance_daily)
prior_hr = model's season-long HR (from model_performance_daily)
n_14d = model's 14d graded count
credibility = min(n_14d / 30, 1.0)

trust_raw = credibility * observed_hr + (1 - credibility) * prior_hr
trust_multiplier = clamp((trust_raw - 52.4) / (70.0 - 52.4), 0.0, 1.0)
```

**Staleness factor:**
```
days = days_since_training (from model_performance_daily)
staleness = 1.0 if days <= 7
           0.95 if days <= 10
           0.85 if days <= 14
           0.70 if days > 14
```

**Effective edge (replaces raw edge for ranking):**
```
effective_edge = raw_edge * trust_multiplier * staleness_factor
```

**Effect:** A V9 pick at edge 6.0 with trust 0.8 → effective_edge 4.8. A Q43 pick at edge 7.0 with trust 0.5 → effective_edge 3.5. V9 ranks higher despite lower raw edge because it's more trusted. But if V9 is cold (trust 0.3) and Q43 is hot (trust 0.8), Q43's pick at 7.0 * 0.8 = 5.6 beats V9's 6.0 * 0.3 = 1.8.

**New model handling:** A model with 0 graded picks has credibility = 0, so trust = prior_hr (season average for the family). It starts at a reasonable baseline, not zero.

**Circuit breaker:** If ALL models have trust_multiplier < 0.15, output zero picks with a clear explanation.

**Files changed:**
- `ml/signals/aggregator.py` — compute trust, use effective_edge for ranking
- `data_processors/publishing/signal_best_bets_exporter.py` — query model_performance_daily, pass to aggregator

**Validation:** 30-day backtest comparing trust-weighted vs raw-edge ranking on historical data before deploying to production.

---

### Phase C: Quality Gates and Refinements

**Goal:** Only surface picks with >= 60% expected HR, add direction-aware adjustments.

**Expected HR lookup:** Build a historical lookup table bucketed by:
- Edge bucket: [5.0-6.0, 6.0-7.0, 7.0+]
- Direction: OVER, UNDER
- Source model family: v9_mae, v12_mae, v9_quantile, v12_quantile

For each bucket, compute the rolling 60-day HR. Only surface picks where expected_hr >= 60%.

**Direction-specific edge floors:**
```
OVER: effective_edge >= 5.0 (current)
UNDER: effective_edge >= 5.0 AND at least ONE of:
  - quantile consensus (2+ quantile models agree UNDER)
  - strong signal (bench_under, b2b_fatigue_under, combo_he_ms)
  - V9 UNDER HR last 14d >= 50%
```

This addresses V9 UNDER's 47.2% HR by requiring additional evidence for UNDER picks.

**Consensus adjustments (additive to effective_edge):**
```
direction_conflict (models disagree): -0.5
quantile_consensus_under (3+ quantile models agree UNDER): +0.3
v12_mae_agrees_OVER: -0.5 (anti-correlated per data)
4+ models agree same direction: +0.1
```

**Signal regime awareness:**
- If a signal is in COLD regime (from signal_health_daily, divergence < -10), don't count it toward the MIN_SIGNAL_COUNT = 2 gate
- If a signal is in HOT regime, count it as 1.5x toward signal_count tiebreaker (cosmetic effect only — does not override edge ranking)

**Files changed:**
- `ml/signals/aggregator.py` — quality gate, direction-specific floors, consensus adjustments
- New: `ml/signals/expected_hr_lookup.py` — builds/caches the bucketed HR lookup table
- `data_processors/publishing/signal_best_bets_exporter.py` — query signal_health_daily

**Validation:** Compare 14 days post-deploy P&L vs 14 days pre-deploy.

---

## What Must Happen First (Blockers)

### 1. Quantile model grading volume (CRITICAL)

The 4 quantile models have <10 graded edge 3+ picks each. Multi-model consensus cannot be evaluated without grading data. **Before Phase A can be validated, we need 2-4 weeks of post-ASB grading data for quantile models.**

**Action:** Verify quantile predictions ARE being written to `prediction_accuracy` after grading. If not, this is a pipeline bug that must be fixed first.

### 2. Fix existing best bets pipeline

Today's best bets output is empty (0 picks). The GCS file has `total_picks: 0`. Before we can improve best bets, the existing system must work.

**Action:** Diagnose why best bets is empty post-ASB retrain. Is it:
- Model health unknown (no graded data yet)?
- Edge floor too high for the fresh model?
- Signal annotation not running?

### 3. Fix cross_model data quality

Cross-model picks have `player: "tyresemaxey"` (lookup key, not display name) and empty team/opponent. This must be fixed before multi-model picks can appear in best bets.

---

## Selection Funnel (For Analytics Page)

The new system should export a complete selection funnel for each day:

```json
{
  "funnel": {
    "candidates": {
      "total_models_queried": 6,
      "total_predictions": 486,
      "unique_player_games": 81,
      "after_best_offer_dedup": 81
    },
    "trust_weighting": {
      "models": {
        "catboost_v9": { "trust": 0.31, "staleness": 1.0, "14d_hr": 44.1, "picks_contributed": 12 },
        "catboost_v12": { "trust": 0.42, "staleness": 0.95, "14d_hr": 48.3, "picks_contributed": 3 },
        "catboost_v9_q43": { "trust": 0.55, "staleness": 1.0, "14d_hr": null, "picks_contributed": 5 }
      }
    },
    "negative_filters": [
      { "name": "effective_edge >= 5.0", "dropped": 68, "survived": 13 },
      { "name": "signal_count >= 2", "dropped": 2, "survived": 11 },
      { "name": "player_blacklist", "dropped": 0, "survived": 11 },
      { "name": "UNDER edge 7+ block", "dropped": 1, "survived": 10 },
      { "name": "quality_floor >= 85", "dropped": 0, "survived": 10 },
      { "name": "UNDER without evidence", "dropped": 2, "survived": 8 }
    ],
    "quality_gate": {
      "threshold": "60% expected HR",
      "dropped": 1,
      "survived": 7
    },
    "output": {
      "total_picks": 7,
      "by_source_model": {
        "catboost_v9": 4,
        "catboost_v9_q43": 2,
        "catboost_v12": 1
      },
      "by_direction": { "OVER": 5, "UNDER": 2 },
      "avg_effective_edge": 6.1,
      "avg_expected_hr": 64.2
    }
  }
}
```

---

## Monitoring the New System

### Daily automated checks
- **Model trust dashboard:** Which models are contributing picks? What trust scores?
- **Source attribution:** What % of best bets come from non-V9 models?
- **Quality gate effectiveness:** How many picks filtered by expected HR < 60%?
- **Direction balance:** What % OVER vs UNDER? (Flag if >90% one direction)
- **Hit rate by source:** Graded HR for V9-sourced vs non-V9-sourced best bets

### Weekly review questions
- Is trust-weighted scoring beating raw-edge ranking?
- Are non-V9 picks hitting at comparable rates?
- Has the expected HR lookup table drifted from reality?
- Should any edge/trust thresholds be adjusted?

### Automated alerts
- **Source concentration:** If >95% of best bets come from one model for 7+ consecutive days, alert (system isn't truly multi-source)
- **Trust crash:** If all models drop below 0.3 trust simultaneously, alert (systemic issue)
- **Expected HR table stale:** If lookup table hasn't been refreshed in 7+ days, alert

---

## What We're NOT Doing (Dead Ends)

1. **Signal-weighted composite scoring.** Session 297 proved edge-first beats signal-scored selection (71.1% vs 59.8% HR). Do not revert.
2. **ELO ratings for models.** Over-engineered for this domain. Bayesian credibility weighting is simpler and better suited to small sample sizes.
3. **Averaging edges across models.** If V9 says edge 2.0 and Q43 says edge 6.1, averaging gives 4.05 which fails the edge floor. Take the best offer, don't dilute.
4. **Hard model exclusion based on HR threshold.** Binary cutoffs create cliff effects. Smooth trust multipliers degrade gracefully.
5. **V12 MAE agreement as positive signal.** Data shows it's anti-correlated. Use as negative signal only.

---

## Summary

| Phase | What Changes | Key Metric | Effort |
|-------|-------------|------------|--------|
| **A: Multi-source candidates** | Query all models, "best offer" dedup | % picks from non-V9 | 2-3 sessions |
| **B: Trust-weighted scoring** | effective_edge = raw_edge × trust × staleness | Backtest P&L improvement | 2-3 sessions |
| **C: Quality gates** | 60% expected HR floor, direction-specific rules, consensus adjustments | Live P&L improvement | 1-2 sessions |

**Blocker:** Quantile model grading volume must exist before Phase A can be validated. Fix the grading pipeline first if needed.

**Rollback plan:** Each phase is independently reversible. Phase A → fall back to V9-only. Phase B → fall back to raw edge ranking. Phase C → remove quality gate.
