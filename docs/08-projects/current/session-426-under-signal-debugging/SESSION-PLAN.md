# Session 426: UNDER Signal Debugging + Cross-Season Analysis

**Date:** 2026-03-06
**Algorithm:** v426_cross_season_rebalance (staged — weight changes pending Mar 7 observation)
**Status:** Stage A complete, Stage B pending Mar 7+8 grading

## Investigation 1: Shadow UNDER Signals Zero Fires (RESOLVED)

### Root Cause: Deployment Timing

All 4 shadow UNDER signals were created and pushed to main on Mar 6 between 14:51 and 15:14 PST (22:51-23:14 UTC). The daily Phase 6 export runs at ~11 AM ET (08:00 PST). **No export has ever run with these signals deployed.**

| Signal | Created Commit | Push Time (PST) |
|--------|---------------|-----------------|
| volatile_starter_under | 75e17fe2 | Mar 6 14:51 |
| downtrend_under | 75e17fe2 | Mar 6 14:51 |
| star_favorite_under | 75e17fe2 | Mar 6 14:51 |
| starter_away_overtrend_under | d6ecdd58 | Mar 6 15:14 |

Additionally, many filters from Sessions 413-422 (flat_trend, b2b_under_block, mid_line_over, etc.) were also pushed on Mar 5-6, meaning the entire filter rebalance is untested in production.

### Validation: Signals Are Correctly Wired

Confirmed via code review and BQ analysis:

1. **Signal code** — All 4 properly inherit BaseSignal, registered in registry.py, in UNDER_SIGNAL_WEIGHTS
2. **Prediction dict fields** — All required fields (`trend_slope`, `points_std_last_10`, `spread_magnitude`, `over_rate_last_10`, `is_home`) are properly mapped in supplemental_data.py (lines 1118-1147)
3. **Feature data** — 92-100% populated across all key features (Mar 1-6)
4. **979 qualifying opportunities** exist at feature level:
   - volatile_starter: 26
   - downtrend: 286
   - star_favorite: 419
   - starter_away_overtrend: 162
   - mean_reversion: 86
5. **Retroactive check** — Of 17 actual UNDER BB picks from Feb 20-Mar 6:
   - 7-8 would qualify for star_favorite_under
   - 3-4 would qualify for downtrend_under
   - 1+ would qualify for starter_away_overtrend_under

### Prediction for Mar 7 Export

First production test. Expected signal fires (based on feature data patterns):
- star_favorite_under: Highest fire rate (any star UNDER pick with spread 3+)
- downtrend_under: Moderate fire rate (slope -1.5 to -0.5, common range)
- volatile_starter_under: Lower fire rate (edge 5+ requirement is restrictive)
- starter_away_overtrend_under: Moderate (away starters with 50%+ over rate)

### Action: Monitor Mar 7 Export

```sql
-- Run after Mar 7 ~11:30 AM ET
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.signal_best_bets_picks,
UNNEST(signal_tags) AS signal_tag
WHERE signal_tag IN ('volatile_starter_under', 'downtrend_under',
                      'star_favorite_under', 'starter_away_overtrend_under',
                      'mean_reversion_under')
  AND game_date = '2026-03-07'
GROUP BY 1
```

---

## Investigation 2: LGBM Model Deactivation Decision (COMPLETE)

**Result:** Mixed — one LGBM model is strong, one is harmful.

| Model | BB Picks (14d) | HR | Decision |
|-------|---------------|-----|----------|
| lgbm_v12_noveg_train0103_0227 | 6 | 33.3% (2-4) | DEACTIVATE |
| lgbm_v12_noveg_vw015_train1215_0208 | 8 | 80.0% (4-1) | KEEP |

**Action:** Deactivate `lgbm_v12_noveg_train0103_0227` — actively harming BB quality. Keep the older training window model (80% HR is excellent).

