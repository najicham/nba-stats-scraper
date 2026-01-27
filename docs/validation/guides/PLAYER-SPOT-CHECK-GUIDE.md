# Player Spot Check Guide

**Purpose**: Verify player game history, detect missing data, and ensure player absences are properly explained
**Skills**: `/spot-check-player`, `/spot-check-gaps`, `/spot-check-date`, `/spot-check-team`
**Last Updated**: 2026-01-26
**Version**: 2.0 (Added cascade tracking and multiple spot-check skills)

---

## Overview

The player spot check validates that a player's game history is complete and that any absences are properly explained. It answers the question: **"For every game this player's team played, can we account for whether the player played or not?"**

**Skill reference**: `.claude/skills/spot-check-overview.md` - Start here for workflow guidance

### Why This Matters

The website displays a player's "last 10 games" with an injury icon ("I") for games they missed due to injury. If:

1. **NBA.com scraper fails** - Injury flags are missing
2. **BDL fallback is used** - BDL boxscores don't include injury reasons
3. **Player appears missing** - User sees an unexplained gap

This creates a poor user experience and can affect prediction quality.

---

## What Gets Checked

### 1. Player Game Records

For each game in the requested window, check if a record exists in `player_game_summary`:

| Field | Purpose |
|-------|---------|
| `game_date` | When the game occurred |
| `points`, `minutes_played` | Basic stats (null = didn't play) |
| `is_active` | Whether player was active for the game |
| `player_status` | Status code (active, out, dnp-coach, etc.) |
| `primary_source_used` | Which data source provided the record |

### 2. Team Schedule

Cross-reference against the team's actual schedule to find games where:
- Team played but player has no `player_game_summary` record
- These are the "missing games" that need explanation

### 3. Injury Reports (for Missing Games)

Check both injury data sources:

| Source | Table | Notes |
|--------|-------|-------|
| **NBA.com** (primary) | `nba_raw.nbac_injury_report` | Official injury report PDF, scraped daily |
| **BDL** (backup) | `nba_raw.bdl_injuries` | Ball Don't Lie API, less detailed |

Injury statuses: `Out`, `Doubtful`, `Questionable`, `Probable`, `Available`

### 4. Raw Boxscores (DNP Detection)

Check `nba_raw.bdl_player_boxscores` for players who appeared in the boxscore with 0 minutes (Did Not Play - Coach's Decision).

### 5. Roster Changes (Trade Detection)

Query `player_game_summary` for team changes to identify:
- Mid-season trades
- Waiver pickups
- Two-way contract shuffles

---

## Scenarios Detected

### EXPECTED - Injury Properly Flagged

**Situation**: Player missing from `player_game_summary` but has injury report entry.

```
2026-01-22 vs BOS: Player listed OUT (Knee - rest) in nbac_injury_report
Status: EXPECTED - Injury properly flagged
```

**Action**: None required. System is working correctly.

---

### WARNING - DNP Without Injury Flag

**Situation**: Player has 0 minutes in `bdl_player_boxscores` but NO injury report.

```
2026-01-20 vs MIA: Player in boxscore with 0 minutes, no injury report found
Status: WARNING - May be missing injury data
```

**Possible causes**:
- NBA.com scraper failed for that day
- Player was a late scratch (injury report already published)
- Coach's decision not listed on injury report

**Action**:
1. Check if NBA.com scraper ran successfully for that date
2. Verify injury report was captured
3. May need manual review

---

### ERROR - Data Gap

**Situation**: Player's team played, player NOT in injury report, player NOT in raw boxscores.

```
2026-01-18 vs DEN: Team played, no player record, no injury report, no boxscore entry
Status: ERROR - Likely data collection issue
```

**Possible causes**:
- Scraper failure (both NBA.com and BDL)
- Player lookup mismatch (name normalization issue)
- Game data not yet processed

**Action**:
1. Check scraper logs for that date
2. Verify raw data exists in GCS
3. Check player name normalization
4. May require manual backfill

---

### INFO - Trade/Roster Change

**Situation**: Player changed teams during the window. Missing games are from the "gap" between teams.

```
Player changed teams:
- LAL: first_game 2025-10-22
- WAS: first_game 2026-01-15

2026-01-12 to 2026-01-14: Trade window (expected gap)
Status: INFO - Normal for mid-season acquisition
```

**Action**: None required. Gap is expected during trade processing.

---

### WARNING - Inconsistent Sources

**Situation**: Player has injury status in BDL but NOT in NBA.com (or vice versa).

```
2026-01-19 vs OKC:
- nbac_injury_report: No record
- bdl_injuries: OUT (Ankle)
Status: WARNING - NBA.com scraper may have missed this
```

**Possible causes**:
- NBA.com PDF parsing failed
- Timing issue (BDL updated, NBA.com not yet)
- Player added late to injury report

**Action**:
1. Check NBA.com scraper logs
2. Verify PDF was downloaded and parsed
3. Review injury parser confidence scores

---

## Usage

### Basic Usage

```
/spot-check-player lebron_james
```

Checks LeBron's last 10 games (default).

### Extended Window

```
/spot-check-player anthony_davis 20
```

Checks Anthony Davis's last 20 games.

### Good Test Cases

| Player Type | Example | Why |
|-------------|---------|-----|
| Recent injury | Star who missed games | Verify injury flags captured |
| Traded player | Mid-season acquisition | Verify trade gap handling |
| Ironman player | Player who plays every game | Should have no gaps |
| Two-way player | G-League assignment | May have complex roster status |

---

## Sample Output

```
=== PLAYER SPOT CHECK: LeBron James ===
Team: LAL
Period: Last 10 games (2026-01-16 to 2026-01-26)

GAME HISTORY:
| Date       | Opp | Pts | Min  | Status | Injury Flag |
|------------|-----|-----|------|--------|-------------|
| 2026-01-26 | GSW | 28  | 35.2 | active | -           |
| 2026-01-24 | PHX | 31  | 36.1 | active | -           |
| 2026-01-22 | -   | -   | -    | OUT    | Knee (rest) |
| 2026-01-20 | DEN | 25  | 33.5 | active | -           |
| 2026-01-18 | SAC | 22  | 32.0 | active | -           |
| 2026-01-16 | LAC | 35  | 38.2 | active | -           |
...

MISSING GAME ANALYSIS:
- 2026-01-22 vs BOS: Player listed OUT (Knee - rest) in nbac_injury_report
  Status: EXPECTED - Injury properly flagged

POTENTIAL ISSUES:
- None found

DATA QUALITY:
- 9/10 games have records
- 1/10 games missing (injury - expected)
- Injury coverage: 100% (all absences have injury report)
```

---

## Data Sources

### Primary Tables

| Table | Dataset | Purpose |
|-------|---------|---------|
| `player_game_summary` | `nba_analytics` | Player game records with stats |
| `v_nbac_schedule_latest` | `nba_raw` | Team game schedule |
| `nbac_injury_report` | `nba_raw` | NBA.com injury reports (primary) |
| `bdl_injuries` | `nba_raw` | BDL injury data (backup) |
| `bdl_player_boxscores` | `nba_raw` | Raw boxscores for DNP detection |
| `nbac_player_movement` | `nba_raw` | Trades, signings, waivers |

### GCS Storage Paths

| Data | GCS Path | Format |
|------|----------|--------|
| Injury Report PDF | `nba-com/injury-report-pdf/{date}/{hour24}/{timestamp}.pdf` | Binary PDF |
| Injury Report Data | `nba-com/injury-report-data/{date}/{hour24}/{timestamp}.json` | Parsed JSON |
| Player Movement | `nba-com/player-movement/{date}/{timestamp}.json` | JSON |

### Data Flow

```
NBA.com Injury PDF ──→ GCS (raw) ──→ Parser ──→ nbac_injury_report
                                                        │
                                                        ├──→ player_game_summary
NBA.com Gamebook ────→ nbac_gamebook_player_stats ─────┤    (is_active, player_status)
                                                        │
BDL API ─────────────→ bdl_player_boxscores ───────────┘

NBA.com Transactions ──→ nbac_player_movement ──→ Trade detection
```

### Injury Report Scraper

**File**: `scrapers/nbacom/nbac_injury_report.py`

**URL Pattern**:
- Pre-Dec 23, 2025: `https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{hour}{period}.pdf`
- Post-Dec 23, 2025: `https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{hour}_{minute}{period}.pdf`

**Backfill Job**: `backfill_jobs/scrapers/nbac_injury/nbac_injury_scraper_backfill.py`

```bash
# Backfill specific dates
gcloud run jobs execute nbac-injury-backfill \
  --args="--dates=2025-11-13,2025-11-16" \
  --region=us-west2
```

---

## Integration with Data Lineage

The spot check is part of the broader **data lineage integrity** effort:

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Prevention** | ProcessingGate | Block processing when dependencies incomplete |
| **Prevention** | WindowCompletenessValidator | Verify N games exist before computing rolling avg |
| **Quality** | Quality metadata columns | Track completeness scores on records |
| **Validation** | `/spot-check-player` | Verify player history is complete and explainable |
| **Remediation** | Backfill procedures | Fix gaps when detected |

### Key Principle

**"NULL > Wrong Value"** - If we can't verify a player's status for a game, it's better to show nothing than to show incorrect data.

---

## Troubleshooting

### "Player not found"

```
Error: No records found for player_lookup 'lebronjames'
```

**Fix**: Use underscore format: `lebron_james`

### "Team schedule empty"

```
Warning: No team games found for LAL in last 60 days
```

**Possible causes**:
- Off-season (no games)
- Team lookup mismatch
- Schedule data not loaded

### "Injury report empty but player missing"

This could indicate:
1. NBA.com scraper failure
2. PDF parsing error
3. All-Star break or other schedule gap

Check scraper logs:
```bash
grep "nbac_injury_report" logs/scrapers/*.log | tail -20
```

---

## Spot Check Skill Family

Four complementary skills for different use cases:

| Skill | Use Case | Scope | When to Use |
|-------|----------|-------|-------------|
| `/spot-check-player` | Deep dive on one player | Single player, N games | Investigating specific player issues |
| `/spot-check-gaps` | System-wide audit | All players, date range | Weekly quality audit, post-backfill |
| `/spot-check-date` | Single day audit | All players, one date | After reports of missing data |
| `/spot-check-team` | Team roster audit | One team, N games | After trades, team-specific issues |

### Recommended Workflow

1. **Weekly**: Run `/spot-check-gaps` to find all issues
2. **Daily**: Morning validation includes yesterday's game check
3. **On demand**: Use `/spot-check-player`, `/spot-check-date`, or `/spot-check-team` for investigation

---

## Data Coverage Findings (Jan 2026)

### Injury Report Data Gap

| Period | Status | Impact |
|--------|--------|--------|
| Oct 22 - Nov 13, 2025 | No GCS files | No injury data available |
| Nov 14 - Dec 18, 2025 | Empty files (bug) | No injury data available |
| Dec 19, 2025+ | Working | Full injury coverage |

**Root cause**: Scraper was running but producing empty `[]` files. Fixed Dec 19, 2025.

### Player Movement Data Gap

| Data | Last Updated | Impact |
|------|--------------|--------|
| `nbac_player_movement` | Aug 2025 | No 2025-26 season trades |
| GCS folder | Doesn't exist | Scraper never scheduled |

**Workaround**: Detect team changes from `player_game_summary` team stints.

### Gap Detection Results (Dec 19+ data)

| Gap Type | Count | Players | Meaning |
|----------|-------|---------|---------|
| INJURY_REPORT | 826 | 217 | Expected - injury explains absence |
| DNP_NO_INJURY | 979 | 296 | OK - Coach's decision |
| ERROR_NOT_IN_BOXSCORE | 76 | 46 | Investigate - roster status |
| ERROR_HAS_MINUTES | 20 | 7 | **BUG** - played but missing from analytics |

**Key finding**: 20 cases where players played actual minutes but are missing from `player_game_summary`. These are real bugs requiring investigation (likely recently traded players).

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [VALIDATION-GUIDE.md](./VALIDATION-GUIDE.md) | Full validation framework |
| [MORNING-VALIDATION-GUIDE.md](../../02-operations/MORNING-VALIDATION-GUIDE.md) | Daily pipeline checks |
| [DESIGN-DECISIONS.md](../../08-projects/current/data-lineage-integrity/DESIGN-DECISIONS.md) | Data lineage architecture |

---

## Success Criteria

After running a spot check, you should know:

- [ ] Whether all player absences are properly explained (injury, trade, etc.)
- [ ] Whether injury flags from NBA.com are being captured
- [ ] Whether there are any unexplained data gaps to investigate
- [ ] Whether the website can show accurate "last N games" with proper injury icons
