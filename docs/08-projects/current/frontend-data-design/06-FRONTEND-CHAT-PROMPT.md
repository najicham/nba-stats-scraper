# Frontend Chat Prompt — playerprops.io

**Date:** 2026-02-22 (Session 329)
**Purpose:** Hand this to a Claude Code session working on the playerprops.io frontend codebase.

---

## Prompt

You are building the frontend for **playerprops.io** — an NBA player props prediction site that answers "What should I bet on tonight?" with 3-5 high-conviction picks per game day.

### System Overview

The backend is a fully operational ML prediction pipeline running on GCP. It produces static JSON files in a GCS bucket. The frontend is a static site that fetches these JSON files — no backend API calls, no auth for public pages, no WebSocket connections. One fetch, done.

**Base URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/`

### Current Performance (Live, as of Feb 22, 2026)

| Metric | Value |
|--------|-------|
| **Season Record** | **68-32 (68.0% HR)** |
| **February** | 19-14 (57.6%) |
| **Last 10** | 6-4 (60.0%) |
| **Current Streak** | W1 |
| **Best Streak** | W9 (Jan 18-20) |
| **Total Picks** | 106 (100 graded, 6 ungraded) |
| **Avg Edge** | 7.1 pts |
| **Ultra Bets** | 25-8 (75.8% HR) — 33 total |
| **Ultra OVER** | 17-2 (89.5% HR) |

The system only bets when the edge is >= 5.0 points. This means some days have 0 picks — that's intentional discipline, not downtime. Today (Feb 22) had 0 picks because the max edge across all models was 4.9 (thin post-All-Star slate).

### Data Files

#### 1. `v1/best-bets/all.json` — **Primary data source for the public site**

Single file containing season record, today's picks, and full weekly history. ~50-200 KB. 5-minute cache.

```jsonc
{
  "date": "2026-02-23",
  "season": "2025-26",
  "generated_at": "2026-02-23T00:09:00.999150+00:00",
  "algorithm_version": "v326_ultra_bets",

  // Hero section
  "record": {
    "season":  { "wins": 68, "losses": 32, "total": 100, "pct": 68.0 },
    "month":   { "wins": 19, "losses": 14, "total": 33, "pct": 57.6 },
    "week":    { "wins": 0, "losses": 0, "total": 0, "pct": 0.0 },
    "last_10": { "wins": 6, "losses": 4, "pct": 60.0 }
  },
  "streak": { "type": "W", "count": 1 },
  "best_streak": { "type": "W", "count": 9, "start": "2026-01-18", "end": "2026-01-20" },

  // Today's picks (empty array on days with no qualifying picks)
  "today": [
    {
      "player": "Desmond Bane",
      "player_lookup": "desmondbane",
      "team": "ORL",
      "opponent": "PHX",
      "direction": "OVER",
      "stat": "PTS",           // always PTS for now
      "line": 18.5,
      "edge": 7.7,
      "actual": 34,            // null until game ends
      "result": "WIN",         // null | "WIN" | "LOSS"
      "angles": [              // human-readable pick reasoning, display verbatim
        "ULTRA BET: V12+vegas model, edge >= 6 — 100.0% HR (26 picks)",
        "High conviction: edge 7.7 pts (65.6% HR at edge 5+)",
        "OVER on starter (18-25) line: 53.2% HR historically"
      ]
    }
  ],
  "total_today": 0,

  // Full history grouped by week, most recent first
  "weeks": [
    {
      "week_start": "2026-02-16",
      "record": { "wins": 3, "losses": 3, "pending": 0, "pct": 50.0 },
      "days": [
        {
          "date": "2026-02-21",
          "status": "sweep",    // "pending" | "sweep" | "split" | "miss"
          "record": { "wins": 1, "losses": 0, "pending": 0 },
          "picks": [/* same shape as today items */]
        }
      ]
    }
    // ... more weeks back to Jan 9
  ],
  "total_picks": 106,
  "graded": 100
}
```

#### 2. `v1/status.json` — System health (optional, for status indicators)

```jsonc
{
  "updated_at": "2026-02-23T00:15:18+00:00",
  "overall_status": "healthy",  // "healthy" | "degraded" | "down"
  "services": {
    "best_bets": {
      "status": "healthy",
      "message": "0 picks today — all candidates filtered out",
      "total_picks": 0
    }
  }
}
```

#### 3. `v1/admin/dashboard.json` — Admin-only (hidden `/admin` route)

Full model health, signal health, pick funnels, subset performance. ~20-50 KB. See admin dashboard spec for full schema.

### Page Architecture

**Nav:** `Best Bets` | History | About

#### Best Bets Page (Landing Page)

**Hero — Season Record:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  68.0%      68-32 Season       W1
  hit rate                    streak
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
Big numbers. One line. Establishes credibility instantly. Monthly/weekly in smaller text below.

**Main — Today's Picks:**

Each pick is a full-width card:
```
┌──────────────────────────────────────────────────┐
│  1   Desmond Bane                 OVER 18.5 pts  │
│      ORL @ PHX                    Edge: 7.7      │
│                                                   │
│      • ULTRA BET: V12+vegas model, edge >= 6     │
│      • High conviction: edge 7.7 pts             │
│      • OVER on starter (18-25) line              │
│                                                   │
│      Result: 34 pts  ✓ WIN                       │
└──────────────────────────────────────────────────┘
```

- **Rank** (1, 2, 3) — order = conviction
- **Player + team @ opponent** — large, prominent
- **Direction pill** — `OVER 18.5` or `UNDER 24.5` in bold colored chip (green for OVER, red for UNDER)
- **Edge** — confidence number, higher = better, always >= 5.0
- **Angles** — 1-3 bullet points of human-readable reasoning. Display verbatim from JSON.
- **Result** (after grading) — WIN/LOSS badge + actual score. Card tints green/red.
- If first angle starts with "ULTRA BET:" — this is a high-confidence pick. Consider a special badge or glow.

**Empty state (0 picks):** "No picks today — we only bet when the edge is there." with the season record still visible above. This is discipline, not downtime.

**History — Weekly Accordion:**

```
▼ Week of Feb 17 — 3-3 (50.0%)
    Feb 21  ✓                                    [1-0 sweep]
    Feb 20  ✗                                    [0-1 miss]
    Feb 19  ✓✓✗                                  [2-1 split]

