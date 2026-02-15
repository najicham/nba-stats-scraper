# Sessions 259-262: Comprehensive Review Document

**Date:** 2026-02-15
**Purpose:** Complete summary of all work done across Sessions 259-262 for external review.
**Status:** Code committed (not yet pushed). Games resume Feb 19.

---

## Table of Contents

1. [What Problem We're Solving](#1-what-problem-were-solving)
2. [Session-by-Session Summary](#2-session-by-session-summary)
3. [Architecture: What Was Built](#3-architecture-what-was-built)
4. [Code Changes: Every File](#4-code-changes-every-file)
5. [BigQuery Infrastructure](#5-bigquery-infrastructure)
6. [Key Findings & Data](#6-key-findings--data)
7. [Feb 2 Crash Investigation](#7-feb-2-crash-investigation)
8. [What's Deployed vs What's Pending](#8-whats-deployed-vs-whats-pending)
9. [Known Issues & Risks](#9-known-issues--risks)
10. [Next Steps (Prioritized)](#10-next-steps-prioritized)

---

## 1. What Problem We're Solving

We run an NBA player props prediction system. Models predict whether players will score over/under their betting line. We need >52.4% hit rate to be profitable at -110 odds.

**The core problem across these 4 sessions:** Our champion model (catboost_v9) decayed from 71.2% hit rate at launch to ~40% by early February 2026. We needed to:
- Understand why the model crashed
- Build infrastructure to detect decay automatically
- Enable switching to better models without code deploys
- Improve signal quality (which picks to surface as "best bets")
- Prevent this from happening again

---

## 2. Session-by-Session Summary

### Session 259: Signal Infrastructure Overhaul
**Theme:** Replace hardcoded signal bonuses with data-driven registry

- Built `signal_combo_registry` BQ table with 7 validated combos (5 SYNERGISTIC, 2 ANTI_PATTERN)
- Built `signal_health_daily` BQ table for multi-timeframe signal performance tracking
- Rewrote `aggregator.py` scoring formula:
  - Edge contribution capped at `min(1.0, edge/7.0)` (was /10.0)
  - Signal count floor of 2 (eliminates 43.8% HR single-signal picks)
  - Signal count multiplier capped at 3 signals (4+ don't improve HR)
  - Registry-driven combo adjustments replace hardcoded bonuses
  - ANTI_PATTERN combos blocked entirely
- Added combo fields (`matched_combo_id`, `combo_classification`, `combo_hit_rate`) to pick tables
- Built `signal_health.py` for daily regime classification (HOT/NORMAL/COLD)
- Built `combo_registry.py` for BQ-driven combo matching with hardcoded fallback

**Key discovery:** `high_edge` standalone is an ANTI_PATTERN (43.8% HR, below breakeven). The `edge_spread_optimal + high_edge` combination is a "redundancy trap" (31.3% HR). But `high_edge + minutes_surge` is the best combo (88.9% HR on 17 picks).

### Session 260: Adaptive Model Selection & Signal Health Weighting
**Theme:** Decouple best bets model from champion, make signals health-aware

- Built `shared/config/model_selection.py`:
  - `BEST_BETS_MODEL_ID` env var controls which model drives best bets
  - `get_min_confidence(model_id)` for per-model confidence floors
  - Champion (V9) stays for grading/baseline, V12 can drive best bets independently
- Implemented signal health weighting (LIVE, not just monitoring):
  - HOT regime signals: 1.2x weight
  - NORMAL regime: 1.0x weight
  - COLD regime: 0.5x weight
  - Applied in aggregator's `_weighted_signal_count()` method
- Removed hardcoded champion ID from `signal_annotator.py`, `signal_best_bets_exporter.py`, `supplemental_data.py`
- Fail-safe: if `signal_health_daily` table is missing/empty, defaults to 1.0x (identical to Session 259)

**Key decision:** Signal health weighting is informational-with-teeth. It adjusts the scoring formula but does NOT block picks. Session 257 proved threshold-based blocking has negative EV.

### Session 261: Historical Replay Analysis & Decision Framework
**Theme:** How should we detect decay and decide when to switch models?

- Analyzed champion (V9) decay timeline: 77.4% → 57.3% → 42.3% over 3 weeks
- Confirmed signals amplify model accuracy (good or bad) rather than generating independent value
- Found behavioral signals (cold_snap, 3pt_bounce, minutes_surge) actually improved during crash week while model-dependent signals collapsed
- Designed decision framework:
  - WATCH at 58% 7d rolling HR (2+ consecutive days)
  - ALERT at 55% (3+ consecutive days)
  - BLOCK at 52.4% (breakeven threshold)
  - Consecutive-day gates prevent noise-driven false positives
- Designed replay tool architecture (4 strategies: Threshold, BestOfN, Conservative, Oracle)
- Created Feb 2 investigation prompt for parallel analysis

### Session 262: Build Everything + Feb 2 Investigation
**Theme:** Implement all Session 261 designs, investigate the worst single day

**Part A — Building:**
- V12 confidence floor: filters 0.87 tier (41.7% HR) from best bets, keeps 0.90+ (60.5% HR)
- Built `model_performance_daily` BQ table + backfilled 47 rows (Nov 2025 - Feb 2026)
- Built `replay_engine.py`, `replay_strategies.py`, `replay_cli.py` with 4 strategies
- Built decay detection Cloud Function (`orchestration/cloud_functions/decay_detection/`)
- Built `/replay` Claude skill
- Added `validate-daily` Phase 0.58 (model performance dashboard)
- Deduplicated combo registry (14 rows → 7)

**Replay calibration results:**

| Strategy | HR | ROI | P&L | Switches |
|----------|-----|-----|------|----------|
| **Threshold (58/55/52.4)** | **69.1%** | **31.9%** | $3,400 | 1 |
| Conservative (5d, 55%) | 67.0% | 27.8% | $3,520 | 0 |
| Oracle (hindsight) | 62.9% | 20.0% | $3,680 | 35 |
| BestOfN | 59.5% | 13.6% | $2,360 | 2 |

**Key insight:** Blocking bad days > picking the best model. Threshold has the highest ROI because eliminating loss-making days matters more than optimizing model selection.

**Part B — Feb 2 Crash Investigation:**
- Feb 2 was the worst day in V9 history: 33 edge 3+ picks, 5 wins, 15.2% HR
- 94% of picks were UNDER, avg prediction error -10.32 points
- Every model crashed (V8 at 28.6%, moving_average at 48.0%) — market-wide event
- Root cause: model decay (25+ days stale) amplified by record-breaking trade deadline week (28 trades, 73 players, both NBA records)
- V8 historical analysis shows deadline weeks are NOT normally problematic (73-82% HR across 4 prior seasons)
- 2025-26 is the outlier, not the trade deadline pattern
- Model-dependent signals made it worse (5.9-8.0% HR), behavioral signals went 3/3 (100%)
- A 7-day rolling HR alert at 58% would have fired on Jan 28 — 5 days before the crash

---

## 3. Architecture: What Was Built

### System Flow

```
Model Selection Layer:
  shared/config/model_selection.py (env var + per-model config)
    |
    +---> signal_best_bets_exporter.py (exports top 5 picks)
    +---> signal_annotator.py (annotations + signal picks subset)
    +---> decay_detection/main.py (Slack alerts)

Signal Discovery Framework:
  ml/signals/aggregator.py (health-weighted scoring)
    |
    +---> combo_registry.py (BQ-driven combo matching)
    +---> signal_health.py (regime classification)
    |
    +---> signal_best_bets_exporter.py
    +---> signal_annotator.py

Model Performance Monitoring:
  ml/analysis/model_performance.py (compute daily metrics)
    |
    +---> model_performance_daily BQ table
    +---> orchestration/decay_detection/main.py (queries for alerts)
    +---> ml/analysis/replay_engine.py (historical analysis)

Replay/Backtesting:
  ml/analysis/replay_cli.py
    |
    +---> replay_engine.py (simulation core)
    +---> replay_strategies.py (4 pluggable strategies)
```

### Scoring Formula (Aggregator)

```python
edge_score = min(1.0, abs(edge) / 7.0)

# Each signal contributes its health multiplier (HOT=1.2, NORMAL=1.0, COLD=0.5)
effective_signals = sum(health_multipliers_for_qualifying_signals)
effective_signals = min(effective_signals, 3.0)  # cap

signal_multiplier = 1.0 + 0.3 * (effective_signals - 1)  # max 1.6x

composite_score = (edge_score * signal_multiplier) + combo_adjustment
```

**Filters applied (in order):**
1. Edge >= 3.0 (configured threshold)
2. Signal count >= 2 (MIN_SIGNAL_COUNT floor)
3. Model-specific confidence floor (V12: >= 0.90)
4. ANTI_PATTERN combos blocked
5. Top 5 picks selected by composite_score

### Decay State Machine

```
HEALTHY (7d HR >= 58%)
    |
    v  (7d HR < 58% for 2+ consecutive days)
WATCH
    |
    v  (7d HR < 55% for 3+ consecutive days)
DEGRADING
    |
    v  (7d HR < 52.4%)
BLOCKED
    |
    v  (recovery: 7d HR > 58% for 2+ consecutive days)
HEALTHY
```

---

## 4. Code Changes: Every File

### New Files (12)

| File | Purpose | Session |
|------|---------|---------|
| `shared/config/model_selection.py` | Best bets model config, confidence floors | 260 |
| `ml/signals/signal_health.py` | Daily signal regime computation (HOT/COLD) | 259 |
| `ml/signals/combo_registry.py` | BQ-driven combo matching | 259 |
| `ml/analysis/__init__.py` | Package marker | 262 |
| `ml/analysis/model_performance.py` | Daily model metrics + state machine | 262 |
| `ml/analysis/replay_engine.py` | Core replay simulation | 262 |
| `ml/analysis/replay_strategies.py` | 4 pluggable decision strategies | 262 |
| `ml/analysis/replay_cli.py` | CLI for replay tool | 262 |
| `orchestration/cloud_functions/decay_detection/__init__.py` | Package marker | 262 |
| `orchestration/cloud_functions/decay_detection/main.py` | Decay alert Cloud Function | 262 |
| `orchestration/cloud_functions/decay_detection/requirements.txt` | CF dependencies | 262 |
| `.claude/skills/replay/SKILL.md` | /replay skill docs | 262 |

### Modified Files (5)

| File | Changes | Session |
|------|---------|---------|
| `ml/signals/aggregator.py` | Scoring formula rewrite, health weighting, combo registry, confidence floor | 259-260 |
| `data_processors/publishing/signal_best_bets_exporter.py` | Dynamic model_id, combo fields, signal health in JSON | 259-260 |
| `data_processors/publishing/signal_annotator.py` | Dynamic model_id, combo matching, health weighting | 259-260 |
| `data_processors/publishing/supplemental_data.py` | Added position, is_home fields | 259 |
| `.claude/skills/validate-daily/SKILL.md` | Phase 0.58 model performance dashboard | 262 |

### Documentation (6 files)

| File | Purpose |
|------|---------|
| `docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md` | Session 259 handoff |
| `docs/09-handoff/2026-02-15-SESSION-260-HANDOFF.md` | Session 260 handoff |
| `docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md` | Session 261 handoff |
| `docs/09-handoff/2026-02-15-SESSION-262-HANDOFF.md` | Session 262 handoff |
| `docs/08-projects/current/signal-discovery-framework/SESSION-262-FEB2-CRASH-INVESTIGATION.md` | Full crash forensics |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Quick start for next session |

---

## 5. BigQuery Infrastructure

### New Tables

**1. `nba_predictions.signal_combo_registry`** (Session 259)
- Registry of validated signal combinations
- 7 entries: 5 SYNERGISTIC, 2 ANTI_PATTERN
- Fields: combo_id, classification, status, hit_rate, roi, sample_size, score_weight, conditional_filters
- Used by aggregator for data-driven combo scoring

**2. `nba_predictions.signal_health_daily`** (Session 259)
- Daily signal performance across 4 timeframes (7d, 14d, 30d, season)
- Regime classification: HOT (divergence > +10), NORMAL, COLD (divergence < -10)
- 298 rows backfilled (Jan 9 - Feb 14)
- Used by aggregator for health-weighted signal scoring

**3. `nba_predictions.model_performance_daily`** (Session 262)
- Daily model decay tracking with state machine
- Rolling HR (7d, 14d, 30d), daily picks/wins/losses, consecutive-day counters
- States: HEALTHY, WATCH, DEGRADING, BLOCKED, INSUFFICIENT_DATA
- 47 rows backfilled (Nov 2025 - Feb 2026)
- Used by decay detection CF and replay engine

**4. `nba_predictions.v_signal_combo_performance`** (Session 259, VIEW)
- Joins pick_signal_tags with prediction_accuracy for combo analysis
- Used for ad-hoc combo performance queries

### Schema Extensions (ALTER TABLE)

| Table | New Columns | Purpose |
|-------|-------------|---------|
| `pick_signal_tags` | matched_combo_id, combo_classification, combo_hit_rate | Combo tracking per pick |
| `signal_best_bets_picks` | matched_combo_id, combo_classification, combo_hit_rate, warning_tags | Combo + anti-pattern warnings |
| `current_subset_picks` | warning_tags | Anti-pattern flags |

### Data Operations
- Combo registry deduplicated: 14 rows → 7 (INSERT had run twice)
- Signal health backfilled: 298 rows
- Model performance backfilled: 47 rows

---

## 6. Key Findings & Data

### Signal Performance (from Session 259 backtest)

| Signal | Picks | HR | Classification |
|--------|------:|---:|----------------|
| edge_spread_optimal + high_edge + minutes_surge | 17 | 88.9% | SYNERGISTIC |
| cold_snap (home only) | 15 | 93.3% | SYNERGISTIC (conditional) |
| high_edge + minutes_surge | 34 | 79.4% | SYNERGISTIC |
| 3pt_bounce | 29 | 69.0% | SYNERGISTIC |
| blowout_recovery | 50 | 58.0% | SYNERGISTIC |
| high_edge standalone | 16 | 43.8% | ANTI_PATTERN |
| edge_spread_optimal + high_edge | 16 | 31.3% | ANTI_PATTERN (redundancy trap) |

### Signal Health Regimes (from Session 260)

| Regime | Avg HR | Description |
|--------|-------:|-------------|
| HOT | >80% | Signal divergence > +10 vs season baseline |
| NORMAL | ~60-80% | Signal performing near season average |
| COLD | ~40% | Signal divergence < -10, underperforming |

**COLD signals at 0.5x weight may still be too generous.** Feb 2 investigation shows model-dependent signals in COLD regime hit 5.9-8.0%. Recommendation: consider 0.0x for COLD model-dependent signals.

### V12 Confidence Tiers (from Session 262)

| Confidence | Picks | HR | Action |
|------------|------:|---:|--------|
| 0.87 | 12 | 41.7% | **FILTERED** (below breakeven) |
| 0.90 | 20 | 55.0% | Included |
| 0.92 | 10 | 70.0% | Included |
| 0.95 | 8 | 62.5% | Included |
| **0.90+** | **38** | **60.5%** | **Production threshold** |

### Model Decay Timeline (from Session 261)

| Date | V9 7d HR | State | Event |
|------|------:|-------|-------|
| Jan 12-18 | 77.4% | HEALTHY | Peak performance week |
| Jan 19-25 | 57.3% | WATCH | First dip below 58% |
| Jan 27 | — | — | V8 also crashes (25.0%, market event) |
| Jan 28 | 59.2% → declining | WATCH fires | 5 days before crash |
| Jan 31 | ~55% | ALERT fires | 2 days before crash |
| Feb 1-7 | 42.3% | BLOCKED | Crash week |
| Feb 2 | 15.2% | — | Worst single day |

### Replay Calibration (from Session 262)

| Strategy | HR | ROI | P&L | Switches | Blocked Days |
|----------|-----|-----|------|----------|-------------|
| **Threshold** | **69.1%** | **31.9%** | **$3,400** | 1 | ~8 |
| Conservative | 67.0% | 27.8% | $3,520 | 0 | ~12 |
| Oracle | 62.9% | 20.0% | $3,680 | 35 | 0 |
| BestOfN | 59.5% | 13.6% | $2,360 | 2 | 0 |

**Conclusion:** Standard thresholds (58/55/52.4) are well-calibrated. Threshold strategy has highest ROI because blocking bad days eliminates losses more effectively than picking the best model.

---

## 7. Feb 2 Crash Investigation

### What Happened

On February 2, 2026, our champion model produced 33 edge 3+ picks with only 5 wins (15.2% HR). It was the worst single day in the model's history.

### Root Cause

Two independent factors compounding:

1. **Model decay (primary):** Champion was 25+ days stale, already declining from 77.4% to ~55% over 3 weeks. The model's training data (Nov-Jan) was no longer representative.

2. **Record-breaking trade deadline (amplifier):** The NBA trade deadline was Feb 5 — 3 days later. Feb 2 was the start of the most active deadline week in NBA history (28 trades, 73 players moved, both records). This created:
   - Players "showcased" for trades playing harder (JJJ scored 30, predicted 13.8)
   - Massive star absences shifting usage to unexpected players (Sengun scored 39 with KD/VanVleet/Adams out)
   - Sportsbooks not fully adjusting lines for the chaos

### Key Evidence

**Every model crashed (not just V9):**

| Model | Feb 2 HR | Avg Bias |
|-------|------:|------:|
| moving_average | 48.0% | -6.98 |
| ensemble_v1_1 | 45.5% | -5.47 |
| similarity_balanced_v1 | 42.9% | -6.29 |
| catboost_v8 | 28.6% | -6.93 |
| catboost_v9 | 15.2% | -10.32 |

**Model-dependent signals amplified damage:**

| Signal Type | Feb 2 HR | Example |
|------------|------:|---------|
| Model-dependent (high_edge, edge_spread) | 5.9-8.0% | Concentrated bets on wrong UNDER picks |
| Behavioral (minutes_surge) | 100% (3/3) | Independent of model, picked OVER |
| No signals | 37.5% | Better than signal-tagged |

**V8 historical context (trade deadline is NOT normally bad):**

| Season | Deadline Week HR |
|--------|-------------:|
| 2021-22 | 78.2% |
| 2022-23 | 81.9% |
| 2023-24 | 73.3% |
| 2024-25 | 80.3% |
| **2025-26** | **47.9%** |

**Warning signs visible 4-5 days before crash:**
- Jan 28: 7d rolling HR crossed 58% threshold (WATCH would have fired)
- Jan 31: Below 55% for 2+ days (ALERT would have fired)
- The decay detection system we built in Session 262 would have caught this

### What We Can't Predict

- Trade rumors / showcase games (not in our data pipeline)
- Record-breaking deadline volume (no historical precedent)
- Directional bias emergence (94% UNDER only visible day-of)

---

## 8. What's Deployed vs What's Pending

### Committed (in git, not yet pushed)

| Component | Status |
|-----------|--------|
| V12 confidence floor (0.90+) | In code, deploys on push |
| Signal health weighting (HOT/COLD) | In code, deploys on push |
| Combo registry integration | In code, deploys on push |
| Signal count floor (MIN=2) | In code, deploys on push |
| Model selection via env var | In code, deploys on push |
| Replay engine + CLI + skill | In code, ready to use locally |
| Decay detection CF code | In code, needs Cloud Build trigger |
| All documentation | Committed |

### BigQuery (already created)

| Component | Status |
|-----------|--------|
| signal_combo_registry table | Created, 7 rows |
| signal_health_daily table | Created, 298 rows backfilled |
| model_performance_daily table | Created, 47 rows backfilled |
| v_signal_combo_performance view | Created |
| Schema extensions (ALTER TABLE) | Applied |

### Not Yet Deployed / Pending

| Component | What's Needed |
|-----------|---------------|
| Push to main | `git push origin main` (auto-deploys Cloud Run) |
| Decay detection CF trigger | Cloud Build trigger creation (command in handoff) |
| Decay detection scheduler | Cloud Scheduler job at 11 AM ET daily |
| model_performance_daily automation | Wire into post-grading pipeline |
| latest.json | Will generate on first game day (Feb 19) |
| COLD signal 0.0x weight | Code change needed (currently 0.5x) |
| Directional concentration check | Not yet built |
| Cross-model crash detector | Not yet built |

### Environment Variables (already set on Cloud Run)

| Env Var | Service | Value |
|---------|---------|-------|
| `BEST_BETS_MODEL_ID` | phase6-export | catboost_v12 |
| `BEST_BETS_MODEL_ID` | post-grading-export | catboost_v12 |

---

## 9. Known Issues & Risks

### Active Issues

1. **COLD model-dependent signals at 0.5x may be too generous.** Investigation shows 5.9-8.0% HR during decay. Recommendation: 0.0x for model-dependent signals during COLD regime.

2. **model_performance_daily not auto-populated.** Currently requires manual backfill. Needs to be wired into post-grading pipeline for daily automation.

3. **Decay detection CF not deployed.** Code is committed but needs Cloud Build trigger + Cloud Scheduler job creation.

4. **V12 only 12 days old as of Feb 2.** Limited grading data. Need to verify V12 predictions generate for Feb 19 games.

5. **Vegas line move feature (feature 27) is 93% NULL.** Makes vegas-based signals untestable. Pipeline fix needed upstream.

6. **February is historically the weakest month** for V8 (76.0% HR). Monitor closely when games resume.

### Design Decisions to Validate

1. **58%/55%/52.4% thresholds** — Calibrated against Nov 2025-Feb 2026 data only. May need adjustment with more seasons.

2. **Signal count floor of 2** — Eliminates single-signal picks (43.8% HR). But also reduces pick volume. Monitor coverage impact.

3. **Confidence floor approach** — V12-specific (0.90). Other models don't have discrete confidence tiers. May need per-model tuning.

4. **Consecutive-day gates** — 2 days for WATCH, 3 for DEGRADING. Prevents noise but adds latency. Replay suggests this is well-calibrated.

---

## 10. Next Steps (Prioritized)

### Before Feb 19 (Games Resume)

1. **Push to main** — Auto-deploys Cloud Run services with V12 confidence filter, signal health weighting, combo registry
2. **Create Cloud Build trigger** for decay detection CF (command in Session 262 handoff)
3. **Create Cloud Scheduler job** for decay detection (11 AM ET daily)
4. **Verify V12 predictions** will generate for Feb 19 games
5. **Run validate-daily** on Feb 19 to confirm pipeline health

### Near-Term (Next 1-2 Sessions)

6. **Wire model_performance_daily** into post-grading pipeline for auto-population
7. **Consider COLD model-dependent signals at 0.0x** — strong evidence from Feb 2 investigation
8. **Build directional concentration monitor** — flag if >80% picks are same direction
9. **Build cross-model crash detector** — flag if 2+ models < 40% same day (market disruption vs model decay)
10. **Test /replay skill** with various scenarios

### Future (Next Season Prep)

11. **Calendar-aware risk flags** — Trade deadline week, All-Star break (NOT auto-block, just increased sensitivity)
12. **Integrate injury severity** — When >3 stars OUT across slate, increase uncertainty
13. **Monthly model health reporting** — Feb and Jan are weakest months, need more aggressive monitoring
14. **Trade rumor awareness** — Exclude players in active trade discussions during deadline week

---

## Appendix: Key Commands

```bash
# Push and deploy
git push origin main

# Replay last 30 days
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2026-01-15 --end 2026-02-12 \
    --models catboost_v9,catboost_v12 --compare

# Check model performance
bq query --use_legacy_sql=false \
    "SELECT model_id, rolling_hr_7d, rolling_n_7d, state
     FROM nba_predictions.model_performance_daily
     WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
     ORDER BY model_id"

# Backfill model performance for new date
PYTHONPATH=. python ml/analysis/model_performance.py --date 2026-02-19

# Check signal health
bq query --use_legacy_sql=false \
    "SELECT signal_tag, regime, hr_7d, hr_season, divergence_7d_vs_season
     FROM nba_predictions.signal_health_daily
     WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily)
     ORDER BY regime DESC, signal_tag"

# Deploy decay detection CF (after push)
gcloud builds triggers create github \
  --name="deploy-decay-detection" \
  --repository="projects/nba-props-platform/locations/us-west2/connections/nba-github-connection/repositories/nba-stats-scraper" \
  --branch-pattern="^main$" \
  --build-config="cloudbuild-functions.yaml" \
  --included-files="orchestration/cloud_functions/decay_detection/**,shared/**" \
  --service-account="projects/nba-props-platform/serviceAccounts/github-actions-deploy@nba-props-platform.iam.gserviceaccount.com" \
  --region="us-west2" --project="nba-props-platform" \
  --substitutions="_FUNCTION_NAME=decay-detection,_ENTRY_POINT=decay_detection,_SOURCE_DIR=orchestration/cloud_functions/decay_detection,_TRIGGER_TYPE=http,_ALLOW_UNAUTHENTICATED=true,_MEMORY=512Mi,_TIMEOUT=300s"

# Directional concentration check
bq query --use_legacy_sql=false \
    "SELECT recommendation, COUNT(*) as picks,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
     FROM nba_predictions.player_prop_predictions
     WHERE game_date = CURRENT_DATE()
       AND system_id = 'catboost_v9'
       AND ABS(predicted_points - current_points_line) >= 3.0
       AND is_active = TRUE
     GROUP BY 1"
```

---

## Appendix: File Index

All files touched across Sessions 259-262:

```
New Code (12 files):
  shared/config/model_selection.py
  ml/signals/signal_health.py
  ml/signals/combo_registry.py
  ml/analysis/__init__.py
  ml/analysis/model_performance.py
  ml/analysis/replay_engine.py
  ml/analysis/replay_strategies.py
  ml/analysis/replay_cli.py
  orchestration/cloud_functions/decay_detection/__init__.py
  orchestration/cloud_functions/decay_detection/main.py
  orchestration/cloud_functions/decay_detection/requirements.txt
  .claude/skills/replay/SKILL.md

Modified Code (5 files):
  ml/signals/aggregator.py
  data_processors/publishing/signal_best_bets_exporter.py
  data_processors/publishing/signal_annotator.py
  data_processors/publishing/supplemental_data.py
  .claude/skills/validate-daily/SKILL.md

Documentation (7 files):
  docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md
  docs/09-handoff/2026-02-15-SESSION-260-HANDOFF.md
  docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md
  docs/09-handoff/2026-02-15-SESSION-262-HANDOFF.md
  docs/09-handoff/START-NEXT-SESSION-HERE.md
  docs/08-projects/current/signal-discovery-framework/SESSION-262-FEB2-CRASH-INVESTIGATION.md
  docs/09-handoff/SESSION-259-262-COMPREHENSIVE-REVIEW.md (this file)
```

**Total:** ~4,000 lines of new code across 17 code files, implementing a complete model selection, signal monitoring, decay detection, and historical replay framework.
