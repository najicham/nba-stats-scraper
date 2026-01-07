# MLB Odds Data Collection Strategy

**Created**: 2026-01-06
**Status**: Implementation Phase

## Executive Summary

We're building a bottom-up strikeout prediction model that combines:
1. **Pitcher baseline stats** from Ball Don't Lie API
2. **Per-batter strikeout expectations** from betting lines
3. **Game context** from moneyline, spread, and totals

The key insight: **Sum of individual batter K probabilities should approximate the pitcher K line**. Divergence indicates market inefficiency or edge.

---

## Data Collection Architecture

### Odds API Markets to Collect

```
Per Game Collection:
├── PITCHER PROPS (Primary)
│   ├── pitcher_strikeouts      # TARGET - O/U for pitcher K's
│   ├── pitcher_outs            # Innings proxy (more outs = more K opportunities)
│   ├── pitcher_hits_allowed    # Inverse signal
│   └── pitcher_walks           # Control indicator
│
├── BATTER PROPS (For Lineup Analysis)
│   ├── batter_strikeouts       # CRITICAL - per-batter K expectation
│   ├── batter_hits             # Inverse correlation with K's
│   └── batter_walks            # Plate discipline signal
│
└── GAME LINES (Context)
    ├── h2h                     # Moneyline - team strength
    ├── spreads                 # Run line - expected margin
    └── totals                  # O/U runs - pitcher's duel indicator
```

### Market Priority Matrix

| Market | Priority | Rationale |
|--------|----------|-----------|
| `pitcher_strikeouts` | P0 | Primary prediction target |
| `batter_strikeouts` | P0 | Bottom-up model input |
| `totals` | P1 | Low total = pitcher's duel = more K's |
| `h2h` | P1 | Favored team context |
| `spreads` | P1 | Blowout/close game context |
| `pitcher_outs` | P2 | Innings expectation |
| `batter_hits` | P2 | Contact ability signal |
| `pitcher_hits_allowed` | P3 | Secondary correlation |
| `batter_walks` | P3 | Plate discipline |
| `pitcher_walks` | P3 | Control issues |

---

## File Structure

### New Files to Create

```
scrapers/mlb/oddsapi/
├── __init__.py
├── mlb_events.py              # Get Odds API event IDs for games
├── mlb_game_lines.py          # h2h, spreads, totals
├── mlb_pitcher_props.py       # pitcher_strikeouts, pitcher_outs, etc.
└── mlb_batter_props.py        # batter_strikeouts, batter_hits, etc.

data_processors/raw/mlb/
├── mlb_events_processor.py
├── mlb_game_lines_processor.py
├── mlb_pitcher_props_processor.py
└── mlb_batter_props_processor.py

schemas/bigquery/mlb_raw/
├── oddsa_events_tables.sql
├── oddsa_game_lines_tables.sql
├── oddsa_pitcher_props_tables.sql
└── oddsa_batter_props_tables.sql
```

---

## BigQuery Table Schemas

### `mlb_raw.oddsa_events`
```sql
-- Maps game dates to Odds API event IDs
CREATE TABLE mlb_raw.oddsa_events (
  event_id STRING NOT NULL,           -- Odds API event ID
  game_date DATE NOT NULL,            -- Game date
  commence_time TIMESTAMP,            -- Game start time
  home_team STRING,                   -- Home team name
  away_team STRING,                   -- Away team name
  home_team_abbr STRING,              -- Normalized abbreviation
  away_team_abbr STRING,              -- Normalized abbreviation
  sport_key STRING,                   -- baseball_mlb
  snapshot_time TIMESTAMP,
  source_file_path STRING
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr;
```

### `mlb_raw.oddsa_pitcher_props`
```sql
CREATE TABLE mlb_raw.oddsa_pitcher_props (
  -- Identifiers
  game_id STRING,
  game_date DATE NOT NULL,
  event_id STRING,

  -- Pitcher
  player_name STRING NOT NULL,
  player_lookup STRING NOT NULL,      -- Normalized for joins
  team_abbr STRING,

  -- Market
  market_key STRING NOT NULL,         -- pitcher_strikeouts, pitcher_outs, etc.
  bookmaker STRING NOT NULL,

  -- Line Details
  point FLOAT64,                      -- O/U line (e.g., 6.5)
  over_price INT64,                   -- American odds (e.g., -115)
  under_price INT64,                  -- American odds (e.g., -105)
  over_implied_prob FLOAT64,          -- Calculated probability
  under_implied_prob FLOAT64,

  -- Metadata
  last_update TIMESTAMP,
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_key, bookmaker;
```

### `mlb_raw.oddsa_batter_props`
```sql
CREATE TABLE mlb_raw.oddsa_batter_props (
  -- Identifiers
  game_id STRING,
  game_date DATE NOT NULL,
  event_id STRING,

  -- Batter
  player_name STRING NOT NULL,
  player_lookup STRING NOT NULL,
  team_abbr STRING,

  -- Opposing Pitcher Context
  opposing_team_abbr STRING,

  -- Market
  market_key STRING NOT NULL,         -- batter_strikeouts, batter_hits, etc.
  bookmaker STRING NOT NULL,

  -- Line Details
  point FLOAT64,                      -- O/U line (e.g., 0.5, 1.5)
  over_price INT64,
  under_price INT64,
  over_implied_prob FLOAT64,
  under_implied_prob FLOAT64,

  -- Metadata
  last_update TIMESTAMP,
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_key, bookmaker;
```

