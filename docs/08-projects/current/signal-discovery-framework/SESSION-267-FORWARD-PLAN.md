# Session 267 — System Review & Forward Plan

**Date:** 2026-02-15
**Status:** Comprehensive review of replay, signals, subsets, and Phase 6 exports
**Games resume:** Feb 19 (All-Star break ends)

---

## 1. System Architecture — How It All Fits Together

### The Three Systems

| System | Purpose | Status |
|--------|---------|--------|
| **Replay Engine** | Test decision strategies against historical data | BUILT, validated |
| **Signal Framework** | Curate "Best Bets" from multiple signal sources | LIVE in Phase 6 |
| **Dynamic Subsets** | Filter predictions into audience-facing groups | LIVE, exported to website |

### Data Flow (Phase 5 → Phase 6 → Website)

```
Phase 5 Predictions
    ↓
Phase 6 Export (daily_export.py)
    ├── Step 1: SubsetMaterializer → current_subset_picks (BQ)
    │     Filters predictions into 26 subsets across 4 models
    │     (Top Pick, Top 3, Top 5, High Edge, Green Light, etc.)
    ├── Step 2: SignalAnnotator → pick_signal_tags (BQ)
    │     Evaluates 7+ signals on ALL predictions
    │     Bridges top 5 → current_subset_picks as "Best Bets" (subset 26)
    ├── Step 3: AllSubsetsPicksExporter → picks/{date}.json (GCS)
    │     LEFT JOINs signal tags onto every pick
    │     Grouped by model_groups → subsets → picks
    ├── Step 4: SignalBestBetsExporter → signal-best-bets/{date}.json (GCS)
    │     Curated top 5 with full signal detail + model health gate
    └── Other exports (tonight, results, performance, trends, etc.)
```

---

## 2. Best Bets Subset — How Picks Are Selected

### Current Selection Logic (`BestBetsAggregator`)

**Input:** All active predictions for the best bets model (currently `catboost_v9`, overridable via `BEST_BETS_MODEL_ID` env var)

**Filters (sequential):**
1. Must have 2+ qualifying signals (`MIN_SIGNAL_COUNT = 2`)
2. Must pass confidence floor (V12: >= 0.90, V9: no floor)
3. Must NOT match an ANTI_PATTERN combo from registry
4. Model health gate: entire output blocked if 7d HR < 52.4%

**Scoring formula:**
```
edge_score = min(1.0, abs(edge) / 7.0)     # capped at 7 pts
effective_signals = sum of health-weighted signals (capped at 3.0)
    HOT signal: 1.2x contribution
    NORMAL signal: 1.0x contribution
    COLD behavioral: 0.5x contribution
    COLD model-dependent: 0.0x contribution (Session 264)
signal_multiplier = 1.0 + 0.3 * (effective_signals - 1)  # max 1.6x
base_score = edge_score * signal_multiplier
composite_score = base_score + combo_registry_weight (SYNERGISTIC bonus)
```

**Output:** Top 5 picks ranked by composite_score

### Signal Roster (7 active + 1 gate)

| Signal | Type | Category | Description |
|--------|------|----------|-------------|
| `model_health` | GATE | System | Blocks all picks when 7d HR < 52.4% |
| `high_edge` | Pick | Model-dependent | Edge >= 5.0 points |
| `edge_spread_optimal` | Pick | Model-dependent | Edge spread in optimal range |
| `minutes_surge` | Pick | Behavioral | Recent minutes increase suggests expanded role |
| `cold_snap` | Pick | Behavioral | Player cold, regression-to-mean expected |
| `3pt_bounce` | Pick | Behavioral | 3PT shooter bouncing back |
| `blowout_recovery` | Pick | Behavioral | Recovery after blowout game |
| `dual_agree` | Pick | Model-dependent | V9 and V12 agree on direction |

### Signal Health Weighting (Session 260, updated 264)

Signal health is computed daily from `signal_health_daily` table:
- **HOT** (7d HR > season HR + 10pp): Signal weight 1.2x
- **NORMAL**: Signal weight 1.0x
- **COLD** (7d HR < season HR - 10pp):
  - Model-dependent signals → **0.0x** (broken model = broken signal)
  - Behavioral signals → **0.5x** (reduced but not zeroed)

### Combo Registry (7 combos)

