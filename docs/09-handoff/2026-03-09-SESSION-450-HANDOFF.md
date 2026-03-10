# Session 450 Handoff — Per-Model Deploy, Scheduler Fixes, Mar 8 Autopsy

**Date:** 2026-03-09
**Focus:** Deploy accumulated changes, fix infrastructure, deep autopsy of worst day of season

## What Was Done

### 1. Committed & Pushed (Sessions 445-449 Backlog)

4 commits pushed, 15 Cloud Build triggers all SUCCESS:

| Commit | Content |
|--------|---------|
| `fix: Session 448-449 infra fixes` | decay-detection SQL fix, deploy.sh hardening, CF auto-deploy triggers |
| `feat: per-model pipeline refinements` | disabled_models filter fix, source_pipeline tagging, V9 SQL catch-all |
| `feat: MLB pipeline` | worker regressor, signals, season replay, supplemental loader |
| `chore: algorithm version v446` | Updated merger ALGORITHM_VERSION to `v446_per_model_deployed` |

### 2. Scheduler Fixes (4 jobs)

| Job | Fix |
|-----|-----|
| `filter-counterfactual-evaluator-daily` | Gen1 URL → Gen2 `run.app` + OIDC auth (was code=7) |
| `nba-props-pregame` | Legacy `nba-phase1-scrapers` → `nba-scrapers` (was code=4) |
| `nba-props-midday` | Same legacy service fix |
| `nba-props-morning` | Same legacy service fix |

Stale codes on `morning-deployment-check` (13) and `monthly-retrain-job` (13) will clear on next execution — already had correct Gen2 URLs from Session 448.

### 3. Per-Model Pipeline Now Live

Code was already wired in `signal_best_bets_exporter.py` (calls `run_all_model_pipelines()` + `merge_model_pipelines()`). The push triggered auto-deploy. Algorithm version `v446_per_model_deployed` will appear on next Phase 6 export.

### 4. Observation Promotion Check

`best_bets_filtered_picks` table only has 5 days of data (81 rows, Mar 3-7). All observations at N < 10. **Too early — revisit late March.**

### 5. Mar 8 Autopsy (3-11, 21.4% HR — Worst Day of Season)

8 investigation agents produced comprehensive analysis. See findings below.

## Mar 8 Autopsy — Key Findings

### Scorecard
```
Record:  3-11 (21.4%)  |  -8.27 units
OVER:    2-5 (28.6%)   |  UNDER: 1-6 (14.3%)
Rescued: 2-2 (50.0%)   |  Non-rescued: 1-9 (10.0%)
Ultra:   0-2 (0.0%)    |  No ultra: 3-9 (25.0%)
```

### Root Causes (8 agents converged)

**1. FT Explosion Night**
ALL 6 UNDER losses exceeded season FTA avg. Combined +23 extra FT attempts, ~+19 extra points. Booker 15/15 FT (9.2 pts above avg), KAT 8/8 (+4.5), Wemby 9/10 (+3.5), Thompson 7/8 (+3.1).

**2. Model Blind Spots on Specific Players**
- KAT: 28.1% UNDER HR across 32 predictions — every model picks UNDER, wrong 72% of time. Avg bias -6.9.
- Herro: 12.5% UNDER HR (8 recent preds). 66.7% season OVER rate.
- Both are systematic, not one-day noise.

**3. Line Anomaly (Derrick White ULTRA)**
Line dropped 51% (16.5→8.5). All 9 models predicted 14-16, creating artificial edge 5.4-7.4 that triggered ULTRA. Vegas knew something (injury/restriction). He went 2/9 FG despite 36 min. System has no line anomaly detector.

**4. LGBM Sourced 4/5 OVER Losses**
`lgbm_v12_noveg_vw015` has 49% HR in Feb-Mar. Systematically over-predicts scoring (+4.5 to +13.8 bias). Yabusele, Okoro, Avdija, Achiuwa all sourced from this model.

**5. mean_reversion_under Contributing to real_sc Despite Being Deweighted**
Fired on 4/6 UNDER losses. Already removed from UNDER_SIGNAL_WEIGHTS (Session 429) and rescue (Session 427), so it doesn't affect ranking or rescue eligibility. BUT it still counts toward real_sc (not in BASE_SIGNALS or SHADOW_SIGNALS). In 3 cases the "hot streak" was structural: Thompson (2nd-yr development), Wemby (66.7% season OVER rate), Herro (66.7% OVER rate). Guard: don't fire when season OVER rate > 60%, or move to SHADOW_SIGNALS to stop real_sc contribution.

