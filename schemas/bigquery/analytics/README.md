# Phase 3: Analytics Enrichment

**Dataset:** `nba_analytics`  
**Purpose:** Historical player and team performance with calculated metrics

## Tables

- `player_game_summary` - Individual player performance per game
- `team_offense_game_summary` - Team offensive metrics per game  
- `team_defense_game_summary` - Team defensive metrics per game
- `upcoming_team_game_context` - Pre-game team context
- `upcoming_player_game_context` - Pre-game player context

## Processors

Located in: `data_processors/analytics/`

## Deployment
```bash
# Create dataset
bq query --use_legacy_sql=false < datasets.sql

# Deploy tables
bq query --use_legacy_sql=false < player_game_summary_tables.sql
bq query --use_legacy_sql=false < team_offense_game_summary_tables.sql
bq query --use_legacy_sql=false < team_defense_game_summary_tables.sql
bq query --use_legacy_sql=false < upcoming_team_game_context_tables.sql
bq query --use_legacy_sql=false < upcoming_player_game_context_tables.sql
```