| Combo | Classification | Hit Rate |
|-------|---------------|----------|
| high_edge + minutes_surge | SYNERGISTIC | 87.5% |
| edge_spread + high_edge + minutes_surge | SYNERGISTIC | 100% (N=11) |
| high_edge + prop_value_gap_extreme | SYNERGISTIC | 88.9% |
| 3pt_bounce + blowout_recovery | SYNERGISTIC | 100% (N=7) |
| combo_he_ms (pre-computed) | SYNERGISTIC | ~87% |
| edge_spread + high_edge | ANTI_PATTERN | 31.3% |
| (other anti-pattern) | ANTI_PATTERN | — |

**Status: FROZEN** — validate on post-Feb-19 out-of-sample data before changes.

---

## 3. Phase 6 Exports — What Goes to the Website

### Current GCS Structure

```
gs://nba-props-platform-api/v1/
├── picks/{date}.json                  # All subsets + signal tags per pick
├── signal-best-bets/{date}.json       # Curated top 5 with signal detail
├── results/{date}.json                # Graded results with actuals
├── performance/latest.json            # System performance metrics
├── best-bets/{date}.json              # Legacy best bets (pre-signal)
├── tonight/{date}.json                # All players for tonight's games
├── tonight-players/{player}.json      # Individual player detail
├── daily-signals/{date}.json          # Daily signal (pct_over, direction)
├── systems/subsets.json               # Subset definitions
├── systems/subset-performance.json    # W-L records per subset
├── schedule/game-counts.json          # Calendar data
├── trends/tonight/{date}.json         # Consolidated trends
└── ...other exports
```

### What's Already Exported

**`picks/{date}.json`** — The main export. Structure:
```json
{
  "date": "2026-02-10",
  "version": 2,
  "model_groups": [
    {
      "model_id": "926A",
      "model_name": "V9 Champion",
      "subsets": [
        {
          "id": "1", "name": "Top Pick",
          "record": {"season": {...}, "month": {...}, "week": {...}},
          "picks": [
            {
              "player": "LeBron James",
              "team": "LAL",
              "prediction": 27.5,
              "line": 24.5,
              "direction": "OVER",
              "edge": 3.0,
              "signals": ["high_edge", "minutes_surge"],
              "signal_count": 2,
              "combo": "SYNERGISTIC"
            }
          ]
        },
        {"id": "26", "name": "Best Bets", "picks": [...]}  // Signal-curated top 5
      ]
    }
  ]
}
```

**Key:** Signal tags are already LEFT JOINed onto every pick in every subset. The "Best Bets" subset (id=26) is materialized alongside all other subsets. No additional export work needed for signal visibility.

**`signal-best-bets/{date}.json`** — Detailed signal analysis:
```json
{
  "date": "2026-02-10",
  "model_health": {"status": "healthy", "hit_rate_7d": 63.2},
  "picks": [
    {
      "rank": 1,
      "player": "LeBron James",
      "signals": ["high_edge", "minutes_surge"],
      "composite_score": 1.23,
      "combo": "high_edge+minutes_surge",
      "combo_classification": "SYNERGISTIC"
    }
  ]
}
```

### What's NOT Yet Exported (Gaps)

1. **Signal health data** — `signal_health_daily` (per-signal HOT/COLD/NORMAL regime) is in BQ but NOT exported to GCS. The website can't show signal health badges.

2. **Model performance data** — `model_performance_daily` (rolling HR, state machine) is in BQ but NOT exported to GCS. The website can't show model health status.

3. **Decay state** — The website has no way to know if the model is HEALTHY/WATCH/DEGRADING/BLOCKED. Could display a banner.

4. **Combo registry** — Available in BQ (`signal_combo_registry`) but not exported. Website can't explain why certain combos are good/bad.

---

## 4. Replay System — Architecture & Forward Plan

### 4 Strategies Validated

| Strategy | Logic | HR | ROI | P&L | Best For |
|----------|-------|-----|-----|------|----------|
| **Threshold** | State machine: block when < 52.4%, switch to challengers | **69.1%** | **31.9%** | $3,400 | **Production** |
| Conservative | Block only after 5 consecutive days below breakeven | 67.0% | 27.8% | $3,520 | Noise reduction |
| Oracle | Perfect hindsight — best model each day | 62.9% | 20.0% | $3,680 | Theoretical ceiling |
| BestOfN | Pick highest rolling 7d HR model each day | 59.5% | 13.6% | $2,360 | Upper bound |

**Key finding:** Blocking bad days > picking the best model. Threshold strategy wins on ROI.

### Threshold Validation (Session 265)

