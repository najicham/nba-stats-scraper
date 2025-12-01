# Complete Data Source Catalog

**Created:** 2025-11-30
**Status:** DRAFT - Needs Review
**Purpose:** Document ALL data sources, their scrapers, tables, and fallback options

---

## Overview

This catalog maps the complete data pipeline:
```
Scraper → GCS JSON → Phase 2 Processor → BigQuery Raw Table → Phase 3 Processor
```

---

## Data Source Summary

| Source | Scrapers | Raw Tables | Coverage | Primary Use |
|--------|----------|------------|----------|-------------|
| **NBA.com** | 13 | 10 | ~100% | Official stats, schedule, injuries |
| **Ball Don't Lie** | 6 | 4 | ~94-100% | Backup stats, historical data |
| **BigDataBall** | 2 | 1 | ~94% | Shot zones, lineups |
| **ESPN** | 3 | 3 | ~100% | Backup stats, validation |
| **Odds API** | 7 | 2 | 40-99% | Prop lines, game lines |
| **BettingPros** | 2 | 1 | ~99.7% | Historical prop lines |
| **Basketball Ref** | 1 | 1 | ~100% | Historical rosters |

---

## Part 1: Player Statistics

### Primary: NBA.com Gamebook

| Attribute | Value |
|-----------|-------|
| **Scraper** | `nbac_gamebook_pdf` |
| **Raw Table** | `nba_raw.nbac_gamebook_player_stats` |
| **Coverage** | ~100% for current season |
| **Quality When Used** | gold (100) |
| **Key Fields** | points, rebounds, assists, minutes, FG/3P/FT splits |
| **Unique Value** | Official source, DNP tracking, name resolution |

### Fallback 1: Ball Don't Lie

| Attribute | Value |
|-----------|-------|
| **Scraper** | `bdl_player_box_scores` |
| **Raw Table** | `nba_raw.bdl_player_boxscores` |
| **Coverage** | ~94% (historical complete) |
| **Quality When Used** | silver (85) |
| **Key Fields** | Same core stats |
| **Differences** | No advanced stats, different player IDs |

### Fallback 2: ESPN Boxscores

| Attribute | Value |
|-----------|-------|
| **Scraper** | `espn_game_boxscore` |
| **Raw Table** | `nba_raw.espn_boxscores` |
| **Coverage** | ~100% (recent games) |
| **Quality When Used** | silver (80) |
| **Key Fields** | Same core stats |
| **Differences** | Different player IDs, limited historical |

### Recommendation

```yaml
player_boxscores:
  sources:
    - nbac_gamebook_player_stats  # gold, 100
    - bdl_player_boxscores        # silver, 85
    - espn_boxscores              # silver, 80 (last resort)
  on_all_fail:
    action: skip
    severity: critical
```

---

## Part 2: Team Statistics

### Primary: NBA.com Team Boxscore

| Attribute | Value |
|-----------|-------|
| **Scraper** | `nbac_team_boxscore` |
| **Raw Table** | `nba_raw.nbac_team_boxscore` |
| **Coverage** | ~100% |
| **Quality When Used** | gold (100) |
| **Key Fields** | Team totals, FG/3P/FT splits, pace |
| **Unique Value** | Official source, exactly 2 rows per game |

### Fallback 1: Reconstruct from Player Stats

| Attribute | Value |
|-----------|-------|
| **Scraper** | N/A (derived) |
| **Raw Table** | N/A (computed from player stats) |
| **Coverage** | Same as player stats (~94-100%) |
| **Quality When Used** | silver (85) |
| **Method** | SUM player stats grouped by team |
| **Verified** | GSW 121=121, LAL 114=114 (mathematically exact) |

### Fallback 2: ESPN Team Boxscore

| Attribute | Value |
|-----------|-------|
| **Scraper** | `espn_game_boxscore` (contains team totals) |
| **Raw Table** | `nba_raw.espn_boxscores` (extract team rows) |
| **Coverage** | ~100% (recent) |
| **Quality When Used** | silver (80) |

### Recommendation

```yaml
team_boxscores:
  sources:
    - nbac_team_boxscore              # gold, 100
    - reconstructed_from_players      # silver, 85
    - espn_team_boxscore              # silver, 80 (extract from espn_boxscores)
  on_all_fail:
    action: placeholder
    quality_tier: unusable
    severity: critical
```

---

## Part 3: Player Prop Lines

### Primary: Odds API

| Attribute | Value |
|-----------|-------|
| **Scraper** | `oddsa_player_props` (current), `oddsa_player_props_his` (historical) |
| **Raw Table** | `nba_raw.odds_api_player_points_props` |
| **Coverage** | ~40% (collection started late) |
| **Quality When Used** | gold (100) |
| **Key Fields** | points_line, over/under prices, bookmaker |
| **Unique Value** | Multiple bookmakers, price history |

