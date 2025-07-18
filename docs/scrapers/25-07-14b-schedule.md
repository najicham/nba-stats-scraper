# NBA Data Pipeline - Daily Schedule

## Schedule Overview

This document outlines when each scraper runs throughout the day and what data it collects. The schedule is designed around NBA game timing and data availability patterns.

## 8:00 AM - 10:00 AM ET: Morning Current State Updates

### Primary Goals
- Capture overnight roster changes and trades
- Update injury status before game day
- Refresh schedule for any last-minute changes
- Set baseline data for the day

### Scrapers Running

#### Roster Updates (Multiple runs)
- **ESPN Rosters** (`GetEspnTeamRosterAPI`) - All teams
- **NBA.com Rosters** (`GetNbaTeamRoster`) - All teams
- **Purpose**: Catch trades, signings, releases that happened overnight
- **Frequency**: 2-3 runs during this window
- **Output**: Current roster snapshots only

#### Injury Status (Multiple runs)  
- **Ball Don't Lie Injuries** (`BdlInjuriesScraper`) - All current injuries
- **NBA.com Injury Report** (`GetNbaComInjuryReport`) - Official reports
- **Purpose**: Latest injury designations before games
- **Frequency**: 2-3 runs during this window
- **Output**: Current injury status only

#### Schedule Monitoring
- **NBA.com Schedule** (`GetDataNbaSeasonSchedule`) - Full season
- **Ball Don't Lie Games** (`BdlGamesScraper`) - Today's games
- **Purpose**: Detect postponements, rescheduling
- **Frequency**: Multiple runs
- **Output**: Updated game schedules and times

## 12:00 PM - 4:00 PM ET: Pre-Game Preparation

### Primary Goals
- Collect betting market data before lines move
- Prepare game-specific data collection
- Final roster and injury confirmations

### Scrapers Running

#### Betting Markets Setup
- **Odds API Events** (`GetOddsApiEvents`) - Today's NBA games
- **Purpose**: Get event IDs for prop bet collection
- **Frequency**: 1-2 runs
- **Output**: Event IDs and basic game info
- **Dependencies**: Must run before player props

#### Player Props Collection
- **Odds API Player Props** (`GetOddsApiCurrentEventOdds`) - Per event ID
- **Purpose**: Collect prop betting odds while favorable
- **Frequency**: 1-2 runs per event
- **Output**: Prop odds for each game event
- **Dependencies**: Requires event IDs from events scraper

#### Continued Schedule Monitoring
- **NBA.com Schedule** (`GetDataNbaSeasonSchedule`)
- **Purpose**: Monitor for last-minute changes
- **Frequency**: Ongoing checks

## Game Time (Variable): Live Monitoring

### Primary Goals
- Monitor for real-time changes
- Catch injury updates during warmups
- Handle schedule disruptions

### Scrapers Running

#### Injury Monitoring (Game Days Only)
- **Ball Don't Lie Injuries** (`BdlInjuriesScraper`)
- **NBA.com Injury Report** (`GetNbaComInjuryReport`)
- **Purpose**: Catch late scratches, warmup injuries
- **Frequency**: Hourly during game days
- **Output**: Updated injury status

#### Schedule Emergency Checks
- **NBA.com Schedule** (`GetDataNbaSeasonSchedule`)
- **Purpose**: Handle postponements due to weather, health protocols
- **Frequency**: As needed monitoring

## 6:00 PM - 11:00 PM ET: Game Results Collection

### Primary Goals
- Collect completed game data
- Capture final statistics and scores
- Prepare for next-day analysis

### Scrapers Running

#### Game Results
- **ESPN Scoreboard** (`GetEspnScoreboard`) - Today's final scores
- **Ball Don't Lie Boxscores** (`BdlBoxScoresScraper`) - Team stats
- **NBA.com Player Boxscores** (`GetNbaComPlayerBoxscore`) - Individual stats
- **Purpose**: Final game statistics and results
- **Frequency**: After games complete
- **Output**: Complete game data

#### Individual Game Details
- **ESPN Game Boxscore** (`GetEspnBoxscore`) - Per completed game
- **NBA.com Play by Play** (`GetNbaPlayByPlayRawBackup`) - Per completed game
- **Purpose**: Detailed game analysis data
- **Frequency**: Once per completed game
- **Output**: Detailed game breakdowns

## 11:00 PM - 2:00 AM ET: Enhanced Data & Next Day Prep

### Primary Goals
- Collect enhanced analytics data
- Check for next day's betting markets
- Process overnight updates

### Scrapers Running

#### Enhanced Analytics
- **Big Data Ball Play by Play** - Monitor Google Drive for completed games
- **Purpose**: Advanced play-by-play analysis (available 2 hours post-game)
- **Frequency**: Check for new files
- **Output**: Enhanced game analytics

#### Next Day Preparation  
- **Odds API Events** (`GetOddsApiEvents`) - Tomorrow's games if available
- **Odds API Player Props** (`GetOddsApiCurrentEventOdds`) - Early lines
- **Purpose**: Get head start on next day's betting data
- **Frequency**: 1 run if data available
- **Output**: Early betting lines

## Backfill Operations (As Needed)

### Historical Data Collection
- **Odds API Events Historical** (`GetOddsApiHistoricalEvents`) - Past dates
- **Odds API Player Props Historical** (`GetOddsApiHistoricalEventOdds`) - Past events
- **Purpose**: Fill historical gaps, initial data population
- **Frequency**: As needed for backfill
- **Output**: Historical betting and event data

### Historical Analysis Strategy
- **Use game boxscores instead of current rosters** for historical player analysis
- **Use game logs instead of current injury data** for historical injury impact
- **Purpose**: Accurate historical context without current-state bias

## Critical Dependencies

### Must Run First
1. **Odds API Events** → **Odds API Player Props** (need event IDs)
2. **Schedule Updates** → **Game-Specific Scrapers** (need game IDs)

### Data Timing Constraints
- **Rosters/Injuries**: Current state only, use game data for historical analysis
- **Big Data Ball**: 2-hour delay after game completion
- **Betting Lines**: Best collected before significant line movement

## Monitoring Priorities

### High Priority (Real-time alerts)
- Schedule changes during game days
- Failed Odds API events (blocks prop collection)
- Missing game results after completion

### Medium Priority (Daily review)
- Roster update failures
- Injury data gaps
- Historical backfill progress

### Low Priority (Weekly review)
- Enhanced analytics delays
- Non-critical API failures
- Data quality trends
