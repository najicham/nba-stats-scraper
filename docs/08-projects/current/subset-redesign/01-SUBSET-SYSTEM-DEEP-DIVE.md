# Subset System Deep Dive

Technical reference for how prediction subsets are defined, filtered, materialized, published, and graded. Written so future sessions can fully understand the system without reading code.

**Last updated:** Session 155 (2026-02-07)

## Overview

Subsets are curated groups of daily player prop predictions, filtered by quality criteria (edge, direction, signal). They answer: "which of today's predictions are worth betting on?" Each subset applies different strictness levels, from a single top pick to all profitable picks.

**Pipeline position:** Phase 6 (Publishing). Subsets consume Phase 5 predictions and Phase 4 feature quality data.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  BigQuery: dynamic_subset_definitions                       │
│  (8 active subset configs, each with filter criteria)       │
└──────────────────────┬──────────────────────────────────────┘
                       │
Phase 5 completes      │  Phase 6 triggers
         │             │
         ▼             ▼
┌──────────────────────────────┐
│  SubsetMaterializer          │
│  • Loads definitions         │
│  • Loads predictions         │
│  • Loads daily signal        │
│  • Filters per subset        │
│  • Writes → current_subset_  │
│    picks (append-only)       │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  AllSubsetsPicksExporter     │
│  • Reads materialized picks  │
│  • Adds 30-day performance   │
│  • Builds clean JSON         │
│  • Uploads → GCS API         │
└──────────────┬───────────────┘
               │
               ▼
  gs://nba-props-platform-api/picks/{date}.json → Website

