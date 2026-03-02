# Session 385: Forward-Looking Roadmap — Model Filtering, Monitoring & Signal Strategy

**Date:** 2026-03-02
**Companion doc:** `00-FINDINGS.md` (investigation results, all 5 gates NO-GO)

---

## Table of Contents

1. [What We Learned](#1-what-we-learned)
2. [Profile System Phase 2 Design](#2-profile-system-phase-2-design)
3. [Model Selection Improvements](#3-model-selection-improvements)
4. [Signal System Evolution](#4-signal-system-evolution)
5. [Ultra Bets Expansion](#5-ultra-bets-expansion)
6. [Monitoring & Alerting Improvements](#6-monitoring--alerting-improvements)
7. [Retraining Strategy](#7-retraining-strategy)
8. [Patterns from Dead Ends](#8-patterns-from-dead-ends)
9. [Prioritized Roadmap](#9-prioritized-roadmap)

---

## 1. What We Learned

### The Filter Stack Is Highly Effective

The Session 385 investigation confirmed a pattern that emerged across Sessions 372-374: raw prediction weakness at the model level does NOT translate to best bets weakness. The 14+ hardcoded filters, signal count floor (>=3), edge floor (>=3), player blacklist, and model HR weighting form a screening stack that catches problems before they reach picks.

The profile system's observation mode validated this — it identified the same weaknesses as the hardcoded filters. It is confirming the existing stack is correct, not finding new gaps.

### The 4 Affinity Groups Are the Right Abstraction

Within each group, models make identical predictions on the same players. Differentiation is BETWEEN groups:

| Group | Best Bets N | HR | Character |
|-------|-------------|-----|-----------|
| v9 | 66 | 63.6% | Volume leader (56% of picks), broad coverage |
| v12_vegas | 35 | 74.3% | Quality leader, vegas-informed, Feb-vulnerable (-31.5pp) |
| v12_noveg | 12 | 58.3% | Feb-only data, weakest group, monitor closely |
| v9_low_vegas | 4 | 75.0% | UNDER specialist, tiny sample, promising |

Per-model filtering (33 models) is the wrong abstraction. Per-group filtering (4 groups) is correct but lacks sample size today.

### The AWAY Block Is a Cautionary Tale

Profile blocking identified AWAY as a weak dimension at the raw prediction level (43-48% HR). But in best bets, AWAY-blocked picks were winning at 66.7% HR (N=12). Activating blocking wholesale would have **removed profitable picks**. This validates the observation-mode-first approach and means we should be cautious about any dimension where the filter stack is already compensating.

### The "Filter Stack Handles It" Fragility Risk

The flip side: the system depends on ~20 hardcoded filters remaining correctly configured. If any filter degrades or is accidentally removed (deployment drift, refactoring), the raw-level weaknesses the profile system sees would flow into best bets. The profile system serves as a **safety net** that validates the filter stack is working — even in observation mode, it has diagnostic value.

---

## 2. Profile System Phase 2 Design

### Selective Dimension Activation

Not all dimensions are safe to activate. Phase 2 should activate dimensions independently:

| Dimension | Phase 2 Action | Rationale |
|-----------|---------------|-----------|
| `direction` | **Activate first** | Most closely mirrors existing `model_direction_affinity` system. Known to separate winners from losers. |
| `tier` | Activate in Phase 3 | Trending correct in Q2 counterfactual (bench 0%, role 33%) but N=1-6. Need N>=20. |
| `edge_band` | Activate in Phase 3 | No overlap with existing hardcoded filters. Safe to add. |
| `signal` | Activate in Phase 3 | Zero overlap with hardcoded filters. Could catch model+signal combos like v12_noveg + book_disagreement. |
| `home_away` | **Observation-only permanently** | AWAY blocks are structurally wrong — 66.7% HR in best bets. The filter stack compensates for raw AWAY weakness. |
| `line_range` | Phase 3 at earliest | Insufficient data, overlaps with tier dimension. |

### Graduated Response (Not Binary Blocking)

Replace the binary `is_blocked` flag with a 3-zone system:

| Zone | Condition | Action |
|------|-----------|--------|
| **Green** | HR >= 52.4% | No action |
| **Yellow** | HR 45-52.4%, N >= 15 | Apply 0.85x multiplier to `model_hr_weight` in ROW_NUMBER. Model is less likely to win selection but not excluded. |
| **Red** | HR < 45%, N >= 15 | Hard block (same as current `is_blocked`) |

The yellow zone is important — it provides a softer intervention than binary blocking and avoids the Q2 problem of removing potentially profitable picks entirely.

### Integration Path: Profile → ROW_NUMBER

The cleanest integration is joining `model_profile_daily` directly into the `supplemental_data.py` SQL that computes `model_hr_weight`. For the direction dimension:

```sql
LEFT JOIN (
  SELECT model_id, dimension_value AS direction, hr_14d, n_14d
  FROM model_profile_daily
  WHERE dimension = 'direction'
    AND game_date = (SELECT MAX(game_date) FROM model_profile_daily WHERE game_date < @target_date)
) profile_dir ON profile_dir.model_id = amp.system_id
    AND profile_dir.direction = amp.recommendation
```

Then modify `model_hr_weight` to prefer direction-specific HR when available:

```sql
LEAST(1.0, COALESCE(
  -- Phase 2: direction-specific HR from profile when N >= 15
  CASE WHEN profile_dir.n_14d >= 15 THEN profile_dir.hr_14d ELSE NULL END,
  -- Existing fallback chain
  CASE WHEN mh.bb_n_21d >= 8 THEN mh.bb_hr_21d ELSE NULL END,
  CASE WHEN mh.n_14d >= 10 THEN mh.hr_14d ELSE NULL END,
  50.0
) / 55.0) AS model_hr_weight
```

This uses the existing ROW_NUMBER mechanism — no new filter, no new code path. Profile data flows naturally into model selection.

### Deprecation Path for model_direction_affinity

Once Phase 2 direction blocking is active in the ROW_NUMBER SQL, the aggregator's hardcoded `model_direction_affinity` filter becomes redundant. Run both in parallel for 2 weeks. If the profile system blocks a superset of what affinity blocks, remove `model_direction_affinity` and let the profile-informed ROW_NUMBER handle it.

### Bayesian Threshold Alternative

Instead of fixed 45% / N>=15 thresholds, consider a Bayesian approach:
- Start with Beta(5, 5) prior (50% HR, equivalent to 10 pseudo-observations)
- Update with observed wins/losses
- Block when posterior 90th percentile falls below 52.4% (breakeven)

This naturally handles sample size: with N=7, even 0% observed HR won't trigger because the prior dominates. With N=30 at 40% HR, the posterior clearly triggers. More principled than binary cutoffs.

---

## 3. Model Selection Improvements

### Direction-Conditional HR Weighting (Most Promising)

The current `model_hr_weight` blends OVER and UNDER performance into one number. But v9 shows 45.5% OVER starter vs 75.0% UNDER starter — a model excellent at UNDER gets a middling weight applied to OVER.

Direction-specific weighting via the `model_profile_daily` table's direction dimension (see Phase 2 integration above) would fix this naturally. When the profile system has direction-specific N >= 15 per model consistently (~3-4 weeks), this becomes a clean, low-risk change.

### Ideas Evaluated and Rejected

| Idea | Verdict | Reason |
|------|---------|--------|
| 7-day recency weighting | Reject | N drops below 10 frequently, triggers 50% default. W1-W6 stability (Session 369) means 14d is well-calibrated. |
| Losing streak demotion | Reject | Rolling HR is a smoother version of the same idea. 5-loss streaks on N=12 groups would false-positive on profitable models. |
| v9_low_vegas UNDER boosting | Monitor | N=4 far too small. Direction-conditional weighting would capture this automatically at N>=20. |
| Cross-group ensemble (require 2+ groups to agree) | Dead end | V9+V12 agreement is ANTI-correlated (CLAUDE.md). Requiring agreement would filter winners. |

---

## 4. Signal System Evolution

### 4a. Group-Consensus Signal

The `CrossModelScorer` counts model agreement but treats all models equally. It doesn't distinguish which *groups* agree.

**Idea:** `cross_group_agreement` signal that fires when 2+ affinity groups independently agree on direction+player. Two groups agreeing means genuinely different model architectures converge.

**Why it might work where model agreement failed:** The original `diversity_mult` was removed because V9+V12 agreement was anti-correlated. But that lumped v12_vegas (74.3% HR) with v12_noveg (58.3% HR). Agreement between *specific high-performing groups* (v9_low_vegas + v12_vegas) is a fundamentally different signal.

**Status:** Monitor. v9_low_vegas needs N>=20 before evaluation.

### 4b. Confidence-Weighted Signal Counting

The aggregator uses flat `MIN_SIGNAL_COUNT = 3`. But `_weighted_signal_count()` already exists (line 614) with health multipliers (HOT=1.2x, COLD=0.5x) — it's just never used for selection, only pick angles.

**Idea:** Replace `len(qualifying) < 3` with `weighted_signal_count < 2.5`. Three HOT signals (weighted 3.6) are stronger than three COLD signals (weighted 1.5).

**Status:** Log weighted SC in observation mode first. Gather data on whether weighted SC separates winners from losers better than raw SC.

### 4c. Model-Aware Signal Gating

Instead of signals being model-agnostic, let the aggregator exclude specific signals for specific groups:

```python
SIGNAL_MODEL_EXCLUSIONS = {
    'v12_noveg': {'book_disagreement'},   # 14.3% HR (N=7)
    'v12_vegas': {'edge_spread_optimal'},  # 20.0% HR (N=5)
}
```

When computing qualifying signals, exclude signals in the group's exclusion set. Simple, targeted, and the profile system already tracks the data to populate this mapping.

**Status:** Activate when book_disagreement reaches N>=15 for v12_noveg while staying below 40%.

### 4d. Direction-Adjusted Signal Floor

OVER and UNDER have fundamentally different filter stacks (4 OVER-specific filters vs 10+ UNDER-specific). Yet the signal count gate is symmetric. Session 374b showed SC=3 OVER = 33.3% while SC=3 UNDER = 62.5%.

**Idea:** `MIN_SIGNAL_COUNT_OVER = 4`, `MIN_SIGNAL_COUNT_UNDER = 3`. Or subsume the existing `sc3_edge_floor` filter into a cleaner direction-specific floor.

**Status:** The sc3_edge_floor already handles the worst case (SC=3 OVER blocked unless edge >= 7). A full direction-specific floor would be a larger change with modest incremental benefit. Low priority.

### 4e. Market-Derived Signal Focus

**Pattern from dead ends:** Successful signals encode market information the model doesn't see (sharp_line_move_over 67.8%, line_rising_over 96.6%, book_disagreement 93.0%). Failed signals encode game-context patterns the model already captures (b2b_fatigue 39.5%, blowout_recovery 50%).

**Future signal research should prioritize:**
- Line *acceleration* (how fast the line is moving, not just magnitude)
- Closing line value (CLV) as a post-hoc quality signal
- Steam move detection (sudden multi-book line shifts)
- Reverse line movement (line moves opposite to public betting %)

These bring information the model's 50 features don't include.

---

## 5. Ultra Bets Expansion

### Group-Aware Ultra Criteria

Current ultra criteria are all v12-based (`source_family.startswith('v12')`). This matches both v12_vegas (74.3% HR) and v12_noveg (58.3% HR) indiscriminately.

**Idea:** Use `get_affinity_group()` instead of `startswith('v12')` to create group-specific criteria:
- `v12_vegas_under_edge_5plus`: v12_vegas group + UNDER + edge >= 5.0

This wouldn't fire alone (need 2+ criteria per Session 382), but combined with `v12_edge_6plus` it creates a ultra-UNDER pathway. Ultra UNDER is currently 57.1% (8-6) — group-aware classification could improve this.

### Signal-Conditioned Ultra

No signal information is currently used in ultra classification.

**Idea:** `high_sc_high_edge` ultra criterion — signal count >= 5 AND edge >= 4.0. This captures "multi-angle conviction" that pure edge criteria miss. The signal landscape has changed dramatically since the ultra system was designed (Session 326-327: ~12 signals → now 21 signals).

### Refresh the Backtest Window

`BACKTEST_START` and `BACKTEST_END` in `ultra_bets.py` are frozen at Jan 9 - Feb 21. Now 10+ days stale. The criteria should be periodically re-backtested on the full graded window and parameters updated.

---

## 6. Monitoring & Alerting Improvements

### Leading Indicators (Predict Problems Before HR Drops)

| Indicator | What to Track | Alert Threshold | Why It Leads |
|-----------|---------------|-----------------|--------------|
| **Edge distribution shift** | `mean_edge` and `edge_stddev` per model per day | >1.5 StdDev from 14d mean | Calibration drift precedes HR drops |
| **Direction ratio shift** | `pct_over` per model per day | >15pp shift over 3 days | 80/20 OVER/UNDER ratio preceded Feb collapse |
| **Prediction distribution shape** | `prediction_stddev` per model | Narrowing range (clustering) | Suggests over-reliance on one drifting feature |
| **Mean edge divergence** | `mean_abs_edge` vs historical | >2pp sudden increase | Either found an edge OR model has drifted |
| **Feature distribution drift** | `usage_spike_score` (or next drift-prone feature) below training-period 25th percentile for 5+ days | Escalate to WATCH immediately | Leading indicator — by the time HR drops, weeks of bad predictions have been made |

### New Daily Checks

| Check | What It Does | Why It's Needed |
|-------|-------------|-----------------|
| **Signal firing rate monitor** | For each of 21 signals, compute firing rate on edge 3+ predictions. Flag any signal with 0 fires in 3 days. | Catches broken signal data pipelines (like trends-tonight going stale in Session 349) |
| **Best bets direction balance** | Track OVER/UNDER ratio daily. Alert if >70/30 for 3+ consecutive days. | Would have caught the OVER collapse earlier |
| **Ultra gate progress tracker** | Report current N and HR toward public exposure (N>=50, HR>=80%). Project date at current pace. | Plan the public launch of ultra bets |
| **Filter rejection rate trends** | Log per-filter rejection counts daily. Alert if any filter rejects 3x its normal volume. | Detects upstream data shifts (e.g., opponent_under_block suddenly rejecting 40% instead of 15%) |
| **Profile counterfactual (best bets)** | For picks that profiling *would have blocked*, query their actual best bets HR. | Automates the Q2 analysis that caught the AWAY false positive |

### Alert Fatigue Reduction

1. **Severity tiers with cooldowns.** After alerting on a specific model+dimension, suppress the same alert for 3 days unless severity escalates.
2. **Aggregate daily digest.** Consolidate profile monitor + decay detection + deployment drift into a single daily Slack message instead of per-check alerts.
3. **Action-required vs informational separation.** Stale block recovery (RECOVER_HR = 55% for 3 days) generates INFO alerts mixed with monitoring. Separate into an action queue.

### Automated Model Lifecycle Triggers

| Trigger | Condition | Action | Rationale |
|---------|-----------|--------|-----------|
| **Auto-disable** | 14d best bets HR < 40%, N >= 10 | Set `is_active=FALSE` for model predictions + flag in registry | XGBoost incident (Session 378c) showed manual detection is too slow |
| **Auto-promote from shadow** | 14d best bets HR > 65%, N >= 20 | Alert + human-approved promotion via Slack | Reduces the manual shadow → promote pipeline |
| **Staleness demotion** | Model age > 28 days AND 14d HR < 55% | Auto-demote to shadow | Prevents Feb scenario where stale models stayed in production too long |

---

## 7. Retraining Strategy

### The Retraining Paradox

The 56-day window (Dec 15 - Feb 8) was validated as optimal. But Feb decline is a structural seasonal pattern — `usage_spike_score` collapses from 1.14 → 0.28 as rotations stabilize post-ASB. Training on Dec-Jan data learns a feature distribution that no longer exists. Training on Feb data includes the decayed distribution with lower signal.

Retraining alone cannot fix seasonal drift if the underlying features have shifted. The model will either learn the old distribution and fail, or learn the new (weaker) distribution.

### Cadence Adjustment

Models are stable across W1-W6 of lifecycle (70-75%, StdDev 1.6pp) with a cliff at W7-W8 (Session 369). This means:
- **7-day cadence is too frequent** — weekly retrains produce models that perform identically to the previous version
- **42-day (6-week) lifecycle ceiling** — beyond this, degradation is reliable

Recommendation: Switch to **14-day retrain cadence** with retrain-reminder thresholds at 14d (ROUTINE), 28d (OVERDUE), 42d (URGENT).

### Vegas-Weight Dampening During Regime Shifts

v12_vegas declined -31.5pp in Feb vs v9's -9.8pp. Vegas-heavy models are more sensitive to market feature drift.

**Idea:** When the decay-detection state machine enters WATCH or DEGRADING, automatically apply a 0.9x dampener to `model_hr_weight` for vegas-heavy models (v12_vegas group). Not blocking — just reducing their influence in ROW_NUMBER during periods when market features are likely misaligned.

### Practical Next Steps (March)

1. **Retrain v12_noveg** with 56d window (Dec 22 - Feb 15) + vw015. Validated best configuration.
2. **Monitor v9_low_vegas** — if it sustains 65%+ at N >= 20, its low vegas weight makes it naturally resilient to seasonal drift.
3. **Track `usage_spike_score` recovery** — if March data shows recovery, existing models may improve without retraining. If it stabilizes at the new level, consider excluding or downweighting the feature.

---

## 8. Patterns from Dead Ends

Reviewing 50+ experiments across Sessions 326-385, clear anti-patterns emerge:

### Stop Trying: Adding Features to CatBoost V12

V12_noveg (69-73%) consistently beats every variant: V13 (65.8%), V15 (69.7%), V16 (55.9%), V17 (56.7-58.1%), V18 (48-59%). CatBoost's tree-based splitting already handles the distributions new features try to encode. Feature importance for added features is consistently <1-2%. The 50-feature V12_NOVEG set is at the feature count ceiling for ~2,000 training samples.

### Stop Trying: Quantile Loss Functions

Q43+Vegas (20% HR), Q55 (non-deterministic), Q60 (volume without profit), V16 Q55 (48.9%), noveg Q43 (14.8% live). MAE loss with vegas weight 0.15-0.25x is the proven winner. Quantile models either overfit to directional bias or introduce non-determinism.

### Stop Trying: Filter Tuning for Raw-Level Weakness

Sessions 372-374 and now 385 repeatedly showed: patterns that look terrible at raw prediction level (48-50% HR) often don't affect best bets because existing filters screen them out. **Before implementing ANY new filter, run the best-bets counterfactual.** Only act when best-bets-level HR is below 45% on N>=20.

### Settled Science: Training Window

42-63 day window, starting mid-December to mid-January. Any experiment outside this range should be rejected without running:
- Too short (21-35d): insufficient training data
- Too long (87-96d): old data dilutes signal
- Sweet spot: 49-56d (71.79-73.9% HR)

### Still Promising: What to Explore

| Direction | Why It Has Potential | Status |
|-----------|---------------------|--------|
| **Fresh retraining on Dec-Jan data** | Highest-leverage improvement. 56d window + vw015 validated. | March priority #1 |
| **Market-derived signals** | sharp_line_move_over (67.8%), line_rising_over (96.6%) prove market info adds value the model doesn't have | Ongoing |
| **Group-aware selection** | 4-group abstraction is sound, just needs data | Monitor → act at N>=30 per group |
| **Profile system Phase 2** | Direction dimension integration into ROW_NUMBER is clean and low-risk | 3-4 weeks |
| **Ultra criteria expansion** | Signal-conditioned ultra + group-aware criteria | After ultra backtest refresh |

---

## 9. Prioritized Roadmap

### Immediate (This Week)
- [x] Session 385 investigation complete — all gates NO-GO documented
- [ ] Fresh retrain with 56d window + vw015 (highest leverage action)

### Short-Term (2-4 Weeks)
- [ ] Monitor book_disagreement for v12_noveg → act at N>=15
- [ ] Monitor v12_noveg group overall → act at N>=30
- [ ] Monitor v9 OVER starter → act at N>=20
- [ ] Log weighted signal count in observation mode (4c above)
- [ ] Add profile counterfactual check to daily monitoring
- [ ] Add signal firing rate monitor to daily checks
- [ ] Refresh ultra backtest window

### Medium-Term (4-8 Weeks)
- [ ] Phase 2: Activate direction dimension in profile blocking (graduated response)
- [ ] Integrate direction-specific HR into `model_hr_weight` via `model_profile_daily` join
- [ ] Run model_direction_affinity vs profile direction parallel comparison
- [ ] Evaluate group-consensus signal if v9_low_vegas reaches N>=20
- [ ] Implement model-aware signal gating if monitoring thresholds hit

### Long-Term (8+ Weeks)
- [ ] Phase 3: Activate tier, edge_band, signal dimensions
- [ ] Deprecate model_direction_affinity if profile direction subsumes it
- [ ] Evaluate direction-adjusted signal floor
- [ ] Implement automated model lifecycle triggers (auto-disable, staleness demotion)
- [ ] Consider Bayesian threshold replacement for fixed HR/N cutoffs

---

## Key Files Reference

| File | Role |
|------|------|
| `ml/signals/aggregator.py` | Filter application — observation mode at lines 407-439 |
| `ml/signals/model_profile_loader.py` | `ModelProfileStore.is_blocked()` |
| `ml/analysis/model_profile.py` | Daily profile computation |
| `ml/signals/model_direction_affinity.py` | 4-group mapping (`get_affinity_group()`) |
| `ml/signals/cross_model_scorer.py` | Cross-model agreement scoring |
| `ml/signals/ultra_bets.py` | Ultra classification criteria |
| `data_processors/publishing/supplemental_data.py` | ROW_NUMBER model selection (line 178) |
| `bin/monitoring/model_profile_monitor.py` | Profile monitoring |
| `bin/monitoring/filter_health_audit.py` | Filter counterfactual evaluation |
