# Frontend Update — Voided/DNP Picks

**Date:** 2026-02-22 (Session 330)
**Scope:** `all.json` schema change — voided picks now distinguishable from pending

---

## Problem

6 picks in the season history were for players who **Did Not Play** (DNP). The grading pipeline correctly voids them, but the API was sending them with `result: null` and `actual: null` — identical to pending (ungraded) picks. This made the frontend show "100 of 106 picks graded", implying 6 picks are awaiting results when they'll actually never be graded.

## What Changed in `all.json`

### Top-level counts

**Before:**
```json
{
  "total_picks": 106,
  "graded": 100
}
```

**After:**
```json
{
  "total_picks": 100,
  "graded": 100,
  "voided": 6
}
```

- `total_picks` now **excludes** voided picks (sportsbook convention — voided bets don't count)
- `voided` is a new optional field, present only when > 0
- `graded` is unchanged (still counts picks with a WIN/LOSS result)
- When all games are final: `graded` should equal `total_picks`

### Pick-level changes

**Before (DNP pick):**
```json
{
  "player": "Joel Embiid",
  "team": "PHI",
  "opponent": "NYK",
  "direction": "OVER",
  "line": 28.5,
  "edge": 5.2,
  "actual": null,
  "result": null
}
```

**After (DNP pick):**
```json
{
  "player": "Joel Embiid",
  "team": "PHI",
  "opponent": "NYK",
  "direction": "OVER",
  "line": 28.5,
  "edge": 5.2,
  "actual": null,
  "result": "VOID",
  "void_reason": "DNP"
}
```

- `result` now has 4 possible values: `"WIN"` | `"LOSS"` | `"VOID"` | `null`
- `void_reason` is a new optional field, present only when `result === "VOID"`. Currently always `"DNP"` (future: could include `"POSTPONED"`, `"CANCELLED"`)
- `actual` remains `null` for voided picks (player didn't play, no score)

### Day-level changes

**Before (day with only a DNP pick):**
```json
{
  "date": "2026-02-12",
  "status": "pending",
  "record": { "wins": 0, "losses": 0, "pending": 1 }
}
```

**After:**
```json
{
  "date": "2026-02-12",
  "status": "void",
  "record": { "wins": 0, "losses": 0, "pending": 0, "voided": 1 }
}
```

- `status` now has 5 possible values: `"sweep"` | `"split"` | `"miss"` | `"pending"` | `"void"`
  - `"void"` means all picks that day were voided (no actionable picks)
- `record.voided` is a new optional field, present only when > 0
- `record.pending` no longer counts voided picks — only genuinely ungraded picks

**Mixed day example (3 graded + 1 DNP):**
```json
{
  "date": "2026-02-11",
  "status": "split",
  "record": { "wins": 3, "losses": 2, "pending": 0, "voided": 2 }
}
```

## Frontend Display Recommendations

### Pick cards

When `result === "VOID"`:
- Show a **"DNP" badge** (gray/muted) instead of WIN/LOSS
- The direction pill (OVER/UNDER) and line should still be visible but **dimmed/muted** — the pick existed but was voided
- Don't show actual points (there are none)
- Don't count toward the day's W-L record
- Consider a brief explanation: "Player did not play — pick voided" or just "DNP" as a compact label

Suggested visual treatment:
```
┌──────────────────────────────────────────────────────┐
│  3   Joel Embiid                    OVER 28.5 pts    │  ← dimmed
│      PHI vs NYK                     Edge: 5.2        │
│                                                       │
│      DNP — Pick voided                               │  ← gray badge
└──────────────────────────────────────────────────────┘
```

### Hero / record section

No changes needed — the `record` object already excludes voided picks (they have no `prediction_correct` and were never counted in wins/losses).

### History accordion

- Days with `status: "void"` can be shown with a gray indicator and "All picks voided" or similar
- The `record.voided` count can optionally be shown: "3-2 (1 DNP)"
- Voided picks within a mixed day can be shown at the bottom, dimmed

### Total picks display

If you currently show "X of Y graded", this should now work correctly:
- `total_picks` (100) and `graded` (100) → "100 of 100 graded"
- Optionally: "100 of 100 graded (6 voided)" if you want to show the void count

## TypeScript Type Updates

```typescript
// Pick result now includes VOID
type PickResult = 'WIN' | 'LOSS' | 'VOID' | null;

// Pick type addition
interface Pick {
  // ... existing fields ...
  result: PickResult;
  void_reason?: 'DNP';  // present only when result === 'VOID'
}

// Day status now includes void
type DayStatus = 'sweep' | 'split' | 'miss' | 'pending' | 'void';

// Day record addition
interface DayRecord {
  wins: number;
  losses: number;
  pending: number;
  voided?: number;  // present only when > 0
}

// Top-level addition
interface AllJson {
  // ... existing fields ...
  total_picks: number;  // now excludes voided
  graded: number;
  voided?: number;  // present only when > 0
}
```

## Current Data

The 6 voided picks are:

| Date | Player | Team | Reason |
|------|--------|------|--------|
| Feb 12 | Lauri Markkanen | UTA | DNP |
| Feb 11 | Joel Embiid | PHI | DNP |
| Feb 11 | OG Anunoby | NYK | DNP |
| Feb 10 | OG Anunoby | NYK | DNP |
| Jan 30 | Austin Reaves | LAL | DNP |
| Jan 26 | Deni Avdija | POR | DNP |

All are players who were predicted pre-game but didn't play (injury scratches). This happens ~1-2 times per week in the NBA.
