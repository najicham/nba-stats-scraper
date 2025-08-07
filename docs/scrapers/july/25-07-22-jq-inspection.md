# NBA Scrapers - jq Data Inspection Reference

## Quick Reference Commands

### **Get Latest File Helper**
```bash
# Standard pattern for getting latest file
LATEST_FILE=$(gcloud storage ls gs://nba-analytics-raw-data/SOURCE/TYPE/$(date +%Y-%m-%d)/ | tail -1)

# For team subdirectories (recursive)
LATEST_FILE=$(gcloud storage ls -r gs://nba-analytics-raw-data/SOURCE/TYPE/$(date +%Y-%m-%d)/ | grep '\.json$' | tail -1)

# For specific date
LATEST_FILE=$(gcloud storage ls gs://nba-analytics-raw-data/SOURCE/TYPE/YYYY-MM-DD/ | tail -1)
```

---

## ✅ Working Scrapers - Tested jq Commands

### **1. Odds API Events** ⭐
```bash
# Get latest file
LATEST_EVENTS=$(gcloud storage ls gs://nba-analytics-raw-data/odds-api/events/$(date +%Y-%m-%d)/ | tail -1)

# Basic structure (off-season)
gcloud storage cat $LATEST_EVENTS | jq '{
  total_events: length,
  data_type: type,
  off_season_check: (length == 0)
}'

# During regular season
gcloud storage cat $LATEST_EVENTS | jq '{
  total_events: length,
  sample_events: [.[] | {
    id: .id,
    home_team: .home_team,
    away_team: .away_team,
    commence_time: .commence_time
  }] | .[0:3],
  all_event_ids: [.[].id]
}'

# Extract event IDs for props testing
gcloud storage cat $LATEST_EVENTS | jq -r '.[].id'
```

### **2. NBA.com Player List** ⭐
```bash
# Get latest file
LATEST_PLAYERS=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/player-list/$(date +%Y-%m-%d)/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_PLAYERS | jq '{
  metadata: {
    resource: .resource,
    season: .parameters.Season,
    league: .parameters.LeagueID
  },
  player_stats: {
    total_players: (.resultSets[0].rowSet | length),
    teams_represented: ([.resultSets[0].rowSet[] | .[9]] | unique | length),
    sample_teams: ([.resultSets[0].rowSet[] | .[9]] | unique | sort | .[0:5])
  },
  sample_players: [.resultSets[0].rowSet[0:3][] | {
    name: (.[2] + " " + .[1]),
    team: .[9],
    position: .[11],
    jersey: .[10],
    person_id: .[0]
  }],
  data_quality: {
    all_have_teams: ([.resultSets[0].rowSet[] | .[9]] | map(. != null) | all),
    all_have_ids: ([.resultSets[0].rowSet[] | .[0]] | map(. != null) | all),
    realistic_count: (.resultSets[0].rowSet | length > 400)
  }
}'

# Team breakdown
gcloud storage cat $LATEST_PLAYERS | jq '[.resultSets[0].rowSet[] | .[9]] | group_by(.) | map({team: .[0], count: length}) | sort_by(.team)'

# Search specific player
gcloud storage cat $LATEST_PLAYERS | jq '.resultSets[0].rowSet[] | select((.[1] + " " + .[2]) | contains("LeBron")) | {name: (.[2] + " " + .[1]), team: .[9], id: .[0]}'
```

### **3. BDL Active Players** ⭐
```bash
# Get latest file
LATEST_BDL=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/active-players/$(date +%Y-%m-%d)/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_BDL | jq '{
  pagination_success: {
    total_players: .playerCount,
    actual_count: (.activePlayers | length),
    counts_match: (.playerCount == (.activePlayers | length)),
    data_source: .ident
  },
  team_analysis: {
    teams_count: ([.activePlayers[] | .team.abbreviation] | unique | length),
    players_per_team: ([.activePlayers[] | .team.abbreviation] | group_by(.) | map({
      team: .[0], 
      players: length
    }) | sort_by(.team))
  },
  sample_players: [.activePlayers[0:3][] | {
    name: (.first_name + " " + .last_name),
    team: .team.abbreviation,
    position: .position,
    height: .height,
    weight: .weight
  }],
  data_quality: {
    all_have_teams: ([.activePlayers[] | .team.abbreviation] | map(length > 0) | all),
    realistic_total: (.playerCount > 500 and .playerCount < 700)
  }
}'

# Search specific player
gcloud storage cat $LATEST_BDL | jq '.activePlayers[] | select(.last_name == "James" and .first_name == "LeBron") | {name: (.first_name + " " + .last_name), team: .team.abbreviation, id: .id}'
```