### `mlb_raw.oddsa_game_lines`
```sql
CREATE TABLE mlb_raw.oddsa_game_lines (
  -- Identifiers
  game_id STRING,
  game_date DATE NOT NULL,
  event_id STRING,

  -- Teams
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,

  -- Moneyline
  home_ml INT64,
  away_ml INT64,
  home_ml_implied FLOAT64,
  away_ml_implied FLOAT64,

  -- Spread (Run Line)
  home_spread FLOAT64,
  home_spread_price INT64,
  away_spread FLOAT64,
  away_spread_price INT64,

  -- Totals
  total_runs FLOAT64,
  over_price INT64,
  under_price INT64,

  -- Metadata
  bookmaker STRING NOT NULL,
  last_update TIMESTAMP,
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr, bookmaker;
```

---

## Model Logic: Bottom-Up K Prediction

### Step 1: Get Opposing Lineup
For each game, identify the 9 batters in the lineup.

### Step 2: Per-Batter K Expectation
From `oddsa_batter_props`, get each batter's strikeout O/U line:
```sql
SELECT
  player_name,
  point as k_line,
  over_implied_prob as k_prob_over,
  under_implied_prob as k_prob_under
FROM mlb_raw.oddsa_batter_props
WHERE game_date = '2025-06-15'
  AND market_key = 'batter_strikeouts'
  AND bookmaker = 'draftkings'
```

### Step 3: Sum Expected K's
```python
# Simplified expected value calculation
def expected_ks_for_batter(k_line, over_prob):
    """
    If line is 0.5 with -150 over (60% implied):
    EV = 0.5 * 0.60 + 0 * 0.40 ≈ 0.30

    But more accurately, need to model K distribution.
    """
    # For 0.5 lines: binary (0 or 1+)
    if k_line == 0.5:
        return over_prob * 1.2  # Average K's when hitting over
    # For 1.5 lines: more complex
    elif k_line == 1.5:
        return over_prob * 2.1 + (1 - over_prob) * 0.7
    # etc.
```

### Step 4: Compare to Pitcher Line
```python
pitcher_line = get_pitcher_k_line(pitcher_name, game_date)
lineup_expected_ks = sum(expected_ks_for_batter(b) for b in lineup)

# If these diverge significantly, there may be an edge
edge = lineup_expected_ks - pitcher_line
```

---

## Data Flow

```
Daily Pipeline (Pre-Game):

1. Get today's games ─────────────────▶ mlb_raw.bdl_games
       │
       ▼
2. Get event IDs ─────────────────────▶ mlb_raw.oddsa_events
       │
       ├──▶ 3a. Get pitcher props ────▶ mlb_raw.oddsa_pitcher_props
       │
       ├──▶ 3b. Get batter props ─────▶ mlb_raw.oddsa_batter_props
       │
       └──▶ 3c. Get game lines ───────▶ mlb_raw.oddsa_game_lines

4. Build predictions ─────────────────▶ mlb_predictions.pitcher_strikeouts

Post-Game:
5. Get actual results ────────────────▶ mlb_raw.bdl_pitcher_stats
6. Grade predictions ─────────────────▶ mlb_predictions.graded_predictions
```

---

## Implementation Order

### Phase 1: Odds API Infrastructure
1. `scrapers/mlb/oddsapi/__init__.py`
2. `scrapers/mlb/oddsapi/mlb_events.py` - Get event IDs first
3. `scrapers/mlb/oddsapi/mlb_game_lines.py` - Game context
4. `scrapers/mlb/oddsapi/mlb_pitcher_props.py` - Primary target
5. `scrapers/mlb/oddsapi/mlb_batter_props.py` - Lineup analysis

### Phase 2: BigQuery Schemas
6. Deploy all 4 oddsa table schemas

### Phase 3: Processors
7. Create processors for each scraper

### Phase 4: Batter Stats from BDL
8. Create batter stats scraper/processor for historical data

---

## API Details

### The Odds API Endpoints

```
# Events (get event IDs)
GET /v4/sports/baseball_mlb/events

# Event Odds (player props)
GET /v4/sports/baseball_mlb/events/{eventId}/odds
  ?markets=pitcher_strikeouts,batter_strikeouts
  &bookmakers=draftkings,fanduel

# Odds (game lines)
GET /v4/sports/baseball_mlb/odds
  ?markets=h2h,spreads,totals
  &bookmakers=draftkings,fanduel
```

### Rate Limits & Costs
- Rate limit: ~500 requests/minute
- Usage: Varies by endpoint (10-25 credits per request)
- Historical endpoint: 10 credits per region per market

---

## Success Metrics

1. **Data Completeness**: 95%+ of games have all required odds
2. **Latency**: Odds captured within 30 min of publication
3. **Model Accuracy**: MAE < 1.5 strikeouts
4. **Edge Detection**: Identify 5%+ ROI opportunities in backtesting
