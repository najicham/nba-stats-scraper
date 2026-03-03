# Improvements & Future Enhancements

> **Purpose:** Gaps in the current replication docs, improvements to the NBA system that should be carried forward, and MLB-specific design decisions that need to be made before building.

---

## 1. Gaps in the Current Replication Docs

These are things a new chat would struggle with that aren't covered well enough in docs 00 and 01.

### 1.1 The Bootstrap Problem

**What's missing:** How to validate signals and filters when you have zero historical predictions.

**How NBA solved it:**
- Days 0-6 of each season: Phase 4 skips entirely (no feature store records)
- Day 7+: Partial rolling windows with `early_season_flag=TRUE` metadata
- Cross-season data intentionally excluded (24% of players changed teams, 0.91 MAE worse)
- Quality floor (`quality_score < 85`) naturally blocks predictions with insufficient history

**MLB implication:** MLB has a 162-game season starting late March. The first 2 weeks will have no rolling averages. The bootstrap period document exists at `docs/01-architecture/bootstrap-period-overview.md` — study it before designing MLB features.

**For signal/filter bootstrapping specifically:**
1. Train initial model on 2+ seasons of historical data (backfill feature store first)
2. Generate historical predictions by running the model over past seasons
3. Grade those predictions against actual outcomes
4. THEN discover signals and filters from this historical prediction set
5. Don't try to discover signals from live data until you have 30+ days of predictions

### 1.2 The Backfill Architecture

**What's missing:** How to load historical data when building from scratch.

**How NBA solved it:** Phase-by-phase backfill, NOT date-by-date.

**Golden rule:** Run ALL dates for Phase 2 → ALL dates for Phase 3 → Phase 4 → Phase 5. Phase 4 needs 30-day lookback windows — running date-by-date fails when prior dates haven't been processed.

**Key files:**
- `docs/02-operations/backfill/backfill-guide.md` — 6 scenarios with step-by-step instructions
- `docs/02-operations/backfill/backfill-mode-reference.md` — What changes in backfill mode
- `bin/backfill/preflight_check.py` — Validates upstream data before backfill
- `scripts/validate_backfill_coverage.py` — Checks player-level coverage after

**MLB already has backfill stubs:**
- `scripts/mlb/backfill_pitcher_splits.py`
- `scripts/mlb/backfill_statcast_game_stats.py`
- `scripts/mlb/backfill_mlb_schedule.py`
- `scripts/mlb/backfill_fangraphs_stats.py`
- `scripts/mlb/historical_odds_backfill/` — parallel odds backfill infrastructure

### 1.3 Cost Management

**What's missing:** How to keep GCP costs manageable.

**Key patterns (from `docs/02-operations/COST-OPTIMIZATION.md`):**

| Strategy | Impact | Implementation |
|----------|--------|----------------|
| Partition by game_date | 90%+ query cost reduction | All BigQuery tables |
| Batch loading (not streaming) | Free vs $0.05/GB | `bigquery_batch_writer.py` |
| GCS lifecycle policies | $4,200/year savings | Nearline at 30d, delete at 90d |
| Query caching | 24-hour free cache | Identical parameterized queries |
| Cloud Run min-instances | Prevent cold starts on critical services | Coordinator/orchestrators = 1, others = 0 |

**MLB cost estimate:** Initial backfill will be the most expensive operation. Budget ~$50-100 for the first full-season backfill (BigQuery loads + queries). Ongoing daily costs should be similar to NBA (~$5-10/day).

### 1.4 Error Handling & Recovery Patterns

**What's missing:** How errors flow through the pipeline and how the system recovers.

**Five-layer error architecture:**

1. **ErrorContext** (`shared/utils/error_context.py`) — Decorator/context manager for structured logging with auto-captured metadata (batch_id, game_date, duration_ms)
2. **Alert type system** (`shared/utils/alert_types.py`) — 17 types across 5 severities (CRITICAL/ERROR/WARNING/INFO/SUCCESS) with auto-detection from error messages
3. **Rate limiting** (`shared/utils/processor_alerting.py`) — 15-minute cooldown per alert type per processor to prevent spam
4. **Backfill mode** (`shared/utils/smart_alerting.py`) — Queues errors during bulk operations, sends single summary at end
5. **Circuit breaker** (`shared/config/circuit_breaker_config.py`) — Opens after N failures, prevents cascading failures

**Key pattern for MLB:** Use `@with_error_context` decorator on every function that touches external services:
```python
@with_error_context("load_pitcher_stats", alert_on_failure=True)
def load_pitcher_stats(self, game_date):
    ...
```

### 1.5 The Experiment Framework