### **4. NBA.com Player Movement** ⭐
```bash
# Get latest file
LATEST_MOVEMENT=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/player-movement/$(date +%Y-%m-%d)/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_MOVEMENT | jq '{
  metadata: {
    year: .metadata.year,
    total_transactions: .metadata.recordCount,
    fetched: .metadata.fetchedUtc
  },
  transaction_breakdown: {
    by_type: ([.rows[] | .Transaction_Type] | group_by(.) | map({
      type: .[0], 
      count: length
    }) | sort_by(-.count)),
    recent_activity: [.rows[] | select(.TRANSACTION_DATE | contains("2025-07")) | {
      date: .TRANSACTION_DATE,
      type: .Transaction_Type,
      description: .TRANSACTION_DESCRIPTION,
      team: .TEAM_SLUG,
      player: .PLAYER_SLUG
    }] | .[0:5],
    teams_involved: ([.rows[] | .TEAM_SLUG] | unique | length),
    players_involved: ([.rows[] | .PLAYER_SLUG] | unique | length)
  }
}'

# Search player transactions
gcloud storage cat $LATEST_MOVEMENT | jq '.rows[] | select(.PLAYER_SLUG | contains("lebron")) | {date: .TRANSACTION_DATE, type: .Transaction_Type, team: .TEAM_SLUG, description: .TRANSACTION_DESCRIPTION}'

# Recent trades
gcloud storage cat $LATEST_MOVEMENT | jq '[.rows[] | select(.Transaction_Type == "Trade" and (.TRANSACTION_DATE | contains("2025"))) | {date: .TRANSACTION_DATE, player: .PLAYER_SLUG, team: .TEAM_SLUG}] | .[0:5]'
```

### **5. NBA.com Injury Report** ✅
```bash
# Get latest file (use specific date)
LATEST_INJURY=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/injury-report/2025-03-15/ | grep -o 'gs://[^[:space:]]*\.json$' | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_INJURY | jq '{
  report_summary: {
    total_injuries: (.injuries | length),
    teams_affected: ([.injuries[] | .team] | unique | length)
  },
  by_status: ([.injuries[] | .status] | group_by(.) | map({
    status: .[0],
    count: length
  }) | sort_by(-.count)),
  by_team: ([.injuries[] | .team] | group_by(.) | map({
    team: .[0],
    injured_count: length
  }) | sort_by(-.injured_count)),
  prop_impact: {
    players_out: ([.injuries[] | select(.status == "Out")] | length),
    players_questionable: ([.injuries[] | select(.status == "Questionable")] | length)
  }
}'

# Team-specific injuries
gcloud storage cat $LATEST_INJURY | jq '.injuries[] | select(.team == "Lakers") | {player: .player, status: .status, reason: .reason}'
```

### **6. NBA.com Schedule CDN** ✅
```bash
# Get latest file
LATEST_SCHEDULE=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/schedule-cdn/$(date +%Y-%m-%d)/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_SCHEDULE | jq '{
  schedule_info: {
    source: .source,
    season: .seasonYear,
    total_games: .game_count,
    dates_covered: .date_count,
    teams: ([.games[] | .homeTeam.teamTricode, .awayTeam.teamTricode] | unique | length)
  },
  upcoming_games: [.games[] | select(.gameDate >= (now | strftime("%Y-%m-%d"))) | {
    date: .gameDate,
    time: .gameTime,
    home: .homeTeam.teamTricode,
    away: .awayTeam.teamTricode,
    game_id: .gameId
  }] | .[0:5],
  games_by_month: ([.games[] | .gameDate[0:7]] | group_by(.) | map({
    month: .[0],
    games: length
  }))
}'

# Games for specific date
gcloud storage cat $LATEST_SCHEDULE | jq '.games[] | select(.gameDate == "2025-03-15") | {time: .gameTime, home: .homeTeam.teamTricode, away: .awayTeam.teamTricode}'

# Team schedule
gcloud storage cat $LATEST_SCHEDULE | jq '[.games[] | select(.homeTeam.teamTricode == "LAL" or .awayTeam.teamTricode == "LAL") | {date: .gameDate, opponent: (if .homeTeam.teamTricode == "LAL" then .awayTeam.teamTricode else .homeTeam.teamTricode end)}] | .[0:10]'
```

