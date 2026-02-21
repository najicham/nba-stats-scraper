# Frontend Implementation Spec — playerprops.io Best Bets

**Status:** Final spec. Decisions locked. Build from this.

## Overview

Best Bets is the primary product page — it answers "What should I bet on tonight?" in 3-5 picks. It becomes the first nav item (or the landing page).

**Nav order:** `Best Bets` | Tonight | Picks | Results

**Data:** One static JSON file with everything. One fetch, done.

**Base URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/`

---

## Data Source: `best-bets/all.json`

Single file. ~50-200 KB for a full season. 5-minute cache. No auth.

```jsonc
{
  "date": "2026-02-21",
  "generated_at": "2026-02-21T16:00:00+00:00",
  "algorithm_version": "v319_consolidated",

  // ── HERO: Season Record ──────────────────────────────────────
  "record": {
    "season":  { "wins": 92, "losses": 32, "pct": 74.2, "total": 124 },
    "month":   { "wins": 18, "losses": 15, "pct": 54.5, "total": 33 },
    "week":    { "wins": 3,  "losses": 1,  "pct": 75.0, "total": 4 },
    "last_10": { "wins": 7,  "losses": 3,  "pct": 70.0 }
  },
  "streak": { "type": "W", "count": 2 },
  "best_streak": {
    "type": "W", "count": 8,
    "start": "2026-01-15", "end": "2026-01-22"
  },

  // ── MAIN: Today's Picks ──────────────────────────────────────
  // Duplicated from weeks array for convenience. These ARE the hero picks.
  "today": [
    {
      "rank": 1,
      "player": "LeBron James",
      "player_lookup": "lebron_james",
      "team": "LAL",
      "opponent": "DEN",
      "direction": "OVER",
      "line": 27.5,
      "edge": 5.2,
      "angles": [
        "High-conviction edge (5.2 pts above line)",
        "Season OVER heavy (77% HR)"
      ],
      "actual": null,       // null until game ends
      "result": null        // null → "WIN" or "LOSS" after grading
    },
    {
      "rank": 2,
      "player": "Jayson Tatum",
      "player_lookup": "jayson_tatum",
      "team": "BOS",
      "opponent": "MIA",
      "direction": "OVER",
      "line": 30.5,
      "edge": 6.1,
      "angles": [
        "Top-tier player, strong home bounce-back"
      ],
      "actual": null,
      "result": null
    }
  ],
  "total_today": 2,

  // ── HISTORY: Weekly Accordion ────────────────────────────────
  // Most recent week first. Today's picks appear here too (as pending).
  "weeks": [
    {
      "week_start": "2026-02-17",
      "record": {
        "wins": 3, "losses": 1, "pending": 2,
        "pct": 75.0       // null if no graded picks yet
      },
      "days": [
        {
          "date": "2026-02-21",
          "status": "pending",     // "pending" | "sweep" | "split" | "miss"
          "record": { "wins": 0, "losses": 0, "pending": 2 },
          "picks": [
            {
              "player": "LeBron James",
              "player_lookup": "lebron_james",
              "team": "LAL",
              "opponent": "DEN",
              "direction": "OVER",
              "line": 27.5,
              "edge": 5.2,
              "actual": null,
              "result": null,
              "angles": ["High-conviction edge (5.2 pts above line)"]
            }
          ]
        },
        {
          "date": "2026-02-20",
          "status": "sweep",
          "record": { "wins": 2, "losses": 0, "pending": 0 },
          "picks": [
            {
              "player": "Jayson Tatum",
              "player_lookup": "jayson_tatum",
              "team": "BOS",
              "opponent": "MIA",
              "direction": "OVER",
              "line": 30.5,
              "edge": 6.1,
              "actual": 33,
              "result": "WIN",
              "angles": ["Top-tier player, strong home bounce-back"]
            }
          ]
        }
      ]
    }
  ],

  "total_picks": 124,   // Season total
  "graded": 120          // How many have results
}
```

---

## Page Layout

### Hero — Season Record

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  74.2%        92-32 Season        W2
  hit rate                       streak
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

- Big numbers. One line. Establishes credibility instantly.
- Monthly/weekly records in smaller text below if desired — don't clutter the hero.
- Source: `record.season`, `streak`

### Main — Today's Picks

**NOT PlayerCards.** Each pick is a full-width row or large card:

```
┌─────────────────────────────────────────────────┐
│  1   LeBron James                OVER 27.5 pts  │
│      LAL @ DEN                   Edge: 5.2      │
│                                                  │
│      • High-conviction edge (5.2 pts above line) │
│      • Season OVER heavy (77% HR)                │
└─────────────────────────────────────────────────┘
```

Each card shows:
- **Rank** (1, 2, 3) — order = conviction
- **Player + team @ opponent** — large, prominent
- **Direction pill** — `OVER 27.5` or `UNDER 24.5` in bold colored chip (green/red)
- **Edge** — the confidence number. Higher = better.
- **Angles** — 1-3 lines below in secondary text. Display verbatim.
- **Result** (after grading) — WIN/LOSS badge + actual score. Row tints green/red.

**Empty state:** "No picks today — we only bet when the edge is there." with the season record visible above. Discipline, not downtime.

Source: `today` array (0-8 items)

### History — Weekly Accordion

No calendar. Weekly collapsible groups, most recent first.

```
▼ Week of Feb 17 — 3-1 (75.0%)
    Feb 21 ● ●                                    [pending]
    Feb 20 ✓ ✓                                    [2-0 sweep]
    Feb 19 ✓ ✗                                    [1-1 split]

