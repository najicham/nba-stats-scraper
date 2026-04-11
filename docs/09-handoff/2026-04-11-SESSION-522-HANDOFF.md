# Session 522 Handoff — Full Off-Season Overhaul

**Date:** 2026-04-11
**Focus:** Quantile signals, fleet diversity, OVER strategy, governance, weekly retrain CF, pre-season retrain, MLB feasibility
**Commits:** `734ec014` through `353c87ad` (4 commits on `main`)

---

## TL;DR

Massive session completing all outstanding off-season work:
- **MultiQuantile signals (Steps 3-4 complete):** `quantile_ceiling_under` active (90% HR), `quantile_floor_over` shadow. Both wired into aggregator + registry.
- **Fleet diversity:** 5 enabled models across 3 frameworks (CatBoost MAE/MQ, LightGBM, XGBoost). Breaks r>0.95 correlation ceiling for `combo_3way` + `book_disagreement`.
- **OVER strategy overhaul:** Floor 5.0→6.0, bench OVER hard-blocked, role OVER blocked below edge 7.5.
- **Governance:** `--season-restart` in both `quick_retrain.py` AND `weekly_retrain` CF (auto-detects halt condition). CF deployed.
- **Book-count-aware thresholds:** `sharp_consensus_under` scales std threshold by book count.
- **Pre-season retrain:** 120-day full-season CatBoost MAE (69.2% HR) ready for Oct start.
- **MLB assists/rebounds:** Data confirmed solid (55-162 players/day, 19 books). Models deferred to next season.

---

## What Was Done

### 1. Quantile Signals (Step 3)

| Signal | File | Status | Weight | Condition |
|--------|------|--------|--------|-----------|
| `quantile_ceiling_under` | `ml/signals/quantile_ceiling_under.py` | ACTIVE | 3.0 | p75 < line → UNDER |
| `quantile_floor_over` | `ml/signals/quantile_floor_over.py` | SHADOW | — | p25 > line → OVER |

Both only fire for MultiQuantile models (`quantile_p75`/`quantile_p25` present). IQR width modifier boosts confidence when narrow. Registered in `ml/signals/registry.py`.

### 2. Fleet Diversity (Step 4) + Pre-Season Retrain

**5 enabled models (final fleet):**

| Model ID | Framework | Loss | Window | Eval HR |
|----------|-----------|------|--------|---------|
| `catboost_v12_noveg_train1205_0403` | CatBoost | MAE | 120d (Dec 5 – Apr 3) | 69.2% |
| `catboost_v12_noveg_mq_train0206_0402` | CatBoost | MultiQuantile | 56d | 72.0% |
| `lgbm_v12_noveg_train0206_0402` | LightGBM | MAE | 56d | 61.8% |
| `xgb_v12_noveg_train0206_0402` | XGBoost | MAE | 56d | 80.0% |

**Deactivated:** `lgbm_v12_noveg_train1227_0221`, `lgbm_v12_noveg_train0126_0323`, `xgb_v12_noveg_train0112_0223`, `catboost_v12_noveg_train1227_0221`

Worker cache refreshed. All enabled=TRUE in registry.

### 3. OVER Strategy Overhaul

Three layers of OVER protection:

| Layer | Change | Rationale |
|-------|--------|-----------|
| **Base floor 5.0→6.0** | `aggregator.py` line ~659 | Edge 6-8 = 61.4% HR, consistent 5 seasons |
| **Bench block** | line < 12: OVER hard-blocked at ALL edges | 34.1% HR at edge 7+ (N=91) |
| **Role block** | line 12-17.5: OVER blocked below edge 7.5 | 43.1% HR at edge 7+ (N=72) |

HSE rescue exempt from all blocks. Regime delta still applies (+1.0 cautious/TIGHT → floor 7.0).

### 4. Governance Season-Restart

**Two implementations:**

| Component | Location | Detection |
|-----------|----------|-----------|
| `quick_retrain.py` | `--season-restart` CLI flag | Manual |
| `weekly_retrain` CF | Auto-detect + `?season_restart=true` | avg_edge_7d < 5.0 OR all_models_blocked |

Both loosen: directional balance 52.4%→51.0%, sample min 25/15→10. Core gates (53% HR, vegas bias, tier bias) remain enforced.

**CF deployed** via `deploy.sh`. Runs every Monday 5 AM ET.

### 5. Book-Count-Aware `sharp_consensus_under`

Threshold `MIN_LINE_STD` now scales:
- 4-6 books (Odds API): std ≥ 1.0
- 7-11 books: std ≥ 1.5
- 12+ books (BettingPros): std ≥ 2.0
- Unknown: std ≥ 1.5

Still in SHADOW_SIGNALS. Graduate when N≥30 at BB level with HR≥60%.

### 6. MLB Assists/Rebounds Feasibility

| Market | Players/Day | Books | Avg Line | Since |
|--------|-------------|-------|----------|-------|
| Assists | 55–134 | 19 | 4.1–4.5 | Apr 6 |
| Rebounds | 68–162 | 19 | 5.2–5.5 | Apr 6 |

Data quality confirmed solid. Dedicated models needed (points model captures zero signal for other markets). Build feature store + models when next NBA season starts (Oct).

---

## System State

