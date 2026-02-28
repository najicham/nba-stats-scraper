# Frontend: Add game_time to Trends Tonight Cards

**Date:** 2026-02-28
**Backend:** Deployed (pending export)
**Endpoint:** `GET /v1/trends/tonight.json`

---

## What Changed

Each object in the `trends[]` array has a `tonight` field. A new `game_time` field has been added:

```json
{
  "tonight": {
    "status": "scheduled",
    "opponent": "TOR",
    "home": true,
    "game_time": "2026-02-28T19:30:00-05:00",
    "min": null,
    "pts": null
  }
}
```

### Field Details

| Field | Type | Description |
|-------|------|-------------|
| `game_time` | `string \| null` | ISO 8601 timestamp with ET offset (`-05:00` EST / `-04:00` EDT). `null` if time unavailable. |

The offset reflects Eastern Time as stored in `game_date_est` from the NBA schedule. All NBA game times are published in ET.

---

## Frontend Usage

Display game time alongside opponent on scheduled games:

```
vs TOR · 7:30 PM ET          (scheduled)
vs TOR · Q3 5:42             (in_progress — use status field, ignore game_time)
vs TOR · Final               (final — use status field, ignore game_time)
```

### Parsing Example (TypeScript)

```typescript
function formatGameTime(tonight: TrendTonight): string {
  if (tonight.status !== 'scheduled' || !tonight.game_time) {
    return '';
  }
  const dt = new Date(tonight.game_time);
  return dt.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short',
  });
  // → "7:30 PM ET"
}
```

To display in Pacific Time instead:

```typescript
dt.toLocaleTimeString('en-US', {
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'America/Los_Angeles',
  timeZoneName: 'short',
});
// → "4:30 PM PT"
```

---

## Type Update

Add `game_time` to the tonight object type:

```typescript
interface TrendTonight {
  status: 'scheduled' | 'in_progress' | 'final';
  opponent: string;
  home: boolean;
  game_time: string | null;  // ← NEW
  min: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
  fg: string | null;
  fg_pct: number | null;
  three_pt: string | null;
  three_pct: number | null;
  ft: string | null;
  plus_minus: number | null;
}
```

---

## Backward Compatibility

- `game_time` is a new additive field — existing code ignoring it will not break.
- The field is nullable, so always check for `null` before formatting.
- All other fields in `tonight` remain unchanged.
