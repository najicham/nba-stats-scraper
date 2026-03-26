# Multi-Sport Frontend — Frontend Plan

*Created: Session 488 (2026-03-25)*
*Repo: /home/naji/code/props-web*

## Approach: Sport Tabs on `/best-bets`

Add NBA | MLB pill switcher to the top of the existing Best Bets page. Same components, same layout — different data source and one additional stat label.

No new routes. No new pages. Upgrade path to `/best-bets/nba` and `/best-bets/mlb` routes exists if needed later.

## Changes Required

### 1. Extend TypeScript types

**File:** `src/lib/best-bets-types.ts`

Add optional `sport` field to `BestBetsPick`:
```typescript
export interface BestBetsPick {
  // ... existing fields unchanged ...
  sport?: "nba" | "mlb";   // Optional — NBA picks won't have this field initially
}
```

Add `Sport` type and MLB-specific context:
```typescript
export type Sport = "nba" | "mlb";

export interface BestBetsAllResponse {
  // ... existing fields unchanged ...
  sport?: Sport;   // Backend will include this in mlb/best-bets/all.json
}
```

### 2. Extend stat label function

**Files:** `src/components/best-bets/BetCard.tsx` and `src/components/best-bets/TodayPicksTable.tsx`

Both have a `statLabel()` function. Extract it to a shared util or just add `K`:

```typescript
// Before:
const labels: Record<string, string> = {
  PTS: "pts", REB: "reb", AST: "ast", "3PM": "3pm"
};

// After:
const labels: Record<string, string> = {
  PTS: "pts", REB: "reb", AST: "ast", "3PM": "3pm",
  K: "k",     // MLB strikeouts
  H: "h",     // MLB hits (future)
  ERA: "era",  // MLB ERA (future)
};
```

Best option: extract to `src/lib/stat-labels.ts` and import in both components. But adding `K: "k"` inline is fine for now — don't over-engineer.

### 3. Update API fetch function

**File:** `src/lib/best-bets-api.ts`

```typescript
// Before:
export async function fetchBestBetsAll(): Promise<BestBetsAllResponse> {
  return fetchBestBetsJson<BestBetsAllResponse>("best-bets/all.json");
}

// After:
export async function fetchBestBetsAll(sport: Sport = "nba"): Promise<BestBetsAllResponse> {
  const path = sport === "mlb"
    ? "mlb/best-bets/all.json"
    : "best-bets/all.json";
  return fetchBestBetsJson<BestBetsAllResponse>(path);
}
```

### 4. Add sport tab state to Best Bets page

**File:** `src/app/best-bets/page.tsx`

```typescript
// Add state at top of component:
const [sport, setSport] = useState<Sport>("nba");

// Re-fetch when sport changes:
useEffect(() => {
  fetchBestBetsAll(sport).then(setData);
}, [sport]);

// Add tab UI just below the page header, above RecordHero:
<SportTabs
  value={sport}
  onChange={setSport}
  tabs={[
    { value: "nba", label: "NBA", icon: "🏀" },
    { value: "mlb", label: "MLB", icon: "⚾" },
  ]}
/>
```

`SportTabs` can be a simple inline component — two pill buttons with active state styling. ~20 lines. No new component file needed unless it gets reused.

### 5. Disable player modal for MLB

**File:** `src/app/best-bets/page.tsx` (and `TodayPicksTable.tsx`)

The player click modal opens a Tonight-page player profile. No such profile exists for MLB pitchers.

```typescript
// Pass a no-op handler for MLB:
<TodayPicksTable
  picks={data.today}
  onPlayerClick={sport === "mlb" ? () => {} : openPlayerModal}
/>
```

Or disable the click entirely on the row when `sport === "mlb"`. The simplest approach: pass `null` and let the table conditionally render the player name as non-clickable text.

### 6. Update proxy cache config

**File:** `src/app/api/proxy/[...path]/route.ts`

The proxy has explicit TTL mapping by path prefix. Add MLB:

```typescript
// In getCacheMaxAge() or equivalent:
if (path.startsWith("mlb/best-bets")) return 5 * 60;  // 5 min (same as nba)
if (path.startsWith("mlb/results"))   return 24 * 60 * 60; // 24h
if (path.startsWith("mlb/picks"))     return 5 * 60;
```

### 7. "No picks" state for MLB

If MLB has no picks today (off-season, rainout, etc.), the `today[]` array will be empty. `TodayPicksTable` doesn't handle this — it'll just render an empty table with no rows. Add a simple empty state:

```typescript
// In TodayPicksTable or page.tsx:
if (picks.length === 0) {
  return (
    <div className="text-secondary text-sm text-center py-8">
      {sport === "mlb"
        ? "No MLB picks today"
        : "No picks for today's games"}
    </div>
  );
}
```

## What Does NOT Need to Change

- `RecordHero.tsx` — record windows (season/month/week/last_10) are fully generic
- `WeeklyHistory.tsx` — week/day/pick structure is fully generic
- `BetCard.tsx` — aside from stat labels, renders OVER/UNDER/WIN/LOSS generically
- Direction rendering — OVER/UNDER works for all sports
- Matchup format — `TEAM vs OPPONENT` works for all sports
- Streak display — generic
- Ultra pick logic — MLB picks won't have `is_ultra: true` so it just won't show

## Implementation Order

1. `best-bets-types.ts` — add `Sport` type and `sport?` field (5 min)
2. `best-bets-api.ts` — add `sport` param to fetch (5 min)
3. `BetCard.tsx` + `TodayPicksTable.tsx` — add `K: "k"` to stat labels (2 min)
4. `page.tsx` — add sport tab state + re-fetch + no-op player click for MLB (30 min)
5. `route.ts` — add mlb/ cache TTLs (5 min)
6. Test with real MLB data from GCS

Total frontend work: ~1 hour once backend is publishing.

## Design Notes

### Sport tab visual

```
┌─────────────────────────────────┐
│  [🏀 NBA]  [⚾ MLB]             │  ← pill tabs, active = filled
│                                 │
│  Season: 60.3%  Week: ...       │  ← RecordHero (same component)
│                                 │
│  Gerrit Cole   O 6.5 k          │  ← Pick row (same component)
│  NYY @ BOS     7:05 PM ET       │
└─────────────────────────────────┘
```

MLB picks show "k" (strikeouts) instead of "pts". Everything else is identical.

### Player names

NBA: "LeBron James" (full name, displayed as-is)
MLB: "Gerrit Cole" (pitcher name, displayed as-is)

Same field, no change needed.

### Record hero for MLB

NBA shows season record starting Nov 1. MLB season starts March 27. The `record.season` window in `all.json` will be computed from the MLB season start date by the backend. The frontend just displays whatever numbers it gets — no change needed.

## Future Scope (not in this project)

- `/best-bets/nba` and `/best-bets/mlb` separate routes
- MLB "Tonight" page (starting lineups, pitcher matchups)
- MLB player profiles
- Sport switcher in global nav/header
- MLB live grading
- Additional MLB stats (ERA, WHIP, H, BB)
