# MLB System Replication Guide

> **Purpose:** This document is a comprehensive study guide for a new Claude Code session tasked with building an MLB prediction system (pitcher strikeouts, team betting) following the same architecture, principles, and operational practices as the NBA player props system. Read this guide first, then study the referenced files in order.

## How to Use This Guide

1. **Read this entire document first** — it maps the NBA system's architecture, evolution, and hard-won lessons
2. **Study the referenced files in the order listed** — each section builds on the previous
3. **Pay special attention to the "Lessons Learned" sections** — these represent 388+ sessions of iteration
4. **The dead-end documentation is as valuable as the working code** — it prevents wasting weeks on approaches that don't work

---

## Part 1: System Architecture & Design Philosophy

### 1.1 Core Principles (Read First)

The NBA system was built iteratively over 388+ sessions. These principles emerged from painful failures:

1. **Data quality first** — Discovery queries before assumptions. Never predict with fabricated feature values.
2. **Edge-first architecture** — The model's prediction edge (predicted - line) IS the primary signal. Signals filter and annotate, they don't select.
3. **Zero tolerance for defaults** — Any feature with a default/fabricated value blocks the prediction. Coverage drops from ~180 to ~75 players per day. Intentional.
4. **Batch over streaming** — BigQuery streaming inserts create rows that can't be UPDATEd for ~30 minutes. Always use batch loads.
5. **The filter stack is more valuable than model architecture** — All CatBoost V12 configs produce roughly the same quality within ~5pp. The 14+ negative filters + 21 signals + multi-model aggregation create the actual edge.
6. **Any model comparison difference < 5pp is noise** — Cross-season validation showed 2.5pp StdDev across random seeds. Only trust differences above 5pp.
7. **MAE is not a proxy for betting profitability** — A model with MAE 4.12 crashed HR to 51.2% due to UNDER bias. Build governance around hit rate, not point prediction error.

### 1.2 Files to Study

| File | What You'll Learn |
|------|-------------------|
| `CLAUDE.md` | Complete system overview, all conventions, quick-start commands |
| `docs/01-architecture/pipeline-design.md` | Six-phase event-driven pipeline design |
| `docs/01-architecture/data-flow-comprehensive.md` | End-to-end data flow from scraping to predictions |
| `docs/01-architecture/best-bets-and-subsets.md` | Best bets selection pipeline, the 14-filter stack, 39 subsets, signal architecture |
| `docs/01-architecture/quick-reference.md` | 2-page pipeline overview |

---

## Part 2: The Six-Phase Pipeline

The system is a **six-phase data pipeline** on GCP (Cloud Run, Cloud Functions, BigQuery, GCS, Firestore, Pub/Sub). Daily workflow starts ~6 AM ET.

### Phase 1 — Scrapers

**What:** 30+ scrapers pull data from external APIs → JSON files in GCS.

**Pattern:** Each scraper extends `ScraperBase` with lifecycle: `set_url() → download() → validate() → transform() → export() → publish_completion_event()`. Scrapers export to GCS as JSON (decoupled from processing). Pub/Sub completion events trigger Phase 2.

**Key design decisions:**
- Proxy support for rate-limited APIs (NBA.com)
- Multi-channel notifications (Slack + email) for failures
- Smart season type detection (Regular Season, Playoffs, All-Star)
- Exporter registry pattern for easy addition of new export destinations
- Pipeline event logging to BigQuery for observability and auto-retry queue

**Files to study:**
- `scrapers/scraper_base.py` — Base class with full lifecycle (760+ lines)
- `scrapers/registry.py` — Central registry of all scrapers (30+ NBA, 27+ MLB stubs)
- `scrapers/nbacom/nbac_player_boxscore.py` — Representative scraper
- `scrapers/exporters.py` — GCS/File export patterns
- `docs/06-reference/scrapers/00-SCRAPER-INVENTORY.md` — Complete catalog of all scrapers

**MLB implication:** MLB scraper stubs already exist in `scrapers/mlb/`. Need: pitcher game logs, team boxscores, strikeout props, game lines, lineups, bullpen usage, umpire assignments.

### Phase 2 — Raw Processing

**What:** JSON files in GCS → BigQuery raw tables (`nba_raw.*`).

**Pattern:** Each processor implements `load_data() → validate() → transform() → save()`. Uses `MERGE_UPDATE` (delete-then-insert), NOT streaming inserts. Smart idempotency via content hashing (30% expected skip rate).

