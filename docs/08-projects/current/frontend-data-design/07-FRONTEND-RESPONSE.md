# Frontend Response to Prompt Review

**Date:** 2026-02-22 (responding to Session 329 prompt)
**Scope:** Best Bets page, picks data, admin dashboard

---

## Overall Assessment

The prompt is well-structured and the `all.json` schema documentation is accurate. The ASCII mockups, design principles, and anti-patterns ("What NOT to Build") are all useful. Below are specific corrections, missing fields, and data requests — focused on the picks pipeline and admin dashboard.

---

## 1. `all.json` Schema — Fields the Prompt Misses

The prompt's `all.json` example is close but incomplete. Here's what the frontend actually types and consumes:

### Missing from the example

| Field | Type | Where It's Used | Notes |
|-------|------|-----------------|-------|
| `game_time` on picks | `string \| null` | Not displayed yet, but typed | Could show "7:00 PM ET" on pick cards — is this populated? |
| `ultra_tier` on picks | `boolean` | Ultra badge on pick cards, gold border | The prompt mentions "if first angle starts with ULTRA BET" as the detection heuristic, but we actually have a dedicated boolean field. Which is canonical? |
| `last_10` in `record` | `{ wins, losses, pct }` | RecordHero component | The prompt's example shows `last_10` in the record block but the frontend types it as optional. Is it always present? |
| `pending` in record windows | `number` | Displayed in history day records | The prompt example omits `pending` from `BestBetsRecord` — is it always 0 at the season/month level? |
| `total` in record windows | `number` | Shown in various places | The prompt shows `total` in season record but not month/week — are all windows guaranteed to have it? |
| `algorithm_version` | `string` | Not displayed on public pages (correct per "What NOT to Build") | The prompt's example includes it — confirming it's in the JSON but intentionally hidden? |

### The `ultra_tier` question is important

The prompt says: *"If first angle starts with 'ULTRA BET:' — this is a high-confidence pick."*

But the backend also sends `ultra_tier: true` as a dedicated field. The frontend currently checks `ultra_tier` (the boolean), not the angle text. **Can we standardize on `ultra_tier` being the source of truth?** Parsing angle strings is fragile. If you ever reword the angle text, the frontend detection breaks.

---

## 2. `all.json` — Data Requests for Upcoming Frontend Work

### 2a. Pick-level fields we could use

| Proposed Field | Why | Priority |
|----------------|-----|----------|
| `confidence` | We show edge but not confidence. The admin JSON has it. Could display as a subtle bar or badge on pick cards. | Low — edge works fine for now |
| `model_agreement` | "3 of 3 models agree" is compelling social proof for bettors. The admin JSON has this. | Medium |
| `signal_count` | Could show as "4 signals aligned" beneath angles. | Low |

**Not asking for these to be added now** — just flagging that if we want to make pick cards richer later, these fields already exist in the admin JSON and could be promoted to the public schema.

### 2b. Ultra summary in `record`

The prompt's performance table shows Ultra Bets at 25-8 (75.8%). The frontend could display this on the Best Bets page as a secondary stat, but `all.json` doesn't include an ultra-specific record window. Would it be feasible to add:

```jsonc
"ultra_record": {
  "wins": 25,
  "losses": 8,
  "pct": 75.8,
  "total": 33,
  "over": { "wins": 17, "losses": 2, "pct": 89.5 },
  "under": { "wins": 8, "losses": 6, "pct": 57.1 }
}
```

This would let us show "Ultra Bets: 75.8% HR" as a premium stat on the hero section. Currently we'd have to iterate all weeks and count `ultra_tier` picks manually on the client, which is wasteful and may not match the backend's count.

---

## 3. Admin Dashboard — Major Update

The prompt's admin section describes a flat 6-section layout. **We just redesigned this into a 4-tab pipeline view.** Here's the current state so the prompt can be updated:

### New tab structure

| Tab | Contents | Key Component |
|-----|----------|---------------|
| **Overview** | Pipeline funnel (5-step: Models → Candidates → Edge 5+ → Best Bets → Ultra), picks summary or no-picks explanation | `OverviewTab.tsx` |
| **Models** | Model candidates grid + model health table (grouped by family) | `ModelsTab.tsx` |
| **Picks & Filters** | Subset filter pills + picks table + filter funnel (rejection reasons + edge distribution) | `PicksTab.tsx` |
| **Performance** | Subset performance table + signal health table + ultra gate progress card | `PerformanceTab.tsx` |

### Pipeline funnel — what it needs from the API

The funnel renders these 5 steps from existing `dashboard.json` fields:

```
[N Models] → [N Candidates] → [N Edge 5+] → [N Best Bets] → [N Ultra]
```

Derived from:
- Models enabled: `model_health.filter(m => m.enabled).length`
- Candidates: `sum(model_candidates_summary[].total_candidates)`
- Edge 5+: `sum(model_candidates_summary[].edge_5_plus)`
- Best Bets: `today_picks.length`
- Ultra: `today_picks.filter(p => p.ultra_tier).length`

