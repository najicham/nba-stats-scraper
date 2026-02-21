# Admin Dashboard Spec — playerprops.io/admin

**Status:** Spec ready for frontend implementation.

## Access Model

**Location:** `playerprops.io/admin` — same site, hidden route.

**Auth:** Firebase Auth with Google sign-in. Allowlist of 1 email (yours). If not authenticated, `/admin` redirects to the public Best Bets page. No "admin" link visible in the public nav.

**Why not a separate site:** One codebase, one deploy. You're the only admin. The data has no secrets (it's the same predictions + performance stats). The route just needs to be hidden, not locked down like a bank vault.

---

## Data Source: `admin/dashboard.json`

Single file. Updates daily. 5-minute cache. ~20-50 KB.

**URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/admin/dashboard.json`

```jsonc
{
  "date": "2026-02-21",
  "generated_at": "2026-02-21T16:00:00+00:00",
  "algorithm_version": "v319_consolidated",
  "best_bets_model": "catboost_v9",

  // ── MODEL HEALTH ─────────────────────────────────────────────
  // All active models with decay state and hit rates
  "model_health": [
    {
      "system_id": "catboost_v9",
      "state": "HEALTHY",              // HEALTHY | WATCH | DEGRADING | BLOCKED
      "hr_7d": 62.5,                   // 7-day rolling hit rate (edge 3+)
      "hr_14d": 59.1,                  // 14-day rolling
      "n_7d": 48,                      // picks graded in 7 days
      "n_14d": 93,
      "days_since_training": 3         // null if unknown
    },
    {
      "system_id": "catboost_v12_noveg_train...",
      "state": "WATCH",
      "hr_7d": 55.2,
      "hr_14d": 57.8,
      "n_7d": 45,
      "n_14d": 88,
      "days_since_training": 16
    }
  ],

  // ── SIGNAL HEALTH ────────────────────────────────────────────
  // Per-signal regime (HOT/NORMAL/COLD) with hit rates
  "signal_health": {
    "high_edge":       { "regime": "HOT",    "hr_7d": 75.0, "hr_season": 66.7, "n_7d": 12 },
    "bench_under":     { "regime": "NORMAL", "hr_7d": 60.0, "hr_season": 76.9, "n_7d": 5 },
    "combo_he_ms":     { "regime": "HOT",    "hr_7d": 100.0, "hr_season": 94.9, "n_7d": 3 },
    "3pt_bounce":      { "regime": "COLD",   "hr_7d": 40.0, "hr_season": 74.9, "n_7d": 5 },
    // ... 16 signals total
  },

  // ── SUBSET PERFORMANCE ───────────────────────────────────────
  // All subsets with rolling HR across 3 windows
  "subset_performance": [
    {
      "subset_id": "best_bets",
      "7d":  { "wins": 5, "total": 7,  "hr": 71.4 },
      "14d": { "wins": 12, "total": 18, "hr": 66.7 },
      "30d": { "wins": 28, "total": 40, "hr": 70.0 }
    },
    {
      "subset_id": "edge_5_plus",
      "7d":  { "wins": 8, "total": 12, "hr": 66.7 },
      "14d": { "wins": 15, "total": 22, "hr": 68.2 },
      "30d": { "wins": 35, "total": 50, "hr": 70.0 }
    }
    // ... all subsets
  ],

  // ── TODAY'S PICKS (full metadata) ────────────────────────────
  "picks": [
    {
      "rank": 1,
      "player": "LeBron James",
      "player_lookup": "lebron_james",
      "team": "LAL",
      "opponent": "DEN",
      "direction": "OVER",
      "line": 27.5,
      "edge": 5.2,
      "predicted": 32.7,
      "confidence": 0.912,
      "composite_score": 1.2345,
      "signals": ["high_edge", "combo_he_ms"],
      "signal_count": 2,
      "angles": ["High-conviction edge", "Season OVER heavy"],
      "warnings": [],
      "combo": "combo_he_ms",
      "combo_class": "SYNERGISTIC",
      "combo_hr": 94.9,
      "model_agreement": 3,
      "agreeing_models": ["catboost_v9", "catboost_v9_q43_..."],
      "consensus_bonus": 0.05,
      "source_model": "catboost_v9",
      "source_family": "v9_mae",
      "n_models_eligible": 3,
      "champion_edge": 5.2,
      "direction_conflict": false,
      "algorithm_version": "v319_consolidated",
      "actual": null,
      "result": null
    }
  ],
  "total_picks": 3,

  // ── CANDIDATE FUNNEL ─────────────────────────────────────────
  "candidates_summary": {
    "total": 87,
    "edge_distribution": {
      "total": 87,
      "edge_3_plus": 24,
      "edge_5_plus": 10,
      "edge_7_plus": 3,
      "max_edge": 8.2
    }
  },

  // ── FILTER SUMMARY ───────────────────────────────────────────
  // What the aggregator rejected and why
  "filter_summary": {
    "total_candidates": 87,
    "passed_filters": 5,
    "rejected": {
      "edge_floor": 42,           // edge < 5.0
      "signal_count": 15,         // < 2 qualifying signals
      "quality_floor": 8,         // feature quality < 85
      "bench_under": 5,           // UNDER + line < 12
      "under_edge_7plus": 3,      // UNDER + edge >= 7
      "familiar_matchup": 2,      // 6+ games vs opponent
      "line_jumped_under": 2,     // UNDER + line jumped 2+ pts
      "line_dropped_under": 1,    // UNDER + line dropped 2+ pts
      "blacklist": 0,             // player HR < 40% on 8+ picks
      "confidence": 0,
      "anti_pattern": 0
    }
  }
}
```

---

## Page Layout

The admin dashboard is a single scrollable page with 5 sections. Dense is fine here — this is a Bloomberg terminal, not Barron's.

### Section 1: Status Bar

One-line system status across the top.

```
Model: catboost_v9 HEALTHY (62.5% 7d) | Training: 3d ago | Picks: 3 today | Generated: 6:02 AM ET
```

- Green/yellow/red dot based on champion model state
- `days_since_training` with color: green (<7d), yellow (7-14d), red (>14d)
- Quick link to retrain if stale

Source: `best_bets_model`, `model_health[0]`, `total_picks`, `generated_at`

### Section 2: Today's Picks (Full Detail)

Table with all metadata. Each row is a pick. Columns:

| # | Player | Dir | Line | Edge | Pred | Signals | Combo | Models | Score | Result |
|---|--------|-----|------|------|------|---------|-------|--------|-------|--------|
| 1 | LeBron James (LAL@DEN) | OVER | 27.5 | 5.2 | 32.7 | high_edge, combo_he_ms | SYNERGISTIC (94.9%) | 3 agree | 1.23 | — |

- Show signal tags here (unlike end-user view)
- Color-code combo_class: green=SYNERGISTIC, gray=NEUTRAL
- Direction conflict flag (red if true)
- Expandable row → shows angles, agreeing model list, source model details

Source: `picks` array

### Section 3: Filter Funnel

Visual breakdown of how 87 candidates became 3 picks.

```
87 candidates
 ├─ 42 rejected: edge < 5.0
 ├─ 15 rejected: < 2 signals
 ├─  8 rejected: quality < 85
 ├─  5 rejected: bench under
 ├─  3 rejected: UNDER edge 7+
 ├─  2 rejected: familiar matchup
 ├─  2 rejected: line jumped (UNDER)
 ├─  1 rejected: line dropped (UNDER)
 └─  5 passed → 3 selected (top by edge)
