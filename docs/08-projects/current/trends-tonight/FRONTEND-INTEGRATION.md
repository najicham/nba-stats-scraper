# Frontend Integration: Consolidated Trends Tonight Endpoint

**Backend:** `TrendsTonightExporter` — ready and deployed
**Endpoint:** `GET https://storage.googleapis.com/nba-props-platform-api/v1/trends/tonight.json`
**Cache:** `public, max-age=3600` (1 hour)
**Refresh:** Daily, triggered by Phase 6 export pipeline

---

## What This Replaces

Instead of fetching 6+ individual JSON files (`whos-hot-v2.json`, `bounce-back.json`, etc.), the frontend fetches **one file** that contains everything the Trends page needs for tonight's games.

---

## Response Shape

```json
{
  "metadata": {
    "generated_at": "2026-02-12T18:30:00+00:00",
    "game_date": "2026-02-12",
    "games_tonight": 5,
    "version": "2"
  },
  "players": {
    "hot": [ /* HotPlayerEntryV2[], max 10 */ ],
    "cold": [ /* HotPlayerEntryV2[], max 10 */ ],
    "bounce_back": [ /* BounceBackEntry[], max 5 */ ]
  },
  "matchups": [ /* MatchupCard[], one per game */ ],
  "insights": [ /* TrendInsight[], max 12 */ ]
}
```

---

## Type Mismatches to Resolve

The backend output does NOT match the current frontend types in `types.ts`. Below are the differences and recommended approach for each section.

### 1. `players.hot` / `players.cold` — Minor Differences

**Backend sends:**
```json
{
  "rank": 1,
  "player_lookup": "stephencurry",
  "player_full_name": "Stephen Curry",
  "team_abbr": "GSW",
  "position": "PG",
  "heat_score": 8.5,
  "hit_rate": 0.75,
  "hit_rate_games": 10,
  "current_streak": 5,
  "streak_direction": "over",
  "avg_margin": 3.2,
  "playing_tonight": true,
  "tonight": {
    "opponent": "LAL",
    "game_time": "7:30 PM ET",
    "home": true
  },
  "prop_line": 27.5
}
```

**vs. Frontend `HotPlayerEntryV2`:**
- `prop_line` is at the top level, not inside `tonight`. Frontend type has `tonight.prop_line`.
- All players are pre-filtered to `playing_tonight === true`, so that field is always `true`.
- `tonight` is always present (never null) since we filter.

**Recommendation:** Either move `prop_line` inside `tonight` on the backend, OR update the frontend type. Simplest: update the frontend type to accept `prop_line` at the top level alongside `tonight`.

### 2. `players.bounce_back` — Significant Differences

**Backend sends:**
```json
{
  "rank": 1,
  "player_lookup": "stephencurry",
  "player_full_name": "Stephen Curry",
  "team_abbr": "GSW",
  "last_game": {
    "date": "2026-02-11",
    "result": 12,
    "opponent": "LAL",
    "margin": -14.5
  },
  "season_average": 26.5,
  "shortfall": 14.5,
  "bounce_back_rate": 0.786,
  "bounce_back_sample": 14,
  "significance": "high",
  "playing_tonight": true,
  "tonight": {
    "opponent": "PHX",
    "game_time": "7:30 PM ET",
    "home": true
  },
  "prop_line": 27.5
}
```

**vs. Frontend `BounceBackCandidate`:**

| Frontend expects | Backend sends | Notes |
|---|---|---|
| `prop_type: PropType` | not sent | Backend is points-only. Hardcode `"points"` on frontend or omit |
| `last_game.line` | not sent | Backend sends `last_game.result` and `last_game.margin` |
| `last_game.context` | not sent | Optional field, can be omitted |
| `streak.consecutive_misses` | not sent | Backend uses shortfall model, not consecutive-miss model |
| `streak.avg_miss_margin` | not sent | Same — different model |
| `baseline.season_hit_rate` | not sent | Backend sends `bounce_back_rate` instead |
| `baseline.season_avg` | `season_average` | Rename on frontend |
| `tonight.opp_defense_rank` | not sent | Not available without extra query |
| `tonight.current_line` | `prop_line` (top level) | Different location |
| `signal_strength` | `significance` | Different name: `"high"/"medium"/"low"` vs `"strong"/"moderate"` |