### **7. ESPN Scoreboard** ✅
```bash
# Get latest file (use specific date)
LATEST_SCOREBOARD=$(gcloud storage ls gs://nba-analytics-raw-data/espn/scoreboard/2025-03-22/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_SCOREBOARD | jq '{
  game_summary: {
    total_games: .gameCount,
    game_date: .gamedate,
    games_completed: ([.games[] | select(.state == "post")] | length),
    games_in_progress: ([.games[] | select(.state == "in")] | length),
    games_upcoming: ([.games[] | select(.state == "pre")] | length)
  },
  game_details: [.games[] | {
    gameId: .gameId,
    state: .state,
    status: .status,
    teams: [.teams[] | {
      abbreviation: .abbreviation,
      score: .score,
      home_away: .homeAway
    }]
  }],
  high_scoring_games: [.games[] | select(.state == "post") | {
    matchup: (.teams[0].abbreviation + " vs " + .teams[1].abbreviation),
    total_points: (.teams[0].score + .teams[1].score)
  } | select(.total_points > 220)]
}'

# Extract game IDs
gcloud storage cat $LATEST_SCOREBOARD | jq -r '.games[].gameId'

# Specific team performance
gcloud storage cat $LATEST_SCOREBOARD | jq '.games[] | select(.teams[] | .abbreviation == "LAL") | {gameId: .gameId, teams: [.teams[] | {team: .abbreviation, score: .score}]}'
```

### **8. ESPN Team Roster** ✅
```bash
# Get latest file (recursive for team subdirectories)
LATEST_ESPN_ROSTER=$(gcloud storage ls -r gs://nba-analytics-raw-data/espn/rosters/$(date +%Y-%m-%d)/ | grep '\.json$' | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_ESPN_ROSTER | jq '{
  team_info: {
    team_abbreviation: .team_abbr,
    espn_team_id: .espn_team_id,
    team_name: .teamName,
    total_players: .playerCount
  },
  roster_breakdown: {
    by_position: ([.players[] | .position] | group_by(.) | map({
      position: .[0],
      count: length
    }) | sort_by(-.count)),
    height_stats: {
      tallest: ([.players[] | select(.heightIn != null)] | max_by(.heightIn) | {name: .fullName, height: .height}),
      shortest: ([.players[] | select(.heightIn != null)] | min_by(.heightIn) | {name: .fullName, height: .height})
    }
  },
  player_details: [.players[] | {
    name: .fullName,
    jersey: .jersey,
    position: .position,
    height: .height,
    weight: .weight
  }] | sort_by(.jersey | tonumber)
}'

# Find specific player
gcloud storage cat $LATEST_ESPN_ROSTER | jq '.players[] | select(.fullName | contains("LeBron")) | {name: .fullName, jersey: .jersey, position: .position}'
```

### **9. NBA.com Team Roster** ✅
```bash
# Get latest file (recursive for team subdirectories)
LATEST_NBA_ROSTER=$(gcloud storage ls -r gs://nba-analytics-raw-data/nba-com/rosters/$(date +%Y-%m-%d)/ | grep '\.json$' | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_NBA_ROSTER | jq '{
  team_info: {
    team_abbreviation: .team_abbr,
    team_id: .teamId,
    season: .season,
    total_players: .playerCount
  },
  roster_analysis: {
    by_position: ([.players[] | .position] | group_by(.) | map({
      position: .[0],
      count: length
    })),
    jersey_numbers: [.players[] | {name: .name, number: .number}] | sort_by(.number | tonumber)
  },
  player_details: [.players[] | {
    name: .name,
    jersey_number: .number,
    position: .position,
    player_id: .playerId
  }] | sort_by(.jersey_number | tonumber)
}'
```

