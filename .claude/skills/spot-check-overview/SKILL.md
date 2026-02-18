# Spot Check Skills Overview

Player data validation toolkit for detecting gaps, explaining absences, and tracking downstream contamination.

## The Five Skills

| Skill | Scope | When to Use |
|-------|-------|-------------|
| `/spot-check-player` | One player | Investigating specific player issues |
| `/spot-check-gaps` | All players | Weekly audit, post-backfill verification |
| `/spot-check-date` | One date | After reports of missing data for a game day |
| `/spot-check-team` | One team | After trades, team-specific issues |
| `/spot-check-cascade` | Downstream | Before/after backfilling to understand impact |

## Standard Workflow

```
Weekly Audit:
┌─────────────────────────────────────────────────────────────────────┐
│  1. /spot-check-gaps                                                │
│     └── Find all unexplained gaps system-wide                      │
│                                                                     │
│  2. For each ERROR_HAS_MINUTES:                                     │
│     └── /spot-check-player <name> 20                               │
│         └── Deep dive to understand why                            │
│                                                                     │
│  3. If pattern found (e.g., registry issue):                       │
│     └── Fix root cause (add alias, etc.)                           │
│                                                                     │
│  4. After fix, for each backfill:                                  │
│     └── /spot-check-cascade <player> <date> --backfilled           │
│         └── Generate remediation commands                          │
│                                                                     │
│  5. Run remediation, then verify:                                  │
│     └── /spot-check-gaps (should show improvement)                 │
└─────────────────────────────────────────────────────────────────────┘

After Specific Incident:
┌─────────────────────────────────────────────────────────────────────┐
│  "Player X is missing from the website"                            │
│     └── /spot-check-player <name> 20                               │
│                                                                     │
│  "Yesterday's games look incomplete"                               │
│     └── /spot-check-date <date>                                    │
│                                                                     │
│  "Lakers data seems wrong after trade"                             │
│     └── /spot-check-team LAL 15                                    │
└─────────────────────────────────────────────────────────────────────┘
```

## Severity Levels

All skills use consistent severity classification:

| Severity | Meaning | Action Required |
|----------|---------|-----------------|
| `ERROR` | Data bug - player played but missing from analytics | Fix immediately |
| `WARNING` | Potential issue - needs investigation | Investigate |
| `INFO` | Expected situation - trade, injury, DNP | None |
| `OK` | No issues found | None |

## Gap Types

| Gap Type | Severity | Meaning | Typical Cause |
|----------|----------|---------|---------------|
| `ERROR_HAS_MINUTES` | ERROR | Player has boxscore minutes but no analytics | Registry mismatch |
| `ERROR_NOT_IN_BOXSCORE` | WARNING | Player missing from raw data entirely | Trade window, data issue |
| `DNP_NO_INJURY` | INFO | Player in boxscore with 0 min, no injury report | Coach's decision |
| `INJURY_REPORT` | OK | Player has injury report explaining absence | Expected |

## Common Root Causes

### 1. Registry Mismatch (Most Common)
**Symptom**: ERROR_HAS_MINUTES for specific players
**Cause**: BDL API name doesn't match registry (e.g., `hugogonzlez` vs `hugogonzalez`)
**Fix**: Add alias in registry, reprocess historical dates

### 2. Trade Window
**Symptom**: Player missing games between teams
**Cause**: Gap between last game on old team and first game on new team
**Fix**: None needed - expected behavior

### 3. Scraper Failure
**Symptom**: Multiple players missing for specific date
**Cause**: NBA.com or BDL API was down
**Fix**: Run backfill for that date

### 4. New Player Not in Registry
**Symptom**: Rookie or call-up missing from analytics
**Cause**: Player not yet added to registry
**Fix**: Add player to registry, reprocess

## Data Limitations

| Data Source | Coverage | Notes |
|-------------|----------|-------|
| `nbac_injury_report` | Dec 19, 2025+ | Earlier dates have incomplete data |
| `nbac_player_movement` | Through Aug 2025 | No current season trades |
| `bdl_player_boxscores` | Full season | Primary source for player games |

## Quick Commands

```bash
# Weekly audit
/spot-check-gaps

# Deep dive on player
/spot-check-player lebron_james 20

# Check yesterday
/spot-check-date 2026-01-25

# Check team after trade
/spot-check-team GSW 15

# Analyze backfill impact
/spot-check-cascade jimmybutler 2026-01-15 --backfilled
```

## Integration with Daily Validation

The `/validate-daily` skill includes Phase 3B which runs a simplified spot check:
- Finds players in boxscores with minutes but missing from analytics
- Flags ERROR if any found
- Suggests `/spot-check-player` for investigation

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/validation/guides/PLAYER-SPOT-CHECK-GUIDE.md` | Detailed operational guide |
| `docs/08-projects/current/data-lineage-integrity/SPOT-CHECK-INTEGRATION.md` | Architecture integration |
| `docs/09-handoff/2026-01-26-SPOT-CHECK-HANDOFF.md` | Session handoff with findings |
