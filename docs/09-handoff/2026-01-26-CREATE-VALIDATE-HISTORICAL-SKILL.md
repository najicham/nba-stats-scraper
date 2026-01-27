# Task: Create `/validate-historical` Claude Code Skill

**Date**: 2026-01-26
**Priority**: High
**Reference**: `/validate-daily` skill (`.claude/skills/validate-daily/SKILL.md`)

---

## Overview

Create a new Claude Code skill called `/validate-historical` that validates data completeness and quality over a date range. Unlike `/validate-daily` which checks today's pipeline health, this skill audits historical data integrity and identifies gaps that may have cascading effects.

---

## Why This Matters: The Data Cascade Problem

### Rolling Averages Depend on History

The pipeline calculates rolling statistics like:
- `points_avg_last_5` - Average points over last 5 games
- `rebounds_avg_last_10` - Average rebounds over last 10 games
- `usage_rate` trends

**If one day's data is missing or corrupted:**
1. That player's rolling averages become inaccurate
2. The error propagates forward into subsequent days
3. ML features built on these averages are wrong
4. Predictions using those features are degraded

### Example Cascade

```
Day 1: Player scores 30 points (missing from DB due to pipeline failure)
Day 2: points_avg_last_5 calculated as 20 (should be 22 with the 30)
Day 3: ML features use wrong average
Day 4: Prediction is off because features were wrong
Day 5-10: Error continues propagating until the 5-game window passes
```

### Real Impact

- A single day's Phase 3 failure can degrade prediction quality for 5-10 days
- Multiple gaps compound the problem
- Without historical validation, these issues go unnoticed

---

## Spot Check System Reference

The existing spot check system (`scripts/spot_check_data_accuracy.py`) validates data accuracy by:

### Check Types (A-F)

| Check | What It Validates | How |
|-------|-------------------|-----|
| A | Rolling averages | Recalculates from raw box scores, compares to cached |
| B | Usage rate | Verifies team stats join and calculation |
| C | Minutes played | Cross-references multiple sources |
| D | Game context | Validates opponent, home/away, rest days |
| E | Prediction coverage | Checks predictions exist for eligible players |
| F | Feature completeness | Verifies ML features populated |

### Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Spot Check Accuracy | ≥95% | 90-94% | <90% |
| Minutes Coverage | ≥90% | 80-89% | <80% |
| Usage Rate Coverage | ≥90% | 80-89% | <80% |
| Prediction Coverage | ≥90% | 70-89% | <70% |

### Running Spot Checks

```bash
# Quick check (5 samples, 2 check types)
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate

# Comprehensive check
python scripts/spot_check_data_accuracy.py --samples 10

# Date-specific
python scripts/spot_check_data_accuracy.py --start-date 2026-01-01 --end-date 2026-01-26
```

---

## Skill Requirements

### 1. Flexible Date Range

```bash
/validate-historical              # Default: last 7 days
/validate-historical 14           # Last 14 days
/validate-historical 30           # Last 30 days
/validate-historical season       # Full season (Oct 22 - now)
/validate-historical 2026-01-01 2026-01-15  # Specific range
```

---

## Validation Modes & Options

The skill should support multiple validation modes depending on what the user needs to check.

### Mode 1: `--deep-check` (Cascade Integrity Verification)

**Purpose**: Verify that calculated values (rolling averages, usage rates) actually match recalculation from source data. This catches cascade corruption where gaps caused downstream calculations to be wrong.

**Use case**: After backfilling data, verify the fix actually propagated correctly.

```bash
/validate-historical --deep-check 2026-01-18
/validate-historical --deep-check 2026-01-15 2026-01-20  # Range
```

**What it does**:
1. Picks N random player-game records from the date range
2. For each record, recalculates rolling averages from raw box scores
3. Compares recalculated values to what's stored in `player_daily_cache`
4. Reports mismatches with root cause analysis

