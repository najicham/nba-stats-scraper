# Admin Dashboard Spec — playerprops.io/admin

**Status:** Final spec. Updated with frontend review feedback (Session 319).

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
  "champion_model_state": "HEALTHY",    // shortcut for status bar

  // ── MODEL HEALTH ─────────────────────────────────────────────
  // All active models with decay state, hit rates, and training details
  "model_health": [
    {
      "model_id": "catboost_v9",
      "family": "v9_mae",
      "state": "HEALTHY",              // HEALTHY | WATCH | DEGRADING | BLOCKED | INSUFFICIENT_DATA
      "is_production": true,           // champion model flag
      "enabled": true,
      "hr_7d": 62.5,                   // 7-day rolling hit rate (edge 3+)
      "hr_14d": 59.1,
      "hr_30d": 61.0,
      "n_7d": 48,                      // picks graded in window
      "n_14d": 93,
      "n_30d": 180,
      "days_since_training": 3,
      "training_start": "2026-01-06",  // what data the model saw
      "training_end": "2026-02-05",
      "eval_mae": 4.83,               // evaluation MAE at training time
      "eval_hr_edge3": 66.7,          // evaluation hit rate (edge 3+) at training
      "feature_count": 33,
      "loss_function": "RMSE"          // or "Quantile" for quantile models
    },
    {
      "model_id": "catboost_v9_q43_train1102_0125",
      "family": "v9_q43",
      "state": "INSUFFICIENT_DATA",
      "is_production": false,
      "enabled": true,
      "hr_7d": 55.2,
      "hr_14d": 57.8,
      "hr_30d": 62.6,
      "n_7d": 12,
      "n_14d": 28,
      "n_30d": 115,
      "days_since_training": 25,
      "training_start": "2025-11-02",
      "training_end": "2026-01-25",
      "eval_mae": null,
      "eval_hr_edge3": 62.6,
      "feature_count": 33,
      "loss_function": "Quantile"
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
  // All subsets with rolling HR across 3 windows + display label
  "subset_performance": [
    {
      "subset_id": "best_bets",
      "label": "Best Bets",
      "7d":  { "wins": 5, "losses": 2, "total": 7,  "hr": 71.4 },
      "14d": { "wins": 12, "losses": 6, "total": 18, "hr": 66.7 },
      "30d": { "wins": 28, "losses": 12, "total": 40, "hr": 70.0 }
    },
    {
      "subset_id": "ultra_high_edge",
      "label": "Ultra High Edge",
      "7d":  { "wins": 8, "losses": 4, "total": 12, "hr": 66.7 },
      "14d": { "wins": 15, "losses": 7, "total": 22, "hr": 68.2 },
      "30d": { "wins": 35, "losses": 15, "total": 50, "hr": 70.0 }
    }
    // ... ~39 subsets total
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

| Model | Family | State | 7d/14d/30d HR | 7d N | Age | Trained On | MAE | Loss |
|-------|--------|-------|---------------|------|-----|------------|-----|------|
| catboost_v9 | v9_mae | HEALTHY | 62.5/59.1/61.0 | 48 | 3d | Jan 6 - Feb 5 | 4.83 | RMSE |
| catboost_v9_q43... | v9_q43 | INSUFF | 55.2/57.8/62.6 | 12 | 25d | Nov 2 - Jan 25 | — | Quantile |

- State badge: green=HEALTHY, yellow=WATCH, orange=DEGRADING, red=BLOCKED, gray=INSUFFICIENT_DATA
- Age badge: green (<7d), yellow (7-14d), red (>14d)
- `is_production: true` row highlighted or starred
- Training dates show what data window the model learned from

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

For historical debugging, a separate per-date file with ALL candidates + filter funnel.

**URL:** `v1/admin/picks/{date}.json`

```jsonc
{
  "date": "2026-02-10",
  "generated_at": "...",
  "picks": [ ... ],                     // selected picks with full metadata
  "total_picks": 3,
  "candidates": [                       // ALL predictions with selected flag
    {
      "player": "LeBron James",
      "player_lookup": "lebron_james",
      "team": "LAL",
      "direction": "OVER",
      "line": 27.5,
      "edge": 5.2,
      "quality_score": 95.0,
      "selected": true
    }
  ],
  "total_candidates": 87,
  "candidates_summary": {              // same shape as dashboard.json
    "total": 87,
    "edge_distribution": { "total": 87, "edge_3_plus": 24, "edge_5_plus": 10, "edge_7_plus": 3, "max_edge": 8.2 }
  },
  "filter_summary": {                  // same shape as dashboard.json
    "total_candidates": 87,
    "passed_filters": 5,
    "rejected": { "edge_floor": 42, "signal_count": 15, ... }
  }
}
```

Add a date picker or "browse history" link on the admin dashboard that loads this file for any past date. Enables the "why was the funnel tighter on Feb 10?" debugging use case — full filter funnel + all candidates for any historical date.

---

## Implementation Notes

- **Auth:** Firebase Auth, Google provider, email allowlist. ~30 min to set up.
- **No public nav link:** The `/admin` route exists but isn't linked from the public nav. Bookmark it.
- **Responsive:** Not critical — admin is laptop/desktop use. But if it works on tablet, bonus.
- **Refresh:** Manual page refresh to re-fetch dashboard.json. No auto-polling needed.
- **Dev toggle:** The existing raw model name dev toggle could live here too, consolidating all admin tools under one route.

## Stable Key Sets

### `filter_summary.rejected` keys (stable — Option A)

New filters may be added ~1-2x per month. Backend will flag additions. Frontend should render unknown keys as raw key name as fallback.

| Key | Display Name |
|-----|-------------|
| `edge_floor` | Edge < 5.0 |
| `signal_count` | < 2 qualifying signals |
| `quality_floor` | Feature quality < 85 |
| `bench_under` | Bench player UNDER |
| `under_edge_7plus` | UNDER with edge 7+ |
| `familiar_matchup` | 6+ games vs opponent |
| `line_jumped_under` | UNDER + line jumped 2+ pts |
| `line_dropped_under` | UNDER + line dropped 2+ pts |
| `blacklist` | Player blacklisted (HR < 40%) |
| `confidence` | Low confidence |
| `anti_pattern` | Anti-pattern detected |

### `subset_id` values (~39 total, semi-stable)

Each subset has a `label` field in the payload. Use that for display. Full mapping maintained in `shared/config/subset_public_names.py`. New subsets are added when new models are trained (~monthly).