### **10. BDL Box Scores** ✅
```bash
# Get latest file (use specific date)
LATEST_BDL_BOXSCORE=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/boxscores/2025-01-15/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_BDL_BOXSCORE | jq '{
  game_summary: {
    date: .date,
    total_games: .rowCount,
    games_in_data: (.boxScores | length)
  },
  game_results: [.boxScores[] | {
    status: .status,
    period: .period,
    matchup: (.visitor_team.abbreviation + " @ " + .home_team.abbreviation),
    final_score: ((.visitor_team_score | tostring) + "-" + (.home_team_score | tostring)),
    overtime: (.period > 4),
    total_points: (.home_team_score + .visitor_team_score)
  }],
  game_stats: {
    completed_games: ([.boxScores[] | select(.status == "Final")] | length),
    overtime_games: ([.boxScores[] | select(.period > 4)] | length),
    high_scoring: ([.boxScores[] | select(.home_team_score + .visitor_team_score > 220)] | length)
  }
}'

# Player performance from specific game
gcloud storage cat $LATEST_BDL_BOXSCORE | jq '.boxScores[0].home_team.players[] | select(.points > 20) | {name: (.first_name + " " + .last_name), points: .points, rebounds: .rebounds, assists: .assists}'
```

### **11. ESPN Game Boxscore** ✅
```bash
# Get latest file (use specific game directory)
LATEST_ESPN_GAME=$(gcloud storage ls gs://nba-analytics-raw-data/espn/boxscores/$(date +%Y-%m-%d)/game_401705590/ | tail -1)

# Comprehensive analysis
gcloud storage cat $LATEST_ESPN_GAME | jq '{
  game_info: {
    game_id: .game_id,
    timestamp: .timestamp,
    teams: (keys | map(select(. != "game_id" and . != "timestamp"))),
    total_players: ((keys | map(select(. != "game_id" and . != "timestamp")) | map(. as $team | (.[$team] | length)) | add))
  },
  team_stats: (keys | map(select(. != "game_id" and . != "timestamp")) | map(. as $team | {
    team: $team,
    total_players: (.[$team] | length),
    starters: ([.[$team][] | select(.type == "starters")] | length),
    bench: ([.[$team][] | select(.type == "bench")] | length),
    active_players: ([.[$team][] | select(.stats | length > 0)] | length),
    dnp_players: ([.[$team][] | select(has("dnpReason"))] | length)
  })),
  injury_report: (keys | map(select(. != "game_id" and . != "timestamp")) | map(. as $team | {
    team: $team,
    injured_players: [.[$team][] | select(has("dnpReason")) | {
      name: .playerName,
      reason: .dnpReason
    }]
  }) | map(select(.injured_players | length > 0)))
}'

# Individual player stats
TEAM=$(gcloud storage cat $LATEST_ESPN_GAME | jq -r 'keys | map(select(. != "game_id" and . != "timestamp")) | .[0]')
gcloud storage cat $LATEST_ESPN_GAME | jq --arg team "$TEAM" '.[$team][] | select(.stats | length > 0) | {name: .playerName, jersey: .jersey, minutes: .stats[0], points: .stats[13]}'
```

### **12. BDL Injuries** ⚠️ (Export Mode Fix Needed)
```bash
# Get latest file
LATEST_BDL_INJURIES=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/injuries/$(date +%Y-%m-%d)/ | tail -1)

# Basic structure check
gcloud storage cat $LATEST_BDL_INJURIES | jq '{
  total_injuries: .rowCount,
  data_source: .ident,
  pagination_worked: (.rowCount > 100),
  teams_represented: ([.injuries[] | .team.abbreviation] | unique | length)
}'
```

---

## ⚠️ Off-Season Only Scrapers

### **13. Odds API Player Props** (Regular Season)
```bash
# Get latest file (when event_id available)
LATEST_PROPS=$(gcloud storage ls gs://nba-analytics-raw-data/odds-api/player-props/$(date +%Y-%m-%d)/event_EVENT_ID/ | tail -1)

# Analysis (template for regular season)
gcloud storage cat $LATEST_PROPS | jq '{
  # TODO: Add jq commands when tested during regular season
}'
```

### **14. Odds API Team Players** (Regular Season)
```bash
# Get latest file
LATEST_TEAM_PLAYERS=$(gcloud storage ls gs://nba-analytics-raw-data/odds-api/players/$(date +%Y-%m-%d)/ | tail -1)

# Analysis (template for regular season)
gcloud storage cat $LATEST_TEAM_PLAYERS | jq '{
  # TODO: Add jq commands when tested during regular season
}'
```

---

## ❌ Configuration Issues - No jq Commands Yet

