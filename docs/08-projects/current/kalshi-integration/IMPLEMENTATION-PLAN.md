# Kalshi Integration - Implementation Plan

## Task Overview

| # | Task | Depends On | Parallel? | Agent Type |
|---|------|------------|-----------|------------|
| 1 | Create BigQuery schema | None | Yes | Bash |
| 2 | Create Kalshi scraper | None | Yes | general-purpose |
| 3 | Create GCS path config | None | Yes | general-purpose |
| 4 | Register scraper | 2 | No | general-purpose |
| 5 | Create raw data processor | 1 | Yes | general-purpose |
| 6 | Register processor | 5 | No | general-purpose |
| 7 | Create validation config | 2, 5 | Yes | general-purpose |
| 8 | Update player_loader.py | 1 | Yes | general-purpose |
| 9 | Update predictions schema | None | Yes | Bash |
| 10 | Create scheduler job | 2, 4 | No | Bash |
| 11 | Deploy and test | All | No | Bash |

## Detailed Task Breakdown

### Task 1: Create BigQuery Schema

**File:** `schemas/bigquery/raw/kalshi_player_props_tables.sql`

**Actions:**
1. Create schema SQL file
2. Run schema in BigQuery
3. Verify table created

**Commands:**
```bash
# Create table
bq query --use_legacy_sql=false < schemas/bigquery/raw/kalshi_player_props_tables.sql

# Verify
bq show nba-props-platform:nba_raw.kalshi_player_props
```

---

### Task 2: Create Kalshi Scraper

**Files:**
- `scrapers/kalshi/__init__.py`
- `scrapers/kalshi/kalshi_player_props.py`
- `scrapers/kalshi/kalshi_auth.py`

**Key Implementation Details:**

```python
# kalshi_auth.py
import base64
import hashlib
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from google.cloud import secretmanager

class KalshiAuthenticator:
    """RSA-based authentication for Kalshi API."""

    def __init__(self, api_key_id: str):
        self.api_key_id = api_key_id
        self._private_key = None

    def _load_private_key(self):
        """Load RSA private key from Secret Manager."""
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/nba-props-platform/secrets/kalshi-api-private-key/versions/latest"
        response = client.access_secret_version(request={"name": name})
        key_pem = response.payload.data.decode("UTF-8")
        self._private_key = serialization.load_pem_private_key(
            key_pem.encode(), password=None
        )

    def get_auth_headers(self, method: str, path: str) -> dict:
        """Generate signed headers for API request."""
        if self._private_key is None:
            self._load_private_key()

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = f"{timestamp}{method}{path}"

        signature = self._private_key.sign(
            message.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }
```

```python
# kalshi_player_props.py
class KalshiPlayerProps(ScraperBase, ScraperFlaskMixin):
    name = "kalshi_player_props"
    base_url = "https://trading-api.kalshi.com/trade-api/v2"

    # Prop type mapping
    PROP_TYPES = {
        "PTS": "points",
        "REB": "rebounds",
        "AST": "assists",
        "3PM": "threes",
    }

    def download_and_decode(self) -> dict:
        """Fetch all NBA player props for target date."""
        all_props = []

        # 1. Get all NBA events for the date
        events = self._fetch_nba_events()

        # 2. For each event, get player prop markets
        for event in events:
            markets = self._fetch_markets(event["event_ticker"])
            for market in markets:
                if self._is_player_prop(market):
                    orderbook = self._fetch_orderbook(market["ticker"])
                    prop = self._transform_market(market, orderbook)
                    all_props.append(prop)

            time.sleep(0.1)  # Rate limiting

        return {"props": all_props, "count": len(all_props)}
```

---

### Task 3: Create GCS Path Config

**File:** `scrapers/utils/gcs_path_builder.py`

**Add:**
```python
GCS_PATH_TEMPLATES = {
    # ... existing paths ...
    "kalshi_player_props": "kalshi/player-props/%(date)s/%(timestamp)s.json",
}
```

---

### Task 4: Register Scraper

**File:** `scrapers/registry.py`

**Add:**
```python
NBA_SCRAPER_REGISTRY: Dict[str, Tuple[str, str]] = {
    # ... existing scrapers ...
    "kalshi_player_props": (
        "scrapers.kalshi.kalshi_player_props",
        "KalshiPlayerProps"
    ),
}
```

---

### Task 5: Create Raw Data Processor

**Files:**
- `data_processors/raw/kalshi/__init__.py`
- `data_processors/raw/kalshi/kalshi_props_processor.py`

