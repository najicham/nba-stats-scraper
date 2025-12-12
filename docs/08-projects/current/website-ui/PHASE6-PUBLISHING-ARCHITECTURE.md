# Phase 6 Publishing Architecture

**Document Version:** 1.0
**Created:** 2025-12-11
**Status:** Reference document for website implementation

This document describes the Phase 6 publishing system that generates JSON API files for the website.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Current Implementation](#2-current-implementation)
3. [Storage Architecture](#3-storage-architecture)
4. [New Exporters Needed](#4-new-exporters-needed)
5. [Enhancements to Existing](#5-enhancements-to-existing)
6. [Data Source Reference](#6-data-source-reference)
7. [Frontend Repository Notes](#7-frontend-repository-notes)

---

## 1. Overview

### What is Phase 6?

Phase 6 transforms BigQuery data into static JSON files served from GCS. The website consumes these JSON files directly - no backend server required.

```
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│     BigQuery        │      │    Phase 6          │      │    GCS Bucket       │
│  (source of truth)  │ ───→ │    Exporters        │ ───→ │    (JSON API)       │
│                     │      │    (Python)         │      │                     │
└─────────────────────┘      └─────────────────────┘      └─────────────────────┘
                                                                    │
                                                                    │ fetch()
                                                                    ▼
                                                          ┌─────────────────────┐
                                                          │   Static Website    │
                                                          │   (Next.js)         │
                                                          └─────────────────────┘
```

### Key Principles

1. **Pre-computed JSON** - No real-time queries; everything is pre-generated
2. **CDN-cacheable** - Appropriate Cache-Control headers per file type
3. **Public access** - No auth needed for public prediction data
4. **Date-based organization** - Historical data accessible by date

---

## 2. Current Implementation

### 2.1 Existing Exporters

| Exporter | Output Path | Purpose | Status |
|----------|-------------|---------|--------|
| `BestBetsExporter` | `best-bets/{date}.json`, `best-bets/latest.json` | Top ranked picks | ✅ Working |
| `PredictionsExporter` | `predictions/{date}.json`, `predictions/today.json` | All predictions grouped by game | ✅ Working |
| `ResultsExporter` | `results/{date}.json`, `results/latest.json` | Prediction outcomes | ✅ Working |
| `SystemPerformanceExporter` | `systems/performance.json` | Rolling accuracy metrics | ✅ Working |
| `PlayerProfileExporter` | `players/index.json`, `players/{lookup}.json` | Player accuracy profiles | ✅ Working |

### 2.2 Code Structure

```
data_processors/publishing/
├── __init__.py
├── base_exporter.py              # Abstract base class
├── best_bets_exporter.py         # Top picks ranking
├── predictions_exporter.py       # Daily predictions
├── results_exporter.py           # Prediction outcomes
├── system_performance_exporter.py # System accuracy
└── player_profile_exporter.py    # Player accuracy profiles

backfill_jobs/publishing/
└── daily_export.py               # CLI orchestrator
```

### 2.3 Base Exporter Pattern

All exporters inherit from `BaseExporter`:

```python
class BaseExporter(ABC):
    def __init__(self, project_id, bucket_name):
        self.bq_client = bigquery.Client(project=project_id)
        self.gcs_client = storage.Client(project=project_id)

    @abstractmethod
    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """Generate JSON content - implemented by subclasses"""
        pass

    def query_to_list(self, query, params) -> List[Dict]:
        """Execute BQ query, return list of dicts"""
        pass

    def upload_to_gcs(self, json_data, path, cache_control) -> str:
        """Upload JSON to GCS with cache headers"""
        pass

    def get_generated_at(self) -> str:
        """UTC timestamp for generated_at field"""
        pass
```

### 2.4 CLI Usage

```bash
# Export single date (all exporters)
python daily_export.py --date 2024-12-10

# Export yesterday (default)
python daily_export.py

# Backfill date range
python daily_export.py --start-date 2024-01-01 --end-date 2024-12-10

# Export only specific types
python daily_export.py --date 2024-12-10 --only results,best-bets

# Export player profiles
python daily_export.py --players --min-games 5
```

---

## 3. Storage Architecture

### 3.1 GCS Bucket Structure

**Bucket:** `gs://nba-props-platform-api`

```
v1/
├── tonight/                          # NEW - Website primary endpoints
│   ├── all-players.json             # All players tonight (initial load)
│   └── player/
│       └── {lookup}.json            # Tonight tab detail per player
│
├── best-bets/
│   ├── {date}.json                  # Historical best bets
│   ├── latest.json                  # Symlink to most recent
│   └── today.json                   # NEW - Alias for current date
│
├── predictions/
│   ├── {date}.json                  # Historical predictions
│   └── today.json                   # Current predictions
│
├── results/
│   ├── {date}.json                  # Historical results
│   └── latest.json                  # Most recent with data
│
├── systems/
│   └── performance.json             # Rolling system accuracy
│
└── players/
    ├── index.json                   # All players summary
    └── {lookup}.json                # Individual player profiles
```

### 3.2 Cache-Control Settings

| Endpoint Pattern | Cache TTL | Reason |
|------------------|-----------|--------|
| `tonight/*.json` | 5 min | Lines can change |
| `best-bets/today.json` | 5 min | Rankings can shift |
| `best-bets/{date}.json` | 24 hr | Historical, immutable |
| `predictions/today.json` | 5 min | Reflects current state |
| `results/{date}.json` | 24 hr | Historical, immutable |
| `systems/performance.json` | 1 hr | Aggregated, stable |
| `players/index.json` | 1 hr | Changes slowly |
| `players/{lookup}.json` | 1 hr | Historical profile |

### 3.3 URL Pattern

Public URL: `https://storage.googleapis.com/nba-props-platform-api/v1/{path}`

Example: `https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/latest.json`

---

## 4. New Exporters Needed

### 4.1 TonightAllPlayersExporter (HIGH PRIORITY)

**Output:** `/v1/tonight/all-players.json`
**Purpose:** Initial page load - all players in tonight's games
**Size:** ~150 KB
**Cache:** 5 minutes

**Data Flow:**
```
nba_predictions.player_prop_predictions     ─┐
nba_analytics.upcoming_player_game_context  ─┼──→ TonightAllPlayersExporter ──→ all-players.json
nba_precompute.player_composite_factors     ─┤
nba_raw.nbac_injury_report                  ─┤
nba_analytics.player_game_summary           ─┘
```

**Key Fields:**
- Player identification (lookup, full_name, team)
- Line data (current_line, opening_line, predicted, confidence, recommendation)
- Fatigue (fatigue_score, fatigue_level)
- Injury (status, reason)
- Recent form (last_10_results, last_10_record, season_ppg, last_5_ppg)
- Game context (game_id, opponent, game_time, game_status)

**Grouping:** By game, players within each game

**Schema:** See MASTER-SPEC.md §7.2

---

### 4.2 TonightPlayerExporter (HIGH PRIORITY)

**Output:** `/v1/tonight/player/{lookup}.json`
**Purpose:** Tonight tab detail - game-specific context
**Size:** ~3-5 KB per player
**Cache:** 5 minutes

**Data Flow:**
```
nba_predictions.player_prop_predictions     ─┐
nba_analytics.upcoming_player_game_context  ─┼──→ TonightPlayerExporter ──→ player/{lookup}.json
nba_precompute.player_composite_factors     ─┤
nba_analytics.player_game_summary           ─┤
nba_analytics.team_defense_game_summary     ─┘
```

**Key Fields:**
- game_context (opponent, line, movement, rest, injury)
- quick_numbers (season/last10/last5 averages, minutes trend)
- fatigue (score, level, factors, context JSON)
- current_streak (direction, length)
- tonights_factors (only applicable splits - B2B, home/away, vs opponent, vs defense tier)
- recent_form (last 10 games with details)
- prediction (predicted, confidence, recommendation, system_agreement)

**Schema:** See MASTER-SPEC.md §7.3

---

## 5. Enhancements to Existing

### 5.1 PlayerProfileExporter Enhancements

**Current:** 20 recent predictions, basic accuracy stats
**Enhanced:** 50-game log, full splits, defense tiers, streak

**New Fields to Add:**

```python
# game_log expansion (20 → 50 games)
game_log: [
    {
        game_date, opponent, home_game, team_result,
        points, minutes, fg_made, fg_attempted,
        three_made, three_attempted, ft_made, ft_attempted,
        rebounds, assists, steals, blocks, turnovers,
        line, over_under, margin
    }
]

# splits (NEW)
splits: {
    rest: {b2b, one_day, two_day, three_plus},  # each: {avg, games, vs_line_pct}
    location: {home, away},
    defense_tier: {top_10, middle, bottom_10},
    opponents: [{team, avg, games}]
}

# our_track_record (enhanced)
our_track_record: {
    total_predictions, overall: {wins, losses, pct},
    over_calls: {wins, losses, pct},
    under_calls: {wins, losses, pct},
    avg_error, bias, within_3_pts, within_5_pts
}

# next_game (NEW)
next_game: {game_date, opponent, home_game, has_prediction}
```

**Schema:** See MASTER-SPEC.md §7.4

---

### 5.2 Player Index Enhancement

**Current fields:**
```json
{
  "player_lookup": "lebronjames",
  "team": "LAL",
  "games_predicted": 47,
  "mae": 3.2,
  "win_rate": 0.62
}
```

**Add:** `player_full_name` (required for search)

```json
{
  "player_lookup": "lebronjames",
  "player_full_name": "LeBron James",  // ADD THIS
  "team": "LAL",
  "games_predicted": 47,
  "mae": 3.2,
  "win_rate": 0.62
}
```

---

### 5.3 Best Bets Enhancement

**Add:** `player_full_name` to picks array

Currently has `player_lookup` but frontend needs display name.

---

## 6. Data Source Reference

### 6.1 BigQuery Tables Used

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `nba_predictions.player_prop_predictions` | Predictions | predicted_points, confidence_score, recommendation |
| `nba_predictions.prediction_accuracy` | Graded results | prediction_correct, absolute_error, actual_points |
| `nba_predictions.system_daily_performance` | System metrics | win_rate, mae, by system |
| `nba_analytics.player_game_summary` | Game stats | points, minutes, all box score fields |
| `nba_analytics.upcoming_player_game_context` | Game context | days_rest, back_to_back, opponent |
| `nba_precompute.player_composite_factors` | Fatigue | fatigue_score, fatigue_context_json |
| `nba_raw.nbac_injury_report` | Injuries | injury_status, reason |
| `nba_raw.nbac_schedule` | Schedule | game_time, game_status |
| `nba_raw.odds_api_player_points_props` | Lines | points_line, opening_line |
| `nba_analytics.team_defense_game_summary` | Defense | defensive_rating |
| `nba_reference.nba_players_registry` | Player info | player_full_name, player_lookup |

### 6.2 Fatigue Score Source

**Table:** `nba_precompute.player_composite_factors`

**Fields:**
- `fatigue_score` (0-100, higher = more rested)
- `fatigue_context_json` (breakdown of factors)

**Mapping to UI:**
```python
def fatigue_level(score):
    if score >= 95: return "fresh"    # 🟢
    if score >= 75: return "normal"   # 🟡
    return "tired"                     # 🔴
```

---

## 7. Frontend Repository Notes

### 7.1 Recommended Structure

```
nba-props-website/               # Separate repo
├── app/                         # Next.js app router
│   ├── page.tsx                # Tonight (default)
│   ├── results/
│   │   └── page.tsx            # Results page
│   ├── players/
│   │   └── [lookup]/
│   │       └── page.tsx        # Player profile page
│   └── layout.tsx              # Root layout with nav
├── components/
│   ├── PlayerCard.tsx
│   ├── PlayerDetailPanel.tsx
│   ├── BestBetsSection.tsx
│   ├── GameFilter.tsx
│   └── ...
├── lib/
│   ├── api.ts                  # Fetch helpers for GCS JSON
│   ├── types.ts                # TypeScript types matching JSON schemas
│   └── utils.ts
├── public/
└── package.json
```

### 7.2 API Fetch Pattern

```typescript
// lib/api.ts
const API_BASE = 'https://storage.googleapis.com/nba-props-platform-api/v1';

export async function fetchTonightAllPlayers() {
  const res = await fetch(`${API_BASE}/tonight/all-players.json`, {
    next: { revalidate: 300 }  // 5 min cache
  });
  return res.json();
}

export async function fetchPlayerTonight(lookup: string) {
  const res = await fetch(`${API_BASE}/tonight/player/${lookup}.json`, {
    next: { revalidate: 300 }
  });
  return res.json();
}

export async function fetchPlayerProfile(lookup: string) {
  const res = await fetch(`${API_BASE}/players/${lookup}.json`, {
    next: { revalidate: 3600 }  // 1 hr cache
  });
  return res.json();
}
```

### 7.3 TypeScript Types

Generate from JSON schemas in MASTER-SPEC.md:

```typescript
// lib/types.ts
interface TonightPlayer {
  player_lookup: string;
  player_full_name: string;
  team_abbr: string;
  has_line: boolean;
  current_points_line: number | null;
  predicted_points: number;
  confidence_score: number | null;
  recommendation: 'OVER' | 'UNDER' | 'PASS' | null;
  fatigue_level: 'fresh' | 'normal' | 'tired';
  fatigue_score: number;
  injury_status: 'available' | 'questionable' | 'doubtful' | 'out';
  injury_reason: string | null;
  season_ppg: number;
  last_5_ppg: number;
  last_10_results?: ('O' | 'U')[];
  last_10_record?: string;
  last_10_points?: number[];  // For players without lines
}

interface TonightGame {
  game_id: string;
  home_team: string;
  away_team: string;
  game_time: string;  // "19:30" (Eastern Time)
  game_status: 'scheduled' | 'in_progress' | 'final';
  players: TonightPlayer[];
}

interface TonightAllPlayers {
  game_date: string;
  generated_at: string;
  total_players: number;
  total_with_lines: number;
  games: TonightGame[];
}
```

### 7.4 Recommended Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | Next.js 14+ (App Router) | SSR/SSG, great DX |
| Styling | Tailwind CSS | Utility-first, responsive, fast |
| State | React Query or SWR | Caching, revalidation, loading states |
| Deployment | Firebase Hosting | GCP ecosystem, same billing, easy CDN |
| Types | TypeScript | Type safety with JSON API |

### 7.5 Firebase Hosting Setup

```bash
# Install Firebase CLI
npm install -g firebase-tools

# Initialize in frontend repo
firebase init hosting

# firebase.json configuration
{
  "hosting": {
    "public": "out",           # Next.js static export directory
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [
      { "source": "**", "destination": "/index.html" }
    ],
    "headers": [
      {
        "source": "**/*.json",
        "headers": [{ "key": "Cache-Control", "value": "public, max-age=300" }]
      }
    ]
  }
}

# Build and deploy
npm run build          # next build
npx next export        # generates 'out' directory (or use output: 'export' in next.config.js)
firebase deploy
```

### 7.6 Next.js Static Export Config

```javascript
// next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',           // Static export mode
  trailingSlash: true,        // Better for static hosting
  images: {
    unoptimized: true         // Required for static export
  }
}

module.exports = nextConfig
```

### 7.7 Key Implementation Notes

1. **No backend needed** - All data comes from static JSON on GCS
2. **Client-side search** - Filter loaded JSON, no search API
3. **Lazy loading** - Tonight detail + Profile loaded on demand
4. **Mobile-first** - Bottom nav, bottom sheet patterns
5. **Cache appropriately** - Match frontend cache to backend Cache-Control

---

## Implementation Priority

### Phase 1: Core Website (This Sprint)

1. ✅ Enhance PlayerProfileExporter (add player_full_name to index)
2. 🔲 Create TonightAllPlayersExporter
3. 🔲 Create TonightPlayerExporter
4. 🔲 Enhance PlayerProfileExporter (50 games, splits)

### Phase 2: Polish

5. 🔲 Add fatigue fields to best-bets output
6. 🔲 Add limited_data and points_available flags
7. 🔲 Add current streak computation

### Phase 3: Future (V1.5)

8. 🔲 Streaks endpoint (`/v1/streaks/today.json`)
9. 🔲 Enhanced line movement data
10. 🔲 Additional prop types (rebounds, assists)

---

*End of Phase 6 Publishing Architecture*
