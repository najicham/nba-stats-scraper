# Data Lineage Integrity Validation

**Status**: Design Complete, Ready for Implementation
**Priority**: P1 - Data Quality
**Scope**: Full 2025-26 NBA Season
**Last Updated**: 2026-01-26

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [DESIGN-DECISIONS.md](./DESIGN-DECISIONS.md) | Synthesized design from external reviews |
| [SPOT-CHECK-INTEGRATION.md](./SPOT-CHECK-INTEGRATION.md) | Spot check skills + cascade tracking |
| [reviews/opus-review.md](./reviews/opus-review.md) | External review from Opus web chat |
| [reviews/sonnet-review.md](./reviews/sonnet-review.md) | External review from Sonnet web chat |
| [EXTERNAL-REVIEW-REQUEST.md](./EXTERNAL-REVIEW-REQUEST.md) | Original request sent to reviewers |

## Spot Check Skills (NEW - Jan 2026)

| Skill | Purpose | When to Use |
|-------|---------|-------------|
| `/spot-check-player` | Deep dive on one player | Investigating specific player issues |
| `/spot-check-gaps` | System-wide gap detection | Weekly audit, post-backfill |
| `/spot-check-date` | Check all players for one date | After reports of missing data |
| `/spot-check-team` | Team roster audit | After trades, team-specific issues |
| `/spot-check-cascade` | Downstream impact analysis | Before/after backfilling |

## Contamination Tracking Schema (NEW - Jan 2026)

**File**: `migrations/backfill_tracking_schema.sql`

Three-table architecture:
- `backfill_events` - Immutable log of backfills
- `contamination_records` - Affected downstream records + remediation status
- `remediation_log` - Audit trail of fixes

See [SPOT-CHECK-INTEGRATION.md](./SPOT-CHECK-INTEGRATION.md) for full details.

## Current Investigation: Phase 3 Processor Bug

**Finding**: ~10-15 players/day with actual minutes are missing from `player_game_summary`.

**Details**: [PLAYER-GAPS-INVESTIGATION.md](./PLAYER-GAPS-INVESTIGATION.md)

---

## Executive Summary

Validate that all computed data (rolling averages, ML features, predictions) was calculated with complete, correct upstream data. Detect and fix any "cascade contamination" where records were computed while dependencies were missing or stale.

### Goals

1. **Find and fix**: Identify contaminated data, reprocess affected ranges
2. **Understand scope**: Quantify how widespread the issue is
3. **Build ongoing validation**: Create system to prevent future contamination

### Layers to Validate

| Layer | Tables | Risk Level |
|-------|--------|------------|
| Rolling Averages | `player_rolling_averages`, `team_rolling_averages` | HIGH |
| Game Summaries | `player_game_summary`, `team_*_game_summary` | MEDIUM |
| ML Features | `ml_feature_store_*` | HIGH |
| Predictions | `player_prop_predictions` | CRITICAL |

---

## The Problem: Cascade Contamination

### How It Happens

```
Day 1: Game A played
Day 2: Game A data MISSING (scraper failed, API delayed, etc.)
Day 3: Rolling averages computed (uses wrong window - missing Game A)
Day 4: ML features computed (uses wrong rolling averages)
Day 5: Predictions generated (uses wrong features)
Day 6: Game A backfilled (finally scraped)
Day 7: All downstream data is STALE but looks fine
```

### The Cascade

```
Raw Game Data (source of truth)
       │
       ▼
Player Game Summary (per-game stats)
       │
       ▼
Rolling Averages (last 5, 10, 15, 20 games)  ◄── HIGH RISK: uses sliding window
       │
       ▼
ML Feature Store (combines rolling + situational)  ◄── HIGH RISK: aggregates many sources
       │
       ▼
Predictions (model output)  ◄── CRITICAL: what users see
       │
       ▼
Grading (accuracy tracking)  ◄── Affects model feedback loop
```

---

## Validation Approach

### Phase 1: Backfill Event Detection

**Goal**: Find all records that were loaded "late" (after their game_date + threshold)

```sql
-- Find late-loaded raw game data
SELECT
    game_date,
    game_id,
    loaded_at,
    TIMESTAMP_DIFF(loaded_at, TIMESTAMP(game_date), HOUR) as hours_delayed
FROM nba_raw.bdl_boxscores
WHERE loaded_at > TIMESTAMP_ADD(TIMESTAMP(game_date), INTERVAL 48 HOUR)
  AND game_date >= '2025-10-01'
ORDER BY game_date;
```

**Output**: List of (game_date, game_id) pairs that were backfilled