**Recommendation:** Create a new simpler type `TonightBounceBackEntry` that matches what the backend actually sends, or add a transform layer. The backend's shortfall model (10+ below season avg) is deliberately different from the consecutive-misses model in the old frontend type.

### 3. `matchups` — Structural Differences

**Backend sends:**
```json
{
  "game_id": "0022500001",
  "away_team": { "abbr": "LAL", "name": "Los Angeles Lakers" },
  "home_team": { "abbr": "GSW", "name": "Golden State Warriors" },
  "spread": -4.5,
  "total": 228.5,
  "defense": { "away_opp_ppg": 115.2, "home_opp_ppg": 110.8 },
  "rest": { "away_days": 1, "home_days": 2, "away_b2b": true, "home_b2b": false },
  "injuries": { "away_starters_out": 1, "home_starters_out": 0 },
  "over_rate": { "away_l15": 0.53, "home_l15": 0.47 },
  "pace": { "away": 100.2, "home": 98.7 },
  "key_insight": "LAL on B2B; GSW rested (2 days)"
}
```

**vs. Frontend `TonightMatchup`:**

| Frontend expects | Backend sends | Notes |
|---|---|---|
| `game_time` | not sent | Not available from team context table |
| `matchup_insights.pace.home_rank` | `pace.home` (raw value) | Backend sends raw pace, not rank |
| `matchup_insights.pace.combined_label` | not sent | Frontend can derive: `<98` = slow, `98-102` = avg, `>102` = fast |
| `matchup_insights.defense.home_rating` | `defense.home_opp_ppg` | Different metric name, same concept |
| `matchup_insights.rest` | `rest` (flat) | Same data, different nesting |
| `matchup_insights.recent_ou` | `over_rate` | Same data, different key names |
| — | `spread`, `total` | **Extra fields** not in frontend type (useful for display) |
| — | `injuries` | **Extra field** not in frontend type |

**Recommendation:** Update the frontend `TonightMatchup` type to match the flat structure the backend sends. The backend structure is simpler and has more data (spread, total, injuries). The frontend can derive labels/ranks from raw values.

### 4. `insights` — Minor Type Differences

**Backend sends:**
```json
{
  "id": "ti-b2b-lal",
  "type": "alert",
  "headline": "B2B Alert: LAL on second night",
  "description": "1 team(s) playing a back-to-back tonight...",
  "main_value": "1",
  "is_positive": false,
  "confidence": "high",
  "sample_size": 1,
  "tags": ["rest", "b2b", "lal"],
  "players": []
}
```

**vs. Frontend `TrendInsight`:**
- `type`: Backend sends `"alert" | "info" | "positive"`. Frontend expects `"stat" | "pattern" | "alert" | "trend"`.

**Recommendation:** Either:
- (a) Update backend `type` values to use frontend's vocabulary (`"info"` → `"stat"`, `"positive"` → `"trend"`), or
- (b) Update frontend type to accept `"alert" | "info" | "positive"`, or
- (c) Frontend maps unknown types to a default style

I'd suggest **(b)** — the backend types are more descriptive for rendering (alert = red/warning, info = neutral blue, positive = green).

---

## Fields the Backend Sends That Are NOT in Current Frontend Types

These are bonus fields the frontend can use for richer display:

| Section | Field | Description |
|---|---|---|
| matchups | `spread` | Vegas spread (home team perspective) |
| matchups | `total` | Vegas game total |
| matchups | `injuries.away_starters_out` | Count of starters out |
| matchups | `injuries.home_starters_out` | Count of starters out |
| matchups | `rest.away_b2b` / `home_b2b` | Boolean B2B flags |
| players.hot/cold | `rank` | Pre-computed 1-N rank |
| players.bounce_back | `shortfall` | How far below season avg |
| players.bounce_back | `bounce_back_rate` | Historical recovery % |
| insights | `tags` | For filtering/grouping insights |
| insights | `players` | player_lookups for linking |