Next morning (7:30 AM ET):
┌──────────────────────────────┐
│  SubsetGradingProcessor      │
│  • Selects pre-tip version   │
│  • Compares to actuals       │
│  • Writes → subset_grading_  │
│    results                   │
└──────────────────────────────┘
```

## Subset Definitions

### Storage: `nba_predictions.dynamic_subset_definitions`

Subsets are defined as rows in a BigQuery table. Each row specifies filter criteria. The code reads these dynamically — changing a row changes the subset without any code deploy.

### Schema

| Column | Type | Description |
|--------|------|-------------|
| `subset_id` | STRING | Internal ID (e.g., `top_pick`, `high_edge_over`). Primary key. |
| `subset_name` | STRING | Display name (e.g., "Top Pick") |
| `subset_description` | STRING | Human description of the subset's purpose |
| `system_id` | STRING | Which ML model's predictions to filter. Currently always `catboost_v9`. |
| `min_edge` | FLOAT | Minimum edge threshold. Edge = `ABS(predicted_points - current_points_line)`. |
| `min_confidence` | FLOAT | Minimum confidence score. **Not useful** — all 3+ edge picks have 0.95+. |
| `direction` | STRING | Filter by recommendation: `OVER`, `UNDER`, or `ANY`/NULL (no filter). |
| `signal_condition` | STRING | Filter by daily signal: `GREEN`, `YELLOW`, `RED`, `GREEN_OR_YELLOW`, `ANY`/NULL. |
| `use_ranking` | BOOLEAN | Whether to apply `top_n` limit after other filters. |
| `top_n` | INTEGER | Max picks to include (1-indexed). Only applied when `use_ranking=TRUE`. |
| `pct_over_min` | FLOAT | Minimum percentage of OVER picks in daily signal (rarely used). |
| `pct_over_max` | FLOAT | Maximum percentage of OVER picks (rarely used). |
| `is_active` | BOOLEAN | Soft delete flag. Deactivated subsets are preserved for history. |
| `notes` | STRING | Design notes (why this subset exists). |

### Model Coupling (`system_id`)

**Subsets are coupled to a specific prediction model.** The `system_id` column in the definition table determines which model's predictions are filtered:

- Currently all 8 subsets use `system_id = 'catboost_v9'`.
- The materializer query filters: `WHERE p.system_id = 'catboost_v9' AND p.is_active = TRUE`.
- If a new model (e.g., V10) is deployed, you must either:
  - Update the `system_id` in all definition rows, **OR**
  - Create new subset definitions with `system_id = 'catboost_v10'`.

**In the materialized picks table:** The `system_id` is **not** stored as a separate column. Instead, the subset inherits it from its definition. The model origin is implicit. If you need to know which model generated a materialized pick, check the `prediction_id` and look it up in `player_prop_predictions.system_id`.

### Current 8 Active Subsets

| # | subset_id | Name | min_edge | direction | signal_condition | top_n | Use Case |
|---|-----------|------|----------|-----------|------------------|-------|----------|
| 1 | `top_pick` | Top Pick | 5.0 | OVER | GREEN_OR_YELLOW | 1 | Single best bet |
| 2 | `top_3` | Top 3 | 5.0 | OVER | GREEN_OR_YELLOW | 3 | Small focused set |
| 3 | `top_5` | Top 5 | 5.0 | ANY | GREEN_OR_YELLOW | 5 | Balanced quality/volume |
| 4 | `high_edge_over` | High Edge OVER | 5.0 | OVER | ANY | NULL | All OVER high-edge |
| 5 | `high_edge_all` | High Edge All | 5.0 | ANY | ANY | NULL | Broad high-edge pool |
| 6 | `ultra_high_edge` | Ultra High Edge | 7.0 | ANY | ANY | NULL | Highest conviction |
| 7 | `green_light` | Green Light | 5.0 | ANY | GREEN_OR_YELLOW | NULL | Signal-filtered |
| 8 | `all_picks` | All Picks | 3.0 | ANY | ANY | NULL | Everything profitable |

### Data-Driven Filter Choices (Session 154 Analysis)

The filters were chosen based on full-season (Nov 2025 - Feb 2026) performance data:

| Filter Dimension | Finding | Design Impact |
|-----------------|---------|---------------|
| **Edge** | 7+ = 73.6%, 5+ = 67%, 3+ = 60%, <3 loses money | Min edge of 3.0 for broadest subset, 5.0 for most |
| **Direction** | OVER at 5+ edge = **82.4%** vs UNDER = 55.8% | Top subsets (#1-2, #4) filter to OVER only |
| **Signal** | GREEN/YELLOW = ~80%, RED = 50% (breakeven) | Top subsets (#1-3, #7) require GREEN/YELLOW |
| **Ranking** | Rank #1 = 71%, #6-10 = 70% (weak differentiator) | Only top 3 subsets use ranking (for volume control) |
| **Confidence** | All 3+ edge picks have 0.95+ | Not used in any subset |

## Filtering Logic (Step by Step)

Location: `data_processors/publishing/subset_materializer.py:_filter_picks_for_subset()`

The same logic exists in `data_processors/publishing/all_subsets_picks_exporter.py` as a fallback for dates without materialized data.

### Pre-filter: Prediction Loading

Before any subset filtering, predictions are loaded with these hard filters:

```sql
-- From SubsetMaterializer._query_all_predictions()
WHERE p.game_date = @game_date
  AND p.system_id = 'catboost_v9'      -- Model filter (matches definition)
  AND p.is_active = TRUE                -- Not superseded
  AND p.recommendation IN ('OVER', 'UNDER')  -- Has a direction
  AND p.current_points_line IS NOT NULL  -- Has a betting line
  AND pgs.team_abbr IS NOT NULL          -- Has game context
  AND feature_quality_score >= 85.0      -- Feature quality gate (Session 94)
ORDER BY composite_score DESC            -- Sorted by quality for ranking
```

**Feature quality gate:** Only predictions with `feature_quality_score >= 85.0` enter any subset. Session 94 found <85% quality has 51.9% hit rate vs 56.8% for 85%+.

**Composite score:** Used for ranking/ordering. Formula: `(edge * 10) + (confidence * 0.5)`.

### Per-Subset Filtering

For each prediction, filters are applied in this order. A prediction must pass ALL filters to be included:

```
1. EDGE FILTER
   If subset.min_edge is set:
     Skip if prediction.edge < subset.min_edge

2. CONFIDENCE FILTER (rarely used)
   If subset.min_confidence is set:
     Skip if prediction.confidence_score < subset.min_confidence

3. DIRECTION FILTER
   If subset.direction is set AND is not 'ANY' or NULL:
     Skip if prediction.recommendation != subset.direction
   (If direction is 'ANY', NULL, or not set → no filtering)