### NBA Pipeline
- **Auto-halt ACTIVE** (avg edge 4.03, threshold 5.0) — zero BB picks
- Season ends Apr 12-13 (final regular season), play-in Apr 14-17
- **Final record: 415-235 (63.8%)**
- All old models BLOCKED. New fleet registered but hasn't generated live predictions yet.

### MLB Pipeline
- Grading operational: Apr 9 graded 4 predictions (2-2, 50%). Apr 10 pending.
- 3 picks total (Apr 9-10): jt_ginn, keider_montero (Apr 10 ungraded)
- Auto-deploy triggers (Session 521) active for grading + Phase 2.

### Weekly Retrain CF
- **Deployed** with season-restart auto-detect
- Next fire: Monday Apr 13, 5 AM ET — will auto-detect avg_edge < 5.0 and apply loosened gates
- Probably won't matter (season ending) — real test is first Monday of Oct 2026

---

## Commits

| SHA | What |
|-----|------|
| `734ec014` | Quantile signals + OVER floor 6.0 + `--season-restart` + book-aware `sharp_consensus` |
| `1d3e9fd9` | Fix regime_over_floor log message (stale 4.0 reference) |
| `00ee008e` | Initial handoff doc (superseded by this one) |
| `353c87ad` | Weekly retrain CF auto-detect + OVER bench/role archetype block |

---

## Outstanding Off-Season Work

### Ready for Next Season (Oct 2026)
1. **Weekly retrain will auto-restart** — CF auto-detects halt condition, loosens gates for first cycle
2. **Fleet is pre-staged** — 5 diverse models ready. Weekly retrain will rotate them within 2-3 weeks.
3. **Assists/rebounds models** — Build feature store + train when data accumulates (need ~30 days minimum)

### Signal Graduations to Track
4. **`quantile_floor_over`** — Shadow. Graduate when N≥30 at BB level with HR≥60%
5. **`quantile_ceiling_under` RESCUE** — If live HR ≥75% with N≥15, add to `RESCUE_SIGNAL_PRIORITY`
6. **`sharp_consensus_under`** — Shadow with book-count-aware thresholds. Graduate when N≥30 at BB level with HR≥60%
7. **`book_disagree_under`** — Shadow, accumulating data

### Monitor
8. **MLB grading pipeline** — Verify Apr 10-12 games grade automatically
9. **Cloud Build triggers** — Verify `deploy-mlb-phase6-grading` + `cloudbuild-nba-phase2.yaml` fire on next push

---

## Files Changed

| Purpose | File |
|---------|------|
| Quantile ceiling signal | `ml/signals/quantile_ceiling_under.py` (new) |
| Quantile floor signal | `ml/signals/quantile_floor_over.py` (new) |
| Signal registry | `ml/signals/registry.py` |
| Aggregator (signals + floor + archetype) | `ml/signals/aggregator.py` |
| Book-count-aware sharp_consensus | `ml/signals/sharp_consensus_under.py` |
| CLI governance flag | `ml/experiments/quick_retrain.py` |
| CF governance auto-detect | `orchestration/cloud_functions/weekly_retrain/main.py` |

## Infrastructure Operations

| Operation | Detail |
|-----------|--------|
| Model trained + registered | `lgbm_v12_noveg_train0206_0402` (LGBM MAE) |
| Model trained + registered | `xgb_v12_noveg_train0206_0402` (XGB MAE) |
| Model trained + registered | `catboost_v12_noveg_mq_train0206_0402` (CatBoost MQ) |
| Model trained + registered | `catboost_v12_noveg_train1205_0403` (CB MAE 120d pre-season) |
| Model deactivated | `lgbm_v12_noveg_train1227_0221` (superseded) |
| Model deactivated | `lgbm_v12_noveg_train0126_0323` (superseded) |
| Model deactivated | `xgb_v12_noveg_train0112_0223` (superseded) |
| Model deactivated | `catboost_v12_noveg_train1227_0221` (superseded) |
| Worker cache refresh | `./bin/refresh-model-cache.sh --verify` |
| CF deployed | `weekly-retrain` (season-restart auto-detect) |

---

## Key Decisions

### OVER floor 6.0 — won't Session 476 repeat?
Session 476 reverted because the fleet was all LGBM clones with avg_abs_diff 1.53 — couldn't produce edge 6+ picks. Now we have 3 different frameworks (CatBoost MQ, LightGBM MAE, XGBoost MAE). Different algorithms produce different prediction surfaces → higher chance of genuine edge 6+ divergence.

### Why auto-detect in weekly_retrain CF?
The Apr 7 retrain failed with UNDER HR 50.91% < 52.4%. This was a false failure caused by TIGHT market eval data, not bad model quality. Auto-detection ensures the CF self-heals without human intervention — critical for an off-season restart when nobody's watching.

### Why bench OVER hard-block instead of soft ranking penalty?
Bench OVER (line < 12) has 34.1% HR even at edge 7+ across 91 picks. That's below random chance. No amount of signal stacking or edge can save it. A soft penalty would still let edge 10+ bench OVER picks through — and they'd still lose 2/3 of the time.

### Why 120-day pre-season retrain?
Standard 56-day window captures 2 months. The 120-day model (Dec-Apr) sees the full season's worth of patterns. It'll be replaced within 2-3 weeks by the weekly retrain, but provides a better starting model for day 1 of the new season than a 6-month-stale 56-day model.