**Critical lesson:** Always include partition filter (`game_date`) on BigQuery queries — without it, queries scan entire tables and cost 100x more.

**Files to study:**
- `data_processors/raw/processor_base.py` — Base class
- `data_processors/raw/nbacom/nbac_player_boxscore_processor.py` — Representative processor
- `data_processors/raw/smart_idempotency_mixin.py` — Hash-based dedup
- `data_processors/raw/mlb/` — MLB raw processors (10 files already exist)

### Phase 3 — Analytics

**What:** Raw tables → game-level analytics (`nba_analytics.*`).

**Key output:** `player_game_summary` — 48 fields including performance stats, shot zones, prop betting results, advanced efficiency.

**Pattern:** Multi-source aggregation with graceful degradation. Primary source (gamebook_player_stats) is CRITICAL, optional sources (shot zones, prop lines) degrade gracefully. Quality gates validate upstream freshness.

**Files to study:**
- `data_processors/analytics/analytics_base.py` — Base with dependency checking, change detection, heartbeat
- `data_processors/analytics/player_game_summary/` — Core player analytics
- `data_processors/analytics/upcoming_player_game_context/` — Forward-looking context (betting data, travel, team stats)
- `data_processors/analytics/mlb/` — MLB analytics stubs

**MLB implication:** Need pitcher_game_summary (strikeouts, innings, pitches, game score), team_game_summary (runs, hits, errors), upcoming_pitcher_game_context (opponent lineup, park factors, weather).

### Phase 4 — Precompute / Feature Engineering

**What:** Analytics tables → ML feature vectors in `ml_feature_store_v2`.

**This is the most critical phase.** The feature store is the single source of truth for model training AND production inference. Train/serve skew is prevented by using the SAME feature contract.

**Key concepts:**
- **Feature contract** (`shared/ml/feature_contract.py`) — Versioned feature definitions. V12 = 54 features, V12_NOVEG = 50 (minus 4 vegas features). The contract is the single source of truth for both training and inference.
- **Quality scoring** — 9 source types scored 0-100. Required features with default values cap quality at 69 (below the 70 threshold), blocking the prediction.
- **Zero-tolerance defaults** — `HARD_FLOOR_MAX_DEFAULTS = 0`. Any player with even 1 fabricated required feature is blocked from prediction.
- **Feature categories:** Recent performance, composite factors, derived factors, matchup context, shot zones, team context, vegas lines, opponent history, minutes/efficiency, player trajectory.

**Files to study (critical — read in this order):**
- `shared/ml/feature_contract.py` — Feature version contracts (MOST IMPORTANT)
- `data_processors/precompute/ml_feature_store/quality_scorer.py` — Quality scoring logic
- `data_processors/precompute/ml_feature_store/feature_extractor.py` — How features are extracted from Phase 3/4 tables
- `data_processors/precompute/ml_feature_store/feature_calculator.py` — Derived feature computation
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — Main processor
- `docs/08-projects/current/zero-tolerance-defaults/` — Zero-tolerance design docs

**MLB implication:** Need MLB-specific feature contract: recent K rates, pitch mix, opponent lineup quality, park factors, weather, bullpen availability, platoon splits, umpire tendencies.

### Phase 5 — Predictions

**What:** Feature vectors → predictions in `player_prop_predictions`.

**Architecture:** Coordinator/Worker pattern.
- **Coordinator** (Cloud Run): Queries eligible players, publishes prediction requests via Pub/Sub, tracks batch progress via Firestore, enforces quality gates.
- **Worker** (Cloud Run, 0-20 instances): Receives requests, loads models, generates predictions. Supports CatBoost, LightGBM, XGBoost.

**Multi-model fleet:** 15+ models run simultaneously. The worker reads the model registry at startup and loads all enabled models. Each player gets predictions from every enabled model.

**Files to study:**
- `predictions/coordinator/coordinator.py` — Batch orchestration
- `predictions/coordinator/quality_gate.py` — Quality enforcement (HARD_FLOOR_MAX_DEFAULTS = 0)
- `predictions/worker/worker.py` — Prediction generation
- `predictions/worker/prediction_systems/catboost_v12.py` — Representative model implementation
- `predictions/mlb/` — MLB prediction stubs (worker, pitcher_loader, strikeouts_predictor)

