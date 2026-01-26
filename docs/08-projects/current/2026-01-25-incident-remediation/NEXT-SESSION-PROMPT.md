# Next Session Prompt - Copy/Paste This

Copy the prompt below to continue work on the 2026-01-25 incident remediation:

---

## Prompt for New Session

```
I'm continuing work on the 2026-01-25 incident remediation. A previous session fixed the GSW/SAC player extraction bug, but there's remaining work to complete.

## Current Status (40% Complete)

### ✅ Completed
1. Fixed GSW/SAC extraction bug in player_loaders.py:305 (commit 533ac2ef)
2. Verified all 12 teams now extract correctly (was 10/12)
3. Comprehensive documentation created

### ⚠️ Remaining Tasks

**Task 1 (HIGH PRIORITY - 15-30 min):**
Fix table_id bug preventing data from being saved to BigQuery.

Error: `ValueError: table_id must be a fully-qualified ID in standard SQL format, got nba-props-platform.nba_analytics.nba_analytics.upcoming_player_game_context`
(Note the duplicate "nba_analytics")

Location: `data_processors/analytics/operations/bigquery_save_ops.py:125`

**Task 2 (MEDIUM - 5-10 min):**
After fixing Task 1, rerun the processor to populate GSW/SAC data:
```bash
SKIP_COMPLETENESS_CHECK=true python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor 2026-01-25 --skip-downstream-trigger
```

Expected: 14 → 16 teams in `nba_analytics.upcoming_player_game_context`

**Task 3 (LOW - 5 min when unblocked):**
Retry missing PBP games (currently blocked by CloudFront IP ban):
- Game 0022500651 (DEN @ MEM)
- Game 0022500652 (DAL @ MIL)

## Documentation Location
All details are in: `docs/08-projects/current/2026-01-25-incident-remediation/`

Key files:
- **REMAINING-WORK.md** - Detailed task breakdown with all context
- **GSW-SAC-FIX.md** - What was fixed in previous session
- **SESSION-SUMMARY.md** - Quick overview of previous work
- **STATUS.md** - Full project status

## What I Need You To Do

1. Read REMAINING-WORK.md for complete context
2. Fix the table_id bug in bigquery_save_ops.py:125
3. Test the fix with a dry run
4. Rerun the processor for 2026-01-25
5. Verify GSW/SAC data appears in the database

Start by investigating the table_id bug. The issue is that "nba_analytics" appears twice in the fully-qualified table name.
```

---

## Alternative: Quick Start Without Context

If you just want to dive straight into the work without reading docs first:

```
Fix the BigQuery save operation bug in the upcoming_player_game_context processor.

Error: `ValueError: table_id must be a fully-qualified ID in standard SQL format, got nba-props-platform.nba_analytics.nba_analytics.upcoming_player_game_context`

The "nba_analytics" dataset name appears twice. This is blocking us from saving player context data to BigQuery.

File: `data_processors/analytics/operations/bigquery_save_ops.py:125`

After fixing, we need to rerun:
```bash
SKIP_COMPLETENESS_CHECK=true python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor 2026-01-25 --skip-downstream-trigger
```

Context: This is part of 2026-01-25 incident remediation. Full docs in `docs/08-projects/current/2026-01-25-incident-remediation/REMAINING-WORK.md`
```

---

## For Urgent Focus: Table ID Bug Only

If you only have time for the critical blocker:

```
Urgent fix needed: BigQuery save operation failing in upcoming_player_game_context processor.

Error message:
ValueError: table_id must be a fully-qualified ID in standard SQL format, e.g., "project.dataset.table_id", got nba-props-platform.nba_analytics.nba_analytics.upcoming_player_game_context

Problem: "nba_analytics" appears twice in the table ID.

File to fix: `data_processors/analytics/operations/bigquery_save_ops.py` line 125

Context: The processor successfully extracts 358 players and calculates context for 227 players, but the save operation fails at the very end due to malformed table_id.

Please investigate how table_id is constructed in the save_analytics() method and fix the duplicate dataset name.
```

---

## Choose Your Prompt

- **Full Context Prompt** (recommended) - Use the first prompt for complete understanding
- **Quick Start Prompt** - Use the second if you want to jump in quickly
- **Urgent Focus Prompt** - Use the third if you only have time for the critical bug

All three prompts will work with Claude Code to continue the remediation work.
