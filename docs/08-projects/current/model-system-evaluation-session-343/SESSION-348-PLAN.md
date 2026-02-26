# Session 348: Decline Diagnosis & Recovery Plan

**Date:** 2026-02-26
**Goal:** Diagnose February performance decline, retrain stale models, fix infrastructure bugs, restore January-level profitability.

---

## Part 1: Performance Decline Diagnosis

### The Numbers

| Period | Picks | W-L | HR | Avg Edge |
|--------|-------|-----|----|----------|
| **January** | 67 | 49-18 | **73.1%** | 7.2 |
| Feb 1-15 | 26 | 15-11 | 57.7% | — |
| Feb 16-26 | 12 | 8-4 | 66.7% | — |
| **February total** | 38 | 23-15 | **60.5%** | 5.4 |

Weekly granularity:
| Week | Picks | W-L | HR |
|------|-------|-----|----|
| Jan 5 (wk 1) | 11 | 9-2 | 81.8% |
| Jan 11 (wk 2) | 26 | 14-12 | 53.8% |
| Jan 18 (wk 3) | 17 | 15-2 | 88.2% |
| Jan 25 (wk 4) | 13 | 11-2 | 84.6% |
| Feb 1 (wk 5) | 16 | 11-5 | 68.8% |
| **Feb 8 (wk 6)** | **10** | **4-6** | **40.0%** |
| Feb 19 (wk 7) | 6 | 3-3 | 50.0% |
| Feb 22 (wk 8) | 6 | 5-1 | 83.3% |

Week 6 (Feb 8) was the trough. Recent weeks are recovering.

### Root Cause Breakdown

#### 1. OVER Predictions Collapsed (Biggest Single Factor)

| Period | Direction | Picks | W-L | HR |
|--------|-----------|-------|-----|----|
| January | OVER | 40 | 32-8 | **80.0%** |
| January | UNDER | 27 | 17-10 | 63.0% |
| February | OVER | 24 | 14-10 | **58.3%** |
| February | UNDER | 14 | 9-5 | 64.3% |

OVER HR dropped 22pp (80% → 58%). UNDER held steady (63% → 64%). The entire decline is in OVER predictions.

#### 2. Starters OVER is the Specific Culprit

| Period | Tier | Direction | Picks | W-L | HR |
|--------|------|-----------|-------|-----|----|
| January | Starters | OVER | 10 | 9-1 | **90.0%** |
| February | Starters | OVER | 9 | 3-6 | **33.3%** |
| January | Role Players | OVER | 30 | 23-7 | 76.7% |
| February | Role Players | OVER | 12 | 9-3 | 75.0% |

Starters OVER collapsed 57pp. Role Players OVER held at ~76%. Stars and Role Players UNDER held.

#### 3. Full-Vegas Architecture Is Failing

| Period | Architecture | Direction | Picks | W-L | HR |
|--------|-------------|-----------|-------|-----|----|
| February | full_vegas | OVER | 22 | 12-10 | 54.5% |
| February | full_vegas | UNDER | 11 | 6-5 | 54.5% |
| February | noveg/low_vegas | ALL | 6 | 6-0 | **100%** |
| January | full_vegas | OVER | 40 | 32-8 | 80.0% |
| January | full_vegas | UNDER | 27 | 17-10 | 63.0% |

Full-vegas went from 73.1% (Jan) to 54.5% (Feb). Noveg/low_vegas are 6/6 in Feb (tiny N but directionally strong).

#### 4. Edge Quality Weakened

| Period | Avg Edge | Edge 7+ Picks | Edge 5-7 Picks |
|--------|----------|---------------|----------------|
| January | 7.2 | 25 | 42 |
| February | 5.4 | 7 | 31 |

Models are generating weaker-conviction predictions. This is a staleness indicator — confidence decays as training data becomes less representative.

#### 5. V12 Champion Is 26 Days Stale

| Staleness | HR edge 3+ (N) | HR edge 5+ (N) |
|-----------|----------------|-----------------|
| Days 1-14 | 56.0% (50) | — |
| Days 15-21 | 56.0% (25) | — |
| **Days 22+ (NOW)** | **47.2% (53)** | **Below breakeven** |