**Example output**:
```markdown
## Deep Cascade Integrity Check - 2026-01-18 to 2026-01-20

Samples checked: 20 random player-game records

### Results: 3 MISMATCHES FOUND (85% integrity)

❌ **LeBron James** (2026-01-20)
   - `points_avg_last_5` in cache: 28.4
   - Recalculated from raw: 26.8
   - Difference: 1.6 points (6% error)
   - Root cause: 2026-01-18 game (32 pts) missing from calculation
   - Games used in cache: [Jan 19, 17, 16, 15, 14]
   - Games that should be used: [Jan 19, 18, 17, 16, 15]

❌ **Anthony Davis** (2026-01-19)
   - `rebounds_avg_last_5` in cache: 11.2
   - Recalculated from raw: 12.4
   - Difference: 1.2 rebounds (11% error)
   - Root cause: Same - 2026-01-18 data gap

✅ **Stephen Curry** (2026-01-20) - MATCH
✅ **Kevin Durant** (2026-01-19) - MATCH
... (17 more samples)

### Cascade Impact Summary
- Gap date: 2026-01-18
- Players affected: ~180 (all who played that day)
- Downstream dates with wrong averages: 2026-01-19 through 2026-01-23
- Predictions potentially degraded: ~150

### Remediation
The raw data EXISTS. Regenerate the cache:
```bash
python -m data_processors.analytics.player_daily_cache --start-date 2026-01-18 --end-date 2026-01-25 --force
```
```

**Key queries for deep check**:
```sql
-- Get player's raw box scores for manual recalculation
SELECT
  game_date,
  points,
  rebounds,
  assists,
  minutes
FROM nba_raw.nbac_gamebook_player_stats
WHERE player_id = @player_id
  AND game_date < @check_date
ORDER BY game_date DESC
LIMIT 5;

-- Get what's stored in cache
SELECT
  game_date,
  points_avg_last_5,
  rebounds_avg_last_5,
  assists_avg_last_5
FROM nba_analytics.player_daily_cache
WHERE player_id = @player_id
  AND game_date = @check_date;
```

---

### Mode 2: `--player <name>` (Player-Specific Validation)

**Purpose**: Deep dive into a single player's data history. Useful when you suspect issues with a specific player or want to trace their data quality.

```bash
/validate-historical --player "LeBron James"
/validate-historical --player "lebron_james" --deep-check
```

**What it does**:
1. Shows all games for that player in date range
2. Checks data completeness for each game (raw → analytics → predictions)
3. Validates rolling averages are consistent
4. Identifies any gaps or anomalies

**Example output**:
```markdown
## Player Validation: LeBron James

### Game History (Last 14 Days)

| Date | Opponent | Pts | Reb | Ast | Raw | Analytics | Cache | Prediction |
|------|----------|-----|-----|-----|-----|-----------|-------|------------|
| 01-25 | @GSW | 28 | 8 | 11 | ✅ | ✅ | ✅ | ✅ |
| 01-23 | vs PHX | 31 | 6 | 9 | ✅ | ✅ | ✅ | ✅ |
| 01-21 | @DEN | 25 | 10 | 8 | ✅ | ✅ | ❌ | ⚠️ |
| 01-18 | vs MIA | 32 | 7 | 12 | ✅ | ❌ | ❌ | ❌ |

### Issues Found
- 2026-01-18: Analytics missing (raw exists) - regenerate Phase 3
- 2026-01-21: Cache not updated after 01-18 gap

### Rolling Average Integrity
- points_avg_last_5: ❌ MISMATCH (28.4 vs 26.8 expected)
- rebounds_avg_last_5: ✅ MATCH
- assists_avg_last_5: ❌ MISMATCH (9.2 vs 10.0 expected)
```

---

### Mode 3: `--game <game_id>` (Game-Specific Validation)

**Purpose**: Check all data for a specific game - all players, all stats, all layers.

```bash
/validate-historical --game 0022500123
/validate-historical --game "LAL vs GSW 2026-01-25"
```

**What it does**:
1. Validates all player records exist for that game
2. Compares raw box score to analytics
3. Checks predictions were generated for eligible players
4. Verifies team totals match sum of player stats

---

### Mode 4: `--verify-backfill <date>` (Post-Backfill Verification)

**Purpose**: After running a backfill, verify it succeeded and downstream data is now correct.

