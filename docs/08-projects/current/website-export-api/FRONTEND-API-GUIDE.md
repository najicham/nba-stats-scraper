# Frontend API Guide — NBA Props Platform

**Last Updated:** 2026-02-10 (Session 191)

All data is served as pre-computed JSON files from Google Cloud Storage via CDN. No backend API calls — the frontend fetches static JSON files that are regenerated on schedule.

---

## Base URL

```
https://storage.googleapis.com/nba-props-exports/
```

All paths below are relative to this base. Example: `picks/2026-02-10.json` fetches from `https://storage.googleapis.com/nba-props-exports/picks/2026-02-10.json`.

---

## Model System

### Codenames

All models use opaque codenames. **Never expose internal model IDs to users.**

| Codename | Display Name | Type | Description |
|----------|-------------|------|-------------|
| `phoenix` | Phoenix | `primary` | Our primary prediction engine. Balanced predictions across all players. |
| `aurora` | Aurora | `specialist` | Specialist engine with a different approach. Strong on high-confidence picks. |
| `summit` | Summit | `specialist` | Conservative specialist engine. Selective, high-conviction picks. |

### Champion Model

`phoenix` is always the **champion** (primary) model. It appears first in every `model_groups` array. Use it as the default/active tab.

### Model Types

| Type | Meaning | Suggested Styling |
|------|---------|-------------------|
| `primary` | The main model. Has the most data and longest track record. | Default/prominent styling |
| `specialist` | Focused engine with a particular strength. May have less data. | Secondary styling, different accent color |

### New Models

When a model is new, its `record` will be `null`. Display a **"New"** badge instead of W-L stats. New models may also have empty `dates` arrays or empty `picks` in performance windows.

---

## Endpoints

### 1. Daily Picks — `picks/{date}.json`

**The main endpoint for today's picks page.**

| Property | Value |
|----------|-------|
| Path | `picks/{YYYY-MM-DD}.json` |
| Cache | 5 minutes (`max-age=300`) |
| Updated | Every prediction run (4-6x daily) |

**Structure:**

```json
{
  "date": "2026-02-10",
  "generated_at": "2026-02-10T14:30:00Z",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "model_type": "primary",
      "description": "Our primary prediction engine",
      "signal": "favorable",
      "subsets": [
        {
          "id": "1",
          "name": "Top Pick",
          "record": {
            "season": {"wins": 42, "losses": 18, "pct": 70.0},
            "month": {"wins": 8, "losses": 3, "pct": 72.7},
            "week": {"wins": 3, "losses": 1, "pct": 75.0}
          },
          "picks": [
            {
              "player": "LeBron James",
              "team": "LAL",
              "opponent": "BOS",
              "prediction": 26.1,
              "line": 24.5,
              "direction": "OVER"
            }
          ]
        }
      ]
    }
  ]
}
```

**Field Reference:**

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Date in YYYY-MM-DD format |
| `generated_at` | string | ISO 8601 timestamp of last generation |
| `version` | int | Schema version (currently `2`) |
| `model_groups` | array | Array of model objects. Champion first. |

**Model Group Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `model_id` | string | Opaque codename (e.g., `phoenix`) |
| `model_name` | string | Display name (e.g., `Phoenix`) |
| `model_type` | string | `primary` or `specialist` |
| `description` | string | One-line description for tooltips |
| `signal` | string | Market conditions: `favorable`, `neutral`, or `challenging` |
| `subsets` | array | Subset groups with picks |

**Subset Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Numeric ID (e.g., `"1"`) — stable, use for keys |
| `name` | string | Display name (e.g., `"Top Pick"`) |
| `record` | object or null | W-L record. `null` = new subset, show "New" badge. |
| `record.season` | object | `{wins, losses, pct}` for full season |
| `record.month` | object | `{wins, losses, pct}` for current calendar month |
| `record.week` | object | `{wins, losses, pct}` for current calendar week (Mon-Sun) |
| `picks` | array | Array of pick objects (may be empty) |

**Pick Fields (Daily):**

| Field | Type | Description |
|-------|------|-------------|
| `player` | string | Full player name |
| `team` | string | 3-letter team abbreviation (e.g., `LAL`) |
| `opponent` | string | 3-letter opponent abbreviation |
| `prediction` | float | Model's predicted points (1 decimal) |
| `line` | float | Vegas points line (1 decimal) |
| `direction` | string | `OVER` or `UNDER` |

---

### 2. Daily Signal — `signals/{date}.json`

**Market conditions indicator. One signal for all models.**

| Property | Value |
|----------|-------|
| Path | `signals/{YYYY-MM-DD}.json` |
| Cache | 5 minutes (`max-age=300`) |
| Updated | With each prediction run |

```json
{
  "date": "2026-02-10",
  "generated_at": "2026-02-10T14:30:00Z",
  "signal": "favorable",
  "metrics": {
    "conditions": "favorable",
    "picks": 45,
    "pct_over": 62.5
  }
}
```