### Phase 6 — Publishing

**What:** Predictions + signal analysis → JSON files to GCS API + BigQuery tables.

**The filter stack lives here.** The `BestBetsAggregator` applies 14+ negative filters, signal count gates, and ranks by edge. This is where raw predictions become actionable picks.

**35+ exporters** handle different output formats: best bets, tonight's players, trends, model health, admin dashboards, etc.

**Files to study:**
- `ml/signals/aggregator.py` — **THE MOST IMPORTANT FILE** — 14+ filter cascade, edge-tiered signal count, ultra bets classification
- `data_processors/publishing/signal_best_bets_exporter.py` — Main export pipeline
- `data_processors/publishing/signal_annotator.py` — Signal annotation bridge
- `orchestration/cloud_functions/phase6_export/main.py` — Export trigger

---

## Part 3: The Signal System

### 3.1 How Signals Work

Signals are **pure evaluators** — they take a prediction + supplemental data and return whether the prediction meets criteria. They do NOT select picks. The edge-first architecture means:

1. Model edge (predicted - line) is the primary ranking signal
2. Signals provide **filtering** (minimum signal count gate) and **annotation** (pick angles explaining why)
3. Signal count correlates with quality: SC=3 = 55.1% HR, SC=4 = 76.0%, SC=6+ = 88.2%

### 3.2 Signal Architecture

| Component | File | Purpose |
|-----------|------|---------|
| Base interface | `ml/signals/base_signal.py` | `BaseSignal` ABC with `.evaluate()` → `SignalResult` |
| Registry | `ml/signals/registry.py` | Factory registering all 21 active signals |
| Health monitoring | `ml/signals/signal_health.py` | Rolling HR by timeframe, regime classification (HOT/NORMAL/COLD), firing canary |
| Supplemental data | `ml/signals/supplemental_data.py` | Shared BQ queries for signal inputs (prop deltas, DK movement, streak data) |
| Combo registry | `ml/signals/combo_registry.py` | Signal combination tracking with HR/ROI |
| Pick angles | `ml/signals/pick_angle_builder.py` | Human-readable reasoning per pick |

### 3.3 Active Signals (21 total)

Study a few representative signals to understand the pattern:
- `ml/signals/high_edge.py` — Simple threshold signal (edge >= 5.0)
- `ml/signals/fast_pace_over.py` — Feature-based conditional (opponent pace >= threshold)
- `ml/signals/combo_he_ms.py` — Multi-condition combo (edge + minutes surge)
- `ml/signals/line_rising_over.py` — Market movement signal (prop line increased)
- `ml/signals/sharp_line_move_over.py` — DraftKings intra-day movement signal

### 3.4 The Filter Stack (Edge-First Best Bets Selection)

The aggregator (`ml/signals/aggregator.py`) applies filters in order (cheapest checks first):

1. **Model sanity guard** — Blocks models with >95% same-direction predictions
2. **Legacy model blocklist** — Hardcoded models bypassing registry
3. **Player blacklist** — <40% HR on 8+ edge-3+ picks
4. **Edge floor** — 3.0 minimum (premium signals bypass)
5. **OVER edge 5+ floor** — OVER picks below edge 5 are 25% HR
6. **UNDER edge 7+ block** — V9 family only (34.1% HR)
7. **Model-direction affinity** — Data-driven blocking of bad model+direction+edge combos
8. **AWAY block** — v12_noveg/v9 families on away games (43-48% HR)
9. **Familiar matchup** — 6+ games vs opponent
10. **Feature quality floor** — quality < 85 (24% HR)
11. **Bench/star/starter tier blocks** — Direction-specific tier filters
12. **Line movement blocks** — Line jumped/dropped + direction combinations
13. **Opponent blocks** — Toxic opponents for UNDER, depleted opponents
14. **Edge-tiered signal count** — SC >= 4 for edge < 7, SC >= 3 for edge >= 7
15. **Starter OVER SC floor** — SC >= 5 for starter tier OVER
16. **Signal density** — Base-only signals blocked unless extreme edge
17. **Anti-pattern combos** — Known bad signal combinations

**Critical lesson:** The filter stack evolved over 100+ sessions. Each filter has a session number, HR data, sample size, and reasoning. Filters that block profitable picks are detected by `bin/monitoring/filter_health_audit.py` (counterfactual analysis).

### 3.5 Ultra Bets

