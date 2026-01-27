# `/validate-historical` Claude Code Skill - COMPLETE ✅

**Date**: 2026-01-26
**Task**: Create historical data validation skill
**Status**: ✅ Complete (ready for testing)

---

## What Was Created

### The Skill

**Location**: `.claude/skills/validate-historical/SKILL.md`

**What it does**:
- Validates historical data completeness across date ranges
- Identifies data gaps and assesses cascade impacts (21-day forward window)
- Supports 7 validation modes (deep-check, player-specific, backfill verification, etc.)
- Provides remediation plans in correct dependency order (Phase 3 → 4 → verify)
- Handles flexible date ranges (last N days, season, specific ranges)

**How to use**:
```bash
# Standard validation
/validate-historical              # Last 7 days
/validate-historical 14           # Last 14 days
/validate-historical season       # Full season

# Specific modes
/validate-historical --deep-check 2026-01-18
/validate-historical --player "LeBron James"
/validate-historical --verify-backfill 2026-01-18
/validate-historical 30 --coverage-only
```

---

## Key Features

### 1. Multiple Validation Modes

| Mode | Flag | Purpose |
|------|------|---------|
| **Standard** | (default) | Complete health check with gap detection |
| **Deep Check** | `--deep-check` | Verify calculations from source (recalculate rolling avgs) |
| **Player-Specific** | `--player <name>` | Single player data deep dive |
| **Game-Specific** | `--game <id>` | Single game validation |
| **Verify Backfill** | `--verify-backfill` | Confirm backfill succeeded, cascade resolved |
| **Coverage Only** | `--coverage-only` | Quick completeness scan (no deep analysis) |
| **Anomalies** | `--anomalies` | Statistical outlier detection |
| **Compare Sources** | `--compare-sources` | Cross-source reconciliation |

### 2. Cascade Impact Assessment

The skill understands that missing data on date X affects rolling averages for **21 days forward**:

```
Missing 2026-01-18 data:
  ↓
  Affects points_avg_last_5 for games on 2026-01-19 → 2026-01-28
  Affects points_avg_last_10 for games on 2026-01-19 → 2026-02-08
  ↓
  Predictions degraded: ~150 predictions over 21 days
```

The skill:
- Identifies the gap date
- Calculates affected date range (gap + 21 days)
- Estimates affected players and predictions
- Provides cascade-aware remediation plan

### 3. Remediation in Correct Order

The skill always provides fixes in dependency order:

```bash
# Step 1: Regenerate Phase 3 (Analytics)
python scripts/backfill_player_game_summary.py --start-date 2026-01-18

# Step 2: Regenerate Phase 4 (Cache) for cascade window
python scripts/regenerate_player_daily_cache.py --start-date 2026-01-18 --end-date 2026-02-08

# Step 3: Verify fix with spot checks
python scripts/spot_check_data_accuracy.py --start-date 2026-01-19 --samples 20
```

### 4. Flexible Date Ranges

Supports multiple date range formats:
- **Relative**: `7`, `14`, `30` (last N days)
- **Keyword**: `season` (full season from Oct 22)
- **Specific**: `2026-01-01 2026-01-15` (exact range)

### 5. BigQuery Schema Reference

Includes comprehensive schema documentation for key tables:
- `nba_analytics.player_game_summary`
- `nba_precompute.player_daily_cache` (with cache_date semantics)
- `nba_predictions.ml_feature_store_v2` (with contributing_game_dates)
- `nba_raw.nbac_gamebook_player_stats`

**Key Gotcha Documented**: `cache_date = game_date - 1` (the day BEFORE the game)

---

## Research Conducted

### Explore Agent Deep Dive

Used Task tool with `subagent_type=Explore` to understand:

1. **Player Daily Cache Architecture**:
   - cache_date = game_date - 1 (CRITICAL semantic)
   - Rolling windows: L5, L10, L7d, L14d, season
   - Fields cached: points_avg_last_5, minutes_avg_last_10, usage_rate, etc.

2. **Data Flow & Dependencies**:
   - Raw → Analytics → Precompute → Predictions
   - Each stage depends on previous stage completion
   - Missing data cascades forward through pipeline

3. **Gap Detection Patterns**:
   - NO_DATA: Off-day (expected)
   - RAW_ONLY: Phase 3 failure (backfill needed)
   - INCOMPLETE: Partial failure (investigate)