**Signal Values:**

| Value | Meaning | Suggested Color |
|-------|---------|-----------------|
| `favorable` | Good conditions for predictions | Green |
| `neutral` | Normal conditions | Yellow/Gray |
| `challenging` | Tough conditions, expect lower accuracy | Red |

**Note:** Signal is market-level, not model-specific. All model groups share the same signal.

---

### 3. Subset Performance — `subsets/performance.json`

**Historical accuracy across 6 time windows.**

| Property | Value |
|----------|-------|
| Path | `subsets/performance.json` |
| Cache | 1 hour (`max-age=3600`) |
| Updated | After grading completes |

```json
{
  "generated_at": "2026-02-10T14:30:00Z",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "windows": {
        "last_1_day": {
          "start_date": "2026-02-09",
          "end_date": "2026-02-10",
          "groups": [
            {
              "id": "1",
              "name": "Top Pick",
              "stats": {
                "hit_rate": 100.0,
                "roi": -9.1,
                "picks": 1
              }
            }
          ]
        },
        "last_3_days": { ... },
        "last_7_days": { ... },
        "last_14_days": { ... },
        "last_30_days": { ... },
        "season": { ... }
      }
    }
  ]
}
```

**Windows:**

| Key | Lookback |
|-----|----------|
| `last_1_day` | Yesterday |
| `last_3_days` | Last 3 days |
| `last_7_days` | Last 7 days |
| `last_14_days` | Last 14 days |
| `last_30_days` | Last 30 days |
| `season` | Full NBA season (from Nov 1) |

**Stats Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `hit_rate` | float | Win percentage (0-100) |
| `roi` | float | Return on investment percentage. Positive = profitable. |
| `picks` | int | Number of graded picks in the window |

**Rendering Notes:**
- Let users toggle between windows (tabs or dropdown)
- Default to `last_7_days` or `last_14_days`
- If `picks` is 0, show "No data" instead of stats
- ROI is based on standard -110 juice ($1.10 to win $1.00)

---

### 4. Subset Definitions — `systems/subsets.json`

**Available prediction groups. Rarely changes.**

| Property | Value |
|----------|-------|
| Path | `systems/subsets.json` |
| Cache | 24 hours (`max-age=86400`) |
| Updated | Only when definitions change |

```json
{
  "generated_at": "2026-02-10T14:30:00Z",
  "version": 2,
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "model_type": "primary",
      "description": "Our primary prediction engine",
      "subsets": [
        {
          "id": "1",
          "name": "Top Pick",
          "description": "Single best pick"
        }
      ]
    }
  ]
}
```

**Subset IDs (stable):**

| ID | Name | Model | Description |
|----|------|-------|-------------|
| 1 | Top Pick | Phoenix | Single best pick |
| 2 | Top 3 | Phoenix | Top 3 picks |
| 3 | Top 5 | Phoenix | Top 5 picks |
| 4 | High Edge OVER | Phoenix | High-edge OVER picks |
| 5 | High Edge All | Phoenix | All high-edge picks |
| 6 | Ultra High Edge | Phoenix | Highest edge picks |
| 7 | Green Light | Phoenix | Picks in favorable conditions |
| 8 | All Picks | Phoenix | All qualifying picks |
| 9 | UNDER Top 3 | Aurora | Top 3 UNDER picks |
| 10 | UNDER All | Aurora | All UNDER picks |
| 11 | Q43 All Picks | Aurora | All picks from this engine |
| 12 | Q45 UNDER Top 3 | Summit | Top 3 UNDER picks |
| 13 | Q45 All Picks | Summit | All picks from this engine |

---

### 5. Season Picks — `subsets/season.json`

**Full-season picks history with game results. Largest payload.**

| Property | Value |
|----------|-------|
| Path | `subsets/season.json` |
| Cache | 1 hour (`max-age=3600`) |
| Updated | After grading completes |

```json
{
  "generated_at": "2026-02-10T14:30:00Z",
  "version": 2,
  "season": "2025-26",
  "model_groups": [
    {
      "model_id": "phoenix",
      "model_name": "Phoenix",
      "model_type": "primary",
      "record": {
        "season": {"wins": 42, "losses": 18, "pct": 70.0},
        "month": {"wins": 8, "losses": 3, "pct": 72.7},
        "week": {"wins": 3, "losses": 1, "pct": 75.0}
      },
      "dates": [
        {
          "date": "2026-02-09",
          "signal": "favorable",
          "picks": [
            {
              "player": "LeBron James",
              "team": "LAL",
              "opponent": "BOS",
              "prediction": 26.1,
              "line": 24.5,
              "direction": "OVER",
              "actual": 28,
              "result": "hit"
            }
          ]
        }
      ]
    }
  ]
}
```

**Pick Fields (Season — includes results):**

