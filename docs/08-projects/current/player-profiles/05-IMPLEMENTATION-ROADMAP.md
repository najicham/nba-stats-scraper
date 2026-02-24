# Player Profiles — Implementation Roadmap

## Phased Approach

The profile system can be built incrementally, with each phase delivering standalone value.

---

## Phase 0: Offline Validation (Before Building Anything)

**Goal:** Prove that profile dimensions actually correlate with prediction accuracy before investing in infrastructure.

**Approach:** Run BigQuery analysis on existing `prediction_accuracy` + `player_game_summary` data to answer:

1. **Do metronome players have higher hit rates than volatile players?**
   ```sql
   -- Compute CV per player, join to prediction_accuracy, compare HR by CV bucket
   WITH player_cv AS (
     SELECT player_lookup,
            STDDEV(points) / NULLIF(AVG(points), 0) as cv,
            COUNT(*) as games
     FROM nba_analytics.player_game_summary
     WHERE game_date >= '2025-10-20'
     GROUP BY 1 HAVING COUNT(*) >= 15
   )
   SELECT
     CASE WHEN cv < 0.20 THEN 'metronome'
          WHEN cv < 0.35 THEN 'normal'
          ELSE 'volatile' END as consistency_type,
     COUNT(*) as picks,
     AVG(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as hit_rate
   FROM nba_predictions.prediction_accuracy pa
   JOIN player_cv pc ON pa.player_lookup = pc.player_lookup
   WHERE pa.edge >= 3 AND pa.result IN ('WIN', 'LOSS')
   GROUP BY 1
   ```

2. **Do self-creators have different HR than catch-and-shoot players?**
3. **Does FT rate correlate with OVER hit rate?**
4. **Do interior scorers predict differently than perimeter scorers?**

**Decision gate:** If no dimension shows a statistically significant HR difference (>3 percentage points with N >= 50), reconsider the full build. Even partial signal is enough to justify the profile table, since it's also useful for analysis and monitoring.

**Effort:** 1 session (exploratory queries only, no code changes)

---

## Phase 1: Profile Table and Processor

**Goal:** Build the `player_profiles` table and nightly processor.

### Tasks

1. **Create BigQuery schema** — `schemas/bigquery/precompute/player_profiles.sql`
2. **Build processor** — `data_processors/precompute/player_profiles/player_profile_processor.py`
   - Reads from `player_game_summary` (season aggregation)
   - Reads from `player_shot_zone_analysis` (zone data)
   - Reads from `player_daily_cache` (quick access fields)
   - Computes all archetype dimensions
   - Writes to `nba_precompute.player_profiles`
3. **Schedule in Phase 4** — Run after `player_daily_cache` (which runs at 11:45 PM), before `ml_feature_store` (midnight)
4. **Backfill** — Compute profiles for the current season retroactively

### Design Decisions

- **Aggregation window:** Season-to-date for stability, plus L20 rolling for trend detection
- **Archetype computation:** Pure Python, applied after SQL aggregation
- **Partitioning:** By `game_date` (same as all precompute tables)
- **Clustering:** By `player_lookup`

### Dependencies

- No new scrapers needed — all source data already exists in BQ
- No model changes — this phase is data infrastructure only

**Effort:** 1-2 sessions

---

## Phase 2: Feature Vector Integration

**Goal:** Feed profile data into the ML model.

### Tasks

1. **Replace dead features** with profile-derived values (4 free slots)
   - Update `shared/ml/feature_contract.py` with new feature definitions
   - Update `data_processors/precompute/ml_feature_store/` extraction queries
   - Prioritize: `ft_rate_season`, `points_cv_season`, `assisted_rate_season`, `starter_rate_season`
2. **Retrain model** with new features using `/model-experiment`
3. **Compare performance** — does the retrained model beat current V12?
4. **Shadow deploy** if results are positive

### Risk Mitigation

- Replacing dead features (always-default) cannot make the model worse — it only removes noise
- Use the standard governance gates (edge 3+ HR >= 60%, sample >= 50, etc.)
- Shadow for 2+ days before promoting

**Effort:** 1-2 sessions (including retrain and evaluation)

---

## Phase 3: Signal and Filter Integration

**Goal:** Use profiles in the signal system and best bets selection.

### Tasks

1. **Consistency-aware edge filter** — adjust minimum edge by player volatility
   - Modify `ml/signals/best_bets_selector.py` or signal filters
   - A/B test: run both flat-edge and consistency-adjusted edge in parallel
2. **Creation-aware teammate-out signal** — enhance `star_teammates_out`
3. **Archetype-based subsets** — add to `shared/config/cross_model_subsets.py`
4. **Richer pick angles** — update `pick_angle_builder.py` with profile context

**Effort:** 1-2 sessions

---

## Phase 4: Historical and Multi-Season (Future)

**Goal:** Build season-level baselines for longitudinal analysis.

### Tasks

1. **Backfill `player_profile_baselines`** for 2024-25 season (and optionally 2023-24)
2. **Trend analysis** — detect early/late season patterns per player
3. **Career archetype tracking** — how do players evolve year-over-year?
4. **Pre-season priors** — use last season's profile as a prior for early-season predictions when current-season sample is small

This phase requires backfilling `player_game_summary` for prior seasons (may already be partially available from the `nba-backfill-2021-2026` project).

**Effort:** 2-3 sessions

---

## Priority and Dependencies

```
Phase 0 (offline validation)
    ↓ validates the concept
Phase 1 (build table + processor)
    ↓ profile data available
Phase 2 (ML features)        Phase 3 (signals/filters)
    ↓                             ↓
    └──── both feed into ─────────┘
                ↓
Phase 4 (multi-season, future)
```

**Recommended start:** Phase 0. Run the validation queries in the next session. If results are promising, proceed to Phase 1.

---

## Quick Wins (No Infrastructure Required)

Even before building the full profile system, these can be done immediately:

1. **Unify archetype thresholds** — `_determine_primary_zone_static`, `player_season_exporter`, and `pick_angle_builder` all use different cutoffs. Pick one and make it canonical.

2. **Add `starter_flag` to feature vector** — It already exists in `player_game_summary` and flows to supplemental data. Promoting it to a feature requires only a feature contract update and feature store extraction query change.

3. **Compute FT rate in daily cache** — Add `ft_rate_last_10` to `player_daily_cache` aggregation. This is a simple division of existing fields (`ft_attempts / fg_attempts` over last 10 games).

4. **Run archetype analysis on prediction_accuracy** — Even without a profile table, you can join `player_game_summary` aggregates to `prediction_accuracy` ad-hoc to see if archetypes matter.