The V12 champion (trained to Jan 31) has been past its confirmed ~21-day shelf life since Feb 21. V9 champion (trained to Feb 5) is at day 21.

#### 6. Model Attribution Shows V12 Dragging Portfolio

| System ID | Period | Picks | W-L | HR | Avg Edge |
|-----------|--------|-------|-----|----|----------|
| catboost_v12_train1102_1225 | Jan | 23 | 18-5 | 78.3% | 7.0 |
| catboost_v9 | Jan | 40 | 27-13 | 67.5% | 7.0 |
| catboost_v12_train1102_0125 | Jan | 4 | 4-0 | 100% | 10.3 |
| catboost_v9 | Feb | 24 | 14-10 | 58.3% | 6.9 |
| **catboost_v12** | **Feb** | **6** | **2-4** | **33.3%** | **1.9** |

V12 in February: 33.3% HR with avg edge of just 1.9 — generating low-conviction losing picks.

### Summary

The February decline has 3 interacting causes:
1. **Model staleness** — both champions are past their shelf life
2. **OVER signal degradation** — specifically Starters OVER, from models that anchor to Vegas
3. **Full-vegas architecture weakness** — confirmed by every analysis (feature importance, decay timeline, live performance)

---

## Part 2: Recovery Plan

### Immediate Actions (Session 348)

#### Action 1: Fix pubsub_v1 Import Error
- **File:** `orchestration/cloud_functions/post_grading_export/requirements.txt`
- **Issue:** Missing `google-cloud-pubsub` dependency causes steps 6-8 to crash
- **Root cause:** `shared/utils/__init__.py` eagerly imports `PubSubClient` which requires pubsub_v1
- **Fix:** Add `google-cloud-pubsub>=2.20.0` to requirements.txt
- **Impact:** Restores post-grading re-export of tonight/all-players.json, best-bets/all.json, record.json

#### Action 2: Retrain v12_noveg_q55_tw (Best Offline Performer) — COMPLETED

- **Training window:** Jan 5 - Feb 15 (42 days)
- **Config:** Q55 quantile, no vegas features, category weights (recent_perf=2x, derived=1.5x, matchup=0.5x)
- **Model file:** `models/catboost_v9_50f_noveg_wt_train20260105-20260215_20260226_110254.cbm`

**Results (eval Feb 16-26):**

| Metric | Value |
|--------|-------|
| HR edge 3+ | **68.0%** (17/25) |
| HR edge 5+ | **77.8%** (7/9) |
| OVER | **87.5%** (7/8) |
| UNDER | **58.8%** (10/17) |
| Vegas bias | **+0.11** (near-perfect) |
| MAE | 5.36 (expected for quantile) |
| Edge 7+ | 100% (3/3) |
| Role Players OVER | 85.7% (6/7) |
| Stars UNDER | 50.0% (3/6) |

**Gates:** PASSED HR, vegas bias, tier bias, direction balance. FAILED MAE (structural for quantile) and sample size (N=25, structural for 11-day eval).

**Key insight:** Best directional balance seen — +0.11 bias means nearly zero UNDER lean. This is the calibration fix we've been looking for.

#### Action 3: Retrain v9_low_vegas (Most Decay-Resistant) — COMPLETED

- **Training window:** Jan 5 - Feb 15 (42 days)
- **Config:** V9 33f, MAE loss, vegas category-weight=0.25
- **Model file:** `models/catboost_v9_33f_wt_train20260105-20260215_20260226_110224.cbm`

**Results (eval Feb 16-26):**

| Metric | Value |
|--------|-------|
| HR edge 3+ | 56.8% (25/44) |
| HR edge 5+ | 63.6% (7/11) |
| OVER | **72.7%** (8/11) |
| UNDER | 51.5% (17/33) — below breakeven |
| Vegas bias | -0.44 |
| Stars UNDER | 42.9% (6/14) — confirms universal Stars UNDER problem |
| Starters | 63.6% (7/11) |
| Role Players | 63.2% (12/19) |

**Gates:** ALL FAILED. UNDER direction at 51.5% is the core problem. Stars UNDER drags it below breakeven.

**Decision:** v12_noveg_q55_tw is clearly the better model. v9_low_vegas has OVER signal but UNDER is broken.

### Short-Term Actions (Next 3-5 Days)

