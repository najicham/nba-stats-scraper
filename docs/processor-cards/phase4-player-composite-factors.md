# Player Composite Factors Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 4 - Precompute |
| **Schedule** | Nightly at 11:30 PM (after zone analysis) |
| **Duration** | 10-15 minutes (450 players) |
| **Priority** | **High** - Required for Phase 5 Week 1 |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | 1010 lines |
| **Schema** | `schemas/bigquery/precompute/player_composite_factors.sql` | 39 fields |
| **Tests** | `tests/processors/precompute/player_composite_factors/` | **54 total** |
| | - Unit tests | 46 tests |
| | - Integration tests | 8 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 3 Analytics:
  ├─ upcoming_player_game_context (CRITICAL) - Fatigue, usage data
  └─ upcoming_team_game_context (CRITICAL) - Pace data

Phase 4 Precompute:
  ├─ player_shot_zone_analysis (CRITICAL) - Primary scoring zone
  └─ team_defense_zone_analysis (CRITICAL) - Opponent weakest zone

Consumers (Phase 5):
  └─ All 5 prediction systems - Apply composite adjustments
```

---

## What It Does

1. **Primary Function**: Combines 4 active factors + 4 deferred factors into composite adjustment scores
2. **Key Output**: One row per player per game with pre-calculated adjustment factors
3. **Value**: Fast prediction updates without recalculating complex factors

**Week 1-4 Strategy**: 4 active factors implemented, 4 deferred set to 0.0 (neutral). After 3 months, XGBoost feature importance determines which deferred factors to implement.

---

## Key Metrics Calculated

### 1. Fatigue Score (0-100)
```python
# Physical freshness based on recent workload
base = 50
rest_bonus = {3+: +30, 2: +15, 1: 0, 0: -20}[days_rest]
minutes_penalty = {>245: -20, >210: -10, <140: +10}[minutes_last_7]
fatigue_score = base + rest_bonus + minutes_penalty + b2b_penalty + age_penalty
# Clamped to 0-100
```
- **Range**: 0 (exhausted) to 100 (fully rested)
- **Example**: 2 days rest, normal minutes = 65 (moderately fresh)

### 2. Shot Zone Mismatch Score (-10.0 to +10.0)
```python
# Player's strength vs opponent's weakness
if player_primary_zone == opponent_weakest_zone:
    base = +5.0  # Perfect matchup!
elif player_primary_zone == opponent_strongest_zone:
    base = -5.0  # Bad matchup
else:
    base = 0.0
# Adjust by efficiency differential
score = base + (player_zone_pct - opponent_zone_allowed) * 10
```
- **Range**: -10.0 (terrible matchup) to +10.0 (perfect matchup)
- **Example**: Paint scorer vs weak paint defense = +4.3

### 3. Pace Score (-3.0 to +3.0)
```python
# Game pace impact on possessions
expected_pace = (team_pace + opponent_pace) / 2
pace_differential = expected_pace - league_avg_pace
pace_score = pace_differential / 3.0  # Scale to range
```
- **Range**: -3.0 (slow game) to +3.0 (fast game)
- **Example**: Fast game (104 pace) = +1.33 (more possessions)

### 4. Usage Spike Score (-3.0 to +3.0)
```python
# Recent usage change from season baseline
usage_change = projected_usage - season_avg_usage
spike_score = (usage_change / 10.0) * 3.0
```
- **Range**: -3.0 (usage drop) to +3.0 (usage spike)
- **Example**: Teammate injured, usage +5% = +1.5 spike

### Total Composite Adjustment
```python
# Sum all active factors (deferred = 0.0 in Week 1-4)
fatigue_scaled = ((fatigue - 50) / 50) * 10  # Convert to -10 to +10
total = fatigue_scaled + shot_zone + pace + usage
# Deferred: referee, look_ahead, travel, opponent_strength all = 0.0
```
- **Range**: Typically -15.0 to +15.0
- **Example**: +15.6 = very favorable game setup

---

## Output Schema Summary

**Total Fields**: 39

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | player_lookup, universal_player_id, game_id |
| Active Factors | 4 | fatigue_score, shot_zone_mismatch, pace, usage_spike |
| Deferred Factors | 4 | referee, look_ahead, travel, opponent_strength (all 0.0) |
| Total Adjustment | 1 | total_composite_adjustment |
| Context JSON | 4 | fatigue_context_json, shot_zone_context_json |
| Metadata | 1 | calculation_version |
| Data Quality | 4 | data_completeness_pct, missing_data_fields |
| Source Tracking (v4.0) | 12 | 4 sources × 3 fields |
| Early Season | 2 | early_season_flag, insufficient_data_reason |
| Processing | 2 | created_at, processed_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  COUNT(*) >= 400 as enough_players,
  AVG(data_completeness_pct) >= 80 as good_completeness,
  AVG(total_composite_adjustment) as avg_adjustment,
  COUNT(CASE WHEN has_warnings THEN 1 END) as warning_count,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),
      source_player_context_last_updated, HOUR)) as max_source_age_hrs
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();

-- Expected Results:
-- enough_players: TRUE (400+ players)
-- good_completeness: TRUE (80%+)
-- avg_adjustment: -5.0 to +10.0
-- warning_count: < 50 players
-- max_source_age_hrs: < 72
```