High-confidence classification layer on top of best bets. 2+ criteria required (single-criterion was 33.3% HR). Live performance: 75.8% HR overall, Ultra OVER 89.5%.

**File:** `ml/signals/ultra_bets.py`

### 3.6 How to Build Signals for MLB

**Process followed for NBA (replicate for MLB):**
1. Hypothesize a pattern (e.g., "pitchers with 7+ K in last 3 starts go OVER")
2. Validate with BQ query on historical data — check HR, sample size, Feb resilience
3. Check if the pattern survives the existing filter stack (raw HR may be 50% but best bets HR may be 60% because filters already handle it)
4. Implement as a `BaseSignal` subclass
5. Shadow test for 2+ weeks
6. Promote if sustained HR above breakeven

**Dead-end documentation is critical.** The NBA system has 24 removed/disabled signals, each with session number and failure reason. This prevents revisiting failed approaches.

---

## Part 4: Model Lifecycle

### 4.1 Training Pipeline

**File:** `ml/experiments/quick_retrain.py` (~4,500 lines)

**Flow:** Parse args → calculate date ranges → quality-check data → duplicate check → load train/eval data → prepare features → apply weights → train model → evaluate → run governance gates → auto-upload to GCS → auto-register in model_registry.

**Key decisions:**
- Rolling window (42-56 days), not expanding — old data dilutes signal
- Production-line evaluation (same lines the system actually used, not raw sportsbook)
- Feature contracts as single source of truth (prevents train/serve skew)
- Quality-gated data loading (zero tolerance for defaults)

### 4.2 Governance Gates (6 Hard + 1 Soft)

All must pass before a model can be registered:

1. **Hit rate (edge 3+) >= 60%** — Must be profitable at the edge threshold
2. **Sample size >= 25** — Need enough edge 3+ bets
3. **Vegas bias within +/- 1.5** — Model must be calibrated against market
4. **No critical tier bias** — No tier with > +/- 5 point systematic error
5. **Directional balance** — Both OVER and UNDER >= 52.4% at edge 3+
6. **AUC > 0.55** (classifiers only)
7. *(Soft)* MAE improvement vs baseline — reported but does NOT block

**Why MAE was demoted:** Session 382c discovered a model with MAE 4.12 had HR of only 51.2% because it was biased toward UNDER. MAE measures point accuracy; hit rate measures betting profitability. They are not correlated.

### 4.3 Model Registry

**Files:**
- `bin/model-registry.sh` — CLI for list/validate/sync/compare
- `schemas/model_registry.json` — 28-field schema
- `bin/validation/validate_model_registry.py` — 4 automated checks (duplicates, conflicts, champion presence, GCS files)

**Design:** GCS manifest is source of truth, BQ is queryable cache. SHA256 integrity verification. DML inserts (not streaming) for immediate consistency.

### 4.4 Shadow → Promote → Monitor → Decommission

```
TRAIN (quick_retrain.py)
  → Auto-upload to GCS (SHA256 hash)
  → Auto-register in model_registry (enabled=FALSE)
SHADOW (2+ days)
  → Worker loads enabled models, generates predictions
  → Graded nightly via prediction_accuracy
  → Performance computed daily (model_performance_daily)
  → Profiled across 6 dimensions (model_profile_daily)
PROMOTE
  → Decay-gated promotion (retrain.sh --promote)
  → Deprecate current champion, set new as production
MONITOR
  → Decay detection CF daily 11 AM: state machine HEALTHY→WATCH→DEGRADING→BLOCKED
  → Model-direction affinity blocking
  → Model sanity guard (>95% same-direction)
  → Pipeline canary every 30 min
DECOMMISSION
  → bin/deactivate_model.py: cascade disable
  → Registry + predictions + signal picks + audit trail
```

**Files to study:**
- `bin/retrain.sh` — Automated retraining workflow
- `bin/deactivate_model.py` — Cascade deactivation (registry → predictions → signal picks → audit)
- `ml/signals/model_direction_affinity.py` — Per-model direction blocking
- `ml/analysis/model_profile.py` — Per-model 6-dimension profiling
- `ml/signals/cross_model_scorer.py` — Multi-model consensus scoring

### 4.5 Key Model Lessons (Don't Repeat These Mistakes)

Study the "dead ends" list in CLAUDE.md — it represents months of experimentation. Key themes:

