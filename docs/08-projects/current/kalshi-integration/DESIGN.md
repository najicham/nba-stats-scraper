# Kalshi Integration - Technical Design

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         KALSHI DATA FLOW                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐ │
│  │ Kalshi API   │────▶│ GCS Storage  │────▶│ BigQuery Raw Table       │ │
│  │ (REST/WS)    │     │ kalshi/props │     │ nba_raw.kalshi_props     │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────┘ │
│         │                                            │                   │
│         │ RSA Auth                                   │                   │
│         │                                            ▼                   │
│  ┌──────────────┐                         ┌──────────────────────────┐  │
│  │ Scheduler    │                         │ Prediction Coordinator   │  │
│  │ 2:00 AM ET   │                         │ (player_loader.py)       │  │
│  └──────────────┘                         └──────────────────────────┘  │
│                                                      │                   │
│                                                      ▼                   │
│                                           ┌──────────────────────────┐  │
│                                           │ Predictions Output       │  │
│                                           │ - Kalshi line            │  │
│                                           │ - Kalshi contract price  │  │
│                                           │ - Liquidity indicator    │  │
│                                           └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Design

### 1. Kalshi Scraper

**Location:** `scrapers/kalshi/kalshi_player_props.py`

**Class:** `KalshiPlayerProps(ScraperBase, ScraperFlaskMixin)`

**Authentication:**
- RSA key pair authentication (different from API key)
- Keys stored in Secret Manager: `kalshi-api-private-key`
- Public key registered with Kalshi account

**API Endpoints Used:**
```python
BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"

# Get all NBA player prop events for a date
GET /events?series_ticker=KXNBA&status=open

# Get markets for a specific event
GET /markets?event_ticker={event_ticker}

# Get orderbook depth (for liquidity)
GET /markets/{ticker}/orderbook
```

**Rate Limits:**
- Tier 1 (default): 10 requests/second
- Use 100ms delay between requests (conservative)

**Key Methods:**
```python
class KalshiPlayerProps(ScraperBase, ScraperFlaskMixin):
    name = "kalshi_player_props"
    header_profile = "kalshi"  # Custom auth headers
    proxy_enabled = False  # Kalshi doesn't require proxy
    timeout_http = 30

    def validate_opts(self):
        """Validate date and market_type parameters."""

    def set_additional_opts(self):
        """Fetch game schedule to map Kalshi events to games."""

    def _authenticate(self) -> str:
        """Generate RSA-signed authentication token."""

    def _fetch_events(self) -> List[dict]:
        """Get all NBA events for the target date."""

    def _fetch_markets_for_event(self, event_ticker: str) -> List[dict]:
        """Get all player prop markets for an event."""

    def _fetch_orderbook(self, market_ticker: str) -> dict:
        """Get bid/ask depth for liquidity assessment."""

    def transform_data(self, raw_data: dict) -> dict:
        """Transform Kalshi format to our schema."""
```

### 2. BigQuery Schema

**Table:** `nba_raw.kalshi_player_props`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.kalshi_player_props` (
    -- Partition & Clustering
    game_date DATE NOT NULL,                    -- Partition key

    -- Kalshi Identifiers
    series_ticker STRING NOT NULL,              -- "KXNBA"
    event_ticker STRING NOT NULL,               -- "KXNBA-26-LAL-BOS-20260201"
    market_ticker STRING NOT NULL,              -- "KXNBA-26-LEBRON-PTS-25"

    -- Market Type
    prop_type STRING NOT NULL,                  -- "points", "rebounds", "assists", "threes"

    -- Player Identification
    kalshi_player_name STRING NOT NULL,         -- As shown on Kalshi
    player_lookup STRING NOT NULL,              -- Normalized: "lebronjames"
    player_team STRING,                         -- May not always be available

    -- Game Identification
    home_team STRING,
    away_team STRING,
    game_id STRING,                             -- NBA.com game ID if matched

    -- Line Information
    line_value FLOAT64 NOT NULL,                -- 25.5 (the prop line)

    -- Contract Pricing (in cents, 0-100)
    yes_bid INT64,                              -- Best bid for Yes contracts
    yes_ask INT64,                              -- Best ask for Yes contracts
    no_bid INT64,                               -- Best bid for No contracts
    no_ask INT64,                               -- Best ask for No contracts

    -- Derived Pricing (for comparison with traditional odds)
    implied_over_prob FLOAT64,                  -- yes_ask / 100
    implied_under_prob FLOAT64,                 -- no_ask / 100
    equivalent_over_odds INT64,                 -- American odds equivalent
    equivalent_under_odds INT64,                -- American odds equivalent

    -- Liquidity Metrics
    yes_bid_size INT64,                         -- Contracts available at bid
    yes_ask_size INT64,                         -- Contracts available at ask
    no_bid_size INT64,
    no_ask_size INT64,
    total_volume INT64,                         -- Total contracts traded
    open_interest INT64,                        -- Outstanding contracts
    liquidity_score STRING,                     -- "HIGH", "MEDIUM", "LOW"

    -- Market Status
    market_status STRING NOT NULL,              -- "active", "closed", "settled"
    can_close_early BOOLEAN,
    close_time TIMESTAMP,

    -- Team Validation (following existing pattern)
    has_team_issues BOOLEAN NOT NULL DEFAULT TRUE,
    validated_team STRING,
    validation_confidence FLOAT64,
    validation_method STRING,

    -- Metadata
    data_hash STRING,                           -- For smart idempotency
    scraped_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, prop_type, market_status
OPTIONS (
    require_partition_filter = true,
    description = "Kalshi NBA player props from prediction market"
);
```

### 3. Data Processor

**Location:** `data_processors/raw/kalshi/kalshi_props_processor.py`

