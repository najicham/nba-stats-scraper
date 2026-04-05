# 2026 Off-Season Plan: NBA + MLB Next Season Strategy

**Created:** 2026-04-05 (Session 514)
**Status:** V2 — Revised after 3-agent review (strategy critic, technical feasibility, data/evidence audit)
**Scope:** NBA 2026-27 architecture, MLB 2026 season execution, infrastructure cost reduction

---

## Table of Contents

1. [NBA Season Retrospective](#1-nba-2025-26-season-retrospective)
2. [What Worked — Validated Wins](#2-what-worked--validated-wins)
3. [What Failed — Dead Ends & Lessons](#3-what-failed--dead-ends--lessons)
4. [NBA 2026-27 Strategy](#4-nba-2026-27-strategy)
5. [MLB 2026 Season Execution Plan](#5-mlb-2026-season-execution-plan)
6. [Infrastructure & Cost Optimization](#6-infrastructure--cost-optimization)
7. [Unexplored Opportunities](#7-unexplored-opportunities)
8. [Timeline & Priorities](#8-timeline--priorities)
9. [Review Findings & Corrections](#9-review-findings--corrections)

---

## 1. NBA 2025-26 Season Retrospective

### Final Record: 108-76 (58.7%)

*Note: Pre-voiding record. 14 DNP picks were voided in Session 513; post-voiding record requires BQ verification.*

| Month | Record | HR | Notes |
|-------|--------|-----|-------|
| January | ~19-7 | ~73.1% | Peak performance, fresh models, high edge |
| February | ~27-21 | ~56.3% | Toxicity window (ASB + trade deadline) |
| March | 19-27 | 41.3% | Late-season collapse, edge compression |
| April 1-5 | 0-0 | N/A | Pick drought (Day 6), models exhausted |

*Monthly Jan/Feb breakdowns are approximate — only March is explicitly sourced (memory). Full monthly breakdown requires BQ verification.*

### Edge 5+ Performance (The Money Zone)
- **Season: 82-44 (65.1%)** — consistently profitable across all months
- **Top combos:** edge5+combo3way 83.3%, edge7+ 78.8%, edge5+rest_adv 74.0%
- **Edge 3-5 OVER: 43.5% HR** (net-negative, live BB data)
- **Edge 3-5 UNDER: 36.4% HR** (live BB data). *Note: 5-season simulation shows 56-58% for UNDER across all edge levels, but live BB performance diverges significantly. The simulation N is much larger; the live BB N is small and concentrated in March.*

### The Structural Problem

The system predicts **points scored** via regression, then compares to the Vegas line to derive edge. When late-season variance compresses (load management, tanking, tighter rotations), the predicted-vs-line gap collapses:

- Models trained through March absorb 41% low-variance data
- `line_vs_season_avg` (feature 53) converges to zero
- Average edge drops from high (Jan) to 1.3-1.5 (Apr)
- Below the 3.0 edge floor = 0 picks

### Honest Assessment: Is 58.7% the Ceiling?

Over 5 seasons of walk-forward simulation, the best sustained strategy (edge 6-8 + fixed filters) delivers **61.4% HR**. This season finished at **58.7%**. The numbers are close. The system may already be near its theoretical ceiling for points-scored props with this architecture.

**If 55-60% is the structural ceiling**, the highest-ROI paths are:
1. Reducing costs to maximize net profit
2. Expanding to other markets/sports where inefficiencies are larger
3. Optimizing bet sizing (Kelly criterion on existing edge estimates)
4. Not betting during structurally unprofitable months

The plan must account for this possibility rather than assuming architecture changes will restore January-level performance.

---

## 2. What Worked — Validated Wins

### The Signal/Filter System IS the Product

The raw model is 53.4% HR at edge 3+. The signal/filter system adds **+13.7pp** to reach 65.9%. This is where virtually all the alpha lives.

| Component | Impact | Details |
|-----------|--------|---------|
| **Filter stack** | +13.7pp (65.9% vs 52.2%) | 23 active + 13 observation negative filters |
| **OVER/UNDER asymmetry** | Eliminated systematic OVER losses | OVER floor 5.0, UNDER ranked by signal quality |
| **Signal rescue** | Extended pick volume during compression | Bypasses edge floor for validated signals |
| **Real signal count** | Prevented bad-pick inflation | Base/shadow signals excluded from SC gates |
| **Health-aware weighting** | Auto-dampens cold signals | COLD 0.5x, HOT 1.2x multipliers |

**Top signals by HR** (from CLAUDE.md — sample sizes not individually verified, treat as directional):

| Signal | HR | Caveat |
|--------|-----|--------|
| `combo_3way` | 95.5% | N unknown — likely small, combo signals fire rarely |
| `line_rising_over` | 96.6% | N~30, fragile (one loss drops to 93%) |
| `book_disagreement` | 93.0% | N unknown. Standalone 5-season = 52.8% — the 93% is likely a filtered subset |
| `sharp_line_drop_under` | 87.5% | N unknown — likely small |
| `fast_pace_over` | 81.5% | N unknown |

### Per-Model Pipelines

- Each enabled model runs an independent BB pipeline
- Pool-and-rank merge by composite score
- Framework diversity (CatBoost + LightGBM) >> seed diversity (same framework)
- Full provenance in `model_bb_candidates` BQ table (45 columns)

### Model Configuration

- **V12_NOVEG is king** — 60+ experiments across features/loss functions/windows, V12_noveg always wins
- **56-day window + 7-day retrain** — walk-forward validated across 2 seasons
- **Vegas weight 0.15-0.25x** — cross-season validated optimal
- **Zero tolerance for defaults** — predictions blocked for ANY player with default features

### Discovery Infrastructure

- **5-season simulator** (`bb_enriched_simulator.py`) — 79K predictions, walk-forward. *Technical note: file location needs verification; may need to build on `season_replay_full.py` instead.*
- **Feature scanner** — BH FDR correction, cross-season validation
- **Combo tester** — 2-way/3-way signal interactions
- **Archetype analyzer** — player clustering by usage/line/variance

### DNP Voiding (Session 513)

- `is_voided` + `void_reason` columns on `signal_best_bets_picks`
- Third pass in post-grading detects DNP via `player_game_summary.is_dnp`
- Frontend shows `result=VOID` instead of counting DNP as losses

---

## 3. What Failed — Dead Ends & Lessons

### Model Experiments (All Failed)

60+ documented experiments in `docs/06-reference/model-dead-ends.md`:

| Experiment | Result | Why |
|-----------|--------|-----|
| Quantile regression (Q43-Q60) | 20-53% HR across 6 variants | Didn't capture edge structure. Q43+Vegas=20% HR, Noveg Q43=14.8% live (0/54 UNDER), LightGBM Q55=non-deterministic |
| Edge classifier | AUC < 0.50 | Direction not predictive at training time |
| Binary classifier (no-vegas) | AUC 0.507 = random | Same features can't separate OVER/UNDER at better than chance |
| Huber loss | 47.4% HR | Interaction effects degraded signal |
| Recency weighting | 33.3% HR | Over-penalized off-season data |
| Direction-specific models | AUC 0.507 | Circular dependency |
| Post-ASB-only training | N=637 | Insufficient data |
| Anchor-line training | 33.3% UNDER HR | Collapsed feature importance |
| Tier-specific models | 1/6 gates | Insufficient per-tier samples |
| Window-based ensemble | All 64-66% | No diversity |

### Features That Hurt

| Feature | Impact | Why |
|---------|--------|-----|
| Pace + efficiency (5 features) | +0.0pp | Redundant with existing features |
| Usage spike score | -0.3pp | Model handles drift internally |
| Percentile features | -2.76pp | Increased variance |
| Deviation features (V17) | 56.7% vs 73.7% V12 | Missing context |
| Expected scoring possessions | 62.8% vs 68.6% | Amplifies drift |

**Lesson:** V12_NOVEG's 37 base features are the sweet spot. Adding features consistently hurts across 5 seasons.

### Signals That Failed

- `extended_rest_under`: 28.6% season HR — demoted to shadow
- `sharp_book_lean_over`: 41.7% 5-season HR — harmful
- `starter_away_overtrend_under`: 48.2% 5-season HR — harmful
- `blowout_recovery`: collapses during toxic window (75% → 33.3%)
- `projection_consensus_over`: 12.5% BB HR (1/8) — catastrophic
- `mean_reversion_under`: declined from 75.7% → 65.2% → 53.0% across seasons, below baseline

### Filters That Blocked Winners (Removed)

- `ft_variance_under`: 56.0% CF HR (N=1,001) — blocking winners
- `b2b_under`: 54.0% CF HR (N=2,060) — blocking winners
- `familiar_matchup`: 54.4% CF HR (N=1,151) — blocking winners

### Key Lessons

1. **Governance HR is inflated** — backtest cherry-picks 11% of predictions. Live HR 20-30pp lower than backtest. Use live shadow data for promotion decisions.
2. **Small-N filter decisions are dangerous** — Session 512 tightened `under_low_rsc` based on N=7 from one day. Always require N≥30.
3. **Player over/under rates are NOT stable** across seasons (r=0.143). Player scoring variance IS stable (r=0.642).
4. **March is structurally different** — load management + tanking + blowout surge (38.5%) invalidate Jan-Feb patterns.
5. **Observation-mode filter debt accumulates silently** — code writes, data computes, nothing blocks. Must audit regularly.
6. **Simulation ≠ live performance** — 5-season simulation says UNDER is 56-58% at edge 3-5, live BB says 36.4%. Always distinguish data sources.

---

## 4. NBA 2026-27 Strategy

### 4.1 Strategic Options (Ranked by Expected Value)

The three reviewers converged on this priority ordering:

#### Option 1: Seasonal Dormancy (Highest EV, Lowest Effort)

**Don't bet during structurally unprofitable months.** March was 41.3% HR, April produced 0 picks. A simple regime-based shut-off when 7-day avg edge drops below 3.0 preserves the 65%+ edge-5+ record from November-February.

**Analysis needed:** Model the ROI of a 4-5 month season (Nov-Feb/early Mar) vs 6 months. If March drags the season ROI below what Nov-Feb alone produces, dormancy is the optimal strategy.

**Implementation:**
- Auto-pause when compression ratio RED for 14+ days
- Publish "System paused for late season" to frontend
- Continue pipeline in shadow mode for data collection
- ~1 day to implement

#### Option 2: Signal System Investment (High EV, Medium Effort)

**The signal/filter system adds +13.7pp. Improving it is higher-ROI than fixing the model.**

**Signal graduation via historical replay:** `book_disagree_over` (79.6% 5-season HR) and `sharp_consensus_under` (69.3%) are blocked at N=1 live BB pick. Instead of waiting for live picks that will never accumulate at scale, run these signals through the full simulator with BB-level filtering to get robust N. Use N≥30 from simulator at BB level + N≥10 live picks for sanity check.

**New signals to build:**
- **Market-consensus UNDER:** `line_dropped ≥ 1.5 AND multi_book_std < 0.5` (sharp money + book agreement)
- **Stale line fade:** bet WITH sharp consensus against laggard books
- **Playoff rotation signal:** track minutes distribution shift when rotations tighten

**System improvements:**
- Season-phase regime detection (not just TIGHT/NORMAL/LOOSE market)
- Playoff mode with different edge floors, signal weights, filter stack
- Accelerated signal graduation using replay data

#### Option 3: Auto Training Anchor (Medium EV, Low Effort)

Regardless of other choices, implement `cap_to_pre_late_season()` in `weekly_retrain/main.py`:

```python
def cap_to_pre_late_season(train_end: date) -> date:
    """Prevent late-season data from contaminating training.
    Cap should ideally be ASB_date + buffer, not hardcoded Feb 28,
    since ASB moves yearly. Compose with existing TIGHT market cap.
    """
    # TODO: Make ASB-date-aware rather than hardcoded
    season_cap = date(train_end.year, 2, 28)
    if train_end > season_cap:
        return season_cap
    return train_end
```

**Technical notes (from feasibility review):**
- Must compose with existing `cap_to_last_loose_market_date()`: `train_end = min(cap_late, cap_tight)`
- Feb 28 is imperfect — ASB moves yearly (mid-Feb to early-Mar). Hardcoded date may include post-ASB degraded data in some seasons or exclude good pre-ASB data in others.
- November training is correctly handled (Nov < Feb 28, no cap applied)

**Effort:** 0.5 day

#### Option 4: Season-Phase Walk-Forward Diagnostic (Medium EV, Low Effort)

**Run before committing to any architecture change.** Answers: "Is late-season degradation consistent across all 5 seasons, or was 2025-26 an outlier?"

1. Slice 5-season data by phase: Early (Oct-Nov), Mid (Dec-Jan), Late (Feb-Mar), Endgame (Apr)
2. Train on each phase, evaluate on same phase next season
3. Quantify exactly when/how the model breaks
4. Test: Does a model trained only on Early+Mid data perform better in Late?

**If Late/Endgame is consistently 5-10pp lower:** Architecture needs changing. Proceed to quantile experiment.
**If inconsistent:** Problem is 2025-26-specific. Focus on signal system improvements and dormancy instead.

**Technical notes:** Build on `season_replay_full.py` and `discovery/data_loader.py`. Referenced `bb_enriched_simulator.py` needs location verification. Effort: 2-3 days.

#### Option 5: Quantile Regression IQR Experiment (Unvalidated, High Effort)

**CAUTION: Quantile approaches have failed 6 times on this data.** The IQR framing (train Q25/Q50/Q75, edge = "entire IQR on one side of line") is conceptually different from prior single-quantile attempts, but is completely unvalidated.

**Only pursue if the season-phase walk-forward confirms consistent late-season degradation AND the following offline experiment shows promise:**

1. Train Q25/Q50/Q75 models using `quick_retrain.py --quantile-alpha 0.25/0.50/0.75` (CatBoost supports natively)
2. Compute IQR offline — check whether "entire IQR on one side of line" identifies profitable picks at N > 50
3. **Hard kill criterion:** If 5-season simulator shows < 55% HR at BB level after 1 week of iteration, abandon.

**If IQR works, full pipeline integration requires:**
- Training pipeline: 3 models per family (1 day)
- Prediction worker: new `QuantileEnsemble` wrapper returning q25/q50/q75 (2-3 days)
- Edge computation: new IQR-based edge flowing through BQ schema (1 day)
- Aggregator integration: map IQR edge to compatible scalar (1-2 days)
- BQ schema: add q25/q75/iqr_width columns (0.5 day)

**Realistic total effort: 5-7 days** (not 2 as initially estimated)

#### Removed: Classification Model

**Infeasible.** AUC 0.507 (random) on the same 37 features. The features predict point totals, not direction-relative-to-line. Would require fundamentally different features — which 60+ experiments show don't exist in this data. No path forward without external data sources not currently in the system.

### 4.2 Feature Engineering (Extremely Cautious)

60+ experiments show features consistently hurt V12_NOVEG. Only pursue features that are **structurally impossible** for the current model to learn from existing data:

| Feature | Rationale | Risk |
|---------|-----------|------|
| `games_back` (playoff seeding) | Captures load management motivation directly | Only useful last 30 days |
| `clinched_playoff` / `eliminated` | Binary flag for tanking/coasting | Same limitation |
| RotoWire `play_probability` | Pre-game lineup confirmation (data already scraped) | Integration effort |

**Do NOT add:** pace features, efficiency features, deviation features, percentile features, usage spike score. All confirmed dead ends.

### 4.3 Playoff-Specific Strategy

NBA playoffs are structurally different:
- No load management (every game matters)
- Tighter 8-9 man rotations (predictable minutes)
- Same opponent for 4-7 games (matchup features more valuable)

**Plan:** Run current system in shadow during 2026 playoffs. Collect data. Build playoff-specific model for 2026-27 using walk-forward on historical playoff data.

---

## 5. MLB 2026 Season Execution Plan

### Current State

- **Live since March 27, 2026** — full pipeline operational
- **Model:** CatBoost V2, 36 features, OVER-only
- **4-season replay (backtest):** 63.4% HR, +470.7u, 12.8% ROI
- **Live graded picks: ~0** (system is 8 days old, grading pipeline just starting)
- **20 active + 30 shadow signals, 6 negative filters**

*Important: The 63.4% HR and 12.8% ROI are from historical backtest, NOT live performance. Sports betting backtests routinely overstate live performance by 5-15pp. Set expectations at 55-58% live HR for the first month.*

### 5.1 Immediate (This Week)

| Task | Effort | Impact |
|------|--------|--------|
| Auto-deploy trigger for MLB worker | 1 day | Prevents manual deploy drift |
| Automated daily performance SQL → Slack | 1 day | Visibility into live HR |
| Verify April picks are generating correctly | 30 min | Confirm launch success |

### 5.2 April Monitoring Phase

- Track daily HR, ROI, pick volume, edge distribution
- Compare live performance to backtest expectations (expect 5-15pp below backtest)
- Watch for early hooks (short rest = 43.4% early hook rate)
- Monitor overconfidence (prob 0.80+ = 48.2% HR — losing)
- Track signal health for all 20 active signals

### 5.3 May 1 Decision Points

| Decision | Criteria | Action |
|----------|----------|--------|
| Enable UNDER | OVER HR ≥ 55% at N ≥ 50 live | Set `MLB_UNDER_ENABLED=true`, edge floor 1.5K |
| Signal promotions | Shadow signal HR ≥ 60% at N ≥ 30 live | Move from SHADOW to active |
| Blacklist review | Per-pitcher HR at N ≥ 15 | Remove profitable pitchers, add losers |
| Model retrain | 14-day cadence triggered | First retrain with 2026 live data |

### 5.4 June-July (Pre/Post All-Star Break)

- Second retrain with 2-3 months of 2026 data
- Season-phase analysis: are April-May patterns holding?
- ASB impact analysis (roster changes, fatigue)
- Multi-model evaluation: LightGBM V1 / XGBoost V1 vs CatBoost V2

### 5.5 August-September (Peak Performance Period)

Historical backtest shows Aug-Sep as strongest months (54-69% HR). Strategy:
- Maximize volume (relax edge floors slightly if live HR supports)
- More aggressive signal rescue
- Post-trade-deadline roster stability = better features

### 5.6 Known Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Early hooks | -1.06K surprise | `short_rest_under` signal (active) |
| Overconfidence | 48.2% HR at prob 0.80+ | `overconfidence_cap` filter (active, edge > 2.0K blocked) |
| Statcast gaps | 28.8% of pitchers | CatBoost NaN-tolerant, not blocking |
| Backtest ≠ live | Expect 5-15pp degradation | Conservative edge floors, 55% not 63% as success bar |
| Bullpen games | Unpredictable | `bullpen_game_skip` filter (active, IP avg < 4.0) |
| MLB attention dilution | Debugging new system steals NBA off-season time | Dedicated MLB monitoring before any NBA architecture work |

### 5.7 MLB Maturity Gaps vs NBA

| Gap | Priority | Effort | Target |
|-----|----------|--------|--------|
| Auto-deploy trigger | P0 | 1 day | This week |
| Daily perf tracking | P0 | 1 day | This week |
| Auto-demotion system | P1 | 3 days | May |
| UNDER strategy | P1 | 2 days | May 1 checkpoint |
| Source freshness alerts | P2 | 2 days | June |
| Season-phase thresholds | P2 | 5 days | July |
| Injury/IL automation | P2 | 3 days | June |

---

## 6. Infrastructure & Cost Optimization

### Current: ~$994/month (was $150 baseline)

| Category | Current Cost | Target | Savings |
|----------|-------------|--------|---------|
| Cloud Run (NBA) | $364 | $240 | $124 |
| BigQuery | $179 | $80 | $99 |
| Cloud Logging | $68 | $25 | $43 |
| Cloud Run Functions | $59 | $45 | $14 |
| Artifact Registry | $24 | $10 | $14 |
| Cloud Scheduler | $16 | $8 | $8 |
| Cloud Build | $22 | $22 | $0 |
| Cloud Storage | $26 | $26 | $0 |
| Other | $20 | $20 | $0 |
| infinite-case | $115 | $58 | $57 |
| **Total** | **$994** | **$534** | **$460** |

*Note: Session 511 already reduced infinite-case to 4Gi/2CPU (~$57/mo savings). Plan updated to reflect.*

### P0: Zero Risk, Immediate (~$180/month savings)

1. **Fix publishing exporter BQ partition filters** — 4 exporters scan 10GB+ daily without filters. Add `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)`. Saves ~$85/mo. High-confidence, standard pattern.
2. **Tiered canary monitoring** — Keep 15-min for 11 critical checks, move rest to 60-min. Saves ~$35/mo.
3. **infinite-case savings** — Already deployed Session 511. Saves ~$57/mo.

### P1: Low Risk, This Month (~$115/month savings)

4. **Cloud Logging exclusion filters** — Exclude health checks, heartbeats. Target 50GB (free tier). Saves ~$43/mo.
5. **Phase 4 CPU 4→2** — Already min=0, runs 1x/day. Low risk. Saves ~$30/mo.
6. **Delete legacy services** — `nba-phase1-scrapers`, 7+ BDL scheduler jobs. Saves ~$17/mo.
7. **Artifact Registry lifecycle** — Prune to 3 versions per image. Saves ~$14/mo.
8. **Delete stale scheduler jobs** — 167 jobs, ~10+ stale. Saves ~$5/mo.

### P2: Needs Measurement (~$100/month potential)

9. **Phase 3 CPU 4→2** — *Questionable.* Phase 3 uses request-based billing (`--cpu-throttling`). Analytics processing is typically I/O-bound (BQ waits), so CPU reduction may not save money — just increases latency. Need to measure whether work is CPU-bound before changing. Potential ~$62/mo.
10. **Phase 3 deduplication** — Fires 10-13x/day (multiple Pub/Sub + scheduler sources). Add idempotency check. *Do during off-season with shadow testing, not during MLB active season.* Saves CPU + BQ.
11. **Terraform remote state migration** — Prevents divergence, enables multi-operator safety. No direct cost savings but prevents future drift.

---

## 7. Unexplored Opportunities

*Identified by strategy review — not yet validated.*

### 7.1 Alternative Betting Markets

Points-scored is the most liquid and most efficiently priced market. Other markets may have larger structural edges:

| Market | Potential | Why |
|--------|-----------|-----|
| **Player rebounds** | Medium | Less affected by load management, wider lines at some books |
| **Player assists** | Medium | Different variance dynamics, less efficient pricing |
| **Player 3-pointers** | Low-Medium | High variance, harder to predict |
| **Combined props (PRA)** | Low | More liquid but also more efficiently priced |

**Analysis needed:** Check feature store coverage for these markets, line availability from Odds API, edge distribution. Low cost, high information value. The 5-season simulator infrastructure could be adapted.

### 7.2 Bet Sizing (Kelly Criterion)

The system treats all bets as flat-unit. But it already has edge and confidence estimates. A fractional-Kelly sizing strategy (e.g., half-Kelly on edge estimates) could increase ROI without changing a single prediction.

**Analysis needed:** Backtest Kelly sizing on historical BB picks. Compare ROI of flat-unit vs edge-weighted sizing.

### 7.3 Line Shopping / Execution Optimization

The system predicts against a single line source. Multi-book data (BettingPros, Odds API) is already scraped. A "best available line" matcher at export time could add 1-2pp of pure execution alpha.

**Analysis needed:** How often do books disagree on lines? What is the edge pickup from always taking the best available line?

### 7.4 Off-Season Data Quality Fixes

| Issue | Impact | Effort |
|-------|--------|--------|
| `win_flag` permanently FALSE | Can't use win context in signals | 1 day to fix with `plus_minus > 0` |
| `is_dnp` NULL for older records | Requires defensive filtering everywhere | 1 day to backfill |
| 1-hour injury blind spot pre-game | 2-3 picks/season affected | RotoWire `play_probability` at 4:30 PM re-export |

### 7.5 Cross-Sport Shared Infrastructure

*Deferred from V1 plan based on reviewer feedback. Cross-sport unification touches the most critical code paths and took 500+ sessions to stabilize for NBA alone. Safer to keep systems separate and share only infrastructure (BQ writers, monitoring, alerting).*

| Component | Recommendation |
|-----------|---------------|
| Signal discovery framework | Keep separate per sport. Patterns are shared, code is not. |
| Filter auto-demotion | Build for MLB from scratch, using NBA learnings |
| Model governance gates | Already similar but different thresholds. Keep separate. |
| Monitoring dashboard | Unify — low risk, high visibility value |

---

## 8. Timeline & Priorities

*Restructured based on reviewer feedback. Front-loads signal system work (where the alpha lives) and seasonal dormancy analysis, defers architecture experiments until diagnostic evidence supports them.*

### Week 1 (April 6-12): Pipeline Fixes + MLB Ops

- [x] Revert `under_low_rsc` to ≥2 (Session 514)
- [x] Solo high-conviction UNDER rescue (Session 514)
- [ ] MLB auto-deploy trigger (Cloud Build trigger + deploy step in `cloudbuild-mlb-worker.yaml`)
- [ ] MLB daily performance tracking (Slack integration)
- [ ] P0 cost fixes (BQ partition filters on remaining exporters, tiered canary)
- [ ] Signal graduation via simulator replay (`book_disagree_over`, `sharp_consensus_under`)

### Week 2 (April 13-19): Diagnostics + Signal System

- [ ] Season-phase walk-forward analysis (build on `season_replay_full.py`, 2-3 days)
- [ ] Auto training anchor (`cap_to_pre_late_season()`, compose with TIGHT market cap)
- [ ] Model the ROI of a 4-5 month season (Nov-Feb) vs full 6-month season
- [ ] P1 cost fixes (logging exclusions, legacy cleanup, AR lifecycle)

### Week 3-4 (April 20 - May 3): Decisions + MLB Checkpoint

- [ ] Walk-forward results → decide on architecture path
- [ ] May 1 MLB decision points (UNDER, signal promotion, blacklist)
- [ ] **If walk-forward shows consistent degradation:** Quantile IQR offline experiment (1-week hard kill criterion)
- [ ] **If walk-forward shows inconsistent degradation:** Skip architecture change, double down on signal system
- [ ] Alternative markets exploratory analysis (assists, rebounds — 1-2 days)
- [ ] Bet sizing analysis (Kelly criterion on historical BB picks — 1 day)

### May-June: Build Season

- [ ] NBA playoff shadow mode
- [ ] Implement auto-pause / seasonal dormancy system
- [ ] New signal development (market-consensus UNDER, stale line fade)
- [ ] MLB retrain + performance review
- [ ] Infrastructure P2 items (measure Phase 3 CPU, off-season dedup)
- [ ] Data quality fixes (`win_flag`, `is_dnp` backfill)

### July-September: MLB Peak + NBA Prep

- [ ] MLB peak performance period
- [ ] NBA 2026-27 pre-season testing with any new architecture
- [ ] Playoff-specific model development (if playoff shadow data supports it)
- [ ] New signal development

### October: Season Launch

- [ ] NBA 2026-27 season start
- [ ] MLB playoffs (shadow or active)
- [ ] Full system validation

---

## 9. Review Findings & Corrections

*This section documents what three independent review agents found wrong or missing in the V1 draft, and how V2 addresses each finding.*

### Factual Corrections

| V1 Claim | Actual | Source | Fixed in V2 |
|----------|--------|--------|-------------|
| Season record 104-70 (59.8%) | 108-76 (58.7%) pre-voiding | MEMORY.md | Yes — noted voiding adjustment needs BQ verification |
| MLB ROI 36.2% | 12.8% (current model) | mlb-system.md, mlb-session-464.md | Yes — 36.2% was from older model version |
| UNDER at edge 3-5 "56-58%" | Live BB = 36.4%, simulation = 56-58% | MEMORY.md vs bb-simulator-findings.md | Yes — now distinguishes simulation vs live |
| projection_consensus_over "0% (0-5)" | 12.5% (1/8) | sessions-472-488.md | Yes — removed specific claim |
| mean_reversion_under "12.5% HR" | Unsourced; decline was 75.7%→65.2%→53.0% | sessions-416-426.md | Yes — corrected to documented decline |
| "80+ experiments" | ~63 in dead-ends doc | model-dead-ends.md | Yes — changed to "60+" |
| Quantile regression "highest promise, ~2 days" | 6 prior failures, 5-7 day realistic estimate | dead-ends doc + codebase review | Yes — demoted to Option 5 with hard kill criterion |
| Classification model "medium promise" | Infeasible (AUC 0.507) | dead-ends doc | Yes — removed as option |
| infinite-case "$0 savings" | Session 511 saved ~$57/mo | gcp-cost-structure.md | Yes — included in cost table |

### Strategic Corrections

| V1 Issue | Reviewer | V2 Change |
|----------|----------|-----------|
| Plan prioritizes model architecture over signal system | Strategy Critic | Signal system investment promoted to Option 2 (high EV) |
| "Don't bet in March-April" treated as footnote | Strategy Critic | Seasonal dormancy promoted to Option 1 (highest EV) |
| Missing: alternative markets, bet sizing, line shopping | Strategy Critic | Added Section 7 (Unexplored Opportunities) |
| Signal graduation blocked at N=1 live picks | Strategy Critic | Added simulator replay path for graduation |
| Cross-sport unification underestimates blast radius | Strategy Critic + Tech Review | Deferred; keep systems separate |
| Timeline front-loaded with analysis, back-loaded with implementation | Strategy Critic | Restructured to front-load signal work |
| Feb 28 cap ignores ASB date drift | Tech Review | Added TODO for ASB-date-aware cap |
| Phase 3 CPU savings questionable with request billing | Tech Review | Moved to P2 (needs measurement) |
| Top signal HRs lack sample sizes | Data Auditor | Added caveat table with N warnings |
| MLB 63.4% HR presented as proven | Data Auditor | Explicitly labeled as backtest, added live HR expectations |

---

## Appendix: Key Files Reference

| Purpose | File |
|---------|------|
| BB aggregator | `ml/signals/aggregator.py` |
| Pipeline merger | `ml/signals/pipeline_merger.py` |
| Per-model pipeline | `ml/signals/per_model_pipeline.py` |
| Quick retrain | `predictions/training/quick_retrain.py` |
| Season replay | `ml/experiments/season_replay_full.py` |
| Discovery tools | `scripts/nba/training/discovery/` |
| Signal health | `ml/signals/signal_health.py` |
| Weekly retrain CF | `orchestration/cloud_functions/weekly_retrain/main.py` |
| MLB best bets | `ml/signals/mlb/best_bets_exporter.py` |
| MLB model | `predictions/mlb/` |
| Filter CF evaluator | `orchestration/cloud_functions/filter_counterfactual_evaluator/main.py` |
| Model dead ends | `docs/06-reference/model-dead-ends.md` |
| Signal inventory | `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` |
| MLB launch runbook | `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md` |