4. SIGNAL FILTER
   Three conditions must all be true for signal filtering to apply:
     a) subset.signal_condition is set (not NULL)
     b) subset.signal_condition != 'ANY'
     c) actual daily signal data exists for this date

   If all three are true:
     If signal_condition == 'GREEN_OR_YELLOW':
       Skip if actual signal not in ('GREEN', 'YELLOW')
     Else:
       Skip if actual signal != signal_condition

   If ANY condition is false → no signal filtering applied.
   This means: missing signal data = ALL picks pass the signal filter.

5. PCT_OVER RANGE FILTER (rarely used)
   If pct_over data exists for the date:
     If subset.pct_over_min is set: skip if pct_over < min
     If subset.pct_over_max is set: skip if pct_over > max

6. TOP_N LIMIT
   If subset.top_n is set:
     Keep only first N picks (predictions pre-sorted by composite_score DESC)

   After limiting, assign rank_in_subset (1-indexed position).
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| No predictions for date | Subset returns 0 picks, status='no_predictions' |
| No active definitions | Returns 0 picks, status='no_definitions' |
| Daily signal missing | Signal filter is skipped entirely (not enforced). All picks pass. |
| Signal = RED, subset wants GREEN_OR_YELLOW | Subset returns 0 picks for that date |
| All predictions filtered out | Empty subset is normal — logged but not an error |
| Multiple versions same date | Each materialization creates a new version_id |

## Materialization

### Append-Only Design

**Why:** BigQuery has 90-minute DML partition locks. If we UPDATE existing rows, concurrent materializations would block each other.

**How:** Every call to `SubsetMaterializer.materialize()` creates a new `version_id` (format: `v_YYYYMMDD_HHMMSS`). New rows are INSERT-ed. Old versions remain.

**Frequency:** Predictions regenerate 4-6x/day (early morning, overnight, retry, line checks, last call), creating a new version each time.

### Table: `nba_predictions.current_subset_picks`

Each row = one player in one subset for one version:

| Column | Source |
|--------|--------|
| `game_date`, `subset_id`, `player_lookup` | Identifiers |
| `prediction_id`, `game_id` | Links to source prediction and game |
| `version_id`, `computed_at`, `trigger_source`, `batch_id` | Version tracking |
| `rank_in_subset` | Position within subset (1 = best) |
| `player_name`, `team`, `opponent` | Denormalized from predictions + game context |
| `predicted_points`, `current_points_line`, `recommendation` | The actual prediction |
| `confidence_score`, `edge`, `composite_score` | Quality metrics |
| `feature_quality_score`, `default_feature_count` | Data quality provenance |
| `line_source`, `prediction_run_mode` | How the prediction was generated |
| `prediction_made_before_game`, `quality_alert_level` | Timing and quality flags |
| `subset_name`, `min_edge`, `min_confidence`, `top_n` | Subset config snapshot |
| `daily_signal`, `pct_over`, `total_predictions_available` | Version-level context |

### Version Selection

Different consumers need different versions:

| Consumer | Version Strategy | Rationale |
|----------|-----------------|-----------|
| **Exporter** (website JSON) | Latest version (`MAX(version_id)`) | Show freshest data |
| **Grader** (accuracy tracking) | Last version before first tip time | Grade what was actually published |

## Daily Signal

### What It Is

A daily aggregate characterizing the overall prediction landscape for a game day. Calculated by `predictions/coordinator/signal_calculator.py` after Phase 5 predictions complete.

### Signal Values

| Signal | Meaning | Criteria |
|--------|---------|----------|
| **GREEN** | Balanced picks, good volume. Recommended. | 25-45% OVER picks AND 3-8 high-edge picks |
| **YELLOW** | Caution: low volume or skewed distribution | Either <3 high-edge picks OR >45% OVER |
| **RED** | Risky: heavy under-bias | <25% OVER picks |

### How Subsets Use It

Subsets with `signal_condition = 'GREEN_OR_YELLOW'` only include picks on GREEN or YELLOW days. On RED days, these subsets are empty. This is intentional — RED days historically break even (~50% hit rate).

## JSON Export

### File: `gs://nba-props-platform-api/picks/{date}.json`