#### Action 4: Grade Tonight's 5 Best Bets (Feb 27)
- All 5 picks are UNDER from noveg/low_vegas models (the architecture that's working)
- Kawhi UNDER 29.5 (edge 7.7), Embiid UNDER 27.5 (6.7), Luka UNDER 30.5 (5.9), Ant UNDER 28.5 (5.5), Green UNDER 20.5 (5.1)

#### Action 5: Verify Shadow Model Coverage (Feb 27)
- Feb 26 shadows had 6/117 predictions (deploy timing — expected)
- Feb 27 should show ~117 per shadow model
- If still low, investigate `_prepare_v12_feature_vector()` failures

#### Action 6: Grade Shadow Models (Mar 1-3)
- 4 shadows running: q55, q55_tw, q57, v9_low_vegas_fresh
- Need 3-5 days of predictions before meaningful evaluation
- This is THE critical decision point for architecture shift

### Medium-Term Actions (Week of Mar 2-6)

#### Action 7: Evaluate Starters OVER Segment
- 33.3% HR in Feb vs 90.0% in Jan
- Options:
  - a) Trust retraining to fix (staleness is likely cause)
  - b) Add Starters OVER caution filter (require edge 7+)
  - c) Add full-vegas OVER blocking for starters
- Decision after shadow grading data

#### Action 8: Evaluate Dynamic Edge Floor
- When models are >14 days stale, raise edge floor from 5+ to 6+
- February picks with edge 7+: likely higher HR than edge 5-7
- Decay detection CF already tracks staleness — can integrate

#### Action 9: Architecture Decision (noveg as default)
- Every analysis points to noveg/low-vegas > full-vegas
- Wait for shadow grading to confirm live performance
- If confirmed: promote noveg_q55_tw as co-champion alongside v9_low_vegas

#### Action 10: Retrain Cadence Update
- Current: 7-day target (not being met)
- Recommended: 14-day hard cadence
- Evidence: Models show 14-21 day shelf life. 14-day retrain gives buffer.
- Enforce via retrain-reminder CF (already exists, just tighten threshold)

### Investigation Backlog

| # | Investigation | Status | Priority |
|---|---------------|--------|----------|
| 1 | Best bets source attribution | DONE (Session 345) | — |
| 2 | Model decay timeline | DONE (Session 346) | — |
| 3 | Direction bias deep dive | DONE (Session 347) | — |
| 4+8 | Feature importance analysis | DONE (Session 344) | — |
| 5 | Architecture decision (noveg default) | PENDING — awaiting shadow grading | HIGH |
| 6 | Quantile strategy (Q55/Q57 vs MAE) | PENDING — awaiting shadow grading | HIGH |
| 7 | New feature candidates | NOT STARTED | LOW |
| — | Stars UNDER filter | PENDING — need N >= 15 live | MEDIUM |
| — | B2B + UNDER + V12 filter | PENDING — need more noveg data | LOW |
| — | V12_mae UNDER blocking | PENDING — need shadow replacement | MEDIUM |

---

## Part 3: Success Metrics

| Metric | Current (Feb) | Target (2 weeks) | Target (4 weeks) |
|--------|---------------|-------------------|-------------------|
| Best bets HR | 60.5% | 65%+ | 70%+ |
| Best bets weekly volume | 3-5 | 5-7 | 7-10 |
| OVER HR | 58.3% | 65%+ | 70%+ |
| Models HEALTHY | 0 | 2+ | 4+ |
| Avg edge on best bets | 5.4 | 6.5+ | 7.0+ |
| Days since last retrain | 21-26 | <14 | <14 |

---

## Key Context

- **Health gate removed Session 347** — best bets now flow even when raw model HR is low. Filter pipeline is the real quality control.
- **AWAY noveg filter deployed Session 347** — blocks v12_noveg AWAY predictions (43-44% HR vs 57-59% HOME).
- **4 shadow models active** since Feb 26 — q55, q55_tw, q57, v9_low_vegas_fresh. All at 6/117 on Feb 26 (deploy timing), expected full coverage Feb 27+.
- **All production models BLOCKED/DEGRADING** — but edge 5+ filter chain keeps best bets profitable (60.5% overall, 66.7% recent).
