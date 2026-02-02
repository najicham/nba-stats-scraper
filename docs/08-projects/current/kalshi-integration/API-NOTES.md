# Kalshi API Notes

## Base URLs

| Environment | URL |
|-------------|-----|
| Production | `https://trading-api.kalshi.com/trade-api/v2` |
| Demo | `https://demo-api.kalshi.co/trade-api/v2` |

## Authentication

Kalshi uses RSA key-based authentication (not simple API keys).

### Setup Process

1. **Generate RSA Key Pair**
   ```bash
   openssl genrsa -out kalshi_private_key.pem 2048
   openssl rsa -in kalshi_private_key.pem -pubout -out kalshi_public_key.pem
   ```

2. **Register Public Key with Kalshi**
   - Go to Kalshi Settings > API Keys
   - Create new API key
   - Upload `kalshi_public_key.pem`
   - Note the API Key ID

3. **Store Private Key Securely**
   ```bash
   gcloud secrets create kalshi-api-private-key \
       --data-file=./kalshi_private_key.pem
   ```

### Request Signing

Each request requires these headers:

```
KALSHI-ACCESS-KEY: {api_key_id}
KALSHI-ACCESS-SIGNATURE: {base64_encoded_signature}
KALSHI-ACCESS-TIMESTAMP: {iso8601_timestamp}
```

**Signature Generation:**
```python
message = f"{timestamp}{method}{path}"
signature = private_key.sign(message.encode(), PKCS1v15(), SHA256())
header_value = base64.b64encode(signature).decode()
```

## Relevant Endpoints

### Get Exchange Status (No Auth)
```
GET /exchange/status

Response:
{
  "exchange_status": "open",
  "trading_active": true
}
```

### List Events
```
GET /events?series_ticker=KXNBA&status=open

Response:
{
  "events": [
    {
      "event_ticker": "KXNBA-26-LAL-BOS-20260201",
      "title": "Lakers vs Celtics - Feb 1",
      "category": "Sports",
      "sub_title": "NBA",
      "mutually_exclusive": true,
      "markets": ["KXNBA-26-LEBRON-PTS-25", ...]
    }
  ],
  "cursor": "next_page_token"
}
```

### List Markets
```
GET /markets?event_ticker=KXNBA-26-LAL-BOS-20260201

Response:
{
  "markets": [
    {
      "ticker": "KXNBA-26-LEBRON-PTS-25",
      "event_ticker": "KXNBA-26-LAL-BOS-20260201",
      "subtitle": "LeBron James Over 25.5 Points",
      "yes_bid": 52,
      "yes_ask": 55,
      "no_bid": 45,
      "no_ask": 48,
      "volume": 1500,
      "open_interest": 800,
      "status": "active",
      "close_time": "2026-02-02T03:00:00Z"
    }
  ]
}
```

### Get Orderbook
```
GET /markets/{ticker}/orderbook

Response:
{
  "orderbook": {
    "yes": [
      {"price": 55, "quantity": 500},
      {"price": 54, "quantity": 300},
      {"price": 53, "quantity": 200}
    ],
    "no": [
      {"price": 48, "quantity": 400},
      {"price": 47, "quantity": 250}
    ]
  }
}
```

### Get Market History
```
GET /markets/{ticker}/history?limit=100

Response:
{
  "history": [
    {
      "ts": 1706832000,
      "yes_price": 55,
      "volume": 50
    }
  ]
}
```

## Rate Limits

| Tier | Requests/Second | Batch Size |
|------|-----------------|------------|
| Default | 10 | 20 orders |
| Advanced | 50 | 100 orders |
| Professional | 100 | 500 orders |

**Recommendation:** Use 100ms delay between requests to stay well under limits.

## Market Ticker Format

NBA player props follow this pattern:
```
KXNBA-{season}-{player_code}-{prop_type}-{line}

Examples:
KXNBA-26-LEBRON-PTS-25     (LeBron points O/U 25.5)
KXNBA-26-CURRY-3PM-5       (Curry 3-pointers O/U 5.5)
KXNBA-26-JOKIC-REB-12      (Jokic rebounds O/U 12.5)
KXNBA-26-TRAE-AST-9        (Trae Young assists O/U 9.5)
```

## Contract Pricing

Kalshi uses **cents** (0-100) for contract prices:

| Cents | Implied Probability | American Odds Equivalent |
|-------|--------------------|-----------------------|
| 50 | 50% | -100 / +100 (even) |
| 60 | 60% | -150 |
| 40 | 40% | +150 |
| 70 | 70% | -233 |
| 30 | 30% | +233 |
| 80 | 80% | -400 |
| 20 | 20% | +400 |

**Conversion Formula:**
```python
def cents_to_american(cents: int) -> int:
    if cents >= 50:
        return int(-100 * cents / (100 - cents))
    else:
        return int(100 * (100 - cents) / cents)
```

## Bid-Ask Spread

Always note the spread:
- **Tight spread** (2-3 cents): Liquid market, good execution
- **Wide spread** (5+ cents): Illiquid, may not fill at displayed price

```python
spread = yes_ask - yes_bid  # or equivalently: no_ask - no_bid
```

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| 400 | Bad Request | Check parameters |
| 401 | Unauthorized | Re-sign request, check key |
| 403 | Forbidden | Check permissions |
| 404 | Not Found | Market/event doesn't exist |
| 429 | Rate Limited | Back off, retry |
| 500 | Server Error | Retry with backoff |

## Pagination

Endpoints return a `cursor` field for pagination:

```python
all_results = []
cursor = None

while True:
    params = {"series_ticker": "KXNBA", "status": "open"}
    if cursor:
        params["cursor"] = cursor

    response = requests.get(f"{BASE_URL}/events", params=params, headers=auth_headers)
    data = response.json()

    all_results.extend(data.get("events", []))

    cursor = data.get("cursor")
    if not cursor:
        break

    time.sleep(0.1)  # Rate limiting
```

## Demo Environment

Use demo environment for testing:
- Base URL: `https://demo-api.kalshi.co/trade-api/v2`
- Same authentication method
- Fake money, real market structure
- Good for integration testing

## Useful Links

- [API Documentation](https://docs.kalshi.com/welcome)
- [OpenAPI Spec](https://docs.kalshi.com/openapi.json)
- [Python SDK (community)](https://github.com/topics/kalshi-api)
- [Kalshi Help Center](https://help.kalshi.com/kalshi-api)