```bash
# After backfilling 2026-01-18
/validate-historical --verify-backfill 2026-01-18
```

**What it does**:
1. Confirms the backfilled date now has complete data
2. Runs deep check on downstream dates (next 5-7 days)
3. Verifies rolling averages are now correct
4. Reports if additional regeneration needed

**Example output**:
```markdown
## Backfill Verification: 2026-01-18

### Source Data
✅ Raw box scores: 186 records (6 games)
✅ Analytics: 186 records
✅ Cache updated: Yes

### Downstream Impact Check
Checking rolling averages for dates after 2026-01-18...

| Date | Samples | Integrity | Status |
|------|---------|-----------|--------|
| 01-19 | 10 | 100% | ✅ Fixed |
| 01-20 | 10 | 100% | ✅ Fixed |
| 01-21 | 10 | 90% | ⚠️ 1 mismatch |
| 01-22 | 10 | 100% | ✅ Fixed |

### Result: BACKFILL SUCCESSFUL
- 2026-01-18 data restored
- 39/40 downstream samples now correct
- 1 sample still showing old cached value (may need cache refresh)

### Recommended
```bash
# Force cache refresh for remaining issue
python -m data_processors.analytics.player_daily_cache --date 2026-01-21 --force
```
```

---

### Mode 5: `--coverage-only` (Quick Completeness Report)

**Purpose**: Fast check that just shows data completeness without deep validation. Good for daily monitoring dashboards.

```bash
/validate-historical --coverage-only 30
```

**Output**: Simple table showing record counts per date, no deep analysis.

---

### Mode 6: `--anomalies` (Statistical Outlier Detection)

**Purpose**: Find data that looks suspicious - unusually high/low stats that might indicate data corruption or incorrect joins.

```bash
/validate-historical --anomalies 14
```

**What it flags**:
- Players with >60 points (possible double-counting)
- Players with negative stats (data corruption)
- Players with 0 minutes but non-zero stats (join issue)
- Rolling averages that changed by >50% day-over-day (cache bug)
- Players appearing on wrong teams

---

### Mode 7: `--compare-sources` (Source Reconciliation)

**Purpose**: Compare data across different sources to find discrepancies.

```bash
/validate-historical --compare-sources 2026-01-25
```

**What it compares**:
- NBA.com (nbac_gamebook) vs BallDontLie (bdl_player_boxscores)
- Raw vs Analytics (did transformation preserve data?)
- Analytics vs Cache (did aggregation work correctly?)

---

### Mode 8: `--export <path>` (Save Results)

**Purpose**: Export validation results to JSON for tracking, alerting, or dashboards.

```bash
/validate-historical 14 --export validation-results.json
```

Useful for:
- Automated monitoring
- Historical trend tracking
- Integration with alerting systems

---

## Option Summary Table

| Option | Purpose | Use When |
|--------|---------|----------|
| (default) | Full validation with trends | Weekly health check |
| `--deep-check` | Verify calculations from source | After backfills, suspected cascade |
| `--player <name>` | Single player deep dive | Debugging specific player issues |
| `--game <id>` | Single game validation | Investigating game-specific problems |
| `--verify-backfill` | Confirm backfill succeeded | After running any regeneration |
| `--coverage-only` | Quick completeness scan | Daily monitoring, dashboards |
| `--anomalies` | Find suspicious data | Periodic data quality audit |
| `--compare-sources` | Cross-source reconciliation | Investigating data mismatches |
| `--export <path>` | Save results to file | Automation, tracking |

---

## Recommended Workflows

### After a Pipeline Failure
```bash
# 1. Find gaps
/validate-historical 7

# 2. Backfill the gap
python -m data_processors.analytics.player_game_summary --date 2026-01-18

# 3. Verify the backfill worked AND downstream is fixed
/validate-historical --verify-backfill 2026-01-18
```

### Weekly Health Check
```bash
# Full validation with trends
/validate-historical 7

# If issues found, deep check specific dates
/validate-historical --deep-check 2026-01-18 2026-01-20
```