**What's missing:** How to run controlled model experiments.

**`ml/experiments/quick_retrain.py`** is a 4,500-line CLI with 50+ flags:
- `--feature-set v12_noveg` — Choose feature version
- `--no-vegas` — Remove vegas features (4 features)
- `--category-weight vegas=0.25` — Downweight feature categories
- `--training-window 42` — Rolling window in days
- `--eval-start 2026-02-01` — Evaluation period start
- `--machine-output results.json` — Structured output for grid search
- `--skip-register` — Don't auto-register (for experiments)

**Grid search:** `bin/grid_search_weights.py` wraps quick_retrain with `--machine-output` to sweep hyperparameters.

**Results stored in:** `ml/experiments/results/` with model artifacts + metadata JSON + detailed evaluation.

**For MLB:** Fork `quick_retrain.py` into `ml/experiments/mlb_quick_retrain.py`. Keep the governance gates, feature contract integration, and evaluation framework. Change the feature set, data loading, and grading logic.

### 1.6 Configuration Management

**What's missing:** How configs are managed across environments.

**Three-tier pattern:**
1. **Feature flags** (`shared/config/feature_flags.py`) — Env var-driven booleans, all default False
2. **Resilience configs** — Retry profiles (fast/standard/patient), circuit breaker thresholds, rate limits
3. **Dynamic configs** — Timeouts per operation type, dependency chains between phases

**Key principle:** Environment variables always override defaults. Functions like `_get_env_int()` handle type conversion with fallback.

**For MLB:** Extend existing configs — don't create separate MLB config files. The `shared/config/sports/mlb/teams.py` already exists with all 30 teams.

---

## 2. Improvements to the NBA System (Carry Forward to MLB)

These are things we've learned from 388+ sessions that should be built into the MLB system from day one, not discovered painfully later.

### 2.1 Build Signal Firing Canary from Day One

**NBA pain:** Two 80%+ HR signals (`line_rising_over`, `fast_pace_over`) died silently for weeks. `line_rising_over` depended on a champion model query that went NULL when the champion was decommissioned. `fast_pace_over` had a threshold on raw scale applied to normalized (0-1) data.

**MLB action:** Every signal should have a firing rate assertion from the start. If a signal that normally fires on 10% of predictions drops to 0%, alert immediately.

**Implementation:** The canary already exists in `ml/signals/signal_health.py` — just make sure MLB signals are registered in it.

### 2.2 Build Counterfactual Filter Audit from Day One

**NBA pain:** Filters were added one at a time over 100+ sessions. Some became stale as rosters changed. The counterfactual audit (`bin/monitoring/filter_health_audit.py`) was added late.

**MLB action:** Every filter should be auditable from day one. For each filter, track:
- Blocked predictions count
- Blocked predictions actual HR (would they have won?)
- P&L impact of the filter

### 2.3 Use Affinity Groups, Not Per-Model Filters

**NBA learning (Sessions 384-385):** All 5 decision gates for per-model filtering returned NO-GO. Models within the same group make identical predictions on the same players. Group-level filtering (4 groups) is the right abstraction.

**MLB action:** Start with 1-2 model groups. Don't build per-model filtering infrastructure until you have 10+ models AND evidence that groups behave differently.

### 2.4 Document Dead Ends Immediately

**NBA strength:** The CLAUDE.md dead-ends list is arguably the most valuable part of the system. Every experiment that failed is documented with session number, HR data, sample size, and reasoning.

**MLB action:** Start a dead-ends section in the MLB CLAUDE.md from session 1. Every failed experiment gets documented immediately, not retroactively.

### 2.5 Test Feature Normalization Consistency

**NBA pain:** Feature 18 (opponent_pace) is stored as normalized 0-1 in the feature store, but a signal threshold was set to 102.0 (raw scale). The signal could mathematically never fire.

**MLB action:** Add an assertion in every signal that uses feature store values: verify the value is in expected range (0-1 for normalized, or document the raw range).

### 2.6 Don't Auto-Deploy Everything

**NBA pain (Session 388):** A docs-only commit triggered auto-deploy, which picked up undeployed code changes for V17/V18 features. Four bugs cascaded: BQ schema mismatch, quality scorer cap, feature version rejection, missing PyYAML dependency.

**MLB action:** Separate deploy triggers for MLB services. Consider gating deploys behind a `[deploy]` commit message tag or manual approval for the first few months.

### 2.7 Model Sanity Guard from Day One

**NBA pain (Session 378c):** An XGBoost version mismatch caused all predictions to be ~8.6 points too low — 100% UNDER with inflated edges. The model dominated best bets via fake high-edge picks.