| Field | Type | Description |
|-------|------|-------------|
| `player` | string | Full player name |
| `team` | string | 3-letter team abbreviation |
| `opponent` | string | 3-letter opponent abbreviation |
| `prediction` | float | Model's predicted points |
| `line` | float | Vegas points line |
| `direction` | string | `OVER` or `UNDER` |
| `actual` | int or null | Actual points scored. `null` = game not played yet. |
| `result` | string or null | `hit`, `miss`, `push`, or `null` (unplayed) |

**Result Values:**

| Value | Meaning |
|-------|---------|
| `hit` | Prediction was correct (OVER and scored above line, or UNDER and scored below) |
| `miss` | Prediction was wrong |
| `push` | Actual points exactly matched the line |
| `null` | Game hasn't been played yet |

**Notes:**
- `dates` array is sorted newest-first
- This file can be large (100+ KB). Consider lazy-loading older dates.
- The `record` here is a model-level aggregate (uses the broadest subset). Per-subset records are in `picks/{date}.json`.

---

## Rendering Guide

### Model Groups as Tabs/Sections

```
[ Phoenix (primary) ] [ Aurora (specialist) ] [ Summit (specialist) ]
```

- Always show champion (`phoenix`) first and as the default active tab
- Use `model_type` for visual differentiation:
  - `primary` → default/prominent styling
  - `specialist` → secondary styling with different accent

### Signal Display

```
Today's Conditions: 🟢 Favorable
```

Map signal values to colors:
- `favorable` → green indicator
- `neutral` → yellow/gray indicator
- `challenging` → red indicator

Signal is the same across all model groups (it reflects market conditions, not model performance).

### W-L Records

```
Season: 42-18 (70.0%)  |  Month: 8-3 (72.7%)  |  Week: 3-1 (75.0%)
```

- When `record` is `null`, show: **"New"** badge
- `pct` is pre-calculated — no need to compute client-side
- Records update after games are graded (usually next morning)

### Performance Window Toggles

```
[ 1D ] [ 3D ] [ 7D ] [ 14D ] [ 30D ] [ Season ]
```

Default to `last_7_days` or `last_14_days`. Show:
- Hit rate as percentage with color coding (>55% green, 50-55% yellow, <50% red)
- ROI as +/- percentage
- Pick count as context ("Based on N picks")
- If `picks` is 0: "No data for this period"

### Pick Result States

For the season view, picks have result states:

| State | Display |
|-------|---------|
| `result: "hit"` | Green checkmark or "W" |
| `result: "miss"` | Red X or "L" |
| `result: "push"` | Gray dash or "Push" |
| `result: null` | No indicator / "Pending" |

### Empty States

| Scenario | What to show |
|----------|-------------|
| `model_groups` is empty | "No predictions available" |
| `subsets[].picks` is empty | "No picks for this group today" |
| `record` is `null` | "New" badge |
| `windows[key].groups` is empty | "No data for this period" |
| `picks` count is 0 in stats | "Insufficient data" |
| Fetch returns 404 | "No predictions for this date" (date may not have had games) |

---

## Cache Strategy

| Endpoint | Cache TTL | Reason |
|----------|-----------|--------|
| `picks/{date}.json` | 5 min | Updates multiple times per day |
| `signals/{date}.json` | 5 min | Updates with predictions |
| `subsets/performance.json` | 1 hour | Updates after grading |
| `subsets/season.json` | 1 hour | Updates after grading |
| `systems/subsets.json` | 24 hours | Definitions rarely change |

**Recommended client-side strategy:**
- Poll `picks/{today}.json` every 5 minutes during game hours (7 PM - 1 AM ET)
- Fetch `subsets/performance.json` once on page load, refresh on window focus
- Fetch `systems/subsets.json` once per session (cache in localStorage)
- For `subsets/season.json`, fetch on page load, no polling needed

---

## Error Handling

| Error | Cause | Handling |
|-------|-------|----------|
| **404** | No data for that date (no games, or predictions not yet generated) | Show "No predictions available for this date" |
| **Empty model_groups** | Predictions haven't run yet today | Show "Predictions will be available soon" |
| **Empty picks array** | Model had no qualifying picks for this subset | Show "No picks in this group today" |
| **null record** | New model with no grading history | Show "New" badge |
| **Stale generated_at** | Export hasn't refreshed recently | Compare `generated_at` to current time; show warning if >2 hours stale during game day |

---

## Data Freshness Timeline

| Time (ET) | What Happens |
|-----------|-------------|
| 2:30 AM | Early predictions generated (may be limited) |
| 6:00 AM | Overnight predictions (full run) |
| 10:00 AM | Morning refresh with updated lines |
| 2:00 PM | Afternoon update |
| 6:00 PM | Evening update (final lines) |
| Next AM | Grading runs, performance/records updated |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2 | 2026-02-10 | Multi-model `model_groups` structure. Codenames: phoenix, aurora, summit. Season exporter v2. |
| 1 | 2026-01-xx | Original single-model format with `groups` array. Deprecated. |
