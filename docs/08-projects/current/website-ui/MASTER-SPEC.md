# NBA Props Platform - Website Phase 1 Master Specification

**Document Version:** 1.2
**Created:** 2025-12-11
**Last Updated:** 2025-12-11
**Status:** Ready for Implementation

> **v1.2 Changes:** Added data conventions (timezone, game_status format, player_lookup), edge case handling (final/no-points, low-data players), and `player_full_name` requirement for index.json.

This document consolidates the UI specification, data investigation, backend recommendations, and implementation plan for Phase 1 of the NBA Props website.

---

## Table of Contents

1. [Product Vision](#1-product-vision)
2. [Information Architecture](#2-information-architecture)
3. [Page & Component Specifications](#3-page--component-specifications)
4. [Game State Transitions](#4-game-state-transitions)
5. [Search Implementation](#5-search-implementation)
6. [Data Loading Architecture](#6-data-loading-architecture)
7. [API Endpoints](#7-api-endpoints)
8. [Data Availability & Gaps](#8-data-availability--gaps)
9. [Implementation Plan](#9-implementation-plan)
10. [Technical Decisions](#10-technical-decisions)

---

## 1. Product Vision

### Core Principle
**Research-first, prediction-supplemented.** The organized, contextualized data is the product. The prediction is one data point that supports the user's own decision-making.

### Target Users (V1)

| User Type | Primary Goal | Key Features |
|-----------|--------------|--------------|
| **Sports Bettor** | Research tonight's games, form opinion, make bet | Predictions, splits, line movement |
| **Casual Fan** | Browse player stats, check performance | Season stats, game logs, trends |

### Differentiator
Clean presentation of relevant data, surfaced intelligently based on tonight's context. Not just predictions, not just raw stats - the intersection.

### V1 Scope

**In Scope:**
- Tonight's Picks (players with betting lines + predictions)
- All Players (everyone playing tonight)
- Player detail panel with Tonight/Profile tabs
- Results page (yesterday + rolling accuracy)
- Search functionality
- Mobile-responsive design

**Out of Scope (V1.5+):**
- Live game scores (final scores only)
- User accounts / saved players
- Streaks page
- Player comparison tool
- Premium features

---

## 2. Information Architecture

### Site Structure

```
NBA Props Platform
│
├── Tonight (Default) ─────────────────────────────────
│   ├── Tab: Tonight's Picks (players with lines)
│   │   ├── Best Bets section (top 5-10)
│   │   └── Player grid (filterable, sortable)
│   │
│   └── Tab: All Players (everyone tonight)
│       ├── Game selector (required first)
│       └── Player grid by team
│
├── Results ───────────────────────────────────────────
│   ├── Yesterday's predictions vs outcomes
│   └── Rolling performance (7-day, 30-day, season)
│
├── Search ────────────────────────────────────────────
│   └── Find any player → Detail panel or Profile page
│
└── Player Profile (standalone page) ──────────────────
    └── For players not playing today
```

### Navigation

**Desktop:** Header with logo, search bar, Results link

**Mobile:** Bottom navigation bar
| Icon | Label | Destination |
|------|-------|-------------|
| 🏀 | Tonight | Two-tab view |
| 📊 | Results | Results page |
| 🔍 | Search | Search overlay |

**Mobile Tab Behavior:**
- Tapping "Tonight" in bottom nav opens the two-tab view
- **Tonight's Picks** and **All Players** tabs appear as pills at top of content area
- Users can switch tabs by tapping pills OR swiping horizontally
- Tab state persists when navigating away and back

---

## 3. Page & Component Specifications

### 3.1 Tonight's Picks Tab

#### Best Bets Section
Top 5-10 picks ranked by composite score, displayed as horizontal scrollable cards.

**Ranking Formula (computed in backend):**
```
composite_score = confidence × edge_factor × historical_accuracy

where:
  edge_factor = min(1.5, 1.0 + edge/10.0)
  historical_accuracy = player's win rate on past predictions (default 0.85 if new)
```

```
🏆 BEST BETS
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Jokic    │ │ Tatum    │ │ Booker   │ │ Edwards  │ │ Morant   │
│ UNDER    │ │ OVER     │ │ UNDER    │ │ OVER     │ │ UNDER    │
│ 82%      │ │ 78%      │ │ 76%      │ │ 74%      │ │ 72%      │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
```

**Data source:** `/v1/best-bets/today.json` (already exists)

#### Player Card (Picks Tab)

```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • 7:30 PM               │
│ Line: 25.5                         │
│ → UNDER 72%                        │
│ Last 10: ●●○●○○●○○● (4-6)         │
└────────────────────────────────────┘
```

**Card States:**
- Standard (healthy/probable)
- Injury (questionable) - yellow accent, ⚠️ badge
- Final - shows actual points + result (✅/❌)

#### Filters & Sort

**Filters:**
- Game: Dropdown of tonight's games
- Recommendation: All / OVER / UNDER / PASS
- Healthy only: Toggle

**Sort Options:**
- PPG (default) - Season scoring average
- Confidence - Our confidence score
- Edge - Predicted margin vs line
- Game Time - Chronological

---

### 3.2 All Players Tab

#### Default State
Requires game selection before showing players (prevents 100+ player dump).

```
Select a game to browse players

┌───────────────┐  ┌───────────────┐
│ LAL @ DEN     │  │ PHX @ GSW     │
│ 7:30 PM       │  │ 8:00 PM       │
└───────────────┘  └───────────────┘
```

#### After Game Selection
Shows all players from both teams, grouped by team. Includes OUT players (grayed out, at bottom).

**Card WITHOUT spread:**
```
┌────────────────────────────────────┐
│ Austin Reaves                      │
│ LAL @ DEN • 7:30 PM               │
│ Season: 17.2 pts • Last 5: 19.1   │
│ Minutes: 28.4 avg                  │
│ Last 10: 18 22 15 19 21 17 20...  │
│ No spread available                │
└────────────────────────────────────┘
```

**OUT Player Card:**
```
┌────────────────────────────────────┐
│ Anthony Davis                 OUT  │  ← Grayed out
│ LAL @ DEN • 7:30 PM               │
│ Season: 24.2 pts                   │
│ Ankle - Out for game               │
└────────────────────────────────────┘
```

---

### 3.3 Player Detail Panel

#### Behavior
- **Desktop:** Slides in from right (~40% viewport width), grid remains visible
- **Mobile:** Bottom sheet, swipe to expand/close

#### Two-Tab Structure

```
┌─────────────────────────────────────┐
│ [X]  LeBron James                   │
│ ┌──────────┬──────────┐            │
│ │ Tonight  │ Profile  │  ← tabs    │
│ └──────────┴──────────┘            │
│ [Tab content]                       │
└─────────────────────────────────────┘
```

---

### 3.4 Tonight Tab (Detail Panel)

**Purpose:** Focused decision-support for tonight's bet.

**Sections:**

1. **Tonight's Game**
   - Matchup, game time
   - Current line with movement from open
   - Days rest, injury status

2. **Quick Numbers**
   - Season / Last 10 / Last 5 averages with trend arrows
   - Minutes trend
   - Fatigue level with explanation
   - Current streak (if 3+ games)

3. **Tonight's Factors** (only splits relevant to THIS game)
   - B2B impact (if B2B)
   - Home/Away split
   - vs This Opponent history
   - vs Defense Tier (if top/bottom 10)

4. **Recent Form**
   - Last 10 games mini-grid (●/○)
   - Win rate vs line
   - Tappable for game details

5. **Our Take**
   - Prediction, confidence, recommendation
   - Key factors (frontend templates)
   - System agreement (4 of 5 agree on UNDER)

---

### 3.5 Profile Tab (Detail Panel)

**Purpose:** Complete historical view for deep research.

**Sections:**

1. **Season Overview**
   - PPG, RPG, APG, MPG, games played

2. **Game Log** (GitHub-style grid)
   - Last 50 games
   - Color-coded: ● green OVER, ○ red UNDER, - gray no line
   - Tappable for box score details

3. **All Situational Splits**
   - Rest buckets (B2B, 1-day, 2-day, 3+)
   - Home/Away
   - Defense tier (Top 10, Middle, Bottom 10)
   - Opponent history (teams with 3+ games)

4. **Our Track Record**
   - Total predictions, win rate
   - OVER/UNDER breakdown
   - Average error, bias tendency

---

### 3.6 Results Page

**Yesterday's Results:**
- Total predictions, record, win %
- Grid of outcomes

**Rolling Performance:**
```
         7-day    30-day   Season
Record   18-12    84-62    312-248
Win %    60%      58%      56%
```

**Data source:** `/v1/results/{date}.json` (already exists)

---

### 3.7 Player Profile Page (Standalone)

For players searched who aren't playing today. Identical to Profile tab content, displayed as full page.

**Key Point:** The same `/v1/players/{lookup}.json` endpoint serves both:
- The **Profile tab** in the detail panel (for players with games today)
- The **standalone Profile page** (for players without games today)

The `next_game` field in the response enables the banner:

**Banner if upcoming game:**
```
📅 Next Game: Thu Dec 14 vs PHX
[View prediction when available]
```

**Banner if no upcoming game:**
```
No upcoming games scheduled
```

---

## 4. Game State Transitions

### V1 Scope: Scheduled → Final (No Live)

For V1, we support two game states. Live scores are deferred to V1.5.

```
┌─────────────┐                              ┌─────────────┐
│  SCHEDULED  │ ────── Game Completes ─────→ │    FINAL    │
│             │       (1-6 hours later)      │             │
│ game_status │                              │ game_status │
│    = 1      │                              │    = 3      │
└─────────────┘                              └─────────────┘
```

### Data Sources for Game State

| State | Source | Timing |
|-------|--------|--------|
| Scheduled | `nba_raw.nbac_schedule.game_status = 1` | Available day of game |
| Final | `nba_raw.nbac_schedule.game_status = 3` | Updated after game ends |
| Final scores | `nba_analytics.player_game_summary.points` | 1-6 hours post-game |

### Card State Transitions

**Pre-game (Scheduled):**
```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • 7:30 PM               │
│ Line: 25.5                         │
│ → UNDER 72%                        │
│ Last 10: ●●○●○○●○○● (4-6)         │
└────────────────────────────────────┘
```

**Post-game (Final):**
```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • FINAL                  │
│ Line: 25.5                         │
│ Final: 28 pts ✅ OVER              │
│ Prediction: UNDER 72% ❌           │
└────────────────────────────────────┘
```

### When Final Data Becomes Available

| Component | Timing | Source |
|-----------|--------|--------|
| Game status = FINAL | ~30 min after game | Schedule scraper |
| Player actual points | 1-2 hours after game | Phase 2 boxscore |
| Processed results | 2-6 hours after game | Phase 3 analytics |
| Results JSON updated | Next morning ~3 AM | Phase 6 export |

### V1.5: Adding Live State

In V1.5, we'll add:
- Real-time game scraper (every 2-5 min during games)
- `game_status = 2` (in progress)
- Current points during game
- Live card state with quarter/time

---

## 5. Search Implementation

### Search Strategy

Search uses **client-side filtering** with no additional backend endpoints needed.

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER TYPES IN SEARCH                       │
│                                                                 │
│  "lebr..." → Filter loaded data                                │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│  PLAYER HAS GAME TODAY  │     │  PLAYER HAS NO GAME     │
│                         │     │                         │
│  Filter from:           │     │  Filter from:           │
│  /v1/tonight/           │     │  /v1/players/index.json │
│  all-players.json       │     │  (519 players)          │
│                         │     │                         │
│  → Open detail panel    │     │  → Open Profile page    │
└─────────────────────────┘     └─────────────────────────┘
```

### Data Sources for Search

| Scenario | Endpoint | Already Exists? |
|----------|----------|-----------------|
| Players with games today | `/v1/tonight/all-players.json` | NEW (to build) |
| All other players | `/v1/players/index.json` | ✅ Yes (519 players) |
| Full player profile | `/v1/players/{lookup}.json` | ✅ Yes (enhance) |

### Player Index Contents

The existing `/v1/players/index.json` contains:
```json
{
  "generated_at": "2024-12-11T05:59:55Z",
  "total_players": 519,
  "players": [
    {
      "player_lookup": "lebronjames",
      "player_full_name": "LeBron James",
      "team": "LAL",
      "games_predicted": 47,
      "recommendations": 38,
      "mae": 3.2,
      "win_rate": 0.62,
      "bias": -0.45,
      "within_5_pct": 0.72
    }
  ]
}
```

> **Note:** `player_full_name` is required for search display. Must be added to the existing PlayerProfileExporter.

### Search Flow

1. **User types** in search bar
2. **Frontend filters** against loaded data:
   - First check `tonight/all-players.json` (already loaded)
   - If not found, check `players/index.json` (load once, cache)
3. **Show autocomplete** results with player name + team
4. **On selection:**
   - If player has game today → Open detail panel
   - If player has no game today → Navigate to Profile page

### Search UX Details

- **Minimum characters:** 2 before showing results
- **Debounce:** 150ms to avoid excessive filtering
- **Results limit:** Show top 10 matches
- **Match fields:** `player_full_name`, `player_lookup`
- **Sort results:** Players with games today first, then alphabetical

---

## 6. Data Loading Architecture

### Loading Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                        INITIAL PAGE LOAD                        │
│                                                                 │
│  Parallel fetch:                                                │
│  • /v1/tonight/all-players.json  (~150 KB)                     │
│  • /v1/best-bets/today.json  (~5 KB)                           │
│                                                                 │
│  Total: ~155 KB                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     USER CLICKS A PLAYER                        │
│                                                                 │
│  Fetch: /v1/tonight/player/{lookup}.json  (~3-5 KB)            │
│  Renders: "Tonight" tab in detail panel                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   USER CLICKS "PROFILE" TAB                     │
│                                                                 │
│  Fetch: /v1/players/{lookup}.json  (~30-50 KB)                 │
│  Renders: "Profile" tab (lazy loaded)                          │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Structure

| Principle | Benefit |
|-----------|---------|
| Load all players upfront | Instant search/filter, no waiting |
| Lazy load player details | Don't fetch 50-game logs for 150 players |
| Tab-based loading | Most users won't click Profile |
| Cacheable endpoints | Appropriate TTL per endpoint |

---

## 7. API Endpoints

### 7.1 Endpoints Overview

| Endpoint | Purpose | Size | Status |
|----------|---------|------|--------|
| `/v1/tonight/all-players.json` | Grid data for all players tonight | ~150 KB | **NEW** |
| `/v1/tonight/player/{lookup}.json` | Tonight tab detail data | ~3-5 KB | **NEW** |
| `/v1/best-bets/today.json` | Top ranked picks | ~5 KB | ✅ Exists |
| `/v1/players/index.json` | Player directory (all 519 players) | ~50 KB | ✅ Exists |
| `/v1/players/{lookup}.json` | Full season profile | ~30-50 KB | Enhance |
| `/v1/results/{date}.json` | Daily results | ~20 KB | ✅ Exists |
| `/v1/systems/performance.json` | System accuracy | ~5 KB | ✅ Exists |

---

### 7.2 NEW: `/v1/tonight/all-players.json`

**Purpose:** Initial page load - all players in tonight's games with card-level data.

```json
{
  "game_date": "2024-12-11",
  "generated_at": "2024-12-11T07:00:00Z",
  "total_players": 156,
  "total_with_lines": 98,
  "games": [
    {
      "game_id": "20241211_LAL_DEN",
      "home_team": "DEN",
      "away_team": "LAL",
      "game_time": "19:30",
      "game_status": "scheduled",
      "players": [
        {
          "player_lookup": "lebronjames",
          "player_full_name": "LeBron James",
          "team_abbr": "LAL",
          "has_line": true,
          "current_points_line": 25.5,
          "opening_line": 24.0,
          "predicted_points": 22.4,
          "confidence_score": 74,
          "recommendation": "UNDER",
          "fatigue_level": "tired",
          "fatigue_score": 72,
          "injury_status": "available",
          "injury_reason": null,
          "season_ppg": 24.8,
          "last_5_ppg": 20.4,
          "last_10_results": ["O","O","U","O","U","U","O","U","U","O"],
          "last_10_record": "4-6"
        },
        {
          "player_lookup": "austinreaves",
          "player_full_name": "Austin Reaves",
          "team_abbr": "LAL",
          "has_line": false,
          "current_points_line": null,
          "predicted_points": 16.8,
          "confidence_score": null,
          "recommendation": null,
          "fatigue_level": "normal",
          "fatigue_score": 88,
          "injury_status": "available",
          "injury_reason": null,
          "season_ppg": 17.2,
          "last_5_ppg": 19.1,
          "season_mpg": 28.4,
          "last_10_points": [18, 22, 15, 19, 21, 17, 20, 14, 19, 16]
        },
        {
          "player_lookup": "anthonydavis",
          "player_full_name": "Anthony Davis",
          "team_abbr": "LAL",
          "has_line": false,
          "injury_status": "out",
          "injury_reason": "Ankle",
          "season_ppg": 24.2
        }
      ]
    }
  ]
}
```

**Cache:** 5 minutes

---

### 7.3 NEW: `/v1/tonight/player/{lookup}.json`

**Purpose:** Tonight tab detail - game-specific context and relevant splits.

```json
{
  "player_lookup": "lebronjames",
  "player_full_name": "LeBron James",
  "game_date": "2024-12-11",

  "game_context": {
    "game_id": "20241211_LAL_DEN",
    "opponent": "DEN",
    "opponent_full": "Denver Nuggets",
    "game_time": "19:30",
    "home_game": false,
    "current_line": 25.5,
    "opening_line": 24.0,
    "line_movement": 1.5,
    "days_rest": 0,
    "injury_status": "available",
    "injury_reason": null
  },

  "quick_numbers": {
    "season_avg": 24.8,
    "last_10_avg": 22.1,
    "last_5_avg": 20.4,
    "minutes_season": 34.2,
    "minutes_last_5": 32.1,
    "minutes_trend": "down"
  },

  "fatigue": {
    "score": 72,
    "level": "tired",
    "factors": ["back_to_back", "3rd_game_in_4_days"],
    "context": {
      "days_rest": 0,
      "back_to_back": true,
      "games_last_7": 4,
      "minutes_last_7": 142
    }
  },

  "current_streak": {
    "direction": "UNDER",
    "length": 3
  },

  "tonights_factors": [
    {
      "factor": "back_to_back",
      "label": "Back-to-Back",
      "applies": true,
      "player_avg": 19.8,
      "baseline_avg": 24.8,
      "games": 12,
      "impact": -5.0
    },
    {
      "factor": "away_game",
      "label": "Away Game",
      "applies": true,
      "player_avg": 22.1,
      "baseline_avg": 27.5,
      "games": 35,
      "impact": -5.4
    },
    {
      "factor": "vs_opponent",
      "label": "vs Nuggets",
      "applies": true,
      "opponent": "DEN",
      "player_avg": 19.8,
      "games": 5
    },
    {
      "factor": "vs_defense_tier",
      "label": "vs #3 Defense",
      "applies": true,
      "tier": "top_10",
      "tier_rank": 3,
      "player_avg": 20.1,
      "games": 18
    }
  ],

  "recent_form": {
    "last_10_results": ["O","O","U","O","U","U","O","U","U","O"],
    "last_10_record": {"wins": 4, "losses": 6, "pct": 40},
    "games": [
      {
        "date": "2024-12-08",
        "opponent": "PHX",
        "home": true,
        "points": 28,
        "minutes": 35,
        "line": 25.5,
        "result": "OVER",
        "margin": 2.5
      }
    ]
  },

  "prediction": {
    "predicted_points": 22.4,
    "confidence_score": 74,
    "recommendation": "UNDER",
    "edge": -3.1,
    "key_factors": ["back_to_back", "elite_defense", "minutes_trending_down"],
    "system_agreement": {
      "agree": 4,
      "total": 5,
      "direction": "UNDER",
      "systems": {
        "ensemble_v1": "UNDER",
        "xgboost_v1": "UNDER",
        "similarity_balanced_v1": "UNDER",
        "zone_matchup_v1": "UNDER",
        "moving_average_v1": "PASS"
      }
    }
  }
}
```

**Cache:** 5 minutes

---

### 7.4 ENHANCED: `/v1/players/{lookup}.json`

**Changes from current:**
- Expand game log from 20 → 50 games
- Add defense tier splits
- Add full box score fields
- Add current streak

```json
{
  "player_lookup": "lebronjames",
  "player_full_name": "LeBron James",
  "team_abbr": "LAL",
  "generated_at": "2024-12-11T07:00:00Z",

  "season_overview": {
    "season": "2024-25",
    "ppg": 24.8,
    "rpg": 7.2,
    "apg": 8.1,
    "mpg": 34.2,
    "games_played": 52,
    "fg_pct": 52.1,
    "three_pct": 38.2,
    "ft_pct": 75.4
  },

  "game_log": [
    {
      "game_date": "2024-12-08",
      "opponent": "PHX",
      "home_game": true,
      "team_result": "W",
      "points": 28,
      "minutes": 35,
      "fg_made": 10,
      "fg_attempted": 18,
      "three_made": 2,
      "three_attempted": 5,
      "ft_made": 6,
      "ft_attempted": 7,
      "rebounds": 8,
      "assists": 9,
      "steals": 2,
      "blocks": 1,
      "turnovers": 3,
      "line": 25.5,
      "over_under": "OVER",
      "margin": 2.5
    }
  ],

  "splits": {
    "rest": {
      "b2b": {"avg": 19.8, "games": 12, "vs_line_pct": 33},
      "one_day": {"avg": 21.2, "games": 28, "vs_line_pct": 46},
      "two_day": {"avg": 24.1, "games": 22, "vs_line_pct": 55},
      "three_plus": {"avg": 26.8, "games": 18, "vs_line_pct": 67}
    },
    "location": {
      "home": {"avg": 27.5, "games": 40, "vs_line_pct": 60},
      "away": {"avg": 22.1, "games": 35, "vs_line_pct": 43}
    },
    "defense_tier": {
      "top_10": {"avg": 21.2, "games": 18, "vs_line_pct": 39},
      "middle": {"avg": 24.5, "games": 22, "vs_line_pct": 55},
      "bottom_10": {"avg": 28.1, "games": 12, "vs_line_pct": 67}
    },
    "opponents": [
      {"team": "DEN", "avg": 19.8, "games": 5},
      {"team": "PHX", "avg": 26.2, "games": 4},
      {"team": "GSW", "avg": 24.1, "games": 6}
    ]
  },

  "our_track_record": {
    "total_predictions": 47,
    "overall": {"wins": 29, "losses": 18, "pct": 62},
    "over_calls": {"wins": 14, "losses": 10, "pct": 58},
    "under_calls": {"wins": 15, "losses": 8, "pct": 65},
    "avg_error": 3.2,
    "bias": "under_predicts",
    "within_3_pts": 68,
    "within_5_pts": 82
  },

  "next_game": {
    "game_date": "2024-12-11",
    "opponent": "DEN",
    "home_game": false,
    "has_prediction": true
  }
}
```

**Cache:** 1 hour

---

## 8. Data Availability & Gaps

### 8.1 Fully Supported (No Work Needed)

| Feature | Source Table | Status |
|---------|--------------|--------|
| Player cards with lines | `player_prop_predictions` | ✅ Ready |
| Injury status + reason | `nbac_injury_report` | ✅ Ready |
| Days rest / B2B flag | `upcoming_player_game_context` | ✅ Ready |
| Home/Away | `upcoming_player_game_context.home_game` | ✅ Ready |
| Last 10 results | `player_game_summary` | ✅ Ready |
| Season/Last 5/10 averages | `player_game_summary` | ✅ Ready |
| Line movement | `odds_api_player_points_props` | ✅ Ready |
| System agreement | `player_prop_predictions.system_agreement_score` | ✅ Ready |
| Defensive ratings | `team_defense_game_summary` | ✅ Ready |
| Track record per player | `prediction_accuracy` | ✅ Ready |
| Best bets ranking | Phase 6 JSON | ✅ Ready |
| Results/accuracy | Phase 6 JSON | ✅ Ready |

### 8.2 Exists But Not Exposed

| Feature | Source | Status | Action |
|---------|--------|--------|--------|
| Fatigue score (0-100) | `player_composite_factors.fatigue_score` | Exists | Add to Phase 6 |
| Fatigue context JSON | `player_composite_factors.fatigue_context_json` | Exists | Add to Phase 6 |
| Defense tier splits | Can compute from `team_defense_game_summary` | Can compute | Add to player profile |
| Current streak | Can compute from `player_game_summary` | Can compute | Add to tonight endpoint |

### 8.3 Needs Computation

| Feature | How to Compute | Effort |
|---------|----------------|--------|
| Fatigue level (Fresh/Normal/Tired) | Map score 0-100 to 3 levels | 30 min |
| Tonight's relevant factors | Filter splits based on game context | 1-2 hrs |
| Defense tier ranking | Daily ranking of teams by def_rating | 1 hr |
| vs Line percentage per split | Join game_summary with results | 1 hr |

### 8.4 Not Available (Out of Scope)

| Feature | Status | Notes |
|---------|--------|-------|
| Live game scores | Not tracked | V1.5 - needs new scraper |
| Pre-game lineup confirmations | Post-game only | Would need rotowire/fantasylabs |
| Real-time line updates | Periodic scraping | Current is sufficient for V1 |

---

## 9. Implementation Plan

### 9.1 Phase 6 Backend Work

| Task | Effort | Priority |
|------|--------|----------|
| Create `/v1/tonight/all-players.json` exporter | 3-4 hrs | High |
| Create `/v1/tonight/player/{lookup}.json` exporter | 2-3 hrs | High |
| Add fatigue_level to predictions output | 1 hr | High |
| Enhance `/v1/players/{lookup}.json` (50 games, splits) | 2 hrs | High |
| Add `player_full_name` to index.json | 15 min | High |
| Add defense tier splits computation | 1 hr | Medium |
| Add current streak computation | 30 min | Medium |
| Add `limited_data` and `points_available` flags | 30 min | Medium |

**Total backend:** ~11-13 hours

### 9.2 Exporter Implementation Order

1. **all-players.json** - Enables initial page render
2. **Enhance player profiles** - Enables Profile tab
3. **tonight/player/{lookup}.json** - Enables Tonight tab
4. **Add fatigue to existing** - Polish

### 9.3 Frontend Data Requirements

| Component | Endpoint(s) Needed |
|-----------|-------------------|
| Player Grid | `/v1/tonight/all-players.json` |
| Best Bets Section | `/v1/best-bets/today.json` |
| Tonight Tab | `/v1/tonight/player/{lookup}.json` |
| Profile Tab | `/v1/players/{lookup}.json` |
| Results Page | `/v1/results/{date}.json` |
| System Performance | `/v1/systems/performance.json` |

---

## 10. Technical Decisions

### 10.1 Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| All players upfront vs game selection | **Load all upfront** | ~150 KB is trivial, enables instant search |
| Fatigue calculation location | **Backend** | Already computed in Phase 4, just expose it |
| Tonight's Factors filtering | **Frontend** | Send all splits, frontend filters by context |
| Explanation text | **Frontend templates** | Easier to maintain, tweak copy without deploy |
| Game log depth | **50 games** | ~2 months, good for trends, reasonable size |
| Live scores | **Defer to V1.5** | Final scores only for V1 |

### 10.2 Fatigue Level Mapping

```javascript
// Backend adds fatigue_level based on fatigue_score
if (fatigue_score >= 95) return "fresh";    // 🟢
if (fatigue_score >= 75) return "normal";   // 🟡
return "tired";                              // 🔴
```

### 10.3 Frontend Explanation Templates

```javascript
const templates = {
  back_to_back: (impact) =>
    `B2B games typically cost him ~${Math.abs(impact).toFixed(0)} points.`,

  elite_defense: (rank, team) =>
    `${team}'s elite defense (ranked #${rank}) limits scorers.`,

  minutes_trending_down: () =>
    `Minutes trending down suggests reduced workload.`,

  hot_streak: (length) =>
    `On a ${length}-game scoring streak.`,

  cold_vs_team: (team, avg) =>
    `Averages only ${avg.toFixed(1)} points against ${team}.`
};
```

### 10.4 Caching Strategy

| Endpoint | Cache TTL | Reason |
|----------|-----------|--------|
| `/v1/tonight/all-players.json` | 5 min | Lines can change |
| `/v1/tonight/player/{lookup}.json` | 5 min | Context-specific |
| `/v1/best-bets/today.json` | 5 min | Rankings can shift |
| `/v1/players/{lookup}.json` | 1 hour | Historical data stable |
| `/v1/results/{date}.json` | 24 hours | Historical, immutable |
| `/v1/systems/performance.json` | 1 hour | Aggregated metrics |

### 10.5 Storage Architecture

```
GCS: gs://nba-props-platform-api/v1/
├── tonight/
│   ├── all-players.json          (NEW)
│   └── player/
│       ├── lebronjames.json      (NEW)
│       └── {lookup}.json         (NEW)
├── best-bets/
│   ├── 2024-12-11.json
│   └── latest.json
├── predictions/
│   └── today.json
├── results/
│   ├── 2024-12-10.json
│   └── latest.json
├── systems/
│   └── performance.json
└── players/
    ├── index.json
    └── {lookup}.json             (ENHANCED)
```

### 10.6 Data Conventions

#### Timezone
All game times are in **Eastern Time (ET)**. The `game_time` field uses 24-hour format without timezone suffix (e.g., `"19:30"` = 7:30 PM ET).

Frontend should display times appropriately for user's locale if needed.

#### game_status Values
Use **string values** for readability:

| Value | Meaning | NBA API Code |
|-------|---------|--------------|
| `"scheduled"` | Game not started | 1 |
| `"in_progress"` | Game in progress (V1.5) | 2 |
| `"final"` | Game completed | 3 |

#### player_lookup Format
Lowercase, no spaces, no special characters:
- "LeBron James" → `"lebronjames"`
- "Nikola Jokić" → `"nikolajokic"`

### 10.7 Edge Case Handling

#### Final Game, Points Not Yet Available
Between game end (~30 min) and boxscore processing (1-2 hrs), a game may show `game_status: "final"` but player points are not yet available.

**Backend:** Include `"points_available": false` when final points aren't ready.
**Frontend:** Show "FINAL - Updating..." or spinner instead of points.

#### Low-Data Players
Players with limited history (rookies, recent callups, traded players):

**Backend:** Include `"limited_data": true` when `games_played < 10` this season.
**Frontend:** Show "Limited history" badge, de-emphasize confidence score.

#### DNP (Did Not Play)
Players who are healthy but don't play (coach's decision) won't appear on injury report. Their lines are typically pulled before tipoff.

**Handling:** No special treatment needed - they'll either have a line or not.

---

## Appendix A: UI Component Specifications

### A.1 Fatigue Indicator

| Level | Icon | Color | Score Range |
|-------|------|-------|-------------|
| Fresh | 🟢 | Green | 95-100 |
| Normal | 🟡 | Yellow | 75-94 |
| Tired | 🔴 | Red | 0-74 |

### A.2 Last 10 Mini Grid (Colorblind Accessible)

| Result | Color | Icon | Meaning |
|--------|-------|------|---------|
| OVER | Green | ● (filled) | Beat the line |
| UNDER | Red | ○ (empty) | Missed the line |
| No line | Gray | - (dash) | No betting line |

### A.3 Injury Status Treatment

| Status | Card Style | Badge |
|--------|------------|-------|
| Available | Normal | None |
| Probable | Normal | Small badge (optional) |
| Questionable | Yellow accent | ⚠️ + reason |
| Doubtful | Orange accent | ⚠️ + reason |
| Out | Grayed out | OUT badge |

---

## Appendix B: Data Source Reference

| UI Element | BigQuery Table | Key Fields |
|------------|----------------|------------|
| Player info | `nba_reference.nba_players_registry` | `player_lookup`, `player_full_name` |
| Game schedule | `nba_raw.nbac_schedule` | `game_date`, `game_time`, teams |
| Prop lines | `nba_raw.odds_api_player_points_props` | `points_line`, `opening_line` |
| Predictions | `nba_predictions.player_prop_predictions` | `predicted_points`, `confidence_score` |
| Game stats | `nba_analytics.player_game_summary` | `points`, `minutes_played`, `over_under_result` |
| Injuries | `nba_raw.nbac_injury_report` | `injury_status`, `reason` |
| Rest/fatigue | `nba_analytics.upcoming_player_game_context` | `days_rest`, `back_to_back` |
| Fatigue score | `nba_precompute.player_composite_factors` | `fatigue_score`, `fatigue_context_json` |
| Defense ratings | `nba_analytics.team_defense_game_summary` | `defensive_rating` |
| Track record | `nba_predictions.prediction_accuracy` | `prediction_correct`, `prediction_error` |

---

## Appendix C: Related Documents

| Document | Location | Purpose |
|----------|----------|---------|
| UI Spec v2 (original) | `website-ui/UI-SPEC-V2.md` | Detailed UI specification |
| Data Investigation | `website-ui/DATA-INVESTIGATION-RESULTS.md` | Data availability analysis |
| Phase 6 Design | `phase-6-publishing/DESIGN.md` | Current Phase 6 architecture |
| Phase 6 Operations | `phase-6-publishing/OPERATIONS.md` | Current Phase 6 operations |

---

*End of Master Specification*
