# Session 295 Handoff — Signal System Comprehensive Audit, Direction Alignment

**Date:** 2026-02-18
**Previous:** Session 294 — Prop line delta signal, UNDER anti-pattern filters, f54 feature

## Summary

1. Built full-season signal system audit tool (`signal_system_audit.py`) — 5 audits, Nov 2025–Feb 2026
2. **Signal system validated:** +9.2pp HR over pure edge baseline (67.8% vs 58.6%, +$3,270 P&L)
3. Fixed combo_3way UNDER anti-pattern: OVER 95.5% vs UNDER 20.0% — now OVER-only
4. Added 3 combo registry entries: volatile_under (73.1%), high_usage_under (68.1%), prop_line_drop_over (79.1%)
5. Ran UNDER signal co-occurrence analysis — signals work but overlap exists
6. Evaluated dual_agree/model_consensus — both breakeven (44.8-45.5%), recommend removal
7. Identified model calibration drift as root cause of February decay (not signal failure)

## Current State

| Component | Status |
|-----------|--------|
| Production model | `catboost_v9_33f_train20251102-20260205` — 14 days old, DEGRADING |
| Feature store | 55 features (f54 not backfilled) |
| Signal count | **19 active** (2 flagged for removal: dual_agree, model_consensus_v9_v12) |
| Combo registry | **13 entries** (was 10): 11 SYNERGISTIC, 2 ANTI_PATTERN |
| Algorithm version | `v295_direction_alignment` |
| Games | Resume Feb 19 — All-Star break ends |
| Code | Committed (`4bdc4abb`, `bb75cb8f`), **not yet pushed** |

## Start Here

```bash
# 1. Push to deploy
git push origin main

# 2. Run daily steering after games resume (Feb 19)
/daily-steering

# 3. Retrain when 2-3 days of eval data exist (Feb 21+)
./bin/retrain.sh --promote --eval-days 3

# 4. Remove dual_agree + model_consensus signals (deferred, see below)
```

---

## What Was Implemented

### 1. Signal System Audit Tool

**File:** `ml/experiments/signal_system_audit.py`

Comprehensive 5-audit tool that answers:
1. Does signal system beat pure edge? **YES, +9.2pp HR, +$3,270 P&L**
2. Model directional bias? **V9 is OVER-biased: 63.1% vs 54.9% UNDER**
3. Signal-model alignment? **UNDER signals perform well despite no OVER gap**
4. Consensus bonus value? **Marginal: +0.5pp, only 3 picks change**
5. Quantile model opportunity? **80% HR on unique picks but N=10 too small**

```bash
PYTHONPATH=. python ml/experiments/signal_system_audit.py --save
```

### 2. combo_3way OVER-Only Fix

**File:** `ml/signals/combo_3way.py`

Added direction filter. Before: BOTH directions, UNDER = 20.0% HR (N=5) getting +2.5 combo bonus. After: OVER-only, 95.5% HR (N=22).

### 3. New Combo Registry Entries

**Files:** `ml/signals/combo_registry.py`, BQ `signal_combo_registry`

| Entry | Direction | HR | Weight | Evidence |
|-------|-----------|-----|--------|----------|
| `volatile_under` | UNDER | 73.1% | +1.0 | N=26, full-season audit |
| `high_usage_under` | UNDER | 68.1% | +0.5 | N=47, full-season audit |
| `prop_line_drop_over` | OVER | 79.1% | +1.0 | N=67, full-season audit |

---

## Key Research Findings

### UNDER Signal Co-Occurrence (276 UNDER edge-3+ picks)

| 0 UNDER signals | 173 picks | **45.1% HR** | Below breakeven — this is where losers live |
|:---|:---|:---|:---|
| 1 UNDER signal | 59 picks | **71.2% HR** | Huge jump — 1 signal is the key discriminator |
| 2 UNDER signals | 19 picks | **68.4% HR** | Good but slight regression from 1 |
| 3 UNDER signals | 24 picks | **70.8% HR** | Stable |

**Conclusion:** UNDER signals work. The MIN_SIGNAL_COUNT=2 gate (which counts model_health + 1 UNDER signal) is sufficient. No need for diversity enforcement.

**Overlap matrix (Jaccard):**
- high_usage_under + self_creator_under: **0.48** (high, 31 shared picks)
- high_usage_under + high_ft_under: **0.37** (moderate, 19 shared)
- self_creator_under + high_ft_under: **0.36** (moderate)
- bench_under is **independent** (0.00-0.06 with everything)
- volatile_under has **low overlap** with most (0.02-0.25)

**Implication:** self_creator_under is redundant with high_usage_under (48% overlap). Do NOT add combo entry.

### dual_agree / model_consensus — Remove Both

| Condition | N | V9 HR | Verdict |
|-----------|---|-------|---------|
| V9+V12 agree, both edge 3+ | 11 | 44.8% | Below breakeven |
| V9+V12 agree OVER, both edge 3+ | 2 | 0.0% | Catastrophic (tiny N) |
| V9+V12 agree UNDER, both edge 3+ | 9 | 55.6% | Barely above breakeven |
| V9+V12 disagree, V9 edge 3+ | 30 | 40.0% | Worse |