### Fallback 1: BettingPros

| Attribute | Value |
|-----------|-------|
| **Scraper** | `bp_player_props` |
| **Raw Table** | `nba_raw.bettingpros_player_points_props` |
| **Coverage** | ~99.7% (comprehensive backfill) |
| **Quality When Used** | silver (90) |
| **Key Fields** | points_line, consensus probabilities |
| **Differences** | No game_id (needs schedule JOIN), consensus only |

### Recommendation

```yaml
player_props:
  sources:
    - odds_api_player_points_props    # gold, 100
    - bettingpros_player_points_props # silver, 90
  on_all_fail:
    action: skip  # Can't predict without props
    severity: warning
    message: "No prop line for player"
```

---

## Part 4: Game Schedule

### Primary: NBA.com Schedule

| Attribute | Value |
|-----------|-------|
| **Scraper** | `nbac_schedule_api`, `nbac_schedule_cdn` |
| **Raw Table** | `nba_raw.nbac_schedule` |
| **Coverage** | 100% |
| **Quality When Used** | gold (100) |
| **Key Fields** | game_id, game_date, home/away teams, game_status |
| **Unique Value** | Official source, includes broadcast info |

### Fallback 1: ESPN Scoreboard

| Attribute | Value |
|-----------|-------|
| **Scraper** | `espn_scoreboard` |
| **Raw Table** | `nba_raw.espn_scoreboard` |
| **Coverage** | ~100% (recent) |
| **Quality When Used** | silver (90) |
| **Differences** | Different game IDs, limited metadata |

### Recommendation

```yaml
game_schedule:
  sources:
    - nbac_schedule       # gold, 100
    - espn_scoreboard     # silver, 90 (gap filler)
  on_all_fail:
    action: fail  # Critical - cannot proceed
    severity: critical
```

---

## Part 5: Game Lines (Spreads/Totals)

### Primary: Odds API

| Attribute | Value |
|-----------|-------|
| **Scraper** | `oddsa_game_lines` (current), `oddsa_game_lines_his` (historical) |
| **Raw Table** | `nba_raw.odds_api_game_lines` |
| **Coverage** | 99.1% (missing only All-Star weekend) |
| **Quality When Used** | gold (100) |
| **Key Fields** | spread, total, moneyline prices |

### No Fallback Needed

Coverage is 99.1% and missing dates are All-Star weekend (no betting expected).

### Recommendation

```yaml
game_lines:
  sources:
    - odds_api_game_lines  # gold, 100
  on_all_fail:
    action: continue_without
    quality_impact: -10
    severity: info
    message: "No game lines (likely All-Star)"
```

---

## Part 6: Shot Zones / Play-by-Play

### Primary: BigDataBall

| Attribute | Value |
|-----------|-------|
| **Scraper** | `bigdataball_pbp` |
| **Raw Table** | `nba_raw.bigdataball_play_by_play` |
| **Coverage** | ~94% |
| **Quality When Used** | gold (100) |
| **Key Fields** | shot_x, shot_y, shot_type, shot_distance |
| **Unique Value** | Full 10-player lineups, dual coordinate systems |

### Fallback 1: NBA.com Play-by-Play

| Attribute | Value |
|-----------|-------|
| **Scraper** | `nbac_play_by_play` |
| **Raw Table** | `nba_raw.nbac_play_by_play` |
| **Coverage** | ~100% |
| **Quality When Used** | silver (85) |
| **Key Fields** | shot_x, shot_y, event_type |
| **Differences** | No lineup data, simpler event structure |

### Recommendation

```yaml
shot_zones:
  sources:
    - bigdataball_play_by_play  # gold, 100
    - nbac_play_by_play         # silver, 85
  on_all_fail:
    action: continue_without
    quality_impact: -15
    severity: info
    message: "No shot zone data"
```

---

## Part 7: Injury Reports

### Primary: NBA.com Injury Report

| Attribute | Value |
|-----------|-------|
| **Scraper** | `nbac_injury_report` |
| **Raw Table** | `nba_raw.nbac_injury_report` |
| **Coverage** | Daily during season |
| **Quality When Used** | gold (100) |
| **Key Fields** | player, injury_status, reason, game_date |

### Fallback 1: Ball Don't Lie Injuries

| Attribute | Value |
|-----------|-------|
| **Scraper** | `bdl_injuries` |
| **Raw Table** | `nba_raw.bdl_injuries` |
| **Coverage** | ~95% |
| **Quality When Used** | silver (85) |
| **Differences** | Different status normalization |

### Recommendation

```yaml
injury_reports:
  sources:
    - nbac_injury_report  # gold, 100
    - bdl_injuries        # silver, 85
  on_all_fail:
    action: continue_without
    quality_impact: -5
    severity: info
    message: "No injury data"
```