**6. blowout_risk_under Signal Limitations**
Appeared on 5/6 UNDER losses as a tag. Note: this signal is in BASE_SIGNALS (no real_sc contribution) and the blocking filter (`blowout_risk_under_block_obs`) is observation-only (Session 436 demotion). The signal measures player blowout bench rate (ANY blowout, not directional). It doesn't distinguish team winning vs losing the blowout — starters on blowout-winning teams (SAS +25, MIA +11, PHX +12) score heavily before being pulled.

**7. Low real_sc UNDER Picks**
6 of 7 UNDER losses had real_sc of only 1-2. Current UNDER gate is real_sc >= 1 (at edge < 7). Base signals (starter_under, home_under, blowout_risk_under) inflate raw signal_count (used for SC >= 3 gate) but are correctly excluded from real_sc. The problem is that real_sc = 1 passes with minimal signal quality.

**8. Fleet Homogeneity**
All model pairs r >= 0.95. 70.8% UNDER predictions on a balanced day. Per-model pipeline can't fix identical inputs. The only balanced model (catboost_v9_low_vegas, 51.6% OVER) was disabled.

### What the Agents Found Would NOT Help
- `bias_regime_over_obs` promotion — targets WRONG direction (blocks OVER, but OVER was better side). Would have removed both OVER wins.
- `blowout_risk_under_block_obs` promotion — data too thin (N=10), threshold too broad (captures 65% of UNDER preds).
- Per-model pipeline — same models = same output. Confirmed by counterfactual analysis.
- Lowering OVER edge floor — BB OVER 3-4 still 35.3% HR. Floor is correct.

### FT Variance Signal Discovery
HIGH_FTA + HIGH_CV players (avg FTA >= 5, FTA CV >= 0.5) have 47.8% UNDER HR vs 70.6% for stable high-FTA players (22.8pp gap). Persists excluding Mar 8 (55.6% vs 70.6%). Pre-game computable — FTA avg and CV are stable player traits.

### Missed Covers Analysis
- **Jeremiah Fears** (+8.5): 8/8 model consensus OVER but no real signals at low line (9.5). Need "model_unanimity" signal.
- **Ryan Rollins** (-4.5): 7/7 unanimous UNDER blocked solely by B2B filter. B2B fatigue reinforces UNDER thesis.
- Pritchard, Brown, Jenkins — correctly blocked or weak consensus.

## Ranked Action Items

| # | Action | Impact | Risk | Effort |
|---|--------|--------|------|--------|
| 1 | **Line anomaly detector** — suppress picks when line drops 50%+ from recent avg | Prevents manufactured-edge ULTRA traps (White) | Low — rare event, clear signal | Medium |
| 2 | **Player-level UNDER suppression** — flag when model UNDER HR < 35% at N >= 20 | Blocks KAT (28%), Herro (12.5%) | Low — uses existing data | Medium |
| 3 | **Raise real_sc floor for UNDER to >= 2** | Blocks 5-6 of Mar 8 UNDER losses | Medium — reduces UNDER volume | Low |
| 4 | **FT variance observation** (`ft_variance_under_obs`) | 47.8% vs 70.6% HR split (22.8pp) | Low — observation only | Low |
| 5 | **mean_reversion_under guard** — don't fire when season OVER rate > 60%, or move to SHADOW_SIGNALS to stop real_sc contribution | Prevents misapplication to structural trends; already deweighted from ranking/rescue | Low | Low |
| 6 | **Model unanimity signal** — all models agree = real_sc credit | Captures Fears (8/8), Rollins (7/7) | Medium — new signal | Medium |
| 7 | **B2B UNDER consensus override** | Captures Rollins type picks | Low — rare scenario | Low |
| 8 | **blowout_risk_under direction awareness** — signal currently measures ANY blowout bench rate; add game-flow direction (winning vs losing blowout) to differentiate | Starters on winning-blowout teams score heavily before benching | Low | Medium |

## Pending / Waiting

- **2 BLOCKED models** (`lgbm_v12_noveg_vw015`, `xgb_v12_noveg_s42`) — decay-detection auto-disables at 16:00 UTC Mar 9
- **Per-model pipeline first live run** — next Phase 6 export (~6 AM ET Mar 10)
- **Observation promotion** — revisit late March when N >= 30
- **UNDER signal expansion** — still the biggest architectural opportunity

## Uncommitted Changes

None — all changes committed and pushed this session.

## Key Context for Next Session

- **Algorithm version:** `v446_per_model_deployed` (going live tomorrow)
- **9 enabled models**, 2 BLOCKED pending auto-disable
- **lgbm_v12_noveg_vw015** is BLOCKED and sourced 4/5 OVER losses — will be auto-disabled today
- **Mar 8 was an outlier** (3-11) but exposed real system gaps — action items above are ranked by impact
- **FT variance signal** is the strongest new discovery — deploy as observation first
- **Line anomaly detector** is the most critical safety gap — prevents ULTRA on manufactured edge