### Phase 2: Contamination Window Identification

**Goal**: For each backfilled game, identify the time window where downstream data is suspect

```
If Game A (2025-12-15) was backfilled on 2025-12-20:
   - Rolling averages for 2025-12-16 through 2025-12-20 are suspect
   - Actually, any rolling window that SHOULD have included 2025-12-15 is suspect
   - For "last 10 games" window, this could affect 10+ future dates
```

**Algorithm**:
```python
def find_contamination_window(backfilled_game_date, backfill_timestamp, window_size=20):
    """
    Find all dates whose rolling averages might be contaminated.

    If game from Dec 15 was backfilled on Dec 20:
    - Dec 16-20 rolling averages definitely affected
    - Dec 21+ might be affected if window_size > 5
    """
    # Affected dates are from (game_date + 1) through (backfill_date)
    # Plus any date within window_size of the backfill that should have included this game

    contamination_start = backfilled_game_date + timedelta(days=1)
    contamination_end = backfill_timestamp.date()

    # Extended window: if this game should have been in rolling avg
    extended_end = contamination_end + timedelta(days=window_size)

    return (contamination_start, extended_end)
```

### Phase 3: Affected Record Identification

**Goal**: Find all computed records that fall within contamination windows

```sql
-- Find rolling averages computed during contamination windows
WITH backfilled_games AS (
    SELECT
        game_date,
        game_id,
        loaded_at as backfill_timestamp
    FROM nba_raw.bdl_boxscores
    WHERE loaded_at > TIMESTAMP_ADD(TIMESTAMP(game_date), INTERVAL 48 HOUR)
      AND game_date >= '2025-10-01'
),
contamination_windows AS (
    SELECT
        game_date as backfilled_date,
        DATE_ADD(game_date, INTERVAL 1 DAY) as window_start,
        DATE(backfill_timestamp) as window_end,
        backfill_timestamp
    FROM backfilled_games
)
SELECT
    ra.game_date,
    ra.player_id,
    ra.processed_at,
    cw.backfilled_date,
    cw.backfill_timestamp,
    'potentially_contaminated' as status
FROM nba_analytics.player_rolling_averages ra
JOIN contamination_windows cw
    ON ra.game_date BETWEEN cw.window_start AND DATE_ADD(cw.window_end, INTERVAL 20 DAY)
    AND ra.processed_at < cw.backfill_timestamp
ORDER BY ra.game_date, ra.player_id;
```

### Phase 4: Validation by Recomputation

**Goal**: For a sample of affected records, recompute and compare

```python
def validate_rolling_average(player_id, game_date, stat_name, window_size=10):
    """
    Recompute a rolling average and compare to stored value.

    Returns:
        - stored_value: What's in the database
        - computed_value: What it should be
        - difference: Absolute difference
        - pct_difference: Percentage difference
        - is_contaminated: True if difference > threshold
    """
    # Get stored value
    stored = query(f"""
        SELECT {stat_name}_last_{window_size}_avg
        FROM nba_analytics.player_rolling_averages
        WHERE player_id = {player_id} AND game_date = '{game_date}'
    """)

    # Recompute from raw data
    computed = query(f"""
        SELECT AVG({stat_name}) as recomputed_avg
        FROM (
            SELECT {stat_name}
            FROM nba_analytics.player_game_summary
            WHERE player_id = {player_id}
              AND game_date < '{game_date}'
            ORDER BY game_date DESC
            LIMIT {window_size}
        )
    """)

    difference = abs(stored - computed)
    pct_difference = (difference / stored) * 100 if stored else 0

    return {
        'stored': stored,
        'computed': computed,
        'difference': difference,
        'pct_difference': pct_difference,
        'is_contaminated': pct_difference > 1.0  # 1% threshold
    }
```

### Phase 5: Scope Assessment

**Goal**: Quantify the contamination

```sql
-- Summary: How many records are potentially contaminated?
SELECT
    'player_rolling_averages' as table_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN is_contaminated THEN 1 END) as contaminated_records,
    ROUND(COUNT(CASE WHEN is_contaminated THEN 1 END) * 100.0 / COUNT(*), 2) as pct_contaminated
FROM validation_results
GROUP BY table_name

UNION ALL

SELECT
    'ml_feature_store' as table_name,
    ...
```

### Phase 6: Remediation

**Goal**: Reprocess contaminated data

