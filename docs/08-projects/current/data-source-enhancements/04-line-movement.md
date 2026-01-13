# Line Movement / Sharp Money Enhancement

## Current State

**What we have:**
- OddsAPI - Static snapshots of lines from DraftKings/FanDuel
- BettingPros - Backup static lines
- Historical odds data for backtesting

**What we're missing:**
- Real-time line movement tracking
- Sharp vs public money indicators
- Steam move alerts
- Opening vs current line comparison
- Closing Line Value (CLV) tracking

## Why This Matters

Line movement tells you **when** to bet, not just **what** to bet:

1. **Reverse Line Movement (RLM)** - Line moves against public = sharp action
2. **Steam Moves** - Rapid coordinated moves = professional syndicate betting
3. **Closing Line Value** - Beating the closing line = long-term profitability
4. **Line Shopping** - Best price across books at bet time

For prop betting:
- Player props are less efficient than game lines
- Sharp money moves props significantly
- Early line value exists before public bets

## Available Sources

### The-Odds-API (Current Provider)

**Already have:**
- Static line snapshots
- Multiple bookmakers

**Could add:**
- Historical odds endpoint for line movement
- More frequent polling (current vs opening)

**Cost:** Already paying, just need more API calls

### OddsJam API

**Features:**
- Real-time odds from 100+ books
- Sharp book tracking (Pinnacle, Circa)
- Line movement alerts
- Historical closing lines

**Cost:** $500-1000+/month (enterprise)

**Verdict:** Expensive, consider only if hitting limitations

### Action Network

**Features:**
- Public betting percentages
- Money splits (bet count vs handle)
- Sharp action indicators

**Cost:** ~$99/year (consumer), no API access

**Verdict:** Good for manual research, not automatable

### Pinnacle (Sharp Book Baseline)

**Why it matters:**
- Pinnacle is the sharpest book
- Their closing line is the market benchmark
- Beating Pinnacle CLV = long-term edge

**Access:**
- Not directly accessible in US
- Some APIs include Pinnacle odds (check OddsAPI coverage)

## Implementation Options

### Option A: Enhanced OddsAPI Usage (Recommended Start)

Maximize current provider before adding new ones:

1. **Track opening lines** - Store first line we see for each prop
2. **Poll more frequently** - Every 15-30 min instead of hourly
3. **Calculate movement** - Current vs opening delta
4. **Store historical** - Build our own line movement database

```sql
CREATE TABLE nba_analytics.prop_line_history (
  event_id STRING,
  player_name STRING,
  prop_type STRING,  -- points, rebounds, etc
  bookmaker STRING,

  -- Line tracking
  line_value NUMERIC(4,1),
  over_odds INT64,
  under_odds INT64,

  -- Timestamps
  captured_at TIMESTAMP,
  is_opening_line BOOLEAN,

  -- Calculated
  line_movement NUMERIC(4,1),  -- vs opening
  odds_movement INT64,         -- juice shift
)
```

**Effort:** 2-3 days
**Cost:** More API calls (check quota)

### Option B: Add OddsJam for Sharp Signals

If Option A isn't sufficient:

1. **Use OddsJam for:**
   - Sharp book odds (Pinnacle, Circa)
   - Steam move alerts
   - Real-time cross-book comparison

2. **Keep OddsAPI for:**
   - Primary DraftKings/FanDuel lines
   - Historical data

**Effort:** 1-2 days (API integration)
**Cost:** $500+/month

### Option C: Build CLV Tracking

Track our bet timing vs closing line:

```sql
CREATE TABLE nba_analytics.prediction_clv_tracking (
  prediction_id STRING,
  player_name STRING,
  prop_type STRING,

  -- Our prediction
  predicted_at TIMESTAMP,
  our_line NUMERIC(4,1),
  our_recommendation STRING,  -- OVER/UNDER

  -- Market at prediction time
  market_line_at_prediction NUMERIC(4,1),
  market_odds_at_prediction INT64,

  -- Closing line
  closing_line NUMERIC(4,1),
  closing_odds INT64,

  -- CLV calculation
  clv_line NUMERIC(4,1),  -- closing - prediction_time
  clv_cents INT64,        -- odds improvement
  beat_close BOOLEAN,     -- did we beat closing line?
)
```

This validates model quality - consistently beating close = real edge.

## Recommended Path

1. **Phase 1:** Option A - Maximize OddsAPI (low cost)
2. **Phase 2:** Option C - Add CLV tracking (free, validates model)
3. **Phase 3:** Consider OddsJam only if hitting limitations

## Effort Estimate

- Phase 1: 2-3 days
- Phase 2: 1 day
- Phase 3: 1-2 days (if needed)

## Success Metrics

- Can identify props where line moved in our favor
- CLV tracking shows we beat closing line >50% of time
- Sharp money alignment improves when-to-bet decisions
