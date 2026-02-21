# Admin Dashboard — Frontend Review & Feedback

**Reviewer:** Frontend (Claude Code session)
**Reviewing:** `03-ADMIN-DASHBOARD-SPEC.md`
**Date:** 2026-02-21

---

## Verdict: Spec is solid. Ship it as-is with a few small requests.

The two-file split (`dashboard.json` + `admin/picks/{date}.json`) is correct. The schema maps cleanly to the 5 UI sections. Below is specific feedback organized by priority.

---

## 1. Confirmed: Build it in the main frontend at `/admin`

We already have Firebase Auth wired up (`useAuth`, `AuthModal`, `UserMenu` all exist). Adding an email allowlist guard on a hidden route is trivial — maybe 20 lines of code. A separate monitoring site would mean duplicating the component library, theme, and deploy pipeline for a page only one person uses. Not worth it.

**Frontend will handle:**
- Route guard: redirect to `/best-bets` if not authenticated or not on the allowlist
- No nav link — admin bookmarks the URL
- Reuse existing theme, layout shell, and component primitives

---

## 2. `dashboard.json` schema — small requests

### 2a. Add `champion_model_state` to the top level

The status bar needs the champion model's state without hunting through `model_health[]`. Saves frontend from having to match `best_bets_model` against `model_health[].system_id`.

```jsonc
{
  "best_bets_model": "catboost_v9",
  "champion_model_state": "HEALTHY",  // ← add this
  ...
}
```

Alternatively, guarantee that `model_health[0]` is always the champion. Either works — just document which one.

### 2b. Add `losses` to subset performance windows

Currently each window has `wins`, `total`, `hr`. Adding `losses` explicitly avoids `total - wins` math in the frontend and keeps it consistent with the `BestBetsRecord` shape used elsewhere.

```jsonc
"7d": { "wins": 5, "losses": 2, "total": 7, "hr": 71.4 }
```

Low priority — frontend can compute it, but consistency is nice.

### 2c. Add a `subset_label` (display name) to `subset_performance`

`subset_id` values like `"edge_5_plus"` or `"combo_he_ms"` are fine for internal use but need a human-readable label in the table. Either:
- Add `"label": "Edge 5+"` to each entry, OR
- Provide a one-time mapping object somewhere (could be in `dashboard.json` or a separate `admin/subsets.json`)

If the set of subsets is stable and small (~16), frontend can hardcode the mapping. Just confirm the full list of `subset_id` values so we can build it.

### 2d. Confirm `filter_summary.rejected` keys are stable

The frontend will build a styled funnel list from these keys. If new filter types get added (or renamed), the frontend needs to handle unknown keys gracefully. Two options:
- **Option A (preferred):** Backend guarantees the key set is stable and documents additions in a changelog. Frontend hardcodes display names and descriptions.
- **Option B:** Backend includes a `display_name` and `description` for each filter in the payload. More flexible but more payload.

Current keys and our planned display names for reference:
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

If a new key appears that we don't recognize, we'll render it as the raw key name. Just flag us when new filters are added.

---

## 3. `admin/picks/{date}.json` — one request

### 3a. Include that date's `filter_summary` and `candidates_summary`

The spec says this file has "ALL candidates with `selected: true/false`". If it also includes that date's filter funnel and edge distribution, we can render the full admin dashboard for any historical date — not just today. This is the "why was the funnel tighter on Feb 10?" debugging use case.

```jsonc
{
  "date": "2026-02-10",
  "generated_at": "...",
  "candidates": [ ... ],           // all candidates with selected flag
  "filter_summary": { ... },       // same shape as dashboard.json
  "candidates_summary": { ... }    // same shape as dashboard.json
}
```

If this is already planned, great. If not, it's a nice-to-have — the primary use case (browsing individual candidates) works without it.

---

## 4. No concerns

These parts of the spec are good as-is, no changes needed:

- **Schema shape overall** — clean, flat, easy to type in TypeScript
- **Two-file split** — `dashboard.json` for today's glance, `picks/{date}.json` for deep dives. Correct separation.
- **Payload size** — 20-50KB for `dashboard.json` is fine. Even `picks/{date}.json` with 87 candidates won't exceed 100KB.
- **5-minute cache** — matches our existing proxy behavior for `best-bets/` prefix
- **`signal_health` as an object (keyed by signal name)** — fine, easy to iterate with `Object.entries()`
- **`model_health` as an array** — fine, small list, no need for a map

---

## 5. Implementation plan (frontend side)

Once the backend ships `dashboard.json`, frontend will:

1. Add TypeScript types for the admin schema
2. Add fetch function (`fetchAdminDashboard()`)
3. Build `/admin` page with 5 sections matching the spec
4. Add Firebase email allowlist route guard
5. Wire up date picker for historical `picks/{date}.json` deep dive

Estimated: one session to build, one to polish. No blockers on the frontend side — we can start as soon as `dashboard.json` is live (even with sample/mock data).