- **Feature quantity over quality hurts** — Adding features to V12 consistently hurt HR (V13, V15, V16, V17, V18 all worse)
- **Quantile regression is non-deterministic** — LightGBM Q55 swung 62%→52% between runs
- **NEVER use in-sample predictions as training data** — 88% apparent vs 56% real HR
- **Edge Classifier (Model 2) adds no value** — AUC < 0.50
- **Two-stage pipelines don't work** — Circular dependency at prediction time
- **Stacked residuals learn noise** — 47.37% HR
- **Models degrade on ~21-day shelf life** — Seasonal pattern changes cause structural decline

---

## Part 5: Monitoring & Operations

### 5.1 Seven-Layer Cross-Model Monitoring

| Layer | Component | What It Catches |
|-------|-----------|-----------------|
| 1 | Model sanity guard (aggregator) | Models with >95% same-direction predictions |
| 2 | Signal exporter disabled model filter | Picks from disabled models |
| 3 | Published picks disabled model detection | Locked picks from disabled models |
| 4 | Phase 9 reconciliation (reconcile-yesterday) | Next-day gap detection |
| 5 | Phase 0.486 validation (validate-daily) | Same-day early warning |
| 6 | Pipeline canary auto-heal (every 30 min) | All phases, auto-heals gaps |
| 7 | Decay detection state machine (daily 11 AM) | Model degradation over time |

### 5.2 Monitoring Scripts

| Script | Schedule | Purpose |
|--------|----------|---------|
| `bin/monitoring/deployment_drift_alerter.py` | Every 2h | Detects undeployed code changes |
| `bin/monitoring/pipeline_canary_queries.py` | Every 30 min | 12 canary checks across all 6 phases |
| `bin/monitoring/analyze_healing_patterns.py` | Every 15 min | Self-healing audit |
| `bin/monitoring/grading_gap_detector.py` | Daily 9 AM | Grading completeness |
| `bin/monitoring/filter_health_audit.py` | On demand | Counterfactual filter analysis |
| `bin/monitoring/model_profile_monitor.py` | Daily | Per-model dimension profiling |

### 5.3 Decay Detection State Machine

```
HEALTHY → WATCH (7d HR < 58%, 2+ days)
WATCH → DEGRADING (7d HR < 55%, 3+ days)
DEGRADING → BLOCKED (7d HR < 52.4%)
BLOCKED → RECOVERED → HEALTHY (7d HR >= 58%)
```

**Three detection modes:**
1. Standard decay — per-model state transitions
2. Cross-model crash — 2+ models below 40% simultaneously = market event, NOT model failure. Pause betting.
3. Front-load — 7d HR consistently 5+ pp below 14d HR. Model was good initially, now degrading.

**File:** `orchestration/cloud_functions/decay_detection/main.py`

### 5.4 Pre-commit Hooks (Prevention)

17 hooks preventing common mistakes:
- Schema alignment (BigQuery fields match code)
- Deploy safety (`--set-env-vars` WIPES all env vars — must use `--update-env-vars`)
- Model reference hardcoding prevention
- Dockerfile dependency validation
- SQL anti-pattern detection

**File:** `.pre-commit-config.yaml`, `.pre-commit-hooks/`

### 5.5 Operational Runbooks

| Runbook | Path |
|---------|------|
| Daily checklist | `docs/02-operations/runbooks/daily-checklist.md` |
| Model steering playbook | `docs/02-operations/runbooks/model-steering-playbook.md` |
| Canary failure response | `docs/02-operations/runbooks/canary-failure-response.md` |
| Feature store monitoring | `docs/02-operations/runbooks/feature-store-monitoring.md` |
| Deployment monitoring | `docs/02-operations/runbooks/deployment-monitoring.md` |

### 5.6 Alert Architecture

| Channel | Frequency | Content |
|---------|-----------|---------|
| `#deployment-alerts` | Every 2h | Deployment drift |
| `#canary-alerts` | Every 30 min | Pipeline canary failures |
| `#nba-alerts` | Varies | Self-healing, grading, decay detection |
| `#app-error-alerts` | On critical | Critical health check failures |
| `#daily-orchestration` | Daily | Health summary |

---

## Part 6: Testing Patterns

### 6.1 Unit Tests

Test structure mirrors source code:
- `tests/unit/signals/test_aggregator.py` — Filter cascade tests with helper factories
- `tests/unit/signals/test_player_blacklist.py` — Blacklist computation
- `tests/unit/signals/test_model_direction_affinity.py` — Direction blocking