**Key Implementation:**
```python
class KalshiPropsProcessor(SmartIdempotencyMixin, ProcessorBase):
    dataset_id = "nba_raw"
    table_name = "kalshi_player_props"
    source_table = "kalshi/player-props"
    processing_strategy = ProcessingStrategy.CHECK_BEFORE_INSERT

    HASH_FIELDS = [
        'player_lookup', 'game_date', 'prop_type',
        'line_value', 'yes_ask', 'no_ask'
    ]

    def process_file(self, gcs_uri: str) -> ProcessingResult:
        """Process a single Kalshi props file."""
        raw_data = self._download_gcs_file(gcs_uri)
        records = []

        for prop in raw_data.get("props", []):
            record = self._transform_prop(prop)
            record["data_hash"] = self._compute_hash(record)
            records.append(record)

        self._write_to_bigquery(records)
        return ProcessingResult(success=True, records_processed=len(records))

    def _transform_prop(self, prop: dict) -> dict:
        """Transform raw Kalshi prop to BigQuery schema."""
        return {
            "game_date": prop["game_date"],
            "series_ticker": prop["series_ticker"],
            "event_ticker": prop["event_ticker"],
            "market_ticker": prop["market_ticker"],
            "prop_type": prop["prop_type"],
            "kalshi_player_name": prop["player_name"],
            "player_lookup": normalize_name(prop["player_name"]),
            "line_value": prop["line_value"],
            "yes_bid": prop.get("yes_bid"),
            "yes_ask": prop.get("yes_ask"),
            "no_bid": prop.get("no_bid"),
            "no_ask": prop.get("no_ask"),
            "implied_over_prob": prop.get("yes_ask", 50) / 100.0,
            "implied_under_prob": prop.get("no_ask", 50) / 100.0,
            "equivalent_over_odds": self._to_american_odds(prop.get("yes_ask", 50)),
            "equivalent_under_odds": self._to_american_odds(prop.get("no_ask", 50)),
            "yes_bid_size": prop.get("yes_bid_size"),
            "yes_ask_size": prop.get("yes_ask_size"),
            "total_volume": prop.get("volume"),
            "open_interest": prop.get("open_interest"),
            "liquidity_score": self._calc_liquidity_score(prop),
            "market_status": prop.get("status", "active"),
            "has_team_issues": True,  # Will be validated later
            "scraped_at": prop["scraped_at"],
            "processed_at": datetime.utcnow(),
        }

    def _to_american_odds(self, cents: int) -> int:
        """Convert Kalshi cents (0-100) to American odds."""
        if cents >= 50:
            return int(-100 * cents / (100 - cents))
        else:
            return int(100 * (100 - cents) / cents)

    def _calc_liquidity_score(self, prop: dict) -> str:
        """Assess market liquidity."""
        total_size = sum([
            prop.get("yes_bid_size", 0),
            prop.get("yes_ask_size", 0),
            prop.get("no_bid_size", 0),
            prop.get("no_ask_size", 0),
        ])
        if total_size >= 1000:
            return "HIGH"
        elif total_size >= 100:
            return "MEDIUM"
        else:
            return "LOW"
```

---

### Task 6: Register Processor

**File:** `data_processors/raw/registry.py`

**Add:**
```python
RAW_PROCESSOR_REGISTRY = {
    # ... existing processors ...
    "kalshi_props": (
        "data_processors.raw.kalshi.kalshi_props_processor",
        "KalshiPropsProcessor"
    ),
}
```

---

### Task 7: Create Validation Config

**File:** `validation/configs/scrapers/kalshi_player_props.yaml`

```yaml
scraper: kalshi_player_props
description: "Kalshi NBA player props validation"

schema:
  required_fields:
    - props
    - count

  prop_schema:
    required_fields:
      - market_ticker
      - event_ticker
      - player_name
      - line_value
      - prop_type

value_ranges:
  points:
    min: 3.5
    max: 60.5
  rebounds:
    min: 0.5
    max: 25.5
  assists:
    min: 0.5
    max: 20.5
  threes:
    min: 0.5
    max: 12.5

  contract_price:
    min: 1
    max: 99

row_count:
  min: 5    # May have fewer props than traditional books
  max: 300

notifications:
  on_failure:
    - severity: "warning"  # Not critical, Kalshi is supplementary
      channels: ["slack"]
```

---

### Task 8: Update Player Loader

**File:** `predictions/coordinator/player_loader.py`

**Changes:**
```python
def get_betting_line(self, player_lookup: str, game_date: date) -> dict:
    """Get betting line with Kalshi data."""
    result = self._get_primary_line(player_lookup, game_date)

    # Add Kalshi data
    kalshi_data = self._query_kalshi_line(player_lookup, game_date)
    if kalshi_data:
        result["kalshi_available"] = True
        result["kalshi_line"] = kalshi_data["line_value"]
        result["kalshi_yes_price"] = kalshi_data["contract_price"]
        result["kalshi_liquidity"] = kalshi_data["liquidity_score"]
        result["kalshi_market_ticker"] = kalshi_data["market_ticker"]
        result["line_discrepancy"] = abs(
            result["line_value"] - kalshi_data["line_value"]
        )
    else:
        result["kalshi_available"] = False

    return result

def _query_kalshi_line(self, player_lookup: str, game_date: date) -> Optional[dict]:
    """Query Kalshi props table."""
    query = """
        SELECT
            line_value,
            yes_ask as contract_price,
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
    # Execute query...
```