### **Ball Don't Lie Scrapers (Missing GCS Path Keys)**
```bash
# bdl_teams.py - Missing path key: bdl_teams
# LATEST_BDL_TEAMS=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/teams/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_BDL_TEAMS | jq '{ TODO: Add after fixing GCS path }'

# bdl_players.py - Missing path key: bdl_players  
# LATEST_BDL_PLAYERS=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/players/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_BDL_PLAYERS | jq '{ TODO: Add after fixing GCS path }'

# bdl_games.py - Missing path key: bdl_games
# LATEST_BDL_GAMES=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/games/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_BDL_GAMES | jq '{ TODO: Add after fixing GCS path }'

# bdl_player_box_scores.py - Missing path key: bdl_player_box_scores
# LATEST_BDL_PLAYER_SCORES=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/player-box-scores/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_BDL_PLAYER_SCORES | jq '{ TODO: Add after fixing GCS path }'

# bdl_game_detail.py - Missing path key: bdl_game_detail
# LATEST_BDL_GAME_DETAIL=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/game-detail/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_BDL_GAME_DETAIL | jq '{ TODO: Add after fixing GCS path }'

# bdl_standings.py - Missing path key: bdl_standings
# LATEST_BDL_STANDINGS=$(gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/standings/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_BDL_STANDINGS | jq '{ TODO: Add after fixing GCS path }'
```

### **NBA.com Scrapers (Parameter/Configuration Issues)**
```bash
# nbac_player_boxscore.py - Parameter handling bug
# LATEST_NBA_PLAYER_BOXSCORE=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/player-boxscores/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_NBA_PLAYER_BOXSCORE | jq '{ TODO: Add after fixing parameter handling }'

# nbac_scoreboard_v2.py - Flask mixin conflict
# LATEST_NBA_SCOREBOARD_V2=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/scoreboard-v2/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_NBA_SCOREBOARD_V2 | jq '{ TODO: Add after fixing Flask mixin }'

# nbac_play_by_play.py - Needs testing
# LATEST_NBA_PBP=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/play-by-play/$(date +%Y-%m-%d)/game_GAME_ID/ | tail -1)
# gcloud storage cat $LATEST_NBA_PBP | jq '{ TODO: Add after testing }'

# nbac_schedule_api.py - Needs testing  
# LATEST_NBA_SCHEDULE_API=$(gcloud storage ls gs://nba-analytics-raw-data/nba-com/schedule-api/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_NBA_SCHEDULE_API | jq '{ TODO: Add after testing }'
```

### **PBPStats Scrapers (All Missing GCS Path Keys)**
```bash
# pbpstats_boxscore.py - Missing path key: pbpstats_boxscore
# LATEST_PBPSTATS_BOXSCORE=$(gcloud storage ls gs://nba-analytics-raw-data/pbpstats/boxscore/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_PBPSTATS_BOXSCORE | jq '{ TODO: Add after fixing GCS path }'

# pbpstats_play_by_play.py - Missing path key: pbpstats_play_by_play
# LATEST_PBPSTATS_PBP=$(gcloud storage ls gs://nba-analytics-raw-data/pbpstats/play-by-play/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_PBPSTATS_PBP | jq '{ TODO: Add after fixing GCS path }'

# pbpstats_schedule.py - Missing path key: pbpstats_schedule
# LATEST_PBPSTATS_SCHEDULE=$(gcloud storage ls gs://nba-analytics-raw-data/pbpstats/schedule/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_PBPSTATS_SCHEDULE | jq '{ TODO: Add after fixing GCS path }'
```

### **Odds API Historical Scrapers (Untested)**
```bash
# oddsa_events_his.py - Needs testing
# LATEST_ODDS_EVENTS_HIS=$(gcloud storage ls gs://nba-analytics-raw-data/odds-api/events-history/$(date +%Y-%m-%d)/ | tail -1)
# gcloud storage cat $LATEST_ODDS_EVENTS_HIS | jq '{ TODO: Add after testing }'

# oddsa_player_props_his.py - Needs testing
# LATEST_ODDS_PROPS_HIS=$(gcloud storage ls gs://nba-analytics-raw-data/odds-api/player-props-history/$(date +%Y-%m-%d)/event_EVENT_ID/ | tail -1)
# gcloud storage cat $LATEST_ODDS_PROPS_HIS | jq '{ TODO: Add after testing }'
```

---

## Cross-Source Validation Commands