▶ Week of Feb 10 — 5-1 (83.3%)                   [collapsed]
▶ Week of Feb 3 — 4-2 (66.7%)                    [collapsed]
```

- Most recent week expanded by default
- Each day's picks shown inline with results
- **Day status field** for color coding: `"pending"` | `"sweep"` (all W) | `"split"` (mixed) | `"miss"` (all L)
- Optional: mini heatmap (last 20 days as tiny colored dots) at the top of history section

Source: `weeks` array

### Tap a Graded Pick → Player Modal

Use `player_lookup` to link into the existing Tonight page player view. Don't rebuild the drill-down, just connect to it.

---

## Field Reference

| Field | Type | Values | Notes |
|-------|------|--------|-------|
| `direction` | string | `"OVER"` or `"UNDER"` | Never null for best bets |
| `edge` | float | 5.0+ | Points above/below line. Higher = stronger. All picks >= 5.0 |
| `result` | string/null | `"WIN"`, `"LOSS"`, `null` | null = game hasn't happened |
| `actual` | int/null | 0-70+ | Actual points scored. null = pending |
| `angles` | string[] | 1-3 items | Human-readable pick reasoning. Display verbatim |
| `player_lookup` | string | e.g. `"lebron_james"` | URL-safe ID for linking to player pages |
| `rank` | int | 1-8 | Conviction order (1 = strongest) |
| `status` (day) | string | `"pending"`, `"sweep"`, `"split"`, `"miss"` | Day-level result for color coding |
| `pct` | float/null | 0-100 | Win percentage. null if 0 graded picks |

**Do NOT display:** `signals` (internal jargon — `angles` is the user-facing version)

## Update Schedule

| Event | Time | What Changes |
|-------|------|--------------|
| Daily export | ~6 AM ET | Fresh `all.json` with today's picks |
| Injury re-check | ~6:40 PM ET | May deactivate a pick (rare) |
| Post-grading | Next morning | `result`/`actual` populated for yesterday's picks |

5-minute cache headers. Poll on page load, not continuously.

## Future Enhancements (Not Blocking v1)

- **"Picks are in" freshness indicator** — compare `generated_at` to current time. If today and recent, show "Fresh picks" badge.
- **Shareable pick cards** — screenshot-ready or Open Graph formatted single-pick view for social sharing.
- **Push notifications** — "Today's picks are in" at 6 AM ET. Backend can provide a webhook or the frontend can poll `generated_at`.