**MLB action:** The sanity guard already exists in the aggregator (`>95% same-direction blocks model`). Ensure MLB uses the same guard. Also add version pinning in training AND production environments.

---

## 3. MLB-Specific Design Decisions Needed

These decisions should be made before writing code. Each has trade-offs that need discussion.

### 3.1 Pitcher Strikeouts: What's the "Line"?

**NBA:** Line = sportsbook prop line (e.g., 25.5 points). One line per player per game.

**MLB options:**
- **Strikeout prop line** (e.g., 6.5 Ks) — Most direct equivalent. Available from DraftKings, FanDuel, etc.
- **Strikeout total** (e.g., 7.0) — Season projection pro-rated to game. Less volatile.
- **Multiple props per pitcher** — Ks, innings pitched, hits allowed, earned runs. More volume but more complexity.

**Recommendation:** Start with strikeout prop lines only. It's the closest NBA equivalent and the most liquid betting market. Add innings/hits/ERA props later if the system works.

### 3.2 Team Betting: What Markets?

**NBA:** Player points over/under only (one market).

**MLB team betting options:**
- **Moneyline** (who wins) — Simplest but requires different edge calculation (no line to compare against)
- **Run line** (spread, usually -1.5/+1.5) — Most similar to NBA points spread, but less liquid
- **Game total** (over/under runs) — Most similar to NBA player props architecture
- **First 5 innings** (F5) — Isolates starting pitcher, removes bullpen variance

**Recommendation:** Start with game total over/under. The existing architecture (predicted value vs line → edge → filters → best bets) transfers directly. Moneyline requires a fundamentally different edge calculation (implied probability vs odds, not points vs line).

### 3.3 Feature Store: What Features?

**NBA:** 54 features across 9 categories. The feature contract defines everything.

**MLB pitcher strikeout features to design (suggested starting set):**

| Category | Features | Source |
|----------|----------|--------|
| Recent performance | K rate L5/L10, K/9 L5/L10, avg Ks per start L5/L10 | Pitcher game logs |
| Pitch quality | Swinging strike rate, chase rate, zone rate | Statcast |
| Opponent quality | Opponent K rate, lineup K rate vs LHP/RHP | Team stats |
| Park factors | Park K factor, park run factor | FanGraphs |
| Game context | Home/away, day/night, weather (temp, wind, humidity) | Schedule + weather API |
| Rest/workload | Days rest, pitch count last start, innings last 30d | Pitcher logs |
| Platoon | % batters same-hand, % batters opposite-hand in lineup | Lineups |
| Bullpen | Team bullpen rest, bullpen ERA last 7d | Team stats |
| Historical | Career K rate vs this opponent, this park | Historical logs |
| Vegas | Prop line, game total, moneyline implied probability | Odds API |

**Start with 20-25 features, not 54.** NBA V12_noveg (50 features) consistently beats V13-V18 (52-60 features). Feature quantity hurts.

### 3.4 Training Data: How Much History?

**NBA:** 42-56 day rolling window. Older data dilutes signal as rosters/rotations change.

**MLB considerations:**
- MLB seasons are 6 months (April-October), not 7 months like NBA (October-April)
- Pitchers face the same teams repeatedly within divisions (19 games vs same team)
- Pitcher performance has more variance than NBA player points (fewer data points per pitcher per week)
- Cross-season data may be MORE useful in MLB (pitchers change teams less often)

**Recommendation:** Start with 60-day rolling window. MLB has fewer games per week per pitcher (1-2 vs 3-4 for NBA players), so you need a wider window to get enough training samples. Experiment with 42d/60d/90d once you have data.

### 3.5 Retraining Cadence

**NBA:** 7-day cadence, 42-day window. Models have ~21-day shelf life.

**MLB considerations:**
- Pitchers change more slowly than NBA players (less injury churn, rotation more stable)
- But trades and call-ups cause sudden shifts mid-season
- Weather changes dramatically through the season (April cold → July hot)

**Recommendation:** Start with 14-day cadence, 60-day window. MLB changes more slowly within-season. Reduce to 7-day if decay detection triggers frequently.

### 3.6 When to Start

**NBA season:** October-April. **MLB season:** March-October. They barely overlap.

**This is a feature, not a bug.** You can use NBA off-season (May-September) to build, backfill, and test the MLB system against historical data. By the time NBA starts again in October, the MLB system should be running.

**Recommended timeline:**
1. **March-April:** Build scrapers, raw processors, start collecting live data
2. **May-June:** Build analytics, feature store, train initial models
3. **June-July:** Deploy to shadow mode, start grading predictions
4. **July-August:** Discover signals and filters from accumulated data
5. **August-September:** Go live with best bets, iterate on filter stack
6. **October:** MLB playoffs + NBA season start — both systems running

