# Session 104 Handoff - Data Quality & Duplicate Team Records Fix

**Date:** 2026-02-03
**For:** Next Claude Code session
**Priority:** HIGH - Outstanding issue: 3 teams missing Feb 2 data

---

## Session Summary

Found and fixed duplicate team records issue in analytics tables. Root cause: Different game_id formats (AWAY_HOME vs HOME_AWAY) caused MERGE to create duplicates instead of updating. Changed PRIMARY_KEY_FIELDS to use game_date instead of game_id.

---

## Fixes Applied

| Fix | File | Description |
|-----|------|-------------|
| Validation check | `.claude/skills/validate-daily/SKILL.md` | Added Phase 0.49 duplicate detection |
| Single-game dedup | `player_game_summary_processor.py:2318-2356` | Added ROW_NUMBER() dedup for team stats |
| Team offense key | `team_offense_game_summary_processor.py:156` | Changed PRIMARY_KEY to ['game_date', 'team_abbr'] |
| Team defense key | `team_defense_game_summary_processor.py:143` | Changed PRIMARY_KEY to ['game_date', 'defending_team_abbr'] |
| Player summary key | `player_game_summary_processor.py:186` | Changed PRIMARY_KEY to ['game_date', 'player_lookup'] |
| Cleanup script | `bin/maintenance/cleanup_team_duplicates.py` | Created to remove duplicates |

---

## Root Cause Analysis

### The Problem Chain

1. **Raw data sources use different game_id formats**
   - `nbac_boxscores`: AWAY_HOME (20260201_LAC_PHX)
   - `gamebook`: HOME_AWAY (20260201_PHX_LAC)

2. **Team processor didn't standardize game_id**
   - One code path standardizes to AWAY_HOME
   - Reconstruction path uses game_id as-is from source

3. **MERGE used `(game_id, team_abbr)` as primary key**
   - Different game_ids = different keys = NEW records
   - Result: 100 duplicate cases since Jan 1, 51% had different stats

4. **Player processor joined to team stats without deduplication**
   - Batch path: Had deduplication (ORDER BY possessions DESC)
   - Single-game path: NO deduplication (arbitrary selection)

5. **Wrong team stats used → Wrong usage_rate stored**
   - LAC: 36 FGA (partial) instead of 83 FGA (full)
   - usage_rate off by ~50% for affected players

### Evidence

```
LAC on Feb 1:
| game_id          | created_at | fg_attempts | possessions |
|------------------|------------|-------------|-------------|
| 20260201_LAC_PHX | 02:05 AM   | 36          | 45          | ← Partial (early processing)
| 20260201_PHX_LAC | 11:30 AM   | 83          | 100         | ← Full game (correct)
```

---

## Cleanup Results

```
team_offense_game_summary: Deleted 123 duplicate records
team_defense_game_summary: Deleted 40 duplicate records
Total: 163 duplicates removed
Remaining duplicates: 0
```

---

## Outstanding Issue: Missing Team Stats for Feb 2

### Symptom

After cleanup, spot checks show "team stats missing" for MEM, MIN, NOP on Feb 2.

### Investigation Results

```sql
-- Teams with player records but no team_offense records for Feb 2
Team | Has player_game_summary | Has team_offense_game_summary
-----|-------------------------|------------------------------
MEM  | YES (18 players)        | NO
MIN  | YES (17 players)        | NO
NOP  | YES (18 players)        | NO
CHA  | YES (18 players)        | YES
```

### Root Cause (likely)

These teams were **never processed** by team_offense processor, not deleted by cleanup. The cleanup script only removes rn > 1 records (duplicates with lower possessions), not primary records.

### Fix Required

Reprocess Feb 2 games for MEM/MIN and NOP/CHA:

```bash
# Trigger Phase 3 reprocessing for specific games
# Option 1: Manual trigger via API
ANALYTICS_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "${ANALYTICS_URL}/process" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"processor_name": "team_offense_game_summary", "game_date": "2026-02-02"}'

# Option 2: Run recovery script
PYTHONPATH=. python orchestration/recovery_processor.py \
  --processor team_offense_game_summary \
  --game-date 2026-02-02
```

---

## Deployment Status

- Phase 3 analytics processors: **DEPLOYED** (revision 00180-tpb)
- Commit: df11f500
- Changes include: All PRIMARY_KEY fixes and single-game deduplication

---

## Spot Check Results (Post-Fix)

Before fix: 49.8% discrepancy on usage_rate for Jericho Sims
After fix: TBD (need to reprocess Feb 2 and re-run spot checks)

The spot check script (`scripts/spot_check_data_accuracy.py`) is working correctly - it detected the issue.

---

## Prevention Mechanisms Added

1. **PRIMARY_KEY_FIELDS changed** - Now uses `game_date` instead of `game_id`
   - Prevents duplicates regardless of game_id format
   - Business logic: One team plays at most one game per day

2. **Daily validation** - Phase 0.49 duplicate detection in `/validate-daily`
   - Alerts on FGA spread > 5 between duplicates
   - CRITICAL alert for spread > 20

3. **Single-game deduplication** - Player processor now uses ROW_NUMBER()
   - Matches batch processing behavior
   - Picks highest possessions record

---

## Next Session Checklist

- [ ] **P0**: Fix missing team stats for MEM, MIN, NOP on Feb 2
  - Trigger Phase 3 reprocessing
  - Verify team_offense records created

- [ ] **P1**: Re-run spot checks on Feb 1-2 data
  - Verify usage_rate calculations are now correct
  - Document pass rate

- [ ] **P1**: Run `/validate-daily` to confirm no duplicate alerts

- [ ] **P2**: Commit all changes
  ```bash
  git add .claude/skills/validate-daily/SKILL.md \
          data_processors/analytics/player_game_summary/player_game_summary_processor.py \
          data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py \
          data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py \
          bin/maintenance/cleanup_team_duplicates.py

  git commit -m "fix: Prevent duplicate team records by using game_date as primary key

  Root cause: Different game_id formats (AWAY_HOME vs HOME_AWAY) caused
  MERGE operations to create duplicates instead of updating existing records.

  - Change PRIMARY_KEY_FIELDS from game_id to game_date in team processors
  - Add single-game deduplication to player_game_summary_processor
  - Create cleanup script for existing duplicates
  - Add duplicate detection to /validate-daily skill

  Cleaned up 163 duplicate records from team tables.

  Session 104: Data Quality & Duplicate Team Records Fix

  Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
  ```

- [ ] **P2**: Consider reprocessing historical data
  - Check for games with partial team stats from Jan 1 onwards
  - May need bulk reprocessing

---

## Files Changed (Uncommitted)

```
M .claude/skills/validate-daily/SKILL.md
M data_processors/analytics/player_game_summary/player_game_summary_processor.py
M data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py
M data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
?? bin/maintenance/cleanup_team_duplicates.py
```

---

## Related Sessions

- **Session 101**: Model bias investigation (parallel track)
- **Session 99**: Data provenance tracking
- **Session 103**: Tier calibration metadata

---

**End of Handoff**