▶ Week of Feb 10 — 5-2 (71.4%)                  [collapsed]
▶ Week of Feb 3  — 4-2 (66.7%)                  [collapsed]
```

- Most recent week expanded by default
- Each day's picks inline with WIN/LOSS indicators
- Day `status` field for color coding: `"sweep"` (all green), `"split"` (mixed), `"miss"` (all red), `"pending"` (gray)
- Tap a day to expand and see full pick details

### Key Design Principles

1. **Credibility first.** The 68-32 season record is the hero. Every visitor should see it within 1 second.
2. **No jargon.** Users see "edge" (how many points our model is ahead), "angles" (plain English reasoning), and results. No "signals", "CatBoost", "model families", "composite scores".
3. **Discipline messaging.** 0-pick days happen (~1-2 per week). Frame it as selective, not broken. "We only bet when we have an edge" is the mantra.
4. **Mobile-first.** Most sports bettors check on their phone. Cards should be full-width, thumb-friendly.
5. **Static and fast.** One JSON fetch. No loading spinners. Cache aggressively.
6. **Green/red language.** OVER = green pill. UNDER = red pill. WIN = green tint. LOSS = red tint. Pending = neutral/gray.

### Admin Dashboard (`/admin` — hidden route)

**Auth:** Firebase Auth with Google sign-in. Single allowlisted email. Unauthenticated visitors redirect to public Best Bets page.

**Data:** `v1/admin/dashboard.json`

**Sections:**
1. **Status bar** — Champion model state, algorithm version, best_bets_model
2. **Today's picks** — Full metadata (signals, model source, composite score, warnings)
3. **Model health table** — All 14 models with state, 7d/14d/30d HR, days since training
4. **Signal health matrix** — 12 signals × 3 timeframes with regime colors
5. **Filter funnel** — How many candidates, what filtered them out, edge distribution
6. **Subset performance** — Dynamic subsets with rolling HR

### What NOT to Build

- No user accounts or login for public pages
- No real-time updates or WebSocket connections
- No bet placement or sportsbook integration
- No player detail pages (yet) — just the pick cards
- No push notifications (future enhancement)
- Don't display: `system_id`, `algorithm_version`, `player_lookup`, `signal_count`, `composite_score` on public pages

### Update Schedule

| Event | Time (ET) | What Changes |
|-------|-----------|--------------|
| Daily export | ~6 AM | Fresh `all.json` with today's picks (if any) |
| Post-grading | Next morning | `result`/`actual` populated for yesterday's picks |

The JSON updates once or twice per day. 5-minute cache headers are fine.

### Live Data Samples

The real `all.json` is live right now at:
`https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/all.json`

Fetch it to see the actual data shape and current season results. This is production data, not mocked.
