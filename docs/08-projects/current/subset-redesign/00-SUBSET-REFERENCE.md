# Subset Reference (Session 154)

Quick reference for all active subset definitions. Edit these in BigQuery table `nba_predictions.dynamic_subset_definitions`.

## Active Subsets

| # | ID | Name | Edge | Direction | Signal | Top N | Expected Hit Rate | Use Case |
|---|-----|------|------|-----------|--------|-------|-------------------|----------|
| 1 | `top_pick` | Top Pick | 5+ | OVER | GREEN/YELLOW | 1 | ~85% | Single best bet of the day |
| 2 | `top_3` | Top 3 | 5+ | OVER | GREEN/YELLOW | 3 | ~82% | Small focused set |
| 3 | `top_5` | Top 5 | 5+ | ANY | GREEN/YELLOW | 5 | ~78% | Balanced quality/volume |
| 4 | `high_edge_over` | High Edge OVER | 5+ | OVER | ANY | - | ~82% | All OVER high-edge picks |
| 5 | `high_edge_all` | High Edge All | 5+ | ANY | ANY | - | ~67% | Broad high-edge pool |
| 6 | `ultra_high_edge` | Ultra High Edge | 7+ | ANY | ANY | - | ~74% | Highest conviction, low volume |
| 7 | `green_light` | Green Light | 5+ | ANY | GREEN/YELLOW | - | ~80% | Signal-filtered high edge |
| 8 | `all_picks` | All Picks | 3+ | ANY | ANY | - | ~60% | Everything profitable |

## Filter Dimensions

| Dimension | Values | Impact (full season data) |
|-----------|--------|--------------------------|
| **Edge** | `min_edge` threshold | Strongest signal. 7+ = 73.6%, 5+ = 67%, 3+ = 60%, <3 = loses money |
| **Direction** | `OVER`, `UNDER`, `NULL` (any) | OVER at 5+ edge = **82.4%** vs UNDER = 55.8%. Huge difference. |
| **Signal** | `GREEN`, `YELLOW`, `RED`, `GREEN_OR_YELLOW`, `NULL` (any) | GREEN/YELLOW = ~80%, RED = 50% (breakeven) |
| **Top N** | Integer or NULL (all) | Controls volume, not accuracy. Rank #1 = 71%, #6-10 = 70% |
| **Confidence** | `min_confidence` threshold | Not useful — all 3+ edge picks have 0.95+ confidence |

## How to Modify Subsets

```sql
-- Add a new subset
INSERT INTO nba_predictions.dynamic_subset_definitions
  (subset_id, subset_name, subset_description, system_id, min_edge, direction, signal_condition, use_ranking, top_n, is_active, notes)
VALUES
  ('my_new_subset', 'My Subset', 'Description', 'catboost_v9', 5.0, 'OVER', 'GREEN', TRUE, 3, TRUE, 'Why I created this');

-- Deactivate a subset (don't delete — keep history)
UPDATE nba_predictions.dynamic_subset_definitions SET is_active = FALSE WHERE subset_id = 'my_subset';

-- Change a filter
UPDATE nba_predictions.dynamic_subset_definitions SET min_edge = 6.0 WHERE subset_id = 'high_edge_over';
```

After changing definitions, also update `shared/config/subset_public_names.py` to map the subset_id to a website name.

## Pipeline Flow

```
Predictions generated (Phase 5)
  → Phase 5→6 orchestrator triggers export with 'subset-picks'
    → SubsetMaterializer: reads definitions, filters predictions, writes to current_subset_picks (BQ)
    → AllSubsetsPicksExporter: reads materialized data, builds JSON, uploads to GCS
      → Website reads gs://nba-props-platform-api/picks/{date}.json

Morning grading (7:30 AM ET):
  → SubsetGradingProcessor: reads pre-tip version from current_subset_picks
    → Grades against actuals, writes to subset_grading_results
```

## Key Tables

| Table | Purpose |
|-------|---------|
| `nba_predictions.dynamic_subset_definitions` | Subset filter configurations |
| `nba_predictions.current_subset_picks` | Materialized picks per version (append-only) |
| `nba_predictions.subset_grading_results` | Grading results per subset per date |
| `nba_predictions.daily_prediction_signals` | Daily signal (GREEN/YELLOW/RED) |

## Design Decisions (Session 154)

1. **Direction filtering added** — OVER at 5+ edge hits 82.4% vs UNDER at 55.8%. Previous subsets claimed direction filtering but had no implementation.
2. **Signal 'ANY' bug fixed** — Old code treated 'ANY' as a literal signal value, filtering out all picks on signal days. Now 'ANY' and NULL both mean "no filter".
3. **Confidence dropped** — All 3+ edge picks have 0.95+ confidence. No differentiation.
4. **18 → 8 subsets** — Removed duplicates (6 subsets had identical filters), anti-subsets (not for website), and misleading subsets (claimed direction filtering that didn't exist).