**Root cause:** V12 has too few edge-3+ predictions (only 50 total graded). Not enough data to form meaningful consensus. Both signals are noise at best.

### Model Calibration Drift (February Decay)

**What it is:** The champion model (trained Nov 2–Feb 5) learned scoring patterns from that window. By mid-February, those patterns shifted — the model underestimates UNDER targets by 7+ points (predicted 12.3, actual 19.6). Shadow models (Q45 at 60%, V12 at 56%) didn't collapse because they use different loss functions or feature sets.

**How to handle:**
1. **Retrain on 42-day rolling window** (already built: `./bin/retrain.sh --promote`)
2. **Weekly cadence** (7 days, Session 284 finding: +$20,720 vs 14d expanding)
3. **Monitor via decay-detection CF** (11 AM ET daily, Slack alerts on state transitions)
4. **Future:** Add direction-specific residual monitoring (track OVER-error and UNDER-error separately in `model_performance_daily`)

---

## Subset Architecture Review (For Next Session)

**Current state (not yet acted on):** The subset system has 3 layers:

| Layer | What | Count | Source |
|-------|------|-------|--------|
| L1 | Per-model subsets | 30 | `dynamic_subset_definitions` BQ table |
| L2 | Cross-model subsets | 5 | `cross_model_subsets.py` hardcoded |
| L3 | Signal best bets | 1 (`best_bets`) | Aggregator top-5 |

**Potential improvements identified but NOT yet implemented:**
- L2 subsets are observation-only — they don't feed into aggregator scoring
- `xm_quantile_agreement_under` subset could boost quantile UNDER picks in best bets
- No per-model signal profiles exist (all models use same signal config)
- Subset definitions haven't been audited for staleness

**Next session should:** Query `current_subset_picks` to see which subsets produce the best graded results, and consider promoting winning L2 subsets to influence L3 scoring.

---

## What's Next (Priority Order)

### 1. Push and Deploy (Immediate)

```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

### 2. Retrain Champion After Feb 21 (HIGH)

```bash
# After 2-3 days of post-All-Star eval data
./bin/retrain.sh --promote --eval-days 3
```

### 3. Remove dual_agree + model_consensus (MEDIUM)

Both signals at 44.8% HR add no value. Remove from registry, verify aggregator still performs. Small change: delete imports from `registry.py`, remove signal files, bump algorithm version.

### 4. Subset Performance Audit (MEDIUM)

Query graded subset picks to find which L1/L2 subsets actually produce winning picks:
```sql
SELECT subset_id, system_id,
  COUNT(*) as n,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.current_subset_picks csp
JOIN nba_predictions.prediction_accuracy pa USING (player_lookup, game_id)
WHERE csp.game_date >= '2025-12-01'
GROUP BY 1, 2 HAVING COUNT(*) >= 10
ORDER BY hr DESC
```

### 5. Add Direction-Specific Residual Monitoring (LOW)

Track OVER-error and UNDER-error separately in `model_performance_daily` to catch calibration drift earlier. Currently only tracks aggregate HR.

### 6. Backfill f54 + Retrain with New Feature (DEFERRED)

See Session 294 handoff for f54 backfill query. Blocked until retrain infrastructure absorbs 55-feature contract.

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/combo_3way.py` | OVER-only direction filter |
| `ml/signals/combo_registry.py` | 3 new entries, 3-way direction fix |
| `ml/signals/aggregator.py` | Algorithm version v295_direction_alignment |
| `ml/experiments/signal_system_audit.py` | **NEW** — 5-audit comprehensive tool |
| `CLAUDE.md` | Updated combo count, combo_3way direction |
| `docs/08-projects/current/signal-discovery-framework/SESSION-295-SIGNAL-SYSTEM-AUDIT.md` | **NEW** — audit findings doc |
| BQ `signal_combo_registry` | Updated 3-way, added 3 entries |

## Commits

```
4bdc4abb feat: combo_3way OVER-only fix, 3 new combo entries, signal system audit tool
bb75cb8f docs: Session 295 signal system audit findings
```

## Known Issues (Do NOT Investigate)

- f54 not backfilled: column exists, NULL for historical dates (Session 294)
- `features` array column: deprecated, dual-written, removal deferred
- V9 champion at 36.7% Feb HR: known, retrain pending after All-Star
- V12 has very few edge-3+ predictions: limits dual_agree/consensus usefulness
- self_creator_under overlaps high_usage_under (Jaccard 0.48): keep both, no combo entry for self_creator
- b2b_fatigue_under fires 0 times on UNDER edge-3+ pool: need B2B games in the data window

## Key Lessons

1. **Always validate direction-specific performance** — combo_3way's 88.9% average masked a 20% UNDER catastrophe getting +2.5 score bonus.
2. **Signal co-occurrence doesn't mean redundancy** — UNDER signals overlap but the key discriminator is 0 signals (45.1% HR) vs 1+ signals (71.2% HR). Even correlated signals add value.
3. **Consensus signals need sufficient base data** — dual_agree at N=11 is noise. V12 needs more edge-3+ predictions before cross-model consensus is meaningful.
4. **Model calibration drift is direction-specific** — V9 champion's February collapse was UNDER-specific (7+ point residual), not uniform. Direction-specific monitoring would have caught this earlier.