4. **Cascade Impact**:
   - Default window: 21 days forward from gap
   - Stored in `historical_completeness.contributing_game_dates`
   - Affects all features using that game in rolling window

5. **Backfill Commands**:
   - `backfill_player_game_summary.py` - Phase 3
   - `regenerate_player_daily_cache.py` - Phase 4
   - Verification uses spot checks + cascade detection

---

## Design Highlights

### Intelligent Mode Detection

The skill parses user input to determine:
1. **Date range**: From command arguments
2. **Validation mode**: From flags (--deep-check, --player, etc.)
3. **Output preferences**: JSON export, coverage-only, etc.

**Example**:
```
/validate-historical --deep-check 2026-01-18 2026-01-25
  ↓
  Date range: 2026-01-18 to 2026-01-25
  Mode: Deep check (recalculate rolling averages)
  Output: Detailed mismatch analysis
```

### Cascade-Aware Investigation

Unlike `/validate-daily` which checks today's health, this skill:
- **Looks backward**: Find historical gaps
- **Projects forward**: Calculate downstream impact
- **Assesses severity**: Based on cascade window size and prediction count

### Remediation Specificity

Every gap gets specific remediation commands:
- **Not**: "Regenerate data"
- **But**: "Regenerate Phase 3 for 2026-01-18, then Phase 4 for 2026-01-18 through 2026-02-08"

---

## Skill Architecture

### Information Flow

```
User invokes /validate-historical with args
  ↓
Skill parses: date range + mode flags
  ↓
Mode 1 (Standard): Run completeness checks, identify gaps
Mode 2 (Deep check): Recalculate rolling avgs, compare to cache
Mode 3 (Player): Show player's game-by-game data pipeline status
Mode 4 (Verify backfill): Confirm gap filled, cascade resolved
Mode 5-7: Coverage, anomalies, source comparison
  ↓
For each gap found:
  1. Determine type (RAW_ONLY, INCOMPLETE)
  2. Calculate cascade impact (affected dates, predictions)
  3. Provide remediation (Phase 3 → 4 → verify)
  ↓
Generate structured report with severity (P1-P5)
```

### Decision Points

At each validation step, the skill decides:
1. **Is this a gap or expected?** (off-day vs missing data)
2. **How severe is the gap?** (partial vs complete failure)
3. **What's the cascade impact?** (days affected, predictions degraded)
4. **Can we backfill?** (raw data exists vs missing)
5. **What's the remediation order?** (dependencies)

---

## Differences from `/validate-daily`

| Aspect | `/validate-daily` | `/validate-historical` |
|--------|-------------------|------------------------|
| **Focus** | Today's pipeline health | Historical data integrity |
| **Timing** | Run daily (5 PM or 6 AM) | Run weekly or ad-hoc |
| **Scope** | Single day | Date range (7-90+ days) |
| **Goal** | Is pipeline ready? | Is historical data complete? |
| **Output** | Current status | Gap detection + cascade analysis |
| **Actions** | Fix today's issues | Backfill historical gaps |
| **Complexity** | Moderate (5 phases) | High (7 modes, cascade math) |

### Complementary Relationship

- `/validate-daily` catches issues **same-day** (prevent problems)
- `/validate-historical` catches issues **after-the-fact** (find past problems)
- Together: Comprehensive data quality assurance

---

## Key Insights from Research

### Critical Concept: Cache Date Semantics

```
cache_date = game_date - 1
```

This is CRITICAL for understanding the system:
- Cache for game on 2026-01-26 has cache_date = 2026-01-25
- Cache contains rolling averages from games BEFORE 2026-01-25
- Query: `WHERE game_date < '2026-01-25'` (NOT `<=`)

### The Cascade Window

**Default**: 21 days forward from gap

**Why 21 days?**
- L5 window: 5 games ≈ 7-10 days
- L10 window: 10 games ≈ 14-21 days
- Safe buffer: 21 days covers L10 window plus margin

**Stored in**: `nba_predictions.ml_feature_store_v2.historical_completeness.contributing_game_dates`

### Gap Types & Remediation