**Pattern:** Helper factories (`_make_prediction()`, `_make_signal_result()`) create test fixtures with sensible defaults that pass all filters. Tests modify one parameter at a time to verify each filter independently.

### 6.2 Validation Scripts

| Script | Purpose |
|--------|---------|
| `bin/validation/validate_model_registry.py` | 4 checks: duplicates, conflicts, champion, GCS |
| `bin/validation/validate_workflow_dependencies.py` | Detects workflows monitoring disabled scrapers |
| `bin/validation/validate_cloud_function_imports.py` | Cloud Function shared module presence |

---

## Part 7: Key Documentation to Study

### Must-Read Documents (in order)

1. `CLAUDE.md` — System overview, all conventions, dead ends list
2. `docs/01-architecture/pipeline-design.md` — Six-phase architecture
3. `docs/01-architecture/best-bets-and-subsets.md` — Filter stack, signals, subsets
4. `docs/02-operations/system-features.md` — 9 major system features detailed
5. `docs/02-operations/troubleshooting-matrix.md` — Symptom-based troubleshooting
6. `docs/02-operations/session-learnings.md` — Historical bug fixes and patterns
7. `docs/06-reference/scrapers/00-SCRAPER-INVENTORY.md` — All scrapers catalog
8. `docs/06-reference/data-flow/01-13` series — Phase-by-phase data transformations

### Project-Specific Deep Dives

| Project Doc | What You'll Learn |
|-------------|-------------------|
| `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md` | Multi-model aggregation design |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | All 21 active + 24 disabled signals |
| `docs/08-projects/current/zero-tolerance-defaults/` | Why and how zero-tolerance works |
| `docs/08-projects/current/fleet-lifecycle-automation/00-PLAN.md` | Model fleet automation plan |
| `docs/08-projects/current/session-368-experiment-matrix/00-FINDINGS.md` | Cross-season experiment results |

### Session Handoffs (System Evolution)

The `docs/09-handoff/` directory contains 250+ session handoffs showing how the system evolved. Key ones to understand architectural decisions:

| Session | Key Contribution |
|---------|-----------------|
| 297 | Edge-first architecture (replaced signal scoring) |
| 334 | Model registry validation, hardcoded reference prevention |
| 348 | Signal density filter, signal count floor |
| 352 | Edge floor lowered to 3.0, Cloud Build image push fix |
| 357 | V16 features, feature store schema v2_57features |
| 365 | Model HR-weighted selection, AWAY block expansion |
| 370 | Signal count raised to 3, adversarial validation |
| 374b | Line movement signals, opponent blocks |
| 378c | Model sanity guard (XGBoost version mismatch) |
| 382 | Ultra bets 2-criterion gate |
| 386 | Cascade model deactivation |
| 387 | Silent signal failure detection |
| 388 | Edge-tiered signal count, auto-deploy cascade diagnosis |

---

## Part 8: MLB-Specific Considerations

### 8.1 What Transfers Directly

| NBA Component | MLB Equivalent | Notes |
|---------------|----------------|-------|
| Six-phase pipeline | Same architecture | Phases 1-6 identical pattern |
| Feature contract | MLB feature contract | Different features, same contract pattern |
| Quality scoring | Same system | Same zero-tolerance approach |
| Signal system | MLB signals | Different signals, same BaseSignal pattern |
| Filter stack | MLB filter stack | Different filters, same aggregator pattern |
| Model registry | Same system | Already supports multi-sport |
| Decay detection | Same system | Same state machine, different thresholds |
| Monitoring | Same infrastructure | Same canaries, different queries |
| Pre-commit hooks | Same hooks | Already sport-agnostic |
| Coordinator/Worker | Same architecture | MLB stubs exist |

### 8.2 What Needs MLB-Specific Design

**Pitcher Strikeouts:**
- Features: K rate last 5/10 starts, pitch mix (fastball/slider/curve %), swinging strike rate, opponent lineup K rate, park K factor, weather (wind/temp), bullpen rest, platoon splits (L/R matchup %), innings pitch count, days rest
- Signals: High K rate OVER, weak lineup OVER, pitcher's park OVER, short rest UNDER, high pitch count last start UNDER
- Filters: Opener/bullpen games, shortened starts, blowout risk, weather extremes