```python
def remediate_contaminated_data(contamination_report):
    """
    Reprocess all data in contaminated date ranges.

    Strategy:
    1. Find earliest contaminated date
    2. Reprocess from that date forward (cascade fixes downstream)
    3. Mark as reprocessed in audit log
    """
    earliest_date = min(r['game_date'] for r in contamination_report)

    # Reprocess Phase 3 (rolling averages)
    trigger_backfill('phase3', start_date=earliest_date, end_date='today')

    # Reprocess Phase 4 (ML features)
    trigger_backfill('phase4', start_date=earliest_date, end_date='today')

    # Reprocess Phase 5 (predictions) - only for future games
    trigger_prediction_refresh()
```

### Phase 7: Ongoing Prevention

**Goal**: Build validation into the pipeline

```python
class DataLineageValidator:
    """
    Run after each processing phase to detect contamination.
    """

    def validate_rolling_average_completeness(self, game_date, player_id, window_size):
        """
        Verify all games in the rolling window actually existed at computation time.
        """
        games_in_window = self.get_games_in_window(player_id, game_date, window_size)

        for game in games_in_window:
            if game.loaded_at > self.processing_timestamp:
                return ValidationResult(
                    status='CONTAMINATED',
                    reason=f'Game {game.game_id} loaded after computation',
                    affected_date=game_date
                )

        return ValidationResult(status='VALID')
```

---

## Implementation Plan

### Week 1: Detection & Assessment

| Day | Task | Output |
|-----|------|--------|
| 1 | Build backfill detection queries | List of all late-loaded games |
| 2 | Build contamination window calculator | Date ranges per backfill event |
| 3 | Identify affected records | Count by table and date |
| 4 | Sample validation (recompute & compare) | Accuracy of contamination detection |
| 5 | Scope report | Executive summary of impact |

### Week 2: Remediation

| Day | Task | Output |
|-----|------|--------|
| 1 | Design reprocessing strategy | Which dates need reprocessing |
| 2 | Reprocess rolling averages | Fixed player_rolling_averages |
| 3 | Reprocess ML features | Fixed ml_feature_store |
| 4 | Validate fixes | Confirmation report |
| 5 | Document findings | Lessons learned |

### Week 3: Prevention System

| Day | Task | Output |
|-----|------|--------|
| 1 | Design ongoing validation | Spec for real-time checks |
| 2 | Implement pre-processing checks | Dependency validation |
| 3 | Implement post-processing audit | Contamination detection |
| 4 | Add to monitoring dashboard | Visibility |
| 5 | Documentation | Runbooks, alerts |

---

## Queries Reference

### Find All Backfilled Games

```sql
-- Games loaded more than 48 hours after they were played
SELECT
    game_date,
    game_id,
    home_team,
    away_team,
    loaded_at,
    TIMESTAMP_DIFF(loaded_at, TIMESTAMP(game_date), HOUR) as hours_delayed,
    CASE
        WHEN TIMESTAMP_DIFF(loaded_at, TIMESTAMP(game_date), HOUR) > 168 THEN 'severe'  -- > 7 days
        WHEN TIMESTAMP_DIFF(loaded_at, TIMESTAMP(game_date), HOUR) > 72 THEN 'moderate'  -- > 3 days
        ELSE 'minor'
    END as delay_severity
FROM nba_raw.bdl_games
WHERE game_date >= '2025-10-01'
  AND loaded_at > TIMESTAMP_ADD(TIMESTAMP(game_date), INTERVAL 48 HOUR)
ORDER BY hours_delayed DESC;
```

### Find Rolling Averages With Incomplete Windows

```sql
-- For each rolling average record, check if all source games existed
WITH rolling_avg_records AS (
    SELECT
        player_id,
        game_date,
        processed_at,
        -- Need to know which games were used in the calculation
    FROM nba_analytics.player_rolling_averages
    WHERE game_date >= '2025-10-01'
),
games_in_window AS (
    SELECT
        ra.player_id,
        ra.game_date as avg_date,
        ra.processed_at as avg_processed_at,
        pg.game_date as source_game_date,
        pg.loaded_at as source_loaded_at,
        CASE
            WHEN pg.loaded_at > ra.processed_at THEN 'NOT_AVAILABLE'
            ELSE 'AVAILABLE'
        END as availability_at_computation
    FROM rolling_avg_records ra
    LEFT JOIN nba_analytics.player_game_summary pg
        ON ra.player_id = pg.player_id
        AND pg.game_date < ra.game_date
        AND pg.game_date >= DATE_SUB(ra.game_date, INTERVAL 30 DAY)  -- Approximate window
)
SELECT
    avg_date,
    player_id,
    COUNT(*) as games_in_window,
    COUNTIF(availability_at_computation = 'NOT_AVAILABLE') as games_not_available,
    COUNTIF(availability_at_computation = 'AVAILABLE') as games_available
FROM games_in_window
GROUP BY avg_date, player_id
HAVING games_not_available > 0
ORDER BY avg_date DESC;
```