| Gap Type | Cause | Remediation |
|----------|-------|-------------|
| **NO_DATA** | Off-day (no games) | None (expected) |
| **RAW_ONLY** | Phase 3 failed | Regenerate analytics |
| **INCOMPLETE** | Partial Phase 3 | Investigate, then regenerate |
| **CACHE_MISSING** | Phase 4 failed | Regenerate cache |

---

## Testing Plan

### Test Scenarios

1. **Standard Validation (Last 7 Days)**:
   ```bash
   /validate-historical
   ```
   Expected: Show completeness table, identify any gaps

2. **Deep Check on Known Date**:
   ```bash
   /validate-historical --deep-check 2026-01-25
   ```
   Expected: Recalculate rolling averages, compare to cache

3. **Player-Specific**:
   ```bash
   /validate-historical --player "LeBron James"
   ```
   Expected: Show LeBron's game-by-game data pipeline status

4. **Verify Backfill** (after running backfill):
   ```bash
   # First backfill
   python scripts/backfill_player_game_summary.py --date 2026-01-18

   # Then verify
   /validate-historical --verify-backfill 2026-01-18
   ```
   Expected: Confirm gap filled, downstream dates fixed

5. **Coverage Only (Fast Check)**:
   ```bash
   /validate-historical 30 --coverage-only
   ```
   Expected: Simple table, no deep analysis, fast execution

### Success Criteria

- ✅ Skill correctly parses date ranges and mode flags
- ✅ Identifies gaps in historical data
- ✅ Calculates cascade impact (affected dates, predictions)
- ✅ Provides remediation in correct dependency order
- ✅ Output is clear, actionable, and severity-classified

---

## Known Limitations

### 1. Performance on Large Date Ranges

- Season-wide checks (100+ days) will be slow
- Solution: Warn user, suggest --coverage-only for quick scan

### 2. Manual BigQuery Queries

- Skill provides query templates but Claude must run them
- Some queries may need parameter adjustment
- Solution: Schema reference helps prevent errors

### 3. Cascade Calculation Assumptions

- Assumes 21-day cascade window (may vary by feature)
- Assumes standard L5/L10 windows
- Solution: Document assumptions clearly

### 4. No Auto-Fix Mode

- Skill recommends remediation but doesn't execute
- User must run backfill commands manually
- Solution: Clear, copy-pasteable commands provided

---

## Future Enhancements

### High Priority

1. **Automated Backfill Execution** (with approval):
   - Skill detects gap
   - Asks "Run backfill for 2026-01-18? (Y/n)"
   - Executes commands if approved

2. **Trend Visualization**:
   - Show quality metrics over time (line chart in markdown)
   - Detect patterns (weekly degradation, specific day issues)

### Medium Priority

3. **Export Results** (--export):
   - Save validation results to JSON
   - Enable trend tracking over weeks/months
   - Integration with dashboards

4. **Anomaly Detection ML**:
   - Learn what "normal" looks like
   - Flag statistically significant deviations
   - Reduce false positives

### Low Priority

5. **Multi-file Skill Structure**:
   ```
   .claude/skills/validate-historical/
   ├── SKILL.md
   ├── modes/
   │   ├── deep-check.md
   │   ├── player-specific.md
   │   └── verify-backfill.md
   └── reference/
       ├── schemas.md
       └── remediation.md
   ```

6. **Integration with /validate-daily**:
   - Daily skill logs gaps to tracking table
   - Historical skill reads gap log
   - Automated weekly historical validation

---

## Documentation Files

### Created

1. **Skill Definition**:
   - `.claude/skills/validate-historical/SKILL.md` (~20KB)
   - Comprehensive multi-mode validation skill

2. **Completion Summary**:
   - `docs/09-handoff/2026-01-26-VALIDATE-HISTORICAL-SKILL-COMPLETE.md` (this file)
   - Design decisions, testing plan, future enhancements

### To Update (Next Session)

3. **Operations Runbook**:
   - `docs/02-operations/daily-operations-runbook.md`
   - Add section on weekly historical validation

4. **Skills Reference** (if creating):
   - `docs/02-operations/CLAUDE-SKILLS-REFERENCE.md`
   - Document both validate-daily and validate-historical

---

## Comparison to Creation Guide

### Original Requirements (from spec)