---

## Common Issues & Quick Fixes

### Issue 1: Low Completeness (<70%)
**Symptom**: Many players with low `data_completeness_pct`
**Diagnosis**:
```sql
-- Check which sources incomplete
SELECT
  AVG(source_player_context_completeness_pct) as player_context,
  AVG(source_team_context_completeness_pct) as team_context,
  AVG(source_player_shot_completeness_pct) as shot_zones,
  AVG(source_team_defense_completeness_pct) as team_defense
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();
```
**Fix**:
1. Check which Phase 4 processor (P1/P2) failed to complete
2. Verify all Phase 3 sources available
3. Run missing processors manually

### Issue 2: Extreme Composite Adjustments
**Symptom**: Players with `total_composite_adjustment > 20` or `< -15`
**Diagnosis**:
```sql
-- Find extreme adjustments
SELECT player_lookup, total_composite_adjustment,
       fatigue_score, shot_zone_mismatch_score,
       pace_score, usage_spike_score
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND (total_composite_adjustment > 20 OR total_composite_adjustment < -15)
ORDER BY total_composite_adjustment DESC;
```
**Fix**:
1. +20: Verify factors - may be legitimate (perfect storm)
2. <-15: Usually back-to-back + bad matchup + usage drop
3. Check context JSON fields for details

### Issue 3: Phase 4 Dependencies Not Complete
**Symptom**: Processor fails at startup
**Fix**:
1. Ensure P1 (team_defense_zone) completed
2. Ensure P2 (player_shot_zone) completed
3. Check orchestration timing (should run at 11:30 PM)
4. Verify Pub/Sub events triggered correctly

---

## Processing Flow

```
upcoming_player_game_context ─┐
upcoming_team_game_context ───┤
                              ├─→ PLAYER COMPOSITE ─→ Phase 5 predictions
player_shot_zone_analysis ────┤     FACTORS              (apply adjustments)
team_defense_zone_analysis ───┘   (450 players)
```

**Timing**:
- Runs: 11:30 PM nightly (after zone analysis processors)
- Waits for: 2 Phase 3 + 2 Phase 4 processors
- Must complete before: ML Feature Store can run
- Total window: 10-15 minutes

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Players processed | < 400 | Critical |
| Avg completeness | < 70% | Warning |
| Avg completeness | < 50% | Critical |
| Processing time | > 20 min | Warning |
| Players with warnings | > 100 | Warning |
| Source age | > 72 hrs | Critical |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Player Composite Factors Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/precompute/player_composite_factors.sql`
- 🧪 **Test Suite**: `tests/processors/precompute/player_composite_factors/`
- 📊 **Related Processors**:
  - ↑ Upstream: Team Defense Zone, Player Shot Zone (Phase 4)
  - ↓ Downstream: ML Feature Store V2 (Phase 4)
  - → Consumers: All Phase 5 prediction systems

---

## Notes

- **4 Active + 4 Deferred**: Start simple, add complexity based on XGBoost feature importance
- **Context JSON**: Debugging transparency - see exactly why scores calculated
- **Deferred Factors**: Referee, look_ahead, travel, opponent_strength all return 0.0 (neutral)
- **XGBoost Analysis**: After 3 months, analyze feature importance to decide which deferred factors to implement
- **Most Complex Dependency**: Requires 2 Phase 3 + 2 Phase 4 sources

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