The website reads this file. Technical details (prediction IDs, feature quality scores, etc.) are stripped. Each subset becomes a "group" with clean naming.

```json
{
  "date": "2026-02-07",
  "generated_at": "2026-02-07T14:30:22Z",
  "model": "926A",
  "groups": [
    {
      "id": "1",
      "name": "Top Pick",
      "stats": { "hit_rate": 81.8, "roi": 15.2, "days": 30 },
      "picks": [
        {
          "player": "LeBron James",
          "team": "LAL",
          "opponent": "BOS",
          "prediction": 26.1,
          "line": 24.5,
          "direction": "OVER"
        }
      ]
    }
  ]
}
```

**Group IDs** (1-8) are mapped in `shared/config/subset_public_names.py`. The mapping is ordered by conviction (1 = highest).

**Performance stats** come from the `v_dynamic_subset_performance` view (30-day rolling window).

**Model codename** (e.g., "926A") hides the internal model name. Mapped in `shared/config/model_codenames.py`.

## Grading

### When: Morning after games (7:30 AM ET)

### Process

1. **Version selection:** Find the latest version_id computed BEFORE the first game tip-off. This ensures we grade what was actually published, not retroactive recomputations.
2. **Load picks** from `current_subset_picks` for that version.
3. **Load actuals** from `nba_analytics.player_game_summary` (actual points scored).
4. **Grade each pick:**
   - DNP void: 0 points + 0 minutes → excluded
   - Push: actual == line → excluded
   - Win/Loss: based on recommendation direction vs actual
5. **Calculate per-subset metrics:** hit_rate, ROI (-110 odds), MAE, directional breakdown.
6. **Write to `subset_grading_results`** (DELETE + INSERT for idempotency).

### Table: `nba_predictions.subset_grading_results`

| Column | Description |
|--------|-------------|
| `game_date`, `subset_id`, `subset_name` | Identifiers |
| `version_id`, `graded_at` | Which version was graded |
| `total_picks`, `graded_picks`, `voided_picks` | Volume |
| `wins`, `losses`, `pushes` | Outcomes |
| `hit_rate`, `roi`, `units_won` | Performance |
| `avg_edge`, `avg_confidence`, `mae` | Quality |
| `over_picks`, `over_wins`, `under_picks`, `under_wins` | Directional breakdown |

## Code Locations

| Component | File | Purpose |
|-----------|------|---------|
| **Materializer** | `data_processors/publishing/subset_materializer.py` | Filters predictions → BQ |
| **Exporter** | `data_processors/publishing/all_subsets_picks_exporter.py` | BQ → GCS JSON |
| **Grader** | `data_processors/grading/subset_grading/subset_grading_processor.py` | BQ actuals → grading results |
| **Public names** | `shared/config/subset_public_names.py` | Internal ID → website name mapping |
| **Performance view** | `schemas/bigquery/predictions/views/v_dynamic_subset_performance.sql` | 30-day rolling stats |
| **Signal calculator** | `predictions/coordinator/signal_calculator.py` | Computes daily signal |

## How to Add/Modify Subsets

1. **Add/change rows** in `nba_predictions.dynamic_subset_definitions` (see `00-SUBSET-REFERENCE.md` for SQL).
2. **Update** `shared/config/subset_public_names.py` to map the new `subset_id` to a public name and group ID.
3. **Deploy** the publishing service (or push to main for auto-deploy).
4. **Verify** next materialization picks up the change.

No code changes needed for simple filter adjustments — just update the BQ table.

## When Changing Prediction Models

If deploying a new model (e.g., V10):

1. **Option A: Replace V9** — Update `system_id` in all definition rows from `catboost_v9` to `catboost_v10`. Simple, but loses V9 history.
2. **Option B: Parallel subsets** — Create 8 new definitions with `system_id = 'catboost_v10'`. More complex, enables A/B comparison.
3. **Code change needed:** The materializer's `_query_all_predictions()` has `system_id = 'catboost_v9'` hardcoded in the SQL. This must be updated to either use a parameter or read from the definition.

**Recommendation:** For a V10 that replaces V9 (same features, better training data), use Option A. For a fundamentally different model, use Option B.