**Executed:** `python bin/deactivate_model.py lgbm_v12_noveg_train0103_0227` — SUCCESS.
- Disabled in model_registry (enabled=FALSE, status=blocked)
- Deactivated 119 predictions on 2026-03-06
- 0 BB picks affected (model wasn't sourcing any that day)

---

## Investigation 3: v12 Edge 5+ Underperformance (COMPLETE)

**Result:** The "45.5% at edge 5+" is entirely UNDER-driven. Edge band breakdown (14d):

| Band | Direction | N | HR |
|------|-----------|---|-----|
| 3-5 | OVER | 15 | 73.3% |
| 3-5 | UNDER | 60 | 55.0% |
| 5-7 | UNDER | 20 | 45.0% |
| 7+ | UNDER | 1 | 100% |

**No OVER predictions at edge 5+ in this window.** The UNDER edge 5-7 weakness (45.0%) is consistent with Session 421 findings that error scales with edge for UNDER. Not actionable — the edge floor and signal-first ranking already mitigate this.

---

## Investigation 4: predicted_pace_over Promotion (WAITING)

| Metric | Value | Threshold |
|--------|-------|-----------|
| Model HR | 63.6% | >= 60% |
| Model N | 22 | >= 30 (need 8 more) |
| BB HR | 66.7% (8-4) | >= 60% |
| Regime | NORMAL | - |

**Status:** 8 picks from N=30 promotion threshold. BB HR is strong at 66.7%. Will promote when N=30 is reached. Do NOT add to rescue yet (HR 63.6% < 65% threshold).

---

## Experiment: Cross-Season Signal Analysis (COMPLETE - Critical Findings)

### Feature Store Limitation

Features are completely empty for 2021-2023. Cross-season analysis is limited to ~1.5 seasons (mid-2024 onward). Spread (f41) only starts in 2025. Over_rate (f55) only starts late 2025.

### 2026 Baseline Drop

Model-level edge 3+ HR dropped from ~67% (2021-2025 average) to **54.3% UNDER / 54.7% OVER in 2026**. All signal HRs must be compared against this lower baseline.

### Signal Cross-Season Validation

| Signal | 2024 HR (N) | 2025 HR (N) | 2026 HR (N) | 2026 Lift vs Baseline | Verdict |
|--------|-------------|-------------|-------------|----------------------|---------|
| downtrend_under | 65.7% (394) | 64.1% (1,475) | 62.4% (651) | **+8.1pp** | HEALTHY — mild decay, strong lift |
| volatile_starter_under | 87.1% (70) | 79.2% (231) | 65.4% (104) | **+11.1pp** | HEALTHY — decaying but best lift |
| star_favorite_under | N/A | 48.7% (226) | 55.0% (822) | +0.7pp | WEAK — zero structural edge |
| mean_reversion_under | 75.7% (189) | 65.2% (784) | 53.0% (641) | **-1.3pp** | ALARMING — below baseline |

### Critical Actions

1. **star_favorite_under: Demote or remove.** The 73% HR from current-season shadow (N=88) is noise. Cross-season shows 48.7% in 2025, 55.0% in 2026 — no structural edge.
2. **mean_reversion_under: Review urgently.** This is a production rescue signal at weight 2.5, but 2026 HR is 53.0% — BELOW the 54.3% baseline. The 77.8% HR cited in memory is from model-level current-season data that doesn't match cross-season evidence. May need threshold tightening, weight reduction, or removal from rescue.
3. **volatile_starter_under: Strongest signal.** +11.1pp lift in 2026 despite decay. Worth promoting from shadow to active.
4. **downtrend_under: Reliable workhorse.** +8.1pp lift, highest volume (651 in partial 2026). Promote to active.

---

## Key Finding: Filter Stack Also Untested

The filter rebalance (Session 422) was also deployed on Mar 6. These active filters have never run in production:
- flat_trend_under (trend_slope -0.5 to 0.5) — blocks ~53% HR UNDER picks
- b2b_under_block (rest_days <= 1) — blocks 30.8% HR B2B UNDER
- mid_line_over (line 15-25 OVER) — blocks 47.9% HR mid-line OVER
- under_after_streak (3+ consecutive unders) — blocks 44.7% HR

Mar 7 will be the first test of the full filter+signal stack together. Monitor pick volume and filter rejection rates closely.

---

## Staged Implementation Plan

### Rationale for Staging

Three independent reviewers (devil's advocate, risk analyst, statistician) unanimously recommended staging changes rather than deploying everything at once. Key reasons:

1. **Sessions 422-425 are completely untested in production.** Mar 7 is the first-ever run of 4 new filters + 4 new signals + NULL fixes. Layering weight changes on top destroys diagnostic signal.
2. **"One small thing at a time"** — project core principle.
3. **mean_reversion_under has zero BB-level data.** Removing from rescue before seeing a single production fire is an irreversible decision based on ambiguous evidence.

### Stage A: LGBM Deactivation (COMPLETE - Mar 6)

- Deactivated `lgbm_v12_noveg_train0103_0227` (33.3% BB HR, 2-4)
- BQ-only operation, no code deploy needed
- Instant rollback: `UPDATE model_registry SET enabled=TRUE, status='watch'`
- Kept `lgbm_v12_noveg_vw015_train1215_0208` (80.0% BB HR, 4-1)

### Stage B: Signal Weight Rebalance (PENDING - After Mar 7 export + Mar 8 grading)

All changes to `ml/signals/aggregator.py`:

| Signal | Current | Proposed | Rationale |
|--------|---------|----------|-----------|
| `star_favorite_under` | Weight 1.5 | **Remove from UNDER_SIGNAL_WEIGHTS** | Cross-season lift +0.7pp = noise. Effective lift -8.2pp. Keep in registry for monitoring. |
| `mean_reversion_under` | Weight 2.5 + rescue | **Weight 1.5, KEEP in rescue 30 days** | Cross-season 53.0% in 2026 (-1.3pp vs baseline). But 77.8% vs 53.0% discrepancy unexplained (likely different model populations). Zero BB-level data. Conservative approach. |
| `volatile_starter_under` | Weight 1.5 (shadow) | **Weight 2.0** | Best cross-season lift +11.1pp. Wilson CI [77-93%] for 2024 data. Structural edge. |
| `downtrend_under` | Weight 1.5 (shadow) | **Weight 2.0** | Lift is *increasing* (1.3 → 0.5 → 8.1pp). Most reliable signal by trend. Highest volume (N=651 in 2026). |
| `starter_away_overtrend_under` | Weight 1.5 | **No change** | No cross-season data available (f55 only started late 2025). Wait for production data. |

Algorithm version: `v426_cross_season_rebalance`

### Stage B Prerequisites

Before deploying Stage B, verify Session 422-425 code works:

```sql
-- 1. Mar 7 pick volume and direction split
SELECT recommendation, COUNT(*) as picks,
  COUNTIF(signal_rescued) as rescued
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-07'
GROUP BY 1;

-- 2. New UNDER signal fires
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.signal_best_bets_picks,
UNNEST(signal_tags) AS signal_tag
WHERE game_date = '2026-03-07'
  AND signal_tag IN ('volatile_starter_under', 'downtrend_under',
                      'star_favorite_under', 'starter_away_overtrend_under',
                      'mean_reversion_under')
GROUP BY 1;

-- 3. Filter rejection rates
SELECT * FROM nba_predictions.best_bets_filter_audit
WHERE game_date = '2026-03-07';

-- 4. After Mar 7 games graded (Mar 8 morning)
SELECT bb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date = '2026-03-07'
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1;
```

### Stage B Go/No-Go Criteria

- Mar 7 picks generated successfully (> 0 total picks)
- No catastrophic filter dominance (single filter rejecting > 80% of candidates)
- UNDER signal fire rate > 0 for at least 2 of the 4 new signals

### Rollback Plan

| Change | Rollback Method | Time |
|--------|----------------|------|
| LGBM deactivation | `UPDATE model_registry SET enabled=TRUE, status='watch'` | 2 min |
| Weight changes | `git revert` + push (auto-deploy) | 10 min |
| Re-trigger export | Manual Pub/Sub: `{"export_types": ["signal-best-bets"], "target_date": "YYYY-MM-DD"}` | 5 min |

---

## Cross-Season Analysis: Detailed Findings

### Methodology Caveats (from peer review)

1. **Different model versions per year.** Signal HR is inseparable from the model that generated predictions. Cross-season comparisons conflate signal quality with model quality.
2. **Survivorship bias.** Signals were discovered using recent data — finding they "worked" historically is partially tautological.
3. **NULL features pre-2024.** Three years of data completely unavailable.
4. **Lift vs raw HR is the right metric.** The 2026 baseline drop (54.3% vs ~67%) accounts for 13pp of apparent decay across all signals.

### Statistician's Lift Analysis (recency-weighted)

| Signal | Effective HR | Effective Lift | 2026 Lift Trend |
|--------|-------------|----------------|-----------------|
| volatile_starter_under | 75.6% | +13.5pp | Declining but strong |
| downtrend_under | ~63.8% | +1.7pp | **Increasing** (best trend) |
| star_favorite_under | 53.9% | **-8.2pp** | Negative |
| mean_reversion_under | 60.2% | **-1.9pp** | Collapsing |

### The 77.8% vs 53.0% Discrepancy (mean_reversion_under)

Same signal, same 2025-26 season. Most likely explanation: **different model populations.**
- N=212 (77.8%): Single champion model or favorable model subset
- N=641 (53.0%): All models in fleet
- If the 212 best-model picks hit at 77.8%, the remaining 429 picks would need 40.7% HR — indicating weaker models generate anti-predictive mean_reversion signals

**Implication:** The signal may work well for the best models but is NOT robust across the fleet. Weight reduction (not removal) is the right approach until BB-level data resolves this.

### Monitoring Schedule

| Date | Action |
|------|--------|
| Mar 7 ~11:30 AM ET | Check Mar 7 export: pick volume, signal fires, filter rejections |
| Mar 8 morning | Grade Mar 7 picks. Assess Session 422-425 performance. |
| Mar 8-9 | If healthy: deploy Stage B weight changes |
| Mar 20 | Review: volatile_starter + downtrend BB-level HR at N >= 15 |
| Apr 5 | mean_reversion rescue decision: keep or remove based on 30 days BB data |
| Apr 5 | projection_delta + sharp_money feature experiments (30 days accumulated) |