### Compare Stored vs Recomputed Values

```sql
-- Sample validation: recompute points_last_10_avg and compare
WITH stored_values AS (
    SELECT
        player_id,
        game_date,
        points_last_10_avg as stored_value,
        processed_at
    FROM nba_analytics.player_rolling_averages
    WHERE game_date >= '2025-10-01'
),
recomputed_values AS (
    SELECT
        player_id,
        game_date,
        AVG(points) as recomputed_value
    FROM (
        SELECT
            player_id,
            game_date,
            points,
            ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC) as rn
        FROM nba_analytics.player_game_summary
        WHERE game_date >= '2025-09-01'
    )
    WHERE rn <= 10
    GROUP BY player_id, game_date
)
SELECT
    s.player_id,
    s.game_date,
    s.stored_value,
    r.recomputed_value,
    ABS(s.stored_value - r.recomputed_value) as difference,
    ROUND(ABS(s.stored_value - r.recomputed_value) / NULLIF(s.stored_value, 0) * 100, 2) as pct_diff,
    CASE
        WHEN ABS(s.stored_value - r.recomputed_value) / NULLIF(s.stored_value, 0) > 0.01 THEN 'CONTAMINATED'
        ELSE 'VALID'
    END as validation_status
FROM stored_values s
JOIN recomputed_values r
    ON s.player_id = r.player_id AND s.game_date = r.game_date
WHERE ABS(s.stored_value - r.recomputed_value) > 0.1  -- Only show differences
ORDER BY pct_diff DESC
LIMIT 100;
```

---

## Success Metrics

### Detection Phase
- [ ] Identified all games loaded late (>48h after game_date)
- [ ] Mapped contamination windows for each backfill event
- [ ] Counted affected records by table

### Validation Phase
- [ ] Sample validation shows detection accuracy >95%
- [ ] False positive rate <5%
- [ ] Quantified scope (X% of records affected)

### Remediation Phase
- [ ] All contaminated rolling averages reprocessed
- [ ] All contaminated ML features reprocessed
- [ ] Validation confirms fixes

### Prevention Phase
- [ ] Pre-processing dependency checks implemented
- [ ] Post-processing audit running
- [ ] Alerts configured for future contamination
- [ ] Dashboard showing data lineage health

---

## Open Questions

1. **What's the contamination threshold?**
   - 1% difference? 5%? Depends on use case.

2. **How far back do we reprocess?**
   - Rolling averages cascade forward, so one early gap affects many dates.

3. **What about ML model retraining?**
   - If training data was contaminated, model itself might be biased.

4. **Historical predictions?**
   - Do we need to re-grade past predictions with correct data?

---

## Related Documentation

- BigQuery quota fix: `docs/08-projects/current/bigquery-quota-fix/`
- Validation skills: `.claude/skills/validate-historical.md`
- Processing architecture: `docs/03-phases/`

---

---

## Initial Findings (2026-01-26)

### Backfill Scope Assessment

Ran initial queries to understand the scope of backfilled data:

**Raw Data (bdl_player_boxscores):**

| Delay Category | Game Dates | Records | Date Range |
|---------------|------------|---------|------------|
| SEVERE (>7 days) | 78 | 19,619 | Oct 21 - Jan 18 |
| MODERATE (3-7 days) | 8 | 2,321 | Dec 26 - Jan 22 |
| MINOR (2-3 days) | 3 | 699 | Dec 30 - Jan 10 |
| NORMAL (<2 days) | 7 | 1,894 | Dec 31 - Jan 26 |

**Key Finding**: 78 out of 96 game dates (81%) were backfilled more than 7 days late.

**Precompute Data (player_composite_factors):**

Multiple processing timestamps visible:
- First wave: Dec 20, 2025 (~02:30 UTC)
- Second wave: Jan 23, 2026 (~04:20 UTC)

Some dates (Nov 10-15) show ONLY Jan 23 processing, indicating they were first computed in Jan.

### Interpretation

1. **Good news**: Backfill reprocessing HAS occurred (Jan 23 timestamps)
2. **Concern**: Any data computed BEFORE Jan 23 backfill with dependencies from Oct-Nov may be contaminated
3. **Validation needed**: Compare stored values to recomputed values

### Next Step

Run sample validation on player_composite_factors to check if Jan 23 reprocessing fixed contamination.

---

**Next Step**: Start with Phase 1 - run the backfill detection query to understand scope.