### Investigating a Specific Prediction Miss
```bash
# Check the player's data
/validate-historical --player "Giannis Antetokounmpo" --deep-check

# Check the game's data
/validate-historical --game 0022500456
```

### Pre-Season Audit
```bash
# Full season coverage check
/validate-historical season --coverage-only

# Deep check random samples across season
/validate-historical season --deep-check
```

### 2. Data Completeness Checks

For each date in range, check:

- **Games scheduled vs processed**: Did we capture all games?
- **Player records**: Expected ~30-40 players per game
- **Analytics populated**: `player_game_summary` has records
- **Predictions generated**: For games that have completed

**BigQuery Queries:**

```sql
-- Games per date
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
ORDER BY game_date;

-- Player records per date
SELECT game_date, COUNT(*) as player_records
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date
ORDER BY game_date;

-- Prediction coverage
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN @start_date AND @end_date
  AND is_active = TRUE
GROUP BY game_date
ORDER BY game_date;
```

### 3. Quality Trend Analysis

Track metrics over time to identify degradation:

- **Spot check accuracy by week**: Is it declining?
- **Usage rate coverage trend**: Consistent or degrading?
- **Prediction coverage trend**: Improving or worsening?

**Identify patterns:**
- Single bad day (pipeline failure, recoverable)
- Gradual decline (code bug, needs investigation)
- Periodic gaps (scheduler issue)

### 4. Gap Detection

Find dates with missing or incomplete data:

```sql
-- Find dates with fewer than expected players
WITH daily_counts AS (
  SELECT
    game_date,
    COUNT(*) as records,
    COUNT(DISTINCT game_id) as games
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  game_date,
  records,
  games,
  records / NULLIF(games, 0) as players_per_game
FROM daily_counts
WHERE records / NULLIF(games, 0) < 25  -- Expect ~30+ per game
ORDER BY game_date;
```

### 5. Cascade Impact Assessment

When gaps are found, assess downstream impact:

1. **Which rolling averages are affected?**
   - Players who played on missing date
   - Their next 5-10 games have wrong averages

2. **Which predictions were potentially degraded?**
   - Games within rolling window of the gap

3. **Is the data recoverable?**
   - Raw data exists? → Can regenerate analytics
   - Raw data missing? → Need to re-scrape (if source still available)

### 6. Actionable Recommendations

For each issue found, provide:

- **Severity**: P1-P5 using same system as `/validate-daily`
- **Impact scope**: How many games/players/predictions affected
- **Remediation**: Specific commands to fix

**Example recommendations:**

```markdown
## Gap Found: 2026-01-15

**Missing**: Phase 3 analytics (player_game_summary has 0 records)
**Raw data**: EXISTS in nba_raw.nbac_gamebook_player_stats
**Impact**:
  - 6 games, ~180 players affected
  - Rolling averages wrong for Jan 16-20 predictions
  - Estimated 30-50 predictions degraded

**Remediation**:
```bash
# Regenerate Phase 3 for specific date
python -m data_processors.analytics.player_game_summary --date 2026-01-15

# Regenerate dependent caches
python -m data_processors.analytics.player_daily_cache --start-date 2026-01-15 --end-date 2026-01-20
```
```

---

## Output Format