### **Player Count Consistency**
```bash
# Compare player counts across sources
echo "=== Player Data Consistency ==="
NBA_COUNT=$(gcloud storage cat $LATEST_PLAYERS | jq '.resultSets[0].rowSet | length')
BDL_COUNT=$(gcloud storage cat $LATEST_BDL | jq '.playerCount')
echo "NBA.com: $NBA_COUNT players, BDL: $BDL_COUNT players"

# Team counts
NBA_TEAMS=$(gcloud storage cat $LATEST_PLAYERS | jq '[.resultSets[0].rowSet[] | .[9]] | unique | length')
BDL_TEAMS=$(gcloud storage cat $LATEST_BDL | jq '[.activePlayers[] | .team.abbreviation] | unique | length')
echo "NBA.com: $NBA_TEAMS teams, BDL: $BDL_TEAMS teams"
```

### **Transaction Impact Analysis**
```bash
# Recent trades affecting current rosters
gcloud storage cat $LATEST_MOVEMENT | jq '[.rows[] | select(.Transaction_Type == "Trade" and (.TRANSACTION_DATE | contains("2025"))) | {date: .TRANSACTION_DATE, player: .PLAYER_SLUG, team: .TEAM_SLUG}] | .[0:5]'

# Players with multiple transactions
gcloud storage cat $LATEST_MOVEMENT | jq '[.rows[] | .PLAYER_SLUG] | group_by(.) | map({player: .[0], transaction_count: length}) | sort_by(-.transaction_count) | .[0:10]'
```

### **Daily Health Check Script**
```bash
#!/bin/bash
TODAY=$(date +%Y-%m-%d)
echo "=== NBA Data Health Check - $TODAY ==="

# Check all working scrapers
echo "Core Business:"
gcloud storage ls gs://nba-analytics-raw-data/odds-api/events/$TODAY/ 2>/dev/null && echo "✅ Events" || echo "❌ Events"
gcloud storage ls gs://nba-analytics-raw-data/nba-com/player-list/$TODAY/ 2>/dev/null && echo "✅ Players" || echo "❌ Players"
gcloud storage ls gs://nba-analytics-raw-data/ball-dont-lie/active-players/$TODAY/ 2>/dev/null && echo "✅ BDL Players" || echo "❌ BDL Players"
gcloud storage ls gs://nba-analytics-raw-data/nba-com/player-movement/$TODAY/ 2>/dev/null && echo "✅ Transactions" || echo "❌ Transactions"

echo "Game Intelligence:"
gcloud storage ls gs://nba-analytics-raw-data/nba-com/schedule-cdn/$TODAY/ 2>/dev/null && echo "✅ Schedule" || echo "❌ Schedule"
gcloud storage ls gs://nba-analytics-raw-data/espn/scoreboard/ 2>/dev/null && echo "✅ Scoreboards" || echo "❌ Scoreboards"

echo "Team Data:"
gcloud storage ls -r gs://nba-analytics-raw-data/espn/rosters/$TODAY/ 2>/dev/null && echo "✅ ESPN Rosters" || echo "❌ ESPN Rosters"
gcloud storage ls -r gs://nba-analytics-raw-data/nba-com/rosters/$TODAY/ 2>/dev/null && echo "✅ NBA Rosters" || echo "❌ NBA Rosters"
```

---

## Usage Tips

### **Quick Data Snapshots**
```bash
# Get quick counts for all working scrapers
echo "NBA.com Players: $(gcloud storage cat $LATEST_PLAYERS | jq '.resultSets[0].rowSet | length')"
echo "BDL Players: $(gcloud storage cat $LATEST_BDL | jq '.playerCount')"
echo "Transactions: $(gcloud storage cat $LATEST_MOVEMENT | jq '.metadata.recordCount')"
echo "Schedule Games: $(gcloud storage cat $LATEST_SCHEDULE | jq '.game_count')"
```

### **Business Intelligence Queries**
```bash
# Players out today (for prop availability)
gcloud storage cat $LATEST_INJURY | jq '.injuries[] | select(.status == "Out") | {player: .player, team: .team, reason: .reason}'

# High-scoring games (for over/under analysis)
gcloud storage cat $LATEST_BDL_BOXSCORE | jq '.boxScores[] | select(.home_team_score + .visitor_team_score > 220) | {game: (.visitor_team.abbreviation + " @ " + .home_team.abbreviation), total: (.home_team_score + .visitor_team_score)}'

# Recent player movement (for team context)
gcloud storage cat $LATEST_MOVEMENT | jq '[.rows[] | select(.TRANSACTION_DATE | contains("2025-07")) | {date: .TRANSACTION_DATE, type: .Transaction_Type, player: .PLAYER_SLUG, team: .TEAM_SLUG}] | .[0:5]'
```