- **58/55/52.4 thresholds validated** across V8's 4-season history
- **0.13% false positive rate** (1 BLOCKED day in 780 healthy game days)
- The single false positive was All-Star break gap + bad day collision
- **No seasonal trade deadline dip** — 2025-26 drop is genuine decay
- **Recommendation: Keep thresholds as-is**

### Forward Plan for Replay

The replay system is complete for analysis purposes. No production integration needed because:
- **Decay detection CF** already implements the Threshold strategy's state machine in production
- **model_performance_daily** already tracks the same metrics
- Replay CLI remains valuable for testing threshold adjustments and evaluating new models

**Optional enhancement:** Add `--signal-filter` to replay CLI to test "only take picks with 2+ signals" vs "take all edge 3+ picks" historically.

---

## 5. Backfill Assessment

### What Should Be Backfilled?

| Data | Status | Backfill Needed? | Rationale |
|------|--------|-----------------|-----------|
| **Best Bets subset (id=26)** | Materialized daily since Session 254 (~Feb 14) | **YES for grading** | Only ~1 day of data. Need historical best bets for performance tracking. |
| **pick_signal_tags** | Backfilled 35 dates (Session 255) | **Extend to full season** | Enables full-season signal performance analysis |
| **signal_health_daily** | Backfilled Jan 9 - Feb 14 | **Already sufficient** | Pre-season data doesn't help (different model) |
| **model_performance_daily** | 47 rows backfilled | **Already sufficient** | Auto-populated by post_grading_export going forward |
| **signal-best-bets JSON** | Only recent dates | **YES** | Website needs historical signal best bets for track record display |
| **Signal health JSON** | Not exported | **No (new export)** | Build export first, then consider backfill |

### Backfill Recommendations

**Priority 1: Best Bets subset backfill (BQ)**
```bash
# Backfill best_bets subset into current_subset_picks for grading
# This requires running SignalAnnotator._bridge_signal_picks() for historical dates
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --backfill-range 2026-01-09 2026-02-14 --only subset-picks
```
This would re-materialize subsets + annotate signals + bridge best bets picks for all historical dates with graded predictions. The SubsetGradingProcessor would then grade the "Best Bets" subset.

**Priority 2: Signal best bets JSON backfill (GCS)**
```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --backfill-range 2026-01-09 2026-02-14 --only signal-best-bets
```
Populates GCS with historical `signal-best-bets/{date}.json` files for the website.

**Priority 3: Pick signal tags extension (BQ)**
Already backfilled 35 dates. If we want full-season coverage, extend:
```bash
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --backfill-range 2025-11-02 2026-01-08 --only subset-picks
```
Note: Pre-Jan 9 dates will have fewer signals (signal framework was calibrated on Jan 9+ data). Results are still useful for trend analysis.

### What Should NOT Be Backfilled

- **Combo registry** — FROZEN, doesn't change per day
- **Signal health beyond Jan 9** — Pre-season data uses different model, signals are meaningless
- **Model performance beyond current backfill** — Already sufficient

---

## 6. New Exports to Build

### Export 1: Signal Health Summary (NEW)

**Path:** `v1/systems/signal-health.json`
**Trigger:** Daily, during Phase 6 export
**Content:**
```json
{
  "date": "2026-02-19",
  "generated_at": "...",
  "signals": {
    "high_edge": {"regime": "HOT", "hr_7d": 75.0, "hr_season": 62.3, "is_model_dependent": true},
    "minutes_surge": {"regime": "NORMAL", "hr_7d": 55.0, "hr_season": 53.7, "is_model_dependent": false},
    "cold_snap": {"regime": "COLD", "hr_7d": 30.0, "hr_season": 64.3, "is_model_dependent": false}
  }
}
```
**Website use:** Signal health badges (green/yellow/red dots), signal performance cards.

### Export 2: Model Health Status (NEW)

**Path:** `v1/systems/model-health.json`
**Trigger:** Daily, during Phase 6 export
**Content:**
```json
{
  "date": "2026-02-19",
  "generated_at": "...",
  "best_bets_model": "catboost_v12",
  "models": {
    "catboost_v9": {"state": "BLOCKED", "hr_7d": 39.9, "hr_14d": 42.1, "days_since_training": 38},
    "catboost_v12": {"state": "HEALTHY", "hr_7d": 56.0, "hr_14d": 55.2, "days_since_training": 15}
  }
}
```
**Website use:** Model health banner (green/yellow/red), confidence indicator, "we're sitting out today" messaging when BLOCKED.

