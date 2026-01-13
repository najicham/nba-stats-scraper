# Session Prompt Template

Use this template when starting a new Claude Code session for daily operations.

---

## Standard Daily Session Prompt

```
Session [N] - Daily Orchestration Check

Start by reading: docs/00-start-here/DAILY-SESSION-START.md

Then read the most recent handoff: docs/09-handoff/

Key verifications for today:
1. [Specific check based on previous session]
2. [Any pending deployments to verify]
3. [Known issues to monitor]

Current time: [Time in ET]
```

---

## Example: Session 28 Prompt (January 13, 2026 Morning)

```
Session 28 - January 13, 2026 Morning

Start by reading: docs/00-start-here/DAILY-SESSION-START.md

Then read the most recent handoff: docs/09-handoff/2026-01-13-SESSION-27-HANDOFF.md

Key verifications for today:
1. Jan 12 overnight processing - expect 6 games in gamebooks AND BDL box scores
2. BDL west coast fix - verify LAL@SAC and CHA@LAC games were captured
3. BettingPros reliability fix - NEEDS DEPLOYMENT (changes in bp_player_props.py)
4. ESPN rosters - confirm still getting 30/30 teams

Deployment pending:
- scrapers/bettingpros/bp_player_props.py (timeout + retry logic)
- scripts/betting_props_recovery.py (new recovery script)
- scripts/check_data_completeness.py (added BettingPros check)

Current time: ~8 AM ET (after post_game_window_3 completed)
```

---

## Quick Reference Paths

| What | Path |
|------|------|
| Daily start guide | `docs/00-start-here/DAILY-SESSION-START.md` |
| Latest handoff | `docs/09-handoff/` (most recent by date) |
| Operations docs | `docs/02-operations/` |
| Active projects | `docs/08-projects/current/` |
| Validation scripts | `scripts/check_data_completeness.py` |
| Recovery scripts | `scripts/betting_props_recovery.py` |

---

## Tips for Effective Handoffs

1. **Be specific** - "verify Jan 12 has 6 games" not "check data"
2. **Include pending deployments** - What code changes need to go out
3. **Note the time** - Helps the session understand what workflows have run
4. **Link to docs** - Point to specific handoff and project docs
