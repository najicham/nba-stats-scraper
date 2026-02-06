# Session 139 Prompt - Adopt New Quality Fields Across Codebase + Source Validation

Copy and paste this to start the next session:

---

## Context

Sessions 137-138 deployed the **Feature Quality Visibility** system — 121 new columns on `ml_feature_store_v2` with per-feature quality scores, per-category quality percentages, alert levels, and a new `is_quality_ready` field. A 4-season backfill was launched and should be complete.

**The new fields exist but nothing outside the processor uses them yet.** The rest of the codebase still relies on the old aggregate `feature_quality_score` and `is_production_ready`. This session's job is to adopt the new fields everywhere they add value, update validation skills, and design new source-vs-feature-store validation.

## Priority 1: Validate Backfill Completion (Quick)

```bash
# Check if backfill processes are still running
ps aux | grep "backfill" | grep -v grep | wc -l

# Push if needed
git log --oneline -3  # Should see 339f42a7 as latest
git push 2>/dev/null || echo "Already pushed"
```

```sql
-- Verify all seasons backfilled
SELECT
  CASE
    WHEN game_date >= '2025-10-01' THEN '2025-26'
    WHEN game_date >= '2024-10-01' THEN '2024-25'
    WHEN game_date >= '2023-10-01' THEN '2023-24'
    WHEN game_date >= '2022-10-01' THEN '2022-23'
    WHEN game_date >= '2021-10-01' THEN '2021-22'
  END as season,
  COUNT(*) as total,
  COUNTIF(quality_alert_level IS NOT NULL) as backfilled,
  ROUND(COUNTIF(quality_alert_level IS NOT NULL) * 100.0 / COUNT(*), 1) as pct
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2021-10-01'
GROUP BY 1 ORDER BY 1;
```

If any season is <100%, re-run backfill for those dates:
```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date <gap-start> --end-date <gap-end> --skip-preflight --no-resume
```

## Priority 2: Audit & Upgrade Codebase Consumers

The new quality visibility fields are much richer than the old `feature_quality_score`. Every consumer should be reviewed to decide if it should use the new fields. Here's the full inventory of files that reference the feature store — audit each one and upgrade where it adds value.

### Skills (`.claude/skills/`) — UPDATE THESE

These are the interactive validation tools. They should use the new per-category and per-feature quality fields.

| Skill File | What to Update |
|------------|---------------|
| `.claude/skills/validate-daily/SKILL.md` | Add checks for `quality_alert_level` distribution (red/yellow/green), `matchup_quality_pct`, and `is_quality_ready`. Replace bare `feature_quality_score` checks with category-level breakdown. |
| `.claude/skills/spot-check-features/SKILL.md` | **Major upgrade.** Use `feature_N_quality`, `feature_N_source`, category quality pcts, `quality_alerts` array. This is the primary quality triage tool — it should surface per-feature issues. |
| `.claude/skills/hit-rate-analysis/SKILL.md` | Add `is_quality_ready` and `quality_tier` (gold/silver/bronze) as grouping dimensions. Compare hit rates by quality tier. |
| `.claude/skills/validate-feature-drift.md` | Use `matchup_quality_pct`, `vegas_quality_pct`, `game_context_quality_pct` trends over time instead of just aggregate score. |
| `.claude/skills/subset-picks/SKILL.md` | Filter by `is_quality_ready` instead of raw `feature_quality_score` threshold. |
| `.claude/skills/validate-historical/SKILL.md` | Use category quality pcts for historical validation. |
| `.claude/skills/validate-lineage.md` | Use `missing_processors`, `upstream_processors_ran` for lineage tracking. |
| `.claude/skills/spot-check-cascade.md` | Use `matchup_quality_pct` and `has_composite_factors` for cascade impact. |

### Prediction System — REVIEW THESE

| File | Current Behavior | Potential Upgrade |
|------|-----------------|-------------------|
| `predictions/worker/data_loaders.py` | Reads `feature_quality_score` | Could also read `quality_alert_level`, `is_quality_ready` for richer quality context |
| `predictions/worker/worker.py` | Uses `feature_quality_score < 70` for `low_quality_flag` | Could use `is_quality_ready` (already computed, more precise) |
| `predictions/coordinator/quality_gate.py` | Gates on `feature_quality_score >= 85%` | Could add `matchup_quality_pct >= 50` check (catches Session 132 scenario) |
| `predictions/coordinator/data_freshness_validator.py` | Checks avg feature_quality_score | Could check `quality_alert_level` red count |

### Validation Scripts — REVIEW THESE

| File | Current Behavior | Potential Upgrade |
|------|-----------------|-------------------|
| `validation/validators/precompute/ml_feature_store_validator.py` | Validates `quality_tier` distribution | Should validate new tiers (gold/silver/bronze/poor/critical), check `quality_alert_level` distribution |
| `shared/validation/feature_store_validator.py` | Cross-table consistency | Should use per-feature source columns for validation |
| `validation/validators/gates/phase4_to_phase5_gate.py` | Avg feature_quality_score | Could add `COUNTIF(quality_alert_level = 'red') = 0` gate |
| `bin/monitoring/pipeline_canary_queries.py` | Checks avg feature_quality_score and count < 70 | Should add `quality_alert_level = 'red'` canary |