**Bottleneck detection**: first step where count drops to 0 after a nonzero step gets highlighted yellow. Today's example: Models=8, Candidates=135, Edge 5+=0 → "Edge 5+" is the bottleneck.

This all works with existing fields. No new API changes needed.

### Ultra gate card — data questions

The `ultra_gate` field in `dashboard.json` has `target_n` and `target_hr` as optional fields on each segment. **Are these always populated?** If not, the progress bars degrade gracefully (just show W-L and HR without targets), but it'd be nice to always have them.

Also: `ultra_gate.backtest_end` — is this the date the backtest data goes up to? Used as a label like "Backtest through Feb 20". Confirming interpretation.

---

## 4. Admin `dashboard.json` — Schema Gaps

### Fields the frontend normalizes / defaults

The admin API fetch (`admin-api.ts`) does defensive normalization:

```typescript
today_picks: raw.today_picks ?? raw.picks ?? []
model_candidates_summary: raw.model_candidates_summary ?? []
ultra_count: raw.ultra_count ?? 0
ultra_gate: raw.ultra_gate   // optional, no default
```

**Questions:**
- Is `today_picks` vs `picks` a legacy rename? Can we drop the `raw.picks` fallback?
- Is `model_candidates_summary` ever absent in production, or is this just defensive coding from early development?
- `ultra_count` — is this redundant with `today_picks.filter(p => p.ultra_tier).length`? The frontend doesn't use `ultra_count` directly anymore (the pipeline funnel counts ultra picks from the array). Can we deprecate it?

### Missing: pipeline metadata

The funnel would benefit from a small metadata object so we don't have to derive everything:

```jsonc
"pipeline_summary": {
  "models_enabled": 8,
  "total_candidates": 135,
  "edge_5_plus": 0,
  "best_bets": 0,
  "ultra": 0,
  "max_edge": 4.9,
  "bottleneck": "edge_floor"  // or null if pipeline succeeded
}
```

This isn't blocking — the frontend derives all of this today — but it would:
1. Be a single source of truth (no risk of frontend counting differently)
2. Allow the `bottleneck` field to carry backend-side logic (e.g., "model_blocked" vs "edge_floor" vs "pipeline_not_run") rather than the frontend guessing
3. Make the funnel render from a flat object instead of aggregating arrays

**Priority: Low.** Nice-to-have for future accuracy, not needed now.

---

## 5. Prompt Corrections for the Best Bets Page

### The page already exists and works

The prompt reads like a greenfield build spec. The Best Bets page (`/best-bets`) is fully implemented with:
- `RecordHero` component (season record, streak, best streak, total picks)
- `BetCard` component (rank, player, direction pill, edge, angles, result)
- `WeeklyHistory` component (expandable weeks → days → picks)
- Empty state: "No picks today — we only bet when the edge is there."
- Ultra detection via `ultra_tier` boolean
- Pull-to-refresh
- Background refresh on tab visibility change

If the prompt is meant to describe existing behavior to a new session, it should say "this page exists, here's how it works" rather than "build this."

### Nav is different from what the prompt says

The prompt says: `Best Bets | History | About`

Actual nav:
- **Desktop header**: Best Bets | Tonight | Trends
- **Mobile bottom nav**: Bets | Tonight | Trends

There is no "History" or "About" in the main nav (About exists as `/about` but isn't in primary nav).

---

## 6. `status.json` — Quick Note

The prompt documents `status.json` as optional. The frontend does fetch it — there's a `/status` page and a status dot in the header. The schema shown in the prompt matches what we consume. No issues here.

---

## Summary: Action Items for Backend

### Clarify (no code changes needed)
1. Is `ultra_tier` boolean the canonical source, or angle text parsing?
2. Is `ultra_count` in dashboard.json redundant / deprecatable?
3. Is `today_picks` vs `picks` a legacy rename we can drop the fallback for?
4. Is `game_time` populated on picks in `all.json`?
5. Are `target_n` / `target_hr` on ultra gate segments always populated?
6. Is `ultra_gate.backtest_end` the backtest data cutoff date?

### Nice-to-have data additions (non-blocking)
1. `ultra_record` in `all.json` — precomputed ultra season stats for the hero section
2. `pipeline_summary` in `dashboard.json` — flat object with funnel counts + bottleneck reason
3. `last_10` guaranteed present (or documented as optional)

### Prompt text corrections
1. Nav is "Best Bets | Tonight | Trends", not "Best Bets | History | About"
2. Admin dashboard is now a 4-tab pipeline view, not a flat 6-section layout
3. Best Bets page already exists — prompt should reference existing implementation
4. `ultra_tier` field should be documented in the pick schema example (it's missing from the `all.json` example)
5. `algorithm_version` is in the JSON but should be noted as "present but not displayed on public pages"