### Export 3: Combo Registry (NEW, optional)

**Path:** `v1/systems/combo-registry.json`
**Trigger:** Static (only changes when registry changes)
**Content:** Combo definitions + historical hit rates
**Website use:** Tooltip explaining "Why is this a Best Bet?" (e.g., "This pick has the high_edge + minutes_surge combo, which historically hits 87.5%")

---

## 7. Forward Roadmap

### Feb 19 (Games Resume)

- [ ] Run `/validate-daily` morning check — verify all monitoring works
- [ ] Verify V12 predictions generate (check BEST_BETS_MODEL_ID env var)
- [ ] Monitor first decay-detection Slack alert
- [ ] Monitor first signal annotation run (pick_signal_tags populated)
- [ ] Check `picks/{date}.json` has Best Bets subset (id=26) with signal tags

### Week 1 (Feb 19-25)

- [ ] Backfill best_bets subset and signal-best-bets JSON for Jan 9 - Feb 18
- [ ] Build signal health export (`v1/systems/signal-health.json`)
- [ ] Build model health export (`v1/systems/model-health.json`)
- [ ] Validate combo registry on first 5 post-break game days (still FROZEN)
- [ ] Monitor: Are signal picks actually performing well? Track daily

### Week 2 (Feb 26 - Mar 4)

- [ ] Evaluate signal best bets subset grading results (should have 5+ days)
- [ ] If combo registry validates on out-of-sample data, consider unfreezing
- [ ] Consider BEST_BETS_MODEL_ID switch from V9 to V12 if V12 continues 56%+ edge 3+ HR
- [ ] Calibrate INSUFFICIENT_DATA state for V12's lower pick volume

### Week 3+ (Mar 5+)

- [ ] Monthly retrain decision (V9 is 38+ days stale by then)
- [ ] Evaluate if replay CLI needs `--signal-filter` enhancement
- [ ] Full-season signal performance review
- [ ] Consider adding new signals if data supports them

---

## 8. Key Decisions Pending

### 1. Which model drives Best Bets?

Currently `catboost_v9` (default via `BEST_BETS_MODEL_ID` env var). V12 shows 56.0% edge 3+ HR (N=50, +6.9% ROI). But V9 is decaying (39.9% edge 3+ HR, 38+ days stale).

**Decision needed:** Switch BEST_BETS_MODEL_ID to `catboost_v12` on/before Feb 19? Monitor first 2-3 days then decide.

### 2. Should best bets be backfilled?

**Yes, recommended.** Without backfill:
- Website shows "Best Bets" subset with only 1 day of history
- No grading track record to display
- Can't calculate performance metrics

Backfill is non-destructive (append-only) and uses existing infrastructure.

### 3. Do we need a signal health GCS export?

**Yes, recommended.** Without it the website can't show:
- Which signals are currently hot/cold
- Why certain signals are weighted more/less
- Signal-level performance transparency

This is a small exporter (query `signal_health_daily`, format JSON, upload to GCS).

### 4. Do we need a model health GCS export?

**Yes, recommended.** Without it the website can't show:
- Current model state (HEALTHY/WATCH/DEGRADING/BLOCKED)
- "We're sitting out today" messaging
- Model confidence indicator

Also a small exporter.

---

## Files Referenced

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | BestBetsAggregator — scoring + selection |
| `ml/signals/signal_health.py` | Signal health computation + regime classification |
| `ml/signals/combo_registry.py` | 7 validated combos (5 SYNERGISTIC, 2 ANTI_PATTERN) |
| `ml/signals/registry.py` | Signal registry — all active signals |
| `ml/analysis/replay_cli.py` | Replay CLI — 4 strategies |
| `ml/analysis/replay_engine.py` | Replay simulation engine |
| `ml/analysis/replay_strategies.py` | Threshold, Conservative, Oracle, BestOfN |
| `ml/analysis/model_performance.py` | model_performance_daily compute |
| `data_processors/publishing/signal_annotator.py` | Signal annotation + best bets bridge |
| `data_processors/publishing/signal_best_bets_exporter.py` | Signal best bets GCS export |
| `data_processors/publishing/subset_materializer.py` | Subset materialization engine |
| `data_processors/publishing/all_subsets_picks_exporter.py` | Main picks export |
| `shared/config/model_selection.py` | BEST_BETS_MODEL_ID config |
| `shared/config/subset_public_names.py` | 26 subsets with public names |
| `backfill_jobs/publishing/daily_export.py` | Phase 6 export orchestration |