**Team Betting:**
- Features: Moneyline, run line, total (over/under), starting pitcher quality, bullpen strength, offensive metrics (OPS, wOBA), park factors, umpire tendencies, head-to-head history, travel/rest
- Signals: Pitching matchup advantage, home field + ace, bullpen availability, lineup quality
- Filters: Weather postponement risk, key injury impact, interleague disadvantage

### 8.3 Existing MLB Infrastructure

The NBA codebase already has MLB stubs:

```
scrapers/mlb/                           # 27+ MLB scraper stubs
data_processors/raw/mlb/                # 10 raw processors
data_processors/analytics/mlb/          # Batter/pitcher analytics
data_processors/precompute/mlb/         # Pitcher features, lineup analysis
predictions/mlb/                        # Worker, predictor, shadow mode
data_processors/publishing/mlb/         # Best bets, predictions, results exporters
data_processors/grading/mlb/            # Grading processor
orchestration/cloud_functions/mlb_*/    # Phase orchestrators
schemas/bigquery/mlb_*/                 # BQ schemas
shared/config/sports/mlb/teams.py       # Team configuration
```

### 8.4 Recommended Build Order for MLB

1. **Data first:** Get scrapers working and raw data flowing into BigQuery
2. **Analytics:** Build pitcher_game_summary and team_game_summary
3. **Feature store:** Design MLB feature contract, implement feature extraction
4. **Baseline model:** Train a simple CatBoost on pitchers strikeouts (same quick_retrain.py, new feature set)
5. **Best bets:** Implement MLB aggregator with basic filters (start simple — edge floor + quality floor only)
6. **Grading:** Grade predictions against actuals
7. **Signals:** Add signals one at a time, validated against historical data
8. **Monitoring:** Extend existing canaries for MLB phase checks
9. **Iterate:** The NBA system's filter stack evolved over 100+ sessions. Start simple, add complexity only when data supports it.

---

## Part 9: Code Patterns to Replicate

### 9.1 BigQuery Write Pattern

```python
# ALWAYS batch, NEVER streaming inserts
from shared.utils.bigquery_batch_writer import get_batch_writer
writer = get_batch_writer(table_id)
writer.add_record(record)  # Auto-batches at 100 records or 30s timeout
```

### 9.2 Feature Contract Pattern

```python
# shared/ml/feature_contract.py
@dataclass
class ModelFeatureContract:
    model_version: str
    feature_count: int
    feature_names: List[str]
    description: str

    def validate(self) -> bool: ...
    def extract_from_dict(self, row: dict) -> List[float]: ...
```

### 9.3 Signal Pattern

```python
# ml/signals/your_signal.py
class YourSignal(BaseSignal):
    def evaluate(self, prediction, features, supplemental) -> SignalResult:
        if meets_criteria(prediction, supplemental):
            return SignalResult(qualifies=True, confidence=0.7, source_tag='your_signal')
        return self._no_qualify()
```

### 9.4 Filter Pattern (in Aggregator)

```python
# Cheapest checks first, most expensive last
if some_condition:
    filter_counts['your_filter'] += 1
    continue
```

### 9.5 Governance Gate Pattern

```python
# All gates must pass
gates = [
    ('hit_rate', hr >= 0.60, f'{hr:.1%}'),
    ('sample_size', n >= 25, f'N={n}'),
    ('vegas_bias', abs(bias) <= 1.5, f'{bias:+.2f}'),
    ...
]
all_passed = all(passed for _, passed, _ in gates)
```

---

## Part 10: What Makes This System Work

After 388+ sessions, the three things that matter most:

1. **The filter stack catches what models miss.** Models are ~55% accurate at raw prediction level. The filter stack lifts that to 65-76% by removing the patterns where models systematically fail. This is where the actual money is made.

2. **Monitoring prevents silent failures.** Models degrade, signals die, features drift. The 7-layer monitoring stack catches these before they cost money. The signal firing canary (Session 387) was added after two 80%+ HR signals were dead for weeks undetected.

3. **Dead-end documentation prevents wasted effort.** The CLAUDE.md dead-ends list and 250+ handoff documents represent months of experimentation. Every approach that failed is documented with session number, HR data, sample size, and reasoning. This is arguably the most valuable part of the system.

**The same principles will work for MLB.** The sport-specific details (features, signals, filters) will be different, but the architecture, governance, monitoring, and operational practices should be replicated exactly.