### Monitoring — REVIEW THESE

| File | Current Behavior | Potential Upgrade |
|------|-----------------|-------------------|
| `bin/monitoring/feature_store_health_check.py` | Checks player_daily_cache quality_tier | Should also check ml_feature_store_v2 quality_alert_level |
| `bin/alerts/daily_summary/main.py` | References FEATURE_STORE_TABLE | Should include quality distribution in daily summary |

### ML Training — REVIEW THESE

| File | Current Behavior | Potential Upgrade |
|------|-----------------|-------------------|
| `ml/experiments/quick_retrain.py` | Filters `feature_quality_score >= 70` | Could filter `is_training_ready = TRUE` (more precise, checks matchup + history) |
| `ml/features/breakout_features.py` | JOINs with ml_feature_store_v2 | Could filter by `is_quality_ready` for cleaner training data |

**Approach:** Use Explore agents to read each file, then decide if the upgrade is worth it. Not every file needs changing — only upgrade where the new fields provide meaningfully better decisions.

## Priority 3: New Source-vs-Feature-Store Validation

Design and implement new validation that compares **upstream source data** to what ended up in `ml_feature_store_v2`. The goal is to catch data flow issues like:

1. **Source data exists but feature store has defaults** — upstream table has real data for a player/date but the feature store used fallback values (wrong JOIN, missing processor, timing issue)
2. **Feature store has data but source is stale** — feature store was populated but from outdated upstream data
3. **Value drift between source and feature** — source table has value X but feature store derived value Y is unreasonably different
4. **Coverage gaps** — source table covers N players but feature store only has M < N

### Source Tables to Compare Against

| Feature Store Field | Source Table | What to Compare |
|-------------------|-------------|----------------|
| Features 0-4 (player history) | `nba_precompute.player_daily_cache` | Rolling averages, game counts |
| Features 5-8 (composite factors) | `nba_precompute.player_composite_factors` | Fatigue, shot zone, pace, usage scores |
| Features 13-14 (opponent defense) | `nba_precompute.team_defense_zone_analysis` | Def rating, pace |
| Features 25-26 (vegas lines) | `nba_raw.odds_api_player_props` | Line values, availability |
| Features 29-30 (opponent history) | `nba_analytics.player_game_summary` | Points vs specific opponent |

### Validation Ideas

1. **Coverage comparison**: For each game_date, count players in source table vs players in feature store with non-default source for those features. Alert if source has significantly more.
2. **Freshness comparison**: Compare `source_daily_cache_last_updated` in feature store vs actual `updated_at` in player_daily_cache. If feature store timestamp is >6h behind, flag stale data.
3. **Value spot-check**: For a sample of players, compare `feature_0` (points_avg_last_5) against actual `AVG(points)` from the last 5 games in player_game_summary. Flag if difference > 10%.
4. **Default rate vs source availability**: When `feature_N_source = 'default'` but the upstream table HAS data for that player/date, that's a bug. This is the highest-value check.

Consider building this as a new skill (`/validate-source-alignment`) or as a validation script.

## Key Files

```
docs/09-handoff/2026-02-06-SESSION-138-HANDOFF.md      # Full handoff with design decisions
data_processors/precompute/ml_feature_store/quality_scorer.py  # Quality field definitions
schemas/bigquery/predictions/04_ml_feature_store_v2.sql        # Complete schema
```

## New Quality Fields Quick Reference

```
-- Aggregate
quality_tier, quality_alert_level, quality_alerts (REPEATED STRING),
default_feature_count, phase4_feature_count, phase3_feature_count,
calculated_feature_count, is_training_ready, training_quality_feature_count,
is_quality_ready

-- Category quality (5 categories)
matchup_quality_pct, player_history_quality_pct, team_context_quality_pct,
vegas_quality_pct, game_context_quality_pct,
matchup_default_count, player_history_default_count, team_context_default_count,
vegas_default_count, game_context_default_count,
has_composite_factors, has_opponent_defense, has_vegas_line,
critical_features_training_quality, critical_feature_count,
optional_feature_count, matchup_quality_tier, game_context_quality_tier

-- Per-feature (37 each)
feature_0_quality through feature_36_quality (FLOAT64, 0-100)
feature_0_source through feature_36_source (STRING: phase4/phase3/calculated/default)

-- Traceability
upstream_processors_ran, missing_processors,
feature_store_age_hours, upstream_data_freshness_hours,
quality_computed_at, quality_schema_version
```

## What NOT to Change

- `is_production_ready` semantics — unchanged, 20+ consumers
- `calculated` source weight — keep at 100
- Shared `QualityTier` enum — feature store uses its own `get_feature_quality_tier()`
- `feature_quality_score` computation — already correct with all 9 source types