---

## Recommended Frontend Changes

### Option A: Transform layer (minimal backend changes)

Add a `transformTrendsData()` function that reshapes the backend response into the existing frontend types. Quick to implement but adds a maintenance burden.

### Option B: Update frontend types (recommended)

Create a new `TrendsTonight` type family that matches the backend exactly:

```typescript
// New consolidated response type
interface TrendsTonightResponse {
  metadata: {
    generated_at: string;
    game_date: string;
    games_tonight: number;
    version: string;
  };
  players: {
    hot: TonightHotColdPlayer[];
    cold: TonightHotColdPlayer[];
    bounce_back: TonightBounceBack[];
  };
  matchups: TonightMatchupCard[];
  insights: TonightInsight[];
}

// Extends existing HotPlayerEntryV2 with prop_line at top level
interface TonightHotColdPlayer extends HotPlayerEntryV2 {
  rank: number;
  prop_line: number | null;
}

// Simplified bounce-back matching backend's shortfall model
interface TonightBounceBack {
  rank: number;
  player_lookup: string;
  player_full_name: string;
  team_abbr: string;
  last_game: {
    date: string;
    result: number;
    opponent: string;
    margin: number;
  };
  season_average: number;
  shortfall: number;
  bounce_back_rate: number;
  bounce_back_sample: number;
  significance: 'high' | 'medium' | 'low';
  playing_tonight: boolean;
  tonight: {
    opponent: string;
    game_time: string;
    home: boolean;
  } | null;
  prop_line: number | null;
}

// Flat matchup card with all context
interface TonightMatchupCard {
  game_id: string;
  away_team: { abbr: string; name: string };
  home_team: { abbr: string; name: string };
  spread: number | null;
  total: number | null;
  defense: { away_opp_ppg: number | null; home_opp_ppg: number | null };
  rest: {
    away_days: number | null;
    home_days: number | null;
    away_b2b: boolean;
    home_b2b: boolean;
  };
  injuries: {
    away_starters_out: number;
    home_starters_out: number;
  };
  over_rate: { away_l15: number | null; home_l15: number | null };
  pace: { away: number | null; home: number | null };
  key_insight: string;
}

// Insight with backend's type vocabulary
interface TonightInsight {
  id: string;
  type: 'alert' | 'info' | 'positive';
  headline: string;
  description: string;
  main_value: string;
  is_positive: boolean | null;
  confidence: 'high' | 'medium' | 'low';
  sample_size: number | null;
  tags: string[];
  players: string[];
}
```

### Option C: Backend adapts to frontend types

I can update the backend to match the existing frontend types more closely. This would mean:
- Nest `prop_line` inside `tonight` for hot/cold players
- Reshape matchups to use `matchup_insights` nesting
- Map insight `type` to the frontend's vocabulary
- Add `game_time` to matchups (requires joining schedule data)

Trade-off: more backend work now, but zero frontend type changes.

---

## How to Fetch

```typescript
const API_BASE = 'https://storage.googleapis.com/nba-props-platform-api/v1';

async function fetchTrendsTonight(): Promise<TrendsTonightResponse> {
  const res = await fetch(`${API_BASE}/trends/tonight.json`);
  if (!res.ok) throw new Error(`Trends fetch failed: ${res.status}`);
  return res.json();
}
```

---

## Testing

Backend can be tested locally:
```bash
# Generate the file locally (requires GCP auth)
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2026-02-12 --only trends-tonight

# Check output at:
# gs://nba-props-platform-api/v1/trends/tonight.json
```

The endpoint returns real data from today's games. If no games are scheduled, sections will be empty but the response structure is still valid.

---

## Decision Needed

Before the frontend starts, we need to decide: **Option A, B, or C?**

- **A** (transform layer) — fastest if existing components are tightly coupled to current types
- **B** (new frontend types) — cleanest long-term, recommended if this is a page redesign anyway
- **C** (backend adapts) — I can do this in ~30 min if you'd rather not touch frontend types