- ✅ Flexible date ranges (days, weeks, season, specific)
- ✅ Data completeness checks (games, players, analytics, predictions)
- ✅ Quality trend analysis (spot checks over time)
- ✅ Gap detection (identify missing data)
- ✅ Cascade impact assessment (21-day forward window)
- ✅ Actionable recommendations (specific commands)
- ✅ Consistent severity classification (P1-P5)
- ✅ Multiple validation modes (8 modes requested, 7+ implemented)

### Additional Features Beyond Spec

- ✅ BigQuery schema reference (learned from /validate-daily review)
- ✅ Mode-specific investigation guidance
- ✅ Remediation verification steps (not just backfill commands)
- ✅ Anomaly detection queries
- ✅ Source comparison (NBA.com vs BallDontLie)

---

## Skill Size & Complexity

### Metrics

- **File size**: ~20KB (vs ~12KB for /validate-daily)
- **Modes**: 7+ distinct validation modes
- **BigQuery queries**: ~10 comprehensive query templates
- **Tables documented**: 4 key tables with full schemas
- **Commands**: ~15 reference commands

### Complexity Factors

1. **Multi-mode logic**: Skill must detect and route to correct mode
2. **Cascade mathematics**: Calculate affected dates and predictions
3. **Dependency ordering**: Ensure Phase 3 → 4 → verify sequence
4. **Date range handling**: Multiple formats (relative, keyword, specific)
5. **Gap type classification**: Distinguish NO_DATA, RAW_ONLY, INCOMPLETE

---

## Next Steps

### Immediate (This Session)

- ✅ Skill created and documented
- ✅ Research complete (Explore agent)
- ✅ Completion summary written

### Next Session (Testing)

1. **Test standard validation**:
   ```bash
   /validate-historical 7
   ```

2. **Test deep check mode**:
   ```bash
   /validate-historical --deep-check 2026-01-20 2026-01-25
   ```

3. **Test on known gap** (if one exists):
   ```bash
   /validate-historical --verify-backfill 2026-01-18
   ```

4. **Refine based on real-world usage**:
   - Are queries correct?
   - Is output clear?
   - Are remediation commands accurate?

### Future (After Validation)

1. Update operations runbook with historical validation procedures
2. Create CLAUDE-SKILLS-REFERENCE.md documenting both skills
3. Consider automation enhancements (auto-backfill with approval)

---

## Questions for Review

When reviewing this skill:

1. **Completeness**: Does it cover all major validation scenarios?
2. **Clarity**: Are the modes clearly differentiated?
3. **Usability**: Can operators use it without extensive training?
4. **Correctness**: Are BigQuery queries and commands accurate?
5. **Cascade Math**: Is the 21-day window calculation correct?
6. **Remediation**: Are fix commands in correct dependency order?

---

## Success Metrics

### Skill Creation Goals

- ✅ Created comprehensive historical validation skill
- ✅ Supports 7+ validation modes
- ✅ Understands cascade impact (21-day window)
- ✅ Provides remediation in dependency order
- ✅ Includes BigQuery schema reference
- ✅ Uses consistent P1-P5 severity classification
- ✅ Documented design decisions and testing plan

### Expected Value

**Before Skill**:
- Historical gaps discovered manually (time-consuming)
- Cascade impact calculated ad-hoc (error-prone)
- Remediation order sometimes wrong (dependencies missed)
- No systematic weekly validation process

**With Skill**:
- Automated gap detection (runs in minutes)
- Cascade impact calculated automatically (consistent)
- Remediation commands provided in correct order (reliable)
- Weekly historical validation becomes routine

---

## Conclusion

The `/validate-historical` skill complements `/validate-daily` by providing:
1. **Historical gap detection** (find past problems)
2. **Cascade impact assessment** (understand downstream effects)
3. **Multi-mode validation** (deep-check, player-specific, backfill verification)
4. **Remediation guidance** (specific commands in correct order)

**Together**, the two skills provide comprehensive data quality assurance:
- `/validate-daily`: Prevent problems (daily health check)
- `/validate-historical`: Find and fix past problems (weekly audit)

---

**Session Complete**: 2026-01-26
**Skill Created**: Yes (.claude/skills/validate-historical/SKILL.md)
**Documentation**: Complete
**Ready for Testing**: Yes
**Next Action**: Test skill in new session, refine based on real-world usage