```

Could be a funnel chart, sankey diagram, or just a styled list. The key is showing what got filtered and why.

Edge distribution bar: `[===3+===|==5+==|=7+=]` with counts.

Source: `filter_summary`, `candidates_summary.edge_distribution`

### Section 4: Subset Performance Table

Sortable table of all subsets with rolling hit rates.

| Subset | 7d HR | 7d N | 14d HR | 14d N | 30d HR | 30d N | Trend |
|--------|-------|------|--------|-------|--------|-------|-------|
| best_bets | 71.4% | 7 | 66.7% | 18 | 70.0% | 40 | → |
| edge_5_plus | 66.7% | 12 | 68.2% | 22 | 70.0% | 50 | ↑ |

- Trend arrow: compare 7d to 30d. ↑ if 7d > 30d + 5, ↓ if 7d < 30d - 5, → otherwise.
- Color-code HR: green >= 60%, yellow 52-60%, red < 52%
- Sortable by any column. Default: sort by 30d HR descending.
- N < 10 shown in muted text (low confidence)

Source: `subset_performance` array

### Section 5: Model & Signal Health

Two side-by-side panels.

**Models (left):**

| Model | State | 7d HR | 14d HR | 7d N | Age |
|-------|-------|-------|--------|------|-----|
| catboost_v9 | HEALTHY | 62.5% | 59.1% | 48 | 3d |
| catboost_v12... | WATCH | 55.2% | 57.8% | 45 | 16d |

- State badge: green=HEALTHY, yellow=WATCH, orange=DEGRADING, red=BLOCKED
- Age badge: green/yellow/red as above

**Signals (right):**

| Signal | Regime | 7d HR | Season HR | 7d N |
|--------|--------|-------|-----------|------|
| combo_he_ms | HOT | 100% | 94.9% | 3 |
| high_edge | HOT | 75.0% | 66.7% | 12 |
| 3pt_bounce | COLD | 40.0% | 74.9% | 5 |

- Regime badge: green=HOT, gray=NORMAL, blue=COLD
- Sort by regime (HOT first), then by 7d HR

Source: `model_health`, `signal_health`

---

## Per-Date Deep Dive: `admin/picks/{date}.json`

For historical debugging, a separate per-date file exists with ALL candidates (not just selected picks).

**URL:** `v1/admin/picks/{date}.json`

Add a date picker or "browse history" link on the admin dashboard that loads this file for any past date. Shows the full candidate list with `selected: true/false` flag, quality scores, and edge values.

This is the "why did/didn't player X get picked on date Y?" debugging tool.

---

## Implementation Notes

- **Auth:** Firebase Auth, Google provider, email allowlist. ~30 min to set up.
- **No public nav link:** The `/admin` route exists but isn't linked from the public nav. Bookmark it.
- **Responsive:** Not critical — admin is laptop/desktop use. But if it works on tablet, bonus.
- **Refresh:** Manual page refresh to re-fetch dashboard.json. No auto-polling needed.
- **Dev toggle:** The existing raw model name dev toggle could live here too, consolidating all admin tools under one route.