---

## 4. Cross-Sport Infrastructure Improvements

Things that should be built once and shared between NBA and MLB.

### 4.1 Sport-Agnostic Model Registry

The current model registry (`schemas/model_registry.json`) has NBA-specific fields. Extend it:
- Add `sport` field (nba/mlb)
- Add `market_type` field (player_points/pitcher_strikeouts/game_total)
- Keep all governance gates — they're sport-agnostic

### 4.2 Sport-Agnostic Decay Detection

The decay state machine (HEALTHY→WATCH→DEGRADING→BLOCKED) works for any sport. Parameterize thresholds:
- NBA breakeven: 52.4% (at -110 odds)
- MLB strikeout props breakeven: 52.4% (same odds typically)
- MLB moneyline breakeven: varies by odds (would need different calculation)

### 4.3 Unified Alerting

One Slack workspace, sport-specific channels:
- `#nba-alerts`, `#mlb-alerts` (per-sport)
- `#deployment-alerts` (shared — one deploy pipeline)
- `#canary-alerts` (shared — one canary framework, sport-specific checks)

### 4.4 Shared Feature Engineering Patterns

The `feature_contract.py` pattern (versioned feature definitions, quality scoring, zero-tolerance defaults) should be reused exactly. Create:
- `shared/ml/mlb_feature_contract.py` — MLB feature versions
- Keep `shared/ml/feature_contract.py` for NBA
- Both use the same `quality_scorer.py` framework

### 4.5 Shared Publishing Infrastructure

Phase 6 exporters follow a consistent pattern. The GCS API bucket should be:
```
gs://nba-props-platform-api/v1/         # NBA (existing)
gs://nba-props-platform-api/v1/mlb/     # MLB (new)
  ├── best-bets/{date}.json
  ├── tonight/all-pitchers.json
  └── results/{date}.json
```

Or create a separate bucket if you want independent lifecycle policies.

---

## 5. Things NOT to Build for MLB

Lessons from NBA about what to skip.

### 5.1 Don't Build Multi-Model Fleet Initially

**NBA:** 15+ models running simultaneously. This evolved over 100+ sessions. Start with 1 model for MLB. Add a second only when you have evidence the first is degrading.

### 5.2 Don't Build Ultra Bets Initially

**NBA:** Ultra bets require 50+ graded picks to validate. You won't have enough data for months. Add ultra classification after you have 2+ months of graded best bets.

### 5.3 Don't Build Per-Model Profiling

**NBA (Sessions 384-385):** All 5 decision gates returned NO-GO. Per-model profiling is only useful with 15+ models and 6+ months of data. Skip for MLB year one.

### 5.4 Don't Over-Engineer Signals

**NBA:** 21 active signals, 24 dead. Most value comes from 5-6 signals. Start with 3-4 MLB signals:
1. `high_edge` — Universal, direction-agnostic
2. `high_k_rate_over` — Recent K rate significantly above season average
3. `weak_lineup_over` — Opponent lineup K rate in top quartile
4. `rest_advantage_under` — Pitcher on short rest (4 days) with high recent pitch count

Add more only when you have data to validate them.

### 5.5 Don't Build Complex Filter Stack Initially

**NBA:** 14+ negative filters evolved over 100+ sessions. Start MLB with 3 filters:
1. Edge floor (>= 3.0)
2. Quality floor (>= 85)
3. Signal count (>= 3)

Add filters one at a time as data reveals systematic failure patterns.

---

## 6. Recommended Study Order for a New Chat

If a new chat is going to build the MLB system, they should study in this order:

1. **This doc** (02-IMPROVEMENTS) — Know what to build and what to skip
2. **00-SYSTEM-OVERVIEW.md** — Understand the full NBA architecture
3. **01-MODELS-FILTERS-MONITORING.md** — Understand measurement and validation
4. **CLAUDE.md** — The complete system reference (especially dead ends)
5. **`shared/ml/feature_contract.py`** — The feature contract pattern
6. **`ml/signals/aggregator.py`** — The filter stack (THE most important file)
7. **`ml/experiments/quick_retrain.py`** — The training pipeline
8. **`scrapers/mlb/`** — Existing MLB scraper stubs
9. **`predictions/mlb/`** — Existing MLB prediction stubs
10. **`docs/02-operations/backfill/backfill-guide.md`** — How to load historical data

Then start building: scrapers → raw processors → analytics → feature store → model → best bets → grading → signals → monitoring.