```markdown
## Historical Data Validation - [DATE RANGE]

### Summary
[One-line overall assessment]

### Data Completeness

| Date | Games | Players | Analytics | Predictions | Status |
|------|-------|---------|-----------|-------------|--------|
| 2026-01-20 | 7 | 210 | 210 | 180 | ✅ |
| 2026-01-19 | 9 | 270 | 270 | 0 | ⚠️ No predictions |
| 2026-01-18 | 6 | 180 | 45 | 0 | ❌ Analytics gap |

### Quality Trends

| Week | Spot Check Accuracy | Usage Coverage | Prediction Coverage |
|------|---------------------|----------------|---------------------|
| Jan 20-26 | 85% ⚠️ | 35% ❌ | 42% ⚠️ |
| Jan 13-19 | 92% ⚠️ | 88% ✅ | 45% ⚠️ |
| Jan 6-12 | 98% ✅ | 91% ✅ | 48% ⚠️ |

### Gaps Detected

🔴 **P1**: 2026-01-18 - Analytics incomplete (45/180 records)
  - Impact: Rolling averages wrong for 5 subsequent days
  - Cascade: ~150 predictions potentially degraded
  - Raw data: Available
  - Fix: Regenerate Phase 3 for 2026-01-18

🟡 **P2**: 2026-01-19 - No predictions generated
  - Impact: Historical tracking incomplete
  - Cascade: None (predictions are point-in-time)
  - Fix: Cannot regenerate (games already played)

### Cascade Analysis

Players with potentially incorrect rolling averages:
- Games on 2026-01-18: LeBron James, Anthony Davis, ... (180 players)
- Predictions affected: 2026-01-19 through 2026-01-23

### Recommended Actions

1. **IMMEDIATE**: Regenerate 2026-01-18 analytics
   ```bash
   python -m data_processors.analytics.player_game_summary --date 2026-01-18
   ```

2. **FOLLOW-UP**: Regenerate dependent caches
   ```bash
   python -m data_processors.analytics.player_daily_cache --start-date 2026-01-18
   ```

3. **VERIFY**: Re-run spot checks after regeneration
   ```bash
   python scripts/spot_check_data_accuracy.py --start-date 2026-01-18 --samples 10
   ```
```

---

## Key Files to Reference

When creating this skill, explore these files for context:

### Validation Scripts
- `scripts/validate_tonight_data.py` - Main validation logic
- `scripts/spot_check_data_accuracy.py` - Spot check implementation

### Analytics Processors
- `data_processors/analytics/player_game_summary/` - Core analytics
- `data_processors/analytics/player_daily_cache/` - Rolling averages

### Documentation
- `docs/06-testing/SPOT-CHECK-SYSTEM.md` - Spot check architecture
- `docs/02-operations/daily-operations-runbook.md` - Operations procedures
- `.claude/skills/validate-daily/SKILL.md` - Reference skill implementation

### Database Tables
- `nba_raw.*` - Raw scraped data
- `nba_analytics.player_game_summary` - Processed analytics
- `nba_analytics.player_daily_cache` - Rolling averages cache
- `nba_predictions.player_prop_predictions` - Generated predictions
- `nba_predictions.ml_feature_store_v2` - ML features

---

## Implementation Notes

### 1. Skill Structure

Create as: `.claude/skills/validate-historical/SKILL.md`

```yaml
---
name: validate-historical
description: Validate historical data completeness and quality trends
---
```

### 2. Key Differences from `/validate-daily`

| Aspect | `/validate-daily` | `/validate-historical` |
|--------|-------------------|------------------------|
| Focus | Today's pipeline health | Historical data integrity |
| Timing | Run daily | Run weekly or ad-hoc |
| Scope | Single day | Date range |
| Goal | Is pipeline ready? | Is data complete? |
| Actions | Fix today's issues | Backfill gaps |

### 3. Performance Considerations

- Large date ranges = more queries
- Consider sampling for season-wide checks
- Batch queries where possible
- Warn user if range > 30 days (slower)

### 4. Integration with `/validate-daily`

The skills complement each other:
- `/validate-daily` catches issues same-day
- `/validate-historical` catches issues that slipped through
- Together they provide comprehensive data quality assurance

---

## Success Criteria

The skill is complete when it can:

1. ✅ Accept flexible date ranges (days, weeks, season)
2. ✅ Identify gaps in data completeness
3. ✅ Show quality trends over time
4. ✅ Assess cascade impact of gaps
5. ✅ Provide specific remediation commands
6. ✅ Use consistent severity classification (P1-P5)
7. ✅ Produce clear, actionable output

---

## Questions to Consider

1. Should the skill auto-detect the season start date?
2. How to handle dates before the pipeline existed?
3. Should it integrate with the run_history table?
4. Store validation results for trend tracking?

---

## References

- `/validate-daily` skill review: `docs/09-handoff/2026-01-26-VALIDATE-DAILY-REVIEW.md`
- Skill creation guide: `docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md`
- Spot check system: `docs/06-testing/SPOT-CHECK-SYSTEM.md`
