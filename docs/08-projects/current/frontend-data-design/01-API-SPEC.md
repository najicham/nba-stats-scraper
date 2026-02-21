# Frontend Data Design — API Specification

Session 319 · 2026-02-21

## Two Audiences

| Audience | URL | Purpose |
|----------|-----|---------|
| **End user** | `playerprops.io` | Simple, confidence-inspiring, no jargon |
| **Admin** | Internal | Full metadata, all subsets, debugging |

---

## End User Endpoints

### `v1/best-bets/today.json` (NEW — Session 319)

Clean picks for today. Strips internal metadata.

```jsonc
{
  "date": "2026-02-21",
  "generated_at": "2026-02-21T16:00:00Z",
  "algorithm_version": "v319_...",
  "record": {
    "season": { "wins": 92, "losses": 32, "pct": 74.2, "total": 124 }
  },
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
      "angles": [
        "High-conviction edge (5.2 pts above line)",
        "Season OVER heavy (77% HR)"
      ]
    }
  ],
  "total_picks": 3
}
```

**Cache:** 300s · **Source:** `signal_best_bets_picks` table

### `v1/best-bets/record.json` (existing)

Season/month/week W-L record + streak info.

### `v1/best-bets/history.json` (existing)

All graded picks grouped by week/day for calendar and history views.

---

## Admin Endpoints

### `v1/admin/picks/{date}.json` (NEW — Session 319)

Full metadata for debugging. Includes all candidates, not just top picks.

```jsonc
{
  "date": "2026-02-21",
  "generated_at": "...",
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
      "angles": ["..."],
      "warnings": [],
      "matched_combo": "combo_he_ms",
      "combo_classification": "SYNERGISTIC",
      "combo_hit_rate": 94.9,
      "model_agreement": 3,
      "agreeing_models": ["catboost_v9", "catboost_v9_q43_..."],
      "consensus_bonus": 0.05,
      "source_model": "catboost_v9",
      "source_family": "v9_mae",
      "n_models_eligible": 3,
      "champion_edge": 5.2,
      "direction_conflict": false,
      "algorithm_version": "v319_...",
      "filter_summary": "{\"total_candidates\": 87, ...}",
      "actual": null,
      "result": null
    }
  ],
  "total_picks": 3,
  "candidates": [
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
  "edge_distribution": {
    "total": 87,
    "edge_3_plus": 24,
    "edge_5_plus": 10,
    "edge_7_plus": 3,
    "max_edge": 8.2
  }
}
```

**Cache:** 3600s · **Source:** `signal_best_bets_picks` + `player_prop_predictions`

### Existing Admin Endpoints

| Endpoint | Purpose |
|----------|---------|
| `v1/subsets/performance.json` | All subsets with rolling HR |
| `v1/systems/signal-health.json` | Per-signal HOT/COLD/NORMAL regime |
| `v1/systems/model-health.json` | Model state + blocked banner |
| `v1/signal-best-bets/{date}.json` | Full pick metadata per date |

---

## Frontend Layout Recommendations

### End User — "Best Bets" Page

**Hero:** Season record banner
```
92-32 (74.2%) Season  |  18-15 (54.5%) Feb  |  W2 streak
```

**Main:** Today's picks (or "No qualifying picks today")
- Player, team, opponent, direction, line, edge
- 1-2 pick angles as human-readable text

**History:** Month calendar grid + weekly collapsible groups
- Green/yellow/red/gray day cells
- Click day → modal with picks + results

### Admin — Dashboard

**Top:** Subset performance table (all subsets, sortable)
**Middle:** Per-date pick explorer with full metadata
**Bottom:** Signal health matrix (16 signals × 3 timeframes)

---

## Data File Sizes

| File | Pattern | Size |
|------|---------|------|
| `best-bets/today.json` | Per-day | 2-5 KB |
| `signal-best-bets/{date}.json` | Per-day | 5-15 KB |
| `admin/picks/{date}.json` | Per-day | 10-30 KB |
| `best-bets/record.json` | Aggregate | ~1 KB |
| `best-bets/history.json` | Aggregate | 50-200 KB |
| `subsets/performance.json` | Aggregate | ~10 KB |