---

### Task 9: Update Predictions Schema

**File:** `schemas/bigquery/predictions/player_prop_predictions_alter.sql`

```sql
-- Add Kalshi fields to predictions table
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS kalshi_available BOOLEAN,
ADD COLUMN IF NOT EXISTS kalshi_line FLOAT64,
ADD COLUMN IF NOT EXISTS kalshi_yes_price INT64,
ADD COLUMN IF NOT EXISTS kalshi_no_price INT64,
ADD COLUMN IF NOT EXISTS kalshi_liquidity STRING,
ADD COLUMN IF NOT EXISTS kalshi_market_ticker STRING,
ADD COLUMN IF NOT EXISTS line_discrepancy FLOAT64;
```

---

### Task 10: Create Scheduler Job

**Commands:**
```bash
# Create scheduler for Kalshi scraper
gcloud scheduler jobs create http kalshi-props-scraper \
    --schedule="0 7 * * *" \
    --uri="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"scraper":"kalshi_player_props","date":"TODAY","group":"prod"}' \
    --time-zone="UTC" \
    --location="us-west2" \
    --oidc-service-account-email="scheduler-invoker@nba-props-platform.iam.gserviceaccount.com"
```

---

### Task 11: Deploy and Test

**Steps:**
1. Deploy scraper service
2. Test scraper manually
3. Deploy processor service
4. Test processor manually
5. Run full pipeline test
6. Enable scheduler

**Commands:**
```bash
# Deploy scraper
./bin/deploy-service.sh nba-scrapers

# Test scraper
curl -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper":"kalshi_player_props","date":"2026-02-01","group":"dev"}'

# Deploy processor
./bin/deploy-service.sh nba-phase2-processors

# Test processor
curl -X POST https://nba-phase2-processors-f7p3g7f6ya-wl.a.run.app/process \
  -H "Content-Type: application/json" \
  -d '{"processor":"kalshi_props","date":"2026-02-01"}'

# Verify data
bq query --use_legacy_sql=false "
  SELECT game_date, prop_type, COUNT(*) as props,
         AVG(yes_ask) as avg_over_price,
         COUNTIF(liquidity_score = 'HIGH') as high_liquidity
  FROM nba_raw.kalshi_player_props
  WHERE game_date = '2026-02-01'
  GROUP BY 1, 2"
```

## Execution Strategy

### Recommended: Parallel Agent Execution

Since many tasks are independent, we can parallelize:

**Wave 1 (Parallel):**
- Task 1: BigQuery schema (Bash)
- Task 2: Kalshi scraper (general-purpose)
- Task 3: GCS path config (general-purpose)
- Task 9: Predictions schema (Bash)

**Wave 2 (After Wave 1):**
- Task 4: Register scraper (needs Task 2)
- Task 5: Raw processor (needs Task 1)
- Task 8: Player loader update (needs Task 1)

**Wave 3 (After Wave 2):**
- Task 6: Register processor (needs Task 5)
- Task 7: Validation config (needs Task 2, 5)

**Wave 4 (After Wave 3):**
- Task 10: Scheduler (needs Task 4)
- Task 11: Deploy and test (needs all)

## Pre-requisites

Before starting implementation:

1. **Kalshi Account Setup**
   - Create Kalshi account
   - Generate API key pair
   - Note API key ID

2. **Store Credentials**
   ```bash
   # Generate RSA key pair
   openssl genrsa -out kalshi_private_key.pem 2048
   openssl rsa -in kalshi_private_key.pem -pubout -out kalshi_public_key.pem

   # Upload public key to Kalshi dashboard

   # Store private key in Secret Manager
   gcloud secrets create kalshi-api-private-key \
       --data-file=./kalshi_private_key.pem

   gcloud secrets create kalshi-api-key-id \
       --data-file=<(echo "YOUR_API_KEY_ID")
   ```

3. **Test API Access**
   ```bash
   # Quick test that API is reachable
   curl https://trading-api.kalshi.com/trade-api/v2/exchange/status
   ```

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Kalshi API changes | Version API calls, monitor for errors |
| Low liquidity | Display liquidity score prominently |
| Player name mismatches | Use fuzzy matching, manual mapping table |
| Rate limiting | Conservative delays, exponential backoff |
| Missing markets | Graceful degradation, not blocking |