**Class:** `KalshiPropsProcessor(SmartIdempotencyMixin, ProcessorBase)`

**Processing Strategy:** `CHECK_BEFORE_INSERT` (preserve time-series for price history)

**Key Transformations:**
```python
class KalshiPropsProcessor(SmartIdempotencyMixin, ProcessorBase):
    dataset_id = "nba_raw"
    table_name = "kalshi_player_props"
    processing_strategy = ProcessingStrategy.CHECK_BEFORE_INSERT

    # Hash fields for idempotency
    HASH_FIELDS = [
        'player_lookup',
        'game_date',
        'prop_type',
        'line_value',
        'yes_ask',
        'no_ask'
    ]

    def _normalize_player_name(self, kalshi_name: str) -> str:
        """Convert Kalshi player name to player_lookup format."""

    def _calculate_liquidity_score(self, row: dict) -> str:
        """Assess liquidity: HIGH (>1000 contracts), MEDIUM (100-1000), LOW (<100)."""

    def _convert_to_american_odds(self, contract_price: int) -> int:
        """Convert Kalshi cents to American odds.

        50¢ = -100 (even money)
        60¢ = -150 (60% implied)
        40¢ = +150 (40% implied)
        """
        if contract_price >= 50:
            return int(-100 * contract_price / (100 - contract_price))
        else:
            return int(100 * (100 - contract_price) / contract_price)

    def _match_to_game(self, event_ticker: str, game_date: date) -> Optional[str]:
        """Match Kalshi event to NBA.com game_id."""
```

### 4. Predictions Integration

**File:** `predictions/coordinator/player_loader.py`

**Changes:**
```python
class PlayerDataLoader:
    def get_betting_line(self, player_lookup: str, game_date: date) -> dict:
        """Get betting line from available sources.

        Priority:
        1. Odds API (DraftKings, FanDuel, BetMGM)
        2. BettingPros
        3. Kalshi (NEW)

        Returns dict with:
        - line_value: float
        - line_source: str
        - kalshi_available: bool (NEW)
        - kalshi_line: float (NEW, if different)
        - kalshi_yes_price: int (NEW)
        - kalshi_liquidity: str (NEW)
        """

    def _query_kalshi_line(self, player_lookup: str, game_date: date) -> Optional[dict]:
        """Query Kalshi props table for line."""
        query = """
            SELECT
                line_value,
                yes_ask as contract_price,
                equivalent_over_odds,
                liquidity_score,
                market_ticker
            FROM `nba_raw.kalshi_player_props`
            WHERE game_date = @game_date
              AND player_lookup = @player_lookup
              AND prop_type = 'points'
              AND market_status = 'active'
            ORDER BY scraped_at DESC
            LIMIT 1
        """
```

### 5. Output Schema Changes

**Table:** `nba_predictions.player_prop_predictions`

**New Fields:**
```sql
-- Kalshi availability and comparison
kalshi_available BOOLEAN,              -- Is there a Kalshi market?
kalshi_line FLOAT64,                   -- Kalshi line (may differ from primary)
kalshi_yes_price INT64,                -- Contract price for OVER in cents
kalshi_no_price INT64,                 -- Contract price for UNDER in cents
kalshi_liquidity STRING,               -- "HIGH", "MEDIUM", "LOW"
kalshi_market_ticker STRING,           -- Direct link to market
line_discrepancy FLOAT64,              -- Difference between primary line and Kalshi
```

## Scheduling

### Scraper Schedule

```bash
# Kalshi props scraper - run at 2:00 AM ET (after lines posted, before predictions)
gcloud scheduler jobs create http kalshi-props-scraper \
    --schedule="0 7 * * *" \  # 7 AM UTC = 2 AM ET
    --uri="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}' \
    --time-zone="UTC" \
    --location="us-west2"
```

### Processor Registration

Add to Phase 2 orchestration to process after scraping.

## Error Handling

### Kalshi-Specific Errors

| Error | Cause | Handling |
|-------|-------|----------|
| 401 Unauthorized | RSA signature invalid | Re-generate token, check key |
| 429 Rate Limited | Too many requests | Exponential backoff |
| Market Not Found | No props for game | Log, continue (normal for some games) |
| Low Liquidity | Thin orderbook | Flag in data, warn in predictions |

### Graceful Degradation

If Kalshi scraper fails:
1. Predictions continue with OddsAPI/BettingPros
2. `kalshi_available = FALSE` in output
3. Alert sent but non-blocking

## Security

### API Key Storage

```bash
# Store Kalshi private key in Secret Manager
gcloud secrets create kalshi-api-private-key \
    --data-file=./kalshi_private_key.pem

# Grant access to scraper service account
gcloud secrets add-iam-policy-binding kalshi-api-private-key \
    --member="serviceAccount:nba-scrapers@nba-props-platform.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Key Rotation

Kalshi API keys should be rotated quarterly. Document process in runbook.

## Testing Strategy

### Unit Tests
- RSA authentication signing
- Contract price to American odds conversion
- Player name normalization
- Liquidity score calculation

### Integration Tests
- End-to-end scraper with Kalshi demo environment
- Processor with sample GCS files
- Predictions loader with Kalshi data

### Validation
- Line values within expected ranges (pts: 5-50, reb: 2-20, ast: 1-15)
- Contract prices sum to ~100 (yes_ask + no_bid ≈ 100)
- Liquidity metrics are non-negative

## Rollout Plan

### Phase 1: Scraper Only (Week 1)
- Deploy scraper, collect data
- Validate data quality
- No changes to predictions

### Phase 2: Parallel Display (Week 2)
- Add Kalshi fields to predictions
- Display alongside primary line
- Monitor for discrepancies

### Phase 3: Full Integration (Week 3)
- Use Kalshi as fallback source
- Add arbitrage detection
- Dashboard integration