---

## Part 8: Player Rosters / Registry

### Primary: NBA.com Player List

| Attribute | Value |
|-----------|-------|
| **Scraper** | `nbac_player_list` |
| **Raw Table** | `nba_raw.nbac_player_list_current` |
| **Coverage** | 100% |
| **Quality When Used** | gold (100) |
| **Key Fields** | player_id, player_lookup, team_abbr |
| **Unique Value** | Official NBA player IDs |

### Fallback 1: Ball Don't Lie Active Players

| Attribute | Value |
|-----------|-------|
| **Scraper** | `bdl_active_players` |
| **Raw Table** | `nba_raw.bdl_active_players_current` |
| **Coverage** | ~100% |
| **Quality When Used** | silver (90) |
| **Differences** | BDL player IDs, may have team mismatches |

### Fallback 2: Basketball Reference Rosters

| Attribute | Value |
|-----------|-------|
| **Scraper** | `br_season_roster` |
| **Raw Table** | `nba_raw.br_rosters_current` |
| **Coverage** | Historical complete |
| **Quality When Used** | silver (85) |
| **Differences** | Historical only, different name formats |

### Recommendation

```yaml
player_roster:
  sources:
    - nbac_player_list_current     # gold, 100
    - bdl_active_players_current   # silver, 90
    - br_rosters_current           # silver, 85
  on_all_fail:
    action: fail  # Critical for ID resolution
    severity: critical
```

---

## Summary: Complete Fallback Matrix

| Data Type | Primary | Fallback 1 | Fallback 2 | On All Fail |
|-----------|---------|------------|------------|-------------|
| Player Stats | nbac_gamebook | bdl_boxscores | espn_boxscores | skip |
| Team Stats | nbac_team_boxscore | reconstruct | espn_boxscores | placeholder |
| Player Props | odds_api_props | bettingpros_props | - | skip |
| Schedule | nbac_schedule | espn_scoreboard | - | fail |
| Game Lines | odds_api_lines | - | - | continue_without |
| Shot Zones | bigdataball_pbp | nbac_play_by_play | - | continue_without |
| Injuries | nbac_injury | bdl_injuries | - | continue_without |
| Rosters | nbac_player_list | bdl_players | br_rosters | fail |

---

## Resolved Questions

### 1. ESPN as tertiary fallback?
**Decision: YES** - Add ESPN as 3rd fallback for player and team stats.

### 2. BDL injuries?
**Decision: YES** - Injury data is important, implement BDL as fallback.

### 3. Other data types (referee, standings, player movement)?
**Finding:** All three are collected (Phase 2) but NOT consumed by any Phase 3+ processor.
- **Referee:** Placeholders exist, marked "deferred"
- **Standings:** Explicit "No dependencies yet" comment
- **Player Movement:** No future plans documented

**Decision:** Don't add fallbacks yet - not consumed. Add to config as "future" when implemented.

### 4. PBP Reconstruction?
**Finding:** PBP can reconstruct some stats (points 98%, FG 95%) but not all (rebounds 85%, assists 80%).
Your code correctly uses PBP for **enhancement** (shot zones), not replacement.

**Decision:**
- Don't make PBP an automatic fallback (unreliable for some stats)
- Offer as manual remediation option with `remediation_options` in config
- Document which stats CAN be reconstructed and at what accuracy

---

## Scraper → Table Mapping

For the config file, here's the complete mapping:

```yaml
scraper_to_table:
  # NBA.com
  nbac_gamebook_pdf: nbac_gamebook_player_stats
  nbac_team_boxscore: nbac_team_boxscore
  nbac_play_by_play: nbac_play_by_play
  nbac_schedule_api: nbac_schedule
  nbac_injury_report: nbac_injury_report
  nbac_player_list: nbac_player_list_current
  nbac_player_boxscore: nbac_player_boxscores
  nbac_scoreboard_v2: nbac_scoreboard_v2

  # Ball Don't Lie
  bdl_player_box_scores: bdl_player_boxscores
  bdl_active_players: bdl_active_players_current
  bdl_injuries: bdl_injuries
  bdl_standings: bdl_standings

  # BigDataBall
  bigdataball_pbp: bigdataball_play_by_play

  # ESPN
  espn_game_boxscore: espn_boxscores
  espn_scoreboard: espn_scoreboard
  espn_roster: espn_team_roster

  # Odds API
  oddsa_player_props: odds_api_player_points_props
  oddsa_player_props_his: odds_api_player_points_props
  oddsa_game_lines: odds_api_game_lines
  oddsa_game_lines_his: odds_api_game_lines

  # BettingPros
  bp_player_props: bettingpros_player_points_props

  # Basketball Reference
  br_season_roster: br_rosters_current
```

---

*This catalog should be reviewed and validated before implementation.*
